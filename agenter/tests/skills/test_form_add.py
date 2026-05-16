# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`
"""Tests for the `form-add` skill.

Auto-generated stub. Fill in fixtures and assertions following
the patterns in `tests/skills/test_subsystem_edit.py`.

Source: `.claude/skills/form-add/SKILL.md`
Entry kind: ps1
Entry script: `.claude/skills/form-add/scripts/form-add.ps1`
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.skill_runner import run_skill  # noqa: F401


# ---------------------------------------------------------------------------
# Smoke check — entry kind: ps1
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    """A PowerShell entry point named `form-add.ps1` should exist."""
    script = skills_dir / "form-add" / "scripts" / "form-add.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


# ---------------------------------------------------------------------------
# Edge cases — one test per Write-Error/throw message in the PS1.
# Each verifies the skill exits non-zero with a recognisable message,
# NOT with an unhandled exception or silent success.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="auto-stub: implement edge case for 'Файл объекта не найден: $ObjectPath'")
def test_edge_objectpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Файл объекта не найден: $ObjectPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Не удалось определить тип объекта. Поддерживаемые типы: $($supportedTypes -join'")
def test_edge_supportedtypes_join(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Не удалось определить тип объекта. Поддерживаемые типы: $($supportedTypes -join'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Не удалось определить имя объекта из Properties/Name'")
def test_edge_properties_name(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Не удалось определить имя объекта из Properties/Name'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Недопустимое назначение: $Purpose. Допустимые: Object, List, Choice, Record'")
def test_edge_purpose_object_list_choice_record(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Недопустимое назначение: $Purpose. Допустимые: Object, List, Choice, Record'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Purpose=List недопустим для DataProcessor'")
def test_edge_purpose_list_dataprocessor(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Purpose=List недопустим для DataProcessor'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Purpose=Choice недопустим для $objectType'")
def test_edge_purpose_choice_objecttype(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Purpose=Choice недопустим для $objectType'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Purpose=Record допустим только для InformationRegister'")
def test_edge_purpose_record_informationregister(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Purpose=Record допустим только для InformationRegister'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Форма уже существует: $formMetaPath'")
def test_edge_formmetapath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Форма уже существует: $formMetaPath'."""
    raise NotImplementedError


@pytest.mark.skip(reason="auto-stub: implement edge case for 'Не найден элемент ChildObjects в $ObjectPath'")
def test_edge_childobjects_objectpath(skills_dir: Path, fixture_factory):
    """Trigger PS1 error: 'Не найден элемент ChildObjects в $ObjectPath'."""
    raise NotImplementedError


