"""Фаза 1 / Шаг 1.2 — проверка баланс-ledger. Использует ВРЕМЕННУЮ БД, не agenter.db.
Запуск: python app/tests/test_phase1_ledger.py"""
import sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ledger  # noqa: E402

fails = []
def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)

tmp = Path(tempfile.mkdtemp()) / "ledger_test.db"
ledger.init_ledger(tmp)

# ── базовое: кредит/дебет/остаток ──
check("старт баланс = 0", ledger.get_balance(db_path=tmp) == 0.0)
b1 = ledger.credit(100.0, db_path=tmp)
check("после пополнения 100 → 100", b1 == 100.0)
b2 = ledger.debit(2.5, task_id="t1", note="task cost", db_path=tmp)
check("дебет фактической стоимости 2.5 → 97.5", b2 == 97.5)
check("get_balance отражает остаток", ledger.get_balance(db_path=tmp) == 97.5)
led = ledger.get_ledger(db_path=tmp)
check("журнал содержит 2 записи (credit+debit)", len(led) == 2 and led[0]["kind"] == "debit")

# ── гонка: 50 параллельных дебетов по 0.10 из 97.5 → 92.5 ровно ──
start = ledger.get_balance(db_path=tmp)
N, AMT = 50, 0.10
def worker(i):
    ledger.debit(AMT, task_id=f"par{i}", note="concurrent", db_path=tmp)
threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
for t in threads: t.start()
for t in threads: t.join()
end = ledger.get_balance(db_path=tmp)
expected = round(start - N * AMT, 2)
check(f"гонка: {N} параллельных дебетов не теряют апдейты ({end:.2f} == {expected:.2f})",
      round(end, 2) == expected)
check("гонка: в журнале ровно N+2 записей",
      len(ledger.get_ledger(limit=999, db_path=tmp)) == N + 2)

# ── негатив: amount<0 запрещён ──
neg_ok = False
try:
    ledger.debit(-1.0, db_path=tmp)
except ValueError:
    neg_ok = True
check("отрицательный amount отвергается (направление — через kind)", neg_ok)

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}"); sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
