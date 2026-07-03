"""Фаза 1 / Шаг 1.3 — проверка денежного потолка (чистая логика, без LLM).
Запуск: python app/tests/test_phase1_money_guard.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import money_guard as M  # noqa: E402

fails = []
def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)

# ── pre-start gate ──
ok, why = M.pre_start_check(balance=1.0, reserve=0.2)
check("gate: достаточно баланса → старт разрешён", ok and why == "")
ok2, why2 = M.pre_start_check(balance=0.05, reserve=0.2)
check("gate: баланс < резерв → старт отклонён, есть причина", (not ok2) and "Недостаточно" in why2)

# ── ceiling = min(task_cap, остаток − резерв витка) ──
c1 = M.compute_ceiling(balance=10.0, task_cap=2.0, one_turn=0.05)
check("ceiling: ограничен потолком задачи (2.0 < 9.95)", c1 == 2.0)
c2 = M.compute_ceiling(balance=1.0, task_cap=5.0, one_turn=0.05)
check("ceiling: ограничен остатком−резерв (0.95 < 5.0)", abs(c2 - 0.95) < 1e-9)
c3 = M.compute_ceiling(balance=1.0, task_cap=None, one_turn=0.10)
check("ceiling: без потолка задачи = остаток−резерв (0.90)", abs(c3 - 0.90) < 1e-9)

# ── живой потолок: срабатывает при пересечении, один раз ──
g = M.MoneyGuard(ceiling=0.30)
seq = [g.add_turn(0.10), g.add_turn(0.10), g.add_turn(0.10), g.add_turn(0.10)]
print("add_turn seq:", seq, "cumulative:", round(g.cumulative, 4))
check("живой: не срабатывает до достижения (0.10,0.20)", seq[0] is False and seq[1] is False)
check("живой: срабатывает РОВНО при достижении 0.30", seq[2] is True)
check("живой: повторно НЕ срабатывает (один interrupt)", seq[3] is False and g.tripped)

# ── резерв: max_turns × оценка витка, либо явный ──
r = M.estimate_reserve({}, max_effective_turns=120)
check("reserve: дефолт = max_turns × оценка витка (>0)", r > 0)
r2 = M.estimate_reserve({"task_reserve_usd": 0.5}, max_effective_turns=120)
check("reserve: явный task_reserve_usd имеет приоритет", r2 == 0.5)

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}"); sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
