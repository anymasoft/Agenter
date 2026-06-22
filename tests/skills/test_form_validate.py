# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `form-validate` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/form-validate/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/form-validate/scripts/form-validate.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `form-validate.ps1` should exist."""
    script = skills_dir / "form-validate" / "scripts" / "form-validate.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'File not found: $FormPath'")
def test_edge_file_not_found_formpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'File not found: $FormPath'."""
    raise NotImplementedError


