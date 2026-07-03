"""Tests for `app/task_planner.py` — plan validation invariants.

ФАЗА 2 разворота: инвариант SYNC-FIRST СНЯТ. Раньше любой план с
модифицирующей стадией обязан был начинаться с `sync-from-db`; теперь
синхронизация условная и внешняя по отношению к плану (ConfigDumpInfo-детектор
сверяет базу перед задачей и выгружает только при реальных изменениях; см.
`base_change_detector` + кнопка «Синхронизировать»). Эти тесты фиксируют новое
поведение: модифицирующий план БЕЗ sync-from-db теперь ПРОХОДИТ валидацию.

Защита от прод-инцидента 2026-05-17 (orphan-файлы) сохраняется другими
средствами: db_load-gate (сохраняемое ядро) + single-shot db_dump guard
(tool_guards 2A/2B). Сам план их больше не дублирует.

These tests are FAST — no PowerShell, no 1C, no agent. They directly
exercise the pure-Python planner functions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add agenter/app to sys.path so we can import task_planner directly.
# In production, app/main.py runs with cwd=app/, so its imports are flat.
APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

from task_planner import (  # noqa: E402
    MODIFYING_STAGE_KINDS,
    Stage,
    expected_tool_for_kind,
    validate_plan_invariants,
    validate_stages,
)


def _stage(i: int, kind: str, desc: str = "test") -> Stage:
    """Build a Stage. expected_tool is filled from STAGE_KIND_TO_TOOL."""
    return Stage(
        index=i,
        kind=kind,
        description=desc,
        expected_tool=expected_tool_for_kind(kind),
    )


# ---------------------------------------------------------------------------
# validate_plan_invariants — direct unit tests
# ---------------------------------------------------------------------------

def test_empty_plan_no_errors():
    assert validate_plan_invariants([]) == []


def test_research_only_plan_passes_without_sync():
    """Read-only plan — no modifying stages, no sync needed."""
    plan = [_stage(1, "research", "look around")]
    assert validate_plan_invariants(plan) == []


def test_research_plus_ask_user_passes():
    """Read-only chain still passes."""
    plan = [
        _stage(1, "research", "find Финансы"),
        _stage(2, "ask-user", "confirm intent"),
    ]
    assert validate_plan_invariants(plan) == []


def test_plan_with_sync_first_still_passes():
    """sync-from-db as stage 1 is still a perfectly valid plan — the agent
    may include it voluntarily (e.g. it knows the base changed manually)."""
    plan = [
        _stage(1, "sync-from-db"),
        _stage(2, "borrow-object"),
        _stage(3, "include-in-subsystem"),
        _stage(4, "validate-and-load"),
    ]
    assert validate_plan_invariants(plan) == []


# ── Фаза 2: SYNC-FIRST снят — модифицирующий план без sync теперь проходит ──

def test_modifying_plan_without_sync_now_passes():
    """Шаг 2.1: ранее этот план отвергался инвариантом SYNC-FIRST.
    Теперь он валиден — синхронизация условная и вне плана."""
    plan = [
        _stage(1, "research", "find Финансы"),
        _stage(2, "include-in-subsystem", "add Posuda to Финансы"),
    ]
    assert validate_plan_invariants(plan) == []


def test_sync_not_first_now_passes():
    """sync-from-db в середине плана больше не ошибка — инвариант снят."""
    plan = [
        _stage(1, "research"),
        _stage(2, "sync-from-db"),
        _stage(3, "borrow-object"),
    ]
    assert validate_plan_invariants(plan) == []


def test_lone_modifying_stage_now_passes():
    """Одиночная модифицирующая стадия без sync теперь валидна."""
    plan = [_stage(1, "borrow-object", "borrow X")]
    assert validate_plan_invariants(plan) == []


@pytest.mark.parametrize("kind", sorted(MODIFYING_STAGE_KINDS))
def test_every_modifying_kind_passes_without_sync(kind: str):
    """Покрытие ВСЕГО набора модифицирующих kind'ов: одиночный план с таким
    kind БЕЗ sync-from-db теперь проходит (инвариант SYNC-FIRST снят)."""
    plan = [_stage(1, kind)]
    assert validate_plan_invariants(plan) == [], (
        f"Modifying kind `{kind}` should no longer require sync-from-db "
        f"(SYNC-FIRST removed in Фаза 2)."
    )


# ---------------------------------------------------------------------------
# Non-modifying kinds NOT in the set — guard against false enforcement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["research", "ask-user", "sync-from-db", "other"])
def test_non_modifying_kinds_excluded_from_set(kind: str):
    """These kinds are NOT modifying. They must not be in MODIFYING_STAGE_KINDS.

    The set itself is retained (it labels which stages touch ext_src/БД for
    other purposes), even though SYNC-FIRST no longer consumes it.
    """
    assert kind not in MODIFYING_STAGE_KINDS, (
        f"`{kind}` must NOT be in MODIFYING_STAGE_KINDS — it doesn't write."
    )


# ---------------------------------------------------------------------------
# validate_stages — end-to-end, structural + invariants
# ---------------------------------------------------------------------------

def test_validate_stages_accepts_plan_without_sync():
    """Через полный публичный API: план без sync-from-db теперь валиден."""
    raw = [
        {"kind": "research", "description": "Найти подсистему Финансы"},
        {"kind": "include-in-subsystem", "description": "Добавить Посуда в Финансы"},
    ]
    stages, errors = validate_stages(raw)
    assert not errors, errors
    assert len(stages) == 2


def test_validate_stages_accepts_plan_with_sync():
    """План с явной sync-from-db первой стадией тоже валиден."""
    raw = [
        {"kind": "sync-from-db", "description": "Sync ext_src from DB"},
        {"kind": "research", "description": "Verify Финансы exists"},
        {"kind": "borrow-object", "description": "Borrow Subsystem.Финансы"},
        {"kind": "include-in-subsystem", "description": "Add Catalog.Расш1_Посуда"},
        {"kind": "validate-and-load", "description": "Validate and load"},
    ]
    stages, errors = validate_stages(raw)
    assert not errors, errors
    assert len(stages) == 5
    assert stages[0].kind == "sync-from-db"


def test_validate_stages_structural_errors_still_enforced():
    """Структурная валидация НЕ затронута снятием SYNC-FIRST: неизвестный
    kind по-прежнему отвергается."""
    raw = [
        {"kind": "unknown-kind", "description": "broken"},
    ]
    stages, errors = validate_stages(raw)
    assert errors
    assert any("неизвестный kind" in e or "unknown" in e.lower() for e in errors)
    # И никакого SYNC-FIRST-шума (инварианта больше нет в принципе)
    assert not any("SYNC-FIRST" in e for e in errors)
