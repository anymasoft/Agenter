"""
Декодер имён файлов/папок 1С-выгрузки.

1C конфигурации, выгруженные в XML, иногда содержат имена файлов/папок
в виде #UXXXX (UTF-16 code unit в hex). Например:
    "#U041F#U0440#U0438#U043C#U0435#U0440" → "Пример"

Порт из MetadataViewer1C/src/metadata_utils/UnicodeName.ts.
"""
from __future__ import annotations

import re

# Совпадает с UNICODE_SEQ из TS-версии
_UNICODE_SEQ = re.compile(r"#U([0-9A-Fa-f]{4})")


def decode_1c_unicode_escapes(input_str: str) -> str:
    """Декодирует #UXXXX последовательности в строке.

    Невалидные последовательности оставляет как есть.
    Если в строке нет #U — возвращает как есть, без накладных расходов.
    """
    if not input_str or "#U" not in input_str:
        return input_str

    def _replace(match: re.Match[str]) -> str:
        hex_code = match.group(1)
        try:
            code = int(hex_code, 16)
            return chr(code)
        except (ValueError, OverflowError):
            return f"#U{hex_code}"

    return _UNICODE_SEQ.sub(_replace, input_str)


def basename_without_ext(file_name: str) -> str:
    """Имя без расширения. Аналог Node basename без .ext."""
    dot = file_name.rfind(".")
    return file_name if dot == -1 else file_name[:dot]
