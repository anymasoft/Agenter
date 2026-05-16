# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `skd-compile` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/skd-compile/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/skd-compile/scripts/skd-compile.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `skd-compile.ps1` should exist."""
    script = skills_dir / "skd-compile" / "scripts" / "skd-compile.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Cannot use both -DefinitionFile and -Value'")
def test_edge_cannot_use_both_definitionfile_and_value(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Cannot use both -DefinitionFile and -Value'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Either -DefinitionFile or -Value is required'")
def test_edge_either_definitionfile_or_value_is_required(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Either -DefinitionFile or -Value is required'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Definition file not found: $DefinitionFile'")
def test_edge_definition_file_not_found_definitionfile(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Definition file not found: $DefinitionFile'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'JSON must have at least one entry in'")
def test_edge_json_must_have_at_least_one_entry_in(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'JSON must have at least one entry in'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Query file not found: $filePath (searched: $($candidates -join'")
def test_edge_query_file_not_found_filepath_searched_candidates_join(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Query file not found: $filePath (searched: $($candidates -join'."""
    raise NotImplementedError


