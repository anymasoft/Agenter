"""Запуск полной индексации ChromaDB справки платформы 1С.

Запускать вручную в фоне, не через UI/ops — UI ставит timeout и не показывает
batch-логи которые нужны для отладки.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

# UTF-8 для логов
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Кэш модели — локально
os.environ.setdefault("HF_HOME", str(PROJECT_ROOT / "tools" / "models"))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(PROJECT_ROOT / "tools" / "models"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

from platform_docs_chroma import build_chroma_index  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("Полная индексация ChromaDB справки платформы 1С")
    print("=" * 60)
    t0 = time.time()
    result = build_chroma_index(
        reset=True,
        progress_callback=lambda c, t, eta: print(
            f"  PROGRESS {c:,}/{t:,}  ETA {eta/60:.1f}мин"
        ),
    )
    elapsed = time.time() - t0
    print("=" * 60)
    print(f"DONE in {elapsed/60:.1f} мин")
    print(f"  indexed: {result.get('indexed', 0):,}")
    print(f"  skipped: {result.get('skipped', 0)}")
    print(f"  size:    {result.get('chroma_size_mb', 0)} МБ")
    if result.get("failed_ids"):
        print(f"  failed IDs (first 20): {result['failed_ids']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
