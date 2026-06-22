"""
Репозиторий метаданных с кэшированием и прогрессивной загрузкой дерева.

Порт из MetadataViewer1C/src/metadata_utils/MetadataRepository.ts.

Использует:
    - asyncio для параллельного парсинга батчами по BATCH_SIZE
    - asyncio.sleep(0) между батчами для освобождения event loop
    - Pydantic-модель MetadataTreeNode для сериализации в JSON для UI
    - TTL-кэш по корню (один процесс держит несколько корней)
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[assignment,misc]
    Field = lambda *a, **kw: None  # type: ignore[assignment]

from .metadata_parser import MetadataMember, ParsedMetadataObject, parse_metadata_object
from .metadata_scanner import MetadataFileRef, scan_metadata_root
from .metadata_types import get_display_name_by_dir
from .predefined_parser import parse_predefined_xml

# Размер батча параллельного парсинга
BATCH_SIZE = 32

# Тип callback для прогрессивной загрузки
OnTypeLoadedCallback = Callable[["MetadataTreeNode"], None]
AsyncOnTypeLoadedCallback = Callable[["MetadataTreeNode"], Awaitable[None]]


# ---- Pydantic-модели (для JSON-сериализации в API) ---------------------------


class TreeMemberInfo(BaseModel):
    """Краткое описание члена объекта для UI."""

    kind: str
    name: Optional[str] = None
    path: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class TreeObjectInfo(BaseModel):
    """Краткое описание объекта метаданных для UI."""

    object_type: str
    object_type_dir: Optional[str] = None
    name: str
    display_name: str
    source_path: str
    properties: dict[str, Any] = Field(default_factory=dict)
    n_attributes: int = 0
    n_tabular_sections: int = 0
    n_forms: int = 0
    n_commands: int = 0
    n_templates: int = 0
    n_predefined: int = 0


class MetadataTreeNode(BaseModel):
    """Узел дерева метаданных для UI.

    kind:
        "root"   - корень (Configuration)
        "type"   - папка типа (Catalogs, Documents, ...)
        "object" - конкретный объект (Catalog.Номенклатура)
        "group"  - группа членов (Attributes, TabularSections, ...)
        "member" - конкретный член (атрибут, табчасть, ...)
    """

    id: str
    label: str
    kind: str
    icon: Optional[str] = None  # имя иконки без расширения
    children: list["MetadataTreeNode"] = Field(default_factory=list)
    object: Optional[TreeObjectInfo] = None
    member: Optional[TreeMemberInfo] = None


# ---- Репозиторий -------------------------------------------------------------


class _Cached:
    """Кэшированный результат загрузки."""

    __slots__ = ("objects", "tree", "ts", "errors")

    def __init__(
        self,
        objects: list[ParsedMetadataObject],
        tree: MetadataTreeNode,
        errors: list[str],
        ts: float,
    ) -> None:
        self.objects = objects
        self.tree = tree
        self.errors = errors
        self.ts = ts


class MetadataRepository:
    """Кэширующий репозиторий метаданных конфигурации 1С.

    Использование:
        repo = MetadataRepository(ttl_seconds=300)
        result = await repo.load(r"D:\\CURSORIC\\agenter\\SCHEME")
        # или с прогрессивной загрузкой:
        async def on_type(node):
            print(node.label, len(node.children))
        result = await repo.load_progressive(root, on_type)
    """

    def __init__(self, ttl_seconds: float = 300.0, max_workers: int = 4) -> None:
        self._cache: dict[str, _Cached] = {}
        self._ttl = ttl_seconds
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="meta")
        self._lock = asyncio.Lock()

    async def load(self, root: str | Path) -> dict[str, Any]:
        """Полная загрузка дерева. Возвращает dict с tree/objects/errors."""
        return await self._load_internal(str(root), on_type_loaded=None)

    async def load_progressive(
        self,
        root: str | Path,
        on_type_loaded: AsyncOnTypeLoadedCallback,
    ) -> dict[str, Any]:
        """Прогрессивная загрузка: вызывает callback после каждого типа."""
        return await self._load_internal(str(root), on_type_loaded=on_type_loaded)

    def invalidate(self, root: Optional[str | Path] = None) -> None:
        """Сбросить кэш для одного корня или для всех."""
        if root is None:
            self._cache.clear()
        else:
            self._cache.pop(str(root), None)

    async def _load_internal(
        self,
        root: str,
        on_type_loaded: Optional[AsyncOnTypeLoadedCallback],
    ) -> dict[str, Any]:
        async with self._lock:
            now = time.time()
            cached = self._cache.get(root)
            if cached and now - cached.ts < self._ttl:
                if on_type_loaded:
                    for type_node in cached.tree.children:
                        if type_node.kind == "type":
                            await on_type_loaded(type_node)
                return {
                    "tree": cached.tree,
                    "objects": cached.objects,
                    "errors": cached.errors,
                    "cached": True,
                }

        # Сканируем (синхронно в executor)
        loop = asyncio.get_event_loop()
        scan = await loop.run_in_executor(self._executor, scan_metadata_root, root)
        errors = list(scan.errors)

        # Группируем по типу
        refs_by_type: dict[str, list[MetadataFileRef]] = {}
        for ref in scan.objects:
            refs_by_type.setdefault(ref.object_type_dir, []).append(ref)

        parsed_all: list[ParsedMetadataObject] = []
        type_nodes: list[MetadataTreeNode] = []
        sorted_types = sorted(refs_by_type.keys(), key=lambda s: s.lower())

        for type_dir in sorted_types:
            refs = refs_by_type[type_dir]
            type_parsed: list[ParsedMetadataObject] = []

            for batch_start in range(0, len(refs), BATCH_SIZE):
                batch = refs[batch_start : batch_start + BATCH_SIZE]
                batch_results = await asyncio.gather(
                    *(
                        loop.run_in_executor(self._executor, _parse_with_predefined, ref)
                        for ref in batch
                    ),
                    return_exceptions=True,
                )
                for ref, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        errors.append(f"Parse failed: {ref.main_xml_path}: {result}")
                    else:
                        type_parsed.append(result)  # type: ignore[arg-type]

            type_node = _build_type_node(type_dir, type_parsed)
            type_nodes.append(type_node)
            parsed_all.extend(type_parsed)

            if on_type_loaded:
                await on_type_loaded(type_node)
                await asyncio.sleep(0)  # освобождаем event loop

        tree = MetadataTreeNode(
            id="root", label="Configuration", kind="root", children=type_nodes
        )

        async with self._lock:
            self._cache[root] = _Cached(parsed_all, tree, errors, time.time())

        return {"tree": tree, "objects": parsed_all, "errors": errors, "cached": False}


def _parse_with_predefined(ref: MetadataFileRef) -> ParsedMetadataObject:
    """Парсит объект + Predefined.xml, если есть. Запускается в thread executor."""
    obj = parse_metadata_object(ref)
    if ref.predefined_xml_path:
        try:
            obj.predefined = parse_predefined_xml(ref.predefined_xml_path)
        except Exception:  # noqa: BLE001
            pass
    return obj


# ---- Построение дерева --------------------------------------------------------


# Маппинг type_dir → имя иконки (имя файла без расширения, на основе папки assets/icons/)
_ICON_BY_TYPE_DIR: dict[str, str] = {
    "Catalogs": "catalog",
    "Documents": "document",
    "Enums": "enum",
    "Reports": "report",
    "DataProcessors": "dataProcessor",
    "ChartsOfCharacteristicTypes": "chartsOfCharacteristicType",
    "ChartsOfAccounts": "chartsOfAccount",
    "ChartsOfCalculationTypes": "chartsOfCalculationType",
    "InformationRegisters": "informationRegister",
    "AccumulationRegisters": "accumulationRegister",
    "AccountingRegisters": "accountingRegister",
    "CalculationRegisters": "calculationRegister",
    "BusinessProcesses": "businessProcess",
    "Tasks": "task",
    "Constants": "constant",
    "CommonModules": "commonModule",
    "CommonForms": "form",
    "ExternalDataSources": "externalDataSource",
    "DefinedTypes": "attribute",
    "ExchangePlans": "exchangePlan",
    "DocumentJournals": "documentJournal",
    "Sequences": "sequence",
    "DocumentNumerators": "documentNumerator",
    "WebServices": "ws",
    "HTTPServices": "http",
    "Subsystems": "subsystem",
    "Roles": "role",
    "SessionParameters": "sessionParameter",
    "CommonAttributes": "attribute",
    "EventSubscriptions": "eventSubscription",
    "ScheduledJobs": "scheduledJob",
    "CommonCommands": "command",
    "CommandGroups": "command",
    "CommonTemplates": "template",
    "CommonPictures": "picture",
    "WSReferences": "wsLink",
    "Styles": "style",
    "StyleItems": "style",
    "FilterCriteria": "filterCriteria",
    "FunctionalOptions": "common",
    "FunctionalOptionsParameters": "parameter",
    "SettingsStorages": "common",
    "XDTOPackages": "common",
    "Languages": "common",
}


_ICON_BY_MEMBER_KIND: dict[str, str] = {
    "Attribute": "attribute",
    "Dimension": "dimension",
    "Resource": "resource",
    "AccountingFlag": "accountingFlag",
    "ExtDimensionAccountingFlag": "extDimensionAccountingFlag",
    "TabularSection": "tabularSection",
    "Form": "form",
    "Command": "command",
    "Template": "template",
    "Layout": "template",
    "EnumValue": "enum",
    "PredefinedItem": "common",
}


def _build_type_node(type_dir: str, objs: list[ParsedMetadataObject]) -> MetadataTreeNode:
    """Создаёт узел типа со всеми его объектами."""
    sorted_objs = sorted(objs, key=lambda o: (o.display_name or "").casefold())
    children = [_build_object_node(type_dir, o) for o in sorted_objs]
    return MetadataTreeNode(
        id=f"type:{type_dir}",
        label=f"{get_display_name_by_dir(type_dir)} ({len(objs)})",
        kind="type",
        icon=_ICON_BY_TYPE_DIR.get(type_dir, "common"),
        children=children,
    )


def _build_object_node(type_dir: str, obj: ParsedMetadataObject) -> MetadataTreeNode:
    """Создаёт узел объекта со всеми его группами членов."""
    obj_info = TreeObjectInfo(
        object_type=obj.object_type,
        object_type_dir=obj.object_type_dir,
        name=obj.name,
        display_name=obj.display_name,
        source_path=obj.source_path,
        properties=_safe_properties(obj.properties),
        n_attributes=len(obj.attributes),
        n_tabular_sections=len(obj.tabular_sections),
        n_forms=len(obj.forms),
        n_commands=len(obj.commands),
        n_templates=len(obj.templates),
        n_predefined=len(obj.predefined),
    )

    groups: list[MetadataTreeNode] = []

    def _add_group(title: str, items: Iterable[MetadataMember], group_icon: Optional[str] = None) -> None:
        items_list = list(items)
        if not items_list:
            return
        members_sorted = sorted(items_list, key=lambda m: (m.name or "").casefold())
        children = [
            MetadataTreeNode(
                id=f"{type_dir}/{obj.name}/{title}/{m.name or i}",
                label=m.name or m.kind or str(i),
                kind="member",
                icon=_ICON_BY_MEMBER_KIND.get(m.kind, group_icon or "common"),
                member=TreeMemberInfo(
                    kind=m.kind,
                    name=m.name,
                    path=m.path,
                    properties=_safe_properties(m.properties),
                ),
            )
            for i, m in enumerate(members_sorted)
        ]
        groups.append(
            MetadataTreeNode(
                id=f"{type_dir}/{obj.name}/{title}",
                label=f"{title} ({len(items_list)})",
                kind="group",
                icon=group_icon,
                children=children,
            )
        )

    _add_group("Attributes", obj.attributes, group_icon="attribute")
    _add_group("TabularSections", obj.tabular_sections, group_icon="tabularSection")
    _add_group("Forms", obj.forms, group_icon="form")
    _add_group("Commands", obj.commands, group_icon="command")
    _add_group("Templates", obj.templates, group_icon="template")
    _add_group("Predefined", obj.predefined, group_icon="common")

    return MetadataTreeNode(
        id=f"{type_dir}/{obj.name}",
        label=obj.display_name or obj.name,
        kind="object",
        icon=_ICON_BY_TYPE_DIR.get(type_dir, "common"),
        children=groups,
        object=obj_info,
    )


def _safe_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Возвращает безопасные для JSON свойства (строки/числа/bools, не глубокие).

    Глубокие словари обрезаем до 1 уровня, чтобы UI не утонул в JSON.
    """
    out: dict[str, Any] = {}
    for k, v in props.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict):
            # Берём только первый уровень — обычно это {_text: "..."} или примитивы
            simple: dict[str, Any] = {}
            for kk, vv in v.items():
                if isinstance(vv, (str, int, float, bool)) or vv is None:
                    simple[kk] = vv
                else:
                    simple[kk] = str(vv)[:200]
            out[k] = simple
        elif isinstance(v, list):
            # Списки тоже сжимаем
            out[k] = [
                x if isinstance(x, (str, int, float, bool)) else str(x)[:200]
                for x in v[:10]  # максимум 10 элементов
            ]
        else:
            out[k] = str(v)[:200]
    return out


# Pydantic для forward-ссылки на MetadataTreeNode
MetadataTreeNode.model_rebuild()
