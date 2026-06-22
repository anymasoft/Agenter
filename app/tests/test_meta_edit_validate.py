"""Тесты валидации имён + улучшенного нормализатора для add-ts."""
from __future__ import annotations

import sys
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parent.parent.parent / "desktop"
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_main", DESKTOP_DIR / "main.py")
desktop_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop_main)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

validate = desktop_main._validate_meta_name
extract = desktop_main._extract_names_from_value
normalize = desktop_main._normalize_meta_edit_value


def main() -> int:
    failed = 0

    print("=== _validate_meta_name ===")
    name_cases = [
        # (name, expected_ok, description)
        ("Город",                True,  "обычное русское"),
        ("City",                 True,  "обычное латинское"),
        ("ГородКлиента",         True,  "PascalCase ru"),
        ("город_клиента",        True,  "snake_case ru"),
        ("Город123",             True,  "с цифрой в середине"),
        ("_Hidden",              True,  "ведущий подчёркивание"),
        ("Город Строка(50)",     False, "пробел и скобки"),
        ("Город(50)",            False, "скобки"),
        ("123Город",             False, "начинается с цифры"),
        ("Город-Клиента",        False, "дефис"),
        ("Город.Клиента",        False, "точка"),
        ("Город:Тип",            False, "двоеточие"),
        ("",                     False, "пустое"),
        ("a" * 129,              False, "слишком длинное"),
        ("Город!@#",             False, "спецсимволы"),
    ]
    for name, ok_expected, desc in name_cases:
        err = validate(name)
        ok_actual = err is None
        mark = "OK" if ok_actual == ok_expected else "FAIL"
        suffix = "" if ok_actual else f" — {err}"
        print(f"  [{mark}] {desc:35s} {name[:30]!r}{suffix}")
        if ok_actual != ok_expected:
            failed += 1

    print("\n=== _extract_names_from_value ===")
    extract_cases = [
        # (op, value, expected_names, description)
        ("add-attribute",  "Город:String(50)",                 ["Город"],          "single"),
        ("add-attribute",  "Город:String(50);;Адрес:String(200)", ["Город", "Адрес"], "batch"),
        ("add-attribute",  "Город:String(50)|req,index",       ["Город"],          "с флагами"),
        ("add-attribute",  "Город:String(50) >> after Адрес",  ["Город"],          "positional"),
        ("add-ts",         "Товары",                            ["Товары"],         "ts без attrs"),
        ("add-ts",         "Товары: Номенклатура:CatalogRef.X, Количество:Number(15,3)",
                            ["Товары", "Номенклатура", "Количество"],              "ts с attrs"),
        ("add-ts",         "Товары: Сумма:Number(15,2), НДС:Number(15,2)",
                            ["Товары", "Сумма", "НДС"],                            "ts с двумя Number"),
        # Не add-* — извлечения нет
        ("modify-property", "CodeLength=11;;DescriptionLength=150", [],            "modify"),
        ("remove-attribute", "Город;;Адрес",                         [],           "remove"),
        ("add-owner",      "Catalog.Договор",                       [],            "add-owner skipped"),
    ]
    for op, val, expected, desc in extract_cases:
        actual = extract(op, val)
        ok = actual == expected
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {desc:35s} {op}")
        if not ok:
            print(f"        value    = {val!r}")
            print(f"        expected = {expected}")
            print(f"        actual   = {actual}")
            failed += 1

    print("\n=== _normalize_meta_edit_value (add-ts с русскими типами внутри) ===")
    norm_cases = [
        ("add-ts",
         "Товары: Номенклатура:СправочникСсылка.Номенклатура, Количество:Число(15,3)",
         "Товары: Номенклатура:CatalogRef.Номенклатура, Количество:Number(15,3)",
         "ts: ru ref + ru number"),
        ("add-ts", "Товары", "Товары", "ts без attrs"),
        ("add-ts",
         "Товары: Сумма Число(15,2), Курс:Число(10,4)",
         "Товары: Сумма:Number(15,2), Курс:Number(10,4)",
         "ts: space + ru types"),
    ]
    for op, inp, expected, desc in norm_cases:
        actual = normalize(op, inp)
        ok = actual == expected
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {desc}")
        if not ok:
            print(f"        input    = {inp!r}")
            print(f"        expected = {expected!r}")
            print(f"        actual   = {actual!r}")
            failed += 1

    print("\n=== End-to-end сценарий из лога пользователя ===")
    # Симулируем что LLM прислал "Город Строка(50)" — нормализуем + извлекаем + валидируем
    user_input = "Город Строка(50)"
    operation = "add-attribute"
    normalized = normalize(operation, user_input)
    names = extract(operation, normalized)
    errs = [(n, validate(n)) for n in names]
    print(f"  Input:      {user_input!r}")
    print(f"  Normalized: {normalized!r}")
    print(f"  Names:      {names}")
    print(f"  Errors:     {[(n, e) for n, e in errs if e]}")
    if normalized != "Город:String(50)" or names != ["Город"] or any(e for _, e in errs):
        print("  [FAIL] e2e сценарий")
        failed += 1
    else:
        print("  [OK] e2e сценарий — нормализатор спас, валидация прошла")

    # Теперь симулируем что нормализатор НЕ сработал (гипотетический мусор)
    bad_input_after_norm = "Город Строка(50)"  # без двоеточия — _normalize обработает, но представим что нет
    # Принудительно через extract без нормализации
    names2 = extract("add-attribute", bad_input_after_norm)
    # extract разрезал по ":" — двоеточия нет, так что names2 = ["Город Строка(50)"]
    print(f"\n  Без нормализации (имитация мусора):")
    print(f"  Input:  {bad_input_after_norm!r}")
    print(f"  Names:  {names2}")
    errs2 = [(n, validate(n)) for n in names2 if validate(n)]
    print(f"  Errors: {errs2}")
    if not errs2:
        print("  [FAIL] валидация должна была отклонить")
        failed += 1
    else:
        print("  [OK] валидация отклонила мусор как fallback")

    print(f"\n=== Total: {'OK' if failed == 0 else f'{failed} test(s) FAILED'} ===")
    return failed


if __name__ == "__main__":
    sys.exit(main())
