"""Auto-generate test stubs for every skill that doesn't have one yet.

Industrial pattern: when you have N similar units to test, you don't
write N skeletons by hand — you generate them from a manifest, then
fill in the bodies. The generator stays accurate because it re-reads
the manifest (SKILL.md + PS1) each time.

What this generates:
  For each skill without a test_<skill>.py file, write a stub that:
    - has the right imports and parametrize structure
    - lists declared operations and edge cases as separate test functions
    - skips each with an explanatory reason
    - documents what to fill in

Existing test files are NEVER overwritten unless --force is passed.

Usage:
  cd agenter
  .\\backend\\.venv\\Scripts\\python.exe -m tests.audit.scaffold_tests
  .\\backend\\.venv\\Scripts\\python.exe -m tests.audit.scaffold_tests --force
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tests.audit.skill_audit import SkillInfo, collect_skills

TESTS_DIR = Path(__file__).resolve().parent.parent
SKILL_TESTS_DIR = TESTS_DIR / "skills"

# Sentinel placed at the top of every auto-generated stub. The scaffold
# tool may re-overwrite files containing this marker even without --force,
# so that audit changes propagate cleanly. Hand-edited tests should remove
# the marker (and ideally remove the auto-stub @pytest.mark.skip lines).
AUTOGEN_MARKER = "# AUTO-GENERATED-TESTS: regen with `python -m tests.audit.scaffold_tests`"


# Identifier sanitization: convert any string into a valid Python ident.
_INVALID_CHAR = re.compile(r"[^a-z0-9_]+")


def py_ident(s: str, max_len: int = 60) -> str:
    """Lowercase, replace runs of non-[a-z0-9_] with underscore, truncate.

    Used to derive Python function names from operation strings and
    error messages. Pure ASCII to dodge any source-encoding issues.
    """
    s = s.lower()
    # Strip XML-ish tags, common punctuation that doesn't carry meaning
    s = s.replace("<", " ").replace(">", " ").replace("/", " ")
    s = _INVALID_CHAR.sub("_", s)
    s = s.strip("_")
    if not s:
        s = "case"
    if s[0].isdigit():
        s = "x" + s
    return s[:max_len]


def render_stub(info: SkillInfo) -> str:
    """Build a test file body for a skill.

    Pattern:
      - first line: AUTOGEN_MARKER so scaffold can safely overwrite
      - one test_smoke shaped to the skill's entry_kind
      - one test_<op> per declared operation
      - one test_edge_<msg> per Write-Error/throw message
      - all skipped with informative reason — pytest still collects them
    """
    entry_label = info.entry_script.name if info.entry_script else "(no script)"
    mod_doc = (
        f'"""Tests for the `{info.name}` skill.\n\n'
        f"Auto-generated stub. Fill in fixtures and assertions following\n"
        f"the patterns in `tests/skills/test_subsystem_edit.py`.\n\n"
        f"Source: `.claude/skills/{info.name}/SKILL.md`\n"
        f"Entry kind: {info.entry_kind}\n"
        f"Entry script: `.claude/skills/{info.name}/scripts/{entry_label}`\n"
        '"""'
    )

    lines: list[str] = []
    lines.append(AUTOGEN_MARKER)
    lines.append(mod_doc)
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from pathlib import Path")
    lines.append("")
    lines.append("import pytest")
    lines.append("")
    lines.append("from tests.harness.skill_runner import run_skill  # noqa: F401")
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append(f"# Smoke check — entry kind: {info.entry_kind}")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")
    if info.entry_kind == "ps1" and info.entry_script is not None:
        lines.append("def test_skill_script_exists(skills_dir: Path):")
        lines.append(f'    """A PowerShell entry point named `{info.entry_script.name}` should exist."""')
        lines.append(f'    script = skills_dir / "{info.name}" / "scripts" / "{info.entry_script.name}"')
        lines.append('    assert script.exists(), f"Skill PS1 missing: {script}"')
    elif info.entry_kind == "py" and info.entry_script is not None:
        lines.append('@pytest.mark.skip(reason="python-based skill — needs a Python-aware test, not the PS skill_runner")')
        lines.append("def test_skill_script_exists(skills_dir: Path):")
        lines.append(f'    """A Python entry point named `{info.entry_script.name}` should exist."""')
        lines.append(f'    script = skills_dir / "{info.name}" / "scripts" / "{info.entry_script.name}"')
        lines.append('    assert script.exists()')
    else:
        # doc-only or missing
        lines.append('@pytest.mark.skip(reason="documentation-only skill: no executable to test")')
        lines.append("def test_skill_is_documentation_only(skills_dir: Path):")
        lines.append('    """No scripts/ entry point — this skill is documentation only."""')
        lines.append('    pass')
    lines.append("")
    lines.append("")

    if info.operations:
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("# Happy paths — one test per declared operation in SKILL.md.")
        lines.append("# Fill in fixture name and skill args, then drop the @skip decorator.")
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("")
        seen: set[str] = set()
        for op in info.operations:
            fn = py_ident(op)
            if fn in seen:
                continue
            seen.add(fn)
            lines.append(
                f'@pytest.mark.skip(reason="auto-stub: implement happy path for operation `{op}`")'
            )
            lines.append(f"def test_op_{fn}(skills_dir: Path, fixture_factory):")
            lines.append(f'    """Happy path for `{op}` operation."""')
            lines.append('    raise NotImplementedError')
            lines.append("")
            lines.append("")

    if info.edge_cases:
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("# Edge cases — one test per Write-Error/throw message in the PS1.")
        lines.append("# Each verifies the skill exits non-zero with a recognisable message,")
        lines.append("# NOT with an unhandled exception or silent success.")
        lines.append("# ---------------------------------------------------------------------------")
        lines.append("")
        seen_edge: set[str] = set()
        for msg in info.edge_cases:
            fn = py_ident(msg)
            if fn in seen_edge:
                # Keep test names unique even when messages share keywords
                suffix = 2
                while f"{fn}_{suffix}" in seen_edge:
                    suffix += 1
                fn = f"{fn}_{suffix}"
            seen_edge.add(fn)
            safe_msg = msg.replace('"', "'").replace("\\", "/")
            lines.append(
                f'@pytest.mark.skip(reason="auto-stub: implement edge case for {safe_msg!r}")'
            )
            lines.append(f"def test_edge_{fn}(skills_dir: Path, fixture_factory):")
            lines.append(f'    """Trigger PS1 error: {safe_msg!r}."""')
            lines.append('    raise NotImplementedError')
            lines.append("")
            lines.append("")

    if not info.operations and not info.edge_cases:
        lines.append("# No operations or edge cases were extracted from this skill's")
        lines.append("# SKILL.md / PS1. Either the skill is a simple wrapper without")
        lines.append("# structured operations, or its docs use a non-standard format.")
        lines.append("# Add tests manually as you understand the skill's interface.")
        lines.append("")

    return "\n".join(lines) + "\n"


def stub_path(skill_name: str) -> Path:
    return SKILL_TESTS_DIR / f"test_{skill_name.replace('-', '_')}.py"


def _is_autogen(path: Path) -> bool:
    """Return True if the file was produced by this scaffold tool.

    Two detection strategies:
        1. New style: AUTOGEN_MARKER on or near the first line.
        2. Legacy style: "Auto-generated stub" phrase in the module
           docstring of pre-marker stubs (one-time migration path).

    Hand-edited test files have neither pattern and are never overwritten
    unless --force is passed.
    """
    try:
        head = path.read_text(encoding="utf-8").splitlines()[:20]
    except (OSError, UnicodeDecodeError):
        return False
    for ln in head:
        if "AUTO-GENERATED-TESTS" in ln:
            return True
        if "Auto-generated stub" in ln:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite ALL existing test files, including hand-edited ones.",
    )
    args = ap.parse_args(argv)

    SKILL_TESTS_DIR.mkdir(parents=True, exist_ok=True)
    skills = collect_skills()
    if not skills:
        print("[ERROR] No skills found.", file=sys.stderr)
        return 1

    written = 0
    refreshed = 0
    protected = 0
    for info in skills:
        target = stub_path(info.name)
        if target.exists():
            if args.force:
                action = "force"
            elif _is_autogen(target):
                action = "refresh"
            else:
                protected += 1
                continue
        else:
            action = "new"
        target.write_text(render_stub(info), encoding="utf-8")
        if action == "refresh":
            refreshed += 1
        else:
            written += 1
        print(f"  {action:7s} {target.relative_to(TESTS_DIR.parent)}")

    print(
        f"[scaffold_tests] new={written} refreshed={refreshed} "
        f"protected-hand-edited={protected}"
    )
    if protected:
        print(f"[scaffold_tests] use --force to overwrite hand-edited files (not recommended)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
