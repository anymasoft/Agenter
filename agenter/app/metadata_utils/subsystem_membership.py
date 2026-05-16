"""
Принадлежность объектов метаданных подсистемам.

Каждая подсистема (Subsystems/<Name>.xml) содержит блок Properties/Content
со списком xr:Item — ссылок на объекты метаданных, входящие в подсистему.

Используется в задачах:
    - «в какие подсистемы входит объект X»
    - «объекты подсистемы Y»
    - «добавить новый объект в подсистему» (read-only анализ; запись
      делается через стандартный механизм 1С)

Порт из MetadataViewer1C/src/utils/subsystemMembership.ts (read-only часть).
Запись (applySubsystemMembershipChanges) пока не портирована — она требует
точного контроля namespace при сериализации.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

_NS_PATTERN = re.compile(r"^\{[^}]+\}")
_SYNONYM_PATTERN = re.compile(
    r"<Synonym>[\s\S]*?<v8:content>([^<]*)</v8:content>", re.IGNORECASE
)
_NAME_PATTERN = re.compile(
    r"<Properties>[\s\S]*?<Name>([^<]+)</Name>", re.IGNORECASE
)


def _local_name(tag: str) -> str:
    return _NS_PATTERN.sub("", tag)


def _is_backup_file(file_name: str) -> bool:
    """Файлы вида ИмяПодсистемы.backup.<date>.xml — резервные копии."""
    return ".backup." in file_name.lower()


@dataclass
class SubsystemMembershipRow:
    """Принадлежность объекта одной подсистеме."""

    rel_path: str
    """Путь от корня конфигурации, POSIX-style: Subsystems/Имя.xml."""

    label: str
    """Подпись подсистемы (синоним ru или Name)."""

    included: bool
    """Объект входит в Content этой подсистемы."""


def enumerate_subsystem_xml_files(config_root: str | Path) -> list[Path]:
    """Рекурсивно перечисляет XML-файлы подсистем."""
    root = Path(config_root) / "Subsystems"
    if not root.exists() or not root.is_dir():
        return []

    result: list[Path] = []
    for path in root.rglob("*.xml"):
        if not path.is_file():
            continue
        name_lower = path.name.lower()
        # Интерфейс команд подсистемы — не сами метаданные
        if name_lower == "commandinterface.xml":
            continue
        if _is_backup_file(path.name):
            continue
        result.append(path)

    result.sort(key=lambda p: str(p).casefold())
    return result


def _read_text_safe(path: Path) -> Optional[str]:
    """Читает текст файла, обрезает BOM."""
    try:
        text = path.read_text(encoding="utf-8-sig")
        return text
    except OSError:
        return None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except OSError:
            return None


def _read_subsystem_display_label(xml: str, fallback_name: str) -> str:
    """Извлекает синоним ru или имя подсистемы из XML."""
    syn = _SYNONYM_PATTERN.search(xml)
    if syn and syn.group(1).strip():
        return syn.group(1).strip()
    name_match = _NAME_PATTERN.search(xml)
    if name_match:
        return name_match.group(1).strip()
    return fallback_name


def extract_content_md_refs(xml: str) -> list[str]:
    """Извлекает список MDObjectRef из Content подсистемы.

    Внутри XML структура:
        MetaDataObject/Subsystem/Properties/Content/xr:Item (text)
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    if _local_name(root.tag) != "MetaDataObject":
        return []

    # MetaDataObject → Subsystem
    subsystem_el = next(
        (c for c in root if _local_name(c.tag) == "Subsystem"), None
    )
    if subsystem_el is None:
        return []

    # Subsystem → Properties
    properties = next(
        (c for c in subsystem_el if _local_name(c.tag) == "Properties"), None
    )
    if properties is None:
        return []

    # Properties → Content
    content = next(
        (c for c in properties if _local_name(c.tag) == "Content"), None
    )
    if content is None:
        return []

    # Content → xr:Item (text)
    refs: list[str] = []
    for item in content:
        if _local_name(item.tag) != "Item":
            continue
        text = (item.text or "").strip()
        if text:
            refs.append(text)
    return refs


def load_subsystem_membership(
    config_root: str | Path, md_ref: str
) -> list[SubsystemMembershipRow]:
    """Возвращает список подсистем с флагами участия объекта md_ref.

    Args:
        config_root: путь к корню выгрузки конфигурации (SCHEME)
        md_ref: ссылка на объект, например 'Catalog.Номенклатура',
                'Document.РеализацияТоваровУслуг'

    Returns:
        Список SubsystemMembershipRow, отсортированный по relPath.
    """
    config_root_path = Path(config_root)
    files = enumerate_subsystem_xml_files(config_root_path)

    result: list[SubsystemMembershipRow] = []
    for abs_path in files:
        xml = _read_text_safe(abs_path)
        if xml is None:
            continue

        try:
            rel = abs_path.relative_to(config_root_path).as_posix()
        except ValueError:
            rel = abs_path.name

        label = _read_subsystem_display_label(xml, abs_path.stem)
        refs = extract_content_md_refs(xml)
        result.append(
            SubsystemMembershipRow(
                rel_path=rel,
                label=label,
                included=md_ref in refs,
            )
        )

    return result


def list_subsystem_content(config_root: str | Path, subsystem_rel_path: str) -> list[str]:
    """Возвращает все MDObjectRef одной подсистемы по её относительному пути."""
    abs_path = Path(config_root) / subsystem_rel_path
    if not abs_path.exists():
        return []
    xml = _read_text_safe(abs_path)
    if xml is None:
        return []
    return extract_content_md_refs(xml)


def find_subsystems_for_object(
    config_root: str | Path, md_ref: str
) -> list[SubsystemMembershipRow]:
    """Возвращает только подсистемы, в которые входит объект.

    Удобный shortcut над load_subsystem_membership() для частого
    use-case «в какие подсистемы входит X».
    """
    rows = load_subsystem_membership(config_root, md_ref)
    return [r for r in rows if r.included]


def should_offer_subsystem_membership(
    file_path: str | Path, object_type: Optional[str] = None
) -> bool:
    """Имеет ли смысл показывать «подсистемы» для данного объекта.

    Конфигурация и сами подсистемы — не показываем.
    """
    p = Path(file_path)
    if p.name == "Configuration.xml":
        return False
    parts = p.as_posix().split("/")
    if "Subsystems" in parts:
        return False
    if object_type == "Subsystem":
        return False
    return True
