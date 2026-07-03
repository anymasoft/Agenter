"""
agenter/app/task_planner.py — библиотека валидации стадий (ИСТОРИЧЕСКОЕ).

ВНИМАНИЕ (Фаза 5 разворота): стадийная машина и tool `plan_task` СНЯТЫ.
Планирование задачи — нативный TodoWrite движка; этот модуль больше НЕ
участвует в рантайме. Описание ниже — историческое (Sprint 4), оставлено
для контекста.

Из модуля в рантайме НИЧЕГО не вызывается. Сохранены лишь чистые функции
`validate_stages` / `render_plan_for_agent` / `validate_plan_invariants` и
типы `Stage` / `STAGE_KIND` — их держат юнит-тесты планировщика
(tests/app/test_task_planner.py). Диспетчеризация (stage_kind_to_full_tool /
is_tool_allowed_for_stage) удалена ещё в Фазе 4.

Историческая модель (Sprint 4): «LLM КЛАССИФИЦИРУЕТ стадию, ДИСПЕТЧЕР
детерминистически выбирает tool». Эта клетка снята разворотом — движок
вызывает инструменты свободно, границы держит периметр (check_tool_call).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Каталог типов стадий ────────────────────────────────────────────────────
#
# Названия kind'ов чётко описывают НАМЕРЕНИЕ стадии (что нужно сделать),
# а не средство (каким tool'ом). Это разделение позволяет позже менять
# реализацию (другой скилл / новый hot tool) без переписывания планов.

STAGE_KIND = {
    # === Метаданные объектов ===
    "create-metadata-object":   "Создать новый объект метаданных в расширении (Catalog/Document/Register/Enum/...)",
    "edit-metadata-object":     "Точечная правка существующего объекта (добавить/изменить/удалить реквизит, ТЧ, измерение, ресурс)",
    "remove-metadata-object":   "Удалить объект метаданных из расширения",

    # === Заимствование ===
    "borrow-object":            "Заимствовать типовой объект конфигурации в расширение",

    # === Подсистемы ===
    "include-in-subsystem":     "Добавить объект в Содержимое подсистемы (или дочернюю подсистему)",
    "remove-from-subsystem":    "Убрать объект из Содержимого подсистемы",
    "create-subsystem":         "Создать новую подсистему",
    "edit-subsystem-property":  "Изменить свойство подсистемы (Synonym, IncludeInCommandInterface и пр.)",

    # === Формы ===
    "create-form":              "Создать новую управляемую форму",
    "edit-form":                "Добавить элементы/реквизиты/команды в существующую форму",
    "remove-form":              "Удалить форму у объекта",

    # === Программный код ===
    "write-bsl-module":         "Написать или существенно изменить BSL-модуль (объекта, формы, общий)",
    "method-interceptor":       "Создать перехватчик метода (Before/After/Around) в расширении",

    # === Прочие типы метаданных через cold skills ===
    "create-role":              "Создать роль с правами",
    "create-template":          "Создать макет (MXL/HTML/текст)",
    "create-skd":               "Создать схему компоновки данных (СКД)",
    "create-command-interface": "Настроить командный интерфейс подсистемы",

    # === Утилитарные стадии ===
    "research":                 "Исследовать существующую конфигурацию/код перед изменениями (read-only)",
    "validate-and-load":        "Финальная валидация и загрузка изменений в БД 1С (cfe_validate + db_load)",
    "sync-from-db":             "Синхронизировать ext_src/ из реальной БД (db_dump)",
    "ask-user":                 "Запросить уточнение у пользователя (неоднозначность в ТЗ)",
    "other":                    "Прочее, не подходит ни под один из стандартных видов — потребуется skill_search или ручная работа",
}


# ── Diopетчер: kind → expected_tool ──────────────────────────────────────────
#
# Это «карта истины». Когда стадия активна, агент имеет право вызвать ИМЕННО
# этот tool (плюс read-only/validation — они всегда разрешены).
#
# Значение — короткое имя tool'а как в логах (`db_dump`, `meta_compile`),
# orchestrator на стороне SDK сопоставит с `mcp__agenter__<name>`.
#
# Для kind'ов где нет первоклассного hot tool — указан `skill_run` с
# подсказкой какой skill_name использовать.

STAGE_KIND_TO_TOOL: dict[str, str] = {
    "create-metadata-object":   "meta_compile",
    "edit-metadata-object":     "meta_edit",
    "remove-metadata-object":   "skill_run:meta-remove",   # cold skill
    "borrow-object":            "cfe_borrow",
    "include-in-subsystem":     "subsystem_edit",          # operation=add-content
    "remove-from-subsystem":    "subsystem_edit",          # operation=remove-content
    "create-subsystem":         "skill_run:subsystem-compile",
    "edit-subsystem-property":  "subsystem_edit",          # operation=set-property
    "create-form":              "form_compile",
    "edit-form":                "form_edit",
    "remove-form":              "skill_run:form-remove",
    "write-bsl-module":         "Edit",                     # Edit/Write на *.bsl
    "method-interceptor":       "cfe_patch_method",
    "create-role":              "skill_run:role-compile",
    "create-template":          "skill_run:mxl-compile",    # для MXL; для других — skd-compile
    "create-skd":               "skill_run:skd-compile",
    "create-command-interface": "skill_run:interface-edit",
    # research — особый kind: agent делает много read-only вызовов и затем
    # ПЕРЕПЛАНИРУЕТ задачу через plan_task. Auto-advance этой стадии отключён
    # в orchestrator_sdk._make_post_tool_use_hook (hotfix-7) — иначе первый
    # же Read закрывал бы стадию. expected = "Read" — placeholder; реально
    # на research разрешён весь read-only + Bash + Edit/Write на .bsl.
    "research":                 "Read",
    "validate-and-load":        "db_load",                  # после cfe_validate
    "sync-from-db":             "db_dump",
    "ask-user":                 "ask_user",
    # other — fallback для нестандартных операций. Агент сначала ищет skill
    # через skill_search (always-allowed), потом вызывает skill_run. Поэтому
    # expected = skill_run (это завершает стадию).
    "other":                    "skill_run",
}


# ── Модифицирующие стадии (для invariant SYNC-FIRST) ───────────────────────
#
# Стадии, которые пишут в ext_src/ либо в БД 1С. Планировщик enforce'ит, что
# любой план, содержащий хоть одну такую стадию, ОБЯЗАН начинаться с
# 'sync-from-db'. Без этого гаранта orphan-файлы от прошлой неудачной задачи
# (когда db_load не успел выполниться) попадают в текущую модификацию и
# ломают её — корневая причина прод-инцидента 2026-05-17 (заимствование
# Финансы.xml в сломанном состоянии + db_load с ошибкой формата).
#
# Сюда сознательно НЕ входят:
#   research      — read-only исследование
#   ask-user      — только запрос пользователю
#   sync-from-db  — это сам синхрон, инвариант его и требует
#   other         — нетипизированный (риск enforce'ить слепо)

MODIFYING_STAGE_KINDS: frozenset[str] = frozenset({
    "create-metadata-object", "edit-metadata-object", "remove-metadata-object",
    "borrow-object",
    "include-in-subsystem", "remove-from-subsystem",
    "create-subsystem", "edit-subsystem-property",
    "create-form", "edit-form", "remove-form",
    "write-bsl-module", "method-interceptor",
    "create-role", "create-template", "create-skd", "create-command-interface",
    "validate-and-load",
})


# ── Always-allowed whitelist + R1 skill-suffixes — СНЯТО (Фаза 4) ──────────
# Здесь жили ALWAYS_ALLOWED_TOOLS, _ALWAYS_ALLOWED_SKILL_SUFFIXES и
# _is_always_allowed_skill — whitelist для stage-dispatch (что разрешено на
# любой стадии). Использовались ТОЛЬКО внутри is_tool_allowed_for_stage,
# которая снята вместе со стадийной машиной. Удалены как мёртвый код.


# ── Stage ──────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Stage:
    """Одна стадия в плане задачи."""
    index: int                   # порядковый номер от 1
    kind: str                    # один из ключей STAGE_KIND
    description: str             # человекочитаемое описание что делать
    expected_tool: str           # tool который ОДНОЗНАЧНО соответствует kind
    args_hint: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"      # pending | in_progress | completed | failed | skipped

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "description": self.description,
            "expected_tool": self.expected_tool,
            "args_hint": self.args_hint,
            "status": self.status,
        }


# ── API ────────────────────────────────────────────────────────────────────

def expected_tool_for_kind(kind: str) -> str:
    """Возвращает имя ожидаемого tool'а для kind стадии. Бросает ValueError
    если kind неизвестен."""
    if kind not in STAGE_KIND_TO_TOOL:
        raise ValueError(
            f"Неизвестный stage_kind: '{kind}'. "
            f"Допустимые: {sorted(STAGE_KIND.keys())}"
        )
    return STAGE_KIND_TO_TOOL[kind]


def normalize_tool_name(short_or_full: str) -> str:
    """Приводит имена tool'ов к каноническому виду для сравнения.

    Различаем:
      'meta_compile' → 'mcp__agenter__meta_compile'
      'db_load'      → 'mcp__agenter__db_load'
      'skill_run:meta-remove' → 'mcp__agenter__skill_run' (с проверкой args позже)
      'Edit'         → 'Edit'
      'bsl_*'        → 'bsl_*' (wildcard для read tools)
    """
    if not short_or_full:
        return ""
    if short_or_full.startswith("mcp__"):
        return short_or_full
    if short_or_full.startswith("skill_run:"):
        return "mcp__agenter__skill_run"
    # bsl_* — wildcard, остаётся как есть
    if short_or_full.endswith("*"):
        return short_or_full
    # Built-in (Edit/Read/Write/Glob/Grep/Bash/TodoWrite/Agent) — capitalized
    if short_or_full[0].isupper():
        return short_or_full
    # agenter MCP tool
    return f"mcp__agenter__{short_or_full}"


# ── stage-dispatch decision — СНЯТО (Фаза 4 разворота) ──────────────────────
# Здесь жили stage_kind_to_full_tool / _stage_field / is_tool_allowed_for_stage —
# ядро диспетчеризации (что разрешено на текущей стадии). Снято вместе со
# стадийной машиной: клетки больше нет, движок вызывает инструменты свободно,
# границы держит периметр (check_tool_call). validate_stages/render_plan_for_agent
# ниже сохранены только для юнит-тестов планировщика — в рантайме (Фаза 5,
# plan_task снят) их больше никто не вызывает.


def validate_plan_invariants(stages: list[Stage]) -> list[str]:
    """Семантические инварианты на уже-распарсенный план.

    Структурная валидация (kind/description/индексы) делается отдельно в
    `validate_stages`. Здесь — содержательные инварианты, которые требуют
    видеть план целиком как набор стадий.

    Активные инварианты: нет.

    ── Фаза 2 разворота (снято): SYNC-FIRST ──────────────────────────────
    Ранее здесь жил инвариант SYNC-FIRST: любой план с модифицирующей
    стадией ОБЯЗАН был начинаться с 'sync-from-db'. Это «всегда
    синхронизируй» закрывало класс багов «orphan-файл от прошлой неудачной
    задачи», но ценой принудительной полной выгрузки в начале КАЖДОЙ
    модифицирующей задачи (дорого и часто бессмысленно — база не менялась).

    Снят в пользу умной синхронизации (Р4):
      • истина на чтение = реальная база/индекс, не записанная память;
      • перед задачей дёшево сверяемся ConfigDumpInfo-детектором
        (`base_change_detector`) — выгружаем ТОЛЬКО если база реально
        менялась (Шаг 2.2), иначе старт мгновенный;
      • явная кнопка «Синхронизировать» как ручная страховка (Шаг 2.3);
      • orphan-файлы теперь не проблема: db_load-gate (сохраняемое ядро) и
        single-shot db_dump guard (tool_guards 2A/2B) остаются на месте.

    Функция намеренно сохранена (а не удалена) как точка расширения для
    будущих семантических инвариантов плана.

    Возвращает список текстовых ошибок. Пустой список = инварианты держатся.
    Эти ошибки `validate_stages` отправит обратно агенту, чтобы он
    перепланировал через повторный plan_task.
    """
    errors: list[str] = []
    if not stages:
        return errors

    # SYNC-FIRST снят (Фаза 2): план больше не обязан начинаться с
    # 'sync-from-db'. Синхронизация теперь условная и внешняя по отношению к
    # плану (см. docstring). Других активных инвариантов пока нет.
    return errors


def validate_stages(raw_stages: list[dict]) -> tuple[list[Stage], list[str]]:
    """Валидирует массив сырых стадий из вызова plan_task.

    Возвращает (parsed_stages, errors). Если errors не пуст — план невалиден,
    plan_task должен вернуть ошибку агенту.

    Что проверяется:
      Структурно:
        • kind — известный
        • description — не пустой
        • порядок индексов — последовательный 1..N
      Семантически (через validate_plan_invariants):
        • SYNC-FIRST: модифицирующий план должен начинаться с sync-from-db
    """
    stages: list[Stage] = []
    errors: list[str] = []
    if not isinstance(raw_stages, list) or not raw_stages:
        return [], ["stages должно быть непустым массивом"]

    for i, raw in enumerate(raw_stages, start=1):
        if not isinstance(raw, dict):
            errors.append(f"стадия #{i}: ожидался объект, получено {type(raw).__name__}")
            continue
        kind = str(raw.get("kind", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not kind:
            errors.append(f"стадия #{i}: отсутствует kind")
            continue
        if kind not in STAGE_KIND:
            errors.append(
                f"стадия #{i}: неизвестный kind '{kind}'. "
                f"Допустимые: {sorted(STAGE_KIND.keys())}"
            )
            continue
        if not description:
            errors.append(f"стадия #{i} ({kind}): отсутствует description")
            continue
        args_hint = raw.get("args_hint")
        if args_hint is not None and not isinstance(args_hint, dict):
            errors.append(
                f"стадия #{i}: args_hint должен быть объектом или отсутствовать"
            )
            continue
        try:
            expected = expected_tool_for_kind(kind)
        except ValueError as e:
            errors.append(f"стадия #{i}: {e}")
            continue
        stages.append(Stage(
            index=i,
            kind=kind,
            description=description,
            expected_tool=expected,
            args_hint=args_hint or {},
            status="pending",
        ))

    # Sprint 4 hotfix-8: семантические инварианты проверяем ТОЛЬКО если
    # структурно всё валидно (иначе ошибки накладываются и агент путается).
    if not errors and stages:
        errors.extend(validate_plan_invariants(stages))

    return stages, errors


def render_plan_for_agent(stages: list[Stage]) -> str:
    """Форматирует план в человекочитаемый текст для возврата агенту.
    Подсказывает какой tool вызывать на каждой стадии."""
    if not stages:
        return "План пуст."
    lines = [f"План задачи: {len(stages)} стадий\n"]
    for s in stages:
        full_tool = normalize_tool_name(s.expected_tool)
        marker = {
            "pending":     "[ ]",
            "in_progress": "[>]",
            "completed":   "[x]",
            "failed":      "[!]",
            "skipped":     "[~]",
        }.get(s.status, "?")
        lines.append(
            f"  {marker} #{s.index} [{s.kind}] {s.description}\n"
            f"     → expected tool: {full_tool}"
        )
        if s.args_hint:
            lines.append(f"     args hint: {s.args_hint}")
    lines.append("")
    lines.append(
        "Выполняй стадии по порядку. На каждой стадии — вызови ИМЕННО "
        "expected tool. Если стадия неприменима (например 'create-form' но "
        "формы не нужно) — пометь её skipped через повторный plan_task. "
        "После всех модифицирующих стадий — последняя стадия должна быть "
        "'validate-and-load' (cfe_validate → db_load)."
    )
    return "\n".join(lines)
