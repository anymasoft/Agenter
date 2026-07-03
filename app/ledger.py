"""
Фаза 1 / Шаг 1.2 — баланс-ledger (net-new, sqlite, параллельно клетке).

Реестр предоплаченного баланса + журнал кредит/дебет. Дебет = фактическая
стоимость задачи из `_trace_rollup` (`cost_source="calc-effective"`, DeepSeek-
прайс) на финализации. Транзакционно — параллельные задачи дебетуют один
баланс через сериализацию писателей sqlite (`BEGIN IMMEDIATE`).

Живёт в той же БД, что tasks/sessions — `app/agenter.db`. UI-оплаты ПОКА нет:
только реестр + API пополнить/списать/остаток. Стартовый баланс задаётся
вручную (для теста — `credit`).

Денежный потолок (Шаг 1.3) читает `get_balance()` для pre-start gate и живого
лимита; дебет здесь — на финализации задачи.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Та же БД, что tasks/sessions (см. main.DB_PATH / orchestrator_sdk).
DEFAULT_DB_PATH = Path(__file__).parent / "agenter.db"
DEFAULT_ACCOUNT = "default"


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_ledger(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Создаёт таблицы баланса и журнала (идемпотентно)."""
    conn = _connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balance (
                account TEXT PRIMARY KEY,
                amount  REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL,
                ts      TEXT NOT NULL,
                kind    TEXT NOT NULL CHECK (kind IN ('credit','debit')),
                amount  REAL NOT NULL,
                task_id TEXT,
                note    TEXT
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO balance(account, amount) VALUES (?, 0)",
            (DEFAULT_ACCOUNT,),
        )
        conn.commit()
    finally:
        conn.close()


def get_balance(account: str = DEFAULT_ACCOUNT,
                db_path: Path | str = DEFAULT_DB_PATH) -> float:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT amount FROM balance WHERE account=?", (account,)
        ).fetchone()
        return float(row[0]) if row else 0.0
    finally:
        conn.close()


def _apply(kind: str, amount: float, account: str, task_id: str | None,
           note: str, db_path: Path | str) -> float:
    """Атомарно меняет баланс и пишет строку журнала. Возвращает новый остаток.
    BEGIN IMMEDIATE сериализует писателей → параллельные задачи не теряют апдейты."""
    if amount < 0:
        raise ValueError("amount должен быть ≥ 0; направление задаёт kind")
    delta = amount if kind == "credit" else -amount
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _connect(db_path)
    try:
        conn.isolation_level = None  # ручное управление транзакцией
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO balance(account, amount) VALUES (?, 0)",
            (account,),
        )
        conn.execute(
            "UPDATE balance SET amount = amount + ? WHERE account=?",
            (delta, account),
        )
        conn.execute(
            "INSERT INTO ledger(account, ts, kind, amount, task_id, note) "
            "VALUES (?,?,?,?,?,?)",
            (account, ts, kind, amount, task_id, note),
        )
        row = conn.execute(
            "SELECT amount FROM balance WHERE account=?", (account,)
        ).fetchone()
        conn.execute("COMMIT")
        return float(row[0]) if row else 0.0
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def credit(amount: float, account: str = DEFAULT_ACCOUNT, *,
           note: str = "", db_path: Path | str = DEFAULT_DB_PATH) -> float:
    """Пополнение. Возвращает новый остаток."""
    return _apply("credit", float(amount), account, None, note, db_path)


def debit(amount: float, account: str = DEFAULT_ACCOUNT, *,
          task_id: str | None = None, note: str = "",
          db_path: Path | str = DEFAULT_DB_PATH) -> float:
    """Списание фактической стоимости задачи. Возвращает новый остаток.
    Допускается уход в небольшой минус (перерасход ≤ хвост одного витка, см.
    Фаза 0 / Замер 1) — баланс честно отражает факт, gate решает на старте."""
    return _apply("debit", float(amount), account, task_id, note, db_path)


def get_ledger(account: str = DEFAULT_ACCOUNT, limit: int = 50,
               db_path: Path | str = DEFAULT_DB_PATH) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, kind, amount, task_id, note FROM ledger "
            "WHERE account=? ORDER BY id DESC LIMIT ?",
            (account, limit),
        ).fetchall()
        return [
            {"id": r[0], "ts": r[1], "kind": r[2], "amount": r[3],
             "task_id": r[4], "note": r[5]}
            for r in rows
        ]
    finally:
        conn.close()
