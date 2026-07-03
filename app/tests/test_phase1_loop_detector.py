"""Фаза 1 / Шаг 1.1 — проверка детектора циклов искусственным зацикливанием.
Запуск: python app/tests/test_phase1_loop_detector.py  (выход 0 = все проверки прошли)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .../app

from loop_detector import LoopDetector  # noqa: E402

fails = []


def check(name, cond):
    print(("OK  " if cond else "FAIL") + " " + name)
    if not cond:
        fails.append(name)


# ── 1. Идентичный повтор: steer на 3-м, stop на 6-м, НЕ на 50-м ──
d = LoopDetector()
actions = []
for i in range(8):
    a = d.record("meta_compile", {"x": 1}, ok=True)
    actions.append(a["action"])
print("repeat actions:", actions)
check("повтор: 1-2-й шаг тихие", actions[0] == "none" and actions[1] == "none")
check("повтор: steer ровно на 3-м шаге", actions[2] == "steer")
check("повтор: жёсткий stop наступает рано (≤6-й шаг), не на 50-м",
      "stop" in actions and actions.index("stop") <= 5)
check("повтор: is_blocked ловит застрявшую сигнатуру после stop",
      d.is_blocked("meta_compile", {"x": 1}) and not d.is_blocked("meta_compile", {"x": 2}))

# ── 2. Research: каждый шаг — НОВОЕ успешное действие → НЕ стопится ──
d2 = LoopDetector()
research_actions = [d2.record("bsl_search", {"q": f"запрос-{i}"}, ok=True)["action"]
                    for i in range(30)]
check("research: 30 различных успешных шагов → ни одного срабатывания",
      all(a == "none" for a in research_actions))

# ── 3. Повтор одной и той же ошибки → срабатывает ──
d3 = LoopDetector()
err_actions = [d3.record("db_load", {"p": i}, ok=False, error_class="неизвестное имя типа")["action"]
               for i in range(4)]
print("error actions:", err_actions)
check("ошибка: повтор того же класса ошибки даёт срабатывание", err_actions[0] != "stop" and "steer" in err_actions or "stop" in err_actions)

# ── 4. Застой: повторяющееся (не новое) действие без прогресса ловится по K ──
d4 = LoopDetector(repeat_n=999, error_repeat=999, no_progress_k=9)  # глушим повтор/ошибку, чистый no-progress
# чередуем две сигнатуры, чтобы repeat<3, но прогресса нет (не новые после 2-й)
seq = []
for i in range(20):
    sig = {"a": i % 2}  # только 2 различных → после 2 шагов всё «не ново»
    seq.append(d4.record("Read", sig, ok=True)["action"])
print("no-progress actions:", seq)
check("застой: срабатывает по no_progress_k, не бесконечно тихо", any(a != "none" for a in seq))

# ── 5. Прогресс сбрасывает счётчик застоя (db_load explicit_progress) ──
d5 = LoopDetector(repeat_n=999, error_repeat=999, no_progress_k=5)
for i in range(4):
    d5.record("Read", {"same": 1}, ok=True)  # 0..1 новое, дальше не ново
a_before = d5.record("Read", {"same": 1}, ok=True)["action"]
a_progress = d5.record("db_load", {"n": 1}, ok=True, explicit_progress=True)["action"]
a_after = d5.record("Read", {"same": 1}, ok=True)["action"]
check("прогресс: db_load (explicit) сбрасывает застой", a_progress == "none" and a_after == "none")

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} — {fails}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
