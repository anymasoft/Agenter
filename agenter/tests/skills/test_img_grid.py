# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `img-grid` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/img-grid/SKILL.md`
Entry kind: py
Entry script: `.claude/skills/img-grid/scripts/overlay-grid.py`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: py
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="python-based skill — needs a Python-aware test, not the PS skill_runner")
def test_skill_script_exists(skills_dir: Path):
    """A Python entry point named `overlay-grid.py` should exist."""
    script = skills_dir / "img-grid" / "scripts" / "overlay-grid.py"
    assert script.exists()


# No operations or edge cases were extracted from this skill's
# SKILL.md / PS1. Either the skill is a simple wrapper without
# structured operations, or its docs use a non-standard format.
# Add tests manually as you understand the skill's interface.

