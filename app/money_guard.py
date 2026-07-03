"""
Фаза 1 / Шаг 1.3 — денежный потолок (net-new, параллельно клетке).

Три рубежа из разведки 3.1 (Рубеж 2 НЕ нужен — Фаза 0 подтвердила, что
`interrupt()` режет виток mid-turn за 15–31 мс):

  • Рубеж 0 — pre-start gate: перед `client.query()` сверяем остаток баланса
    с резервом задачи; баланс < резерв → НЕ стартуем (трат ноль).
  • Рубеж 1 — живой потолок по витку: в `_stream_messages`, где уже считается
    стоимость витка, накапливаем `cumulative` и при достижении `task_ceiling`
    зовём `client.interrupt()` + честная финализация.

`task_ceiling = min(потолок задачи, остаток − резерв одного витка)` — резерв
одного витка делает гарантию «не превысить предоплату» твёрдой даже при
перерасходе в один хвост витка.

Этот модуль — чистая логика (легко тестируется без LLM). Enforcement (interrupt,
блокировка старта) живёт в orchestrator_sdk и включается флагами client_cfg,
чтобы в Фазе 1 не ломать работающее приложение (клетка остаётся backstop'ом).
"""
from __future__ import annotations

# Грубые оценки для резерва (DeepSeek-режим). Тюнятся; при заданном
# task_reserve_usd/one_turn_reserve_usd в config — берутся они.
DEFAULT_TURN_COST_USD: float = 0.02
MIN_RESERVE_USD: float = 0.05


def estimate_reserve(client_cfg: dict, max_effective_turns: int) -> float:
    """Минимальный резерв задачи: явный из config или max_turns × оценка витка."""
    explicit = client_cfg.get("task_reserve_usd")
    if explicit:
        return float(explicit)
    return max(MIN_RESERVE_USD, int(max_effective_turns or 0) * DEFAULT_TURN_COST_USD)


def one_turn_reserve(client_cfg: dict) -> float:
    """Резерв одного максимального витка — буфер под mid-turn перерасход."""
    return float(client_cfg.get("one_turn_reserve_usd") or DEFAULT_TURN_COST_USD)


def pre_start_check(balance: float, reserve: float) -> tuple[bool, str]:
    """Рубеж 0. Возвращает (можно_стартовать, причина_если_нет)."""
    if balance >= reserve:
        return True, ""
    return False, (
        f"Недостаточно баланса для старта задачи: остаток ${balance:.4f} < "
        f"резерв ${reserve:.4f}. Пополни баланс — задача не запущена (трат ноль)."
    )


def compute_ceiling(balance: float, task_cap: float | None,
                    one_turn: float) -> float:
    """Рубеж 1. `task_ceiling = min(потолок задачи, остаток − резерв витка)`."""
    by_balance = balance - one_turn
    if task_cap is not None and task_cap > 0:
        return min(float(task_cap), by_balance)
    return by_balance


class MoneyGuard:
    """Живой накопитель стоимости по виткам. add_turn() → True, когда пора
    звать interrupt() (потолок достигнут). Срабатывает один раз."""

    def __init__(self, ceiling: float):
        self.ceiling = float(ceiling)
        self.cumulative = 0.0
        self.tripped = False

    def add_turn(self, cost: float | None) -> bool:
        if cost:
            self.cumulative += float(cost)
        if not self.tripped and self.cumulative >= self.ceiling:
            self.tripped = True
            return True
        return False

    def remaining(self) -> float:
        return self.ceiling - self.cumulative
