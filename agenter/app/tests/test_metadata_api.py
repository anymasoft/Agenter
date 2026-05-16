"""Smoke-тест /metadata/* endpoints через FastAPI TestClient (без MCP)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

# Импортируем app БЕЗ полного lifespan (TestClient запустит свой)
# Lifespan делает MCP-handshake, который требует bsl-atlas — для теста API
# метаданных это не нужно. Создаём app вручную без lifespan.

# Заглушаем mcp_registry чтобы lifespan не падал, если bsl-atlas не доступен
import logging

logging.basicConfig(level=logging.WARNING)


def main() -> int:
    from fastapi.testclient import TestClient

    # Простой обход: импортируем main, но переопределим lifespan на no-op
    import main as agenter_main  # noqa: PLC0415

    # Подменяем lifespan на минимальный
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    original_app = agenter_main.app
    # Сохраним routes и подменим lifespan
    @asynccontextmanager
    async def noop_lifespan(_a: FastAPI):
        # минимум — заполнить state.client_cfg
        from _imports import load_config
        agenter_main.state.client_cfg = load_config()
        yield

    new_app = FastAPI(lifespan=noop_lifespan, title="Agenter Test")
    new_app.router.routes = original_app.router.routes  # переиспользуем все роуты

    with TestClient(new_app) as client:
        # 1. /metadata/tree slim
        print("[test] GET /metadata/tree?slim=true ...")
        t0 = time.time()
        r = client.get("/metadata/tree?slim=true", timeout=300.0)
        elapsed = time.time() - t0
        print(f"  status={r.status_code} time={elapsed:.2f}s size={len(r.content)/1024:.1f}KB")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tree" in data
        n_types = len(data["tree"].get("children", []))
        print(f"  types={n_types} cached={data.get('cached')}")
        assert n_types > 30, f"expected >30 types, got {n_types}"

        # 2. /metadata/tree повторно — должно быть из кэша
        print("\n[test] GET /metadata/tree (cached) ...")
        t1 = time.time()
        r2 = client.get("/metadata/tree?slim=true", timeout=10.0)
        elapsed2 = time.time() - t1
        print(f"  status={r2.status_code} time={elapsed2*1000:.0f}ms cached={r2.json().get('cached')}")
        assert r2.json().get("cached") is True

        # 3. /metadata/object для первого Catalog
        catalogs = next((c for c in data["tree"]["children"] if c["id"] == "type:Catalogs"), None)
        if catalogs and catalogs.get("children"):
            sample_key = catalogs["children"][0]["id"]
            print(f"\n[test] GET /metadata/object?key={sample_key} ...")
            t3 = time.time()
            r3 = client.get(f"/metadata/object?key={sample_key}", timeout=30.0)
            elapsed3 = time.time() - t3
            print(f"  status={r3.status_code} time={elapsed3*1000:.0f}ms size={len(r3.content)/1024:.1f}KB")
            assert r3.status_code == 200, r3.text
            obj_data = r3.json()
            print(f"  label={obj_data.get('label')}")
            print(f"  groups={[g.get('label') for g in obj_data.get('children', [])]}")

        # 4. /metadata/invalidate
        print("\n[test] POST /metadata/invalidate ...")
        r4 = client.post("/metadata/invalidate", timeout=5.0)
        print(f"  status={r4.status_code} body={r4.json()}")
        assert r4.status_code == 200

        print("\n[OK] all metadata API tests passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
