"""
agenter/app/orchestrator_sdk.py — orchestrator на Claude Agent SDK.

Заменяет ручной agent loop из orchestrator.py. Использует SDK для:
  • Многошагового agent reasoning (как Claude Code)
  • Built-in tools: Read / Write / Edit / Bash / Grep / Glob / TodoWrite / Agent
  • MCP servers: BSL Atlas (HTTP) + наш agenter SDK MCP (PowerShell skills + platform_docs)
  • Hooks: PreToolUse → tool_guards для жёсткого enforcement
  • Streaming событий → on_log callbacks → WebSocket в UI

Старый orchestrator.py остаётся рядом на время миграции — переключение
делается в app/main.py одним import'ом.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from _imports import (
    SYSTEM_PROMPT,
    _build_system_prompt,
    MAX_ITERATIONS,
    ToolExecutor,
    BslAtlasClient,
)
from ops_runner import humanize_1c_error
from sdk_tools import make_agenter_tools, AGENTER_TOOL_NAMES
# Структурная трассировка прогона (Фаза 2 логирования). Только наблюдение —
# emit() неблокирующий (queue.put), новых await в горячий путь не вносит.
from run_trace import get_tracer, RunTrace, calc_cost as _trace_cost
# Фаза 1 / Шаг 1.1 — детектор циклов (net-new, параллельно клетке).
from loop_detector import LoopDetector, classify_error
# Фаза 1 / Шаг 1.2 — баланс-ledger (net-new). Дебет фактической стоимости задачи.
import ledger as _ledger
# Фаза 1 / Шаг 1.3 — денежный потолок (net-new). Pre-start gate + живой лимит.
import money_guard as _money
from tool_guards import (
    check_tool_call, record_call,
    _list_known_objects,
    _list_known_objects_cached,
    invalidate_known_objects_cache,
)
# MAX_ASK_USER_PER_TASK и SDK_HARD_CAP_TURNS — для собственного счётчика turns,
# который отделяет «полезные» turns от ask_user-уточнений (см. ADR-016).
from _imports import MAX_ASK_USER_PER_TASK, SDK_HARD_CAP_TURNS

log = logging.getLogger(__name__)


# ── Sprint 4 S4.4: загрузка/продвижение стадий — СНЯТО (Фаза 4 разворота) ────
# Здесь жили _load_current_stage_from_db / _advance_stage_in_db — чтение и
# авто-продвижение стадий task_stages. Стадийная машина обездвижена ещё в
# Фазе 3 (stage-dispatch снят), в Фазе 4 удалена целиком: движок планирует
# свободно нативным TodoWrite (в Фазе 5 снят и совещательный plan_task),
# стадии больше не гейтят и не персистятся.


# ── Sprint 2 hotfix-4: обход Windows-лимита cmdline (32767 символов) ────────
#
# Проблема (выявлено 2026-05-16): для больших задач (L4 + interactive_mode +
# resumed session + memory_md) наш `--append-system-prompt` достигает 14K
# символов. Базовый SYSTEM_PROMPT 21K. Итого по cmdline ~35K + флаги →
# Windows CreateProcess() обрывается с FileNotFoundError, SDK переинтерпретирует
# как «Claude Code not found at: ...» — обманчивая ошибка про .exe.
#
# Решение: monkey-patch SubprocessCLITransport._build_command. Если значение
# `--append-system-prompt` длиннее порога — записываем в temp-файл и
# заменяем на `--append-system-prompt-file <path>` (claude.exe этот флаг
# поддерживает с давних пор, см. claude.exe --help). Лимит cmdline тогда
# уже не упирается.
#
# Патч идемпотентный — повторное применение игнорируется.

_SP_FILE_THRESHOLD = 4000  # запас от 32k cmdline, остаётся ~28k на остальные флаги
_CMDLINE_PATCH_APPLIED = False


def _patch_sdk_for_long_system_prompt() -> None:
    """Монопатчит SDK так, чтобы длинные --append-system-prompt и
    --system-prompt передавались через временный файл (-file вариант флага).
    Безопасен для повторного вызова.
    """
    global _CMDLINE_PATCH_APPLIED
    if _CMDLINE_PATCH_APPLIED:
        return
    try:
        from claude_agent_sdk._internal.transport.subprocess_cli import (
            SubprocessCLITransport,
        )
    except Exception as e:
        log.warning("SDK monkey-patch: модуль не найден (%s) — пропуск", e)
        return

    _orig = SubprocessCLITransport._build_command

    def _patched(self):
        import tempfile as _tf
        cmd = _orig(self)
        # Идём по cmd, ищем длинные значения у --append-system-prompt
        # и --system-prompt; заменяем на -file вариант.
        out: list[str] = []
        i = 0
        replaced_count = 0
        while i < len(cmd):
            flag = cmd[i]
            if (flag in ("--append-system-prompt", "--system-prompt")
                    and i + 1 < len(cmd)
                    and isinstance(cmd[i + 1], str)
                    and len(cmd[i + 1]) >= _SP_FILE_THRESHOLD):
                value = cmd[i + 1]
                tmp = _tf.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False,
                    encoding="utf-8", prefix="agenter_sp_",
                )
                try:
                    tmp.write(value)
                finally:
                    tmp.close()
                # claude.exe поддерживает --append-system-prompt-file / --system-prompt-file
                file_flag = flag + "-file"
                out.extend([file_flag, tmp.name])
                replaced_count += 1
                i += 2
                continue
            out.append(flag)
            i += 1
        if replaced_count:
            log.info(
                "SDK cmdline patch: вынес %d system-prompt значен(ие/ия) в файл — "
                "обход Windows 32k cmdline limit",
                replaced_count,
            )
        return out

    SubprocessCLITransport._build_command = _patched
    _CMDLINE_PATCH_APPLIED = True
    log.info("Patched SubprocessCLITransport._build_command for long system_prompt")


# Применяем патч сразу при импорте модуля — до первого создания
# ClaudeSDKClient'а в run_task.
_patch_sdk_for_long_system_prompt()


# ── Sprint 1 Step 1: SDK silence watchdog ───────────────────────────────────
# Если Anthropic-сервер замолчал в середине стрима (SSE оборвалось, network
# stall, серверный hang) — `async for message in client.receive_response()`
# будет ждать вечно. Без таймаута это превращается в «UI крутит спиннер
# часами». Заворачиваем итерацию в watchdog с per-event тайм-аутом.
SDK_SILENCE_TIMEOUT_SEC = 300  # 5 минут без событий → задача признаётся зависшей


class SDKSilenceTimeout(Exception):
    """Anthropic SDK перестал присылать события дольше чем
    SDK_SILENCE_TIMEOUT_SEC. Обрабатывается в run_task как фатальная ошибка
    задачи (на UI уходит понятное сообщение, не CancelledError).
    """


async def _with_silence_watchdog(stream, timeout: float):
    """Async-iter wrapper: оборачивает каждый `__anext__` в
    `asyncio.wait_for(..., timeout)`. При тайм-ауте кидает
    SDKSilenceTimeout. На нормальной итерации работает прозрачно.

    Используется в _stream_messages для отлова зависаний на стороне
    Anthropic API без явного таймаута со стороны SDK.
    """
    it = stream.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(it.__anext__(), timeout=timeout)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            raise SDKSilenceTimeout(
                f"Anthropic SDK не прислал ни одного события за {int(timeout)}s "
                f"подряд. Скорее всего, оборвалось SSE-соединение или сервер "
                f"перегружен. Задача прервана как зависшая."
            )


# Типы коллбеков — те же что у старого orchestrator, чтобы app/main.py не менять
LogFn = Callable[..., Awaitable[None]]
StatusFn = Callable[[str, str], Awaitable[None]]
DoneFn = Callable[[str], Awaitable[None]]
ErrorFn = Callable[[str, str], Awaitable[None]]


# Tools, ошибки которых критичны (как в старом orchestrator)
_CRITICAL_TOOLS = {"mcp__agenter__db_dump", "mcp__agenter__db_load"}
_ONE_C_TOOL_PREFIXES = (
    "mcp__agenter__db_",
    "mcp__agenter__meta_",
    "mcp__agenter__cfe_",
)

# Допустимые built-in tools — то что нужно для 1С coding-agent.
# WebFetch/WebSearch исключены (не нужны в self-contained сценарии).
_BUILTIN_ALLOWED = [
    "Read", "Write", "Edit",
    "Glob", "Grep",
    "Bash",
    "TodoWrite",
    "Agent",
]

# Полный список разрешённых tools: built-in + наши custom + все MCP-серверы.
# Wildcards по имени mcp__<server>__* — все tools любого зарегистрированного
# в config.mcp_servers HTTP-сервера автоматически разрешены.
_ALLOWED_TOOLS = _BUILTIN_ALLOWED + AGENTER_TOOL_NAMES + [
    "mcp__bsl_atlas__*",        # BSL Atlas — структурный поиск (всегда)
    "mcp__syntax_check__*",     # SyntaxCheckServer (Docker, comol/1c_syntaxcheck_mcp)
    "mcp__help_platform__*",    # HelpSearchServer  (Docker, comol/1c_help_mcp)
    "mcp__ssl_search__*",       # SSLSearchServer   (Docker, comol/mcp_ssl_server)
    # Sprint 1 Step 4 — дополнительные external MCP
    "mcp__forms_server__*",     # FormsServer       (Docker build, mcp-forms-server)
    "mcp__graph_metadata__*",   # Graph_metadata_search (Docker, comol/1c_graph_metadata + Neo4j)
]


# ── Фаза 5: нативные скиллы (gated, по умолчанию OFF) ────────────────────────
# SDK-опция `skills` (types.py) — контекст-фильтр: перечисленные скиллы движок
# видит НАТИВНО (через Skill tool), остальные скрыты из листинга и отклоняются.
# db-МУТАТОРЫ (запись в боевую БД) сознательно ИСКЛЮЧЕНЫ из нативного списка —
# они идут только через MCP-обёртку (там снапшот / apply-gate / биллинг) плюс
# защёлку прямой записи Фазы 3. Защёлка остаётся доп. рубежом: контекст-фильтр
# прячет скилл из листинга, но файлы на диске остаются доступны через Read/Bash
# (док SDK), поэтому периметр всё равно держит запись.
#
# Флаг native_skills_enabled по умолчанию OFF: включение `skills` задействует
# project-setting-source SDK, а рантайм-.claude пока содержит DEV-конфиг
# (CLAUDE.md с путями C:\BUFFER\ERP + settings.local.json с auto-allow прямого
# `db-load-xml … -UpdateDB` + SessionStart-hook). Включать ТОЛЬКО после чистой
# runtime-раскладки workspace (Фаза 7) и живого теста discovery — иначе риск
# затащить чужой контекст и пробить периметр. Не угадывать — проверять прогоном.
_DB_MUTATOR_SKILLS = frozenset({
    "db-load-cf", "db-load-dt", "db-load-git", "db-load-xml",
    "db-update", "db-run", "db-create",
})


def _discover_skills_dir(cwd: str, client_cfg: dict) -> "Path | None":
    """Каталог .claude/skills, который CLI найдёт walk-up'ом от cwd.

    Приоритет — явный client_cfg['skills_dir']; иначе подъём от cwd вверх."""
    sd = client_cfg.get("skills_dir")
    if sd and Path(sd).exists():
        return Path(sd)
    try:
        p = Path(cwd).resolve()
    except Exception:
        return None
    for cand in [p, *p.parents]:
        sk = cand / ".claude" / "skills"
        if sk.exists():
            return sk
    return None


def _compute_native_skills(cwd: str, client_cfg: dict) -> "list[str] | None":
    """Безопасный allowlist для SDK-опции `skills` (db-мутаторы исключены).

    None → каталог скиллов не найден: нативные скиллы не включаем (остаётся
    MCP-канал)."""
    sk_dir = _discover_skills_dir(cwd, client_cfg)
    if not sk_dir:
        return None
    names = sorted(
        d.name for d in sk_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )
    safe = [n for n in names if n not in _DB_MUTATOR_SKILLS]
    return safe or None


def _build_client_context(
    client_cfg: dict,
    memory_md: str = "",
    is_resumed_session: bool = False,
) -> str:
    """Build context block (расширение, префикс, пути) — то же что
    _build_system_prompt в старой версии делает. Добавим в system_prompt SDK.

    memory_md — содержимое agenter/data/<project_id>/MEMORY.md (если есть);
    инлайнится напрямую в системный промпт, чтобы агент видел его даже
    без явного Read tool.

    is_resumed_session — True если эта задача продолжает предыдущую
    Claude SDK сессию через resume. Меняет вводный блок промпта.
    """
    base = _build_system_prompt(client_cfg)
    # Дополнительные подсказки про built-in tools, которые LLM теперь имеет.
    sdk_addendum = """

═══════════════════════════════════════════════════════
 ЯЗЫК ОТВЕТОВ И МЫШЛЕНИЯ
═══════════════════════════════════════════════════════

ВАЖНО: общайся с пользователем ИСКЛЮЧИТЕЛЬНО на русском языке.
Это касается и финальных ответов, и thinking-блоков (твои внутренние
рассуждения «»). Никаких "The user wants...", "Let me check..." —
вместо них «Пользователь хочет...», «Сейчас проверю...».

Имена методов и объектов 1С, термины SDK/инструментов (PowerShell,
ChromaDB, MCP, JSON, BSL) — оставляй как есть (англоязычные имена кода
не переводим). Но все рассуждения, объяснения, планы — на русском.

═══════════════════════════════════════════════════════
 BUILT-IN TOOLS (от Claude Agent SDK)
═══════════════════════════════════════════════════════

Используй встроенные tools для общих операций:
  Read(file_path)              — прочитать ЛЮБОЙ файл (ext_src/, SCHEME/, и т.д.)
                                  пути абсолютные или относительно cwd
  Write(file_path, content)    — создать/перезаписать файл (только BSL/текстовые,
                                  для XML метаданных используй mcp__agenter__meta_*)
  Edit(file_path, old_str,     — точечная замена (как старый edit_file)
        new_str)
  Glob(pattern)                — найти файлы по glob паттерну
  Grep(pattern, path?)         — ripgrep по тексту (regex)
  Bash(command)                — выполнить shell-команду (для диагностики,
                                  запуска внешних утилит)
  TodoWrite(todos)             — структурированный план задачи (для multi-step)
  Agent(...)                   — делегировать подзадачу sub-agent'у

Эти tools НЕ требуют BSL Atlas индекса. Если bsl_* MCP возвращает пусто —
используй Grep по SCHEME напрямую.

НЕ ИСПОЛЬЗУЙ Bash для рутины: список файлов — это Glob, поиск по содержимому —
Grep, чтение файла — Read. `ls`, `cat`, `head` через Bash — нарушение CLAUDE.md
и лишняя медлительность. Bash оставь для случаев, когда нужно реально что-то
выполнить (запуск утилиты, проверка статуса процесса).

═══════════════════════════════════════════════════════
 КОГДА СПРОСИТЬ ПОЛЬЗОВАТЕЛЯ — tool ask_user
═══════════════════════════════════════════════════════

У тебя есть БЛОКИРУЮЩИЙ tool `mcp__agenter__ask_user(question, options?)`.
Он останавливает выполнение задачи и ждёт ответ юзера через модалку в UI.
Возвращает строку с ответом.

ВАЖНО ПРО БЮДЖЕТ:
  • Вызов ask_user НЕ тратит «эффективный» бюджет turns. Юзер не штрафует
    тебя за уточнения — спрашивай когда нужно.
  • НО: можно задать **максимум 5 ask_user в одной задаче** (защита от
    петли «ошибка→спрос→ответ→ошибка→спрос…»). После 5 PreToolUse hook
    заблокирует следующий ask_user — продолжишь сам или признаешь тупик.
  • Время ожидания юзера не тратит turns — юзер может думать сколько хочет.

КОГДА вызывать ask_user:
  1. Упёрся в неустранимое (то же действие повторилось с той же ошибкой 2+ раза)
     → СПРОСИ: «Я пытался X, получаю Y. Как продолжить?»
  2. Ключевое решение, которое нельзя угадать:
     • префикс расширения (если в ТЗ написано одно, в ext_src уже другое);
     • выбор между несколькими существующими справочниками;
     • политика именования (CamelCase vs ВерхнийРегистр);
     • противоречие в ТЗ.
  3. ТЗ требует объект, которого нет в SCHEME (возможно опечатка):
     → СПРОСИ список вариантов из bsl_metadatasearch или предложи создать.

КАК НЕ использовать ask_user:
  Тривиальное (выбор имени реквизита, который ясно следует из ТЗ).
  То, что можно проверить tool'ами (читать SCHEME, искать через bsl_*).
  Подтверждение каждого шага — это раздражает.

ПРАВИЛО ПОВТОРОВ: если tool вернул ошибку, и ты собираешься позвать тот же
tool с почти теми же параметрами — СТОП. Подумай:
  • Может ошибка указывает на структурное непонимание (не «формат», а суть)?
  • Может стоит проверить состояние через Read/Glob, а не угадывать?
  • Если действительно не знаешь, как разрулить — вызови ask_user.
Три подряд одинаковых tool-вызова с ошибкой = почти гарантированно зацикливание.

═══════════════════════════════════════════════════════
 ЗАВЕРШЕНИЕ ЗАДАЧИ
═══════════════════════════════════════════════════════

Жёсткого лимита по числу шагов (turn-budget) НЕТ — работай столько шагов,
сколько реально нужно для результата. Задачу может остановить только:
  • денежный потолок (исчерпан бюджет трат) — тогда заверши честным итогом;
  • детектор циклов (один и тот же вызов без прогресса) — смени подход;
  • твоё собственное штатное завершение, когда задача сделана.
Если работа прервалась на полпути — заверши финальным текстовым ответом:
что успел сделать (применённые изменения), что осталось, какие следующие
шаги предложить юзеру.

Лучше планируй: если задача огромная (15+ объектов) — раздели её на ФАЗЫ
с промежуточными db_load (см. ниже), чтобы каждая часть была атомарно
применена в БД и устойчива к обрыву.

═══════════════════════════════════════════════════════
 PRE-FLIGHT ОБЪЕКТОВ EXT_SRC
═══════════════════════════════════════════════════════

Pre-flight кэш known_objects ОБНОВЛЯЕТСЯ автоматически после каждого
успешного meta_compile/cfe_borrow/cfe_patch_method. Поэтому:
  • Создал АП_ФизическиеЛица через meta_compile → можешь сразу делать
    регистр с измерением `CatalogRef.АП_ФизическиеЛица`. Preflight его
    увидит на следующем шаге.
  • Если preflight всё-таки блокирует ссылку на свежий объект — значит
    предыдущий meta_compile НЕ создал объект (был is_error). Проверь
    через Read что файл реально появился в ext_src/.../Catalogs/.

Если preflight упорно отвергает то, что должно работать — это сигнал
вызвать ask_user, не повторять одно и то же.

═══════════════════════════════════════════════════════
 ФАЗЫ И КОММИТЫ (для больших задач)
═══════════════════════════════════════════════════════

ПРАВИЛО: для задач, затрагивающих 5 и более объектов конфигурации —
ОБЯЗАТЕЛЬНО разделяй задачу на фазы.

ФАЗА — это группа изменений, которая может быть атомарно применена
в БД через db_load. После применения фазы БД остаётся валидной
(нет orphan-ссылок, нет полу-доделанных документов).

Признаки правильно спланированной фазы:
  • 3-7 объектов внутри
  • Логически связаны (создал справочник → используй его в этой же фазе)
  • Зависимости РАЗРЕШЕНЫ внутри фазы (если регистр ссылается на справочник —
    оба в одной фазе)
  • Можно безопасно остановиться после неё (БД валидна)

ПЛАНИРОВАНИЕ. В начале большой задачи ОБЯЗАТЕЛЬНО создай план через TodoWrite:
  - Фаза 1: создание новых справочников (без зависимостей)
  - Фаза 2: создание регистров на этих справочниках
  - Фаза 3: заимствование документов + добавление реквизитов
  - Фаза 4: формы, проведение, отчёты

Маркер в начале строки TodoWrite = «граница фазы», после неё нужен commit.

ВЫПОЛНЕНИЕ ФАЗЫ:
  1. Делай все meta_*/cfe_*/edit_file этой фазы
  2. В КОНЦЕ ФАЗЫ обязательно: cfe_validate → db_load
  3. Только после успешного db_load переходи к следующей фазе

ЕСЛИ задача оборвалась посреди фазы N (деньги/цикл/ошибка) — фазы 1..N-1 уже
в БД (commit'нуты), фаза N осталась в ext_src/ как незавершённая. Юзер
продолжит её отдельной задачей.

ДЛЯ МАЛЕНЬКИХ ЗАДАЧ (1-4 объекта) — одна фаза, db_load в самом конце задачи.
TodoWrite в таких случаях необязателен.

ПРИМЕЧАНИЕ: успешный db_load автоматически детектируется системой как
«commit фазы». Тебе не нужно ничего объявлять явно — просто следуй паттерну
«meta_* → cfe_validate → db_load» в конце каждой фазы.

═══════════════════════════════════════════════════════
 КОНТИНУАЦИЯ СЕССИИ
═══════════════════════════════════════════════════════

Эта сессия может быть ПРОДОЛЖЕНИЕМ предыдущей задачи (auto-resume).
Если ты видишь, что в истории сообщений выше уже была работа — это значит:
  • Прошлая задача не завершилась (BUDGET / ошибка / пауза)
  • TodoWrite список из прошлой задачи доступен в твоей памяти
  • Файлы ext_src уже в том состоянии, до которого дошёл прошлый цикл
  • Фазы, которые ты успел committ'ить (db_load), уже в БД 1С

Когда юзер пишет «продолжай», «дальше», «теперь...» — это значит
ПРОДОЛЖЕНИЕ. Не начинай заново, не делай db_dump повторно (если ext_src
не менялся вручную), не переделывай уже committ'нутые фазы.

Если юзер сменил тему — это всё равно та же сессия (юзер сам нажмёт
«Новая задача» если ему нужен чистый контекст).

═══════════════════════════════════════════════════════
 ПАМЯТЬ ПРОЕКТА (MEMORY.md)
═══════════════════════════════════════════════════════

Файл: agenter/data/<project_id>/MEMORY.md — твоя долговременная память,
переживающая сброс сессии. Содержимое инлайнится в этот промпт автоматически.

ЧТО ЗАПИСЫВАТЬ (в конце задачи, через Edit/Write):
  Префиксы расширений (АП_, пгт_, ...)
  UUID часто используемых объектов (если узнал/сгенерировал)
  Принятые архитектурные решения проекта (почему так, а не иначе)
  Особенности проекта, не очевидные из ТЗ
  Неудачные подходы (чтобы не повторять)

ЧТО НЕ ЗАПИСЫВАТЬ:
  Тривиальное (в коде и так видно)
  Временное (одноразовые UUID, status конкретной задачи)
  Дублирование того, что уже есть выше в этом файле

ПРАВИЛО ОБЪЁМА: MEMORY.md должен оставаться компактным (< 100 строк).
Если разрастается — делай compact: объединяй похожие записи, удаляй устаревшие.
"""
    # Содержимое MEMORY.md инлайнится отдельным блоком ПОСЛЕ инструкции
    # как с ней работать. Это позволяет агенту даже без Read увидеть факты.
    if memory_md.strip():
        sdk_addendum += f"""

═══════════════════════════════════════════════════════
 MEMORY.md (текущее содержимое)
═══════════════════════════════════════════════════════

{memory_md.strip()}

═══════════════════════════════════════════════════════
"""

    # Если это resumed-сессия — даём агенту явную подсказку.
    # Это резервный канал поверх SDK-resume (сама история диалога приходит
    # из SDK, но напоминание полезно для случаев когда SDK потерял часть).
    if is_resumed_session:
        sdk_addendum += """

ВНИМАНИЕ: это ПРОДОЛЖЕНИЕ предыдущей сессии (auto-resume).
   История диалога с пользователем — выше. Учти что:
     • TodoWrite список из прошлой задачи может быть актуален
     • ext_src/ в состоянии, до которого дошёл прошлый цикл
     • Не повторяй уже сделанную работу
     • Не делай повторный db_dump если ничего не менялось вручную
"""

    # Sprint 3 S3.2: Multi-level workflow — разный объём дисциплины для разных
    # размеров задачи. memory bank pattern: чем больше задача, тем больше
    # структурного процесса. Маленькие — минимум churn, большие — proposal.
    task_level = client_cfg.get("task_level") or "L2"
    if task_level == "L1":
        sdk_addendum += """

═══════════════════════════════════════════════════════
 УРОВЕНЬ L1 — МАЛЕНЬКАЯ ЗАДАЧА
═══════════════════════════════════════════════════════

Задача распознана как простая (1-2 пункта, <500 символов, budget 50 turns).
TodoWrite НЕ нужен — сразу делай. Одна фаза = вся задача. db_load в конце.
"""
    elif task_level == "L2":
        sdk_addendum += """

═══════════════════════════════════════════════════════
 УРОВЕНЬ L2 — НЕБОЛЬШАЯ ЗАДАЧА
═══════════════════════════════════════════════════════

Задача распознана как средней простоты (3-5 пунктов или 500-2000 символов,
budget 80 turns). TodoWrite опционален, но полезен для 4+ шагов.
Обычно одна фаза, db_load в конце задачи.
"""
    elif task_level == "L3":
        sdk_addendum += """

═══════════════════════════════════════════════════════
 УРОВЕНЬ L3 — СРЕДНЯЯ ЗАДАЧА
═══════════════════════════════════════════════════════

Задача требует структуры (4-5 пунктов, budget 80 turns).
ОБЯЗАТЕЛЬНО TodoWrite на старте — это поможет не забыть шаги при context
shift. Используй 2-3 фазы (cfe_validate → db_load в конце каждой), чтобы
ext_src и БД не уходили в рассинхрон при ошибке посередине.
"""
    # L4 → spec-first блок ниже (он содержит всё что нужно для крупной задачи)

    # Sprint 2 S2.6: spec-first для больших задач (L4, ~120 turns budget).
    # Без этой директивы агент сразу лезет писать код и теряет контекст в
    # середине большой задачи. Жёсткое предписание дисциплинирует.
    if client_cfg.get("spec_first_required"):
        sdk_addendum += """

═══════════════════════════════════════════════════════
 БОЛЬШАЯ ЗАДАЧА (L4) — СПЛАНИРУЙ ЧЕРЕЗ TODOWRITE
═══════════════════════════════════════════════════════

Задача распознана как БОЛЬШАЯ (6+ пунктов или объём >2000 символов). Это L4 —
комплексная работа. Никаких стадий и обязательного «сначала plan_task» —
планируй нативно.

ПОТОК L4:

1. В начале построй план через TodoWrite — разбей ТЗ на пункты и сгруппируй
   их в ФАЗЫ (каждая фаза заканчивается cfe_validate → db_load, чтобы БД
   оставалась валидной и устойчивой к обрыву задачи). Поддерживай статусы
   пунктов актуальными по ходу работы.

2. Включай промежуточные коммиты, а не только финальный: после каждой
   логически замкнутой группы объектов — cfe_validate → db_load. Тогда при
   обрыве задачи фазы 1..N-1 уже применены в БД.

ТОПОЛОГИЯ РЕФЕРЕНСОВ (учитывай порядок, иначе pre-flight отвергнет ссылку):
  • Catalog.A создаётся ДО Document.B, если B имеет реквизит CatalogRef.A
  • Заимствование (cfe_borrow) перед правкой того же объекта (meta_edit)
  • BSL-модуль формы пишется ПОСЛЕ создания формы (ссылается на её элементы)
  • cfe_validate → db_load — точки коммита, разбивай ими большие группы
"""

    # Sprint 2 S2.8: интерактивный режим — пользователь явно попросил спрашивать.
    # Универсальный детект из промпта (см. main.py:_detect_interactive_intent).
    # Этот блок ПЕРЕОПРЕДЕЛЯЕТ дефолтную сдержанность ask_user именно для
    # данной задачи. Никакого hardcode под тип задачи — только реакция на
    # явный речевой паттерн в промпте.
    if client_cfg.get("interactive_mode"):
        sdk_addendum += """

═══════════════════════════════════════════════════════
 ИНТЕРАКТИВНЫЙ РЕЖИМ — ПОЛЬЗОВАТЕЛЬ ПРОСИТ СПРАШИВАТЬ (R19)
═══════════════════════════════════════════════════════

В промпте этой задачи пользователь явно дал понять, что хочет быть в курсе
неоднозначностей («спроси», «уточни», «при сомнениях», «не угадывай»,
«ask me», «clarify» и т.п.). Это ПЕРЕОПРЕДЕЛЯЕТ дефолтную сдержанность
с ask_user именно для этой задачи (для других задач — поведение прежнее).

Что меняется в поведении НА ЭТОЙ ЗАДАЧЕ:
  • Понижай порог обращения к ask_user. Любое существенное сомнение →
    короткий вопрос, а не угадывание по контексту.
  • Перед предположением о неоднозначном выборе (имя реквизита, тип данных,
    политика нумерации, какой именно из нескольких подходящих объектов
    использовать) — лучше спроси.
  • Перед тратой turns на обход PRE-FLIGHT / GUARD / повторяющейся ошибки —
    спроси, а не пытайся выкрутиться 5 раз.
  • Если ТЗ юзера допускает несколько разумных интерпретаций — выбери одну
    как «предлагаю по умолчанию», но СПРОСИ подтверждение перед делом.

Что НЕ меняется:
  • Лимит ask_user (5 на задачу) — не меняется. Не злоупотребляй —
    тривиальные вопросы по-прежнему недопустимы.
  • Сама шкала «тривиально vs существенно» — пересмотрена в эту сторону:
    если в обычном режиме что-то трактуется как «угадаю, очевидно из ТЗ»,
    в этом режиме — «не уверен на 100%, спрошу подтверждение».

Принцип: уважай явное требование пользователя. Он сам предупредил, что
готов отвечать на уточнения. Лучше потратить 1 turn на ask_user, чем 5 turns
на workaround неверного допущения.
"""

    return base + sdk_addendum


# ── Pre-tool-use hook = наш существующий tool_guards ────────────────────────


def _make_pre_tool_use_hook(
    tool_history: list[dict],
    on_log: LogFn,
    task_id: str,
    known_objects_ref: dict,
    turn_state: dict,
    client_cfg: dict | None = None,
    rt: RunTrace | None = None,
    tool_timing: dict | None = None,
    loop_detector: "LoopDetector | None" = None,
):
    """Создаёт PreToolUse hook, который применяет наши tool_guards.

    known_objects_ref — mutable container {"data": dict|None}, чтобы
    post-hook мог пересобирать кэш после meta_compile/cfe_borrow и
    pre-hook видел свежее состояние без пересоздания замыкания.

    Фаза 4: стадийная машина снята — pre-hook больше не читает current_stage
    и не делает whitelisting по kind стадии. Остался периметр (check_tool_call)
    + детектор циклов + лимит ask_user.

    turn_state — mutable {"effective": int, "ask_user": int}; считается
    post-hook'ом. Бизнес-лимит по числу turns (turn-cap) СНЯТ в Фазе 4 —
    здесь остался только лимит на ask_user:
      • если tool == ask_user и ask_user >= MAX_ASK_USER_PER_TASK →
        блокируем именно ask_user, остальные tools работают (агент может
        попробовать завершить задачу собственными силами).
    """

    async def hook(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        tool_name_full = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {}) or {}

        # SDK даёт имя вида "mcp__agenter__db_load" — приводим к старому
        # короткому имени для tool_guards (он понимает 'db_load').
        short_name = tool_name_full
        if tool_name_full.startswith("mcp__agenter__"):
            short_name = tool_name_full[len("mcp__agenter__"):]

        # Трассировка: штамп старта tool для расчёта длительности в post-hook.
        if tool_timing is not None and tool_use_id:
            tool_timing[tool_use_id] = time.monotonic()

        # ── Фаза 1 / Шаг 1.1: стоп по детектору циклов ────────────────
        # После Фазы 4 (turn-cap снят) это ОСНОВНОЙ ловец «застрял» — рядом
        # с money-cap («дорого»). Отклоняет ТОЛЬКО «застрявшую» сигнатуру
        # (после 2-го срабатывания детектора) — подталкивает к финалу;
        # остальные tools (вкл. ask_user) свободны.
        if loop_detector is not None and loop_detector.is_blocked(short_name, tool_input):
            loop_msg = (
                "LOOP STOP: этот вызов повторяется без прогресса и отклонён "
                "детектором циклов. Не повторяй его с теми же параметрами. "
                "Смени подход, спроси пользователя (ask_user) или заверши "
                "задачу честным итогом: что сделано, что застряло и почему."
            )
            if rt is not None:
                rt.emit("guard", {
                    "tool": short_name, "guard": "loop-detector",
                    "decision": "deny", "reason": loop_msg,
                }, level="WARN", status="deny")
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": loop_msg,
            }}

        # ── Фаза 4 разворота (СНЯТО): turn-cap «BUDGET EXHAUSTED» ──────
        # Здесь стоял жёсткий бизнес-лимит по числу «эффективных» turns
        # (`effective >= max_effective_turns` → блок ВСЕХ tools). Это был
        # последний грубый прут клетки: он обрывал задачу по числу шагов,
        # не глядя на реальную пользу/стоимость. Снят. Остановки теперь:
        #   • «дорого»  → money-cap (живой потолок по тратам, Шаг 4.1);
        #   • «застрял» → детектор циклов (Фаза 1, выше в этом hook);
        #   • абсолют   → SDK max_turns=sdk_hard_cap (аварийная страховка от
        #                 бесконечного цикла на уровне SDK, НЕ бизнес-потолок).
        # `max_effective_turns` больше не приходит в этот hook; значение всё
        # ещё считается в run_task для расчёта sdk_hard_cap и оценки резерва.

        # ── Лимит на количество ask_user в одной задаче ───────────────
        if short_name == "ask_user" and turn_state["ask_user"] >= MAX_ASK_USER_PER_TASK:
            ask_limit_msg = (
                f"ASK_USER LIMIT: в одной задаче можно задать максимум "
                f"{MAX_ASK_USER_PER_TASK} уточняющих вопросов, ты уже задал "
                f"{turn_state['ask_user']}. Дальше — реши самостоятельно "
                f"на основе уже полученных ответов, или заверши задачу с "
                f"описанием тупика."
            )
            await on_log(
                task_id,
                "ask_user: LIMIT EXCEEDED",
                f"{turn_state['ask_user']}/{MAX_ASK_USER_PER_TASK}",
            )
            tool_history.append(record_call(short_name, tool_input, ok=False))
            if rt is not None:
                rt.emit("guard", {
                    "tool": "ask_user", "guard": "ask-user-limit",
                    "decision": "deny",
                    "ask_user": turn_state["ask_user"],
                    "max_ask_user": MAX_ASK_USER_PER_TASK,
                    "reason": ask_limit_msg,
                }, level="WARN", status="deny")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": ask_limit_msg,
                }
            }

        # ── Периметр: check_tool_call (§0 / R7 / db_load-gate / защёлка БД) ─
        # Фаза 4: стадийные параметры убраны — клетки нет, диспетчеризации нет.
        guard_msg = check_tool_call(
            short_name, tool_input, tool_history,
            known_objects=known_objects_ref.get("data"),
        )
        if guard_msg:
            # Логируем блокировку в UI
            await on_log(task_id, f"{short_name}: GUARD BLOCKED", guard_msg[:200])
            tool_history.append(record_call(short_name, tool_input, ok=False))
            if rt is not None:
                rt.emit("guard", {
                    "tool": short_name, "guard": "tool-guards",
                    "decision": "deny",
                    "reason": guard_msg,
                }, level="WARN", status="deny")
            # Отказ через PreToolUse hook
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": guard_msg,
                }
            }
        if rt is not None:
            # Разрешение тоже фиксируем (DEBUG) — полная видимость guard-решений.
            rt.emit("guard", {
                "tool": short_name, "guard": "tool-guards", "decision": "allow",
            }, level="DEBUG", status="allow")
        return {}  # разрешить

    return hook


# Tools, которые могут добавить новые типы в ext_src (Catalog/Document/Enum/…).
# После их успешного выполнения preflight-кэш пересобирается, иначе следующий
# meta_compile со ссылкой на свежесозданный объект будет ложно заблокирован.
_TOOLS_THAT_AFFECT_KNOWN_OBJECTS = {"meta_compile", "cfe_borrow", "cfe_patch_method"}

# Модифицирующие tools — пишут в ext_src или БД. Для семантического исхода
# прогона (applied/staged/readonly) в run_end (Fix D).
_MODIFYING_TOOLS = {
    "meta_compile", "meta_edit", "cfe_borrow", "cfe_patch_method",
    "subsystem_edit", "form_compile", "form_edit", "db_update", "db_load",
}


def _extract_tool_result(tool_response: Any) -> tuple[str, bool]:
    """Достаёт (текст, is_error) из tool_response PostToolUse.

    ВАЖНО: реальный Claude Agent SDK кладёт tool_response как СПИСОК блоков
    `[{"type":"text","text":...}]` (а не dict {"content":[...]}). Прежний код
    ждал только dict → терял текст результата у ВСЕХ tools и не детектил
    ошибку (ok всегда True). Поддерживаем оба формата + строку.

    is_error: из явного флага (dict), типа блока, либо нашей конвенции `_err`
    (текст начинается с 'ERROR:')."""
    text = ""
    is_err = False
    blocks = None
    if isinstance(tool_response, list):
        blocks = tool_response
    elif isinstance(tool_response, dict):
        is_err = bool(tool_response.get("is_error") or tool_response.get("isError"))
        c = tool_response.get("content")
        if isinstance(c, list):
            blocks = c
        elif isinstance(c, str):
            text = c
    elif isinstance(tool_response, str):
        text = tool_response
    if blocks is not None:
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict):
                if b.get("text"):
                    parts.append(str(b["text"]))
                if b.get("type") == "error" or b.get("is_error"):
                    is_err = True
            elif isinstance(b, str):
                parts.append(b)
        text = "\n".join(parts)
    # Конвенция _err() в sdk_tools: текст ошибки начинается с 'ERROR:'
    if text.lstrip().startswith("ERROR:"):
        is_err = True
    return text, is_err


def _make_post_tool_use_hook(
    tool_history: list[dict],
    on_log: LogFn,
    task_id: str,
    known_objects_ref: dict,
    client_cfg: dict,
    turn_state: dict,
    on_phase_commit: Callable[[str, int], Awaitable[None]] | None = None,
    phase_state: dict | None = None,
    on_todos_update: Callable[[str, int, int], Awaitable[None]] | None = None,
    rt: RunTrace | None = None,
    tool_timing: dict | None = None,
    loop_detector: "LoopDetector | None" = None,
):
    """PostToolUse hook — записывает в history для будущих pre-checks
    (например db_load требует успешного cfe_validate в истории).

    Также пересобирает preflight-кэш known_objects после успешных tools,
    которые могут создавать новые объекты в ext_src (meta_compile,
    cfe_borrow). Без этого следующий meta_compile со ссылкой на только что
    созданный объект блокируется ложно (известная регрессия из лога
    2026-05-15: «Город Строка(50)» / «АП_ФизическиеЛица»).

    Ведёт turn_state — счётчик «полезных» turns против бюджета:
      effective инкрементируется на любом tool КРОМЕ ask_user
      ask_user инкрементируется только на ask_user
    Это даёт юзеру право уточнять задачу без «штрафа» по бюджету.

    Детектит фазы:
      Каждый успешный db_load = коммит очередной фазы. phase_state["committed"]
      инкрементируется, on_phase_commit(task_id, phase_index) вызывается —
      backend записывает в task_phases и шлёт WS-event."""

    async def hook(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        tool_name_full = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {}) or {}
        tool_response = input_data.get("tool_response", {})

        short_name = tool_name_full
        if tool_name_full.startswith("mcp__agenter__"):
            short_name = tool_name_full[len("mcp__agenter__"):]

        # Извлечение текста результата + флага ошибки. Реальный SDK кладёт
        # tool_response списком блоков — см. _extract_tool_result.
        result_text, is_error_flag = _extract_tool_result(tool_response)
        ok = not is_error_flag

        if short_name == "cfe_validate" and ok:
            low = result_text.lower()
            has_errors = "error" in low
            has_zero = "0 errors" in low or "no errors" in low or "errors: 0" in low
            if has_errors and not has_zero:
                ok = False

        tool_history.append(record_call(short_name, tool_input, ok=ok))

        # ── Трассировка: tool_call с полным input/response/ok/duration ────
        if rt is not None:
            dur_ms = None
            if tool_timing is not None and tool_use_id and tool_use_id in tool_timing:
                dur_ms = int((time.monotonic() - tool_timing.pop(tool_use_id)) * 1000)
            is_db_op = short_name in ("db_dump", "db_load")
            rt.emit("tool_call", {
                "tool": short_name,
                "input": tool_input,
                "result": result_text,
                "ok": ok,
                "is_db_op": is_db_op,
            }, level="INFO", status=("ok" if ok else "error"), duration_ms=dur_ms)
            if not ok:
                # Отдельное error-событие (контролируемый тип) — для фильтрации.
                # «Реакция» агента (повтор/ask_user/стоп) видна в следующих
                # событиях llm_call/tool_call этого же прогона.
                human = humanize_1c_error(result_text, client_cfg or {}) \
                    if any(p in result_text for p in ("PowerShell", "1cv8", "db_")) \
                    else result_text
                rt.emit("error", {
                    "source": "tool", "tool": short_name,
                    "message": human[:600], "is_db_op": is_db_op,
                }, level="ERROR", status="error")

        # ── Счётчик turns (эффективные vs ask_user) ───────────────────
        # ask_user не «штрафует» — юзер должен иметь право уточнить
        # задачу без потери бюджета. Все остальные tool calls считаются
        # за полезную работу, даже неудачные (это тоже расход API/времени).
        if short_name == "ask_user":
            turn_state["ask_user"] += 1
        else:
            turn_state["effective"] += 1
        # Фаза 4 разворота: soft-warn «бюджет turns на 80%» СНЯТ вместе с
        # turn-cap — он создавал то же шаговое давление «скоро заблокирую».
        # turn_state["effective"] остаётся для трассировки/метрик прогона.

        # ── Пересборка preflight-кэша после успешных «структурных» tools ──
        if ok and short_name in _TOOLS_THAT_AFFECT_KNOWN_OBJECTS:
            try:
                before_count = sum(
                    len(v) for v in (known_objects_ref.get("data") or {}).values()
                )
                # Sprint 2 S2.3: инвалидируем модульный кэш (его читают другие
                # задачи через _list_known_objects_cached), пересобираем
                # per-task ref свежим сканом.
                invalidate_known_objects_cache()
                fresh = _list_known_objects_cached(
                    client_cfg.get("scheme_path"),
                    client_cfg.get("ext_src_path"),
                )
                known_objects_ref["data"] = fresh
                after_count = sum(len(v) for v in (fresh or {}).values()) if fresh else 0
                if after_count != before_count:
                    delta = after_count - before_count
                    sign = "+" if delta > 0 else ""
                    await on_log(
                        task_id,
                        f"Pre-flight кэш обновлён: {after_count} объектов ({sign}{delta} после {short_name})",
                        "",
                    )
            except Exception as e:
                log.warning("Не удалось пересобрать preflight-кэш: %s", e)

        # ── Phase commit detection (успешный db_load = граница фазы) ──
        # ЛЮБОЙ успешный db_load трактуется как «фаза N применена в БД».
        # Это намеренно автоматизировано — агенту не нужно явно объявлять
        # фазы, достаточно следовать паттерну meta_* → cfe_validate → db_load.
        # phase_state хранит счётчики ИМЕННО в этой run_task; backend
        # синхронизирует их с SQLite через on_phase_commit callback.
        if ok and short_name == "db_load" and phase_state is not None:
            phase_state["committed"] = int(phase_state.get("committed", 0)) + 1
            phase_index = phase_state["committed"]
            # Краткое название фазы — из текста ответа агента или дефолт.
            # Точный текст приходит позже отдельным WS event'ом из backend.
            await on_log(
                task_id,
                f"Фаза {phase_index} применена в БД",
                f"db_load #{phase_index} успешен",
            )
            if on_phase_commit is not None:
                try:
                    await on_phase_commit(task_id, phase_index)
                except Exception as e:
                    log.warning("on_phase_commit failed: %s", e)

        # ── Sprint 2 S2.7: TodoWrite-attestation ──────────────────────────
        # При каждом успешном TodoWrite парсим список пунктов и считаем
        # незавершённые (pending / in_progress). Сохраняем снимок через
        # on_todos_update — backend кладёт в БД, _compute_final_state
        # использует этот сигнал как самый надёжный.
        #
        # Универсально: работает для любых задач — простых (где TodoWrite
        # не вызывался → колонка остаётся NULL → не влияет на логику) и
        # для больших L4 (где остаются pending → partial вместо ложного
        # applied).
        if ok and short_name == "TodoWrite" and on_todos_update is not None:
            todos = (tool_input or {}).get("todos")
            if isinstance(todos, list):
                total = len(todos)
                incomplete = sum(
                    1 for t in todos
                    if isinstance(t, dict)
                    and str(t.get("status", "")).lower() in ("pending", "in_progress")
                )
                try:
                    await on_todos_update(task_id, incomplete, total)
                except Exception as e:
                    log.warning("on_todos_update failed: %s", e)
                # Лёгкая отметка в exec-логе для прозрачности
                if total > 0:
                    completed = total - incomplete
                    await on_log(
                        task_id,
                        f"TodoWrite: {completed}/{total} завершено",
                        f"осталось {incomplete} в pending/in_progress" if incomplete else "всё выполнено",
                    )

        # ── Фаза 5: plan_task снят целиком (планирование — нативный TodoWrite).
        # Стадийная машина убрана ещё в Фазе 4; здесь раньше была plan-трассировка
        # совещательного plan_task — теперь не нужна. Повторный db_dump ловит
        # single-shot guard 2A/2B, застой — детектор циклов ниже.

        # ── Фаза 1 / Шаг 1.1: детектор циклов ─────────────────────────────
        # Вызывается на КАЖДЫЙ завершённый tool. Возвращает модели мягкий
        # разворот (steer) или честный стоп (stop). Жёсткий deny повторов —
        # в pre-hook через loop_detector.is_blocked(). После Фазы 4 — основной
        # ловец застоя (клетки больше нет).
        if loop_detector is not None:
            explicit_progress = bool(ok and short_name == "db_load")
            err_cls = None if ok else classify_error(result_text)
            decision = loop_detector.record(
                short_name, tool_input, ok,
                explicit_progress=explicit_progress, error_class=err_cls)
            act = decision.get("action")
            if act in ("steer", "stop"):
                reason = decision.get("reason", "")
                if rt is not None:
                    rt.emit("loop_suspected", {
                        "tool": short_name, "stage": act, "reason": reason,
                    }, level="WARN", status=("deny" if act == "stop" else "warn"))
                await on_log(
                    task_id,
                    "Похоже на зацикливание" if act == "steer" else "Зацикливание — стоп",
                    reason,
                )
                if act == "steer":
                    ctx = (
                        "ВНИМАНИЕ (детектор циклов): " + reason + ". Ты повторяешься "
                        "без прогресса. СМЕНИ подход: проверь состояние через "
                        "Read/Glob/bsl_*, либо задай уточняющий вопрос ask_user, либо "
                        "заверши задачу честным итогом. НЕ повторяй тот же вызов с теми "
                        "же параметрами."
                    )
                else:
                    ctx = (
                        "СТОП (детектор циклов): " + reason + ". Повтор не помогает. "
                        "Прекрати повторять это действие. Заверши задачу честным "
                        "финалом: что сделано, что не получилось и почему; при "
                        "необходимости спроси пользователя (ask_user). Дальнейшие "
                        "повторы той же сигнатуры будут отклонены."
                    )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": ctx,
                    },
                    "systemMessage": (f"Детектор циклов [{act}]: {reason}")[:200],
                }

        return {}

    return hook


# ── Стриминг сообщений SDK → callbacks UI ──────────────────────────────────


def _fmt_tokens(n: int) -> str:
    """1234567 → '1.23M', 12345 → '12.3k', 999 → '999'."""
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _calc_cost_usd(usage: dict, pricing: dict | None) -> float | None:
    """Считает $-стоимость по usage и pricing ($/Mtok).
    Поддерживает cache_creation/cache_read токены. None если pricing неизвестен."""
    if not pricing or not usage:
        return None
    in_t          = usage.get("input_tokens", 0) or 0
    out_t         = usage.get("output_tokens", 0) or 0
    cache_create  = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read    = usage.get("cache_read_input_tokens", 0) or 0
    cost = (
        in_t         * pricing.get("in", 0)
        + out_t        * pricing.get("out", 0)
        + cache_create * pricing.get("cache_write", 0)
        + cache_read   * pricing.get("cache_read", 0)
    ) / 1_000_000
    return cost


async def _stream_messages(
    client: ClaudeSDKClient,
    task_id: str,
    on_log: LogFn,
    client_cfg: dict,
    model_pricing: dict | None = None,
    on_session_captured: Callable[[str], Awaitable[None]] | None = None,
    rt: RunTrace | None = None,
    run_metrics: dict | None = None,
    money_guard: "_money.MoneyGuard | None" = None,
) -> ResultMessage | None:
    """Читает поток сообщений SDK и проксирует в on_log callbacks.
    Возвращает финальный ResultMessage.

    Также извлекает usage из каждого AssistantMessage и логирует тонкой
    мета-строкой расход токенов на текущий turn. Накапливать total не
    нужно — ResultMessage.usage уже содержит итог по сессии.

    on_session_captured(session_id) — callback вызывается ОДИН раз когда
    SDK пришлёт первую SystemMessage(subtype="init") с session_id. Backend
    использует его для UPSERT в таблицу sessions и привязки task → session.
    """
    final: ResultMessage | None = None
    session_captured = False
    # Watchdog: per-event тайм-аут (SDK_SILENCE_TIMEOUT_SEC). При зависании
    # SSE — поднимется SDKSilenceTimeout, перехватим в run_task.
    async for message in _with_silence_watchdog(
        client.receive_response(),
        SDK_SILENCE_TIMEOUT_SEC,
    ):
        if isinstance(message, SystemMessage):
            # init-сообщение содержит session_id — ловим его один раз
            if not session_captured and on_session_captured is not None:
                # SDK может класть session_id как атрибут SystemMessage или в data
                sid = getattr(message, "session_id", None)
                if not sid:
                    data = getattr(message, "data", None)
                    if isinstance(data, dict):
                        sid = data.get("session_id")
                if sid:
                    session_captured = True
                    try:
                        await on_session_captured(sid)
                    except Exception as e:
                        log.warning("on_session_captured failed: %s", e)
            # init / лог инфраструктурный — не показываем в UI
            continue

        if isinstance(message, AssistantMessage):
            # Трассировка: один AssistantMessage = один виток ReAct. Собираем
            # текст ассистента / мышление / предложенные tool_use для llm_call.
            assistant_text: list[str] = []
            thinking_text: list[str] = []
            tool_uses: list[dict] = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        assistant_text.append(block.text)
                        await on_log(task_id, block.text, "", kind="text")
                elif isinstance(block, ThinkingBlock):
                    # Расширенное мышление — пишем как нейтральный текст
                    if block.thinking:
                        thinking_text.append(block.thinking)
                        await on_log(task_id, f"{block.thinking[:300]}", "", kind="text")
                elif isinstance(block, ToolUseBlock):
                    # Логируем вызов tool
                    params_preview = json.dumps(
                        block.input or {}, ensure_ascii=False
                    )[:160]
                    short_name = block.name
                    if short_name.startswith("mcp__agenter__"):
                        short_name = short_name[len("mcp__agenter__"):]
                    elif short_name.startswith("mcp__bsl_atlas__"):
                        short_name = "bsl_" + short_name[len("mcp__bsl_atlas__"):]
                    tool_uses.append({"name": short_name, "input": block.input or {}})
                    await on_log(task_id, f"→ {short_name}", params_preview)

            # Per-turn usage: тонкая meta-строка после tool/text-блоков
            # этого AssistantMessage. Полезно следить за расходом по ходу
            # задачи (особенно на больших ТЗ). Cache_read токены — почти
            # бесплатные, отображаем отдельно для прозрачности.
            usage = getattr(message, "usage", None)
            in_t = out_t = cache_read = 0
            if usage:
                in_t        = int(usage.get("input_tokens", 0) or 0)
                out_t       = int(usage.get("output_tokens", 0) or 0)
                cache_read  = int(usage.get("cache_read_input_tokens", 0) or 0)
                parts = [f"in {_fmt_tokens(in_t)} out {_fmt_tokens(out_t)}"]
                if cache_read:
                    parts.append(f"cache {_fmt_tokens(cache_read)}")
                cost = _calc_cost_usd(usage, model_pricing)
                if cost is not None and cost > 0:
                    # Формат: $0.001 для маленьких, $0.12 для крупных
                    if cost < 0.01:
                        parts.append(f"~${cost:.4f}")
                    else:
                        parts.append(f"~${cost:.3f}")
                await on_log(task_id, "tokens", " · ".join(parts))

                # ── Фаза 1 / Шаг 1.3: живой денежный потолок (Рубеж 1) ──────
                # Накапливаем стоимость по виткам; при достижении task_ceiling
                # зовём interrupt() — Фаза 0 подтвердила mid-turn-обрыв.
                # После Фазы 4 это ОСНОВНОЙ потолок остановки «по тратам».
                if money_guard is not None and cost:
                    if money_guard.add_turn(cost):
                        await on_log(
                            task_id,
                            "Денежный потолок достигнут — останавливаю задачу",
                            f"потрачено ~${money_guard.cumulative:.4f} ≥ "
                            f"лимит ~${money_guard.ceiling:.4f}",
                        )
                        if rt is not None:
                            rt.emit("ceiling", {
                                "cumulative": money_guard.cumulative,
                                "ceiling": money_guard.ceiling,
                                "action": "interrupt",
                            }, level="WARN", status="deny")
                        try:
                            await client.interrupt()
                        except Exception as e:
                            log.warning("interrupt() при достижении потолка не удался: %s", e)

            # ── Трассировка: llm_call (виток ReAct) ───────────────────────
            # payload = ОТВЕТ модели целиком (текст + мышление + предложенные
            # tool_use). Дельта входных сообщений витка не дублируется — она
            # восстановима из предыдущих tool_call (ToolResult) этого прогона
            # (без квадратичного роста). iteration — номер витка (основа
            # детектора циклов Фазы 3).
            if rt is not None:
                if run_metrics is not None:
                    run_metrics["llm_calls"] = run_metrics.get("llm_calls", 0) + 1
                iteration = run_metrics.get("llm_calls") if run_metrics else None
                if iteration is not None:
                    rt.set_iteration(iteration)
                rt.llm_call(
                    delta_messages=None,  # см. комментарий: дельта из tool_call
                    response={
                        "text": "\n".join(assistant_text) or None,
                        "thinking": "\n".join(thinking_text) or None,
                        "tool_uses": tool_uses,
                    },
                    tokens_in=in_t, tokens_out=out_t, tokens_cache=cache_read,
                )

        elif isinstance(message, UserMessage):
            # ToolResult — приходит как user message с ToolResultBlock внутри
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        result_text = ""
                        if isinstance(block.content, str):
                            result_text = block.content
                        elif isinstance(block.content, list):
                            for c in block.content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    result_text += c.get("text", "")
                        is_err = bool(getattr(block, "is_error", False))
                        # Найти имя из последнего ToolUseBlock — упростим:
                        # просто пишем длину/preview результата
                        if is_err:
                            # для 1С tools прогоняем через humanize
                            human = humanize_1c_error(result_text, client_cfg) \
                                if any(p in result_text for p in ("PowerShell", "1cv8", "db_")) \
                                else result_text
                            await on_log(task_id, "← ОШИБКА", human[:300])
                        else:
                            await on_log(task_id, "← OK", f"{len(result_text)} симв.")

        elif isinstance(message, ResultMessage):
            final = message
            break

    return final


# ── Главная точка входа: run_task с SDK ─────────────────────────────────────


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
    on_ask_user=None,
    model: str | None = None,
    model_pricing: dict | None = None,
    resume_session_id: str | None = None,
    on_session_captured: Callable[[str], Awaitable[None]] | None = None,
    on_phase_commit: Callable[[str, int], Awaitable[None]] | None = None,
    on_todos_update: Callable[[str, int, int], Awaitable[None]] | None = None,
    memory_md: str = "",
    selected_model: str | None = None,
):
    """Запускает агентный цикл через Claude Agent SDK.

    Сигнатура совместима со старым orchestrator.run_task — app/main.py не
    нужно менять, только переключить import.

    on_ask_user(task_id, question, options=[...]) → str — опц. блокирующая
    функция, к которой SDK-tool `ask_user` обращается чтобы дождаться ответа
    юзера. Если None — tool не регистрируется (агент не сможет задать вопрос).

    model — API alias модели Anthropic (например 'claude-sonnet-4-6').
    None → берём дефолт claude-sonnet-4-6. Передаётся в ClaudeAgentOptions.

    model_pricing — {"in": $/Mtok, "out": $/Mtok, "cache_read": ..., "cache_write": ...}
    для расчёта примерной стоимости задачи в логах. None → не считаем $.

    resume_session_id — Claude SDK session_id предыдущей задачи (из таблицы
    sessions). Если передан — новый run_task продолжает ту же conversation,
    SDK получает всю историю и TodoWrite предыдущей задачи. None = новая сессия.

    on_session_captured(session_id) — async callback, вызывается когда SDK
    пришлёт session_id (либо resumed = тот же, либо новый = свежий UUID).
    Backend использует для UPSERT sessions и UPDATE tasks.session_id.

    on_phase_commit(task_id, phase_index) — async callback, вызывается при
    успешном db_load (детект фазы). Backend записывает в task_phases и
    шлёт WS-event phase_committed.

    memory_md — содержимое MEMORY.md проекта (если есть), инлайнится в
    system_prompt. Пустая строка = MEMORY.md ещё не создан.
    """
    await on_status(task_id, "running")
    await on_log(task_id, "Задача принята, запускаю агента (SDK)...", "")

    if not anthropic_api_key:
        await on_error(task_id, "ANTHROPIC_API_KEY не установлен")
        return

    # SDK берёт ключ из env — пробросим
    import os
    os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key

    # ── Трассировка прогона (Фаза 2 логирования) ──────────────────────────
    # run_id := task_id. Трейсер — процессный синглтон; ключи дорегистрируем,
    # чтобы редактор гарантированно их маскировал. t0 — для длительности.
    tracer = get_tracer()
    tracer.add_secret(anthropic_api_key)
    tracer.add_secret(os.environ.get("DEEPSEEK_API_KEY"))
    rt: RunTrace = tracer.begin(task_id)
    _trace_t0 = time.monotonic()
    provider = os.environ.get("AGENT_PROVIDER", "claude").strip().lower()
    run_metrics: dict = {"llm_calls": 0}
    tool_timing: dict = {}

    # cwd: ставим на ext_src/, чтобы Read/Glob/Grep по умолчанию ходили туда.
    # add_dirs: расширяем доступ для built-in tools на SCHEME и agenter/data.
    # Это критично — LLM должен мочь Read/Grep по SCHEME для образцов.
    ext_src = client_cfg.get("ext_src_path") or "."
    cwd = ext_src if Path(ext_src).exists() else "."
    extra_dirs: list[str] = []
    for key in ("scheme_path",):
        val = client_cfg.get(key)
        if val and Path(val).exists():
            extra_dirs.append(val)
    # agenter/data/ — для будущих UI операций (опционально).
    agenter_data = Path(__file__).parent.parent / "data"
    if agenter_data.exists():
        extra_dirs.append(str(agenter_data))

    # История tool calls — общая для PreToolUse и PostToolUse hooks
    tool_history: list[dict] = []

    # MCP servers config — data-driven из config.json["mcp_servers"].
    # Backward-compat: если массива нет, берём только bsl-atlas из bsl_atlas_url.
    # ask_user_ctx: контекст для блокирующего tool ask_user (см. sdk_tools).
    # Если on_ask_user не передан — tool не регистрируется (deprecated path).
    ask_user_ctx = None
    if on_ask_user is not None:
        ask_user_ctx = {"task_id": task_id, "on_ask_user": on_ask_user}
    agenter_server = make_agenter_tools(
        executor,
        ask_user_ctx=ask_user_ctx,
    )
    mcp_servers: dict = {"agenter": agenter_server}

    raw_servers = client_cfg.get("mcp_servers") or []
    if raw_servers:
        for entry in raw_servers:
            if not isinstance(entry, dict):
                continue
            if not entry.get("enabled", True):
                continue
            transport = entry.get("transport", "http")
            if transport != "http":
                continue  # stdio пока не поддержан
            name = entry.get("name", "").strip()
            url = (entry.get("url") or "").strip()
            if not name or not url:
                continue
            # SDK ключ — с подчёркиваниями: bsl-atlas → bsl_atlas
            sdk_key = name.replace("-", "_")
            mcp_servers[sdk_key] = {
                "type": "http",
                "url": f"{url.rstrip('/')}/mcp",
            }
    else:
        # Старая конфигурация без mcp_servers — только bsl-atlas
        bsl_atlas_url = client_cfg.get("bsl_atlas_url", "http://localhost:8000")
        mcp_servers["bsl_atlas"] = {
            "type": "http",
            "url": f"{bsl_atlas_url.rstrip('/')}/mcp",
        }

    # SYSTEM_PROMPT + контекст клиента (включая addendum про built-in tools).
    # MEMORY.md инлайнится напрямую в промпт (страховка на случай если SDK
    # потеряет факты из истории). is_resumed_session — флаг для подсказки
    # агенту что это продолжение прошлой работы.
    sys_prompt = _build_client_context(
        client_cfg,
        memory_md=memory_md,
        is_resumed_session=bool(resume_session_id),
    )
    if resume_session_id:
        await on_log(
            task_id,
            f"Продолжаю сессию (resume)",
            f"session_id={resume_session_id[:12]}…",
        )
    if memory_md.strip():
        mem_lines = memory_md.count("\n") + 1
        await on_log(
            task_id,
            f"MEMORY.md загружен",
            f"{mem_lines} строк, инлайн в system_prompt",
        )

    # Pre-flight данные: объединённый список объектов основной конфигурации
    # (из SCHEME) и собственного расширения (из ext_src). Если оба пусты —
    # пропускаем проверку (db_load сам поймает ошибку, но менее изящно).
    # Mutable container: post-hook будет пересобирать "data" после каждого
    # успешного meta_compile/cfe_borrow, чтобы pre-hook видел свежесозданные
    # объекты ext_src на следующем шаге (иначе CatalogRef.NewObject ложно
    # блокируется preflight'ом — баг из лога 2026-05-15).
    known_objects_ref: dict = {
        "data": _list_known_objects_cached(
            client_cfg.get("scheme_path"),
            client_cfg.get("ext_src_path"),
        ),
    }
    if known_objects_ref["data"]:
        total = sum(len(v) for v in known_objects_ref["data"].values())
        await on_log(task_id, f"Pre-flight: {total} известных объектов (SCHEME + ext_src)", "")
    else:
        await on_log(
            task_id,
            "Pre-flight: SCHEME/ext_src пусты — типы проверятся только при db_load",
            "",
        )

    # ── Аварийный SDK-cap turns (Фаза 4: бизнес turn-cap снят) ─────────
    # max_effective_turns больше НЕ блокирует задачу — он лишь база для
    # расчёта sdk_hard_cap (абсолютная страховка от бесконечного цикла на
    # уровне SDK) и оценки денежного резерва. Остановка «по делу» — money-cap
    # и детектор циклов.
    max_effective_turns = int(client_cfg.get("max_iterations") or MAX_ITERATIONS)
    sdk_hard_cap = max(SDK_HARD_CAP_TURNS, max_effective_turns + MAX_ASK_USER_PER_TASK + 20)
    # Префикс _ означает: внутреннее, не из config.json юзера. Используется
    # для оценки резерва и трассировки (НЕ как блокирующий лимит по шагам).
    client_cfg["_max_effective_turns"] = max_effective_turns
    await on_log(
        task_id,
        f"Аварийный SDK-cap: {sdk_hard_cap} turns (бизнес-лимита по шагам нет — стоп по деньгам/циклам)",
        "",
    )

    # Mutable счётчики, общие для pre и post hook:
    #   effective — все tool calls КРОМЕ ask_user (считаются «работой»)
    #   ask_user  — только вызовы ask_user (считаются отдельно, своим лимитом)
    turn_state: dict = {"effective": 0, "ask_user": 0}

    # phase_state — счётчики фаз для этой задачи. committed увеличивается на
    # каждом успешном db_load, on_phase_commit callback синхронизирует с БД.
    phase_state: dict = {"committed": 0}

    # Фаза 4 разворота: stage_state_ref снят вместе со стадийной машиной —
    # стадии больше не персистятся и не гейтят; движок планирует свободно.

    # Фаза 1 / Шаг 1.1: детектор циклов (net-new). Один на задачу, общий для
    # pre/post hooks: post записывает в него каждый tool и возвращает steer/stop,
    # pre отклоняет «застрявшую» сигнатуру. После Фазы 4 — основной ловец
    # «застрял» (turn-cap снят), рядом с money-cap.
    loop_detector = LoopDetector()

    # Hooks
    pre_hook = _make_pre_tool_use_hook(
        tool_history, on_log, task_id, known_objects_ref,
        turn_state,
        client_cfg=client_cfg,
        rt=rt, tool_timing=tool_timing,
        loop_detector=loop_detector,
    )
    post_hook = _make_post_tool_use_hook(
        tool_history, on_log, task_id, known_objects_ref, client_cfg, turn_state,
        on_phase_commit=on_phase_commit, phase_state=phase_state,
        on_todos_update=on_todos_update,  # Sprint 2 S2.7
        rt=rt, tool_timing=tool_timing,
        loop_detector=loop_detector,
    )

    effective_model = (model or "claude-sonnet-4-6").strip()
    await on_log(task_id, f"Модель: {effective_model}", "")

    # ── Трассировка: run_start ────────────────────────────────────────────
    # Фиксируем ОБЕ модели (selected из UI-дропдауна vs effective в SDK),
    # провайдера, снимок конфига и фактически собранный системный промпт
    # (append поверх preset claude_code) — один раз + хеш.
    _trace_cfg_snapshot = {
        "provider": provider,
        "scheme_path": client_cfg.get("scheme_path"),
        "ext_src_path": client_cfg.get("ext_src_path"),
        "bsl_atlas_url": client_cfg.get("bsl_atlas_url"),
        "cwd": cwd,
        "add_dirs": extra_dirs,
        "mcp_servers": sorted(mcp_servers.keys()),
        "max_effective_turns": max_effective_turns,
        "sdk_hard_cap": sdk_hard_cap,
        "task_level": client_cfg.get("task_level"),
        "interactive_mode": bool(client_cfg.get("interactive_mode")),
        "spec_first_required": bool(client_cfg.get("spec_first_required")),
        "resume": bool(resume_session_id),
        "system_prompt_preset": "claude_code",
    }
    rt.start_run(
        prompt=prompt,
        selected_model=selected_model,
        effective_model=effective_model,
        provider=provider,
        config_snapshot=_trace_cfg_snapshot,
        system_prompt=sys_prompt,
    )

    # ── Перехват stderr CLI-подпроцесса SDK ──────────────────────────────
    # Без колбэка SDK прячет реальную причину падения за «Check stderr output
    # for details» (subprocess_cli.py). Собираем строки: и для диагностики
    # (например «No conversation found with session ID» → resume-fallback),
    # и чтобы показать пользователю настоящий текст вместо заглушки.
    cli_stderr: list[str] = []

    def _on_cli_stderr(line: str) -> None:
        s = (line or "").rstrip()
        if s:
            cli_stderr.append(s)
            log.debug("CLI stderr: %s", s)

    # Базовые опции SDK. resume передаётся отдельно ниже (только если задан),
    # потому что не все версии SDK принимают None как «без resume».
    options_kwargs: dict = dict(
        model=effective_model,
        stderr=_on_cli_stderr,
        # preset=claude_code даёт нам тюнинг Anthropic для coding-agent
        # (TodoWrite, reflection, multi-step planning), наш SYSTEM_PROMPT
        # с HARD RULES добавляется как append.
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": sys_prompt,
        },
        mcp_servers=mcp_servers,
        allowed_tools=_ALLOWED_TOOLS,
        # acceptEdits = Edit/Write для файлов автоапрув (доверяем guard'ам)
        permission_mode="acceptEdits",
        cwd=cwd,
        add_dirs=extra_dirs,
        # Изолируем от настроек Claude Code на диске. Фаза 5: НЕ переключаем на
        # ["project"] — рантайм-.claude содержит dev-конфиг (CLAUDE.md, auto-allow
        # прямого db-load -UpdateDB, SessionStart-hook), его подхват пробил бы
        # периметр. Нативные скиллы включаются отдельной опцией `skills` ниже
        # (она сама задействует нужный setting-source без settings.json/CLAUDE.md).
        setting_sources=[],
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_hook])],
        },
        # SDK hard cap: абсолютная страховка от бесконечного цикла на уровне
        # SDK (Фаза 4 — единственный оставшийся «потолок по шагам», и он НЕ
        # бизнес-лимит). Реальная остановка задачи «по делу» — money-cap
        # (живой потолок трат) и детектор циклов, а не число turns.
        max_turns=sdk_hard_cap,
    )

    # ── Фаза 5: нативные скиллы (gated) ──────────────────────────────────
    # По умолчанию OFF (см. _DB_MUTATOR_SKILLS / _compute_native_skills выше).
    # Когда включено — движок видит безопасные скиллы нативно; db-мутаторы
    # остаются только за MCP-обёрткой + защёлкой записи Фазы 3.
    if client_cfg.get("native_skills_enabled"):
        _native_skills = _compute_native_skills(cwd, client_cfg)
        if _native_skills:
            options_kwargs["skills"] = _native_skills
            await on_log(
                task_id,
                f"Нативные скиллы включены: {len(_native_skills)}",
                f"db-мутаторы ({len(_DB_MUTATOR_SKILLS)}) — только через MCP",
            )
        else:
            await on_log(
                task_id,
                "Нативные скиллы: каталог .claude/skills не найден",
                "остаётся MCP-канал",
            )

    # Auto-resume: если есть session_id предыдущей задачи в этом проекте —
    # SDK получит всю историю разговора (включая TodoWrite, ToolResult'ы,
    # размышления и финальные тексты прошлых заданий). Это решает проблему
    # «контекст не сохраняется между задачами» из бага 2026-05-15.
    if resume_session_id:
        options_kwargs["resume"] = resume_session_id

    options = ClaudeAgentOptions(**options_kwargs)

    # ── Трассировка: сборка роллапа и финализация-через-одну-точку ─────────
    def _trace_rollup(final_obj) -> dict:
        roll: dict = {
            "iterations": run_metrics.get("llm_calls"),
            "llm_calls": run_metrics.get("llm_calls"),
            "tool_calls": len(tool_history),
            "effective_turns": turn_state.get("effective"),
            "ask_user_turns": turn_state.get("ask_user"),
            "phases_committed": phase_state.get("committed"),
            "duration_ms": int((time.monotonic() - _trace_t0) * 1000),
        }
        # ── Fix D: семантический исход прогона (рядом с reason) ───────
        committed = int(phase_state.get("committed", 0) or 0)
        used_modifying = any(c.get("tool") in _MODIFYING_TOOLS for c in tool_history)
        if committed >= 1:
            roll["outcome"] = "applied"       # хотя бы один db_load → в БД
        elif used_modifying:
            roll["outcome"] = "staged"        # правки в ext_src, но НЕ загружены
        else:
            roll["outcome"] = "readonly"      # модифицирующих действий не было
        if final_obj is not None and getattr(final_obj, "usage", None):
            u = final_obj.usage
            ti = int(u.get("input_tokens", 0) or 0)
            to = int(u.get("output_tokens", 0) or 0)
            tc = int(u.get("cache_read_input_tokens", 0) or 0)
            roll["tokens_in"], roll["tokens_out"], roll["tokens_cache"] = ti, to, tc
            # ── Fix A: стоимость по effective-провайдеру, не по SDK ────
            # SDK считает total_cost_usd по Claude-прайсу — в DeepSeek-режиме
            # это завышает в ~30-40×. Берём свой расчёт по effective-модели.
            our_cost = _trace_cost(effective_model, ti, to, tc)
            sdk_cost = getattr(final_obj, "total_cost_usd", None)
            if provider != "claude" and our_cost is not None:
                roll["cost"], roll["cost_source"] = our_cost, "calc-effective"
            elif sdk_cost is not None:
                roll["cost"], roll["cost_source"] = sdk_cost, "sdk"
            else:
                roll["cost"], roll["cost_source"] = our_cost, "calc-effective"
            nt = getattr(final_obj, "num_turns", None)
            if nt:
                roll["num_turns"] = nt
        return roll

    # Фаза 1 / Шаг 1.2: дебет фактической стоимости задачи списывается ровно
    # один раз на финализации. Best-effort: ошибка ledger НЕ ломает задачу.
    _billing = {"debited": False}

    def _debit_once(summary: dict) -> None:
        if _billing["debited"]:
            return
        cost = summary.get("cost")
        if not isinstance(cost, (int, float)) or cost <= 0:
            return
        _billing["debited"] = True
        try:
            _ledger.init_ledger()
            account = (client_cfg.get("billing_account") or _ledger.DEFAULT_ACCOUNT)
            new_balance = _ledger.debit(
                float(cost), account, task_id=task_id,
                note=summary.get("outcome") or "task")
            if rt is not None:
                rt.emit("billing", {
                    "debit": float(cost), "balance_after": new_balance,
                    "account": account, "cost_source": summary.get("cost_source"),
                }, level="INFO")
        except Exception as e:
            log.warning("ledger debit failed (не критично): %s", e)

    async def _trace_finalize(reason: str, final_obj=None, *,
                              status: str | None = None, extra: dict | None = None,
                              sync: bool = False) -> None:
        summary = _trace_rollup(final_obj)
        if extra:
            summary.update(extra)
        _debit_once(summary)
        if sync:
            # На путях отмены/finally — прямой вызов (await может быть отменён).
            rt.finish_run(reason, status=status, summary=summary)
        else:
            await asyncio.to_thread(rt.finish_run, reason, status=status, summary=summary)

    # ── Фаза 1 / Шаг 1.3: денежный потолок (net-new, параллельно клетке) ──
    # Pre-start gate (Рубеж 0) + объект живого потолка (Рубеж 1). Включается
    # флагами client_cfg, чтобы в Фазе 1 НЕ блокировать работу без баланса
    # (клетка остаётся backstop'ом). Ledger-ошибка просто выключает потолок.
    money_guard = None
    _bill_account = client_cfg.get("billing_account") or _ledger.DEFAULT_ACCOUNT
    try:
        _ledger.init_ledger()
        _balance = _ledger.get_balance(_bill_account)
    except Exception as e:
        log.warning("ledger недоступен — потолок выключен на этой задаче: %s", e)
        _balance = None
    if _balance is not None:
        _reserve = _money.estimate_reserve(client_cfg, max_effective_turns)
        if client_cfg.get("billing_enforced"):
            _ok_start, _why = _money.pre_start_check(_balance, _reserve)
            if not _ok_start:
                await on_log(task_id, "Старт отклонён денежным потолком", _why)
                if rt is not None:
                    rt.emit("ceiling", {
                        "stage": "pre-start", "decision": "deny",
                        "balance": _balance, "reserve": _reserve,
                    }, level="WARN", status="deny")
                await on_error(task_id, _why)
                await _trace_finalize("ceiling-prestart", status="blocked",
                                      extra={"detail": _why})
                return
        if client_cfg.get("money_ceiling_enabled") or client_cfg.get("billing_enforced"):
            _ceiling = _money.compute_ceiling(
                _balance, client_cfg.get("task_cap_usd"),
                _money.one_turn_reserve(client_cfg))
            if _ceiling > 0:
                money_guard = _money.MoneyGuard(_ceiling)
                await on_log(task_id, "Денежный потолок активен",
                             f"лимит ~${_ceiling:.4f} (остаток ${_balance:.4f})")

    final = None
    try:
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                final = await _stream_messages(
                    client, task_id, on_log, client_cfg,
                    model_pricing=model_pricing,
                    on_session_captured=on_session_captured,
                    rt=rt, run_metrics=run_metrics,
                    money_guard=money_guard,
                )
        except Exception as exc:
            # Если resume не удался (например session_id протух на стороне
            # Anthropic/CLI) — пробуем начать новую сессию без resume. Это
            # graceful fallback, чтобы пользователь не оставался без агента.
            # ВАЖНО: реальная причина resume-сбоя («No conversation found with
            # session ID …») приходит только в stderr CLI — SDK кладёт в
            # исключение общее «Command failed with exit code 1». Поэтому
            # триггер проверяет И текст исключения, И собранный stderr.
            # Даём detached-читателю stderr SDK дочитать строки (гонка: CLI
            # уже упал, но «No conversation found …» мог не успеть прийти).
            await asyncio.sleep(0.1)
            msg = str(exc)
            stderr_text = "\n".join(cli_stderr)
            resume_failed = (
                "session" in msg.lower() or "resume" in msg.lower()
                or "no conversation found" in stderr_text.lower()
                or "session id" in stderr_text.lower()
                # CLI упал с кодом выхода во время connect, а мы пытались
                # resume — почти всегда это протухший session_id. Пробуем заново.
                or "exit code" in msg.lower()
            )
            if resume_session_id and resume_failed:
                real = next(
                    (l for l in cli_stderr
                     if "conversation" in l.lower() or "session" in l.lower()),
                    msg[:200],
                )
                await on_log(
                    task_id,
                    "Не удалось продолжить прошлую сессию",
                    f"{real[:200]} — начинаю новую",
                )
                rt.emit("decision", {
                    "decision": "resume-fallback",
                    "detail": real[:300],
                }, level="WARN")
                options_kwargs.pop("resume", None)
                # Перестраиваем sys_prompt без флага «это продолжение»
                options_kwargs["system_prompt"]["append"] = _build_client_context(
                    client_cfg, memory_md=memory_md, is_resumed_session=False,
                )
                fallback_options = ClaudeAgentOptions(**options_kwargs)
                async with ClaudeSDKClient(options=fallback_options) as client:
                    await client.query(prompt)
                    final = await _stream_messages(
                        client, task_id, on_log, client_cfg,
                        model_pricing=model_pricing,
                        on_session_captured=on_session_captured,
                        rt=rt, run_metrics=run_metrics,
                        money_guard=money_guard,
                    )
            else:
                raise

        if final is None:
            await on_error(task_id, "SDK завершился без ResultMessage")
            await _trace_finalize("model-error",
                                  extra={"detail": "SDK завершился без ResultMessage"})
            return

        # ── Итоговая статистика usage ────────────────────────────────
        # Anthropic SDK кладёт суммарные счётчики по сессии в ResultMessage.usage.
        # Кроме того, ResultMessage.total_cost_usd может быть посчитан самим SDK —
        # используем его если есть (он учитывает фактические тарифы Anthropic,
        # которые могут отличаться от наших захардкоженных), иначе считаем сами.
        usage_line = ""
        if final.usage:
            in_t       = int(final.usage.get("input_tokens", 0) or 0)
            out_t      = int(final.usage.get("output_tokens", 0) or 0)
            cache_read = int(final.usage.get("cache_read_input_tokens", 0) or 0)
            parts = [
                f"in={_fmt_tokens(in_t)}",
                f"out={_fmt_tokens(out_t)}",
            ]
            if cache_read:
                parts.append(f"cache={_fmt_tokens(cache_read)}")
            # В DeepSeek-режиме total_cost_usd от SDK посчитан по Claude-прайсу —
            # берём свой расчёт по model_pricing (в нём есть DeepSeek).
            if provider != "claude":
                disp_cost = _calc_cost_usd(final.usage, model_pricing)
            else:
                disp_cost = getattr(final, "total_cost_usd", None)
                if disp_cost is None:
                    disp_cost = _calc_cost_usd(final.usage, model_pricing)
            if disp_cost is not None and disp_cost > 0:
                parts.append(f"~${disp_cost:.4f}" if disp_cost < 0.01 else f"~${disp_cost:.3f}")
            num_turns = getattr(final, "num_turns", None)
            if num_turns:
                parts.append(f"{num_turns} turns")
            usage_line = " · ".join(parts)
            await on_log(task_id, "Итого", usage_line)

        if final.subtype == "success":
            await on_log(task_id, "Задача выполнена", "")
            await on_done(task_id)
            await _trace_finalize("success", final, status="success")
            return

        # SDK завершился с ошибкой / лимитом / интерраптом
        await on_error(
            task_id,
            f"Задача не завершилась успешно (subtype={final.subtype}).\n"
            + (f"Tokens: {usage_line}\n" if usage_line else "")
            + (getattr(final, "result", "") or ""),
        )
        # Маппинг subtype SDK → reason из контролируемого перечня.
        _st = (final.subtype or "").lower()
        if "max_turn" in _st or "max turns" in _st:
            _reason = "max-iterations"
        elif "token" in _st and "max" in _st:
            _reason = "max-tokens"
        else:
            _reason = "model-error"
        await _trace_finalize(_reason, final, status=final.subtype,
                              extra={"subtype": final.subtype})

    except asyncio.CancelledError:
        log.info("Задача %s отменена пользователем", task_id)
        try:
            await asyncio.shield(on_error(task_id, "Отменено пользователем"))
        except Exception:
            pass
        # Отмена пользователем — внешнее прерывание (нет «cancelled» в перечне).
        # Поведение control flow не меняем: как и раньше, отмену не пробрасываем.
        try:
            await _trace_finalize("external-error", status="cancelled",
                                  extra={"cause": "cancelled-by-user"}, sync=True)
        except Exception:
            pass

    except SDKSilenceTimeout as exc:
        # Watchdog сработал — Anthropic SDK перестал присылать события.
        # Отдаём пользователю понятное сообщение вместо «висит» в UI.
        log.warning("SDK silence watchdog triggered для %s: %s", task_id, exc)
        await on_error(task_id, str(exc))
        await _trace_finalize("model-error", status="silence-timeout",
                              extra={"cause": "sdk-silence-timeout",
                                     "detail": str(exc)[:300]})

    except Exception as exc:
        log.exception("Ошибка SDK orchestrator'а %s", task_id)
        # SDK прячет настоящую причину за «Check stderr output for details» —
        # подставляем реальный stderr CLI, чтобы пользователь видел суть.
        detail = str(exc)
        tail = [l for l in cli_stderr if l][-8:]
        if tail and "check stderr output" in detail.lower():
            detail = "Ошибка CLI-агента:\n" + "\n".join(tail)
        elif tail:
            detail += "\nCLI stderr:\n" + "\n".join(tail)
        await on_error(task_id, detail)
        rt.emit("error", {"source": "orchestrator", "exception": repr(exc),
                          "cli_stderr": tail},
                level="ERROR", status="error")
        await _trace_finalize("unknown-crash", status="exception",
                              extra={"exception": repr(exc)[:300],
                                     "cli_stderr": tail})

    finally:
        # Catch-all: тишины быть не может. Если ни одна ветка не финализировала
        # прогон явной причиной — закрываем unknown-crash. finish_run идемпотентна:
        # явный финал выше делает это no-op.
        try:
            rt.finish_run("unknown-crash",
                          summary={**_trace_rollup(final),
                                   "note": "финал без явной причины (catch-all)"})
        except Exception:
            pass
