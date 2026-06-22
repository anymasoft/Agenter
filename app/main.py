"""
Agenter Local — единый процесс: FastAPI + LLM-цикл + Tools + PyWebView.

Заменяет двухкомпонентную схему (backend + desktop с WS-relay). Всё работает
локально: tool calls идут напрямую в ToolExecutor, без сетевых хопов.

Запуск:
    cd agenter/app
    pip install -r requirements.txt
    python main.py

Откроется нативное окно с UI (PyWebView), за кулисами — FastAPI на localhost:8080.
LLM API остаётся в облаке (Anthropic), но конфигурация 1С / ext_src / индекс
никогда не покидают машину.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Пути ────────────────────────────────────────────────────────────────────
_APP_DIR      = Path(__file__).parent.resolve()
_AGENTER_ROOT = _APP_DIR.parent
_CONFIG_DIR   = _AGENTER_ROOT / "config"
_FRONTEND_DIR = _AGENTER_ROOT / "frontend"
DB_PATH       = _APP_DIR / "agenter.db"
OP_STATE_FILE = _APP_DIR / "op_state.json"


# ── Adaptive task budget + Claude Code memory stub ─────────────────────────
# Помощники для Sprint 1 Step 1:
#   • _estimate_max_iterations: подбирает бюджет turns 50/80/120 по сложности
#     prompt'а — большие 9-шаговые ТЗ не должны обрезаться лимитом 50;
#   • _ensure_claude_memory_file: пре-создаёт пустой MEMORY.md в локации,
#     которую Claude Code выводит из cwd. Без этого agent тратит 1 turn на
#     старте каждой задачи на «file does not exist» от внутреннего механизма
#     project-memory.
import re as _re

def _estimate_max_iterations(prompt: str) -> int:
    """Адаптивный бюджет turns:
       • small  (<500 симв ИЛИ <3 нумерованных пунктов) → 50
       • medium (500-2000 ИЛИ 3-5 пунктов)               → 80
       • large  (>2000 ИЛИ >=6 пунктов / упоминаний фаз) → 120

       Нумерованным пунктом считается строка вида ``1. ``/``1) `` или
       упоминание ``Шаг N``/``Phase N``/``Фаза N``.
    """
    chars = len(prompt or "")
    numbered = len(_re.findall(r"(?m)^\s*\d+[\.\)]\s", prompt or ""))
    phases   = len(_re.findall(r"(?i)\b(?:шаг|phase|фаза)\s+\d+\b", prompt or ""))
    items = max(numbered, phases)
    if items >= 6 or chars >= 2000:
        return 120
    if items >= 3 or chars >= 500:
        return 80
    return 50


# ── Sprint 2 S2.8: Детект интерактивного режима из промпта ────────────────
# Универсальный механизм: если в промпте есть явные намёки на желание
# пользователя получать вопросы при неоднозначностях — поднимаем флаг
# `interactive_mode`. Orchestrator добавляет в system_prompt блок,
# который понижает порог обращения к ask_user именно для этой задачи.
#
# Принцип:
#   • НЕТ упоминаний → дефолтное поведение (агент сдержанный, мало спрашивает)
#   • ЕСТЬ упоминания → агент спрашивает на любой существенной неоднозначности
#
# Никаких прошитых имён задач, регистров или объектов. Только обнаружение
# универсального речевого паттерна «спроси меня».

_INTERACTIVE_INTENT_PATTERNS = [
    # RU — глаголы в повелительном (главный сигнал)
    r"\bспрос(?:и|ит[еь])\b",          # спроси, спросите, спросить
    r"\bспрашивай(?:те)?\b",           # спрашивай, спрашивайте
    r"\bуточн(?:и|ит[еь]|яй(?:те)?)\b",# уточни, уточните, уточняй
    r"\bсообщ(?:и|ит[еь])\b",          # сообщи, сообщите
    # RU — устойчивые обороты
    r"если\s+(?:есть|возникн[уу][тл])\s+вопрос",
    r"если\s+что[- ]?то\s+непонятно",
    r"если\s+(?:что[- ]?то|есть)\s+непонятн",
    r"\bне\s+угадывай\b",
    r"\bне\s+выдумывай\b",
    r"\bне\s+додумывай\b",
    # EN
    r"\bask\s+(?:me|user|first)\b",
    r"\bclarify\b",
    r"if\s+you\s+have\s+(?:any\s+)?questions",
    r"when\s+in\s+doubt",
    r"\bdon[\'`]?t\s+guess\b",
]

_INTERACTIVE_RE = _re.compile("|".join(_INTERACTIVE_INTENT_PATTERNS), _re.IGNORECASE)

# Anti-patterns: явные «НЕ будь интерактивным» формулировки. Если матч есть —
# полностью отключаем интерактивный режим независимо от наличия позитивных
# сигналов. Это покрывает кейсы вида «не спрашивай меня, разберись сам»
# где могут попасться и позитивные слова, но общая интенция — НЕ спрашивать.
_INTERACTIVE_ANTI_PATTERNS = [
    r"\bне\s+спрашивай(?:те)?\b",
    r"\bне\s+спрос(?:и|ит[еь])\b",
    r"\bне\s+уточняй(?:те)?\b",
    r"\bне\s+отвлекай\b",
    r"\bразбер(?:и(?:сь)?|итесь)\s+сам",
    r"\bdon[\'`]?t\s+(?:ask|clarify|interrupt|bother)\b",
    r"\bjust\s+do\s+it\b",
]
_INTERACTIVE_ANTI_RE = _re.compile("|".join(_INTERACTIVE_ANTI_PATTERNS), _re.IGNORECASE)


def _detect_interactive_intent(prompt: str) -> bool:
    """Возвращает True если в промпте есть явный запрос на интерактивность.

    Иерархия:
      1. Anti-pattern («не спрашивай», «don't ask», «разберись сам») —
         блокирует режим целиком, независимо от позитивных триггеров.
      2. Локальное отрицание перед позитивным триггером (lookback 8 симв):
         «не угадывай» уже в позитивных, но «не спроси» — пропустить.
      3. Любой позитивный триггер без отрицания → True.

    Это покрывает ~99% реальных формулировок.
    """
    if not prompt:
        return False
    text = prompt
    # 1. Глобальный anti-pattern перебивает всё
    if _INTERACTIVE_ANTI_RE.search(text):
        return False
    # 2. + 3. Позитивные триггеры с локальной проверкой отрицания
    for m in _INTERACTIVE_RE.finditer(text):
        start = m.start()
        # Lookback 8 символов: достаточно чтобы поймать «Don't » (6 + 1 пробел) или «не »
        prefix = text[max(0, start - 8):start].lower()
        prefix_clean = prefix.rstrip()
        # Отрицание перед триггером — пропустить этот матч
        if (prefix_clean.endswith("не")
                or prefix_clean.endswith("don't")
                or prefix_clean.endswith("dont")):
            continue
        return True
    return False


def _ensure_claude_memory_file(cwd: str) -> None:
    """Гарантирует существование пустого MEMORY.md в локации, которую Claude
    Code выводит из cwd. Слаг Claude Code: drive ``:`` → ``-``, разделители
    путей ``\\`` / ``/`` → ``-``.

    Пример: ``D:\\CURSORIC\\agenter\\ext_src`` → ``C--BUFFER-ERP-ext_src``.

    Файл — пустая заглушка; если уже существует — не трогаем.
    """
    if not cwd:
        return
    try:
        slug = (
            cwd.replace(":", "-")
               .replace("\\", "-")
               .replace("/", "-")
        )
        home = Path.home()
        memdir = home / ".claude" / "projects" / slug / "memory"
        memfile = memdir / "MEMORY.md"
        if memfile.exists():
            return
        memdir.mkdir(parents=True, exist_ok=True)
        memfile.write_text("", encoding="utf-8")
        log.info("Pre-created Claude Code memory stub: %s", memfile)
    except Exception as e:
        log.warning("Не удалось создать MEMORY.md stub: %s", e)

# .env лежит в agenter/.env
load_dotenv(_AGENTER_ROOT / ".env")

# ── Переключатель провайдера модели (model-agnostic ядро) ──────────────────
# AGENT_PROVIDER=deepseek → ходим в DeepSeek через его родной Anthropic-эндпоинт
# (Claude Agent SDK уважает ANTHROPIC_BASE_URL из окружения). По умолчанию Claude.
# Ключи берём из .env (gitignored): DEEPSEEK_API_KEY / ANTHROPIC_API_KEY.
AGENT_PROVIDER = os.environ.get("AGENT_PROVIDER", "claude").strip().lower()
if AGENT_PROVIDER == "deepseek":
    os.environ["ANTHROPIC_BASE_URL"] = os.environ.get(
        "DEEPSEEK_ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    ANTHROPIC_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    # дефолтная модель для этого провайдера (если в запросе/конфиге не указана иная)
    os.environ.setdefault("AGENT_DEFAULT_MODEL", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
else:
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Импорты под уникальными именами — см. _imports.py
from _imports import ToolExecutor, BslAtlasClient, load_config  # noqa: E402

# Локальный оркестратор (миграция на Claude Agent SDK)
# Старый orchestrator.py пока сохранён рядом — переключение через env var.
import os as _os
if _os.environ.get("AGENTER_LEGACY_ORCHESTRATOR") == "1":
    from orchestrator import run_task  # noqa: E402  (старый, для отката)
else:
    from orchestrator_sdk import run_task  # noqa: E402

# Реестр MCP-серверов (Phase C: data-driven регистрация вместо хардкода)
from mcp_registry import McpServerRegistry  # noqa: E402

# Snapshots ext_src/ + чтение MEMORY.md — для auto-rollback и долговременной памяти
from snapshots import (  # noqa: E402
    create_snapshot, restore_snapshot, delete_snapshot,
    load_memory_md, memory_md_path, append_memory_md,
)

# Метаданные конфигурации 1С (порт из MetadataViewer1C, see metadata_utils/)
from metadata_utils.metadata_repository import MetadataRepository, MetadataTreeNode  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agenter.app")


# ── Состояние приложения ────────────────────────────────────────────────────

class AppState:
    """In-memory state. SQLite — для долгоживущих задач."""

    def __init__(self):
        self.web_clients: set[WebSocket] = set()
        self.client_cfg: dict = {}
        self.executor: ToolExecutor | None = None
        self.bsl: BslAtlasClient | None = None
        # Phase C: реестр MCP-серверов (включая bsl-atlas как частный случай).
        # Параллельно держим .bsl для backward-compat с ToolExecutor.
        self.registry: McpServerRegistry | None = None
        # Запущенные сейчас задачи — handle для отмены через .cancel()
        self.running_tasks: dict[str, asyncio.Task] = {}
        # Репозиторий метаданных 1С (lazy-init при первом /metadata/* запросе)
        self.metadata_repo: MetadataRepository | None = None
        # Реестр висящих вопросов к юзеру (tool ask_user).
        # Ключ — task_id; значение — словарь с:
        #   "event":    asyncio.Event — ставится при получении ответа
        #   "answer":   str | None    — текст ответа (None пока не получен)
        #   "qid":      str           — id вопроса (для логов и сопоставления)
        #   "question": str           — текст вопроса (для UI fallback)
        #   "options":  list[str]     — варианты (пусто = свободный ответ)
        # Один task_id может ждать только одного вопроса за раз — это намеренно:
        # tool ask_user блокирующий, новый вопрос задаётся только после ответа.
        self.pending_questions: dict[str, dict] = {}


state = AppState()


# ── SQLite (как в backend/main.py, скопировано) ────────────────────────────

def _init_db():
    """Создаёт схему БД при первом запуске. Idempotent.

    Таблицы:
      tasks         — задачи (расширена полями session_id / phases / final_state)
      sessions      — Claude SDK сессии per project (для auto-resume)
      task_phases   — фазы внутри задачи (детект через успешный db_load)

    Миграции: ALTER TABLE через try/except — если колонка уже есть, sqlite
    бросает 'duplicate column name', который мы глушим. Это работает потому
    что БД небольшая и схема меняется редко (нет нужды в alembic-style миграциях).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            log_jsonl TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    # Новые колонки tasks (миграция для старых БД):
    #   session_id        — к какой Claude SDK сессии относится задача
    #   project_id        — для будущей мультипроектности (сейчас всегда 'erp')
    #   phases_total      — сколько фаз агент спланировал (через TodoWrite или из логов)
    #   phases_committed  — сколько успешно применено в БД через db_load
    #   db_load_count     — сколько раз вызывался успешный db_load
    #   final_state       — applied / partial / staged / failed (см. _compute_final_state)
    #   incomplete_todos  — Sprint 2 S2.7: сколько пунктов TodoWrite остались
    #                       НЕзавершёнными на последнем снимке (pending/in_progress).
    #                       NULL = TodoWrite в этой задаче ни разу не вызывался.
    #                       0    = все пункты completed (или cancelled).
    #                       N>0  = N пунктов остались — задача неполная (partial).
    #   todos_total       — всего пунктов в последнем TodoWrite (для диагностики)
    for col_def in [
        "session_id TEXT",
        "project_id TEXT DEFAULT 'erp'",
        "phases_total INTEGER DEFAULT 0",
        "phases_committed INTEGER DEFAULT 0",
        "db_load_count INTEGER DEFAULT 0",
        "final_state TEXT",
        "incomplete_todos INTEGER",  # NULL by design — отличает «не вызывался» от «всё completed»
        "todos_total INTEGER",
    ]:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_def}")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

    # Таблица сессий — одна на проект. Хранит sdk_session_id для resume.
    # snapshot_path — zip ext_src, созданный при первой задаче в сессии,
    #                  для возможности отката через POST /tasks/{id}/rollback.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            project_id TEXT PRIMARY KEY,
            sdk_session_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            tasks_count INTEGER DEFAULT 0,
            snapshot_path TEXT
        )
    """)

    # Фазы внутри задачи. phase_index — порядковый номер 1..N. status:
    #   pending     — спланирована, но не начата
    #   running     — выполняется сейчас
    #   committed   — успешный db_load по этой фазе
    #   failed      — db_load упал или cfe_validate вернул errors
    #   skipped     — пропущена (бюджет / отмена)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            phase_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            db_load_at TEXT,
            error_msg TEXT,
            UNIQUE(task_id, phase_index)
        )
    """)
    # Индекс для быстрого выбора фаз задачи (GET /tasks/{id}/phases)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_phases_task ON task_phases(task_id)"
    )

    # Sprint 4 S4.2: таблица task_stages — план задачи в детерминированном
    # формате. Один задача → N стадий с kind/expected_tool. Используется
    # диспетчером для жёсткого whitelisting'а tools на каждой стадии.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            stage_index INTEGER NOT NULL,
            kind TEXT NOT NULL,
            description TEXT NOT NULL,
            expected_tool TEXT NOT NULL,
            args_hint TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            completed_at TEXT,
            error_msg TEXT,
            UNIQUE(task_id, stage_index)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_stages_task ON task_stages(task_id)"
    )
    conn.commit()
    conn.close()


def _create_task(task_id: str, prompt: str, project_id: str = "erp") -> dict:
    """INSERT задачи. Новые столбцы (session_id, phases_*, final_state, project_id)
    проставятся ниже при привязке сессии через _bind_task_session()."""
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        # Эксплицитный список колонок: новые поля имеют DEFAULT, поэтому их можно
        # не указывать — INSERT не сломается даже если столбцы добавлены позже.
        "INSERT INTO tasks (id, prompt, status, log_jsonl, created_at, completed_at, project_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (task_id, prompt, "pending", "", now, None, project_id),
    )
    conn.commit()
    conn.close()
    return {"id": task_id, "prompt": prompt, "status": "pending", "created_at": now}


# ── Sessions (Claude SDK auto-resume) ───────────────────────────────────────

def _get_session(project_id: str) -> dict | None:
    """Возвращает текущую сессию проекта или None если её ещё нет/сброшена."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT project_id, sdk_session_id, started_at, last_seen_at, "
        "tasks_count, snapshot_path FROM sessions WHERE project_id=?",
        (project_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "project_id":     row[0],
        "sdk_session_id": row[1],
        "started_at":     row[2],
        "last_seen_at":   row[3],
        "tasks_count":    row[4],
        "snapshot_path":  row[5],
    }


def _upsert_session(
    project_id: str,
    sdk_session_id: str,
    snapshot_path: str | None = None,
) -> None:
    """Записывает/обновляет сессию. Если sdk_session_id меняется (например
    из-за expired resume) — обновляется started_at; иначе только last_seen_at
    и tasks_count++.

    snapshot_path передаётся только при создании сессии (первая задача); при
    повторных вызовах остаётся прежним.
    """
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT sdk_session_id FROM sessions WHERE project_id=?",
        (project_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO sessions (project_id, sdk_session_id, started_at, "
            "last_seen_at, tasks_count, snapshot_path) VALUES (?,?,?,?,?,?)",
            (project_id, sdk_session_id, now, now, 1, snapshot_path),
        )
    elif existing[0] != sdk_session_id:
        # Сессия пересоздана (resume не удался, SDK завёл новую) — обновляем
        # ID и started_at. snapshot оставляем как есть, если не передан явно.
        if snapshot_path is None:
            conn.execute(
                "UPDATE sessions SET sdk_session_id=?, started_at=?, "
                "last_seen_at=?, tasks_count=1 WHERE project_id=?",
                (sdk_session_id, now, now, project_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET sdk_session_id=?, started_at=?, "
                "last_seen_at=?, tasks_count=1, snapshot_path=? "
                "WHERE project_id=?",
                (sdk_session_id, now, now, snapshot_path, project_id),
            )
    else:
        # Та же сессия — просто инкрементируем счётчик и обновляем last_seen.
        conn.execute(
            "UPDATE sessions SET last_seen_at=?, tasks_count=tasks_count+1 "
            "WHERE project_id=?",
            (now, project_id),
        )
    conn.commit()
    conn.close()


def _reset_session(project_id: str) -> dict | None:
    """Удаляет запись сессии. Возвращает старую сессию (для информации о
    snapshot_path, чтобы caller мог его удалить). None если сессии не было."""
    old = _get_session(project_id)
    if old is None:
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM sessions WHERE project_id=?", (project_id,))
    conn.commit()
    conn.close()
    return old


def _bind_task_session(task_id: str, sdk_session_id: str) -> None:
    """Прописывает связь задачи с сессией. Вызывается из orchestrator
    после получения session_id из первой SystemMessage."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tasks SET session_id=? WHERE id=?",
        (sdk_session_id, task_id),
    )
    conn.commit()
    conn.close()


# ── Phases (детект по успешным db_load) ─────────────────────────────────────

def _record_phase(
    task_id: str,
    phase_index: int,
    title: str,
    status: str,
    error_msg: str | None = None,
) -> None:
    """UPSERT фазы. Вызывается из orchestrator при детекте границ фаз и
    при успешном db_load (отмечает фазу как committed).

    status: pending | running | committed | failed | skipped
    """
    now = datetime.utcnow().isoformat() if status == "committed" else None
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM task_phases WHERE task_id=? AND phase_index=?",
        (task_id, phase_index),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE task_phases SET title=?, status=?, db_load_at=?, error_msg=? "
            "WHERE id=?",
            (title, status, now, error_msg, existing[0]),
        )
    else:
        conn.execute(
            "INSERT INTO task_phases (task_id, phase_index, title, status, "
            "db_load_at, error_msg) VALUES (?,?,?,?,?,?)",
            (task_id, phase_index, title, status, now, error_msg),
        )
    conn.commit()
    conn.close()


def _list_phases(task_id: str) -> list[dict]:
    """Все фазы задачи в порядке phase_index."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT phase_index, title, status, db_load_at, error_msg "
        "FROM task_phases WHERE task_id=? ORDER BY phase_index",
        (task_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "index":       r[0],
            "title":       r[1],
            "status":      r[2],
            "db_load_at":  r[3],
            "error_msg":   r[4],
        }
        for r in rows
    ]


# ── Sprint 4 S4.2: помощники для task_stages ────────────────────────────────

def _save_task_stages(task_id: str, stages: list[dict]) -> None:
    """Перезаписывает план задачи. Сначала удаляет старые записи, потом
    INSERT новых. Используется при первом и повторных plan_task вызовах.

    stages — список словарей с полями kind, description, expected_tool,
    args_hint (может быть {}), status (обычно 'pending').
    """
    import json as _json
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        # Полный re-plan: чистим старый план и пишем новый
        conn.execute("DELETE FROM task_stages WHERE task_id=?", (task_id,))
        for i, s in enumerate(stages, start=1):
            args_json = _json.dumps(s.get("args_hint") or {}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO task_stages "
                "(task_id, stage_index, kind, description, expected_tool, "
                " args_hint, status, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id, i,
                    s["kind"], s["description"], s["expected_tool"],
                    args_json, s.get("status", "pending"),
                    now if i == 1 else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _get_task_stages(task_id: str) -> list[dict]:
    """Все стадии задачи в порядке stage_index."""
    import json as _json
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT stage_index, kind, description, expected_tool, args_hint, "
        "status, started_at, completed_at, error_msg "
        "FROM task_stages WHERE task_id=? ORDER BY stage_index",
        (task_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            args_hint = _json.loads(r[4] or "{}")
        except Exception:
            args_hint = {}
        out.append({
            "index":         r[0],
            "kind":          r[1],
            "description":   r[2],
            "expected_tool": r[3],
            "args_hint":     args_hint,
            "status":        r[5],
            "started_at":    r[6],
            "completed_at":  r[7],
            "error_msg":     r[8],
        })
    return out


def _get_current_stage(task_id: str) -> dict | None:
    """Возвращает текущую активную стадию задачи (status='in_progress'),
    или первую pending если активной нет. None если план пуст или все
    стадии закрыты."""
    stages = _get_task_stages(task_id)
    for s in stages:
        if s["status"] == "in_progress":
            return s
    for s in stages:
        if s["status"] == "pending":
            return s
    return None


def _update_stage_status(
    task_id: str,
    stage_index: int,
    status: str,
    error_msg: str | None = None,
) -> None:
    """Обновляет статус одной стадии. status ∈ pending|in_progress|completed|failed|skipped."""
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        if status == "in_progress":
            conn.execute(
                "UPDATE task_stages SET status=?, started_at=COALESCE(started_at,?) "
                "WHERE task_id=? AND stage_index=?",
                (status, now, task_id, stage_index),
            )
        elif status in ("completed", "failed", "skipped"):
            conn.execute(
                "UPDATE task_stages SET status=?, completed_at=?, error_msg=? "
                "WHERE task_id=? AND stage_index=?",
                (status, now, error_msg, task_id, stage_index),
            )
        else:
            conn.execute(
                "UPDATE task_stages SET status=? "
                "WHERE task_id=? AND stage_index=?",
                (status, task_id, stage_index),
            )
        conn.commit()
    finally:
        conn.close()


def _update_task_counters(
    task_id: str,
    *,
    db_load_count: int | None = None,
    phases_total: int | None = None,
    phases_committed: int | None = None,
    final_state: str | None = None,
    incomplete_todos: int | None = None,
    todos_total: int | None = None,
) -> None:
    """Точечное обновление счётчиков задачи. None = не трогать.

    final_state: applied | partial | staged | failed | legacy
    incomplete_todos / todos_total: Sprint 2 S2.7 — снимок TodoWrite-attestation
    """
    sets = []
    vals: list = []
    if db_load_count is not None:
        sets.append("db_load_count=?")
        vals.append(db_load_count)
    if phases_total is not None:
        sets.append("phases_total=?")
        vals.append(phases_total)
    if phases_committed is not None:
        sets.append("phases_committed=?")
        vals.append(phases_committed)
    if final_state is not None:
        sets.append("final_state=?")
        vals.append(final_state)
    if incomplete_todos is not None:
        sets.append("incomplete_todos=?")
        vals.append(incomplete_todos)
    if todos_total is not None:
        sets.append("todos_total=?")
        vals.append(todos_total)
    if not sets:
        return
    vals.append(task_id)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()


def _compute_final_state(task_id: str) -> str:
    """Вычисляет итоговое состояние задачи на основе счётчиков:
      applied — все запланированные фазы committed
      partial — какие-то фазы committed, но не все
      staged  — изменения только в ext_src/, db_load не вызывался (или 0 успехов)
      failed  — задача в статусе error и нет успешных db_load
      legacy  — задача создана ДО ADR-018 (нет session_id), точное состояние
                не отслеживается; UI показывает «Завершено (статус не отслеживался)»

    Иерархия источников истины (от точного к приблизительному):
      1. incomplete_todos (Sprint 2 S2.7) — если агент вёл TodoWrite,
         наличие незавершённых пунктов в финале = partial. Это самый
         надёжный сигнал, опирается на самоотчёт агента.
      2. phases_total/phases_committed — устаревший канал, сейчас никто не
         выставляет phases_total > 0, но логика осталась на будущее.
      3. status + db_load_count — fallback когда нет ни TodoWrite, ни плана.
    """
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT status, phases_total, phases_committed, db_load_count, session_id, "
        "incomplete_todos, todos_total "
        "FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    conn.close()
    if not row:
        return "staged"
    (status, phases_total, phases_committed, db_load_count, session_id,
     incomplete_todos, todos_total) = row
    phases_total     = phases_total or 0
    phases_committed = phases_committed or 0
    db_load_count    = db_load_count or 0

    # Sprint 2 S2.4: legacy задачи (до ADR-018) не имели tracking'а —
    # не врём ни про «applied», ни про «staged», говорим как есть.
    if not session_id:
        if status == "error":
            return "failed"
        return "legacy"

    # Sprint 2 S2.7: ПЕРВЫЙ ПРИОРИТЕТ — TodoWrite-attestation.
    # Если агент вёл TodoWrite (incomplete_todos НЕ NULL — то есть хотя бы
    # один TodoWrite-вызов был) и оставил пункты в pending/in_progress на
    # финале — задача неполная, независимо от того сколько раз был db_load.
    #
    # Это закрывает «партиал-кейс»: L4-задача из 9 пунктов где агент успел
    # сделать 2 db_load и упёрся в BUDGET. status=done (агент сам резюмировал),
    # db_load_count=2, но в TodoWrite осталось 7 pending → partial.
    if incomplete_todos is not None and incomplete_todos > 0:
        # Незавершённые пункты есть. Если хоть один db_load был — partial,
        # иначе staged (план есть, но в БД ничего не дошло).
        if db_load_count > 0:
            return "partial"
        if status == "error":
            return "failed"
        return "staged"

    # Hotfix 2026-05-16: задача завершилась успешно (status=done) + был хотя
    # бы один успешный db_load = всё применено. Раньше это попадало в
    # «partial» из-за phases_total=0 (у простых L1/L2 задач без TodoWrite
    # плана total никогда не выставляется). Для done-задач игнорируем total
    # — если агент сам сказал «готово» и БД получила хотя бы один коммит,
    # значит, по его мнению, фаз больше не планировалось.
    if status == "done" and db_load_count > 0:
        if phases_total > 0 and phases_committed < phases_total:
            # Был явный план на N фаз, закоммитили меньше — действительно partial
            return "partial"
        return "applied"

    if status == "error" and db_load_count == 0:
        return "failed"
    if db_load_count == 0:
        return "staged"
    # status=error и был хотя бы один db_load — частичное применение до ошибки
    if phases_committed > 0 or db_load_count > 0:
        return "partial"
    return "staged"


def _get_task(task_id: str) -> dict | None:
    """Возвращает словарь со всеми полями задачи. ALTER TABLE мог добавить
    новые колонки — используем cursor.description, чтобы не зависеть от
    порядка колонок в схеме."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(zip(cols, row))


def _update_status(task_id: str, status: str, completed_at: str | None = None):
    conn = sqlite3.connect(DB_PATH)
    if completed_at:
        conn.execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?",
                     (status, completed_at, task_id))
    else:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    conn.close()


def _append_log_db(task_id: str, entry: dict):
    conn = sqlite3.connect(DB_PATH)
    line = json.dumps(entry, ensure_ascii=False)
    conn.execute(
        "UPDATE tasks SET log_jsonl = log_jsonl || ? WHERE id=?",
        (line + "\n", task_id),
    )
    conn.commit()
    conn.close()


# ── Broadcast в UI ──────────────────────────────────────────────────────────

async def _broadcast(event: dict):
    dead: set[WebSocket] = set()
    for ws in state.web_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    state.web_clients -= dead


# ── Callback'и для orchestrator.run_task ────────────────────────────────────

async def _on_log(task_id: str, text: str, meta: str = "", kind: str = "step"):
    """kind: 'step' — техническая строка лога (попадёт в exec-rows),
             'text' — markdown-текст от LLM (рендерится отдельным блоком)."""
    ts = datetime.utcnow().strftime("%H:%M:%S")
    entry = {
        "type": "log", "task_id": task_id,
        "ts": ts, "text": text, "meta": meta, "kind": kind,
    }
    await asyncio.to_thread(_append_log_db, task_id, entry)
    await _broadcast(entry)


async def _on_status(task_id: str, status: str):
    await asyncio.to_thread(_update_status, task_id, status)
    await _broadcast({"type": "status", "task_id": task_id, "status": status})


async def _on_done(task_id: str):
    await asyncio.to_thread(
        _update_status, task_id, "done", datetime.utcnow().isoformat()
    )
    await _broadcast({"type": "task_done", "task_id": task_id})


async def _on_error(task_id: str, error_msg: str):
    await asyncio.to_thread(
        _update_status, task_id, "error", datetime.utcnow().isoformat()
    )
    await _broadcast({"type": "task_error", "task_id": task_id, "error": error_msg})


async def _on_iteration(task_id: str, current: int, total: int):
    """Прогресс итерации LLM-цикла. Используется UI для отображения N/M."""
    await _broadcast({
        "type": "iteration_progress",
        "task_id": task_id,
        "current": current,
        "total": total,
    })


# ── ask_user: блокирующий вопрос к юзеру ───────────────────────────────────
# Tool ask_user в SDK вызывает _ask_user_async; та регистрирует pending_question,
# шлёт WS-событие в UI и ждёт setting'а event. POST /tasks/{id}/answer от UI
# проставляет ответ и разбуживает event.

async def _ask_user_async(
    task_id: str,
    question: str,
    options: list[str] | None = None,
    *,
    timeout: float = 600.0,
) -> str:
    """Останавливает агента и ждёт ответ юзера. Возвращает строку ответа.

    Если задача отменена или истёк timeout — возвращает специальный sentinel,
    чтобы LLM понял что взаимодействие сорвалось (и не зациклился)."""
    import secrets
    qid = secrets.token_hex(8)
    event = asyncio.Event()
    state.pending_questions[task_id] = {
        "event":    event,
        "answer":   None,
        "qid":      qid,
        "question": question,
        "options":  list(options or []),
    }
    # WS: показать модалку
    await _broadcast({
        "type":     "ask_user",
        "task_id":  task_id,
        "qid":      qid,
        "question": question,
        "options":  list(options or []),
    })
    # Лог в exec-row: видно что задача ждёт юзера
    await _on_log(
        task_id,
        "⏸ Жду ответ юзера",
        question[:120] + ("…" if len(question) > 120 else ""),
        kind="step",
    )
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        answer = state.pending_questions[task_id].get("answer")
        await _broadcast({
            "type":    "ask_user_resolved",
            "task_id": task_id,
            "qid":     qid,
            "answer":  answer or "",
        })
        if answer is None:
            return "[CANCELLED: задача отменена пользователем]"
        # Лог в чат — markdown-блок с Q+A для истории
        await _on_log(
            task_id,
            f"**❓ Вопрос агенту:** {question}\n\n**🗣 Ответ:** {answer}",
            "",
            kind="text",
        )
        return answer
    except asyncio.TimeoutError:
        await _broadcast({
            "type":    "ask_user_resolved",
            "task_id": task_id,
            "qid":     qid,
            "answer":  "",
            "timeout": True,
        })
        return "[TIMEOUT: пользователь не ответил за 10 минут — продолжай разумным дефолтом или верни ошибку]"
    finally:
        state.pending_questions.pop(task_id, None)


# ── Запуск задачи через BackgroundTasks ─────────────────────────────────────

async def _on_session_captured(task_id: str, project_id: str, sdk_session_id: str):
    """Callback из orchestrator: SDK прислал session_id (init или resumed).
    Записываем в БД, шлём WS-event в UI."""
    snapshot_path = None
    # Если в проекте уже есть сессия с тем же sdk_session_id — snapshot уже
    # создан, не пересоздаём. Если sdk_session_id новый — это либо первая
    # задача проекта, либо resume провалился. В обоих случаях это «новая
    # сессия», и для неё имеет смысл создать свежий snapshot.
    existing = await asyncio.to_thread(_get_session, project_id)
    is_new_session = existing is None or existing.get("sdk_session_id") != sdk_session_id
    if is_new_session:
        ext_src = state.client_cfg.get("ext_src_path") or ""
        try:
            snap = await asyncio.to_thread(
                create_snapshot, ext_src, _APP_DIR, project_id, task_id,
            )
            snapshot_path = str(snap) if snap else None
            if snap:
                await _broadcast({
                    "type": "snapshot_created",
                    "task_id": task_id,
                    "project_id": project_id,
                    "path": snapshot_path,
                })
        except Exception as e:
            log.warning("snapshot create failed: %s", e)

    await asyncio.to_thread(
        _upsert_session, project_id, sdk_session_id, snapshot_path,
    )
    await asyncio.to_thread(_bind_task_session, task_id, sdk_session_id)
    sess = await asyncio.to_thread(_get_session, project_id)
    if sess:
        await _broadcast({
            "type": "session_updated",
            "project_id": project_id,
            "sdk_session_id": sess["sdk_session_id"],
            "tasks_count": sess["tasks_count"],
            "started_at": sess["started_at"],
        })


async def _on_phase_commit(task_id: str, phase_index: int):
    """Callback из orchestrator после успешного db_load. Записываем фазу
    как committed, обновляем счётчик задачи, шлём WS-event."""
    # Title по умолчанию — индекс. Реальное название берётся из TodoWrite
    # на стороне UI (если фронт сопоставит). Здесь храним только факт коммита.
    title = f"Фаза {phase_index}"
    await asyncio.to_thread(
        _record_phase, task_id, phase_index, title, "committed",
    )
    # Инкрементируем суммарный счётчик задачи + достаём project_id для MEMORY.md
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT db_load_count, phases_committed, project_id, "
        "substr(prompt,1,80) as prompt_head FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    conn.close()
    if row:
        new_db_load = (row[0] or 0) + 1
        new_committed = (row[1] or 0) + 1
        project_id = row[2] or "erp"
        prompt_head = (row[3] or "").replace("\n", " ").strip()
        await asyncio.to_thread(
            _update_task_counters, task_id,
            db_load_count=new_db_load,
            phases_committed=new_committed,
        )
        # Sprint 2 S2.5: автозапись в MEMORY.md — чтобы следующая задача
        # (через resume) сразу видела факт «фаза N задачи XXX применена в БД».
        memory_line = (
            f"db_load #{new_db_load} (task {task_id[:8]}, фаза {phase_index})"
            f" · {prompt_head[:60]}"
        )
        await asyncio.to_thread(
            append_memory_md, _APP_DIR, project_id, memory_line,
        )
    await _broadcast({
        "type":        "phase_committed",
        "task_id":     task_id,
        "phase_index": phase_index,
        "title":       title,
    })


async def _on_todos_update(task_id: str, incomplete: int, total: int):
    """Sprint 2 S2.7: callback из orchestrator post-hook после каждого
    успешного TodoWrite. Сохраняет снимок прогресса (сколько незавершённых
    пунктов осталось) — нужен для финального вычисления `final_state`.

    Семантика incomplete: пункты со статусом pending или in_progress.
    completed и cancelled не считаются (они «закрыты»).

    Этот канал универсален: работает для любых задач — простых, средних,
    больших. Никакого hardcode под тип задачи."""
    await asyncio.to_thread(
        _update_task_counters, task_id,
        incomplete_todos=incomplete,
        todos_total=total,
    )


async def _run_task_wrapper(
    task_id: str,
    prompt: str,
    model_alias: str | None = None,
    project_id: str = "erp",
):
    if state.executor is None:
        await _on_error(task_id, "ToolExecutor не инициализирован")
        return

    # Auto-resume: если в проекте есть сессия — возобновляем её, иначе
    # новая сессия (SDK сам выпишет session_id, мы поймаем через callback).
    sess = await asyncio.to_thread(_get_session, project_id)
    resume_session_id = sess["sdk_session_id"] if sess else None

    # MEMORY.md: долговременная память проекта. Инлайнится в system_prompt.
    memory_md = await asyncio.to_thread(load_memory_md, _APP_DIR, project_id)

    # ── Sprint 1 Step 1: предотвращаем -1 turn на старте задачи ──────────
    # Claude Code SDK при инициализации ищет project-memory по cwd. Если
    # файла нет — он логирует «file does not exist», что в нашем UI
    # выглядит как лишний шаг. Создаём пустую заглушку.
    ext_src = state.client_cfg.get("ext_src_path") or ""
    if ext_src:
        await asyncio.to_thread(_ensure_claude_memory_file, ext_src)

    # ── Sprint 1 Step 1: адаптивный бюджет turns ──────────────────────────
    # Большие 9-шаговые ТЗ не помещаются в 50 turns по умолчанию. Считаем
    # сложность по prompt'у (длина + число пунктов) → 50/80/120. Делаем
    # per-task копию client_cfg, чтобы не задеть параллельные задачи.
    #
    # Семантика: max_iterations в config.json = «нижняя планка» (floor).
    # Адаптивный auto — может только увеличить, не уменьшить. Это даёт
    # пользователю контроль («хочу минимум 50 даже на мелочи»), но не
    # обрезает большие задачи.
    task_cfg = dict(state.client_cfg)
    auto_budget = _estimate_max_iterations(prompt)
    config_floor = int(task_cfg.get("max_iterations") or 0)
    final_budget = max(config_floor, auto_budget)
    task_cfg["max_iterations"] = final_budget
    # Sprint 2 S2.6: для L4-задач (auto_budget == 120) включаем «spec-first»
    # директиву в system_prompt. Не активируем для resume — в продолжении
    # сессии proposal уже есть (или агент сам решит дописать).
    is_large_task = (auto_budget >= 120)
    task_cfg["spec_first_required"] = is_large_task and (resume_session_id is None)
    task_cfg["task_level"] = (
        "L4" if auto_budget >= 120 else
        "L3" if auto_budget >= 80  else
        "L2" if auto_budget >= 50  else "L1"
    )
    await _on_log(
        task_id,
        "📊 Бюджет turns",
        f"{final_budget}"
        + (f" (auto={auto_budget}, config floor={config_floor})"
           if config_floor and config_floor != final_budget
           else f" (auto по длине промпта и числу пунктов)")
        + f" · уровень {task_cfg['task_level']}",
    )
    if task_cfg.get("spec_first_required"):
        await _on_log(
            task_id, "📋 Spec-first",
            "Большая задача — первым шагом TodoWrite + proposal.md в agenter/data/.../proposals/",
        )

    # ── Sprint 2 S2.8: интерактивный режим по запросу юзера ─────────────
    # Универсальный механизм без hardcode под тип задачи: если юзер в промпте
    # явно просит «спроси / уточни / при сомнениях» — флаг task_cfg["interactive_mode"]
    # → orchestrator добавляет блок в system_prompt, который понижает порог
    # обращения к ask_user именно для этой задачи.
    task_cfg["interactive_mode"] = _detect_interactive_intent(prompt)
    if task_cfg["interactive_mode"]:
        await _on_log(
            task_id, "💬 Интерактивный режим",
            "в промпте есть просьба спрашивать — порог ask_user понижен на эту задачу",
        )

    # ── Sprint 4 S4.7: stage-dispatch обязателен для L2+ ──────────────────
    # L1 — простые задачи (1-2 шага), план не нужен (overhead больше пользы).
    # L2+ — должны идти через plan_task → стадии → expected_tool на каждой.
    # До plan_task все модифицирующие tools заблокированы guard'ом
    # (см. check_tool_call с stage_dispatch_required=True).
    task_cfg["_stage_dispatch_required"] = (task_cfg["task_level"] != "L1")
    if task_cfg["_stage_dispatch_required"]:
        await _on_log(
            task_id, "🎯 Stage-dispatch активен",
            "первым шагом должен быть plan_task — диспетчер выбирает tool по kind стадии",
        )

    # Wrapper над on_session_captured, чтобы прокинуть project_id (orchestrator
    # его не знает — там cwd-based).
    async def _capture(sid: str):
        await _on_session_captured(task_id, project_id, sid)

    try:
        await run_task(
            task_id=task_id,
            prompt=prompt,
            executor=state.executor,
            client_cfg=task_cfg,
            anthropic_api_key=ANTHROPIC_API_KEY,
            on_log=_on_log,
            on_status=_on_status,
            on_done=_on_done,
            on_error=_on_error,
            on_iteration=lambda c, t: _on_iteration(task_id, c, t),
            # ask_user: блокирующая функция, которую SDK-tool вызывает чтобы
            # остановиться и дождаться ответа юзера. См. _ask_user_async выше.
            on_ask_user=_ask_user_async,
            # Модель Anthropic для этой задачи. None → orchestrator берёт
            # дефолт. Цена за токены извлекается из MODEL_PRICING по alias.
            model=model_alias,
            model_pricing=MODEL_PRICING.get(model_alias) if model_alias else None,
            # Auto-resume / session capture / phase detection / memory
            resume_session_id=resume_session_id,
            on_session_captured=_capture,
            on_phase_commit=_on_phase_commit,
            on_todos_update=_on_todos_update,  # Sprint 2 S2.7
            memory_md=memory_md,
        )
    finally:
        # Удаляем handle из реестра. asyncio.CancelledError проходит через
        # finally нормально, до этого orchestrator уже отметил ошибку.
        state.running_tasks.pop(task_id, None)
        # Подчищаем висящие вопросы (страховка — обычно их уже нет к этому моменту)
        state.pending_questions.pop(task_id, None)
        # Вычисляем итоговое состояние задачи (applied/partial/staged/failed)
        # и шлём WS-event task_state_changed, чтобы UI обновил TaskFinalStatus.
        try:
            final_state = await asyncio.to_thread(_compute_final_state, task_id)
            await asyncio.to_thread(
                _update_task_counters, task_id, final_state=final_state,
            )
            phases = await asyncio.to_thread(_list_phases, task_id)
            await _broadcast({
                "type":              "task_state_changed",
                "task_id":           task_id,
                "final_state":       final_state,
                "phases":            phases,
                "phases_committed":  sum(1 for p in phases if p["status"] == "committed"),
                "phases_total":      len(phases),
            })
        except Exception as e:
            log.warning("compute final_state failed for %s: %s", task_id, e)


# ── FastAPI ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _init_db()
    log.info("DB готова: %s", DB_PATH)

    # Загружаем config и создаём ToolExecutor локально
    cfg = load_config()
    state.client_cfg = cfg

    # Phase C: MCP registry — общий слой для всех MCP-серверов.
    # state.bsl смотрит на тот же клиент в registry (избегаем дублирующих
    # persistent sessions). Интерфейс McpHttpClient.call_tool/ensure_session
    # совместим со старым BslAtlasClient — ToolExecutor работает без правок.
    state.registry = McpServerRegistry.from_config(cfg)
    await state.registry.start_all()
    state.bsl = state.registry.get("bsl-atlas")  # type: ignore[assignment]
    if state.bsl is None:
        # Fallback на случай если bsl-atlas отключён в конфиге — старый клиент
        log.warning("bsl-atlas не в registry, создаю legacy BslAtlasClient")
        state.bsl = BslAtlasClient(cfg["bsl_atlas_url"])
    state.executor = ToolExecutor(cfg, state.bsl)

    log.info("Конфиг: extension=%s, ext_src=%s", cfg.get("extension"), cfg.get("ext_src_path"))
    log.info("BSL Atlas: %s", cfg["bsl_atlas_url"])
    log.info("MCP registry: %s", state.registry.names())

    # Лёгкая проверка доступности BSL Atlas (HTTP /health, без MCP-инициализации).
    # MCP-handshake откладываем до первого реального запроса — иначе persistent
    # session создаётся в lifespan ДО того как orchestrator её использует,
    # и порой сервер не возвращает session-id (timing-related).
    try:
        import aiohttp as _aiohttp
        url = (cfg.get("bsl_atlas_url") or "").rstrip("/")
        if url:
            async with _aiohttp.ClientSession() as _s:
                async with _s.get(f"{url}/health", timeout=_aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        log.info("✓ BSL Atlas /health: 200 OK")
                    else:
                        log.warning("⚠ BSL Atlas /health: HTTP %d", r.status)
    except Exception as e:
        log.warning("⚠ BSL Atlas не отвечает на /health: %s (агент сам ретрайт при первом вызове)", e)

    yield

    # Graceful shutdown: закрываем persistent sessions всех MCP-клиентов
    if state.registry is not None:
        try:
            await state.registry.stop_all()
            log.info("MCP registry stopped")
        except Exception as e:
            log.warning("MCP registry stop error: %s", e)


app = FastAPI(lifespan=lifespan, title="Agenter Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Раздаём frontend/ как статику
if _FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="ui")


# ── REST API ───────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    prompt: str
    project_id: str = "default"
    # Опциональный выбор модели на конкретную задачу. None = используем default
    # из client_cfg["model"] или хардкод. Список допустимых моделей: см.
    # ALLOWED_MODELS ниже. Невалидное значение → 400.
    model: str | None = None


# Перечень моделей, разрешённых для выбора через UI/API. Ключ — что приходит
# из API/UI, значение — официальный API alias модели Anthropic. Описание для
# логов и пересчёта стоимости — в MODEL_PRICING.
#
# Порядок ключей = порядок отображения в UI dropdown. Сортируем по убыванию
# мощности (Opus → Sonnet → Haiku), чтобы юзер сразу видел флагман сверху.
# Дефолт (Sonnet) остаётся помечен галочкой независимо от позиции.
ALLOWED_MODELS = {
    "opus-4-6":   "claude-opus-4-6",
    "sonnet-4-6": "claude-sonnet-4-6",
    "haiku-4-5":  "claude-haiku-4-5",
}
# Дефолт (если в запросе и в config.json модель не указана) — Sonnet остаётся
# дефолтом по балансу качество/цена, даже когда Opus стоит первым в списке.
DEFAULT_MODEL_KEY = "sonnet-4-6"

# Цены за миллион токенов (USD) — для отображения примерной стоимости.
# Источник: https://www.anthropic.com/pricing (актуально на 2026-05-15).
# in/out — обычные input/output, cache — кэшированные input (cheaper).
MODEL_PRICING = {
    "claude-sonnet-4-6": {"in": 3.00,  "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-6":   {"in": 15.00, "out": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-haiku-4-5":  {"in": 1.00,  "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
}


def _resolve_model(req_model: str | None, cfg: dict) -> str:
    """API-имя модели для SDK. Принимает короткий ключ из UI (sonnet-4-6)
    или полный alias (claude-sonnet-4-6). None → дефолт из cfg или DEFAULT_MODEL_KEY."""
    raw = (req_model or cfg.get("model")
           or os.environ.get("AGENT_DEFAULT_MODEL") or DEFAULT_MODEL_KEY).strip()
    # Короткий ключ из UI
    if raw in ALLOWED_MODELS:
        return ALLOWED_MODELS[raw]
    # Полный alias — оставляем как есть если он в нашем списке-значений
    if raw in ALLOWED_MODELS.values():
        return raw
    # Не-Claude провайдер (напр. DeepSeek через ANTHROPIC_BASE_URL) — pass-through.
    if AGENT_PROVIDER != "claude" or raw.startswith(("deepseek", "deepseek-")):
        return raw
    raise ValueError(f"Неизвестная модель: '{raw}'. Допустимые: {list(ALLOWED_MODELS.keys())}")


@app.post("/tasks")
async def create_task(req: TaskRequest):
    # Валидация модели до создания записи задачи
    try:
        model_alias = _resolve_model(req.model, state.client_cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Защита от параллельных задач в одном проекте: пока есть активная —
    # новый POST отклоняется. UI и так превращает кнопку в «Стоп», но
    # бэк-страховка нужна на случай если клик пройдёт мимо UI-state'а.
    project_id = req.project_id or "erp"
    for tid, handle in list(state.running_tasks.items()):
        if not handle.done():
            # Проверим что running task принадлежит этому проекту
            existing = await asyncio.to_thread(_get_task, tid)
            if existing and (existing.get("project_id") or "erp") == project_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"В проекте '{project_id}' уже выполняется задача {tid}. "
                        "Дождитесь её завершения или отмените."
                    ),
                )

    task_id = str(uuid.uuid4())
    await asyncio.to_thread(_create_task, task_id, req.prompt, project_id)
    # Запускаем как asyncio.Task — это даёт handle для отмены.
    # BackgroundTasks использовать нельзя — оттуда нельзя отменить.
    handle = asyncio.create_task(
        _run_task_wrapper(task_id, req.prompt, model_alias, project_id)
    )
    state.running_tasks[task_id] = handle
    return {
        "task_id": task_id,
        "status": "pending",
        "model": model_alias,
        "project_id": project_id,
    }


@app.get("/models")
async def list_models():
    """Возвращает список моделей для UI dropdown.
    Имена — короткие ключи (sonnet-4-6); alias — полное API-имя; pricing — за 1M токенов."""
    items = []
    for key, alias in ALLOWED_MODELS.items():
        price = MODEL_PRICING.get(alias, {})
        items.append({
            "key": key,
            "alias": alias,
            "label": {
                "sonnet-4-6": "Sonnet 4.6",
                "opus-4-6":   "Opus 4.6",
                "haiku-4-5":  "Haiku 4.5",
            }.get(key, key),
            "in_per_mtok":  price.get("in"),
            "out_per_mtok": price.get("out"),
        })
    return {"default": DEFAULT_MODEL_KEY, "models": items}


# ── Sessions / Phases / Rollback endpoints ─────────────────────────────────

@app.get("/sessions/{project_id}")
async def get_session_endpoint(project_id: str):
    """Текущая Claude SDK сессия проекта. UI использует для отображения
    бейджа «🔗 Контекст активен (N задач)» над composer."""
    sess = await asyncio.to_thread(_get_session, project_id)
    if sess is None:
        return {"active": False, "project_id": project_id}
    return {
        "active":         True,
        "project_id":     sess["project_id"],
        "sdk_session_id": sess["sdk_session_id"],
        "started_at":     sess["started_at"],
        "last_seen_at":   sess["last_seen_at"],
        "tasks_count":    sess["tasks_count"],
        "has_snapshot":   bool(sess.get("snapshot_path")),
    }


@app.post("/sessions/{project_id}/reset")
async def reset_session_endpoint(project_id: str):
    """Сброс сессии: следующая задача начнётся с чистого контекста (без
    resume). Удаляем sdk_session_id из БД и связанный snapshot.

    Запущенные сейчас задачи продолжают работать со своей сессией — мы
    только обнуляем «последнюю известную» для будущих POST /tasks."""
    old = await asyncio.to_thread(_reset_session, project_id)
    deleted_snapshot = False
    if old and old.get("snapshot_path"):
        deleted_snapshot = await asyncio.to_thread(
            delete_snapshot, old["snapshot_path"],
        )
    await _broadcast({
        "type":       "session_reset",
        "project_id": project_id,
    })
    return {
        "ok": True,
        "had_session": bool(old),
        "deleted_snapshot": deleted_snapshot,
    }


@app.get("/tasks/{task_id}/phases")
async def get_task_phases(task_id: str):
    """Фазы задачи с их статусами. UI использует для рендера PhasePill."""
    task = await asyncio.to_thread(_get_task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    phases = await asyncio.to_thread(_list_phases, task_id)
    return {
        "task_id":          task_id,
        "final_state":      task.get("final_state"),
        "phases_total":     task.get("phases_total") or 0,
        "phases_committed": task.get("phases_committed") or 0,
        "db_load_count":    task.get("db_load_count") or 0,
        "phases":           phases,
    }


@app.post("/tasks/{task_id}/rollback")
async def rollback_task(task_id: str):
    """Откатывает ext_src/ к состоянию из snapshot'а сессии, к которой
    принадлежит задача. БД 1С НЕ откатывается — это решает юзер вручную
    через дополнительный db_load после успешного rollback'а.

    Возвращает 409 если в проекте сейчас выполняется задача (нельзя
    откатывать на лету).
    """
    task = await asyncio.to_thread(_get_task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    project_id = task.get("project_id") or "erp"

    # Запрещаем откат при активной задаче — это вело бы к гонке за ext_src
    for tid, handle in list(state.running_tasks.items()):
        if not handle.done():
            existing = await asyncio.to_thread(_get_task, tid)
            if existing and (existing.get("project_id") or "erp") == project_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"В проекте '{project_id}' выполняется задача {tid}. "
                        "Дождитесь её завершения перед откатом."
                    ),
                )

    sess = await asyncio.to_thread(_get_session, project_id)
    snapshot_path = sess.get("snapshot_path") if sess else None
    if not snapshot_path:
        raise HTTPException(
            status_code=404,
            detail="Snapshot для отката не найден (возможно сессия была сброшена)",
        )

    ext_src = state.client_cfg.get("ext_src_path") or ""
    if not ext_src:
        raise HTTPException(
            status_code=500,
            detail="ext_src_path не настроен в client_cfg",
        )

    result = await asyncio.to_thread(restore_snapshot, snapshot_path, ext_src)
    if not result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=f"Откат провален: {result.get('error')}",
        )

    await _broadcast({
        "type":           "snapshot_restored",
        "task_id":        task_id,
        "project_id":     project_id,
        "files_restored": result.get("files_restored", 0),
    })
    return {"ok": True, "files_restored": result.get("files_restored", 0)}


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Отменяет запущенную задачу. Прерывание происходит на ближайшем
    await — обычно это вызов LLM API или PowerShell-скрипт. Текущий
    выполняющийся subprocess (например db_dump) НЕ убивается сразу,
    он дойдёт до конца, но следующий шаг не запустится."""
    handle = state.running_tasks.get(task_id)
    if handle is None:
        return {"ok": False, "message": "Задача не найдена или уже завершена"}
    if handle.done():
        return {"ok": False, "message": "Задача уже завершена"}
    # Если задача ждёт ответа юзера через ask_user — разбудим event с
    # пустым ответом ДО cancel(), чтобы tool вернул нормальный sentinel
    # вместо CancelledError из середины wait_for.
    pending = state.pending_questions.get(task_id)
    if pending is not None and not pending["event"].is_set():
        pending["answer"] = None  # None → "[CANCELLED]" в _ask_user_async
        pending["event"].set()
    handle.cancel()
    return {"ok": True}


# ── ask_user: REST endpoint для ответа от UI ───────────────────────────────

class AnswerBody(BaseModel):
    answer: str
    qid: str | None = None  # опц. — для верификации что отвечают на актуальный вопрос


@app.post("/tasks/{task_id}/answer")
async def submit_answer(task_id: str, body: AnswerBody):
    """Юзер отвечает на висящий вопрос ask_user. Разбуживает блокирующий
    tool, который сидит на event.wait() в _ask_user_async."""
    pending = state.pending_questions.get(task_id)
    if pending is None:
        return {"ok": False, "message": "Нет ожидающего вопроса для этой задачи"}
    if pending["event"].is_set():
        return {"ok": False, "message": "Ответ уже получен"}
    # Если клиент прислал qid — сверяем (защита от race condition,
    # когда UI шлёт ответ на старый вопрос после того как пришёл новый).
    if body.qid and body.qid != pending["qid"]:
        return {
            "ok": False,
            "message": f"qid не совпадает: ожидаю {pending['qid']}, получил {body.qid}",
        }
    pending["answer"] = body.answer or ""
    pending["event"].set()
    return {"ok": True}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = await asyncio.to_thread(_get_task, task_id)
    if not task:
        return {"error": "Задача не найдена"}
    return task


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "local",
        "executor_ready": state.executor is not None,
        "web_clients": len(state.web_clients),
        "mcp_servers": state.registry.names() if state.registry else [],
    }


@app.get("/mcp/status")
async def mcp_status():
    """Health-сводка по всем зарегистрированным MCP-серверам.
    Используется UI для отображения индикаторов в правой панели."""
    if state.registry is None:
        return {"servers": {}}
    summary = await state.registry.health_summary()
    return {"servers": summary}


@app.get("/desktop/status")
async def desktop_status():
    """Совместимость со старым UI. В local-режиме всегда 'connected'."""
    return {"connected": True, "mode": "local"}


@app.get("/config")
async def get_config():
    """Безопасная копия конфига для UI (без password)."""
    cfg = {k: v for k, v in state.client_cfg.items() if k != "password"}
    # Флаг "пароль сохранён" — чтобы UI понимал что поле не пустое (там просто звёздочки)
    cfg["password_set"] = bool(state.client_cfg.get("password"))
    return cfg


class ConfigUpdate(BaseModel):
    name: str = ""
    extension: str = ""
    ext_src_path: str = ""
    scheme_path: str = ""
    v8_path: str = ""
    base_path: str = ""
    username: str = ""
    password: str | None = None   # None = "не менять"; "" = очистить
    bsl_atlas_url: str = "http://localhost:8000"


@app.post("/config")
async def save_config(update: ConfigUpdate):
    """Сохраняет конфиг в config/config.json и обновляет state in-place."""
    config_file = _AGENTER_ROOT / "config" / "config.json"

    # Читаем текущий, мёрджим, пишем обратно
    current = dict(state.client_cfg)
    new_data = update.model_dump(exclude_none=False)

    # password: None означает "оставить старый", "" — очистить, иначе — заменить
    if new_data["password"] is None:
        new_data.pop("password", None)

    current.update({k: v for k, v in new_data.items() if v is not None})

    # Гарантируем что dump_script / load_script остаются (они уже в state)
    for k in ("dump_script", "load_script"):
        if k in state.client_cfg and not current.get(k):
            current[k] = state.client_cfg[k]

    # Пишем
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    # Обновляем state in-place (executor хранит ссылку на этот же dict)
    state.client_cfg.clear()
    state.client_cfg.update(current)

    # Если URL BSL Atlas изменился — пересобираем MCP registry с новым URL.
    # state.bsl смотрит на клиент внутри registry, чтобы persistent session
    # был один. Legacy BslAtlasClient тут больше не нужен.
    new_url = current.get("bsl_atlas_url", "")
    old_url = state.bsl.base_url if state.bsl else ""
    if new_url and new_url.rstrip("/") != old_url.rstrip("/"):
        try:
            if state.registry is not None:
                await state.registry.stop_all()
            state.registry = McpServerRegistry.from_config(current)
            await state.registry.start_all()
            state.bsl = state.registry.get("bsl-atlas")
            if state.executor and state.bsl is not None:
                state.executor.bsl = state.bsl
            log.info("BSL Atlas URL изменён: %s → %s", old_url, new_url)
        except Exception as e:
            log.warning("Не удалось пересоздать MCP registry: %s", e)

    log.info("Config сохранён: extension=%s, ext_src=%s",
             current.get("extension"), current.get("ext_src_path"))

    # Дополнительная проверка: пытаемся войти в 1С с новыми credentials.
    # Это занимает 10-30 секунд (запуск 1cv8.exe), но позволяет сразу
    # отловить неверный пароль / занятую базу / отсутствие прав.
    auth_check = None
    # Делаем только если все required-пути выглядят валидно (иначе бессмысленно)
    required_keys = ("v8_path", "base_path", "ext_src_path", "dump_script")
    if all(current.get(k) and Path(current.get(k, "")).exists() if k != "base_path"
           else bool(current.get(k))
           for k in required_keys):
        try:
            from ops_runner import test_1c_auth
            log.info("Проверяю авторизацию в 1С (UpdateInfo)...")
            auth_check = await test_1c_auth(current)
            log.info("Результат auth_check: ok=%s", auth_check.get("ok"))
        except Exception as e:
            log.warning("auth_check упал с исключением: %s", e)
            auth_check = {"ok": False, "message": f"Внутренняя ошибка проверки: {e}"}

    return {
        "ok": True,
        "config": {k: v for k, v in current.items() if k != "password"},
        "auth_check": auth_check,  # None если проверка не делалась, иначе {ok,message,raw?}
    }


# ── Operations (выгрузка/индексация/загрузка вне LLM-цикла) ────────────────

# Поддерживаемые операции. Каждая мапится на функцию в ops_runner.
SUPPORTED_OPS = {
    "dump-extension",
    "dump-config",
    "reindex",
    "rebuild-platform-docs",
    "rebuild-platform-docs-semantic",
    "validate-xdto",
}


def _read_op_state() -> dict:
    """Читает op_state.json, возвращает {} если файла нет."""
    if not OP_STATE_FILE.exists():
        return {}
    try:
        with open(OP_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("op_state.json чтение: %s", e)
        return {}


def _write_op_state(s: dict):
    try:
        with open(OP_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("op_state.json запись: %s", e)


def _dir_size_bytes(folder: Path) -> int:
    """Размер папки в байтах (рекурсивно). 0 если папки нет."""
    if not folder.exists():
        return 0
    total = 0
    for f in folder.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _derive_op_state() -> dict:
    """Достраивает op_state из реального состояния на диске.

    Назначение: при первом запуске (или после переустановки) op_state.json
    может быть пуст, но данные уже существуют — выгруженная конфигурация,
    индекс платформенной справки и т.д. Здесь синтезируем записи по факту
    наличия файлов и их mtime, чтобы UI сразу показывал реалистичное
    состояние, а не «никогда».

    Реальные записи (от выполненных операций) всегда побеждают синтез.
    """
    state_data = _read_op_state()
    cfg = state.client_cfg or {}

    def _file_iso_mtime(p: Path) -> str:
        try:
            return datetime.utcfromtimestamp(p.stat().st_mtime).isoformat()
        except OSError:
            return datetime.utcnow().isoformat()

    def _maybe_add(op_name: str, build_record):
        """Достраиваем запись:
        - Если в state_data её нет — синтезируем целиком, помечаем derived.
        - Если запись есть, но без `stats` (старый формат) — добиваем только stats
          из диска, сохраняя оригинальные at/ok/info. derived не ставим, потому
          что сама запись реальная (от прошлого запуска).
        """
        existing = state_data.get(op_name)
        try:
            rec = build_record()
        except Exception as e:
            log.debug("derive_op_state[%s] упало: %s", op_name, e)
            return
        if rec is None:
            return
        if existing is None:
            rec["derived"] = True
            state_data[op_name] = rec
        else:
            # Дополняем существующую запись недостающими stats (для UI).
            if not existing.get("stats") and rec.get("stats"):
                existing["stats"] = rec["stats"]

    # --- dump-extension: ext_src_path/Configuration.xml ------------------
    def _derive_dump_extension():
        ext_src = cfg.get("ext_src_path", "").strip()
        if not ext_src:
            return None
        ext_path = Path(ext_src)
        cfg_xml = ext_path / "Configuration.xml"
        if not cfg_xml.exists():
            return None
        xml_count   = sum(1 for _ in ext_path.rglob("*.xml"))
        files_count = sum(1 for _ in ext_path.rglob("*"))
        size_mb     = round(_dir_size_bytes(ext_path) / 1024 / 1024, 1)
        return {
            "at": _file_iso_mtime(cfg_xml),
            "ok": True,
            "info": f"{xml_count} XML, {files_count} файлов",
            "stats": {
                "ext_name":    cfg.get("extension", ""),
                "xml_count":   xml_count,
                "files_count": files_count,
                "size_mb":     size_mb,
                "path":        str(ext_path.resolve()),
            },
        }

    # --- dump-config: scheme_path/Configuration.xml ----------------------
    def _derive_dump_config():
        scheme = cfg.get("scheme_path", "").strip()
        if not scheme:
            return None
        sp = Path(scheme)
        cfg_xml = sp / "Configuration.xml"
        if not cfg_xml.exists():
            return None
        xml_count   = sum(1 for _ in sp.rglob("*.xml"))
        files_count = sum(1 for _ in sp.rglob("*"))
        size_mb     = round(_dir_size_bytes(sp) / 1024 / 1024, 1)
        top_folders = sum(1 for x in sp.iterdir() if x.is_dir())
        return {
            "at": _file_iso_mtime(cfg_xml),
            "ok": True,
            "info": f"{xml_count} XML-файлов, {top_folders} типов объектов",
            "stats": {
                "xml_count":    xml_count,
                "files_count":  files_count,
                "size_mb":      size_mb,
                "object_types": top_folders,
                "path":         str(sp.resolve()),
            },
        }

    # --- rebuild-platform-docs: agenter/data/platform_docs.db ------------
    def _derive_platform_docs():
        # Совпадает с platform_docs.DOCS_DB_PATH — agenter/data/platform_docs.db
        db_path = _AGENTER_ROOT / "data" / "platform_docs.db"
        if not db_path.exists():
            return None
        size_mb = round(db_path.stat().st_size / 1024 / 1024, 1)
        # Пробуем посчитать число записей через короткий SQL
        records_count = None
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute("SELECT COUNT(*) FROM docs").fetchone()
                records_count = int(row[0]) if row else None
            except sqlite3.Error:
                pass
            conn.close()
        except Exception:
            pass
        info = f"БД {size_mb} МБ"
        if records_count is not None:
            info = f"{records_count:,} записей · БД {size_mb} МБ"
        return {
            "at": _file_iso_mtime(db_path),
            "ok": True,
            "info": info,
            "stats": {
                "records_count": records_count or 0,
                "db_size_mb":    size_mb,
                "db_path":       str(db_path),
            },
        }

    # --- reindex (BSL Atlas): default-путь к индексной БД ----------------
    def _derive_reindex():
        # Дефолтный путь, заданный в инфре проекта.
        # См. CLAUDE.md: c:\BUFFER\tools\bsl-atlas-data\bsl_index.db
        db_path = Path("C:/BUFFER/tools/bsl-atlas-data/bsl_index.db")
        if not db_path.exists():
            return None
        size_mb = round(db_path.stat().st_size / 1024 / 1024, 1)
        # Если можем достучаться до BSL Atlas — запросим /health.
        # Это удорожает derive, поэтому делаем мягко (но мы уже на async-пути? нет).
        # В синхронной derive ограничимся mtime + size.
        return {
            "at": _file_iso_mtime(db_path),
            "ok": True,
            "info": f"SQLite-индекс {size_mb} МБ",
            "stats": {
                "db_size_mb": size_mb,
                "db_path":    str(db_path),
                "url":        cfg.get("bsl_atlas_url", ""),
            },
        }

    # --- rebuild-platform-docs-semantic: agenter/data/platform_docs_chroma -
    def _derive_platform_docs_semantic():
        chroma_path = _AGENTER_ROOT / "data" / "platform_docs_chroma"
        if not chroma_path.exists() or not any(chroma_path.iterdir()):
            return None
        # Размер всей папки ChromaDB
        size_bytes = _dir_size_bytes(chroma_path)
        size_mb = round(size_bytes / 1024 / 1024, 1)
        # Считаем количество записей через chromadb (если установлен)
        indexed = None
        try:
            import chromadb  # noqa: PLC0415  — local import
            client = chromadb.PersistentClient(path=str(chroma_path))
            try:
                col = client.get_collection("platform_docs")
                indexed = col.count()
            except Exception:
                pass
        except ImportError:
            pass
        info = f"ChromaDB {size_mb} МБ"
        if indexed is not None:
            info = f"{indexed:,} записей · ChromaDB {size_mb} МБ"
        # mtime последнего обновлённого файла
        last_file = max(
            (f for f in chroma_path.rglob("*") if f.is_file()),
            key=lambda f: f.stat().st_mtime,
            default=None,
        )
        return {
            "at": _file_iso_mtime(last_file) if last_file else None,
            "ok": True,
            "info": info,
            "stats": {
                "indexed":        indexed or 0,
                "chroma_size_mb": size_mb,
                "chroma_path":    str(chroma_path),
            },
        }

    _maybe_add("dump-extension",                  _derive_dump_extension)
    _maybe_add("dump-config",                     _derive_dump_config)
    _maybe_add("rebuild-platform-docs",           _derive_platform_docs)
    _maybe_add("rebuild-platform-docs-semantic",  _derive_platform_docs_semantic)
    _maybe_add("reindex",                         _derive_reindex)

    return state_data


async def _run_operation(op_name: str):
    """Запускает операцию, шлёт события в WS, обновляет op_state.json.

    Делегирует выполнение в ops_runner. Сам отвечает за событийный поток
    и сохранение состояния.
    """
    op_id = str(uuid.uuid4())
    started_at = datetime.utcnow().isoformat()
    start_ts = asyncio.get_event_loop().time()

    await _broadcast({
        "type": "op_started", "operation": op_name, "op_id": op_id, "at": started_at,
    })

    async def op_log(text: str, meta: str = ""):
        ts = datetime.utcnow().strftime("%H:%M:%S")
        await _broadcast({
            "type": "op_log", "operation": op_name, "op_id": op_id,
            "ts": ts, "text": text, "meta": meta,
        })

    try:
        from ops_runner import (
            dump_extension, dump_config, reindex_bsl_atlas,
            rebuild_platform_docs, rebuild_platform_docs_semantic,
            validate_xdto,
        )

        OP_HANDLERS = {
            "dump-extension":                  dump_extension,
            "dump-config":                     dump_config,
            "reindex":                         reindex_bsl_atlas,
            "rebuild-platform-docs":           rebuild_platform_docs,
            "rebuild-platform-docs-semantic":  rebuild_platform_docs_semantic,
            "validate-xdto":                   validate_xdto,
        }
        handler = OP_HANDLERS.get(op_name)
        if handler is None:
            raise ValueError(f"Неизвестная операция: {op_name}")

        result = await handler(state.client_cfg, op_log)
        duration = round(asyncio.get_event_loop().time() - start_ts, 1)
        info = result.get("info", "OK")
        op_stats = result.get("stats") or {}

        await op_log(f"Готово · {info}", f"{duration}с")

        s = _read_op_state()
        s[op_name] = {
            "at": datetime.utcnow().isoformat(),
            "ok": True,
            "info": info,
            "duration_sec": duration,
            # Структурированные счётчики для UI: размер БД, число записей, путь и т.п.
            # Содержимое зависит от операции — UI знает что искать (см. OpRow).
            "stats": op_stats,
        }
        _write_op_state(s)

        await _broadcast({
            "type": "op_done", "operation": op_name, "op_id": op_id,
            "info": info, "duration_sec": duration,
            "stats": op_stats,
        })

    except Exception as exc:
        err_msg = str(exc)
        log.exception("Операция %s упала", op_name)

        s = _read_op_state()
        s[op_name] = {
            "at": datetime.utcnow().isoformat(),
            "ok": False,
            "error": err_msg[:500],
        }
        _write_op_state(s)

        await _broadcast({
            "type": "op_error", "operation": op_name, "op_id": op_id,
            "error": err_msg,
        })


@app.post("/ops/{op_name}")
async def run_op(op_name: str, bg: BackgroundTasks):
    if op_name not in SUPPORTED_OPS:
        return {"ok": False, "error": f"Операция '{op_name}' не поддерживается"}
    bg.add_task(_run_operation, op_name)
    return {"ok": True, "operation": op_name}


@app.get("/ops/state")
async def get_op_state():
    """Возвращает timestamps, статусы и stats последних операций.

    Если op_state.json не содержит записи для какой-то операции, но данные
    на диске существуют (выгрузка / БД индекса), запись синтезируется по
    mtime файлов (поле `derived: true`). Это обеспечивает корректное
    отображение в UI при первом запуске или после переустановки.
    """
    return _derive_op_state()


# ── Метаданные конфигурации 1С ──────────────────────────────────────────────
#
# Используют пакет metadata_utils (порт из MetadataViewer1C):
#   /metadata/tree          — лёгкое дерево (типы + объекты, без members)
#   /metadata/tree/stream   — SSE-стрим: один event = один тип целиком
#   /metadata/object        — детальная инфа об объекте (с members)
#   /metadata/invalidate    — POST для сброса кэша после db-dump-xml

def _get_metadata_repo() -> MetadataRepository:
    """Lazy-init глобального репозитория метаданных."""
    if state.metadata_repo is None:
        state.metadata_repo = MetadataRepository(ttl_seconds=600.0, max_workers=8)
    return state.metadata_repo


def _resolve_metadata_root(root: str | None) -> Path:
    """По умолчанию берётся scheme_path из конфига."""
    if root:
        return Path(root)
    cfg_root = state.client_cfg.get("scheme_path")
    if not cfg_root:
        raise HTTPException(status_code=400, detail="Не задан scheme_path в конфиге")
    return Path(cfg_root)


def _slim_tree(node: MetadataTreeNode) -> dict:
    """Возвращает облегчённое представление узла дерева — без member.properties.

    Для UI достаточно структуры (label, kind, icon) и счётчиков объектов.
    Полные свойства приходят через /metadata/object.
    """
    children = [_slim_tree(c) for c in node.children] if node.children else []
    info: dict = {
        "id": node.id,
        "label": node.label,
        "kind": node.kind,
        "icon": node.icon,
    }
    if children:
        info["children"] = children
    if node.object is not None:
        info["object"] = {
            "type": node.object.object_type,
            "type_dir": node.object.object_type_dir,
            "name": node.object.name,
            "display_name": node.object.display_name,
            "n_attributes": node.object.n_attributes,
            "n_tabular_sections": node.object.n_tabular_sections,
            "n_forms": node.object.n_forms,
            "n_commands": node.object.n_commands,
            "n_templates": node.object.n_templates,
            "n_predefined": node.object.n_predefined,
        }
    if node.member is not None:
        info["member"] = {
            "kind": node.member.kind,
            "name": node.member.name,
        }
    return info


@app.get("/metadata/tree")
async def metadata_tree(root: str | None = None, slim: bool = True):
    """Полное дерево метаданных конфигурации 1С.

    По умолчанию возвращает облегчённое представление (slim=true) — без
    свойств членов. Для деталей конкретного объекта используйте /metadata/object.

    На холодной загрузке для ERP-конфигурации это занимает ~45 секунд.
    Для прогрессивной загрузки используйте /metadata/tree/stream.
    """
    repo = _get_metadata_repo()
    root_path = _resolve_metadata_root(root)
    if not root_path.exists():
        raise HTTPException(status_code=404, detail=f"Root not found: {root_path}")

    result = await repo.load(root_path)
    tree: MetadataTreeNode = result["tree"]
    if slim:
        return {
            "tree": _slim_tree(tree),
            "errors": result["errors"][:50],
            "cached": result.get("cached", False),
            "root": str(root_path),
        }
    return {
        "tree": tree.model_dump(),
        "errors": result["errors"][:50],
        "cached": result.get("cached", False),
        "root": str(root_path),
    }


@app.get("/metadata/tree/stream")
async def metadata_tree_stream(root: str | None = None):
    """SSE-стрим прогрессивной загрузки дерева.

    Поток событий:
        event: start         — начало загрузки
        event: type-loaded   — один тип со всеми объектами (slim)
        event: done          — конец загрузки + errors
        event: error         — фатальная ошибка
    """
    repo = _get_metadata_repo()
    root_path = _resolve_metadata_root(root)
    if not root_path.exists():
        raise HTTPException(status_code=404, detail=f"Root not found: {root_path}")

    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def producer():
        async def on_type_loaded(type_node: MetadataTreeNode) -> None:
            await queue.put(("type-loaded", _slim_tree(type_node)))

        try:
            await queue.put(("start", {"root": str(root_path)}))
            result = await repo.load_progressive(root_path, on_type_loaded)
            await queue.put((
                "done",
                {
                    "errors": result["errors"][:50],
                    "cached": result.get("cached", False),
                    "n_objects": len(result["objects"]),
                },
            ))
        except Exception as e:  # noqa: BLE001
            log.exception("metadata tree stream failed")
            await queue.put(("error", {"message": str(e)}))
        finally:
            await queue.put(None)  # sentinel

    async def event_generator():
        producer_task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\n"
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            if not producer_task.done():
                producer_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/metadata/object")
async def metadata_object(key: str, root: str | None = None):
    """Полная инфа об одном объекте (с members).

    key — стабильный ключ вида "Catalogs/Номенклатура" или "Documents/РеализацияТоваровУслуг".
    """
    repo = _get_metadata_repo()
    root_path = _resolve_metadata_root(root)
    result = await repo.load(root_path)
    tree: MetadataTreeNode = result["tree"]

    # Ищем в дереве
    for type_node in tree.children:
        if type_node.kind != "type":
            continue
        for obj_node in type_node.children:
            if obj_node.id == key:
                return obj_node.model_dump()
    raise HTTPException(status_code=404, detail=f"Object not found: {key}")


@app.post("/metadata/invalidate")
async def metadata_invalidate(root: str | None = None):
    """Сбрасывает кэш метаданных. Вызывайте после db-dump-xml."""
    if state.metadata_repo is None:
        return {"ok": True, "note": "no cache yet"}
    state.metadata_repo.invalidate(root)
    return {"ok": True, "root": root or "all"}


@app.get("/config/check")
async def check_config():
    """Проверяет валидность путей в текущем конфиге. Используется мастером настройки."""
    cfg = state.client_cfg
    checks: dict[str, dict] = {}

    # --- v8_path ---
    v8 = cfg.get("v8_path", "").strip()
    if not v8:
        checks["v8_path"] = {"ok": False, "message": "Не задан"}
    else:
        p = Path(v8)
        if not p.exists():
            checks["v8_path"] = {"ok": False, "message": "Папка не существует"}
        elif not (p / "1cv8.exe").exists():
            checks["v8_path"] = {"ok": False, "message": "1cv8.exe не найден в этой папке"}
        else:
            checks["v8_path"] = {"ok": True, "message": "1cv8.exe найден"}

    # --- base_path ---
    bp = cfg.get("base_path", "").strip()
    if not bp:
        checks["base_path"] = {"ok": False, "message": "Не задан"}
    elif "Srvr=" in bp:
        checks["base_path"] = {"ok": True, "message": "Серверная база"}
    elif Path(bp).exists():
        checks["base_path"] = {"ok": True, "message": "Файловая база найдена"}
    else:
        checks["base_path"] = {"ok": False, "message": "Путь не существует"}

    # --- ext_src_path ---
    ext = cfg.get("ext_src_path", "").strip()
    if not ext:
        checks["ext_src_path"] = {"ok": False, "message": "Не задан"}
    else:
        p = Path(ext)
        if not p.exists():
            checks["ext_src_path"] = {"ok": False, "message": "Папка не существует"}
        else:
            xml_count = sum(1 for _ in p.rglob("*.xml"))
            cfg_xml = p / "Configuration.xml"
            if cfg_xml.exists():
                checks["ext_src_path"] = {"ok": True, "message": f"{xml_count} XML, Configuration.xml есть"}
            else:
                checks["ext_src_path"] = {"ok": True, "message": f"{xml_count} XML, пусто или не выгружено"}

    # --- scheme_path (опциональный) ---
    sch = cfg.get("scheme_path", "").strip()
    if not sch:
        checks["scheme_path"] = {"ok": True, "message": "Не задан (опционально)"}
    else:
        p = Path(sch)
        if not p.exists():
            checks["scheme_path"] = {"ok": False, "message": "Папка не существует"}
        else:
            cfg_xml = p / "Configuration.xml"
            if cfg_xml.exists():
                checks["scheme_path"] = {"ok": True, "message": "Configuration.xml найден"}
            else:
                checks["scheme_path"] = {"ok": False, "message": "Configuration.xml не найден (не похоже на SCHEME)"}

    # --- extension ---
    ext_name = cfg.get("extension", "").strip()
    if not ext_name:
        checks["extension"] = {"ok": False, "message": "Не задано"}
    else:
        checks["extension"] = {"ok": True, "message": "OK"}

    # --- bsl_atlas_url (опциональный, но желательный) ---
    url = cfg.get("bsl_atlas_url", "").strip()
    if not url:
        checks["bsl_atlas_url"] = {"ok": True, "message": "Не задан (поиск отключён)"}
    else:
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(f"{url.rstrip('/')}/health") as r:
                    if r.status == 200:
                        data = await r.json()
                        sqlite_info = data.get("sqlite", {})
                        objects = sqlite_info.get("objects", "?")
                        checks["bsl_atlas_url"] = {"ok": True, "message": f"OK · {objects} объектов в индексе"}
                    else:
                        checks["bsl_atlas_url"] = {"ok": False, "message": f"HTTP {r.status}"}
        except Exception as e:
            checks["bsl_atlas_url"] = {"ok": False, "message": "Не отвечает — запусти C:\\BUFFER\\tools\\bsl-atlas\\start.bat"}

    # --- скрипты (technical, обычно ok) ---
    for key, label in [("dump_script", "Скрипт выгрузки"), ("load_script", "Скрипт загрузки")]:
        sp = cfg.get(key, "").strip()
        if not sp:
            checks[key] = {"ok": False, "message": "Не задан"}
        elif Path(sp).exists():
            checks[key] = {"ok": True, "message": "OK"}
        else:
            checks[key] = {"ok": False, "message": "Файл не найден"}

    required = ["v8_path", "base_path", "ext_src_path", "extension", "dump_script", "load_script"]
    all_required_ok = all(checks.get(k, {}).get("ok") for k in required)

    return {
        "checks": checks,
        "all_required_ok": all_required_ok,
        "required_fields": required,
    }


# ── WebSocket: UI слушает события ──────────────────────────────────────────

@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    state.web_clients.add(ws)
    # Сразу сигналим что готовы (для совместимости со старым обработчиком desktop_status)
    await ws.send_json({"type": "desktop_status", "status": "online", "mode": "local"})

    try:
        while True:
            await ws.receive_text()  # держим соединение
    except WebSocketDisconnect:
        pass
    finally:
        state.web_clients.discard(ws)


# ── Запуск: uvicorn в фоновом потоке + PyWebView в основном ────────────────

HOST = "127.0.0.1"
PORT = 8080
URL  = f"http://{HOST}:{PORT}/ui/app.html"

# BSL Atlas — отдельный Python-процесс. Запускаем его сами как child, чтобы
# при закрытии Agenter он закрылся вместе с нами. Если он уже запущен извне —
# не трогаем, не убиваем при выходе.
BSL_ATLAS_DIR_DEFAULT = Path("C:/BUFFER/tools/bsl-atlas")

# Выделенный порт продукта Agenter для BSL Atlas. :8000 был выбран ранее,
# но он слишком популярен и часто занят (FastAPI dev-серверы, торговые боты,
# дашборды). :8765 — наш фиксированный выбор. Если требуется поменять —
# одновременно правится в:
#   - agenter/config/config.json::bsl_atlas_url
#   - C:/BUFFER/tools/bsl-atlas/.env::PORT
BSL_ATLAS_DEFAULT_PORT = 8765

# Глобальный handle нашего BSL Atlas процесса (None если мы его не запускали)
_bsl_proc: subprocess.Popen | None = None


class BslAtlasPortConflictError(RuntimeError):
    """Порт BSL Atlas занят сторонним процессом. Фатальная ошибка старта."""
    pass


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """True если кто-то слушает на host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bsl_atlas_endpoint() -> tuple[str, int]:
    """Достаёт host/port BSL Atlas из конфига (с дефолтом BSL_ATLAS_DEFAULT_PORT)."""
    cfg_url = (
        state.client_cfg.get("bsl_atlas_url")
        or f"http://localhost:{BSL_ATLAS_DEFAULT_PORT}"
    )
    parsed = urlparse(cfg_url)
    return parsed.hostname or "localhost", parsed.port or BSL_ATLAS_DEFAULT_PORT


def _identify_port_holder(port: int) -> tuple[int, str] | None:
    """Возвращает (pid, имя_процесса) для процесса, слушающего port на localhost.
    Если определить не удалось — возвращает None. Windows-only через netstat+tasklist;
    на не-Windows возвращает None (тогда сообщение об ошибке будет без PID).
    """
    if sys.platform != "win32":
        return None
    try:
        netstat = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True,
            encoding="cp866", errors="ignore",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    needle_v4 = f"127.0.0.1:{port}"
    needle_v6 = f"[::1]:{port}"
    pid: int | None = None
    for line in (netstat.stdout or "").splitlines():
        if "LISTENING" not in line:
            continue
        if needle_v4 not in line and needle_v6 not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
            break
        except ValueError:
            continue
    if pid is None:
        return None

    # Получаем имя процесса через tasklist
    name = "<unknown>"
    try:
        tl = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
            encoding="cp866", errors="ignore",
            timeout=5,
        )
        first_line = (tl.stdout or "").strip().splitlines()
        if first_line:
            # CSV формат: "Image Name","PID","Session Name","Session#","Mem Usage"
            cells = [c.strip().strip('"') for c in first_line[0].split(",")]
            if cells and cells[0] and not cells[0].lower().startswith("info"):
                name = cells[0]
    except (OSError, subprocess.TimeoutExpired):
        pass

    return pid, name


def _looks_like_bsl_atlas(host: str, port: int, timeout: float = 1.5) -> bool:
    """Проверяет что на host:port слушает именно BSL Atlas, а не случайный
    сервис. Реальный BSL Atlas отвечает на GET /health JSON-документом
    с ключом 'sqlite' или 'status'. Любой другой ответ (404, HTML, JSON
    без этих ключей) считается «не BSL Atlas».

    Используется при старте, чтобы не путать BSL Atlas с чужими сервисами,
    которые случайно заняли тот же порт.
    """
    import http.client as _httpc
    try:
        conn = _httpc.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            return False
        body = resp.read(2048).decode("utf-8", errors="ignore")
        conn.close()
    except OSError:
        return False
    # Простая эвристика: должен быть JSON с упоминанием sqlite/chroma или status:ok
    if not body.startswith("{"):
        return False
    lowered = body.lower()
    markers = ("sqlite", "chroma", "bsl_index", "indexer")
    return any(m in lowered for m in markers)


def start_bsl_atlas():
    """Запускает BSL Atlas как дочерний процесс.

    Логика:
    - Если порт открыт И на /health отвечает реальный BSL Atlas → используем его
      (например, пользователь запустил его сам через start.bat).
    - Если порт открыт, но это другой сервис → бросаем BslAtlasPortConflictError.
      Agenter должен прекратить запуск и показать диалог пользователю.
    - Если порт свободен → запускаем свой.
    """
    global _bsl_proc

    host, port = _bsl_atlas_endpoint()
    if _is_port_open(host, port, timeout=0.5):
        if _looks_like_bsl_atlas(host, port):
            log.info("BSL Atlas уже работает на %s:%s — использую существующий", host, port)
            return
        # Порт занят сторонним сервисом — это фатально.
        holder = _identify_port_holder(port)
        if holder:
            pid, name = holder
            who = f"PID {pid} ({name})"
        else:
            who = "(процесс определить не удалось — попробуй `netstat -ano | findstr :%d`)" % port
        raise BslAtlasPortConflictError(
            f"Порт {host}:{port} занят другим сервисом — {who}.\n"
            f"\n"
            f"Agenter использует порт :{BSL_ATLAS_DEFAULT_PORT} для BSL Atlas — "
            f"локального индекса конфигурации 1С. Запуск без него невозможен.\n"
            f"\n"
            f"Что сделать:\n"
            f"  1) Закрой процесс {who}\n"
            f"     (Диспетчер задач → найди по PID → Снять задачу), либо\n"
            f"  2) Перенастрой Agenter на другой порт:\n"
            f"     • открой agenter\\config\\config.json\n"
            f"     • замени bsl_atlas_url на http://localhost:18765 (например)\n"
            f"     • открой C:\\BUFFER\\tools\\bsl-atlas\\.env\n"
            f"     • замени PORT=8765 на PORT=18765\n"
            f"\n"
            f"После этого запусти Agenter заново."
        )

    bsl_dir = BSL_ATLAS_DIR_DEFAULT
    bsl_python = bsl_dir / "venv" / "Scripts" / "python.exe"

    if not bsl_python.exists():
        log.warning(
            "BSL Atlas Python не найден: %s — пропускаю автозапуск. "
            "Запусти BSL Atlas вручную через %s",
            bsl_python, bsl_dir / "start.bat",
        )
        return

    log.info("Запускаю BSL Atlas: %s -m src.main", bsl_python)

    creationflags = 0
    if sys.platform == "win32":
        # NEW_PROCESS_GROUP — чтобы Ctrl+C в нашей консоли не убил его раньше времени
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        _bsl_proc = subprocess.Popen(
            [str(bsl_python), "-m", "src.main"],
            cwd=str(bsl_dir),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.error("Не удалось запустить BSL Atlas: %s", e)
        return

    # Ждём пока порт откроется (старт ~3–15 сек)
    deadline = time.time() + 60
    while time.time() < deadline:
        if _bsl_proc.poll() is not None:
            log.error("BSL Atlas упал сразу после запуска (exit code %s)", _bsl_proc.returncode)
            _bsl_proc = None
            return
        if _is_port_open(host, port, timeout=0.3):
            log.info("✓ BSL Atlas стартовал (PID %s)", _bsl_proc.pid)
            return
        time.sleep(0.5)

    log.warning("BSL Atlas не открыл порт за 60 секунд — продолжаю, но индексация может ещё идти")


def stop_bsl_atlas():
    """Аккуратно останавливает наш BSL Atlas. Идемпотентно."""
    global _bsl_proc
    if _bsl_proc is None:
        return

    proc = _bsl_proc
    _bsl_proc = None

    if proc.poll() is not None:
        log.info("BSL Atlas уже завершён")
        return

    log.info("Останавливаю BSL Atlas (PID %s)...", proc.pid)
    try:
        if sys.platform == "win32":
            # taskkill /F /T убивает дерево процессов — на случай если BSL Atlas
            # породил кого-то ещё (worker, indexer и т.п.)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.info("BSL Atlas остановлен")
    except Exception as e:
        log.warning("Ошибка при остановке BSL Atlas: %s", e)


def _run_server():
    """Uvicorn запускается в отдельном потоке. PyWebView требует основной поток."""
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", access_log=False)


def _show_fatal_dialog(title: str, message: str) -> None:
    """Показывает нативный диалог с ошибкой ДО открытия webview-окна.

    На Windows используется MessageBoxW (ctypes), на других ОС — печатаем
    в stderr и тем самым полагаемся, что пользователь запускал Agenter
    из консоли и увидит сообщение.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            # MB_ICONERROR (0x10) + MB_OK (0x0) + MB_SYSTEMMODAL (0x1000) —
            # модальный диалог поверх всех окон, чтобы пользователь точно увидел.
            MB_ICONERROR = 0x10
            MB_OK = 0x0
            MB_SYSTEMMODAL = 0x1000
            ctypes.windll.user32.MessageBoxW(
                0, message, title,
                MB_OK | MB_ICONERROR | MB_SYSTEMMODAL,
            )
            return
        except Exception as e:
            log.error("MessageBoxW не сработал: %s", e)
    # Fallback — stderr
    sys.stderr.write(f"\n=== {title} ===\n{message}\n")
    sys.stderr.flush()


def main():
    log.info("Agenter Local · запуск")

    # Регистрируем cleanup сразу — даже если упадём на следующих шагах,
    # дочерние процессы будут убраны при выходе Python.
    atexit.register(stop_bsl_atlas)

    # ── Шаг 1/3: BSL Atlas (зависимость) ──────────────────────────────────
    log.info("Шаг 1/3 · BSL Atlas")
    try:
        start_bsl_atlas()
    except BslAtlasPortConflictError as e:
        # Фатальная ошибка старта: порт занят сторонним процессом.
        # Показываем нативный MessageBox и прекращаем запуск (UI не открываем).
        msg = str(e)
        log.error("Конфликт порта BSL Atlas:\n%s", msg)
        _show_fatal_dialog("Agenter — конфликт порта", msg)
        return  # выход из main(), atexit разрулит cleanup

    # ── Шаг 2/3: FastAPI (наш backend) ────────────────────────────────────
    log.info("Шаг 2/3 · FastAPI на %s", URL)
    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        if _is_port_open(HOST, PORT, timeout=0.3):
            break
        time.sleep(0.15)
    else:
        log.error("Uvicorn не поднялся за 10 секунд")
        stop_bsl_atlas()
        return

    # ── Шаг 3/3: PyWebView (окно UI) ──────────────────────────────────────
    log.info("Шаг 3/3 · PyWebView")
    try:
        import webview
    except ImportError:
        log.error("PyWebView не установлен. pip install -r requirements.txt")
        log.info("UI доступен в браузере: %s", URL)
        log.info("Нажми Ctrl+C для завершения (BSL Atlas будет остановлен)")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            stop_bsl_atlas()
        return

    webview.create_window(
        title="Agenter",
        url=URL,
        width=1440,
        height=900,
        min_size=(1100, 700),
        resizable=True,
    )
    try:
        webview.start()  # блокирует до закрытия окна
    finally:
        log.info("Окно закрыто, останавливаю зависимости")
        stop_bsl_atlas()
        log.info("Agenter завершён")


if __name__ == "__main__":
    main()
