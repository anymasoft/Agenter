"""Замер throughput USER-bge-m3 на батчах разного размера.
Цель: понять реалистичное время полной индексации 25k записей."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "tools" / "models"
os.environ.setdefault("HF_HOME", str(MODELS_DIR))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODELS_DIR))

print("[load] loading model from cache (already downloaded)...")
t0 = time.time()
from sentence_transformers import SentenceTransformer  # noqa: E402
model = SentenceTransformer("deepvk/USER-bge-m3", device="cpu")
print(f"  loaded in {time.time()-t0:.1f}s")

# Прогрев — первый вызов всегда медленнее (PyTorch JIT, тензорный аллокатор)
print("\n[warmup] 1 query...")
t = time.time()
_ = model.encode(["прогрев"], show_progress_bar=False, convert_to_numpy=True)
print(f"  warmup: {(time.time()-t)*1000:.0f}ms")

# Реальный замер на разных batch размерах
sample_texts = [
    f"Документ ПродажаТоваровУслуг с параметром {i}. Это типичная фраза из справки 1С платформы "
    f"описывающая методы работы с реквизитами и табличными частями."
    for i in range(256)
]

for batch_size in [1, 8, 32, 64]:
    n = batch_size * 4  # 4 итерации каждый размер
    t = time.time()
    embs = model.encode(
        sample_texts[:n],
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    elapsed = time.time() - t
    per_doc_ms = (elapsed * 1000) / n
    docs_per_sec = n / elapsed
    eta_25k = 25000 / docs_per_sec
    print(
        f"  batch_size={batch_size:>3d}  n={n:>3d}  "
        f"total={elapsed:>5.1f}s  per_doc={per_doc_ms:>6.0f}ms  "
        f"throughput={docs_per_sec:>5.1f}/s  ETA(25k)={eta_25k/60:>5.1f}мин"
    )

print("\n[OK]")
