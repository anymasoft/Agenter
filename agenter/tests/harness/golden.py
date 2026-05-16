"""Golden-file (snapshot) regression testing.

Industrial pattern: instead of writing assertions for every byte of
expected output, run the code once, capture the output, save it, then
on every future run compare actual against saved. Reviewer reads the
diff to decide if the change was intentional.

Why it scales:
    Writing assertions for XML structure is fragile (whitespace,
    namespaces, attribute order). Golden files capture the exact
    expected output, character-for-character. A test author only
    has to validate the output once visually, then commits it.

Workflow:
    1. Test runs `assert_golden("x", actual)`.
    2. If `golden/x.txt` is missing, the test fails with a clear
       message telling you to run with `--update-golden`.
    3. Run pytest with `--update-golden` — golden file is written.
    4. Inspect `git diff` manually to confirm the output is correct.
    5. Commit. Future runs verify nothing drifts.

To regenerate all golden files after an intentional change:
    pytest tests --update-golden
"""
from __future__ import annotations

import difflib
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"


def assert_golden(
    name: str,
    actual: str,
    *,
    update: bool,
    suffix: str = ".txt",
) -> None:
    """Compare `actual` against `tests/golden/<name><suffix>`.

    Args:
        name: Stable identifier for this snapshot. Convention:
              `<skill>_<scenario>` e.g. `subsystem_edit_add_content_to_borrowed`.
        actual: The actual output to compare.
        update: If True, overwrite the golden file with `actual`.
                Pass the value of `request.config.getoption("--update-golden")`.
        suffix: File extension. Use `.xml` for XML if you want syntax
                highlighting in your editor; the comparison is plain text.
    """
    golden_path = GOLDEN_DIR / f"{name}{suffix}"

    if update:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return

    if not golden_path.exists():
        pytest.fail(
            f"Golden file missing: {golden_path}\n"
            f"Run with --update-golden to create it, then `git diff` to verify."
        )

    expected = golden_path.read_text(encoding="utf-8")
    if actual == expected:
        return

    diff_lines = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=f"golden/{name}{suffix}",
        tofile="actual",
        lineterm="",
        n=3,
    )
    diff = "\n".join(diff_lines)
    pytest.fail(
        f"Golden mismatch for `{name}`.\n"
        f"If the change is intentional, run with --update-golden.\n\n"
        f"{diff}"
    )
