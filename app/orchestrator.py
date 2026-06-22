"""
Оркестратор LLM-цикла. Заменяет backend/run_task — вместо WS-relay
к desktop вызывает executor.execute() напрямую (один процесс).

Импортирует SYSTEM_PROMPT, TOOL_DEFINITIONS, _build_system_prompt из
backend/main.py — чтобы не дублировать ~900 строк промпта.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable, Awaitable

import anthropic

# Все импорты из backend/desktop под уникальными именами — см. _imports.py
from _imports import (
    SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
    _build_system_prompt,
    MAX_ITERATIONS,
    MAX_TOOL_RESULT,
    CRITICAL_TOOLS,
    LOOP_DETECT_WINDOW,
    ToolExecutor,
    BslAtlasClient,
    _ConfigError,
)

# humanize_1c_error — общий для ops_runner и orchestrator
from ops_runner import humanize_1c_error

# Tool guards: жёсткий enforcement правил из SYSTEM_PROMPT.
# Блокирует deprecated tools, неправильные write_file, db_load без validate.
from tool_guards import check_tool_call, record_call

# Tools которые зовут 1С через PowerShell — их ошибки имеет смысл
# проводить через humanize_1c_error для понятного сообщения в UI.
_ONE_C_TOOL_PREFIXES = ("db_", "meta_", "cfe_")

log = logging.getLogger(__name__)


# Типы callback'ов для отделения оркестратора от транспорта (FastAPI/WS)
LogFn        = Callable[..., Awaitable[None]]   # (task_id, text, meta="", kind="step")
StatusFn     = Callable[[str, str], Awaitable[None]]        # (task_id, status)
DoneFn       = Callable[[str], Awaitable[None]]             # (task_id,)
ErrorFn      = Callable[[str, str], Awaitable[None]]        # (task_id, error_msg)


async def run_task(
    task_id: str,
    prompt: str,
    executor: ToolExecutor,
    client_cfg: dict,
    anthropic_api_key: str,
    on_log: LogFn,
    on_status: StatusFn,
    on_done: DoneFn,
    on_error: ErrorFn,
    on_iteration=None,
    on_ask_user=None,  # legacy: игнорируется, доступен только в orchestrator_sdk
    **_ignored,
):
    """
    Главный LLM-цикл. Логика 1:1 как в backend/run_task, но:
    - tool calls идут напрямую в executor.execute(), без WS;
    - события (log/status/done/error) отдаются через callback'и.

    on_iteration(current, total) — опциональный коллбек прогресса.
    """
    await on_status(task_id, "running")
    await on_log(task_id, "Задача принята, запускаю агента...", "")

    if not anthropic_api_key:
        await on_error(task_id, "ANTHROPIC_API_KEY не установлен")
        return

    # Лимит итераций — из конфига клиента, с дефолтом из backend
    max_iter = int(client_cfg.get("max_iterations") or MAX_ITERATIONS)

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": prompt}]

    # История tool calls текущей задачи — нужна guard'ам (например db_load
    # требует cfe_validate в истории). Записываем {tool, params, ok}.
    tool_history: list[dict] = []

    # Сигнатуры последних итераций — для loop detection.
    # signature = детерминированный хеш всех tool_use вызовов одной итерации.
    import hashlib
    recent_signatures: list[str] = []

    def _iteration_signature(content_blocks) -> str:
        sig_parts = []
        for block in content_blocks:
            if getattr(block, "type", None) == "tool_use":
                sig_parts.append([
                    block.name,
                    json.dumps(block.input or {}, sort_keys=True, ensure_ascii=False),
                ])
        if not sig_parts:
            return ""  # пустая итерация (только текст) — не считаем
        raw = json.dumps(sig_parts, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    try:
        for iteration in range(max_iter):
            # Прогресс итерации в UI (если backend подключил callback)
            if on_iteration is not None:
                try:
                    await on_iteration(iteration + 1, max_iter)
                except Exception:
                    pass  # не валим задачу из-за UI-события
            # Маркер итерации не пишем — он шумит в логе. Если задача
            # упрётся в лимит итераций, увидим это в финальной ошибке.
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8096,
                system=[{
                    "type": "text",
                    "text": _build_system_prompt(client_cfg),
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Логируем текстовые блоки ответа отдельно от tool-шагов.
            # UI отрендерит их как markdown, без сетки exec-row.
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    await on_log(task_id, block.text, "", kind="text")

            if response.stop_reason == "end_turn":
                await on_log(task_id, "✓ Задача выполнена", "")
                await on_done(task_id)
                return

            if response.stop_reason != "tool_use":
                await on_log(task_id, f"Неожиданная остановка: {response.stop_reason}", "")
                break

            # ── Loop detection: 3 одинаковых tool_use итерации подряд ──
            sig = _iteration_signature(response.content)
            if sig:
                recent_signatures.append(sig)
                if len(recent_signatures) > LOOP_DETECT_WINDOW:
                    recent_signatures = recent_signatures[-LOOP_DETECT_WINDOW:]
                if (
                    len(recent_signatures) == LOOP_DETECT_WINDOW
                    and len(set(recent_signatures)) == 1
                ):
                    # Узнаём какие именно tools и параметры зациклились
                    tool_names = sorted({
                        b.name for b in response.content
                        if getattr(b, "type", None) == "tool_use"
                    })
                    msg = (
                        f"Обнаружено зацикливание: tool(s) {', '.join(tool_names)} "
                        f"вызвался {LOOP_DETECT_WINDOW} раз подряд с одинаковыми параметрами. "
                        "Задача остановлена, чтобы не сжигать токены впустую.\n"
                        "\n"
                        "Возможные причины:\n"
                        "• LLM не имеет нужного инструмента и пробует обходной путь\n"
                        "• Параметры неверные, но LLM их не корректирует\n"
                        "• Внешняя система (1С, BSL Atlas) возвращает одинаковую ошибку\n"
                        "\n"
                        "Что попробовать:\n"
                        "• Переформулируй задачу конкретнее\n"
                        "• Проверь что нужные пути в Настройках валидны\n"
                        "• Открой лог выше и посмотри что отвечал инструмент"
                    )
                    await on_log(task_id, "⚠ Зацикливание обнаружено", "loop")
                    await on_error(task_id, msg)
                    return

            # Выполняем tool calls — НАПРЯМУЮ через executor
            tool_results: list[dict] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input: dict[str, Any] = dict(block.input) if block.input else {}
                params_preview = json.dumps(tool_input, ensure_ascii=False)[:120]
                await on_log(task_id, f"→ {tool_name}", params_preview)

                # ── Tool guard: жёсткий enforcement правил перед executor ──
                guard_msg = check_tool_call(tool_name, tool_input, tool_history)
                if guard_msg is not None:
                    await on_log(task_id, f"⚠ {tool_name}: GUARD BLOCKED", guard_msg[:200])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": guard_msg,
                        "is_error": True,
                    })
                    tool_history.append(record_call(tool_name, tool_input, ok=False))
                    continue

                try:
                    raw_result = await executor.execute(tool_name, tool_input)
                    result_text = str(raw_result)[:MAX_TOOL_RESULT]
                    await on_log(
                        task_id,
                        f"← {tool_name}: OK",
                        f"{len(result_text)} симв.",
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
                    # Особое отслеживание cfe_validate: успех ли (для guard на db_load).
                    # Скилл возвращает текст с "errors:" если были ошибки.
                    ok_for_history = True
                    if tool_name == "cfe_validate":
                        low = result_text.lower()
                        # Эвристика: если в выводе есть "error" но НЕ "0 errors" / "no errors" — считаем failed
                        has_errors_mention = "error" in low
                        has_zero_errors = "0 errors" in low or "no errors" in low or "errors: 0" in low
                        if has_errors_mention and not has_zero_errors:
                            ok_for_history = False
                    tool_history.append(record_call(tool_name, tool_input, ok=ok_for_history))
                except Exception as exc:
                    raw_msg = str(exc)
                    # Для 1С-инструментов превращаем raw stderr в понятный текст.
                    # Для остальных (bsl_*, file ops) оставляем как есть.
                    if tool_name.startswith(_ONE_C_TOOL_PREFIXES):
                        err_msg = humanize_1c_error(raw_msg, client_cfg)
                    else:
                        err_msg = raw_msg

                    await on_log(task_id, f"← {tool_name}: ОШИБКА", err_msg[:300])

                    if tool_name in CRITICAL_TOOLS:
                        raise RuntimeError(
                            f"[{tool_name}] завершился с ошибкой — задача прервана.\n\n{err_msg}"
                        )

                    # Для не-критических tools — отдаём LLM, чтобы он попробовал
                    # другой подход. Передаём ОРИГИНАЛЬНЫЙ текст (LLM-у нужны
                    # технические детали), но в UI пользователь видит human-version.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"ERROR: {raw_msg}",
                        "is_error": True,
                    })
                    tool_history.append(record_call(tool_name, tool_input, ok=False))

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Превышен лимит итераций
        await on_error(
            task_id,
            f"Превышен лимит итераций ({max_iter}). "
            f"Задача оказалась сложнее запланированного. "
            f"Увеличь max_iterations в config.json или разбей задачу на части."
        )

    except asyncio.CancelledError:
        # Пользователь нажал «Стоп». Публикуем понятное сообщение об ошибке.
        # shield нужен потому что cancel мог сработать прямо в момент on_error —
        # мы хотим довести сообщение до UI и БД, даже если cancel «продолжает».
        log.info("Задача %s отменена пользователем", task_id)
        try:
            await asyncio.shield(on_error(task_id, "Отменено пользователем"))
        except Exception:
            pass
        # raise НЕ делаем — позволяем wrapper'у завершиться нормально

    except Exception as exc:
        log.exception("Ошибка выполнения задачи %s", task_id)
        await on_error(task_id, str(exc))
