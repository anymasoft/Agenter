# Agenter test harness

Systematic coverage for 67 PowerShell skills + end-to-end agent
scenarios. Built 2026-05-16 in response to whack-a-mole bug discovery
in production runs.

## Why this exists

Agent quality is bounded by skill quality. We have 67 skills, each
with ~5 operations and dozens of `Write-Error`/`throw` edge cases.
Without systematic tests:

- Bugs surface only when a user runs a real task.
- One bug fixed → another lurks in a sibling operation.
- "Audit by reading code" misses what tests would catch trivially.

The harness gives us:

1. **Reality:** every test calls the actual PowerShell skill the
   exact way the agent's `ToolExecutor` calls it. No mocks.
2. **Inventory:** `tests/audit/skill_audit.py` enumerates declared
   operations and `throw` messages for every skill and reports
   what is tested vs missing.
3. **Regression locks:** every prod bug becomes a permanent test.
   `test_subsystem_edit.py::test_add_content_to_borrowed_subsystem_without_content`
   is the first such lock.

## Layout

```
tests/
├── README.md              (this file)
├── conftest.py            pytest fixtures (skills_dir, fixture_factory)
├── audit/
│   ├── skill_audit.py     coverage matrix generator
│   └── COVERAGE.md        auto-generated
├── harness/
│   └── skill_runner.py    run_skill() wrapper around powershell.exe
├── fixtures/              canonical ext_src/ states; one dir per scenario
│   └── borrowed_subsystem_no_content/
└── skills/                one test_<skill>.py per skill (eventually 67)
    └── test_subsystem_edit.py    exemplar
```

`tests/scenarios/` will hold end-to-end agent runs once skill-level
coverage is non-trivial. Skill tests come first.

## Setup (once)

```powershell
cd C:\BUFFER\ERP\agenter
.\backend\.venv\Scripts\python.exe -m pip install -r tests\requirements.txt
```

## Run

```powershell
# One-shot: audit + tests
.\run-tests.bat

# Just the audit (updates tests\audit\COVERAGE.md)
.\backend\.venv\Scripts\python.exe -m tests.audit.skill_audit

# Just the tests
.\backend\.venv\Scripts\python.exe -m pytest tests

# One file, verbose
.\backend\.venv\Scripts\python.exe -m pytest tests\skills\test_subsystem_edit.py -v
```

## Adding a test for a skill

1. Open `tests/audit/COVERAGE.md`. Pick a skill marked **MISSING**.
2. Create `tests/skills/test_<skill_with_underscores>.py`.
3. For each operation listed for that skill, write one happy-path
   test. Pattern:

   ```python
   def test_<op>(skills_dir, fixture_factory):
       ext_src = fixture_factory("<fixture_name>")
       result = run_skill(
           "<skill-name>",
           skills_dir,
           cwd=ext_src,
           # …named args mapped to PowerShell params
       )
       assert result.ok, result.combined
       # assertions on the resulting XML / files
   ```

4. For each edge case listed (every `throw` / `Write-Error` in the
   PS1), write a negative test that triggers it and verifies the
   message is reported clearly (not an unhandled exception).
5. Re-run the audit to refresh `COVERAGE.md`.

## Adding a fixture

A fixture is a canonical `ext_src/` state used as a starting point.

```
tests/fixtures/<name>/
├── README.md             explain what state this represents
├── Configuration.xml
├── Catalogs/...
└── ...
```

Use `fixture_factory("<name>")` in a test to get a fresh writable
copy in `tmp_path`. Never write to the source-of-truth fixture.

When a production incident surfaces a new shape we hadn't tested,
capture the relevant files into a new fixture, name it after the
scenario, and add a regression test.

## Conventions

- Test names spell out the scenario: `test_add_content_to_borrowed_subsystem_without_content`.
- Negative tests assert: skill exits non-zero **and** stderr/stdout
  contains a recognisable error message. Unhandled exceptions are
  treated as bugs in the skill, not in the test.
- Slow tests (real `db_load`, real 1C invocation) get `@pytest.mark.slow`.
- End-to-end agent runs (when added) get `@pytest.mark.requires_agent`.
