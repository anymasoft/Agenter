"""
agenter/app/tool_guards.py — жёсткое обеспечение правил использования инструментов.

Промпт говорит LLM «делай так» — guards делают так, ЧТОБЫ она делала так.
Если LLM пытается вызвать запрещённый tool / в запрещённом контексте —
guard перехватывает ДО executor.execute() и возвращает ошибку с подсказкой,
куда переключиться. LLM получает is_error tool_result и сама исправляется.

Это страховка, не замена промпту. Идеальный сценарий — guards никогда не
срабатывают (LLM правильно читает promo). Реальный — срабатывают редко
и подсказывают правильный маршрут.

Зачем не убрать deprecated tools совсем? Чтобы LLM получала ОБРАЗОВАТЕЛЬНОЕ
сообщение «вот это deprecated, используй то» вместо тихого «tool not found»,
который менее информативен.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

# Tools, которые объявлены DEPRECATED — любой вызов блокируется
# с указанием замены.
_DEPRECATED_REPLACEMENTS = {
    "clone_object":           "meta_compile (создание нового объекта по JSON, без копирования образцов)",
    "get_sample_object":      "meta_compile (не нужен образец — генерирует XML по JSON-описанию)",
    "validate_ext_structure": "cfe_validate (полная проверка расширения)",
}

# Расширения файлов, которые НЕЛЬЗЯ создавать через write_file —
# для них есть скиллы.
_FORBIDDEN_WRITE_EXTS = {".xml"}


def _xml_path_hint(path_lower: str) -> str:
    """Sprint 2 hotfix-5: по пути XML возвращает рекомендацию какой именно
    специализированный tool/skill использовать. path_lower — путь в формате
    posix lowercase.

    Универсальная маршрутизация — основана только на структурной разметке
    папок 1С, без привязки к конкретным именам объектов задачи.
    """
    # Configuration.xml — особенно опасный файл (содержит ChildObjects всего расширения)
    if path_lower.endswith("configuration.xml") or path_lower.endswith("/package.xml"):
        return (
            "Configuration.xml — НИКОГДА не редактируй вручную. Состав расширения "
            "управляется через meta_compile/meta_remove/cfe_borrow."
        )
    # Form.xml — управляемая форма (R12)
    if path_lower.endswith("/form.xml") or "/forms/" in path_lower and path_lower.endswith(".xml"):
        return (
            "Form.xml — только через form_edit (добавить элементы) или "
            "form_compile (создать с нуля). См. R12."
        )
    # Subsystem XML
    if "/subsystems/" in path_lower:
        return (
            "Подсистема — skill_run('subsystem-edit', {'subsystem_path': '<путь>', "
            "'operation': 'add-content', 'value': 'Catalog.X'}) для добавления объекта в Содержимое, "
            "или 'add-child' для дочерней подсистемы. "
            "Альтернативно skill_run('subsystem-compile', ...) для создания с нуля."
        )
    # Roles
    if "/roles/" in path_lower:
        return (
            "Роль — skill_run('role-compile', ...) для создания или "
            "skill_search('роль') чтобы найти точный скилл (edit/info/validate)."
        )
    # Rights.xml
    if path_lower.endswith("/rights.xml"):
        return (
            "Rights.xml — это часть роли; skill_search('роль') найдёт role-compile / "
            "role-info / role-validate."
        )
    # Templates / макеты
    if path_lower.endswith(".mxl") or "/templates/" in path_lower:
        return (
            "Макет/шаблон — skill_run('mxl-compile', ...) или skill_search('макет')."
        )
    # СКД (Schemas of data composition)
    if "datacompositionschema" in path_lower or path_lower.endswith("/template.xml"):
        return "СКД/макет — skill_search('СКД') / skill_search('макет')."
    # CommandInterface
    if "commandinterface" in path_lower:
        return (
            "Командный интерфейс — skill_run('interface-edit', ...) или "
            "skill_search('командный интерфейс')."
        )
    # Главный XML-файл объекта метаданных (на верхнем уровне типа: Catalogs/X.xml)
    # Структура пути обычно: ext_src/<TypeDir>/<Name>.xml — двух-сегментная
    # после ext_src. Сегмент TypeDir включает: Catalogs, Documents, Enums,
    # InformationRegisters, AccumulationRegisters, AccountingRegisters,
    # ChartsOfCharacteristicTypes, ChartsOfAccounts, ExchangePlans,
    # BusinessProcesses, Tasks, DataProcessors, Reports, CommonModules, и т.д.
    for type_dir in (
        "/catalogs/", "/documents/", "/enums/", "/informationregisters/",
        "/accumulationregisters/", "/accountingregisters/",
        "/chartsofcharacteristictypes/", "/chartsofaccounts/",
        "/chartsofcalculationtypes/", "/exchangeplans/",
        "/businessprocesses/", "/tasks/", "/dataprocessors/",
        "/reports/", "/commonmodules/", "/eventsubscriptions/",
        "/scheduledjobs/", "/httpservices/", "/webservices/",
        "/definedtypes/", "/constants/", "/sequences/",
    ):
        if type_dir in path_lower:
            return (
                f"XML объекта метаданных ({type_dir.strip('/')}) — meta_edit "
                f"для правки (object_path='<TypeDir>/<Name>', definition с "
                f"add/modify/remove/set) или meta_compile для создания. "
                f"Структура объекта — meta_info."
            )
    # Generic fallback
    return (
        "XML — попробуй meta_edit (если это объект метаданных), "
        "subsystem-edit (если подсистема), form_edit (если форма). "
        "Если не уверен — skill_search('<что нужно сделать>')."
    )

# Папки в ext_src, в которые НЕЛЬЗЯ писать через write_file даже для .bsl/.txt
# (Configuration.xml и подобные строгие метаданные обновляются скиллами).
_FORBIDDEN_WRITE_FILENAMES = {"configuration.xml", "package.xml"}

# Пути, в которые НЕЛЬЗЯ писать НИКОГДА (защита Agenter от само-модификации
# LLM). Любой Edit/Write в пределах этих папок блокируется.
# Это: код самого Agenter, конфиг, скрипты, БД.
_FORBIDDEN_WRITE_PATH_FRAGMENTS = (
    "/agenter/app/",
    "/agenter/backend/",
    "/agenter/desktop/",
    "/agenter/frontend/",
    "/agenter/scripts/",
    "/agenter/config/",
    # /agenter/data/ убран целиком — это рабочая папка агента для MEMORY.md
    # и proposals/. Защищаем только конкретно опасные подпапки внутри:
    "/agenter/data/erp/snapshots/",  # snapshot zip'ы — управляет snapshots.py
    "/.venv/",
    "/venv/",
    "/site-packages/",
    "/agenter/.venv",
    "/.claude/",
    "/.git/",
)


# Типы ссылок которые нужно проверять на существование объекта в основной
# конфигурации. Полная карта prefix → имя XML-папки в SCHEME/.
# (Имена .xml внутри папки совпадают с именем объекта.)
_REF_PREFIX_TO_DIR = {
    "CatalogRef":                       "Catalogs",
    "DocumentRef":                      "Documents",
    "EnumRef":                          "Enums",
    "ChartOfCharacteristicTypesRef":    "ChartsOfCharacteristicTypes",
    "ChartOfAccountsRef":               "ChartsOfAccounts",
    "ChartOfCalculationTypesRef":       "ChartsOfCalculationTypes",
    "BusinessProcessRef":               "BusinessProcesses",
    "TaskRef":                          "Tasks",
    "ExchangePlanRef":                  "ExchangePlans",
    # Регистр-ссылки требуют отдельной обработки (через .RecordType) — пропускаем
}

# Sprint 2 S2.2: обратная карта — тип в meta_compile.definition → префикс ref.
# Используется для batch-aware preflight (см. _collect_self_declared_names).
_TYPE_TO_REF_PREFIX = {
    "Catalog":                       "CatalogRef",
    "Document":                      "DocumentRef",
    "Enum":                          "EnumRef",
    "Enumeration":                   "EnumRef",
    "ChartOfCharacteristicTypes":    "ChartOfCharacteristicTypesRef",
    "ChartOfAccounts":               "ChartOfAccountsRef",
    "ChartOfCalculationTypes":       "ChartOfCalculationTypesRef",
    "BusinessProcess":               "BusinessProcessRef",
    "Task":                          "TaskRef",
    "ExchangePlan":                  "ExchangePlanRef",
    # ru → ref
    "Справочник":                    "CatalogRef",
    "Документ":                      "DocumentRef",
    "Перечисление":                  "EnumRef",
    "БизнесПроцесс":                 "BusinessProcessRef",
    "Задача":                        "TaskRef",
    "ПланОбмена":                    "ExchangePlanRef",
    "ПланВидовХарактеристик":        "ChartOfCharacteristicTypesRef",
    "ПланСчетов":                    "ChartOfAccountsRef",
    "ПланВидовРасчета":              "ChartOfCalculationTypesRef",
}

# Regex для извлечения всех ссылок на объекты основной конфигурации из текста
# meta_compile definition. Ловит "CatalogRef.Склад", "DocumentRef.РТУ", etc.
_REF_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _REF_PREFIX_TO_DIR) + r")\."
    r"([A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)"
)


def _scan_objects_dir(root: Path) -> dict[str, set[str]]:
    """Сканирует одну корневую папку (SCHEME/ или ext_src/) и собирает
    {dir_name: {object_name}}. dir_name из _REF_PREFIX_TO_DIR.values()."""
    result: dict[str, set[str]] = {}
    for dir_name in _REF_PREFIX_TO_DIR.values():
        d = root / dir_name
        if not d.exists() or not d.is_dir():
            result[dir_name] = set()
            continue
        names: set[str] = set()
        for entry in d.iterdir():
            if entry.is_file() and entry.suffix.lower() == ".xml":
                names.add(entry.stem)
            elif entry.is_dir():
                names.add(entry.name)
        result[dir_name] = names
    return result


def _list_known_objects(
    scheme_path: str | None,
    ext_src_path: str | None = None,
) -> dict[str, set[str]] | None:
    """Возвращает объединённый {dir_name: {object_name}} из SCHEME/ + ext_src/.
    Пропускает проверку (None) если оба источника недоступны или ОБА пустые
    (значит SCHEME не выгружен и нет собственных объектов — не на чем
    основывать проверку).

    Объекты ext_src тоже валидные цели CatalogRef — это собственное расширение
    пользователя.

    Sprint 2 S2.3: на горячем пути используй _list_known_objects_cached —
    результат кэшируется в памяти, инвалидируется через
    invalidate_known_objects_cache() после успешных meta_compile/cfe_borrow.
    """
    sources: list[dict[str, set[str]]] = []
    if scheme_path:
        p = Path(scheme_path)
        if p.exists() and p.is_dir():
            sources.append(_scan_objects_dir(p))
    if ext_src_path:
        p = Path(ext_src_path)
        if p.exists() and p.is_dir():
            sources.append(_scan_objects_dir(p))
    if not sources:
        return None
    # Объединяем
    merged: dict[str, set[str]] = {}
    for src in sources:
        for k, v in src.items():
            merged.setdefault(k, set()).update(v)
    # Если всё пусто во ВСЕХ типах — SCHEME не выгружен, не блокируем
    total = sum(len(v) for v in merged.values())
    if total == 0:
        return None
    return merged


# Sprint 2 S2.3: ───────────────────────────────────────────────────────────
# Кэш known_objects.
#
# Проблема до Sprint 2: на каждой проверке PRE-FLIGHT (а это происходит на
# каждом meta_compile) мы сканировали SCHEME (~50 папок × сотни файлов) и
# ext_src. На большой задаче в 50+ tool calls это 50 повторных сканирований
# одного и того же дерева — лишние секунды и I/O.
#
# Решение: кэшируем результат по ключу (scheme_path, ext_src_path). Кэш
# инвалидируется после успешных meta_compile/cfe_borrow/meta_edit/cfe_init
# (PostToolUse hook) — потому что эти tools могут создать новые объекты.
# Read/Edit/Bash не инвалидируют — они не меняют каталог метаданных.

_KNOWN_OBJECTS_CACHE: dict[tuple[str, str], dict[str, set[str]] | None] = {}


def _list_known_objects_cached(
    scheme_path: str | None,
    ext_src_path: str | None = None,
) -> dict[str, set[str]] | None:
    """Кэшированная версия `_list_known_objects`. Прозрачно возвращает
    тот же тип. Промах кэша → один сканирующий вызов, hit → O(1)."""
    key = (str(scheme_path or ""), str(ext_src_path or ""))
    if key in _KNOWN_OBJECTS_CACHE:
        return _KNOWN_OBJECTS_CACHE[key]
    value = _list_known_objects(scheme_path, ext_src_path)
    _KNOWN_OBJECTS_CACHE[key] = value
    return value


def invalidate_known_objects_cache() -> None:
    """Сбрасывает кэш known_objects. Вызывается PostToolUse hook'ом после
    успешного meta_compile / cfe_borrow / meta_edit (add секция) /
    cfe_init и т.п. — то есть после операции, которая могла создать новый
    объект в ext_src."""
    _KNOWN_OBJECTS_CACHE.clear()


def _collect_self_declared_names(
    definition: object,
) -> dict[str, set[str]]:
    """Sprint 2 S2.2: для batch meta_compile собирает имена объектов,
    объявленных в самом batch'е. Эти имена считаются «доступными» для
    cross-reference внутри того же batch'а.

    Возвращает {dir_name: {object_name}} в формате как `_list_known_objects`.
    """
    items: list[dict] = []
    if isinstance(definition, list):
        items = [x for x in definition if isinstance(x, dict)]
    elif isinstance(definition, dict):
        items = [definition]

    result: dict[str, set[str]] = {}
    for it in items:
        # Поле "type" в meta_compile.definition — например "Catalog", "Document",
        # "Справочник" и т.п. Маппим в ref-префикс, оттуда — в dir_name.
        type_ = (it.get("type") or it.get("Тип") or "").strip()
        name  = (it.get("name") or it.get("Имя") or "").strip()
        if not type_ or not name:
            continue
        prefix = _TYPE_TO_REF_PREFIX.get(type_)
        if not prefix:
            continue
        dir_name = _REF_PREFIX_TO_DIR.get(prefix)
        if not dir_name:
            continue
        result.setdefault(dir_name, set()).add(name)
    return result


def _merge_known(
    base: dict[str, set[str]] | None,
    extra: dict[str, set[str]],
) -> dict[str, set[str]] | None:
    """Возвращает объединение (base ∪ extra). Не мутирует base."""
    if base is None:
        if extra:
            return {k: set(v) for k, v in extra.items()}
        return None
    merged: dict[str, set[str]] = {k: set(v) for k, v in base.items()}
    for k, v in extra.items():
        merged.setdefault(k, set()).update(v)
    return merged


def check_meta_compile_types(definition: object, known_objects: dict[str, set[str]] | None) -> str | None:
    """Проверяет что все CatalogRef.X / DocumentRef.X / ... в definition
    указывают на существующие объекты основной конфигурации.

    Если known_objects=None (SCHEME недоступен) — пропускаем проверку.

    Sprint 2 S2.2: для batch'а (definition=list) объекты, объявленные внутри
    самого batch'а, считаются «известными» — это снимает ложные PRE-FLIGHT
    блокировки на forward references внутри одного meta_compile (см. задача
    46689dc9, где агент 15 turns делал заглушки `String(36)`).

    Возвращает None если всё ок, иначе строка с описанием проблемы для LLM."""
    if known_objects is None:
        return None

    # Sprint 2 S2.2: расширяем known_objects объектами, объявленными в batch'е.
    self_declared = _collect_self_declared_names(definition)
    effective_known = _merge_known(known_objects, self_declared) or known_objects

    # Сериализуем definition в JSON чтобы прогнать regex
    try:
        text = json.dumps(definition, ensure_ascii=False)
    except (TypeError, ValueError):
        return None

    missing: dict[str, set[str]] = {}  # prefix → {имена которых нет}
    for match in _REF_RE.finditer(text):
        prefix = match.group(1)
        obj_name = match.group(2)
        # Объекты собственного расширения (с префиксом расширения) — пропускаем:
        # их пока нет в основной конфигурации, но они будут существовать после
        # текущего batch. Эвристика: имя содержит подчёркивание после префикса.
        # Точнее: они и не в основной — поэтому есть в ext_src. Тут не проверяем.
        dir_name = _REF_PREFIX_TO_DIR[prefix]
        known = effective_known.get(dir_name, set())
        if obj_name not in known:
            missing.setdefault(prefix, set()).add(obj_name)

    if not missing:
        return None

    parts = []
    for prefix, names in missing.items():
        parts.append(
            f"{prefix}: {', '.join(sorted(names))}"
        )
    return (
        "PRE-FLIGHT BLOCKED: в JSON определении объекта упомянуты типы, которых "
        "нет в основной конфигурации этого пользователя:\n  "
        + "\n  ".join(parts)
        + "\n\nЧто делать:\n"
        "  1. Если ты ВЫДУМАЛ имена справочников — спроси у пользователя точные "
        "имена существующих справочников в его базе.\n"
        "  2. Если имена правильные — используй bsl_metadatasearch чтобы найти "
        "реальные имена объектов; если результат пуст — SCHEME не индексирован, "
        "тогда читай SCHEME/Configuration.xml напрямую через Read.\n"
        "  3. Если объект ещё не создан в расширении (но создаётся в этой "
        "же задаче) — используй batch meta_compile с объявлением объекта-предка "
        "в том же массиве (PRE-FLIGHT теперь видит self-declared names).\n"
        "  4. Если объект должен быть в ext_src/ собственного расширения — "
        "также его сначала надо создать.\n"
        "Никаких CatalogRef.Угаданное-Имя. Только проверенные."
    )


# Sprint 2 S2.2: топологический порядок внутри batch meta_compile.
# Используется в desktop/main.py:_meta_compile чтобы перед записью JSON во
# временный файл расположить элементы в правильном порядке создания.

def topological_sort_meta_definitions(
    definition: object,
) -> tuple[object, list[str]]:
    """Сортирует batch meta_compile топологически по cross-references внутри.

    Возвращает (sorted_definition, notes). Если definition не array или
    зависимости отсутствуют — возвращает исходник без изменений. Если
    обнаружен цикл — возвращает исходный порядок и заметку про цикл (caller
    решает, что делать; обычно meta_compile сам выдаст ошибку с деталями).

    notes — список человекочитаемых сообщений (для лога), например:
    «Переставлено: Catalog.A теперь до Document.B».
    """
    if not isinstance(definition, list):
        return definition, []
    items: list[dict] = [x if isinstance(x, dict) else {} for x in definition]
    if len(items) < 2:
        return definition, []

    # Маппинг "TypePrefix.Name" → индекс
    name_to_idx: dict[str, int] = {}
    for i, it in enumerate(items):
        type_ = (it.get("type") or it.get("Тип") or "").strip()
        name  = (it.get("name") or it.get("Имя") or "").strip()
        if type_ and name:
            prefix = _TYPE_TO_REF_PREFIX.get(type_)
            if prefix:
                name_to_idx[f"{prefix}.{name}"] = i

    # Зависимости: для каждого item — индексы тех, на кого он ссылается
    deps: list[set[int]] = [set() for _ in items]
    for i, it in enumerate(items):
        try:
            text = json.dumps(it, ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        for match in _REF_RE.finditer(text):
            full_ref = f"{match.group(1)}.{match.group(2)}"
            target = name_to_idx.get(full_ref)
            if target is not None and target != i:
                deps[i].add(target)

    # Если зависимостей нет — ничего не меняем
    if not any(deps):
        return definition, []

    # Kahn's algorithm со стабильностью (детям с равной готовностью —
    # сохраняем исходный порядок).
    in_degree = [len(d) for d in deps]
    children: list[list[int]] = [[] for _ in items]
    for i, d in enumerate(deps):
        for parent in d:
            children[parent].append(i)
    ready = [i for i, deg in enumerate(in_degree) if deg == 0]
    ready.sort()
    order: list[int] = []
    while ready:
        i = ready.pop(0)
        order.append(i)
        for c in children[i]:
            in_degree[c] -= 1
            if in_degree[c] == 0:
                ready.append(c)
        ready.sort()

    if len(order) != len(items):
        # Цикл — оставляем как есть, пишем заметку
        return definition, [
            "topo_sort: обнаружен цикл зависимостей, batch оставлен без "
            "переупорядочивания"
        ]

    if order == list(range(len(items))):
        return definition, []  # уже в правильном порядке

    notes = [
        f"topo_sort: переупорядочено {sum(1 for i, j in enumerate(order) if i != j)} элементов "
        f"для корректного порядка создания (cross-references внутри batch'а)"
    ]
    return [items[i] for i in order], notes


def check_tool_call(
    tool_name: str,
    tool_input: dict,
    history: list[dict],
    *,
    known_objects: dict[str, set[str]] | None = None,
    stage_dispatch_required: bool = False,
    current_stage: dict | None = None,
) -> str | None:
    """
    Проверяет вызов tool ДО его выполнения.
    Возвращает None если вызов разрешён.
    Возвращает строку с сообщением об ошибке если вызов запрещён —
    эта строка попадёт обратно в LLM как is_error=True.

    history — список словарей вида {"tool": str, "ok": bool, "params": dict}
    — все tool calls текущей задачи. Используется для проверки последовательности
    (например db_load требует cfe_validate в истории).

    Sprint 4 S4.5:
      stage_dispatch_required: bool — True для L2+ задач. Если план ещё
        не построен (current_stage = None) — все модифицирующие tools
        блокируются с подсказкой вызвать plan_task.
      current_stage: dict | None — текущая активная стадия задачи. Если
        задана — разрешены только expected_tool этой стадии + always-allowed.
    """
    # Sprint 4 S4.5: Stage dispatch — ПЕРВЫЙ приоритет, до всех остальных правил.
    # Это самое сильное ограничение, оно заворачивает агента в правильный маршрут
    # ещё до того, как сработают остальные guard'ы (которые ловят ошибки post-hoc).
    if stage_dispatch_required:
        try:
            from task_planner import is_tool_allowed_for_stage
            allowed, reason = is_tool_allowed_for_stage(
                tool_name, current_stage, tool_input=tool_input,
            )
            if not allowed:
                stage_info = ""
                if current_stage:
                    stage_info = (
                        f"\n\nТекущая стадия #{current_stage.get('index')}: "
                        f"[{current_stage.get('kind')}] {current_stage.get('description', '')[:80]}\n"
                        f"Ожидаемый tool: {current_stage.get('expected_tool', '?')}"
                    )
                return f"GUARD BLOCKED (stage-dispatch): {reason}{stage_info}"
        except ImportError:
            # task_planner не доступен — пропускаем эту проверку, остальные guard'ы сработают
            pass

    # ── R3/R4: deprecated tools → подсказка на современный аналог ──────
    if tool_name in _DEPRECATED_REPLACEMENTS:
        replacement = _DEPRECATED_REPLACEMENTS[tool_name]
        return (
            f"GUARD BLOCKED: '{tool_name}' DEPRECATED, не использовать. "
            f"Переключись на: {replacement}. "
            f"Если ты вызвал этот tool по привычке — это сигнал что маршрут "
            f"задачи неправильный, переосмысли подход."
        )

    # ── Защита кода Agenter от само-модификации (любой write-tool) ──
    # Применяется ко всем tool'ам, которые пишут на диск: write_file (legacy),
    # Write/Edit (built-in SDK). Имя файла берём из разных ключей в зависимости
    # от tool'а.
    if tool_name in ("write_file", "Write", "Edit"):
        path = (
            (tool_input or {}).get("path")
            or (tool_input or {}).get("file_path")
            or ""
        )
        if path:
            normalized = path.replace("\\", "/").lower()
            for forbidden in _FORBIDDEN_WRITE_PATH_FRAGMENTS:
                if forbidden in normalized:
                    return (
                        f"GUARD BLOCKED: запись в '{path}' запрещена — "
                        f"это код или служебные файлы Agenter (фрагмент "
                        f"'{forbidden.strip('/')}'). LLM НЕ должен "
                        f"модифицировать собственное окружение. Если ты пытался "
                        f"исправить баг в Agenter — это работа разработчика, "
                        f"не агента. Расскажи о проблеме в финальном ответе."
                    )

    # ── R4: запрет Write/Edit для XML метаданных ─────────────────────────
    # Sprint 2 hotfix-5 (2026-05-16): расширено на Edit. Раньше guard ловил
    # только Write, и агент мог легко обойти его: Read → Edit с regex-заменой
    # на структурном XML. На задаче «включи Острова в подсистему Финансы»
    # агент именно так и сделал — Edit'ом ломал Subsystems/Финансы.xml,
    # затем выдумал что «расширения 1С не позволяют» и удалил подсистему.
    # Edit XML структурных типов теперь блокируется с конкретной подсказкой
    # по типу пути.
    if tool_name in ("write_file", "Write", "Edit"):
        path = (
            (tool_input or {}).get("path")
            or (tool_input or {}).get("file_path")
            or ""
        )
        if path:
            pp = PurePosixPath(path.replace("\\", "/"))
            ext = pp.suffix.lower()
            name = pp.name.lower()
            full_lower = str(pp).lower()
            if ext in _FORBIDDEN_WRITE_EXTS:
                hint = _xml_path_hint(full_lower)
                op = "правка" if tool_name == "Edit" else "запись"
                return (
                    f"GUARD BLOCKED: {op} XML-файла '{path}' запрещена. "
                    f"XML метаданных имеют специфичную структуру (namespace, "
                    f"UUID-ы, ChildObjects, companion-блоки) — Edit/Write с "
                    f"regex почти всегда ломает её.\n\n"
                    f"Правильный путь: {hint}\n\n"
                    f"Если нужного инструмента не помнишь — вызови "
                    f"skill_search с описанием задачи, он найдёт подходящий "
                    f"скилл из ~60 готовых."
                )
            if name in _FORBIDDEN_WRITE_FILENAMES:
                return (
                    f"GUARD BLOCKED: правка '{name}' запрещена. "
                    f"Этот файл управляется скиллами (meta_compile / cfe_borrow / "
                    f"meta_remove). Если нужно изменить состав расширения — "
                    f"используй их, не Edit вручную."
                )

    # ── R7: db_load требует cfe_validate без errors в истории ────────────
    if tool_name == "db_load":
        # Найдём последний cfe_validate в истории
        last_validate = None
        for entry in reversed(history):
            if entry.get("tool") == "cfe_validate":
                last_validate = entry
                break
        if last_validate is None:
            return (
                "GUARD BLOCKED: db_load без предварительного cfe_validate. "
                "Сначала вызови cfe_validate и убедись что 0 errors — потом db_load. "
                "Это финальный шаг, после него правки попадут в реальную БД 1С."
            )
        if not last_validate.get("ok", True):
            return (
                "GUARD BLOCKED: последний cfe_validate завершился с ошибкой. "
                "Прочитай его вывод, точечно исправь проблемы, повтори cfe_validate. "
                "db_load с failed validate запрещён."
            )

    # ── meta_compile: pre-flight проверка существования типов ────────────
    # Ловит ошибку «Неизвестное имя типа CatalogRef.X» ДО db_load, а не на нём.
    if tool_name == "meta_compile":
        definition = (tool_input or {}).get("definition")
        if definition is not None and known_objects is not None:
            # definition может быть JSON-строкой (если LLM передал string)
            if isinstance(definition, str):
                try:
                    definition = json.loads(definition)
                except json.JSONDecodeError:
                    pass  # пусть meta_compile сам отреагирует
            err = check_meta_compile_types(definition, known_objects)
            if err:
                return err

    return None  # вызов разрешён


def record_call(tool_name: str, params: dict, ok: bool) -> dict:
    """Создаёт запись для history после выполнения tool."""
    return {"tool": tool_name, "params": params or {}, "ok": ok}
