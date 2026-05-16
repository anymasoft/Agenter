"""Invoke a PowerShell skill the same way the agent does.

This wrapper exists so tests exercise the exact code path the
production agent (Agenter ToolExecutor) takes. Any divergence
between test invocation and prod invocation is a bug.

Public API: run_skill()
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillResult:
    """Result of a single skill invocation.

    Attributes:
        skill: Skill name (e.g. "subsystem-edit")
        exit_code: Process exit code. 0 = success by PS convention.
        stdout, stderr: Captured streams (UTF-8, errors replaced).
    """
    skill: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def combined(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def run_skill(
    skill_name: str,
    skills_dir: Path,
    cwd: Path | None = None,
    *,
    timeout: int = 60,
    **named_args,
) -> SkillResult:
    """Invoke <skills_dir>/<skill_name>/scripts/<skill_name>.ps1.

    Args:
        skill_name: Hyphenated skill name, e.g. "subsystem-edit".
        skills_dir: Path to .claude/skills/.
        cwd: Working directory for the script. Many skills resolve
            relative paths against cwd, so set this to the test's
            ext_src root when needed.
        timeout: Seconds before subprocess.TimeoutExpired -> exit 124.
        **named_args: PowerShell -ParamName Value pairs.
            * Snake_case keys are converted to PascalCase:
              subsystem_path -> -SubsystemPath
            * Boolean True passes the flag bare: no_validate=True -> -NoValidate
            * Boolean False omits the flag entirely.
            * Everything else is str()-ified.

    Returns:
        SkillResult with exit_code, stdout, stderr.
    """
    script = skills_dir / skill_name / "scripts" / f"{skill_name}.ps1"
    if not script.exists():
        raise FileNotFoundError(f"Skill script not found: {script}")

    args = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
    ]
    for key, value in named_args.items():
        ps_name = "-" + _to_pascal_case(key)
        if isinstance(value, bool):
            if value:
                args.append(ps_name)
            # False -> omit
        else:
            args.extend([ps_name, str(value)])

    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return SkillResult(
            skill=skill_name,
            exit_code=124,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=f"TIMEOUT after {timeout}s",
        )

    return SkillResult(
        skill=skill_name,
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def _to_pascal_case(snake: str) -> str:
    """subsystem_path -> SubsystemPath, no_validate -> NoValidate."""
    parts = snake.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)
