"""Tests for the `cfe-borrow` skill — output XML structure invariants.

Hand-written. Focus: each borrowed object type whose platform schema
requires <ChildObjects/> in the XML must be listed in cfe-borrow.ps1's
`$typesWithChildObjects` array. Otherwise, the borrowed XML omits the
element and 1C db_load rejects the file with:

    "ошибка формата документа - читаемое свойство не соответствует
     ожидаемому. Текущее <X>, ожидаемое ChildObjects."

This is a STATIC parse test, not a behavioural one. It catches the
"missed type in the allow-list" class of bug, which is what tripped
the prod failure on 2026-05-17 (db_load Финансы.xml).

A full behavioural cfe_borrow test would need a sample SCHEME fixture
and produce a real borrow on disk; that is tracked separately.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# Types whose borrowed XML *must* contain <ChildObjects/>, even if empty.
# Authoritative: 1C platform refuses to load files missing this element
# for these types. Discovered cumulatively from prod failures and from
# comparing borrowed output against reference XML in SCHEME.
#
# Adding a type here means: cfe-borrow.ps1 must include this type in
# `$typesWithChildObjects`. This regression-locks the fix.
PLATFORM_REQUIRES_CHILDOBJECTS: list[str] = [
    "Catalog",
    "Document",
    "Enum",
    "ExchangePlan",
    "ChartOfAccounts",
    "ChartOfCharacteristicTypes",
    "ChartOfCalculationTypes",
    "BusinessProcess",
    "Task",
    "InformationRegister",
    "AccumulationRegister",
    "AccountingRegister",
    "CalculationRegister",
    "Subsystem",  # added 2026-05-17 after prod failure on db_load Финансы.xml
]


def _parse_types_with_childobjects(ps1_text: str) -> set[str]:
    """Pull members out of `$typesWithChildObjects = @( "X","Y", ... )`.

    Tolerant of line breaks, comments inside the array, and varying
    whitespace. Returns a case-sensitive set of names.
    """
    m = re.search(
        r'\$typesWithChildObjects\s*=\s*@\(([^)]*)\)',
        ps1_text,
        flags=re.DOTALL,
    )
    if not m:
        return set()
    body = m.group(1)
    return set(re.findall(r'"([A-Za-z]+)"', body))


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

def test_skill_script_exists(skills_dir: Path):
    script = skills_dir / "cfe-borrow" / "scripts" / "cfe-borrow.ps1"
    assert script.exists(), f"Skill PS1 missing: {script}"


def test_types_with_childobjects_array_is_parseable(skills_dir: Path):
    """If this fails, the regex above stopped matching the PS1 syntax.

    Without this guard, the per-type parametrize below could silently
    misbehave on parser breakage — catch it here first.
    """
    ps1 = skills_dir / "cfe-borrow" / "scripts" / "cfe-borrow.ps1"
    listed = _parse_types_with_childobjects(ps1.read_text(encoding="utf-8"))
    assert listed, (
        "Failed to parse $typesWithChildObjects from cfe-borrow.ps1. "
        "Did the syntax change? Update _parse_types_with_childobjects."
    )
    # Sanity: a handful of well-known types are present.
    assert "Catalog" in listed
    assert "Document" in listed


# ---------------------------------------------------------------------------
# Per-type regression check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("type_name", PLATFORM_REQUIRES_CHILDOBJECTS)
def test_type_present_in_childobjects_allowlist(
    skills_dir: Path, type_name: str,
):
    """Every type that needs <ChildObjects/> at borrow time must be listed.

    When this test fails for a type, the immediate fix is to add the
    type's identifier to `$typesWithChildObjects` in cfe-borrow.ps1.
    """
    ps1 = skills_dir / "cfe-borrow" / "scripts" / "cfe-borrow.ps1"
    listed = _parse_types_with_childobjects(ps1.read_text(encoding="utf-8"))
    assert type_name in listed, (
        f"`{type_name}` is missing from $typesWithChildObjects in "
        f"cfe-borrow.ps1.\n"
        f"Without this, borrowed `{type_name}` XML omits <ChildObjects/> "
        f"and 1C db_load rejects the file.\n"
        f"Currently listed: {sorted(listed)}"
    )
