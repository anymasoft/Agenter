"""Skill coverage audit.

For every directory under .claude/skills/ that has a SKILL.md and a
matching scripts/<name>.ps1, extract:
  - Operations declared in the SKILL.md "Операции"/"Operations" section
  - Edge cases: Write-Error and throw messages in the PS1
  - Whether tests/skills/test_<name_underscored>.py exists

Output:
  - Console: short summary
  - tests/audit/COVERAGE.md: full matrix (markdown table + per-skill details)

Usage:
  cd agenter
  .\\backend\\.venv\\Scripts\\python.exe -m tests.audit.skill_audit

This tool tells us what to test next. It is intentionally simple —
heuristic parsers, no AST. Re-run it whenever a skill or its docs change.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
AGENTER_ROOT = TESTS_DIR.parent
PROJECT_ROOT = AGENTER_ROOT.parent
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
SKILL_TESTS_DIR = TESTS_DIR / "skills"
OUTPUT = TESTS_DIR / "audit" / "COVERAGE.md"


@dataclass
class SkillInfo:
    name: str
    skill_md: Path
    ps1: Path | None  # back-compat: the PS1 entry point if any
    entry_script: Path | None = None
    entry_kind: str = "missing"  # "ps1" | "py" | "doc-only" | "missing"
    operations: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    has_test: bool = False
    test_file: Path | None = None


# Markdown row, op name in first column backticked: | `add-content` | ... |
OPERATIONS_TABLE_ROW = re.compile(r"^\|\s*`([a-z][a-z0-9-]+)`\s*\|", re.MULTILINE)
PS_WRITE_ERROR = re.compile(r'Write-Error\s+["\']([^"\']+)["\']')
PS_THROW = re.compile(r'\bthrow\s+["\']([^"\']+)["\']')


def collect_skills() -> list[SkillInfo]:
    skills: list[SkillInfo] = []
    if not SKILLS_DIR.exists():
        return skills
    for entry in sorted(SKILLS_DIR.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        ps1 = entry / "scripts" / f"{entry.name}.ps1"
        info = SkillInfo(
            name=entry.name,
            skill_md=skill_md,
            ps1=ps1 if ps1.exists() else None,
        )
        _classify_entry(info)
        _extract_operations(info)
        _extract_edge_cases(info)
        _check_test(info)
        skills.append(info)
    return skills


def _classify_entry(info: SkillInfo) -> None:
    """Determine the skill's executable entry point, if any.

    Priority:
        1. scripts/<name>.ps1               -> kind="ps1"
        2. any *.ps1 in scripts/            -> kind="ps1"
        3. scripts/<name>.py                -> kind="py"
        4. any *.py in scripts/ (no caches) -> kind="py"
        5. otherwise                        -> kind="doc-only"
    """
    scripts_dir = info.skill_md.parent / "scripts"
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        info.entry_kind = "doc-only"
        return

    named_ps1 = scripts_dir / f"{info.name}.ps1"
    if named_ps1.exists():
        info.entry_script = named_ps1
        info.entry_kind = "ps1"
        return
    other_ps1 = sorted(p for p in scripts_dir.glob("*.ps1") if p.is_file())
    if other_ps1:
        info.entry_script = other_ps1[0]
        info.entry_kind = "ps1"
        return

    named_py = scripts_dir / f"{info.name}.py"
    if named_py.exists():
        info.entry_script = named_py
        info.entry_kind = "py"
        return
    other_py = sorted(
        p for p in scripts_dir.glob("*.py")
        if p.is_file() and "__pycache__" not in p.parts
    )
    if other_py:
        info.entry_script = other_py[0]
        info.entry_kind = "py"
        return

    info.entry_kind = "doc-only"


def _extract_operations(info: SkillInfo) -> None:
    """Find the operations section in SKILL.md and capture all `op-name` rows.

    Heuristic: split on level-2 headings, look for a section whose title
    starts with "операции" or "operations" (case-insensitive). Within it,
    every markdown row with a backticked identifier in column 1 is an op.
    """
    text = info.skill_md.read_text(encoding="utf-8")
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    op_section = None
    for s in sections:
        head = s.split("\n", 1)[0].strip().lower()
        if head.startswith("операции") or head.startswith("operations"):
            op_section = s
            break
    if op_section is None:
        return
    for match in OPERATIONS_TABLE_ROW.finditer(op_section):
        op = match.group(1).strip()
        if op and op not in info.operations:
            info.operations.append(op)


def _extract_edge_cases(info: SkillInfo) -> None:
    """Pull Write-Error and throw messages out of the PS1 entry script.

    Each unique message is one potential edge case to test.
    The text is just the literal string — useful for grepping
    when a test fails with a matching message.

    Python-based skills are not parsed for edge cases yet; their
    error-handling style differs enough to warrant a separate parser.
    """
    if info.entry_kind != "ps1" or info.entry_script is None:
        return
    text = info.entry_script.read_text(encoding="utf-8", errors="replace")
    for match in PS_WRITE_ERROR.finditer(text):
        msg = match.group(1).strip()
        if msg and msg not in info.edge_cases:
            info.edge_cases.append(msg)
    for match in PS_THROW.finditer(text):
        msg = match.group(1).strip()
        if msg and msg not in info.edge_cases:
            info.edge_cases.append(msg)


def _check_test(info: SkillInfo) -> None:
    """Look for tests/skills/test_<name_underscored>.py."""
    test_name = "test_" + info.name.replace("-", "_") + ".py"
    candidate = SKILL_TESTS_DIR / test_name
    if candidate.exists():
        info.has_test = True
        info.test_file = candidate


def render_markdown(skills: list[SkillInfo]) -> str:
    total = len(skills)
    with_tests = sum(1 for s in skills if s.has_test)
    total_ops = sum(len(s.operations) for s in skills)
    total_edges = sum(len(s.edge_cases) for s in skills)
    pct = with_tests * 100 // max(total, 1)
    kinds = {"ps1": 0, "py": 0, "doc-only": 0, "missing": 0}
    for s in skills:
        kinds[s.entry_kind] = kinds.get(s.entry_kind, 0) + 1

    lines: list[str] = []
    lines.append("# Skill Coverage Matrix")
    lines.append("")
    lines.append("**Auto-generated** by `tests/audit/skill_audit.py`. Do not hand-edit — re-run the audit.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total skills with SKILL.md: **{total}**")
    lines.append(f"- Entry kinds: **{kinds['ps1']}** PowerShell, **{kinds['py']}** Python, **{kinds['doc-only']}** doc-only")
    lines.append(f"- Skills with at least one test file: **{with_tests}** ({pct}%)")
    lines.append(f"- Declared operations across all SKILL.md: **{total_ops}**")
    lines.append(f"- Edge cases (Write-Error/throw) in PS1: **{total_edges}**")
    lines.append("")
    lines.append("## Coverage table")
    lines.append("")
    lines.append("| Skill | Entry | Ops | Edge cases | Test |")
    lines.append("|---|---|---:|---:|---|")
    for s in skills:
        marker = f"`{s.test_file.name}`" if s.has_test and s.test_file else "**MISSING**"
        if s.entry_script is not None:
            entry_cell = f"{s.entry_kind} (`{s.entry_script.name}`)"
        else:
            entry_cell = s.entry_kind
        lines.append(f"| `{s.name}` | {entry_cell} | {len(s.operations)} | {len(s.edge_cases)} | {marker} |")
    lines.append("")
    lines.append("## Per-skill details")
    lines.append("")
    for s in skills:
        lines.append(f"### `{s.name}`")
        lines.append("")
        if s.operations:
            lines.append("**Declared operations** (from SKILL.md):")
            for op in s.operations:
                lines.append(f"- `{op}`")
        else:
            lines.append("_No operations table found in SKILL.md._")
        lines.append("")
        if s.edge_cases:
            lines.append("**Edge cases** (Write-Error/throw in PS1):")
            for ec in s.edge_cases:
                lines.append(f"- {ec}")
        else:
            lines.append("_No error patterns extracted from PS1._")
        lines.append("")
        if s.has_test and s.test_file:
            rel = s.test_file.relative_to(AGENTER_ROOT)
            lines.append(f"**Test file:** `{rel}`")
        else:
            expected = "test_" + s.name.replace("-", "_") + ".py"
            lines.append(f"**Test file:** missing — add `tests/skills/{expected}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    skills = collect_skills()
    if not skills:
        print(f"[ERROR] No skills found in {SKILLS_DIR}", file=sys.stderr)
        return 1
    md = render_markdown(skills)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(md, encoding="utf-8")
    total = len(skills)
    with_tests = sum(1 for s in skills if s.has_test)
    total_ops = sum(len(s.operations) for s in skills)
    total_edges = sum(len(s.edge_cases) for s in skills)
    pct = with_tests * 100 // total
    print(f"[skill_audit] {total} skills, {with_tests} with tests ({pct}%)")
    print(f"[skill_audit] {total_ops} declared ops, {total_edges} edge cases")
    print(f"[skill_audit] Report: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
