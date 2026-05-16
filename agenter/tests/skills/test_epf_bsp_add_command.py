# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `epf-bsp-add-command` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/epf-bsp-add-command/SKILL.md`
Entry kind: doc-only
Entry script: `.claude/skills/epf-bsp-add-command/scripts/(no script)`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: doc-only
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="documentation-only skill: no executable to test")
def test_skill_is_documentation_only(skills_dir: Path):
    """No scripts/ entry point — this skill is documentation only."""
    pass


# No operations or edge cases were extracted from this skill's
# SKILL.md / PS1. Either the skill is a simple wrapper without
# structured operations, or its docs use a non-standard format.
# Add tests manually as you understand the skill's interface.

