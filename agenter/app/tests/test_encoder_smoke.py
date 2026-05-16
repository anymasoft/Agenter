"""Smoke-тест: загрузка модели deepvk/USER-bge-m3 + encode тестовых фраз."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Установим явный путь к локальному кэшу моделей чтобы они лежали внутри проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "tools" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(MODELS_DIR))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODELS_DIR))

print(f"[init] models cache: {MODELS_DIR}")

t0 = time.time()
print("[1] importing sentence_transformers...")
from sentence_transformers import SentenceTransformer  # noqa: E402
print(f"      imported in {time.time()-t0:.2f}s")

MODEL_NAME = "deepvk/USER-bge-m3"
t1 = time.time()
print(f"\n[2] loading {MODEL_NAME} (первый раз качает 1.37 GB)...")
model = SentenceTransformer(MODEL_NAME, device="cpu")
print(f"      loaded in {time.time()-t1:.1f}s")

# Параметры модели
print(f"\n[3] model info:")
print(f"      max_seq_length:    {model.max_seq_length}")
print(f"      embedding_dim:     {model.get_sentence_embedding_dimension()}")

# Encode пробных фраз про 1С
queries = [
    "как заблокировать данные",
    "поиск по справочнику",
    "проведение документа",
    "БлокировкаДанных",
]
print(f"\n[4] encoding {len(queries)} queries...")
t2 = time.time()
embeddings = model.encode(queries, convert_to_numpy=True, show_progress_bar=False)
elapsed = time.time() - t2
print(f"      shape: {embeddings.shape}")
print(f"      took:  {elapsed*1000:.0f}ms ({elapsed*1000/len(queries):.0f}ms/query)")

# Cosine similarity между запросами — для sanity check
import numpy as np  # noqa: E402

def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

print(f"\n[5] cosine similarity matrix:")
for i, q in enumerate(queries):
    sims = [f"{cos(embeddings[i], embeddings[j]):.3f}" for j in range(len(queries))]
    print(f"      {q[:30]:30s} | {' '.join(sims)}")

# Базовая проверка: запросы про блокировку должны быть похожи
sim_lock = cos(embeddings[0], embeddings[3])  # "как заблокировать" ↔ "БлокировкаДанных"
sim_random = cos(embeddings[0], embeddings[2])  # "как заблокировать" ↔ "проведение документа"
print(f"\n[6] semantic sanity:")
print(f"      'как заблокировать' ↔ 'БлокировкаДанных': {sim_lock:.3f}  (ожидаем > 0.5)")
print(f"      'как заблокировать' ↔ 'проведение документа': {sim_random:.3f}  (ожидаем < 0.7)")
assert sim_lock > 0.5, "семантическое сходство ниже ожидаемого"
assert sim_lock > sim_random, "блокировка должна быть ближе к блокировке, чем к проведению"

print(f"\n[OK] всё прошло за {time.time()-t0:.1f}s")
