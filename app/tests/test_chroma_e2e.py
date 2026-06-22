"""End-to-end smoke: построить ChromaDB на 200 записях + сделать semantic-запросы."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

# Используем временную ChromaDB папку для теста — не трогаем реальную
TEMP_CHROMA = APP_DIR.parent / "data" / "platform_docs_chroma_test"

from platform_docs_chroma import (  # noqa: E402
    DOCS_DB_PATH,
    build_chroma_index,
    search_semantic,
    stats,
)


def main() -> int:
    if not DOCS_DB_PATH.exists():
        print(f"[skip] {DOCS_DB_PATH} не существует — нужно сначала "
              f"rebuild-platform-docs (SQLite)")
        return 0

    print(f"[build] индексация 200 записей в {TEMP_CHROMA}...")
    t0 = time.time()
    result = build_chroma_index(
        chroma_path=TEMP_CHROMA,
        limit=200,
        reset=True,
    )
    print(f"  {result['indexed']:,} записей за {time.time()-t0:.1f}s")
    print(f"  ChromaDB: {result['chroma_size_mb']} MB, dim={result['dim']}")

    print(f"\n[stats] текущий индекс:")
    s = stats(chroma_path=TEMP_CHROMA)
    print(f"  {s}")

    print(f"\n[search] семантические запросы (ожидаем topN >0):")
    queries = [
        "как заблокировать данные",
        "проведение документа",
        "работа со справочниками",
        "запросы к базе",
        "Lock",
    ]
    for q in queries:
        t = time.time()
        hits = search_semantic(q, limit=3, chroma_path=TEMP_CHROMA)
        elapsed = (time.time() - t) * 1000
        print(f"\n  [{elapsed:.0f}ms] {q!r}:")
        for h in hits[:3]:
            sim = h.get("similarity", 0)
            path = h.get("full_path_ru", "?")
            kind = h.get("kind", "?")
            print(f"    [{sim:.3f}] {path}  ({kind})")

    # Cleanup
    import shutil
    shutil.rmtree(TEMP_CHROMA, ignore_errors=True)
    print(f"\n[cleanup] removed {TEMP_CHROMA}")
    print("[OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
