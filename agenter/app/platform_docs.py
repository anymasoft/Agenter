"""
agenter/app/platform_docs.py — индекс платформенной справки 1С.

Источник: shcntx_ru.hbk из установки 1С (~39 MB сжато, 71 MB разжато,
52000+ HTML файлов). Содержит официальное описание ВСЕХ платформенных
методов, свойств, объектов, глобального контекста.

Pipeline:
  1. ContainerReader (onec_dtools) распаковывает .hbk → FileStorage (ZIP)
  2. ZIP содержит objects/.../*.html — каждая страница = один method/property/object
  3. Парсим HTML, извлекаем структурированные поля (имя ru/en, sig, описание, пример)
  4. Кладём в SQLite + FTS5-индекс по имени и описанию

Tool в Agenter: platform_doc_lookup(name) — возвращает строгое описание
из официальной документации. Используется LLM перед написанием BSL-кода
с любым платформенным методом.

Бандлится с Agenter (БД ~5-15 MB), пересобирается опционально через UI-кнопку.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import zipfile
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


# ── Пути ────────────────────────────────────────────────────────────────────

_APP_DIR = Path(__file__).parent.resolve()
_DATA_DIR = _APP_DIR.parent / "data"
DOCS_DB_PATH = _DATA_DIR / "platform_docs.db"


# ── Парсер HTML страниц шинтакс-помощника 1С ────────────────────────────────


# H1 содержит: "Полное.Имя.МетодRu (Full.Name.MethodEn)"
_H1_RE = re.compile(
    r'<h1\s+class="V8SH_pagetitle"[^>]*>([^<]+)</h1>',
    re.IGNORECASE | re.DOTALL,
)
_PAGE_TITLE_RE = re.compile(
    r'<p\s+class="V8SH_title"[^>]*>([^<]+)</p>',
    re.IGNORECASE | re.DOTALL,
)
_HEADING_RE = re.compile(
    r'<p\s+class="V8SH_heading"[^>]*>([^<]+)</p>',
    re.IGNORECASE | re.DOTALL,
)
# После <p class="V8SH_chapter">Имя_раздела:</p> идёт контент до следующего
# V8SH_chapter или конца body.
_CHAPTER_RE = re.compile(
    r'<p\s+class="V8SH_chapter"[^>]*>([^<]+):</p>(.*?)'
    r'(?=<p\s+class="V8SH_chapter"|<HR|</body>)',
    re.IGNORECASE | re.DOTALL,
)
# "Имя_ru (Name_en)" в заголовке
_RU_EN_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NBSP_RE = re.compile(r"&nbsp;|&#160;| ")


def _strip_html(s: str) -> str:
    """Удаляет HTML-теги, разворачивает entities, нормализует пробелы."""
    s = _NBSP_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = (s
         .replace("&lt;", "<").replace("&gt;", ">")
         .replace("&amp;", "&").replace("&quot;", '"')
         .replace("&#39;", "'"))
    s = _WS_RE.sub(" ", s).strip()
    return s


def _parse_html_page(html: str, rel_path: str) -> dict | None:
    """Парсит одну HTML-страницу справки 1С.

    Возвращает dict с полями:
      name_ru          — короткое имя по-русски (напр. "Заблокировать")
      name_en          — короткое имя по-английски (напр. "Lock")
      full_path_ru     — полный путь («СправочникОбъект.<Имя справочника>.Заблокировать»)
      full_path_en     — полный путь en
      parent_ru        — родительский объект ru
      parent_en        — родительский объект en
      kind             — тип записи: method/property/object/event/operator/...
      signature        — сигнатура (например "Заблокировать()" или "Метод(Парам1, Парам2)")
      description      — текст из раздела «Описание»
      params           — текст из раздела «Параметры» (если есть)
      returns          — текст из раздела «Возвращаемое значение» (если есть)
      example          — извлечённый код примера
      availability     — список контекстов (Сервер, толстый клиент, ...)
      raw_chapters     — все «V8SH_chapter» как dict {name: text}
      rel_path         — путь файла относительно корня (для отладки)

    Возвращает None если страница не похожа на справочную (нет H1 или это TOC).
    """
    h1_match = _H1_RE.search(html)
    if not h1_match:
        return None
    h1_text = _strip_html(h1_match.group(1))

    title_match = _PAGE_TITLE_RE.search(html)
    title_text = _strip_html(title_match.group(1)) if title_match else ""

    heading_match = _HEADING_RE.search(html)
    heading_text = _strip_html(heading_match.group(1)) if heading_match else ""

    # Разбираем "имя ru (имя en)" в heading и title
    name_ru = name_en = heading_text
    full_path_ru = full_path_en = h1_text
    parent_ru = parent_en = title_text

    if (m := _RU_EN_RE.match(heading_text)):
        name_ru, name_en = m.group(1).strip(), m.group(2).strip()
    if (m := _RU_EN_RE.match(h1_text)):
        full_path_ru, full_path_en = m.group(1).strip(), m.group(2).strip()
    if (m := _RU_EN_RE.match(title_text)):
        parent_ru, parent_en = m.group(1).strip(), m.group(2).strip()

    # Извлекаем «главы» (Синтаксис, Описание, Параметры, и т.д.)
    chapters: dict[str, str] = {}
    for m in _CHAPTER_RE.finditer(html):
        chap_name = _strip_html(m.group(1)).strip()
        chap_body = _strip_html(m.group(2)).strip()
        chapters[chap_name] = chap_body

    description = chapters.get("Описание", "")
    signature = chapters.get("Синтаксис", "")
    params_text = chapters.get("Параметры", "")
    returns_text = chapters.get("Возвращаемое значение", "")
    availability_text = chapters.get("Доступность", "")
    example_text = chapters.get("Пример", "")

    # Определяем тип записи по пути файла
    kind = _detect_kind(rel_path, signature, params_text)

    return {
        "name_ru": name_ru,
        "name_en": name_en,
        "full_path_ru": full_path_ru,
        "full_path_en": full_path_en,
        "parent_ru": parent_ru,
        "parent_en": parent_en,
        "kind": kind,
        "signature": signature,
        "description": description,
        "params": params_text,
        "returns": returns_text,
        "example": example_text,
        "availability": availability_text,
        "rel_path": rel_path,
    }


def _detect_kind(rel_path: str, signature: str, params: str) -> str:
    """Определяет тип записи: method/property/object/event/operator/global_func."""
    p = rel_path.lower().replace("\\", "/")
    if "/methods/" in p:
        return "method"
    if "/properties/" in p:
        return "property"
    if "/events/" in p:
        return "event"
    if "/operators/" in p:
        return "operator"
    if "/constructors/" in p:
        return "constructor"
    if "/elements/" in p:
        return "element"
    if "global context" in p:
        # Может быть и функция и свойство в глобальном контексте
        if signature and "(" in signature:
            return "global_func"
        return "global_property"
    # Корневая страница каталога/объекта
    return "object"


# ── Indexer: распаковка hbk + парсинг + SQLite ───────────────────────────────


def _iter_hbk_html(hbk_path: Path) -> Iterator[tuple[str, str]]:
    """Итерирует HTML-файлы внутри .hbk. yield (rel_path, html_text)."""
    from onec_dtools import ContainerReader

    with open(hbk_path, "rb") as f:
        reader = ContainerReader(f)
        fs_bytes = b"".join(reader.entries["FileStorage"].data)
    zf = zipfile.ZipFile(io.BytesIO(fs_bytes))
    for name in zf.namelist():
        if not name.lower().endswith(".html"):
            continue
        try:
            data = zf.read(name)
        except Exception as e:
            log.warning("ZIP entry %s read failed: %s", name, e)
            continue
        # 1С HTML файлы в UTF-8 (видно из <meta charset=utf-8>)
        text = data.decode("utf-8", errors="replace")
        yield name, text


def _ensure_schema(conn: sqlite3.Connection):
    """Создаёт таблицы и FTS5-индекс если ещё нет."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS docs (
            id              INTEGER PRIMARY KEY,
            name_ru         TEXT NOT NULL,
            name_en         TEXT NOT NULL,
            full_path_ru    TEXT NOT NULL,
            full_path_en    TEXT NOT NULL,
            parent_ru       TEXT,
            parent_en       TEXT,
            kind            TEXT NOT NULL,
            signature       TEXT,
            description     TEXT,
            params          TEXT,
            returns         TEXT,
            example         TEXT,
            availability    TEXT,
            rel_path        TEXT UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_docs_name_ru  ON docs(name_ru);
        CREATE INDEX IF NOT EXISTS idx_docs_name_en  ON docs(name_en);
        CREATE INDEX IF NOT EXISTS idx_docs_kind     ON docs(kind);
        CREATE INDEX IF NOT EXISTS idx_docs_parent_ru ON docs(parent_ru);

        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            name_ru, name_en, full_path_ru, full_path_en,
            parent_ru, parent_en,
            description, signature, params, returns,
            content='docs', content_rowid='id',
            tokenize='unicode61 remove_diacritics 0'
        );

        CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
            INSERT INTO docs_fts(rowid, name_ru, name_en, full_path_ru, full_path_en,
                                  parent_ru, parent_en, description, signature, params, returns)
            VALUES (new.id, new.name_ru, new.name_en, new.full_path_ru, new.full_path_en,
                    new.parent_ru, new.parent_en, new.description, new.signature, new.params, new.returns);
        END;

        CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
            INSERT INTO docs_fts(docs_fts, rowid, name_ru, name_en, full_path_ru, full_path_en,
                                  parent_ru, parent_en, description, signature, params, returns)
            VALUES ('delete', old.id, old.name_ru, old.name_en, old.full_path_ru, old.full_path_en,
                    old.parent_ru, old.parent_en, old.description, old.signature, old.params, old.returns);
        END;

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)


def build_index(
    hbk_path: Path | str,
    db_path: Path | str = DOCS_DB_PATH,
    *,
    progress_every: int = 5000,
) -> dict:
    """Полная сборка индекса из .hbk → SQLite.
    Возвращает статистику.
    """
    hbk_path = Path(hbk_path)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)

    inserted = 0
    skipped = 0
    by_kind: dict[str, int] = {}

    cur = conn.cursor()
    for i, (rel_path, html) in enumerate(_iter_hbk_html(hbk_path), start=1):
        try:
            parsed = _parse_html_page(html, rel_path)
        except Exception as e:
            log.warning("parse failed %s: %s", rel_path, e)
            skipped += 1
            continue
        if parsed is None:
            skipped += 1
            continue

        try:
            cur.execute("""
                INSERT INTO docs(name_ru, name_en, full_path_ru, full_path_en,
                                 parent_ru, parent_en, kind, signature,
                                 description, params, returns, example,
                                 availability, rel_path)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                parsed["name_ru"], parsed["name_en"],
                parsed["full_path_ru"], parsed["full_path_en"],
                parsed["parent_ru"], parsed["parent_en"],
                parsed["kind"], parsed["signature"],
                parsed["description"], parsed["params"],
                parsed["returns"], parsed["example"],
                parsed["availability"], parsed["rel_path"],
            ))
            inserted += 1
            by_kind[parsed["kind"]] = by_kind.get(parsed["kind"], 0) + 1
        except sqlite3.IntegrityError:
            skipped += 1

        if progress_every and i % progress_every == 0:
            log.info("Indexed %d (inserted=%d, skipped=%d)", i, inserted, skipped)

    # meta
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("source_hbk", str(hbk_path)))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("inserted", str(inserted)))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("by_kind", json.dumps(by_kind, ensure_ascii=False)))

    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    return {"inserted": inserted, "skipped": skipped, "by_kind": by_kind, "db_path": str(db_path)}


# ── Lookup API ───────────────────────────────────────────────────────────────


_TRUNC_LIMIT = 1500  # обрезать описание/пример при выводе LLM


def _truncate(s: str | None, n: int = _TRUNC_LIMIT) -> str:
    if not s:
        return ""
    if len(s) <= n:
        return s
    return s[:n] + " …(обрезано)"


def lookup_by_name(
    name: str,
    *,
    db_path: Path | str = DOCS_DB_PATH,
    limit: int = 10,
) -> list[dict]:
    """Точный или подстрочный поиск по имени (ru или en).
    Стратегия:
      1. Точное равенство name_ru или name_en (case-sensitive)
      2. Если не нашли — case-insensitive
      3. Если не нашли — подстрока (LIKE)
      4. Если не нашли — FTS5 fallback по описанию
    Возвращает список карточек.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return [{"_error": f"Индекс не построен: {db_path}. Запусти build_index()."}]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Точное равенство
    rows = cur.execute("""
        SELECT * FROM docs
        WHERE name_ru = ? OR name_en = ?
        LIMIT ?
    """, (name, name, limit)).fetchall()

    # 2. Case-insensitive
    if not rows:
        rows = cur.execute("""
            SELECT * FROM docs
            WHERE LOWER(name_ru) = LOWER(?) OR LOWER(name_en) = LOWER(?)
            LIMIT ?
        """, (name, name, limit)).fetchall()

    # 3. Подстрока
    if not rows:
        like = f"%{name}%"
        rows = cur.execute("""
            SELECT * FROM docs
            WHERE name_ru LIKE ? OR name_en LIKE ?
               OR full_path_ru LIKE ? OR full_path_en LIKE ?
            LIMIT ?
        """, (like, like, like, like, limit)).fetchall()

    # 4. FTS5 fallback
    if not rows:
        # FTS5 любит экранирование, упрощаем
        fts_query = name.replace('"', '').strip()
        if fts_query:
            try:
                rows = cur.execute(f"""
                    SELECT docs.* FROM docs
                    JOIN docs_fts ON docs.id = docs_fts.rowid
                    WHERE docs_fts MATCH ?
                    LIMIT ?
                """, (f'"{fts_query}"', limit)).fetchall()
            except sqlite3.OperationalError:
                rows = []

    conn.close()
    if not rows:
        return []

    return [_row_to_card(r) for r in rows]


def _row_to_card(row: sqlite3.Row) -> dict:
    return {
        "name": f"{row['name_ru']} ({row['name_en']})" if row['name_en'] != row['name_ru'] else row['name_ru'],
        "full_path": f"{row['full_path_ru']} | {row['full_path_en']}" if row['full_path_en'] != row['full_path_ru'] else row['full_path_ru'],
        "parent": f"{row['parent_ru']} ({row['parent_en']})" if row['parent_en'] and row['parent_en'] != row['parent_ru'] else (row['parent_ru'] or ""),
        "kind": row["kind"],
        "signature": _truncate(row["signature"], 400),
        "description": _truncate(row["description"]),
        "params": _truncate(row["params"]),
        "returns": _truncate(row["returns"], 500),
        "example": _truncate(row["example"], 1000),
        "availability": _truncate(row["availability"], 200),
    }


def stats(db_path: Path | str = DOCS_DB_PATH) -> dict:
    """Статистика по индексу."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"exists": False, "path": str(db_path)}
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    by_kind = dict(cur.execute("SELECT kind, COUNT(*) FROM docs GROUP BY kind").fetchall())
    db_size = db_path.stat().st_size
    conn.close()
    return {
        "exists": True,
        "path": str(db_path),
        "total": total,
        "by_kind": by_kind,
        "db_size_bytes": db_size,
    }
