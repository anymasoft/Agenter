"""
Фаза 4 / Шаг 4.1 — money-cap включён как замена turn-cap (проверка прогоном).

Проверяем ТРИ вещи:
  A) money_ceiling_enabled включён в БОЕВОМ пути (DEFAULT_CONFIG desktop/main.py),
     а не только в тесте.
  B) Gating-логика оркестратора (один-в-один блок из orchestrator_sdk.py:
     compute_ceiling → MoneyGuard → add_turn) при включённом флаге РЕАЛЬНО
     активируется и обрывает задачу по достижении потолка, НЕ превышая баланс.
  C) pre-start gate (Рубеж 0, флаг billing_enforced) корректно отклоняет старт
     при недостатке баланса и пропускает при достатке.
  D) Зазор непрерывного прикрытия: при пустом ledger (баланс 0) живой потолок
     НЕ активируется — эту зону держит SDK-cap (max_turns) + детектор циклов.

Запуск: python app/tests/test_phase4_money_cap.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import money_guard as M  # noqa: E402

fails = []


def check(name, cond):
    print(("  OK  " if cond else "  FAIL") + " " + name)
    if not cond:
        fails.append(name)


def _orchestrator_gate(client_cfg: dict, balance: float, max_turns: int):
    """Точная копия gating-блока orchestrator_sdk.py (Рубеж 0 + объект Рубежа 1).
    Возвращает (start_denied_reason|None, money_guard|None)."""
    reserve = M.estimate_reserve(client_cfg, max_turns)
    start_denied = None
    if client_cfg.get("billing_enforced"):
        ok, why = M.pre_start_check(balance, reserve)
        if not ok:
            start_denied = why
    guard = None
    if client_cfg.get("money_ceiling_enabled") or client_cfg.get("billing_enforced"):
        ceiling = M.compute_ceiling(
            balance, client_cfg.get("task_cap_usd"),
            M.one_turn_reserve(client_cfg))
        if ceiling > 0:
            guard = M.MoneyGuard(ceiling)
    return start_denied, guard


# ── A. money_ceiling_enabled включён в боевом DEFAULT_CONFIG ─────────────────
print("A. Боевой путь: DEFAULT_CONFIG в desktop/main.py:")
_desktop_main = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "desktop", "main.py")
with open(_desktop_main, encoding="utf-8") as f:
    _src = f.read()
_block = _src[_src.index("DEFAULT_CONFIG = {"):_src.index("def load_config")]
check("DEFAULT_CONFIG содержит money_ceiling_enabled: True (потолок в боевом пути)",
      re.search(r'"money_ceiling_enabled"\s*:\s*True', _block) is not None)
check("billing_enforced присутствует и по умолчанию False (pre-start gate opt-in)",
      re.search(r'"billing_enforced"\s*:\s*False', _block) is not None)

# ── B. При включённом флаге потолок активируется и обрывает по достижении ────
print("\nB. Живой потолок (Рубеж 1) при money_ceiling_enabled=True:")
cfg = {"money_ceiling_enabled": True, "one_turn_reserve_usd": 0.05}
denied, guard = _orchestrator_gate(cfg, balance=0.30, max_turns=50)
check("старт НЕ отклонён (billing_enforced выкл — живой потолок не блокирует старт)",
      denied is None)
check("MoneyGuard создан (флаг включён, баланс > резерва витка)", guard is not None)
# ceiling = min(None, 0.30 - 0.05) = 0.25; копим витки по 0.10
seq = [guard.add_turn(0.10), guard.add_turn(0.10), guard.add_turn(0.10)]
check("потолок НЕ срабатывает до достижения (0.10, 0.20 < 0.25)",
      seq[0] is False and seq[1] is False)
check("потолок срабатывает при пересечении 0.25 (на 0.30)", seq[2] is True)
check("обрыв НЕ превышает баланс: cumulative 0.30 ≤ баланс 0.30",
      guard.cumulative <= 0.30 + 1e-9)

# task_cap_usd как явный потолок задачи (приоритет, если меньше остатка)
cfg2 = {"money_ceiling_enabled": True, "task_cap_usd": 0.10, "one_turn_reserve_usd": 0.05}
_, guard2 = _orchestrator_gate(cfg2, balance=100.0, max_turns=50)
check("task_cap_usd ограничивает потолок задачи (0.10, не весь баланс)",
      guard2 is not None and abs(guard2.ceiling - 0.10) < 1e-9)
check("срабатывает на task_cap_usd (0.10)", guard2.add_turn(0.10) is True)

# ── C. pre-start gate (Рубеж 0) при billing_enforced=True ───────────────────
print("\nC. pre-start gate (billing_enforced=True):")
cfg_bill = {"billing_enforced": True, "task_reserve_usd": 0.20}
denied_lo, _ = _orchestrator_gate(cfg_bill, balance=0.05, max_turns=50)
check("баланс 0.05 < резерв 0.20 → старт ОТКЛОНЁН (трат ноль)",
      denied_lo is not None and "Недостаточно" in denied_lo)
denied_hi, guard_hi = _orchestrator_gate(cfg_bill, balance=5.0, max_turns=50)
check("баланс 5.0 ≥ резерв 0.20 → старт разрешён", denied_hi is None)
check("при billing_enforced живой потолок тоже активен", guard_hi is not None)

# ── D. Зазор непрерывного прикрытия: пустой ledger (баланс 0) ────────────────
print("\nD. Пустой ledger (баланс 0) — зона SDK-cap + детектора циклов:")
_, guard_zero = _orchestrator_gate({"money_ceiling_enabled": True}, balance=0.0, max_turns=50)
check("баланс 0 → живой потолок НЕ активируется (ceiling ≤ 0); страхует SDK-cap",
      guard_zero is None)

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ (Фаза 4 / 4.1 — money-cap включён как замена turn-cap)")
