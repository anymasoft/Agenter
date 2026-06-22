"""Tests структурированного meta_edit API (без DSL-строк)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESKTOP_DIR = Path(__file__).resolve().parent.parent.parent / "desktop"
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_main", DESKTOP_DIR / "main.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)


def main() -> int:
    failed = 0

    print("=== _validate_definition_names ===")
    cases = [
        # (definition, expected_errors_count, description)
        ({"add": {"attributes": [{"name": "Город", "type": "Строка(50)"}]}}, 0, "valid simple add"),
        ({"add": {"attributes": [{"name": "Город", "type": "Строка"}, {"name": "Адрес", "type": "Строка"}]}}, 0, "valid batch"),
        ({"add": {"attributes": [{"name": "Город Строка(50)", "type": "?"}]}}, 1, "name with space"),
        ({"add": {"attributes": [{"name": "123Город", "type": "Строка"}]}}, 1, "starts with digit"),
        ({"add": {"attributes": [{"name": "Город(test)", "type": "Строка"}]}}, 1, "with parens"),
        ({"add": {"tabularSections": [{"name": "Товары", "attrs": [{"name": "Кол-во", "type": "Number"}]}]}}, 1, "attr with dash"),
        ({"add": {"tabularSections": [{"name": "Товары", "attrs": [{"name": "Количество", "type": "Number"}]}]}}, 0, "valid TS"),
        ({"add": {"enumValues": [{"name": "Активный"}, {"name": "InActive"}]}}, 0, "valid enum"),
        ({"add": {"enumValues": [{"name": "Не активный"}]}}, 1, "enum with space"),
        ({"add": {"forms": ["ФормаЭлемента"]}}, 0, "valid form"),
        ({"add": {"forms": ["Форма документа"]}}, 1, "form with space"),
        ({"modify": {"attributes": {"Город": {"name": "Регион", "type": "Строка(100)"}}}}, 0, "valid rename"),
        ({"modify": {"attributes": {"Город": {"name": "Регион Клиента"}}}}, 1, "rename to invalid"),
        ({"modify": {"properties": {"CodeLength": 11}}}, 0, "modify property (not validated)"),
        ({"remove": {"attributes": ["Город"]}}, 0, "valid remove"),
        ({"remove": {"attributes": ["Старый Реквизит"]}}, 1, "remove invalid name"),
        ({}, 0, "empty"),
    ]
    for definition, expected_errs, desc in cases:
        errs = dm._validate_definition_names(definition)
        ok = len(errs) == expected_errs
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {desc:35s} → {len(errs)} errors (expected {expected_errs})")
        if not ok:
            for e in errs:
                print(f"        {e}")
            failed += 1

    # Проверка что JSON корректно записывается с UTF-8
    print("\n=== JSON UTF-8 write ===")
    test_def = {
        "add": {
            "attributes": [
                {"name": "Город", "type": "Строка(50)"},
                {"name": "СтавкаНДС", "type": "EnumRef.СтавкиНДС"},
            ]
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as tmp:
        json.dump(test_def, tmp, ensure_ascii=False, indent=2)
        path = tmp.name
    try:
        content = Path(path).read_text(encoding="utf-8")
        print(f"  Written ({len(content)} chars):")
        print("  " + content.replace("\n", "\n  "))
        # Должны видеть русские буквы, не \uXXXX
        assert "Город" in content, "Кириллица должна быть в plain UTF-8"
        assert "СтавкиНДС" in content
        print("  [OK] UTF-8 plain text")
    finally:
        Path(path).unlink()

    print(f"\n=== Result: {'OK' if failed == 0 else f'{failed} FAILED'} ===")
    return failed


if __name__ == "__main__":
    sys.exit(main())
