"""
Универсальный парсер MetaDataObject XML.

Парсит любой объект метаданных 1С (Catalog, Document, Register, Enum, ...) в
обобщённую модель ParsedMetadataObject. Снимает namespace-префиксы, рекурсивно
обходит ChildObjects с лимитами по глубине и количеству элементов.

Порт из MetadataViewer1C/src/metadata_utils/UniversalMetadataParser.ts.
Использует стандартный xml.etree.ElementTree, без внешних зависимостей.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .metadata_scanner import MetadataFileRef
from .unicode_name import decode_1c_unicode_escapes

# Атрибутивные имена реквизитов в разных типах объектов 1С
_ATTRIBUTE_KINDS = frozenset(
    {
        "Attribute",
        "Dimension",
        "Resource",
        "Measure",
        "AccountingFlag",
        "ExtDimensionAccountingFlag",
        "Characteristic",
        "Requisite",
        "Recalculation",
        "AddressingAttribute",
    }
)

# Лимиты обхода (защита от циклов / гигантских объектов)
MAX_DEPTH = 5
MAX_MEMBERS = 50_000

# Регекс снятия namespace-префикса вида {http://...}TagName
_NS_PATTERN = re.compile(r"^\{[^}]+\}")


# ---- Модели данных -----------------------------------------------------------


@dataclass
class MetadataMember:
    """Один член объекта (реквизит, табчасть, форма, команда, ...)."""

    kind: str
    """Тип члена: Attribute, TabularSection, Form, Command, Template, ..."""

    name: Optional[str] = None
    """Имя из Properties.Name или из атрибута name."""

    path: list[str] = field(default_factory=list)
    """Путь в иерархии для UI/поиска/диффа.
    Пример: ['ChildObjects', 'TabularSection', 'Товары', 'ChildObjects', 'Attribute', 'Номенклатура']
    """

    properties: dict[str, Any] = field(default_factory=dict)
    """Плоский словарь свойств из <Properties> без ns-префиксов."""


@dataclass
class ParsedMetadataObject:
    """Распарсенный объект метаданных в обобщённой модели."""

    object_type: str
    """Catalog, Document, Subsystem, AccumulationRegister, ..."""

    object_type_dir: Optional[str] = None
    """Catalogs, Documents, Subsystems, AccumulationRegisters, ..."""

    name: str = ""
    """Логическое имя (из Properties.Name, если есть)."""

    display_name: str = ""
    """Декодированное имя для UI."""

    source_path: str = ""
    """Путь к исходному XML."""

    properties: dict[str, Any] = field(default_factory=dict)
    """Свойства объекта (без ns-префиксов)."""

    members: list[MetadataMember] = field(default_factory=list)
    """Все дочерние элементы (flatten)."""

    # Быстрые индексы по типам членов
    attributes: list[MetadataMember] = field(default_factory=list)
    tabular_sections: list[MetadataMember] = field(default_factory=list)
    forms: list[MetadataMember] = field(default_factory=list)
    commands: list[MetadataMember] = field(default_factory=list)
    templates: list[MetadataMember] = field(default_factory=list)
    predefined: list[MetadataMember] = field(default_factory=list)


# ---- Парсинг -----------------------------------------------------------------


def parse_metadata_object(ref: MetadataFileRef) -> ParsedMetadataObject:
    """Парсит главный XML объекта метаданных в обобщённую модель.

    Raises:
        ValueError: если XML невалиден или не содержит <MetaDataObject>.
    """
    try:
        tree = ET.parse(ref.main_xml_path)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error in {ref.main_xml_path}: {e}") from e

    root_elem = tree.getroot()

    # Корень должен называться MetaDataObject (с любым ns-префиксом)
    if _strip_ns(root_elem.tag) != "MetaDataObject":
        raise ValueError(
            f"Invalid metadata in {ref.main_xml_path}: root is "
            f"{_strip_ns(root_elem.tag)!r}, expected MetaDataObject"
        )

    # Первый ребёнок — это конкретный тип объекта (Catalog, Document, ...)
    children = list(root_elem)
    if not children:
        raise ValueError(
            f"Invalid metadata in {ref.main_xml_path}: empty MetaDataObject"
        )

    obj_elem = children[0]
    object_type = _strip_ns(obj_elem.tag)

    # Свойства верхнего уровня
    props_elem = _find_child(obj_elem, "Properties")
    properties = _parse_properties(props_elem) if props_elem is not None else {}

    # Определяем имя
    name = _detect_object_name(obj_elem, properties, ref.display_name)

    # Обход ChildObjects
    child_objects_elem = _find_child(obj_elem, "ChildObjects")
    members = (
        _parse_child_objects_deep(child_objects_elem)
        if child_objects_elem is not None
        else []
    )

    # Быстрые срезы
    attributes = [m for m in members if m.kind in _ATTRIBUTE_KINDS]
    tabular_sections = [m for m in members if m.kind == "TabularSection"]
    forms = [m for m in members if m.kind == "Form"]
    commands = [m for m in members if m.kind == "Command"]
    templates = [m for m in members if m.kind in ("Template", "Layout")]

    parsed = ParsedMetadataObject(
        object_type=object_type,
        object_type_dir=ref.object_type_dir,
        name=name,
        display_name=decode_1c_unicode_escapes(name) or ref.display_name,
        source_path=str(ref.main_xml_path),
        properties=properties,
        members=members,
        attributes=attributes,
        tabular_sections=tabular_sections,
        forms=forms,
        commands=commands,
        templates=templates,
        predefined=[],  # заполняется отдельно через predefined_parser
    )

    return parsed


# ---- Хелперы -----------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    """Снимает namespace-префикс {http://...}Tag → Tag."""
    return _NS_PATTERN.sub("", tag)


def _find_child(elem: ET.Element, name: str) -> Optional[ET.Element]:
    """Находит первого ребёнка по локальному имени (игнорируя namespace)."""
    for child in elem:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _find_children(elem: ET.Element, name: str) -> list[ET.Element]:
    """Находит всех детей по локальному имени."""
    return [child for child in elem if _strip_ns(child.tag) == name]


def _parse_properties(props_elem: ET.Element) -> dict[str, Any]:
    """Превращает <Properties> в плоский словарь."""
    result: dict[str, Any] = {}
    for child in props_elem:
        key = _strip_ns(child.tag)
        result[key] = _element_to_value(child)
    return result


def _element_to_value(elem: ET.Element) -> Any:
    """Конвертирует элемент в простое значение: текст, словарь, или список."""
    # Простой текстовый узел без детей
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        # Атрибуты (например <Value xsi:type="...">) добавляем как __attrs__
        if elem.attrib:
            return {"_text": text, **_clean_attrs(elem.attrib)}
        return text

    # Несколько детей — собираем как словарь (по локальным именам)
    result: dict[str, Any] = {}
    for child in children:
        key = _strip_ns(child.tag)
        value = _element_to_value(child)
        if key in result:
            # Преобразуем в список при повторе
            if isinstance(result[key], list):
                result[key].append(value)
            else:
                result[key] = [result[key], value]
        else:
            result[key] = value
    # Текст между тегами обычно служебный — игнорируем
    return result


def _clean_attrs(attrib: dict[str, str]) -> dict[str, str]:
    """Снимает namespace с ключей атрибутов."""
    return {_strip_ns(k): v for k, v in attrib.items()}


def _detect_object_name(
    obj_elem: ET.Element, properties: dict[str, Any], fallback: str
) -> str:
    """Пытается определить логическое имя объекта."""
    # 1. Из Properties.Name
    name_from_props = properties.get("Name")
    if isinstance(name_from_props, str) and name_from_props.strip():
        return name_from_props.strip()
    if isinstance(name_from_props, dict):
        text = name_from_props.get("_text") or ""
        if text.strip():
            return text.strip()

    # 2. Из атрибута name самого объекта
    attr_name = obj_elem.attrib.get("name")
    if attr_name and attr_name.strip():
        return attr_name.strip()

    return fallback


def _parse_child_objects_deep(child_objects_elem: ET.Element) -> list[MetadataMember]:
    """Рекурсивный обход ChildObjects с flatten в плоский список."""
    members: list[MetadataMember] = []
    _walk_children(child_objects_elem, ["ChildObjects"], 0, members)
    return members


def _walk_children(
    node: ET.Element, parent_path: list[str], depth: int, out: list[MetadataMember]
) -> None:
    """Рекурсивно обходит ChildObjects-узлы."""
    if depth > MAX_DEPTH or len(out) >= MAX_MEMBERS:
        return

    for child in node:
        if len(out) >= MAX_MEMBERS:
            return

        kind = _strip_ns(child.tag)
        # Свойства этого подэлемента
        props_elem = _find_child(child, "Properties")
        props = _parse_properties(props_elem) if props_elem is not None else {}

        # Имя
        name = props.get("Name")
        if isinstance(name, dict):
            name = name.get("_text")
        if not isinstance(name, str) or not name.strip():
            name = child.attrib.get("name") or f"_{len(out)}"
        else:
            name = name.strip()

        member_path = [*parent_path, kind, name]

        out.append(
            MetadataMember(
                kind=kind,
                name=name,
                path=member_path,
                properties=props,
            )
        )

        # Рекурсия: если у элемента есть вложенный ChildObjects
        nested_child_objects = _find_child(child, "ChildObjects")
        if nested_child_objects is not None:
            _walk_children(
                nested_child_objects,
                [*member_path, "ChildObjects"],
                depth + 1,
                out,
            )


# ---- Утилиты экспорта --------------------------------------------------------


def to_metadata_key(obj: ParsedMetadataObject) -> str:
    """Стабильный ключ для UI/индекса: <TypeDir>/<Name>."""
    type_part = obj.object_type_dir or obj.object_type
    return f"{type_part}/{obj.name}"


def parse_many(
    refs: Iterable[MetadataFileRef],
) -> tuple[list[ParsedMetadataObject], list[str]]:
    """Парсит список ссылок последовательно. Возвращает (объекты, ошибки)."""
    parsed: list[ParsedMetadataObject] = []
    errors: list[str] = []
    for ref in refs:
        try:
            parsed.append(parse_metadata_object(ref))
        except Exception as e:  # noqa: BLE001
            errors.append(f"Parse failed: {ref.main_xml_path}: {e}")
    return parsed, errors
