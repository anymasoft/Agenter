"""Smoke: новые MCP-серверы в config — registry строится корректно."""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from _imports import load_config  # noqa: E402
from mcp_registry import McpServerRegistry  # noqa: E402


def main() -> int:
    # 1. Config содержит ожидаемые серверы
    cfg = load_config()
    servers = cfg.get("mcp_servers", [])
    print(f"[config] mcp_servers count: {len(servers)}")
    names = [s.get("name") for s in servers]
    print(f"[config] names: {names}")

    assert "bsl-atlas" in names,    "bsl-atlas missing in config"
    assert "syntax-check" in names, "syntax-check missing in config"
    assert "help-platform" in names, "help-platform missing in config"
    assert "ssl-search" in names,   "ssl-search missing in config"

    # 2. Только включённые сервера попадают в registry
    registry = McpServerRegistry.from_config(cfg)
    enabled_in_cfg = [s["name"] for s in servers if s.get("enabled", True)]
    print(f"[registry] enabled in cfg:  {enabled_in_cfg}")
    print(f"[registry] active clients:  {registry.names()}")

    for name in enabled_in_cfg:
        assert name in registry.names(), f"enabled server not in registry: {name}"

    # 3. Disabled сервера НЕ должны быть в реестре
    disabled = [s["name"] for s in servers if not s.get("enabled", True)]
    print(f"[registry] disabled in cfg: {disabled}")
    for name in disabled:
        assert name not in registry.names(), f"disabled server should not be in registry: {name}"

    # 4. Симулируем orchestrator_sdk: строим mcp_servers dict
    fake_mcp = {"agenter": "<sdk_server>"}
    raw_servers = cfg.get("mcp_servers") or []
    for entry in raw_servers:
        if not entry.get("enabled", True):
            continue
        if entry.get("transport", "http") != "http":
            continue
        sdk_key = entry["name"].replace("-", "_")
        fake_mcp[sdk_key] = {"type": "http", "url": f"{entry['url'].rstrip('/')}/mcp"}

    print(f"\n[orchestrator] mcp_servers keys: {sorted(fake_mcp.keys())}")
    assert "bsl_atlas" in fake_mcp, "bsl_atlas missing in orchestrator dict"
    # Включён только bsl-atlas — остальные в config 'enabled': false
    assert "syntax_check" not in fake_mcp, "syntax_check should be disabled"
    assert "help_platform" not in fake_mcp, "help_platform should be disabled"
    assert "ssl_search" not in fake_mcp, "ssl_search should be disabled"

    print("\n[OK] all smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
