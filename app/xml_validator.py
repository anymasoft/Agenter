"""
Валидация XML 1С по предсгенерированным JSON-схемам XDTO платформы.

Использует ресурсы из agenter/app/data/xsd/ (27 файлов JSON, конвертированных
из XSD платформы 1С). Каждая схема описывает:
    - roots: допустимые корневые элементы
    - elements: для каждого элемента — children, childMin, childMax, simpleType

Порт из MetadataViewer1C/src/validation/xmlStructureValidator.ts + schemaMapping.ts.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Папка со схемами относительно этого файла
_XSD_DIR = Path(__file__).parent / "data" / "xsd"

# Маппинг логических имён схем на файлы (как в TS-версии)
_SCHEMA_FILES: dict[str, str] = {
    "metadata": "MDClasses.json",
    "form": "XcfLogForm.json",
    "dcs": "DcsSchema.json",
    "predefined": "XcfPredef.json",
    "dumpinfo": "XcfDumpInfo.json",
    "spreadsheet": "DataSpreadsheet.json",
    "roles": "Roles.json",
}

# Локальные имена тегов, которые часто повторяются в выгрузке 1С
_REPEATING_TAGS = frozenset({"StandardTabularSection", "StandardAttribute", "Item", "item"})

# Теги, специфичные для расширений (CFE). Не описаны в публичной XSD-схеме
# MDClasses, но валидны в файлах ext_src/. Игнорируем как недопустимые в
# extension-режиме (см. validate_xml_file(..., extension_mode=True)).
_EXTENSION_SPECIFIC_TAGS = frozenset(
    {
        "ObjectBelonging",
        "ConfigurationExtensionPurpose",
        "KeepMappingToExtendedConfigurationObjectsByIDs",
        "ExtendedConfigurationObject",
        "GeneratedType",
        "Categories",
        "NamePrefix",
        "ExtendedConfigurationObjectsAdoptionTypes",
        "Adopted",
        "ConfigurationExtensionCompatibilityMode",
        "DefaultRunMode",
    }
)

# Объекты метаданных, для которых root=MetaDataObject
_METADATA_OBJECT_TYPES = frozenset(
    {
        "Document", "Catalog", "Report", "DataProcessor", "Enum", "Constant",
        "InformationRegister", "AccumulationRegister", "AccountingRegister",
        "CalculationRegister", "CommonModule", "Subsystem", "Role",
        "SessionParameter", "CommonForm", "CommonTemplate",
        "ChartOfCalculationTypes", "ChartOfCharacteristicTypes", "ChartOfAccounts",
        "BusinessProcess", "Task", "ExchangePlan", "DocumentJournal",
        "DefinedType", "CommonAttribute", "EventSubscription", "ScheduledJob",
        "CommonCommand", "CommandGroup", "WebService", "HTTPService",
        "FunctionalOption", "FunctionalOptionsParameter", "StyleItem", "Style",
        "WSReference", "ExternalDataSource", "DocumentNumerator", "Sequence",
        "FilterCriterion", "XDTOPackage",
    }
)

_NS_PATTERN = re.compile(r"^\{[^}]+\}")
_ROOT_TAG_PATTERN = re.compile(r"<([^\s/>!?][^\s/>]*)")


@dataclass
class ValidationResult:
    """Результат валидации XML по JSON-схеме."""

    valid: bool
    schema_name: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---- Загрузка схем (кэш в LRU) -----------------------------------------------


@lru_cache(maxsize=32)
def _load_schema(name: str) -> Optional[dict]:
    """Загружает JSON-схему по логическому имени или имени файла."""
    file_name = _SCHEMA_FILES.get(name, name)
    if not file_name.endswith(".json"):
        file_name = f"{file_name}.json"
    schema_path = _XSD_DIR / file_name
    if not schema_path.exists():
        return None
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_available_schemas() -> list[str]:
    """Список логических имён доступных схем."""
    return [name for name in _SCHEMA_FILES if _load_schema(name) is not None]


# ---- Определение схемы для XML -----------------------------------------------


def get_schema_name_for_xml(
    xml_path: Optional[str | Path] = None,
    xml_content: Optional[str] = None,
    root_tag: Optional[str] = None,
    object_type: Optional[str] = None,
) -> Optional[str]:
    """Определяет логическое имя схемы для XML.

    Можно передать любую комбинацию параметров — отсутствующие
    выводятся автоматически (например, root_tag из xml_content).
    """
    file_path = str(xml_path) if xml_path else ""

    if not root_tag and xml_content:
        root_tag = _extract_root_tag(xml_content)

    if not root_tag and xml_path:
        # Попробуем прочитать первые 4 KB чтобы определить root
        try:
            with open(xml_path, "rb") as f:
                head = f.read(4096).decode("utf-8", errors="ignore")
            root_tag = _extract_root_tag(head)
        except OSError:
            return None

    # Приоритеты, как в TS-версии
    if root_tag == "MetaDataObject" or (object_type and object_type in _METADATA_OBJECT_TYPES):
        return "metadata"
    if root_tag == "Form" or file_path.endswith("Form.xml"):
        return "form"
    if root_tag == "DataCompositionSchema" or (
        "Report" in file_path and file_path.endswith("Template.xml")
    ):
        return "dcs"
    if file_path.endswith("Template.xml") and "Report" not in file_path:
        return "spreadsheet"
    if root_tag == "PredefinedData" or file_path.endswith("Predefined.xml"):
        return "predefined"
    if root_tag == "ConfigDumpInfo" or file_path.endswith("ConfigDumpInfo.xml"):
        return "dumpinfo"
    if file_path.endswith("Rights.xml") or root_tag == "Rights":
        return "roles"

    return None


def _extract_root_tag(xml: str) -> Optional[str]:
    """Извлекает имя корневого тега из строки XML."""
    # Убираем BOM
    if xml and xml[0] == "﻿":
        xml = xml[1:]
    # Пропускаем XML-декларацию
    xml = re.sub(r"<\?xml[^?]+\?>", "", xml, count=1).lstrip()
    match = _ROOT_TAG_PATTERN.search(xml)
    if not match:
        return None
    tag = match.group(1)
    # Снимаем namespace-префикс: dcsset:settings → settings
    if ":" in tag:
        tag = tag.split(":", 1)[1]
    return tag


# ---- Валидация ---------------------------------------------------------------


def validate_xml_file(
    xml_path: str | Path,
    *,
    schema_name: Optional[str] = None,
    object_type: Optional[str] = None,
    max_errors: int = 100,
    extension_mode: bool = False,
) -> ValidationResult:
    """Валидирует XML-файл по подходящей JSON-схеме.

    Если schema_name не задан, схема определяется автоматически по rootTag
    и имени файла. Если схема не нужна (например, для неизвестных файлов),
    результат valid=True.
    """
    path = Path(xml_path)
    if not path.exists():
        return ValidationResult(
            valid=False, errors=[f"Файл не найден: {xml_path}"]
        )

    # Определяем схему
    if schema_name is None:
        schema_name = get_schema_name_for_xml(
            xml_path=path, object_type=object_type
        )

    if schema_name is None:
        # Для неизвестных файлов считаем валидным
        return ValidationResult(valid=True, schema_name=None)

    schema = _load_schema(schema_name)
    if schema is None:
        return ValidationResult(
            valid=True,
            schema_name=schema_name,
            warnings=[f"Схема {schema_name!r} не найдена в data/xsd/"],
        )

    # Парсим XML
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        return ValidationResult(
            valid=False,
            schema_name=schema_name,
            errors=[f"Ошибка парсинга XML: {e}"],
        )

    root_elem = tree.getroot()
    root_local = _strip_ns(root_elem.tag)

    errors: list[str] = []

    # Проверка корневого элемента
    schema_roots = schema.get("roots", [])
    if schema_roots and root_local not in schema_roots:
        errors.append(
            f"Корневой элемент {root_local!r} не входит в допустимые: "
            f"{', '.join(schema_roots[:5])}..."
        )

    # Валидируем рекурсивно
    _validate_element(root_elem, schema, "", errors, max_errors)

    # Убираем ложные срабатывания для ChartOfAccounts.StandardTabularSection
    errors = _strip_false_positives_chart_of_accounts(errors, root_elem)

    # В extension-режиме переводим в warnings:
    #   - все ошибки про extension-specific теги (ObjectBelonging и т.п.)
    #   - все minOccurs (расширение может правомерно не содержать обязательных детей)
    warnings: list[str] = []
    if extension_mode:
        filtered: list[str] = []
        for err in errors:
            is_ext_tag = any(tag in err for tag in _EXTENSION_SPECIFIC_TAGS)
            is_min_occurs = (
                "minOccurs=" in err
                or "ожидается минимум" in err
                or "обязательный элемент" in err
            )
            if is_ext_tag or is_min_occurs:
                warnings.append(f"[ext] {err}")
            else:
                filtered.append(err)
        errors = filtered

    return ValidationResult(
        valid=len(errors) == 0,
        schema_name=schema_name,
        errors=errors[:max_errors],
        warnings=warnings[:max_errors],
    )


def _strip_ns(tag: str) -> str:
    """{http://...}Tag → Tag."""
    return _NS_PATTERN.sub("", tag)


def _validate_element(
    elem: ET.Element,
    schema: dict,
    path: str,
    errors: list[str],
    max_errors: int,
) -> None:
    """Рекурсивно валидирует элемент по схеме."""
    if len(errors) >= max_errors:
        return

    elem_local = _strip_ns(elem.tag)
    elements_def = schema.get("elements", {})
    elem_def = elements_def.get(elem_local)

    if not elem_def or elem_def.get("simpleType") or elem_def.get("allowAny"):
        return

    # Собираем счётчики дочерних элементов (с учётом повторов)
    child_counts: Counter[str] = Counter()
    children_by_local: dict[str, list[ET.Element]] = {}
    for child in elem:
        local = _strip_ns(child.tag)
        child_counts[local] += 1
        children_by_local.setdefault(local, []).append(child)

    allowed_children = set(elem_def.get("children", []))
    child_min = elem_def.get("childMin", {})
    child_max = elem_def.get("childMax", {})

    # Проверка: все дочерние элементы должны быть допустимы
    for child_local in child_counts:
        if child_local not in allowed_children:
            # Может быть в общем словаре elements — тогда warn только если совсем неизвестен
            if child_local not in elements_def:
                if len(errors) < max_errors:
                    errors.append(
                        f"{path}{elem_local}: недопустимый дочерний элемент {child_local!r}"
                    )
        else:
            count = child_counts[child_local]
            min_val = child_min.get(child_local, 0)
            max_val = child_max.get(child_local, -1)
            if min_val > 0 and count < min_val:
                if len(errors) < max_errors:
                    errors.append(
                        f"{path}{elem_local}/{child_local}: ожидается минимум "
                        f"{min_val}, найдено {count}"
                    )
            if max_val >= 0 and count > max_val:
                if len(errors) < max_errors:
                    errors.append(
                        f"{path}{elem_local}/{child_local}: ожидается максимум "
                        f"{max_val}, найдено {count}"
                    )

    # Проверка обязательных детей
    for child_local in allowed_children:
        min_val = child_min.get(child_local, 0)
        count = child_counts.get(child_local, 0)
        if min_val > 0 and count < min_val:
            if len(errors) < max_errors:
                errors.append(
                    f"{path}{elem_local}: обязательный элемент {child_local!r} "
                    f"отсутствует (minOccurs={min_val})"
                )

    # Рекурсия в детей
    for child_local, child_list in children_by_local.items():
        if child_local not in elements_def:
            continue
        child_schema = elements_def[child_local]
        if child_schema.get("simpleType"):
            continue
        for child in child_list:
            _validate_element(
                child, schema, f"{path}{elem_local}/", errors, max_errors
            )


def _strip_false_positives_chart_of_accounts(
    errors: list[str], root_elem: ET.Element
) -> list[str]:
    """Снимает ложные срабатывания minOccurs для ChartOfAccounts/StandardTabularSection.

    fast-xml-parser в TS-версии теряет повторяющиеся одноимённые элементы;
    ET в Python не теряет, но оставляем правило на случай рассинхрона.
    """
    return errors


# ---- Bulk-валидация ----------------------------------------------------------


@dataclass
class BulkValidationResult:
    """Результат валидации множества файлов."""

    checked_files: int = 0
    files_with_errors: int = 0
    files_with_warnings: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    by_schema: dict[str, int] = field(default_factory=dict)
    errors_by_file: dict[str, list[str]] = field(default_factory=dict)
    warnings_by_file: dict[str, list[str]] = field(default_factory=dict)


def validate_directory(
    root: str | Path,
    *,
    pattern: str = "*.xml",
    max_files: Optional[int] = None,
    max_errors_per_file: int = 20,
    extension_mode: bool = False,
) -> BulkValidationResult:
    """Валидирует все XML-файлы в директории рекурсивно.

    extension_mode=True — для папок ext_src: extension-specific теги
    (ObjectBelonging, ConfigurationExtensionPurpose, ...) переносятся
    из errors в warnings.
    """
    result = BulkValidationResult()
    root_path = Path(root)
    if not root_path.exists():
        return result

    files = list(root_path.rglob(pattern))
    if max_files is not None:
        files = files[:max_files]

    for file_path in files:
        try:
            res = validate_xml_file(
                file_path,
                max_errors=max_errors_per_file,
                extension_mode=extension_mode,
            )
        except Exception as e:  # noqa: BLE001
            result.errors_by_file[str(file_path)] = [f"Внутренняя ошибка: {e}"]
            result.files_with_errors += 1
            result.checked_files += 1
            continue

        result.checked_files += 1
        if res.schema_name:
            result.by_schema[res.schema_name] = result.by_schema.get(res.schema_name, 0) + 1
        if res.errors:
            result.files_with_errors += 1
            result.total_errors += len(res.errors)
            result.errors_by_file[str(file_path)] = res.errors
        if res.warnings:
            result.files_with_warnings += 1
            result.total_warnings += len(res.warnings)
            result.warnings_by_file[str(file_path)] = res.warnings

    return result


def summarize_errors(errors: list[str], limit: int = 20) -> str:
    """Формирует краткое сообщение об ошибках."""
    if not errors:
        return ""
    head = errors[:limit]
    suffix = f" ... (+{len(errors) - limit} ещё)" if len(errors) > limit else ""
    return "; ".join(head) + suffix
