"""Проверка _resolve_meta_object_path на 3 форматах раскладки."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Подключаем desktop/main.py (там живёт функция)
DESKTOP_DIR = Path(__file__).resolve().parent.parent.parent / "desktop"
sys.path.insert(0, str(DESKTOP_DIR))

# Avoid pulling whole desktop/main.py — extract function via exec-import
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_main", DESKTOP_DIR / "main.py")
desktop_main = importlib.util.module_from_spec(spec)

# Только функцию резолва (без побочных эффектов запуска)
# Поскольку main.py не пытается ничего запускать при импорте (только если __main__),
# импорт безопасен.
try:
    spec.loader.exec_module(desktop_main)
except Exception as e:
    print(f"Failed to import desktop/main.py: {e}")
    sys.exit(1)

resolve = desktop_main._resolve_meta_object_path


def main() -> int:
    failed = 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ext_src = td / "ext_src"
        ext_src.mkdir()

        # Сценарий 1: плоский XML (cfe_borrow newly-created object)
        cat = ext_src / "Catalogs"
        cat.mkdir()
        flat_xml = cat / "Банки.xml"
        flat_xml.write_text("<MetaDataObject/>", encoding="utf-8")

        # Сценарий 2: формат с подпапкой
        nested_dir = cat / "Контрагенты"
        nested_dir.mkdir()
        nested_xml = nested_dir / "Контрагенты.xml"
        nested_xml.write_text("<MetaDataObject/>", encoding="utf-8")

        # Сценарий 3: несуществующий
        missing = cat / "НетТакого"

        cases = [
            # (вход, ожидание)
            (cat / "Банки",                 flat_xml,   "плоский: без .xml → .xml"),
            (cat / "Банки.xml",             flat_xml,   "плоский: с .xml → как есть"),
            (cat / "Контрагенты",           nested_dir, "папка: без .xml → папка"),
            (cat / "Контрагенты.xml",       nested_xml, "папка: с .xml → внутрь"),
            (cat / "Контрагенты" / "Контрагенты.xml", nested_xml, "явный полный путь"),
            (missing,                       None,       "несуществующий"),
            (missing.with_suffix(".xml"),   None,       "несуществующий.xml"),
        ]

        for input_path, expected, desc in cases:
            actual = resolve(input_path)
            ok = (actual == expected) if expected is not None else (actual is None)
            mark = "OK" if ok else "FAIL"
            print(f"  [{mark}] {desc}")
            print(f"        input    = {input_path}")
            print(f"        expected = {expected}")
            print(f"        actual   = {actual}")
            if not ok:
                failed += 1

    print(f"\n{'OK' if failed == 0 else f'{failed} test(s) FAILED'}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
