"""
agenter/app/task_planner.py — детерминированная диспетчеризация стадий.

Sprint 4 архитектуры: уходим от модели «LLM сам выбирает tool» к модели
«LLM КЛАССИФИЦИРУЕТ стадию задачи, ДИСПЕТЧЕР детерминистически выбирает tool».

Принцип:
  1. На L2+ задачах агент ОБЯЗАН первым вызовом сделать `plan_task(stages=[...])`
  2. Каждая стадия имеет `kind` из фиксированного enum'а STAGE_KIND
  3. STAGE_KIND_TO_TOOL — однозначная таблица соответствий «kind → tool»
  4. Orchestrator идёт по стадиям, на каждой разрешает ТОЛЬКО соответствующий
     tool (+ read-only/validation tools всегда разрешены)
  5. Агент НЕ ВЫБИРАЕТ — он либо вызывает expected_tool, либо ask_user

Это снимает класс ошибок «агент попытался Edit XML вручную / выдумал
ограничение / удалил заимствованный объект» — потому что у агента просто
нет такой возможности по архитектуре.

Универсальность гарантируется тем, что mapping kind→tool единый для всех
задач. Никаких task-specific исключений.
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


# ── Always-allowed tools (read-only / диагностика / финал) ─────────────────
#
# Эти tools разрешены на ЛЮБОЙ стадии, потому что они не выполняют
# модификацию ext_src/БД, либо обязательны на финале фазы.

ALWAYS_ALLOWED_TOOLS = frozenset({
    # built-in read tools
    "Read", "Glob", "Grep", "TodoWrite",
    # Claude Code deferred tools — read-only мета-инфраструктура.
    # ToolSearch иногда вызывается агентом для подгрузки JSON Schema
    # известных tools — безопасно, пусть проходит без блокировки.
    "ToolSearch",
    # BSL Atlas — поиск
    "mcp__bsl_atlas__search_function",
    "mcp__bsl_atlas__get_module_functions",
    "mcp__bsl_atlas__get_function_context",
    "mcp__bsl_atlas__metadatasearch",
    "mcp__bsl_atlas__get_object_details",
    "mcp__bsl_atlas__code_grep",
    "mcp__bsl_atlas__codesearch",
    "mcp__bsl_atlas__helpsearch",
    "mcp__bsl_atlas__search_code_filtered",
    "mcp__bsl_atlas__stats",
    # 1С-документация
    "mcp__agenter__platform_doc_lookup",
    "mcp__agenter__platform_doc_search",
    # Информация об объектах/формах
    "mcp__agenter__meta_info",
    "mcp__agenter__form_info",
    # Валидация (всегда нужна перед db_load)
    "mcp__agenter__cfe_validate",
    "mcp__agenter__meta_validate",
    "mcp__agenter__form_validate",
    "mcp__agenter__syntax_check",
    # Discovery
    "mcp__agenter__skill_search",
    # Interaction
    "mcp__agenter__ask_user",
    # План — основной mandatory tool
    "mcp__agenter__plan_task",
    # Sub-agent — должен быть всегда доступен для делегирования
    "Agent",
})


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


def stage_kind_to_full_tool(kind: str) -> str:
    """Полное MCP-имя ожидаемого tool'а для kind стадии."""
    short = expected_tool_for_kind(kind)
    return normalize_tool_name(short)


def _stage_field(stage: Stage | dict | None, name: str, default=None):
    """Универсальный доступ к полю стадии — поддерживает и dataclass, и dict.
    Это нужно потому что стадии приходят из БД как dict, а в коде Stage."""
    if stage is None:
        return default
    if isinstance(stage, dict):
        return stage.get(name, default)
    return getattr(stage, name, default)


def is_tool_allowed_for_stage(
    tool_name: str,
    stage: Stage | dict | None,
    tool_input: dict | None = None,
) -> tuple[bool, str]:
    """Проверяет разрешён ли tool на активной стадии.

    Возвращает (allowed, reason). reason — для отображения пользователю.

    Логика:
      • Если stage = None (план ещё не построен) — разрешены только
        plan_task, read-only/research tools и ask_user.
      • Иначе — разрешён expected_tool текущей стадии + ALWAYS_ALLOWED_TOOLS.
      • Tool Bash — особый случай: разрешён только на 'write-bsl-module' и
        'research' (для diagnostic команд), запрещён везде остальном.
      • Write/Edit на .json — разрешён на ЛЮБОЙ стадии. JSON-файлы это args
        для cold skills (form_compile, skd_compile, role_compile, mxl_compile,
        interface_edit, subsystem_compile), не структурные метаданные.
        Path-guards (Configuration.xml, .xml ext, agenter/* fragment) проверят
        опасные пути ниже по цепочке (см. check_tool_call).

    Универсально: принимает Stage dataclass ИЛИ dict с теми же ключами.
    Также принимает имя tool'а в любом формате — short ('db_dump') или
    full ('mcp__agenter__db_dump') — нормализует внутри.
    tool_input нужен чтобы видеть file_path при проверке Write/Edit на .json.
    """
    if not tool_name:
        return False, "пустое имя tool'а"

    # Нормализуем имя tool'а к полному виду для сравнения с ALWAYS_ALLOWED_TOOLS
    # и expected_tool (которые хранятся в полном формате).
    tool_full = normalize_tool_name(tool_name)

    # Без активного плана: разрешены только меta-tools для построения плана
    # и read-only исследование.
    if stage is None:
        # Read tools + ask_user + plan_task + skill_search всегда OK
        if tool_full in ALWAYS_ALLOWED_TOOLS:
            return True, ""
        # bsl_atlas wildcard
        if tool_full.startswith("mcp__bsl_atlas__"):
            return True, ""
        return (
            False,
            "План задачи не построен. Сначала вызови plan_task с описанием стадий, "
            "потом исполняй их по порядку. До построения плана разрешены только "
            "read-only исследование, ask_user и сам plan_task."
        )

    stage_kind = _stage_field(stage, "kind", "")
    stage_expected = _stage_field(stage, "expected_tool", "")

    # ALWAYS-allowed работает на любой стадии
    if tool_full in ALWAYS_ALLOWED_TOOLS:
        return True, ""
    if tool_full.startswith("mcp__bsl_atlas__"):
        return True, ""

    # Bash — особый случай: только для 'research' и 'write-bsl-module' и
    # 'sync-from-db' (для diagnostic команд типа dir/git status).
    if tool_name == "Bash":
        if stage_kind in ("research", "write-bsl-module", "sync-from-db"):
            return True, ""
        return (
            False,
            f"Bash запрещён на стадии '{stage_kind}'. Bash доступен только на "
            f"'research', 'write-bsl-module', 'sync-from-db'. Используй "
            f"expected_tool='{stage_expected}' для текущей стадии."
        )

    # Edit/Write — только если стадия write-bsl-module И путь — .bsl.
    # Также разрешены на 'research' (write Note.md в proposals для заметок).
    # Sprint 4 hotfix-7: разрешены на ЛЮБОЙ стадии для .json файлов — это
    # args для cold skills (form_compile, skd_compile, role_compile, mxl_compile,
    # interface_edit, subsystem_compile). Без этого create-form/create-role/
    # create-skd стадии не могут подготовить json_path перед skill_run.
    # Детальная проверка пути (.xml/.bsl/Configuration.xml/agenter/*) — в tool_guards.py.
    if tool_name in ("Edit", "Write", "write_file"):
        if stage_kind in ("write-bsl-module", "research"):
            return True, ""
        # .json files — это args, не структурные метаданные. Разрешены всегда.
        path = ""
        if tool_input:
            path = str(
                tool_input.get("path")
                or tool_input.get("file_path")
                or ""
            )
        if path and path.lower().endswith(".json"):
            return True, ""
        return (
            False,
            f"Edit/Write запрещены на стадии '{stage_kind}'. Для модификации "
            f"объектов используй expected_tool='{stage_expected}'. Edit/Write "
            f"разрешены только на стадии 'write-bsl-module' (для *.bsl) либо "
            f"на любой стадии для *.json (args-файлы cold skills)."
        )

    # Sprint 4 hotfix-6: special-case для research kind.
    # Research стадия — открытая, агент делает много read-only вызовов и
    # затем переходит к делу через plan_task (replan). На research разрешены:
    # все always-allowed (уже выше), bsl_atlas (уже выше), Bash (уже выше),
    # Edit/Write на .bsl (уже выше). Прочие модифицирующие tools — запрещены.
    if stage_kind == "research":
        return (
            False,
            f"Стадия 'research' — только read-only исследование и заметки. "
            f"Tool '{tool_name}' для модификации запрещён. Когда закончишь "
            f"исследование — вызови plan_task с обновлённым набором стадий, "
            f"чтобы перейти к действиям."
        )

    # Проверка expected_tool — оба в нормализованном виде
    expected_full = stage_kind_to_full_tool(stage_kind)

    # Точное совпадение
    if tool_full == expected_full:
        return True, ""

    # skill_run может «упаковать» любой cold skill, поэтому если expected
    # начинается с `skill_run:` — разрешён mcp__agenter__skill_run
    if expected_full == "mcp__agenter__skill_run" and tool_full == "mcp__agenter__skill_run":
        return True, ""

    # Sprint 4 hotfix-6: УБРАН опасный fallback `expected_full.endswith("*")`
    # который пропускал ВСЁ. Wildcard'ов в STAGE_KIND_TO_TOOL теперь нет —
    # research обработан special-case'ом выше.

    stage_index = _stage_field(stage, "index", "?")
    stage_desc = _stage_field(stage, "description", "")[:60]
    return (
        False,
        f"На стадии '{stage_kind}' (#{stage_index}: {stage_desc}) "
        f"ожидался tool '{expected_full}', а ты пытаешься вызвать '{tool_name}'. "
        f"Либо смени план (повторный plan_task), либо вызови правильный tool, "
        f"либо ask_user если ситуация неоднозначна."
    )


def validate_plan_invariants(stages: list[Stage]) -> list[str]:
    """Семантические инварианты на уже-распарсенный план.

    Структурная валидация (kind/description/индексы) делается отдельно в
    `validate_stages`. Здесь — содержательные инварианты, которые требуют
    видеть план целиком как набор стадий.

    Активные инварианты:
      SYNC-FIRST:
        Если в плане есть хотя бы одна модифицирующая стадия
        (из MODIFYING_STAGE_KINDS), первая стадия плана ОБЯЗАНА быть
        'sync-from-db'. Это закрывает класс багов «orphan-файл от прошлой
        неудачной задачи мешает новой».
        Read-only-планы (только research/ask-user) этот инвариант не
        затрагивает — sync им не нужен.

    Возвращает список текстовых ошибок. Пустой список = инварианты держатся.
    Эти ошибки `validate_stages` отправит обратно агенту, чтобы он
    перепланировал через повторный plan_task.
    """
    errors: list[str] = []
    if not stages:
        return errors

    has_modifying = any(s.kind in MODIFYING_STAGE_KINDS for s in stages)
    if has_modifying and stages[0].kind != "sync-from-db":
        offending = next(
            (s for s in stages if s.kind in MODIFYING_STAGE_KINDS), None,
        )
        offending_desc = (
            f"#{offending.index} [{offending.kind}]" if offending else "?"
        )
        errors.append(
            "Инвариант SYNC-FIRST нарушен: план содержит модифицирующую "
            f"стадию ({offending_desc}), но не начинается с 'sync-from-db'. "
            "Это создаёт риск orphan-файлов в ext_src/ от прошлой неудачной "
            "задачи (db_load мог не завершиться, файлы остались на диске). "
            "Перепланируй: первой стадией добавь "
            "{'kind': 'sync-from-db', 'description': "
            "'Синхронизировать ext_src/ из БД перед изменениями'}, "
            "потом остальные стадии в прежнем порядке."
        )

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
            "pending":     "○",
            "in_progress": "▶",
            "completed":   "✓",
            "failed":      "✗",
            "skipped":     "↷",
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
