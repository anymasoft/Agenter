"""
ChromaDB-индекс справки платформы 1С (semantic-поиск).

Парный модуль к platform_docs.py — берёт уже распарсенную SQLite БД и
строит над теми же ~25k записями векторный индекс через
sentence-transformers (модель deepvk/USER-bge-m3 — SOTA для русского RAG).

Тулзы для LLM:
    platform_doc_lookup(name)   — точный поиск по имени (FTS5, SQLite) ─┐
    platform_doc_search(query)  — семантический поиск (ChromaDB) ←─────┘ оба читают одну и ту же базу

Параметры модели через ENV (или дефолты):
    SEMANTIC_MODEL — имя HF-модели (по умолчанию deepvk/USER-bge-m3)
    SEMANTIC_DEVICE — cpu | cuda (по умолчанию cpu)

Файлы:
    agenter/data/platform_docs.db          ─ существующая SQLite (источник)
    agenter/data/platform_docs_chroma/     ─ ChromaDB persistent (создаётся)
    agenter/tools/models/                  ─ кэш модели HuggingFace

Использование:
    from platform_docs_chroma import build_chroma_index, search_semantic
    build_chroma_index()                                 # один раз
    hits = search_semantic("как заблокировать данные")   # на каждый запрос
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)

# ── Пути и константы ─────────────────────────────────────────────────────────

_APP_DIR = Path(__file__).resolve().parent
_DATA_DIR = _APP_DIR.parent / "data"
_TOOLS_DIR = _APP_DIR.parent / "tools"

DOCS_DB_PATH = _DATA_DIR / "platform_docs.db"
CHROMA_DIR = _DATA_DIR / "platform_docs_chroma"
MODELS_DIR = _TOOLS_DIR / "models"

def _detect_device() -> str:
    """Возвращает оптимальное устройство для embedding-модели.

    Приоритет: CUDA → MPS (Mac Apple Silicon) → CPU.
    Если pytorch собран без CUDA — fallback на CPU автоматически.
    """
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except (ImportError, Exception):  # noqa: BLE001
        pass
    return "cpu"


# Модель — настраивается через ENV для гибкости (например в тестах)
DEFAULT_MODEL = os.environ.get("SEMANTIC_MODEL", "deepvk/USER-bge-m3")
# Устройство: SEMANTIC_DEVICE → cuda/cpu/mps; если не задано — авто-детект
DEFAULT_DEVICE = os.environ.get("SEMANTIC_DEVICE") or _detect_device()

# Имя коллекции в ChromaDB
COLLECTION_NAME = "platform_docs"

# Размер батча для encoder.encode() — баланс память/скорость.
# Для USER-bge-m3 (1.37 ГБ) на RTX 3050 Laptop (4 ГБ VRAM) больше 8 → 94% VRAM
# и активный CPU swap. На GPU с 8+ ГБ VRAM можно поднять до 32-64.
BATCH_SIZE = 8

# Размер батча для добавления в ChromaDB (она не любит огромные транзакции).
# 200 — оптимально для платформы с 16 ГБ RAM: HNSW не разрастается между flush,
# поэтому RAM не уходит в своп.
CHROMA_INSERT_BATCH = 200


# ── Lazy loaders для тяжёлых зависимостей ────────────────────────────────────

_model_cache: dict[str, Any] = {}
_chroma_client_cache: dict[str, Any] = {}


def _get_model(name: str = DEFAULT_MODEL, device: str = DEFAULT_DEVICE):
    """Lazy-инициализация sentence-transformer модели.
    Кэшируется в процессе — повторные вызовы получают тот же объект."""
    key = f"{name}/{device}"
    if key in _model_cache:
        return _model_cache[key]

    # Локальный кэш моделей HF — внутри проекта, не в %USERPROFILE%
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(MODELS_DIR))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODELS_DIR))

    from sentence_transformers import SentenceTransformer  # local import — heavy
    log.info("Loading embedding model: %s (device=%s)", name, device)
    t0 = time.time()
    model = SentenceTransformer(name, device=device)
    log.info("Model loaded in %.1fs (dim=%d, max_seq=%d)",
             time.time() - t0,
             model.get_sentence_embedding_dimension(),
             model.max_seq_length)
    _model_cache[key] = model
    return model


def _get_chroma_client(path: Path = CHROMA_DIR):
    """Lazy-инициализация persistent ChromaDB клиента."""
    key = str(path)
    if key in _chroma_client_cache:
        return _chroma_client_cache[key]
    import chromadb  # local import
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    _chroma_client_cache[key] = client
    return client


# ── File-lock против параллельных запусков индексации ────────────────────────


def _is_pid_alive(pid: int) -> bool:
    """Проверяет жив ли процесс. Windows-совместимо."""
    import sys
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not h:
            return False
        # Проверяем что процесс не завершён
        exit_code = ctypes.c_ulong(0)
        success = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        STILL_ACTIVE = 259
        return bool(success) and exit_code.value == STILL_ACTIVE
    else:
        import os as _os
        try:
            _os.kill(pid, 0)
            return True
        except OSError:
            return False


def _acquire_lock(chroma_path: Path) -> tuple[Path, bool]:
    """Захватывает advisory file-lock на путь ChromaDB.

    Returns (lock_path, acquired).
        acquired=True — мы захватили lock, можно работать
        acquired=False — уже занято живым процессом, нужно ждать или отказаться

    Stale lock (процесс умер) автоматически снимается.
    """
    import os as _os
    lock_path = chroma_path.parent / f"{chroma_path.name}.lock"
    chroma_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            content = lock_path.read_text(encoding="utf-8").strip()
            pid_str, _, _ = content.partition("|")
            pid = int(pid_str)
            if _is_pid_alive(pid):
                log.warning(
                    "ChromaDB lock held by alive PID %d — пропускаю запуск", pid
                )
                return lock_path, False
            log.info("Stale lock from dead PID %d — снимаю", pid)
            lock_path.unlink(missing_ok=True)
        except Exception as e:
            log.warning("Битый lock-файл (%s) — снимаю", e)
            lock_path.unlink(missing_ok=True)

    try:
        lock_path.write_text(
            f"{_os.getpid()}|{time.time()}",
            encoding="utf-8",
        )
        return lock_path, True
    except OSError as e:
        log.error("Не удалось создать lock: %s", e)
        return lock_path, False


def _release_lock(lock_path: Path) -> None:
    """Снимает file-lock. Без падения если файла уже нет."""
    try:
        lock_path.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Не удалось снять lock %s: %s", lock_path, e)


# ── Подготовка текста для embedding ──────────────────────────────────────────


def _format_doc_for_embedding(row: sqlite3.Row) -> str:
    """Преобразует одну запись справки в текст для embedding.

    Кладём всю полезную информацию: имя, путь, тип, описание, сигнатура,
    параметры, возвращаемое значение. Модель USER-bge-m3 имеет контекст
    8192 токенов — этого с запасом хватает на самые длинные записи.
    """
    parts: list[str] = []

    # Заголовок: полный путь (русский) + тип
    full_path = (row["full_path_ru"] or row["name_ru"] or "").strip()
    kind = (row["kind"] or "").strip()
    if full_path:
        parts.append(f"{full_path} ({kind})" if kind else full_path)

    # Английский путь — для запросов на латинице (Lock vs Блокировка)
    if row["full_path_en"] and row["full_path_en"] != row["full_path_ru"]:
        parts.append(f"EN: {row['full_path_en']}")

    # Описание (главное)
    if row["description"]:
        parts.append(row["description"].strip())

    # Сигнатура — для методов/функций
    if row["signature"]:
        parts.append(f"Сигнатура: {row['signature'].strip()}")

    # Параметры
    if row["params"]:
        parts.append(f"Параметры: {row['params'].strip()}")

    # Возвращаемое значение
    if row["returns"]:
        parts.append(f"Возвращает: {row['returns'].strip()}")

    return "\n".join(parts)


def _iter_docs(sqlite_path: Path) -> Iterator[tuple[int, str, dict]]:
    """Итерирует по всем записям SQLite БД.
    Возвращает (id, text_for_embedding, metadata)."""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM docs ORDER BY id")
        for row in cur:
            text = _format_doc_for_embedding(row)
            if not text.strip():
                continue
            metadata = {
                "name_ru":      row["name_ru"] or "",
                "name_en":      row["name_en"] or "",
                "full_path_ru": row["full_path_ru"] or "",
                "kind":         row["kind"] or "",
                "rel_path":     row["rel_path"] or "",
            }
            yield row["id"], text, metadata
    finally:
        conn.close()


# ── Построение индекса ───────────────────────────────────────────────────────


def build_chroma_index(
    *,
    sqlite_path: Path | str = DOCS_DB_PATH,
    chroma_path: Path | str = CHROMA_DIR,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    reset: bool = True,
    limit: Optional[int] = None,
    progress_callback: Optional[callable] = None,
) -> dict:
    """Строит ChromaDB-индекс на основе существующей SQLite БД.

    Args:
        sqlite_path: путь к platform_docs.db
        chroma_path: куда положить ChromaDB файлы
        model_name: имя HF-модели для embedding
        device: 'cpu' или 'cuda'
        reset: если True — удаляет старую коллекцию перед построением
        progress_callback: f(current, total, eta_sec) для UI

    Returns:
        Статистика {indexed, model, dim, elapsed_sec, chroma_size_mb}.
    """
    sqlite_path = Path(sqlite_path)
    chroma_path = Path(chroma_path)

    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"SQLite БД не найдена: {sqlite_path}\n"
            "Сначала запусти ops/rebuild-platform-docs чтобы построить SQLite."
        )

    # File-lock против параллельных запусков. Если уже работает другой процесс
    # (UI-кнопка + фоновый скрипт одновременно) — отказываемся вместо коллизии.
    lock_path, acquired = _acquire_lock(chroma_path)
    if not acquired:
        raise RuntimeError(
            f"Индексация ChromaDB уже выполняется в другом процессе "
            f"(lock: {lock_path}). Дождись её завершения или удали lock-файл "
            f"если процесс точно завершён."
        )

    try:  # noqa: E501  — главный try для file-lock, finally в конце функции
        model = _get_model(model_name, device)
        client = _get_chroma_client(chroma_path)

        # Получаем или создаём коллекцию
        if reset:
            try:
                client.delete_collection(COLLECTION_NAME)
                log.info("Deleted existing collection %s", COLLECTION_NAME)
            except Exception:
                pass

        # hnsw:space=cosine — ChromaDB будет считать cosine distance, а не L2.
        # Это критично: у нас normalize_embeddings=True, и cosine — единственная
        # метрика которая даёт интерпретируемый similarity в [0..1].
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "model": model_name,
                "dim": model.get_sentence_embedding_dimension(),
            },
        )

        # Считаем общее количество для прогресса
        conn = sqlite3.connect(sqlite_path)
        total = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        conn.close()
        if limit is not None and limit > 0:
            total = min(total, limit)
        log.info("Indexing %d records from %s (limit=%s)", total, sqlite_path, limit)

        # Накопители для батчей
        batch_ids: list[str] = []
        batch_texts: list[str] = []
        batch_metas: list[dict] = []
        inserted = 0
        t_start = time.time()

        failed_ids: list[str] = []  # записи которые не удалось закодировать/вставить

        def _flush():
            """Кодирует и вставляет накопленный батч. Если упадёт целиком —
            пробует поштучно, чтобы пропустить одну плохую запись."""
            nonlocal inserted
            if not batch_ids:
                return
            batch_n = len(batch_ids)
            t_batch = time.time()
            try:
                embeddings = model.encode(
                    batch_texts,
                    batch_size=BATCH_SIZE,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                collection.add(
                    ids=list(batch_ids),
                    embeddings=embeddings.tolist(),
                    documents=list(batch_texts),
                    metadatas=list(batch_metas),
                )
                inserted += batch_n
                log.info(
                    "batch OK: +%d (total=%d/%d) in %.1fs",
                    batch_n, inserted, total, time.time() - t_batch,
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "batch %d failed (%s), retrying one-by-one: %s",
                    batch_n, type(e).__name__, e,
                )
                # Пробуем поштучно — пропускаем только реально плохие записи
                for i in range(batch_n):
                    try:
                        emb = model.encode(
                            [batch_texts[i]],
                            convert_to_numpy=True,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                        )
                        collection.add(
                            ids=[batch_ids[i]],
                            embeddings=emb.tolist(),
                            documents=[batch_texts[i]],
                            metadatas=[batch_metas[i]],
                        )
                        inserted += 1
                    except Exception as ee:  # noqa: BLE001
                        failed_ids.append(batch_ids[i])
                        log.error(
                            "skip doc id=%s (len=%d): %s",
                            batch_ids[i], len(batch_texts[i]), ee,
                        )
            finally:
                batch_ids.clear()
                batch_texts.clear()
                batch_metas.clear()
                # Освобождаем GPU VRAM и RAM после каждого батча — иначе при
                # больших корпусах (>20k записей) Windows начинает свопить,
                # скорость падает с ~30 doc/sec до 0 (см. ADR-010).
                try:
                    import gc as _gc  # noqa: PLC0415
                    _gc.collect()
                    import torch as _torch  # noqa: PLC0415
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except Exception:
                    pass

            if progress_callback:
                elapsed = time.time() - t_start
                eta = (elapsed / inserted) * (total - inserted) if inserted else 0
                progress_callback(inserted, total, eta)

        for doc_id, text, metadata in _iter_docs(sqlite_path):
            if limit is not None and inserted + len(batch_ids) >= limit:
                break
            batch_ids.append(str(doc_id))
            batch_texts.append(text)
            batch_metas.append(metadata)
            if len(batch_ids) >= CHROMA_INSERT_BATCH:
                _flush()
        _flush()

        elapsed = time.time() - t_start

        # Размер ChromaDB на диске
        chroma_size_bytes = sum(
            f.stat().st_size for f in chroma_path.rglob("*") if f.is_file()
        )
        chroma_size_mb = round(chroma_size_bytes / 1024 / 1024, 1)

        result = {
            "indexed":         inserted,
            "skipped":         len(failed_ids),
            "failed_ids":      failed_ids[:20],  # первые 20 для отладки
            "model":           model_name,
            "dim":             model.get_sentence_embedding_dimension(),
            "elapsed_sec":     round(elapsed, 1),
            "chroma_size_mb":  chroma_size_mb,
            "chroma_path":     str(chroma_path),
        }
        log.info("ChromaDB index built: %s", result)
        return result

    finally:
        _release_lock(lock_path)


# ── Семантический поиск ──────────────────────────────────────────────────────


def search_semantic(
    query: str,
    *,
    limit: int = 5,
    chroma_path: Path | str = CHROMA_DIR,
    model_name: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """Семантический поиск в ChromaDB-индексе платформенной справки.

    Args:
        query: фраза/вопрос на любом языке (RU/EN)
        limit: сколько результатов вернуть
        kind_filter: фильтр по типу (method, property, event, object, ...) или None

    Returns:
        Список словарей {full_path_ru, name_ru, kind, description (короткое),
        similarity (0..1), rel_path}, отсортированный по убыванию similarity.
    """
    chroma_path = Path(chroma_path)
    if not chroma_path.exists():
        return [{"_error": f"ChromaDB-индекс не построен: {chroma_path}. "
                           "Запусти build_chroma_index()."}]

    model = _get_model(model_name, device)
    client = _get_chroma_client(chroma_path)
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as e:
        return [{"_error": f"Коллекция {COLLECTION_NAME!r} не найдена: {e}"}]

    # Кодируем запрос
    query_emb = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )[0].tolist()

    where: Optional[dict] = None
    if kind_filter:
        if len(kind_filter) == 1:
            where = {"kind": kind_filter[0]}
        else:
            where = {"kind": {"$in": kind_filter}}

    res = collection.query(
        query_embeddings=[query_emb],
        n_results=limit,
        where=where,
    )

    # ChromaDB возвращает списки списков (на batch запросов). У нас всегда 1 запрос.
    ids = res.get("ids", [[]])[0]
    distances = res.get("distances", [[]])[0]
    metadatas = res.get("metadatas", [[]])[0]
    documents = res.get("documents", [[]])[0]

    results: list[dict] = []
    for i in range(len(ids)):
        # Коллекция создана с hnsw:space=cosine → distances[i] = cosine distance ∈ [0, 2]
        # cosine_similarity = 1 - cosine_distance ∈ [-1, 1]; для normalized embeddings ∈ [0, 1]
        dist = distances[i]
        similarity = max(0.0, min(1.0, 1.0 - dist))
        meta = metadatas[i] or {}
        results.append({
            "full_path_ru": meta.get("full_path_ru", ""),
            "name_ru":      meta.get("name_ru", ""),
            "name_en":      meta.get("name_en", ""),
            "kind":         meta.get("kind", ""),
            "rel_path":     meta.get("rel_path", ""),
            "similarity":   round(similarity, 4),
            # Документ обрежем чтобы не возвращать гигантский текст в каждом hit
            "snippet":      _truncate(documents[i] if i < len(documents) else "", 300),
        })
    return results


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"


# ── Stats / health ───────────────────────────────────────────────────────────


def stats(chroma_path: Path | str = CHROMA_DIR) -> dict:
    """Возвращает статистику ChromaDB-индекса для UI/health."""
    chroma_path = Path(chroma_path)
    if not chroma_path.exists():
        return {"exists": False}

    try:
        client = _get_chroma_client(chroma_path)
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
    except Exception as e:
        return {"exists": False, "error": str(e)}

    size_bytes = sum(f.stat().st_size for f in chroma_path.rglob("*") if f.is_file())
    return {
        "exists":         True,
        "indexed":        count,
        "chroma_size_mb": round(size_bytes / 1024 / 1024, 1),
        "chroma_path":    str(chroma_path),
    }


# ── CLI для отладки ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        print("Building ChromaDB index...")
        result = build_chroma_index(progress_callback=lambda c, t, eta:
                                    print(f"  {c}/{t}  ETA {eta:.0f}s"))
        print(result)
    elif len(sys.argv) >= 2 and sys.argv[1] == "search":
        query = " ".join(sys.argv[2:]) or "как заблокировать данные"
        print(f"Searching: {query!r}")
        hits = search_semantic(query, limit=5)
        for h in hits:
            print(f"  [{h.get('similarity', '?'):.3f}] {h.get('full_path_ru', '?')} ({h.get('kind', '?')})")
            print(f"           {h.get('snippet', '')[:120]}")
    else:
        print(__doc__)
        print(stats())
