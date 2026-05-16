# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `form-compile` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/form-compile/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/form-compile/scripts/form-compile.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `form-compile.ps1` should exist."""
    script = skills_dir / "form-compile" / "scripts" / "form-compile.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Not a 1C metadata XML: $ObjectPath'")
def test_edge_not_a_1c_metadata_xml_objectpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Not a 1C metadata XML: $ObjectPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Cannot use both -JsonPath and -FromObject. Choose one mode.'")
def test_edge_cannot_use_both_jsonpath_and_fromobject_choose_one_mode(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Cannot use both -JsonPath and -FromObject. Choose one mode.'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Either -JsonPath or -FromObject is required.'")
def test_edge_either_jsonpath_or_fromobject_is_required(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Either -JsonPath or -FromObject is required.'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Cannot derive object path from OutputPath. Use -ObjectPath explicitly.'")
def test_edge_cannot_derive_object_path_from_outputpath_use_objectpath_exp(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Cannot derive object path from OutputPath. Use -ObjectPath explicitly.'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Object file not found: $fromObjPath'")
def test_edge_object_file_not_found_fromobjpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Object file not found: $fromObjPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Object type'")
def test_edge_object_type(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Object type'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Purpose'")
def test_edge_purpose(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Purpose'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'File not found: $JsonPath'")
def test_edge_file_not_found_jsonpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'File not found: $JsonPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Invalid form attribute type'")
def test_edge_invalid_form_attribute_type(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Invalid form attribute type'."""
    raise NotImplementedError


