"""Фаза 2 / Шаг 2.2 — проверка решающей логики авто-сверки базы (без 1С).
Запуск: python app/tests/test_phase2_auto_sync.py"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_sync as A  # noqa: E402

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

base = {"Catalog.Номенклатура": "aaaa0000", "Document.Заказ": "cccc0000"}
baseline = tmp / "baseline.xml"
baseline.write_text(make_xml(base), encoding="utf-8")

# ── 1. База не менялась → skip (мгновенный старт) ──
same = tmp / "same.xml"
same.write_text(make_xml(base), encoding="utf-8")
d = A.decide_pre_task_sync(baseline, same)
print("no-change:", d["action"], "—", d["reason"])
check("не менялось → action=skip", d["action"] == A.ACTION_SKIP)

# ── 2. База менялась → reindex + список объектов ──
changed = {"Catalog.Номенклатура": "aaaa9999",   # изменён
           "Document.Поставка": "dddd0000"}        # добавлен; Заказ удалён
cur = tmp / "current.xml"
cur.write_text(make_xml(changed), encoding="utf-8")
d2 = A.decide_pre_task_sync(baseline, cur)
print("changed:", d2["action"], "objects:", d2["changed_objects"])
check("менялось → action=reindex", d2["action"] == A.ACTION_REINDEX)
check("reindex несёт список затронутых объектов", len(d2["changed_objects"]) > 0)
check("reindex: counts отражают diff",
      d2["counts"]["changed"] == 1 and d2["counts"]["added"] == 1 and d2["counts"]["removed"] == 1)

# ── 3. Нет baseline (первый запуск) → full ──
d3 = A.decide_pre_task_sync(tmp / "нет.xml", cur)
print("no-baseline:", d3["action"], "—", d3["reason"])
check("нет baseline → action=full (первый запуск)", d3["action"] == A.ACTION_FULL)

# ── 4. Нет текущего ConfigDumpInfo → skip (не форсим выгрузку) ──
d4 = A.decide_pre_task_sync(baseline, tmp / "нет_текущего.xml")
check("нет current → action=skip (не форсим)", d4["action"] == A.ACTION_SKIP)

# ── 5. update_baseline копирует снимок и делает последующую сверку skip ──
saved = A.update_baseline(cur, tmp / "app", "proj-1")
check("update_baseline: снимок сохранён", saved is not None and saved.is_file())
d5 = A.decide_pre_task_sync(saved, cur)
check("после update_baseline: повторная сверка → skip", d5["action"] == A.ACTION_SKIP)

# ── 6. baseline_path детерминирован и санитизирует project_id ──
p = A.baseline_path(tmp / "app", "erp/main:1")
check("baseline_path: project_id санитизирован (нет / и :)",
      "/" not in p.name and ":" not in p.name)

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}"); sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
