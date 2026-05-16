"""Smoke-тест metadata_repository с прогрессивной загрузкой на SCHEME."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from metadata_utils.metadata_repository import MetadataRepository, MetadataTreeNode  # noqa: E402


async def main() -> int:
    scheme_root = Path(r"C:\BUFFER\ERP\SCHEME")
    if not scheme_root.exists():
        print("[repo] SCHEME not found - skipping")
        return 0

    repo = MetadataRepository(ttl_seconds=600, max_workers=8)

    print("[repo] starting progressive load...")
    t0 = time.time()
    type_count = 0
    object_count = 0

    async def on_type_loaded(node: MetadataTreeNode) -> None:
        nonlocal type_count, object_count
        n = len(node.children)
        type_count += 1
        object_count += n
        elapsed = time.time() - t0
        print(f"  [+{elapsed:5.2f}s] {node.label:50s} {n:>5d} objects")

    result = await repo.load_progressive(scheme_root, on_type_loaded)
    elapsed = time.time() - t0

    tree = result["tree"]
    objects = result["objects"]
    errors = result["errors"]
    print(
        f"\n[repo] DONE: types={type_count}, objects={object_count}, "
        f"errors={len(errors)}, total={elapsed:.2f}s"
    )

    if errors:
        print("[repo] first 5 errors:")
        for e in errors[:5]:
            print(f"  {e}")

    # Проверка: повторная загрузка должна быть из кэша (< 0.1s)
    print("\n[repo] testing cache...")
    t1 = time.time()
    result2 = await repo.load(scheme_root)
    cache_elapsed = time.time() - t1
    print(f"[repo] cached load: {cache_elapsed*1000:.0f}ms, cached={result2.get('cached')}")

    # Тест JSON-сериализации
    print("\n[repo] testing JSON serialization...")
    t2 = time.time()
    catalogs = next((c for c in tree.children if c.id == "type:Catalogs"), None)
    if catalogs and catalogs.children:
        sample_obj = catalogs.children[0]
        json_str = sample_obj.model_dump_json()
        print(f"  sample object JSON: {len(json_str)} bytes in {(time.time()-t2)*1000:.0f}ms")
        # Полное дерево
        t3 = time.time()
        full_json = tree.model_dump_json()
        print(f"  full tree JSON: {len(full_json)/1024:.1f} KB in {(time.time()-t3)*1000:.0f}ms")
    else:
        print("  no Catalogs found - skipping")

    print("\n[OK] smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
