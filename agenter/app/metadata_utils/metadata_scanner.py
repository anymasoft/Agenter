"""
Сканер выгрузки конфигурации 1С (XML).

Универсальное сканирование, поддерживает оба формата выгрузки:
    1) <TypeDir>/<ObjectName>/<ObjectName>.xml  — Catalogs, Documents, Registers
    2) <TypeDir>/<ObjectName>.xml               — Languages, CommandGroups, CommonPictures

Дополнительно автодетектит Ext/Predefined.xml рядом с объектом.

Порт из MetadataViewer1C/src/metadata_utils/MetadataScanner.ts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .unicode_name import basename_without_ext, decode_1c_unicode_escapes

# Технические папки выгрузки — не каталоги типов метаданных
_SKIP_DIRS = frozenset({"Ext", ".git", ".idea", ".vscode", "node_modules"})


@dataclass
class MetadataFileRef:
    """Ссылка на конкретный объект метаданных в файловой системе."""

    object_type_dir: str
    """Имя директории типа: Catalogs, Documents, Subsystems, ..."""

    fs_name: str
    """Имя объекта в ФС (может содержать #UXXXX)."""

    display_name: str
    """Декодированное имя для UI."""

    main_xml_path: Path
    """Главный XML объекта (обычно <Name>.xml)."""

    predefined_xml_path: Optional[Path] = None
    """Ext/Predefined.xml, если найден."""

    ext_xml_paths: list[Path] = field(default_factory=list)
    """Все XML-файлы из подпапки Ext объекта."""


@dataclass
class ScanResult:
    """Результат сканирования корня выгрузки."""

    objects: list[MetadataFileRef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def scan_metadata_root(root: str | Path) -> ScanResult:
    """Сканирует корень выгрузки конфигурации 1С.

    Returns:
        ScanResult с найденными объектами (любого типа) и ошибками.

    Note:
        Это I/O-bound операция; для больших баз (>50k файлов) занимает
        порядка 2-5 секунд на NVMe SSD. Запускайте в thread executor.
    """
    result = ScanResult()
    root_path = Path(root)

    if not root_path.exists():
        result.errors.append(f"Root folder not found: {root}")
        return result

    if not root_path.is_dir():
        result.errors.append(f"Root is not a directory: {root}")
        return result

    # Папки верхнего уровня — это типы метаданных (Catalogs, Documents, ...)
    try:
        type_dirs = [
            entry
            for entry in root_path.iterdir()
            if entry.is_dir() and entry.name not in _SKIP_DIRS
        ]
    except OSError as e:
        result.errors.append(f"Error reading root directory: {e}")
        return result

    for type_dir in type_dirs:
        try:
            _scan_object_type(type_dir, result.objects)
        except OSError as e:
            result.errors.append(f"Error scanning {type_dir.name}: {e}")

    return result


def _scan_object_type(type_dir_path: Path, out: list[MetadataFileRef]) -> None:
    """Сканирует одну папку типа (например, Catalogs/)."""
    object_type_dir = type_dir_path.name

    try:
        entries = list(type_dir_path.iterdir())
    except OSError:
        return

    # Файлы XML прямо в папке типа: Languages/Имя.xml, CommandGroups/Имя.xml
    for entry in entries:
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".xml":
            continue

        fs_name = basename_without_ext(entry.name)
        ref = MetadataFileRef(
            object_type_dir=object_type_dir,
            fs_name=fs_name,
            display_name=decode_1c_unicode_escapes(fs_name),
            main_xml_path=entry,
        )
        ext_xmls = _try_detect_ext_xmls(type_dir_path, fs_name, entry)
        if ext_xmls:
            ref.ext_xml_paths = ext_xmls
            ref.predefined_xml_path = next(
                (p for p in ext_xmls if p.name.lower() == "predefined.xml"), None
            )
        out.append(ref)

    # Подпапки: Catalogs/<Name>/<Name>.xml
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS:
            continue

        # Основной файл обычно совпадает с именем папки
        candidate = entry / f"{entry.name}.xml"
        if not candidate.exists():
            # Альтернатива — любой XML внутри (на случай нестандартного имени)
            try:
                xml_files = [
                    f for f in entry.iterdir() if f.is_file() and f.suffix.lower() == ".xml"
                ]
            except OSError:
                continue
            if not xml_files:
                continue
            # Если есть файл точно совпадающий по имени (без учёта регистра) — берём его
            same_name = [
                f for f in xml_files if f.stem.lower() == entry.name.lower()
            ]
            candidate = same_name[0] if same_name else xml_files[0]

        ref = MetadataFileRef(
            object_type_dir=object_type_dir,
            fs_name=entry.name,
            display_name=decode_1c_unicode_escapes(entry.name),
            main_xml_path=candidate,
        )
        ext_xmls = _try_detect_ext_xmls(type_dir_path, entry.name, candidate)
        if ext_xmls:
            ref.ext_xml_paths = ext_xmls
            ref.predefined_xml_path = next(
                (p for p in ext_xmls if p.name.lower() == "predefined.xml"), None
            )
        out.append(ref)


def _try_detect_ext_xmls(
    type_dir_path: Path, fs_name: str, main_xml_path: Path
) -> list[Path]:
    """Ищет XML-файлы в подпапке Ext рядом с объектом."""
    # Основной формат: <TypeDir>/<Name>/Ext/*.xml
    object_dir = type_dir_path / fs_name
    ext_1 = object_dir / "Ext"
    found_1 = _list_xml_files(ext_1)
    if found_1:
        return found_1

    # Альтернатива: Ext лежит рядом с xml (если объект без подпапки)
    ext_2 = main_xml_path.parent / "Ext"
    found_2 = _list_xml_files(ext_2)
    if found_2:
        return found_2

    return []


def _list_xml_files(directory: Path) -> list[Path]:
    """Перечисляет все .xml-файлы в директории (без рекурсии)."""
    try:
        return [
            entry
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".xml"
        ]
    except (OSError, FileNotFoundError):
        return []


# ---- Утилиты группировки -----------------------------------------------------


def group_by_type(refs: Iterable[MetadataFileRef]) -> dict[str, list[MetadataFileRef]]:
    """Группирует список ссылок по object_type_dir."""
    result: dict[str, list[MetadataFileRef]] = {}
    for ref in refs:
        result.setdefault(ref.object_type_dir, []).append(ref)
    return result
