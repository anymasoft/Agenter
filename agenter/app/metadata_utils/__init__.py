"""
metadata_utils — пакет для работы с XML-выгрузкой 1С:Enterprise.

Портирован из MetadataViewer1C/src/metadata_utils (TypeScript → Python).

Содержит:
    unicode_name        — декодер #UXXXX → кириллица
    metadata_scanner    — сканер выгрузки конфигурации (2 формата)
    metadata_parser     — универсальный парсер MetaDataObject XML
    metadata_types      — словарь 40 типов объектов 1С + BSL mapping
    metadata_repository — кэш + прогрессивная загрузка дерева
    predefined_parser   — парсер Ext/Predefined.xml
    role_parser         — парсер Roles/<Name>/Ext/Rights.xml
    subsystem_membership — определение принадлежности объекта подсистемам
"""

from .unicode_name import decode_1c_unicode_escapes, basename_without_ext
from .metadata_scanner import scan_metadata_root, MetadataFileRef, ScanResult

__all__ = [
    "decode_1c_unicode_escapes",
    "basename_without_ext",
    "scan_metadata_root",
    "MetadataFileRef",
    "ScanResult",
]
