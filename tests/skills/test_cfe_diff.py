# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `cfe-diff` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/cfe-diff/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/cfe-diff/scripts/cfe-diff.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `cfe-diff.ps1` should exist."""
    script = skills_dir / "cfe-diff" / "scripts" / "cfe-diff.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Extension Configuration.xml not found: $extCfg'")
def test_edge_extension_configuration_xml_not_found_extcfg(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Extension Configuration.xml not found: $extCfg'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Config Configuration.xml not found: $srcCfg'")
def test_edge_config_configuration_xml_not_found_srccfg(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Config Configuration.xml not found: $srcCfg'."""
    raise NotImplementedError


