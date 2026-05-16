"""
Загружает символы из backend/main.py и desktop/main.py под уникальными
именами в sys.modules, чтобы избежать коллизии (все три main.py одноимённые).

Использование:
    from _imports import SYSTEM_PROMPT, TOOL_DEFINITIONS, ToolExecutor, ...
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AGENTER_ROOT = Path(__file__).parent.parent


def _load_module(unique_name: str, path: Path):
    """Загружает модуль из конкретного файла под заданным именем в sys.modules."""
    if unique_name in sys.modules:
        return sys.modules[unique_name]
    spec = importlib.util.spec_from_file_location(unique_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось создать spec для {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Загрузка обоих исходников под уникальными именами ──────────────────────
_backend_path = _AGENTER_ROOT / "backend" / "main.py"
_desktop_path = _AGENTER_ROOT / "desktop" / "main.py"

if not _backend_path.exists():
    raise FileNotFoundError(f"Не найден {_backend_path}")
if not _desktop_path.exists():
    raise FileNotFoundError(f"Не найден {_desktop_path}")

_backend = _load_module("agenter_backend_main", _backend_path)
_desktop = _load_module("agenter_desktop_main", _desktop_path)


# ── Реэкспорт нужного из backend ───────────────────────────────────────────
SYSTEM_PROMPT        = _backend.SYSTEM_PROMPT
TOOL_DEFINITIONS     = _backend.TOOL_DEFINITIONS
_build_system_prompt = _backend._build_system_prompt
MAX_ITERATIONS        = _backend.MAX_ITERATIONS
MAX_TOOL_RESULT       = _backend.MAX_TOOL_RESULT
CRITICAL_TOOLS        = _backend.CRITICAL_TOOLS
LOOP_DETECT_WINDOW    = _backend.LOOP_DETECT_WINDOW
MAX_ASK_USER_PER_TASK = _backend.MAX_ASK_USER_PER_TASK
SDK_HARD_CAP_TURNS    = _backend.SDK_HARD_CAP_TURNS


# ── Реэкспорт нужного из desktop ───────────────────────────────────────────
ToolExecutor   = _desktop.ToolExecutor
BslAtlasClient = _desktop.BslAtlasClient
load_config    = _desktop.load_config
_ConfigError   = _desktop._ConfigError
run_powershell = _desktop.run_powershell


__all__ = [
    "SYSTEM_PROMPT", "TOOL_DEFINITIONS", "_build_system_prompt",
    "MAX_ITERATIONS", "MAX_TOOL_RESULT", "CRITICAL_TOOLS",
    "LOOP_DETECT_WINDOW",
    "MAX_ASK_USER_PER_TASK", "SDK_HARD_CAP_TURNS",
    "ToolExecutor", "BslAtlasClient", "load_config", "_ConfigError",
    "run_powershell",
]
