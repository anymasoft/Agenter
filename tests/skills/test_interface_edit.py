# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `interface-edit` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/interface-edit/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/interface-edit/scripts/interface-edit.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `interface-edit.ps1` should exist."""
    script = skills_dir / "interface-edit" / "scripts" / "interface-edit.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Cannot use both -DefinitionFile and -Operation'")
def test_edge_cannot_use_both_definitionfile_and_operation(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Cannot use both -DefinitionFile and -Operation'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Either -DefinitionFile or -Operation is required'")
def test_edge_either_definitionfile_or_operation_is_required(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Either -DefinitionFile or -Operation is required'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'File not found: $CIPath (use -CreateIfMissing to create)'")
def test_edge_file_not_found_cipath_use_createifmissing_to_create(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'File not found: $CIPath (use -CreateIfMissing to create)'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Expected <CommandInterface> root element, got <$($root.LocalName)>'")
def test_edge_expected_commandinterface_root_element_got_root_localname(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Expected <CommandInterface> root element, got <$($root.LocalName)>'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'place requires {command, group}'")
def test_edge_place_requires_command_group(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'place requires {command, group}'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'order requires {group, commands:[...]}'")
def test_edge_order_requires_group_commands(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'order requires {group, commands:[...]}'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'subsystem-order requires array of subsystem paths'")
def test_edge_subsystem_order_requires_array_of_subsystem_paths(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'subsystem-order requires array of subsystem paths'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'group-order requires array of group names'")
def test_edge_group_order_requires_array_of_group_names(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'group-order requires array of group names'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Unknown operation: $opName'")
def test_edge_unknown_operation_opname(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Unknown operation: $opName'."""
    raise NotImplementedError


