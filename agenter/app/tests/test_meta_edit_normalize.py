"""Тесты нормализации DSL value для meta-edit."""
from __future__ import annotations

import sys
from pathlib import Path

# Импортируем функции из desktop/main.py без побочных эффектов
DESKTOP_DIR = Path(__file__).resolve().parent.parent.parent / "desktop"
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_main", DESKTOP_DIR / "main.py")
desktop_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop_main)

normalize = desktop_main._normalize_meta_edit_value
translate = desktop_main._translate_type_to_en

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> int:
    cases = [
        # (operation, input, expected, description)
        # Главный кейс из лога пользователя
        ("add-attribute", "Город Строка(50)",   "Город:String(50)",      "пробел вместо ':' + русский тип"),
        # Type= синтаксис
        ("add-attribute", "Город Type=String(50)", "Город:String(50)",  "Type= → ':'"),
        ("add-attribute", "Город Type=Строка(50)", "Город:String(50)",  "Type=Строка"),
        # Уже правильный — не должен меняться
        ("add-attribute", "Город:String(50)",   "Город:String(50)",      "already correct"),
        # Только русский тип, формат правильный
        ("add-attribute", "Город:Строка(50)",   "Город:String(50)",      "ru type → en"),
        # Числовой тип с параметрами
        ("add-attribute", "Сумма:Число(15,2)",  "Сумма:Number(15,2)",    "Число(N,M)"),
        # Дата
        ("add-attribute", "ДатаПродажи:Дата",   "ДатаПродажи:Date",      "Дата"),
        # Булево
        ("add-attribute", "Активный:Булево",    "Активный:Boolean",      "Булево"),
        # Reference
        ("add-attribute", "Контрагент:СправочникСсылка.Контрагенты",
                          "Контрагент:CatalogRef.Контрагенты",            "ref CatalogRef"),
        ("add-attribute", "Документ:ДокументСсылка.РеализацияТоваровУслуг",
                          "Документ:DocumentRef.РеализацияТоваровУслуг", "ref DocumentRef"),
        # С флагами
        ("add-attribute", "Город:Строка(50)|req",
                          "Город:String(50)|req",                         "with flag req"),
        ("add-attribute", "Город Строка(50) | req,index",
                          "Город:String(50) | req,index",                 "space + flags"),
        # Batch
        ("add-attribute", "Город:Строка(50);;Адрес:Строка(200);;Индекс:Строка(6)",
                          "Город:String(50);;Адрес:String(200);;Индекс:String(6)", "batch"),
        # Mixed: один без двоеточия, второй с
        ("add-attribute", "Город Строка(50);;Адрес:String(200)",
                          "Город:String(50);;Адрес:String(200)",          "mixed batch"),
        # Positional markers
        ("add-attribute", "Город Строка(50) >> after Адрес",
                          "Город:String(50) >> after Адрес",              "with >> after"),
        # ХранилищеЗначения
        ("add-attribute", "Данные:ХранилищеЗначения",
                          "Данные:ValueStorage",                          "ValueStorage"),
        # UUID
        ("add-attribute", "Ид:УникальныйИдентификатор",
                          "Ид:UUID",                                      "UUID"),
        # add-resource (для регистров)
        ("add-resource",  "Сумма:Число(15,2)", "Сумма:Number(15,2)",      "add-resource Number"),
        # add-dimension
        ("add-dimension", "Период:Дата",      "Период:Date",              "add-dimension Date"),
        # modify-property — НЕ трогаем
        ("modify-property", "CodeLength=11;;DescriptionLength=150",
                            "CodeLength=11;;DescriptionLength=150",       "modify-property unchanged"),
        # remove-attribute — НЕ трогаем
        ("remove-attribute", "Город;;Адрес", "Город;;Адрес",               "remove unchanged"),
        # Пустое value
        ("add-attribute",   "",               "",                          "empty value"),
        # Только имя, без типа — оставляем как есть
        ("add-attribute",   "Город",          "Город",                     "name only"),
    ]

    failed = 0
    for op, inp, expected, desc in cases:
        actual = normalize(op, inp)
        ok = actual == expected
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {desc}")
        if not ok:
            print(f"        op       = {op}")
            print(f"        input    = {inp!r}")
            print(f"        expected = {expected!r}")
            print(f"        actual   = {actual!r}")
            failed += 1

    print(f"\n  Total: {len(cases)}, failed: {failed}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
