# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `skd-info` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/skd-info/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/skd-info/scripts/skd-info.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `skd-info.ps1` should exist."""
    script = skills_dir / "skd-info" / "scripts" / "skd-info.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'No DCS templates found in: $originalPath'")
def test_edge_no_dcs_templates_found_in_originalpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'No DCS templates found in: $originalPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'File not found: $TemplatePath'")
def test_edge_file_not_found_templatepath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'File not found: $TemplatePath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Dataset'")
def test_edge_dataset(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Dataset'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'No Query dataset found'")
def test_edge_no_query_dataset_found(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'No Query dataset found'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Dataset has no query element'")
def test_edge_dataset_has_no_query_element(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Dataset has no query element'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Batch $Batch not found (total: $($batches.Count))'")
def test_edge_batch_batch_not_found_total_batches_count(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Batch $Batch not found (total: $($batches.Count))'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Field'")
def test_edge_field(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Field'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Calculated field'")
def test_edge_calculated_field(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Calculated field'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Resource'")
def test_edge_resource(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Resource'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Variant'")
def test_edge_variant(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Variant'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Trace mode requires -Name <field_name_or_title>'")
def test_edge_trace_mode_requires_name_field_name_or_title(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Trace mode requires -Name <field_name_or_title>'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Group or field'")
def test_edge_group_or_field(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Group or field'."""
    raise NotImplementedError


