# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `cfe-init` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/cfe-init/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/cfe-init/scripts/cfe-init.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `cfe-init.ps1` should exist."""
    script = skills_dir / "cfe-init" / "scripts" / "cfe-init.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Configuration.xml already exists: $cfgFile'")
def test_edge_configuration_xml_already_exists_cfgfile(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Configuration.xml already exists: $cfgFile'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'No Configuration.xml in config directory: $ConfigPath'")
def test_edge_no_configuration_xml_in_config_directory_configpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'No Configuration.xml in config directory: $ConfigPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Config file not found: $ConfigPath'")
def test_edge_config_file_not_found_configpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Config file not found: $ConfigPath'."""
    raise NotImplementedError


