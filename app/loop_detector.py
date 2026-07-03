"""
Фаза 1 / Шаг 1.1 — детектор циклов (net-new, работает ПАРАЛЛЕЛЬНО клетке).

Назначение: ловить патологию (повтор / застой) РАНО — на 3-м одинаковом шаге,
а не на 50-м (исчерпание turn-budget). Это §0-принцип «тупик → безопасный
отказ», который в провале `aee67934` не сработал, потому что детектор из легаси
(`orchestrator.py`) в SDK-путь не переносился.

Детектор НИЧЕГО не блокирует сам — он возвращает решение, а enforcement делают
хуки:
  • PostToolUse вызывает record() и при action=="steer"/"stop" возвращает
    модели additionalContext (мягкий разворот / честный стоп);
  • PreToolUse читает is_blocked() и отклоняет повтор «застрявшей» сигнатуры.

Двухступенчато:
  1-е срабатывание → "steer" (сильный намёк сменить подход / ask_user / завершить);
  2-е срабатывание (всё ещё патология после намёка) → "stop" (жёсткий стоп).

Три независимых сигнала срабатывания:
  • повтор: одинаковая сигнатура {tool, params} ≥ repeat_n раз в скользящем окне;
  • повтор ошибки: один и тот же падающий tool с тем же классом ошибки ≥ error_repeat;
  • застой: ≥ no_progress_k шагов без ШИРОКОГО прогресс-маркера.

Прогресс-маркер намеренно широкий (иначе research с 0 db_load ложно стопится):
  любое НОВОЕ успешное отличное действие (свежая сигнатура с ok=True) ИЛИ явный
  прогресс (db_load / phase_commit / закрытый todo).

Параметры стартуют консервативно и вынесены для тюнинга.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field

# ── Параметры по умолчанию (консервативные; тюнить здесь) ────────────────────
DEFAULT_REPEAT_N: int = 3        # одинаковая {tool,params} ≥ N раз в окне → триггер
DEFAULT_ERROR_REPEAT: int = 2    # тот же падающий tool+класс ошибки ≥ this → триггер
DEFAULT_NO_PROGRESS_K: int = 9   # K шагов без прогресса → триггер (8–10)
DEFAULT_WINDOW: int = 12         # длина скользящего окна повторов


def signature(tool: str, params: object) -> str:
    """Стабильная короткая сигнатура {tool, params}. Меняются params → меняется
    сигнатура (итерация с прогрессом НЕ считается повтором)."""
    try:
        p = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        p = repr(params)
    raw = f"{tool}\x00{p}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class LoopDetector:
    repeat_n: int = DEFAULT_REPEAT_N
    error_repeat: int = DEFAULT_ERROR_REPEAT
    no_progress_k: int = DEFAULT_NO_PROGRESS_K
    window: int = DEFAULT_WINDOW

    # ── внутреннее состояние (per-task) ──
    _recent: deque = field(default_factory=deque, init=False, repr=False)
    _seen: set = field(default_factory=set, init=False, repr=False)
    _error_counts: dict = field(default_factory=dict, init=False, repr=False)
    _steps_since_progress: int = field(default=0, init=False)
    _strikes: int = field(default=0, init=False)
    _stopped_sig: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._recent = deque(maxlen=self.window)

    # ── основной вход: вызывается из PostToolUse на каждый завершённый tool ──
    def record(
        self,
        tool: str,
        params: object,
        ok: bool,
        *,
        explicit_progress: bool = False,
        error_class: str | None = None,
    ) -> dict:
        """Возвращает {"action": "none"|"steer"|"stop", "reason": str, "signature": str}."""
        sig = signature(tool, params)
        is_new = sig not in self._seen
        self._seen.add(sig)
        self._recent.append(sig)

        # прогресс: явный ИЛИ новое успешное отличное действие
        progressed = bool(explicit_progress or (ok and is_new))
        if progressed:
            self._steps_since_progress = 0
        else:
            self._steps_since_progress += 1

        repeat = self._recent.count(sig)

        err_hit = False
        err_count = 0
        if not ok:
            ekey = "{}\x00{}".format(tool, error_class or "")
            self._error_counts[ekey] = self._error_counts.get(ekey, 0) + 1
            err_count = self._error_counts[ekey]
            err_hit = err_count >= self.error_repeat

        reasons = []
        if repeat >= self.repeat_n:
            reasons.append(f"одинаковый вызов {tool} повторён {repeat}× подряд")
        if err_hit:
            reasons.append(f"{tool} падает с той же ошибкой {err_count}× подряд")
        if self._steps_since_progress >= self.no_progress_k:
            reasons.append(f"{self._steps_since_progress} шагов без прогресса")

        if not reasons:
            return {"action": "none", "reason": "", "signature": sig}

        reason = "; ".join(reasons)
        self._strikes += 1
        if self._strikes >= 2:
            self._stopped_sig = sig
            return {"action": "stop", "reason": reason, "signature": sig}

        # 1-е срабатывание → steer + даём «чистое окно», чтобы 2-е срабатывание
        # означало «всё ещё застрял ПОСЛЕ предупреждения», а не остаточный счётчик.
        self._recent.clear()
        self._steps_since_progress = 0
        return {"action": "steer", "reason": reason, "signature": sig}

    # ── читается PreToolUse: отклонять ли повтор «застрявшей» сигнатуры ──
    def is_blocked(self, tool: str, params: object) -> bool:
        return self._stopped_sig is not None and signature(tool, params) == self._stopped_sig

    @property
    def stopped(self) -> bool:
        return self._stopped_sig is not None


# ── Грубая классификация ошибки для сигнала «повтор ошибки» ──────────────────
def classify_error(text: str | None) -> str:
    """Короткий класс ошибки из текста результата tool (для группировки повторов).
    Не парсер — эвристика: первые осмысленные токены/код ошибки."""
    if not text:
        return ""
    low = text.lower()
    for marker in (
        "неизвестное имя типа", "unknown type",
        "не найден", "not found",
        "syntax", "синтакс",
        "validate", "валидац",
        "timeout", "таймаут",
        "permission", "доступ",
        "db_load", "загрузк",
    ):
        if marker in low:
            return marker
    return low[:40]
