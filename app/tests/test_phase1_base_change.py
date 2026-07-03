"""Фаза 1 / Шаг 1.4 — проверка детектора изменений базы (ConfigDumpInfo.xml).
Запуск: python app/tests/test_phase1_base_change.py"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import base_change_detector as B  # noqa: E402

fails = []
def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)

NS = 'xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo"'

def make_xml(items: dict) -> str:
    rows = "\n".join(
        f'<Metadata name="{n}" id="id-{i}" configVersion="{v}"/>'
        for i, (n, v) in enumerate(items.items()))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ConfigDumpInfo {NS} version="2.20"><ConfigVersions>\n{rows}\n'
            f'</ConfigVersions></ConfigDumpInfo>')

tmp = Path(tempfile.mkdtemp())

# ── 1. Парсер читает РЕАЛЬНЫЙ ConfigDumpInfo.xml ──
real = Path(__file__).resolve().parents[2] / "_work" / "config_src" / "ConfigDumpInfo.xml"
if real.is_file():
    m = B.parse_config_dump_info(real)
    check(f"парсер: реальный ConfigDumpInfo.xml → {len(m)} объектов со штампом", len(m) > 0)
    check("парсер: значения configVersion непустые хеши",
          all(isinstance(v, str) and len(v) > 8 for v in list(m.values())[:5]))
    same = B.detect_changes(real, real)
    check("детектор: реальный файл vs сам себя → изменений нет", same["any"] is False)
else:
    check("парсер: реальный ConfigDumpInfo.xml найден", False)

# ── 2. Синтетика: ручная правка одного объекта + добавление + удаление ──
baseline = {
    "Catalog.Номенклатура": "aaaa0000",
    "Catalog.Контрагенты": "bbbb0000",
    "Document.Заказ": "cccc0000",
}
modified = {
    "Catalog.Номенклатура": "aaaa9999",   # ИЗМЕНЁН (правка в конфигураторе)
    "Catalog.Контрагенты": "bbbb0000",     # без изменений
    # "Document.Заказ" УДАЛЁН
    "Document.Поставка": "dddd0000",       # ДОБАВЛЕН
}
bpath = tmp / "baseline.xml"; cpath = tmp / "current.xml"
bpath.write_text(make_xml(baseline), encoding="utf-8")
cpath.write_text(make_xml(modified), encoding="utf-8")
d = B.detect_changes(bpath, cpath)
print("diff:", d["counts"], "changed:", d["changed"], "added:", d["added"], "removed:", d["removed"])
check("детектор: видит факт изменений (any=true)", d["any"] is True)
check("детектор: точно называет ИЗМЕНЁННЫЙ объект", d["changed"] == ["Catalog.Номенклатура"])
check("детектор: точно называет ДОБАВЛЕННЫЙ объект", d["added"] == ["Document.Поставка"])
check("детектор: точно называет УДАЛЁННЫЙ объект", d["removed"] == ["Document.Заказ"])

# ── 3. Нет правок → any=false ──
d2 = B.detect_changes(bpath, bpath)
check("детектор: без правок → 'не менялось' (any=false)", d2["any"] is False)

# ── 4. Первый запуск (нет baseline) → всё added ──
d3 = B.detect_changes(tmp / "нет_такого.xml", cpath)
check("детектор: нет baseline → все объекты как added (первый запуск)",
      d3["any"] is True and d3["counts"]["added"] == len(modified) and d3["counts"]["changed"] == 0)

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}"); sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
