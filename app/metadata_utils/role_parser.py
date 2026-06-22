"""
Парсер файла прав роли 1С (Roles/<Name>/Ext/Rights.xml).

Формат: namespace http://v8.1c.ru/8.2/roles.

Используется в задачах вида «дать роли доступ к новому справочнику»:
агент может прочитать существующие права, посчитать какие объекты
покрываются ролью, проверить наличие ограничений по условию (RLS).

Порт из MetadataViewer1C/src/xmlParsers/roleParser.ts.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RoleRestrictionByCondition:
    """Ограничение доступа к данным (RLS)."""

    condition: str
    """Текст условия (запрос RLS)."""

    field: Optional[str] = None
    """Поле, на которое применяется ограничение."""


@dataclass
class RoleRight:
    """Одно право на объект (Read, Insert, Update, Delete, View, Edit, ...)."""

    name: str
    value: bool
    restriction_by_condition: Optional[RoleRestrictionByCondition] = None


@dataclass
class RoleObject:
    """Объект метаданных с правами."""

    name: str
    """Полное имя: Catalog.Номенклатура, Document.РеализацияТоваровУслуг."""

    rights: list[RoleRight] = field(default_factory=list)


@dataclass
class RoleRestrictionTemplate:
    """Шаблон ограничения (RLS-шаблон)."""

    name: str
    condition: str


@dataclass
class ParsedRoleRights:
    """Разобранные права роли."""

    set_for_new_objects: bool = False
    """Устанавливать права для новых объектов автоматически."""

    set_for_attributes_by_default: bool = True
    """Устанавливать права для реквизитов и табличных частей по умолчанию."""

    independent_rights_of_child_objects: bool = False
    """Независимые права подчинённых объектов."""

    objects: list[RoleObject] = field(default_factory=list)
    """Объекты метаданных с правами."""

    restriction_templates: list[RoleRestrictionTemplate] = field(default_factory=list)
    """Шаблоны RLS."""


def _local_name(tag: str) -> str:
    """Снимает namespace-префикс: {http://...}name → name."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _get_child_text(parent: ET.Element, local_name: str) -> str:
    """Возвращает текст первого ребёнка по локальному имени (без ns)."""
    for child in parent:
        if _local_name(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def _get_child_bool(parent: ET.Element, local_name: str, default: bool = False) -> bool:
    """Возвращает булево значение дочернего тега."""
    text = _get_child_text(parent, local_name)
    if not text:
        return default
    return text.lower() == "true"


def _find_direct_children(parent: ET.Element, local_name: str) -> list[ET.Element]:
    """Все прямые дети с указанным локальным именем (без рекурсии)."""
    return [child for child in parent if _local_name(child.tag) == local_name]


def _find_first_child(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
    """Первый прямой ребёнок с локальным именем."""
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def parse_role_rights_xml(file_path: str | Path) -> ParsedRoleRights:
    """Парсит Rights.xml роли 1С.

    Raises:
        FileNotFoundError: если файл не существует.
        ValueError: если XML невалиден или не похож на Rights.xml.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Rights.xml не найден: {file_path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise ValueError(f"Ошибка парсинга {file_path}: {e}") from e

    root = tree.getroot()

    result = ParsedRoleRights(
        set_for_new_objects=_get_child_bool(root, "setForNewObjects"),
        set_for_attributes_by_default=_get_child_bool(
            root, "setForAttributesByDefault", default=True
        ),
        independent_rights_of_child_objects=_get_child_bool(
            root, "independentRightsOfChildObjects"
        ),
    )

    # Объекты
    for obj_node in _find_direct_children(root, "object"):
        name = _get_child_text(obj_node, "name")
        rights: list[RoleRight] = []

        for right_node in _find_direct_children(obj_node, "right"):
            right_name = _get_child_text(right_node, "name")
            right_value = _get_child_bool(right_node, "value")

            restriction: Optional[RoleRestrictionByCondition] = None
            restr_node = _find_first_child(right_node, "restrictionByCondition")
            if restr_node is not None:
                restriction = RoleRestrictionByCondition(
                    condition=_get_child_text(restr_node, "condition"),
                    field=_get_child_text(restr_node, "field") or None,
                )

            rights.append(
                RoleRight(
                    name=right_name,
                    value=right_value,
                    restriction_by_condition=restriction,
                )
            )

        result.objects.append(RoleObject(name=name, rights=rights))

    # Шаблоны ограничений
    for tmpl_node in _find_direct_children(root, "restrictionTemplate"):
        result.restriction_templates.append(
            RoleRestrictionTemplate(
                name=_get_child_text(tmpl_node, "name"),
                condition=_get_child_text(tmpl_node, "condition"),
            )
        )

    return result


# ---- Утилиты для запросов агента --------------------------------------------


def get_object_rights(parsed: ParsedRoleRights, object_name: str) -> Optional[RoleObject]:
    """Находит права роли на конкретный объект метаданных."""
    for obj in parsed.objects:
        if obj.name == object_name:
            return obj
    return None


def has_right(role: ParsedRoleRights, object_name: str, right_name: str) -> bool:
    """Проверяет, есть ли у роли конкретное право на объект."""
    obj = get_object_rights(role, object_name)
    if not obj:
        return False
    for right in obj.rights:
        if right.name == right_name:
            return right.value
    return False


def list_objects_with_full_access(role: ParsedRoleRights) -> list[str]:
    """Возвращает имена объектов, на которые роль имеет все основные права."""
    base_rights = {"Read", "Insert", "Update", "Delete"}
    result: list[str] = []
    for obj in role.objects:
        granted = {r.name for r in obj.rights if r.value}
        if base_rights.issubset(granted):
            result.append(obj.name)
    return result


def list_rls_objects(role: ParsedRoleRights) -> list[tuple[str, str, str]]:
    """Возвращает все RLS-ограничения роли: (object_name, right_name, condition)."""
    result: list[tuple[str, str, str]] = []
    for obj in role.objects:
        for right in obj.rights:
            if right.restriction_by_condition:
                result.append(
                    (obj.name, right.name, right.restriction_by_condition.condition)
                )
    return result
