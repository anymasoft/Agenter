# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `cfe-patch-method` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/cfe-patch-method/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/cfe-patch-method/scripts/cfe-patch-method.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `cfe-patch-method.ps1` should exist."""
    script = skills_dir / "cfe-patch-method" / "scripts" / "cfe-patch-method.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Configuration.xml not found in: $ExtensionPath'")
def test_edge_configuration_xml_not_found_in_extensionpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Configuration.xml not found in: $ExtensionPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module or CommonModule.Name'")
def test_edge_invalid_modulepath_format_modulepath_expected_type_name_modu(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module or CommonModule.Name'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Unknown object type: $objType'")
def test_edge_unknown_object_type_objtype(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Unknown object type: $objType'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module, Type.Name.Form.FormName, or CommonModule.Name'")
def test_edge_invalid_modulepath_format_modulepath_expected_type_name_modu_2(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Invalid ModulePath format: $ModulePath. Expected: Type.Name.Module, Type.Name.Form.FormName, or CommonModule.Name'."""
    raise NotImplementedError


