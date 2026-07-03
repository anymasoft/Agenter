"""Структурированная трассировка прогона агента (Agenter) — Фаза 1.

Слой наблюдаемости поверх существующего пайплайна. НЕ заменяет UI-поток
(`_on_log` → WS/SQLite), а даёт второй, машиночитаемый источник истины:
один NDJSON-файл на прогон в `logs/runs/<run_id>.ndjson`.

Ключевые свойства (по требованиям архитектора, Фаза 1):
  • run_id := task_id (свой идентификатор не вводим).
  • Контролируемый словарь event_type; обязательная reason на финале.
  • Финализация ТОЛЬКО через одну точку — RunTrace.finish_run(reason, ...).
    Первый вызов выигрывает (идемпотентно). Catch-all (run_scope) гарантирует,
    что прогон без явного финала закрывается reason="unknown-crash" — тишины нет.
  • Запись неблокирующая: отдельный поток-писатель + очередь. Каждая строка
    flush'ится; на финале файл fsync'ится и очередь дренится — краш не проглотит
    буфер.
  • Редакция секретов на границе трейсера (ключи .env, Authorization, sk-…).
  • seq — монотонный порядок внутри прогона (ts на мс могут совпасть при async).
  • Стоимость считается по effective-модели/провайдеру (вкл. DeepSeek), не по
    Claude-таблице.

Этот модуль самодостаточен (только stdlib) и в Фазе 1 НЕ подключён к пайплайну —
инструментирование (Фаза 2) расставит вызовы в main.py/orchestrator_sdk.py.
Самопроверка: `python -m app.run_trace` сгенерирует демо-трейсы в logs/runs/.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import queue
import re
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# ── Контролируемые словари ───────────────────────────────────────────────────

EVENT_TYPES: frozenset[str] = frozenset({
    "run_start", "plan", "system_prompt", "stage_enter", "stage_exit",
    "llm_call", "tool_call", "guard", "error", "decision",
    "loop_suspected", "run_end",
})

# Причины финала. unknown-crash — для catch-all (исключение/timeout/обрыв).
# max-iterations / max-tokens — заполнит Фаза 3 через ту же finish_run().
RUN_END_REASONS: frozenset[str] = frozenset({
    "success", "blocked-by-guard", "external-error", "ask_user-pause",
    "max-iterations", "max-tokens", "model-error", "unknown-crash",
})

LEVELS: frozenset[str] = frozenset({"TRACE", "DEBUG", "INFO", "WARN", "ERROR"})
_LEVEL_ORDER = {"TRACE": 10, "DEBUG": 20, "INFO": 30, "WARN": 40, "ERROR": 50}

# ── Прайсинг ($ за 1M токенов) по effective-модели ───────────────────────────
# Считаем по тому, что РЕАЛЬНО ушло в SDK (provider/effective_model), а не по
# имени из UI-дропдауна. DeepSeek-цены — из официальной документации; cache_read
# для DeepSeek — оценочно (cache-hit), уточняемо.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6":   {"in": 15.00, "out": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6": {"in": 3.00,  "out": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5":  {"in": 1.00,  "out": 5.00,  "cache_read": 0.10},
    "deepseek-v4-flash": {"in": 0.14,  "out": 0.28,  "cache_read": 0.014},
    "deepseek-v4-pro":   {"in": 0.435, "out": 0.87,  "cache_read": 0.0435},
}


def _match_pricing(effective_model: Optional[str]) -> Optional[dict[str, float]]:
    if not effective_model:
        return None
    m = effective_model.strip().lower()
    if m in PRICING:
        return PRICING[m]
    # префиксное совпадение (на случай суффиксов/датированных имён)
    for key, val in PRICING.items():
        if m.startswith(key) or key.startswith(m):
            return val
    return None


def calc_cost(effective_model: Optional[str], tokens_in: int = 0,
              tokens_out: int = 0, tokens_cache: int = 0) -> Optional[float]:
    """Стоимость turn'а по effective-модели. None — если прайс неизвестен
    (тогда трейс честно пишет cost отсутствующим, а не нулём по чужому прайсу)."""
    p = _match_pricing(effective_model)
    if not p:
        return None
    cost = (
        (tokens_in or 0) / 1e6 * p["in"]
        + (tokens_out or 0) / 1e6 * p["out"]
        + (tokens_cache or 0) / 1e6 * p.get("cache_read", 0.0)
    )
    return round(cost, 6)


# ── Редакция секретов ────────────────────────────────────────────────────────

_SK_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.I)
_REDACTED = "***REDACTED***"


def _is_secret_key(k: str) -> bool:
    """True для ключей, чьи ЗНАЧЕНИЯ нельзя писать. Намеренно НЕ ловит
    input_tokens/output_tokens/tokens_in (иначе затрём счётчики токенов)."""
    kl = k.lower()
    if kl in ("authorization", "x-api-key", "bearer", "password", "passwd"):
        return True
    if "api_key" in kl or "apikey" in kl or "client_secret" in kl:
        return True
    if "secret" in kl:
        return True
    if kl.endswith("_token") or kl == "token":  # access_token, refresh_token
        return True
    return False


def _make_redactor(extra_secrets: Optional[set[str]] = None) -> Callable[[Any], Any]:
    """Строит функцию редакции. literals — точные значения секретов из env
    (значения .env-ключей), маскируются в ЛЮБОЙ строке payload."""
    literals: set[str] = set(extra_secrets or set())
    for k, v in os.environ.items():
        if v and len(v) >= 8 and _is_secret_key(k):
            literals.add(v)
    ordered = sorted(literals, key=len, reverse=True)

    def redact_str(s: str) -> str:
        for lit in ordered:
            if lit and lit in s:
                s = s.replace(lit, _REDACTED)
        s = _SK_RE.sub(_REDACTED, s)
        s = _BEARER_RE.sub("Bearer " + _REDACTED, s)
        return s

    def redact(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[Any, Any] = {}
            for k, v in obj.items():
                if isinstance(k, str) and _is_secret_key(k):
                    out[k] = _REDACTED
                else:
                    out[k] = redact(v)
            return out
        if isinstance(obj, (list, tuple)):
            return [redact(x) for x in obj]
        if isinstance(obj, str):
            return redact_str(obj)
        return obj

    return redact


# ── Фоновой писатель (один поток на процесс) ─────────────────────────────────

class _Writer:
    """Неблокирующий NDJSON-писатель. emit() кладёт строку в очередь (никогда
    не блокирует event loop), демон-поток пишет+flush'ит. На close — fsync."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[str, Optional[str], bool]]" = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="run-trace-writer", daemon=True
        )
        self._handles: dict[str, Any] = {}
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if not self._started:
                self._thread.start()
                self._started = True

    def submit(self, path: str, line: Optional[str], close: bool = False) -> None:
        self._q.put((path, line, close))

    def drain(self) -> None:
        """Блокирует ВЫЗЫВАЮЩИЙ поток до опустошения очереди. Использовать
        только на финале (редко) — в async-пайплайне обернуть в to_thread."""
        self._q.join()

    def _run(self) -> None:
        while True:
            path, line, close = self._q.get()
            try:
                fh = self._handles.get(path)
                if line is not None:
                    if fh is None:
                        Path(path).parent.mkdir(parents=True, exist_ok=True)
                        fh = open(path, "a", encoding="utf-8")
                        self._handles[path] = fh
                    fh.write(line)
                    fh.write("\n")
                    fh.flush()  # из Python-буфера в ОС — краш интерпретатора не съест
                if close and fh is not None:
                    try:
                        fh.flush()
                        os.fsync(fh.fileno())  # durability на финале
                    finally:
                        fh.close()
                        self._handles.pop(path, None)
            except Exception:
                # трассировка не должна ронять прогон
                pass
            finally:
                self._q.task_done()


# ── Трейс одного прогона ─────────────────────────────────────────────────────

class RunTrace:
    """Трассировка одного прогона. run_id := task_id. Потокобезопасна по seq."""

    def __init__(self, writer: _Writer, run_id: str, root: Path,
                 redactor: Callable[[Any], Any], *, min_level: str = "TRACE") -> None:
        self._writer = writer
        self.run_id = run_id
        self.path = str(root / "runs" / f"{run_id}.ndjson")
        self._redact = redactor
        self._min = _LEVEL_ORDER.get(min_level, 10)
        self._seq = itertools.count(0)
        self._span_ctr = itertools.count(1)
        self._span_stack: list[str] = []
        self._lock = threading.Lock()
        self._finished = False
        self._stage: Optional[str] = None
        self._iteration: Optional[int] = None
        self.system_prompt_hash: Optional[str] = None
        self.effective_model: Optional[str] = None

    # — служебное —
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def set_stage(self, stage: Optional[str]) -> None:
        self._stage = stage

    def set_iteration(self, iteration: Optional[int]) -> None:
        self._iteration = iteration

    # — базовая эмиссия события —
    def emit(self, event_type: str, payload: Optional[dict] = None, *,
             level: str = "INFO", stage: Optional[str] = None,
             iteration: Optional[int] = None, span_id: Optional[str] = None,
             parent_span_id: Optional[str] = None, status: Optional[str] = None,
             reason: Optional[str] = None, tokens_in: Optional[int] = None,
             tokens_out: Optional[int] = None, tokens_cache: Optional[int] = None,
             cost: Optional[float] = None, duration_ms: Optional[int] = None) -> Optional[dict]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"run_trace: неизвестный event_type {event_type!r}")
        if _LEVEL_ORDER.get(level, 30) < self._min:
            return None
        with self._lock:
            seq = next(self._seq)
        cur_span = span_id if span_id is not None else (
            self._span_stack[-1] if self._span_stack else None)
        cur_parent = parent_span_id if parent_span_id is not None else (
            self._span_stack[-2] if len(self._span_stack) >= 2 else None)
        ev: dict[str, Any] = {
            "run_id": self.run_id,
            "seq": seq,
            "span_id": cur_span,
            "parent_span_id": cur_parent,
            "ts": self._now(),
            "event_type": event_type,
            "stage": stage if stage is not None else self._stage,
            "iteration": iteration if iteration is not None else self._iteration,
            "level": level,
            "payload": self._redact(payload or {}),
        }
        # необязательные метрики — только когда заданы (трейс не засоряем null'ами)
        for key, val in (("tokens_in", tokens_in), ("tokens_out", tokens_out),
                         ("tokens_cache", tokens_cache), ("cost", cost),
                         ("duration_ms", duration_ms), ("status", status),
                         ("reason", reason)):
            if val is not None:
                ev[key] = val
        self._writer.submit(self.path, json.dumps(ev, ensure_ascii=False))
        return ev

    # — жизненный цикл —
    def start_run(self, *, prompt: str, selected_model: Optional[str],
                  effective_model: Optional[str], provider: str,
                  config_snapshot: Optional[dict] = None,
                  system_prompt: Optional[str] = None) -> None:
        """Старт прогона. Фиксирует ОБЕ модели (selected из UI vs effective в SDK),
        провайдера, снимок конфига. Системный промпт пишется один раз: полностью
        (TRACE) + хеш — последующие llm_call ссылаются на хеш, не дублируют."""
        self.effective_model = effective_model
        sp_hash = None
        if system_prompt is not None:
            sp_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]
            self.system_prompt_hash = sp_hash
        self.emit("run_start", {
            "prompt": prompt,
            "selected_model": selected_model,
            "effective_model": effective_model,
            "model_divergence": bool(selected_model and effective_model
                                     and selected_model != effective_model),
            "provider": provider,
            "config": config_snapshot or {},
            "system_prompt_hash": sp_hash,
        }, level="INFO")
        if system_prompt is not None:
            self.emit("system_prompt", {"hash": sp_hash, "text": system_prompt},
                      level="TRACE")

    def llm_call(self, *, delta_messages: Any, response: Any,
                 tokens_in: int = 0, tokens_out: int = 0, tokens_cache: int = 0,
                 duration_ms: Optional[int] = None,
                 cumulative_tokens: Optional[dict] = None) -> None:
        """Один виток LLM. payload — ДЕЛЬТА (новые сообщения витка) + ответ
        целиком, НЕ вся растущая история (иначе квадратичный рост трейса;
        полная история восстановима из дельт). cost — по effective-модели."""
        cost = calc_cost(self.effective_model, tokens_in, tokens_out, tokens_cache)
        self.emit("llm_call", {
            "delta": delta_messages,
            "response": response,
            "system_prompt_hash": self.system_prompt_hash,
            "cumulative_tokens": cumulative_tokens,
        }, level="DEBUG", tokens_in=tokens_in, tokens_out=tokens_out,
            tokens_cache=tokens_cache, cost=cost, duration_ms=duration_ms)

    def finish_run(self, reason: str, *, status: Optional[str] = None,
                   summary: Optional[dict] = None) -> bool:
        """ЕДИНСТВЕННАЯ точка завершения прогона. Идемпотентна: первый вызов
        выигрывает (явный финал пайплайна перебивает catch-all). Гарантирует
        запись run_end + fsync файла + дренаж очереди — на ЛЮБОМ пути финала.

        Возвращает True, если этот вызов реально закрыл прогон; False — если
        прогон уже был закрыт (вызов проигнорирован)."""
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        summary = dict(summary or {})
        if reason not in RUN_END_REASONS:
            # никогда не теряем причину молча — фиксируем некорректную и коэрсим
            summary["_invalid_reason"] = reason
            reason = "unknown-crash"
        self.emit("run_end", summary, level="INFO",
                  reason=reason, status=status or reason)
        # durability: закрыть+fsync файл прогона и дождаться опустошения очереди
        self._writer.submit(self.path, None, close=True)
        self._writer.drain()
        _write_latest_pointer(Path(self.path).parent, self.run_id, reason)
        return True

    # — спаны (вложенность) —
    @contextmanager
    def span(self, name: str, *, event_type: str = "decision",
             level: str = "DEBUG", **kw: Any) -> Iterator[str]:
        sid = f"sp{next(self._span_ctr)}"
        parent = self._span_stack[-1] if self._span_stack else None
        self._span_stack.append(sid)
        t0 = time.monotonic()
        self.emit(event_type, {"span": name, "phase": "enter", **kw},
                  level=level, span_id=sid, parent_span_id=parent)
        try:
            yield sid
        finally:
            dur = int((time.monotonic() - t0) * 1000)
            self.emit(event_type, {"span": name, "phase": "exit"},
                      level=level, span_id=sid, parent_span_id=parent,
                      duration_ms=dur)
            self._span_stack.pop()


# ── Указатель на последний прогон ────────────────────────────────────────────

def _write_latest_pointer(runs_dir: Path, run_id: str, reason: str) -> None:
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "_latest.json").write_text(json.dumps({
            "run_id": run_id,
            "file": f"{run_id}.ndjson",
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── Процессный фасад ─────────────────────────────────────────────────────────

def _default_root() -> Path:
    # app/ → agenter/ ; трейсы в agenter/logs/runs/
    return Path(__file__).resolve().parent.parent / "logs"


class Tracer:
    """Процессный фасад: один писатель + редактор на всё приложение, фабрика
    RunTrace на прогон. Создавать ПОСЛЕ load_dotenv (чтобы редактор увидел
    значения .env-ключей); недостающие секреты добавлять add_secret()."""

    def __init__(self, root: Optional[Path | str] = None, *,
                 min_level: str = "TRACE", enabled: bool = True,
                 extra_secrets: Optional[set[str]] = None) -> None:
        self.root = Path(root) if root else _default_root()
        self.min_level = min_level
        self.enabled = enabled
        self._writer = _Writer()
        self._extra_secrets: set[str] = set(extra_secrets or set())
        self._redactor = _make_redactor(self._extra_secrets)
        self._runs: dict[str, RunTrace] = {}

    def add_secret(self, value: Optional[str]) -> None:
        """Зарегистрировать значение секрета (ключ API), которого может не быть
        в os.environ, чтобы он маскировался в трейсе. Пересобирает редактор."""
        if value and len(value) >= 8:
            self._extra_secrets.add(value)
            self._redactor = _make_redactor(self._extra_secrets)

    def begin(self, run_id: str) -> RunTrace:
        self._writer.start()
        rt = RunTrace(self._writer, run_id, self.root, self._redactor,
                      min_level=self.min_level)
        self._runs[run_id] = rt
        return rt

    def get(self, run_id: str) -> Optional[RunTrace]:
        return self._runs.get(run_id)


# Ленивый процессный синглтон — Фаза 2 возьмёт его в main.py.
_TRACER: Optional[Tracer] = None
_TRACER_LOCK = threading.Lock()


def get_tracer() -> Tracer:
    global _TRACER
    if _TRACER is None:
        with _TRACER_LOCK:
            if _TRACER is None:
                enabled = os.environ.get("AGENT_TRACE", "1").strip().lower() not in (
                    "0", "false", "off", "no")
                level = os.environ.get("AGENT_TRACE_LEVEL", "TRACE").strip().upper()
                if level not in LEVELS:
                    level = "TRACE"
                _TRACER = Tracer(min_level=level, enabled=enabled)
    return _TRACER


# ── Catch-all обёртка прогона: тишины быть не может ───────────────────────────

@contextmanager
def run_scope(tracer: Tracer, run_id: str, *, prompt: str,
              selected_model: Optional[str], effective_model: Optional[str],
              provider: str, config_snapshot: Optional[dict] = None,
              system_prompt: Optional[str] = None) -> Iterator[RunTrace]:
    """Оборачивает прогон. Пайплайн ВНУТРИ обязан вызвать rt.finish_run(<reason>)
    с конкретной причиной (success / blocked-by-guard / ...). Если он этого не
    сделал (исключение в хуке, silence-timeout, обрыв subprocess, отмена) —
    finally закрывает прогон reason="unknown-crash". finish_run идемпотентна:
    явный финал перебивает catch-all. Так каждый прогон ВСЕГДА имеет reason."""
    rt = tracer.begin(run_id)
    rt.start_run(prompt=prompt, selected_model=selected_model,
                 effective_model=effective_model, provider=provider,
                 config_snapshot=config_snapshot, system_prompt=system_prompt)
    try:
        yield rt
    except BaseException as e:  # noqa: BLE001 — фиксируем ВСЁ, включая Cancelled
        rt.emit("error", {
            "exception": repr(e),
            "traceback": traceback.format_exc(),
        }, level="ERROR")
        rt.finish_run("unknown-crash", summary={"crash": repr(e)})
        raise
    finally:
        # если пайплайн уже финализировал явной причиной — это no-op
        rt.finish_run("unknown-crash", summary={"note": "финал без явной причины"})


# ── Самопроверка: демо-трейсы ────────────────────────────────────────────────

if __name__ == "__main__":
    tr = Tracer()
    # секрет, чтобы показать редакцию (имитация ключа из конфига)
    tr.add_secret("sk-demo0000000000000000000000000")

    # 1) Нормальный прогон → success
    rid = "demo-success"
    rt = tr.begin(rid)
    rt.start_run(
        prompt="Создать справочник Контрагенты с реквизитом ИНН",
        selected_model="claude-sonnet-4-6",  # из UI-дропдауна
        effective_model="deepseek-v4-flash",  # реально ушло в SDK
        provider="deepseek",
        config_snapshot={
            "scheme_path": "D:/CURSORIC/agenter/SCHEME",
            "bsl_atlas_url": "http://localhost:8765",
            "DEEPSEEK_API_KEY": "<REDACTED>",  # демо: значение маскируется до попадания в лог
            "Authorization": "Bearer <REDACTED>",   # демо: значение маскируется до попадания в лог
        },
        system_prompt="Ты — Agenter. Жёсткие правила: не редактируй XML вручную...",
    )
    rt.emit("plan", {"level": "L2", "stages": [
        {"index": 1, "kind": "sync-from-db", "expected_tool": "db_dump"},
        {"index": 2, "kind": "create-metadata-object", "expected_tool": "meta_compile"},
        {"index": 3, "kind": "validate-and-load", "expected_tool": "db_load"},
    ]})
    with rt.span("stage:create-metadata-object", event_type="stage_enter"):
        rt.set_stage("create-metadata-object")
        rt.set_iteration(1)
        rt.llm_call(
            delta_messages=[{"role": "user", "content": "stage 2: создай объект"}],
            response={"tool_use": "meta_compile", "input": {"name": "Контрагенты"}},
            tokens_in=1820, tokens_out=240, tokens_cache=15000, duration_ms=2100,
            cumulative_tokens={"in": 1820, "out": 240},
        )
        rt.emit("tool_call", {"tool": "meta_compile",
                              "input": {"name": "Контрагенты", "attrs": ["ИНН:Строка"]},
                              "ok": True, "result_preview": "создан Catalog Контрагенты"},
                level="INFO", duration_ms=180, status="ok")
        rt.emit("guard", {"guard": "db_load-after-validate", "decision": "allow"},
                level="DEBUG", status="allow")
    rt.finish_run("success", summary={
        "turns": 3, "tokens_in": 1820, "tokens_out": 240,
        "cost": calc_cost("deepseek-v4-flash", 1820, 240, 15000),
        "final_state": "applied",
    })

    # 2) Прогон с крашем → catch-all даёт unknown-crash (тишины нет)
    try:
        with run_scope(tr, "demo-crash",
                       prompt="Задача, в которой упадёт хук",
                       selected_model="claude-sonnet-4-6",
                       effective_model="deepseek-v4-flash",
                       provider="deepseek",
                       system_prompt="системный промпт..."):
            raise RuntimeError("имитация падения PostToolUse-хука")
    except RuntimeError:
        pass

    runs = Path(_default_root()) / "runs"
    print(f"Демо-трейсы записаны в: {runs}")
    sample = runs / "demo-success.ndjson"
    if sample.exists():
        lines = sample.read_text(encoding="utf-8").splitlines()
        print(f"\nФайл demo-success.ndjson: {len(lines)} событий")
        print("\nПример строки трейса (run_start, отформатировано):")
        print(json.dumps(json.loads(lines[0]), ensure_ascii=False, indent=2))
        print("\nХвост demo-crash.ndjson (run_end):")
        crash = (runs / "demo-crash.ndjson").read_text(encoding="utf-8").splitlines()
        print(json.dumps(json.loads(crash[-1]), ensure_ascii=False, indent=2))
