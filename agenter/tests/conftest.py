"""Shared pytest fixtures and CLI options for Agenter tests.

Loaded automatically by pytest. Exposes:
    skills_dir       — Path to <project>/.claude/skills/
    fixture_factory  — callable(name) -> tmp Path with copy of tests/fixtures/<name>
    update_golden    — bool flag from --update-golden CLI option
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
AGENTER_ROOT = TESTS_DIR.parent
PROJECT_ROOT = AGENTER_ROOT.parent
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
FIXTURES_DIR = TESTS_DIR / "fixtures"


def pytest_addoption(parser):
    """Register custom CLI flags.

    --update-golden: regenerate all golden snapshot files instead of
                     comparing. Use after an intentional output change
                     and review the resulting `git diff`.
    """
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Update golden snapshot files instead of comparing.",
    )


@pytest.fixture
def update_golden(request) -> bool:
    """Boolean: was pytest invoked with --update-golden?"""
    return bool(request.config.getoption("--update-golden"))


@pytest.fixture
def skills_dir() -> Path:
    """Absolute path to .claude/skills (parent of agenter/).

    Tests that need to invoke a skill use this to locate the PS1.
    """
    if not SKILLS_DIR.exists():
        pytest.skip(f"Skills directory not found: {SKILLS_DIR}")
    return SKILLS_DIR


@pytest.fixture
def fixture_factory(tmp_path: Path):
    """Copy a canonical ext_src state into a tmp dir.

    Example:
        def test_foo(fixture_factory):
            ext_src = fixture_factory("borrowed_subsystem_no_content")
            # ext_src is a fresh writable copy under tmp_path

    Why tmp: tests must not mutate the source-of-truth fixture
    on disk. Each test gets an isolated copy.
    """
    def _copy(fixture_name: str) -> Path:
        src = FIXTURES_DIR / fixture_name
        if not src.exists():
            raise FileNotFoundError(
                f"Fixture not found: {src}\n"
                f"Available: {[p.name for p in FIXTURES_DIR.iterdir() if p.is_dir()]}"
            )
        dst = tmp_path / fixture_name
        shutil.copytree(src, dst)
        return dst
    return _copy
