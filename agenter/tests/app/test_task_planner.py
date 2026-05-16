"""Tests for `app/task_planner.py` — plan validation invariants.

Covers the SYNC-FIRST invariant introduced 2026-05-17: any plan with
modifying stages must start with `sync-from-db`. This prevents the
class of prod failures where orphan files from a previously failed
task pollute the next modification (e.g. a borrowed but never-loaded
Subsystem XML stays on disk and breaks subsequent db_load attempts).

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


def test_plan_with_sync_first_passes():
    """Canonical happy path: sync-from-db is stage 1."""
    plan = [
        _stage(1, "sync-from-db"),
        _stage(2, "borrow-object"),
        _stage(3, "include-in-subsystem"),
        _stage(4, "validate-and-load"),
    ]
    assert validate_plan_invariants(plan) == []


def test_prod_failure_pattern_rejected():
    """Exact plan shape that bit us 2026-05-17:
    [research, include-in-subsystem]. The orphan Финансы.xml from the
    previous failed task stayed on disk and broke db_load.
    """
    plan = [
        _stage(1, "research", "find Финансы"),
        _stage(2, "include-in-subsystem", "add Posuda to Финансы"),
    ]
    errors = validate_plan_invariants(plan)
    assert errors, "This is the prod regression — must be rejected"
    assert "SYNC-FIRST" in errors[0]


def test_sync_present_but_not_first_rejected():
    """sync-from-db must be FIRST, not just somewhere."""
    plan = [
        _stage(1, "research"),
        _stage(2, "sync-from-db"),
        _stage(3, "borrow-object"),
    ]
    errors = validate_plan_invariants(plan)
    assert errors, "sync-from-db must be position 1, not later"


def test_lone_modifying_stage_rejected():
    """Single modifying stage without sync."""
    plan = [_stage(1, "borrow-object", "borrow X")]
    errors = validate_plan_invariants(plan)
    assert errors


def test_error_message_names_offending_stage():
    """Error should identify which stage triggered the invariant."""
    plan = [
        _stage(1, "research"),
        _stage(2, "create-form", "build form"),
    ]
    errors = validate_plan_invariants(plan)
    assert errors
    # Helpful diagnostic for the agent
    assert "create-form" in errors[0] or "#2" in errors[0]


@pytest.mark.parametrize("kind", sorted(MODIFYING_STAGE_KINDS))
def test_every_modifying_kind_demands_sync(kind: str):
    """Coverage for the WHOLE set of modifying kinds: a single-stage
    plan with that kind alone must be rejected.

    If a new modifying kind is added later, this test catches its
    omission from MODIFYING_STAGE_KINDS.
    """
    plan = [_stage(1, kind)]
    errors = validate_plan_invariants(plan)
    assert errors, (
        f"Modifying kind `{kind}` should require sync-from-db first, "
        f"but the invariant did not fire."
    )


# ---------------------------------------------------------------------------
# Non-modifying kinds NOT in the set — guard against false enforcement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["research", "ask-user", "sync-from-db", "other"])
def test_non_modifying_kinds_excluded_from_set(kind: str):
    """These kinds are NOT modifying. They must not be in MODIFYING_STAGE_KINDS.

    If someone accidentally adds 'research' here, every plan would need
    sync-from-db before research, which is wrong (research is read-only).
    """
    assert kind not in MODIFYING_STAGE_KINDS, (
        f"`{kind}` must NOT be in MODIFYING_STAGE_KINDS — it doesn't write."
    )


# ---------------------------------------------------------------------------
# validate_stages — end-to-end, structural + invariants
# ---------------------------------------------------------------------------

def test_validate_stages_rejects_prod_failure_pattern():
    """Through the full public API (raw dicts in, errors out)."""
    raw = [
        {"kind": "research", "description": "Найти подсистему Финансы"},
        {"kind": "include-in-subsystem", "description": "Добавить Посуда в Финансы"},
    ]
    stages, errors = validate_stages(raw)
    assert errors, "Plan that failed in prod must now be rejected at plan_task time"
    assert any("SYNC-FIRST" in e for e in errors)


def test_validate_stages_accepts_corrected_prod_plan():
    """Same scenario, but agent included sync-from-db as stage 1."""
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


def test_validate_stages_structural_errors_short_circuit_invariants():
    """If structural validation fails, invariant errors are not added too —
    avoids confusing the agent with overlapping problems."""
    raw = [
        {"kind": "unknown-kind", "description": "broken"},
    ]
    stages, errors = validate_stages(raw)
    assert errors
    # Should report the structural problem, not the SYNC-FIRST issue
    assert any("неизвестный kind" in e or "unknown" in e.lower() for e in errors)
    assert not any("SYNC-FIRST" in e for e in errors)
