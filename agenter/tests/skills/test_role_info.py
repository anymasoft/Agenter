# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `role-info` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/role-info/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/role-info/scripts/role-info.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `role-info.ps1` should exist."""
    script = skills_dir / "role-info" / "scripts" / "role-info.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# No operations or edge cases were extracted from this skill's
# SKILL.md / PS1. Either the skill is a simple wrapper without
# structured operations, or its docs use a non-standard format.
# Add tests manually as you understand the skill's interface.

