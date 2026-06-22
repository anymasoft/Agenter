"""
Парсер Ext/Predefined.xml.

Формат:
    <PredefinedData ...>
      <Item id="...">
        <Name>...</Name>
        <IsFolder>true|false</IsFolder>
        ...
      </Item>
    </PredefinedData>

Сохраняет все поля в properties без типизации (максимальное покрытие).

Порт из MetadataViewer1C/src/metadata_utils/PredefinedXmlParser.ts.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .metadata_parser import MetadataMember, _element_to_value, _strip_ns


def parse_predefined_xml(predefined_xml_path: str | Path) -> list[MetadataMember]:
    """Парсит Predefined.xml в список MetadataMember.

    На любые ошибки парсинга возвращает пустой список (предопределённые
    элементы — необязательная часть метаданных).
    """
    path = Path(predefined_xml_path)
    if not path.exists():
        return []

    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []

    root = tree.getroot()
    # Корень бывает разный: PredefinedData / Predefined
    # Items могут быть на разных уровнях
    items: list[ET.Element] = []

    def _collect_items(elem: ET.Element, depth: int = 0) -> None:
        if depth > 4:
            return
        for child in elem:
            tag = _strip_ns(child.tag)
            if tag == "Item":
                items.append(child)
            elif tag in ("Items", "PredefinedItems", "ChildItems"):
                _collect_items(child, depth + 1)

    _collect_items(root)

    result: list[MetadataMember] = []
    for idx, item_elem in enumerate(items):
        props: dict = {}

        # Атрибуты <Item id="...">
        for k, v in item_elem.attrib.items():
            props[_strip_ns(k)] = v

        # Дочерние элементы — обычные поля
        for child in item_elem:
            key = _strip_ns(child.tag)
            value = _element_to_value(child)
            props[key] = value

        # Определяем имя
        name = props.get("Name")
        if isinstance(name, dict):
            name = name.get("_text")
        if not isinstance(name, str) or not name.strip():
            name = str(idx)
        else:
            name = name.strip()

        result.append(
            MetadataMember(
                kind="PredefinedItem",
                name=name,
                path=["Ext", "Predefined", name],
                properties=props,
            )
        )

    return result
