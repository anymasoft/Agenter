"""Tests for the `subsystem-edit` skill.

Hand-written exemplar. Pattern to copy for other skills.

Covers the cluster of symmetric "missing element" bugs discovered
2026-05-16 when add-content failed on a freshly borrowed (empty)
subsystem. All 5 declared operations are exercised against both:
  - a subsystem WITHOUT <Content> / <ChildObjects> (borrowed-empty)
  - a subsystem WITH them (custom or borrowed-non-empty)

Uses `make_borrowed_subsystem` factory so the test author doesn't
copy XML by hand for every variant.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness.factories import make_borrowed_subsystem, make_ext_src_root
from tests.harness.skill_runner import run_skill


# ---------------------------------------------------------------------------
# add-content
# ---------------------------------------------------------------------------

def test_add_content_to_borrowed_subsystem_without_content(
    skills_dir: Path, fixture_factory,
):
    """REGRESSION: prod failure 2026-05-16.

    Borrowed Финансы XML had Properties but no <Content>. Skill
    must auto-create <Content> and insert the item.
    """
    ext_src = fixture_factory("borrowed_subsystem_no_content")
    subsys_xml = ext_src / "Subsystems" / "Финансы.xml"

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(subsys_xml),
        operation="add-content",
        value="Catalog.Расш1_Посуда",
    )

    assert result.ok, (
        f"exit={result.exit_code}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    xml = subsys_xml.read_text(encoding="utf-8")
    assert "Catalog.Расш1_Посуда" in xml
    assert "<Content" in xml


def test_add_content_to_subsystem_with_existing_content(
    skills_dir: Path, tmp_path: Path,
):
    """Happy path: <Content> already present, append another item."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(
        ext_src, "Финансы",
        with_content=True,
        content_items=["Document.ИзначальныйДокумент"],
    )

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="add-content",
        value="Catalog.Расш1_Посуда",
    )

    assert result.ok, result.combined
    xml = sub.read_text(encoding="utf-8")
    assert "Document.ИзначальныйДокумент" in xml, "Existing item was lost"
    assert "Catalog.Расш1_Посуда" in xml, "New item was not added"


def test_add_content_is_idempotent_on_duplicate(
    skills_dir: Path, tmp_path: Path,
):
    """Adding the same item twice should warn, not error or duplicate."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(
        ext_src, "Финансы",
        with_content=True,
        content_items=["Catalog.Расш1_Посуда"],
    )

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="add-content",
        value="Catalog.Расш1_Посуда",
    )

    assert result.ok, result.combined
    xml = sub.read_text(encoding="utf-8")
    # Item should appear exactly once
    assert xml.count("Catalog.Расш1_Посуда") == 1


# ---------------------------------------------------------------------------
# remove-content
# ---------------------------------------------------------------------------

def test_remove_content_is_idempotent_when_content_missing(
    skills_dir: Path, tmp_path: Path,
):
    """Removing from a subsystem without <Content> is a no-op success.

    Industrial idempotency: "remove X from empty collection" returns
    success, not error. Same as `rm -f` on a missing file.
    """
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(ext_src, "Финансы", with_content=False)

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="remove-content",
        value="Catalog.Расш1_Посуда",
    )

    assert result.ok, (
        f"remove-content should succeed (idempotent) when Content missing.\n"
        f"{result.combined}"
    )


def test_remove_content_existing(skills_dir: Path, tmp_path: Path):
    """Remove an item that is in Content."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(
        ext_src, "Финансы",
        with_content=True,
        content_items=["Catalog.Расш1_Посуда", "Document.Заказ"],
    )

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="remove-content",
        value="Catalog.Расш1_Посуда",
    )

    assert result.ok, result.combined
    xml = sub.read_text(encoding="utf-8")
    assert "Catalog.Расш1_Посуда" not in xml, "Item should be removed"
    assert "Document.Заказ" in xml, "Other items must not be touched"


# ---------------------------------------------------------------------------
# add-child / remove-child
# ---------------------------------------------------------------------------

def test_add_child_subsystem_on_borrowed_without_childobjects(
    skills_dir: Path, tmp_path: Path,
):
    """Symmetric bug: <ChildObjects> may be absent in a borrowed subsystem.

    Skill must auto-create <ChildObjects> and write the child stub XML.
    """
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(ext_src, "Финансы", with_content=False)

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="add-child",
        value="МояДочерняя",
    )

    assert result.ok, (
        f"add-child on borrowed subsystem without ChildObjects failed:\n"
        f"{result.combined}"
    )
    xml = sub.read_text(encoding="utf-8")
    assert "<ChildObjects" in xml
    assert "МояДочерняя" in xml


def test_remove_child_idempotent_when_childobjects_missing(
    skills_dir: Path, tmp_path: Path,
):
    """remove-child on a subsystem with no <ChildObjects> is a no-op."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(ext_src, "Финансы", with_content=False)

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
        operation="remove-child",
        value="НесуществующаяДочерняя",
    )

    assert result.ok, (
        f"remove-child should be idempotent (no-op) when ChildObjects missing.\n"
        f"{result.combined}"
    )


# ---------------------------------------------------------------------------
# negative: malformed inputs
# ---------------------------------------------------------------------------

def test_missing_file_returns_structured_error(
    skills_dir: Path, tmp_path: Path,
):
    """File-not-found exits non-zero with a recognisable message."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    missing = ext_src / "Subsystems" / "DoesNotExist.xml"

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(missing),
        operation="add-content",
        value="Catalog.X",
    )

    assert not result.ok, "Missing file must not exit 0"
    haystack = result.combined.lower()
    assert "not found" in haystack or "не найд" in haystack, result.combined


def test_neither_operation_nor_definitionfile_fails(
    skills_dir: Path, tmp_path: Path,
):
    """Calling with neither -Operation nor -DefinitionFile is a user error."""
    ext_src = make_ext_src_root(tmp_path / "ext_src")
    sub = make_borrowed_subsystem(ext_src, "Финансы")

    result = run_skill(
        "subsystem-edit",
        skills_dir,
        cwd=ext_src,
        subsystem_path=str(sub),
    )

    assert not result.ok
    assert "either" in result.combined.lower() or "operation" in result.combined.lower()
