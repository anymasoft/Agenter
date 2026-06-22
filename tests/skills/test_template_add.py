# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `template-add` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/template-add/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/template-add/scripts/add-template.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `add-template.ps1` should exist."""
    script = skills_dir / "template-add" / "scripts" / "add-template.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Объект'")
def test_edge_case(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Объект'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Корневой файл объекта не найден: $rootXmlPath`nОжидается: <SrcDir>/<ObjectName>.xml`nПодсказка: SrcDir должен указывать на папку типа объектов (например Reports), а не на корень конфигурации'")
def test_edge_rootxmlpath_n_srcdir_objectname_xml_n_srcdir_reports(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Корневой файл объекта не найден: $rootXmlPath`nОжидается: <SrcDir>/<ObjectName>.xml`nПодсказка: SrcDir должен указывать на папку типа объектов (например Reports), а не на корень конфигурации'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Макет уже существует: $templateMetaPath'")
def test_edge_templatemetapath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Макет уже существует: $templateMetaPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Не найден элемент ChildObjects в $rootXmlPath'")
def test_edge_childobjects_rootxmlpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Не найден элемент ChildObjects в $rootXmlPath'."""
    raise NotImplementedError


