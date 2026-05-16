"""
agenter/app/skill_registry.py — реестр скиллов из `.claude/skills/`.

Sprint 1 Step 3 архитектуры из audit-2026-05-15.md. Решает «cold skills» —
тот длинный хвост 1С-инструментов (mxl-*, skd-*, role-*, subsystem-*, epf-*,
erf-*, web-*, …), которые слишком редкие чтобы экспонировать первоклассными
MCP-tools'ами (раздувает tool-list, бьёт по токенам каждого turn'а), но
слишком ценные чтобы агент не знал об их существовании.

Идея — два мета-tool'a в SDK MCP сервере:
  • skill_search(query)         — поиск по индексу SKILL.md → топ-5 кандидатов
  • skill_run(name, args_dict)  — запуск .claude/skills/<name>/scripts/<name>.ps1

Индекс — single-shot scan каталога скиллов при первом обращении. Кэш в памяти.
Реиндексация ленивая (если файл изменился — мы это просто не замечаем; для
агента это нормально, скиллы обновляются редко).

Структура SKILL.md (YAML frontmatter между `---`):
    ---
    name: form-validate
    description: ...
    argument-hint: <FormPath> [-Detailed] [-MaxErrors 30]
    allowed-tools: [...]
    ---
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


# ── Категории по префиксу имени скилла ──────────────────────────────────────
# Используются для группировки в `skill_search(category=...)` и `skill_list`.

_CATEGORY_BY_PREFIX = {
    "cf-":         "Конфигурация",
    "cfe-":        "Расширение",
    "db-":         "База данных",
    "epf-":        "Внешняя обработка",
    "erf-":        "Внешний отчёт",
    "form-":       "Форма",
    "help-":       "Справка объекта",
    "img-":        "Изображения",
    "interface-":  "Командный интерфейс",
    "meta-":       "Метаданные объекта",
    "mxl-":        "Макет MXL",
    "role-":       "Роль",
    "skd-":        "СКД",
    "subsystem-":  "Подсистема",
    "template-":   "Макет/шаблон",
    "web-":        "Веб-публикация",
}


# ── Скиллы, которые УЖЕ экспонированы как hot tools (см. sdk_tools.py) ─────
# Их не показываем в skill_search — у агента есть прямой именованный tool,
# чтобы не плодить дубликат и не сбивать. Список синхронизируется руками
# с make_agenter_tools при добавлении/удалении hot tools.

_HOT_SKILLS = frozenset({
    # Sprint 1 Step 2 hot tools
    "form-info", "form-validate", "form-edit", "form-compile",
    "meta-info", "meta-validate",
    "db-update", "db-run",
    # Sprint 2 hotfix-5 — subsystem-edit (после провала на «Включи в подсистему»)
    "subsystem-edit",
    # Существовавшие до Sprint 1 (экспонируются как агенту прямые tools)
    "cfe-borrow", "cfe-patch-method", "cfe-validate",
    "meta-compile", "meta-edit",
    "db-dump-xml", "db-load-xml",  # обёрнуты как db_dump/db_load
})


@dataclass(slots=True)
class SkillEntry:
    """Один скилл в реестре."""
    name: str               # «form-validate»
    description: str        # короткое описание из frontmatter
    args_hint: str          # «<FormPath> [-Detailed] [-MaxErrors 30]»
    category: str           # «Форма»
    script_path: Path       # .../scripts/form-validate.ps1 (или .py)
    md_path: Path           # .../SKILL.md

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "args_hint":   self.args_hint,
            "category":    self.category,
        }


# ── YAML-frontmatter парсер (минимальный, без зависимости от PyYAML) ───────

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Парсит первый YAML-блок ``---...---`` в начале файла.

    Возвращает плоский dict ``key → value`` (строковые значения только;
    списки/вложенные ключи игнорируем — нам нужны name, description,
    argument-hint, чего достаточно для скиллов).
    """
    m = _FRONT_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out: dict[str, str] = {}
    cur_key: str | None = None
    cur_lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        # Список ``- item`` принадлежит предыдущему ключу — игнорируем
        if line.lstrip().startswith("-") and cur_key:
            continue
        # ``key: value`` или ``key:`` (multiline следующий) — простая эвристика
        if ":" in line and not line.startswith(" "):
            # commit предыдущий
            if cur_key:
                out[cur_key] = " ".join(cur_lines).strip()
                cur_lines = []
            k, _, v = line.partition(":")
            cur_key = k.strip()
            cur_lines = [v.strip()]
        elif cur_key:
            cur_lines.append(line.strip())
    if cur_key:
        out[cur_key] = " ".join(cur_lines).strip()
    return out


def _category_of(name: str) -> str:
    for prefix, cat in _CATEGORY_BY_PREFIX.items():
        if name.startswith(prefix):
            return cat
    return "Прочее"


def _resolve_script(skill_dir: Path, skill_name: str) -> Path | None:
    """Находит исполнимый скрипт скилла.

    Приоритет:
      1. ``scripts/<skill_name>.ps1`` (типичный случай)
      2. ``scripts/<skill_name>.py``
      3. ``scripts/init.ps1`` / ``scripts/init.py`` (cfe-init, epf-init и т.п.)
      4. Единственный ``scripts/*.ps1`` в папке (edge case:
         ``form-remove/scripts/remove-form.ps1``)
      5. Единственный ``scripts/*.py``
    """
    scripts_dir = skill_dir / "scripts"
    ps1 = scripts_dir / f"{skill_name}.ps1"
    py  = scripts_dir / f"{skill_name}.py"
    if ps1.exists(): return ps1
    if py.exists():  return py
    for fallback in (scripts_dir / "init.ps1", scripts_dir / "init.py"):
        if fallback.exists():
            return fallback
    # Fallback: один-единственный .ps1 в scripts/ (исключая stub-* / utility).
    if scripts_dir.exists():
        primary_ps1 = [p for p in scripts_dir.glob("*.ps1")
                       if not p.name.startswith("stub-")]
        if len(primary_ps1) == 1:
            return primary_ps1[0]
        primary_py = [p for p in scripts_dir.glob("*.py")
                      if not p.name.startswith("stub-")]
        if len(primary_py) == 1:
            return primary_py[0]
    return None


# ── Реестр ──────────────────────────────────────────────────────────────────


@dataclass
class SkillRegistry:
    """In-memory индекс всех скиллов проекта. Сканирует один раз при первом
    обращении (или при принудительном refresh)."""

    skills_root: Path
    entries: dict[str, SkillEntry] = field(default_factory=dict)
    _scanned: bool = False

    def scan(self, *, force: bool = False) -> None:
        if self._scanned and not force:
            return
        self.entries.clear()
        if not self.skills_root.exists():
            log.warning("skills_root не существует: %s", self.skills_root)
            self._scanned = True
            return
        for child in sorted(self.skills_root.iterdir()):
            if not child.is_dir():
                continue
            md = child / "SKILL.md"
            if not md.exists():
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                log.warning("SKILL.md read failed: %s — %s", md, e)
                continue
            front = _parse_frontmatter(text)
            name = (front.get("name") or child.name).strip()
            desc = (front.get("description") or "").strip()
            hint = (front.get("argument-hint") or "").strip().strip('"').strip("'")
            script = _resolve_script(child, name)
            if script is None:
                # Без скрипта запускать нечем — пропускаем (например form-patterns)
                log.debug("Skill %s без исполняемого скрипта — пропуск", name)
                continue
            self.entries[name] = SkillEntry(
                name=name,
                description=desc,
                args_hint=hint,
                category=_category_of(name),
                script_path=script,
                md_path=md,
            )
        self._scanned = True
        log.info("SkillRegistry: проиндексировано %d скиллов из %s",
                 len(self.entries), self.skills_root)

    # ── API для skill_search / skill_run ──────────────────────────────────

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        top_k: int = 5,
        include_hot: bool = False,
    ) -> list[SkillEntry]:
        """Поиск по индексу. Скор: совпадения слов в name + description.

        include_hot — обычно False: hot-skills уже доступны агенту как
        отдельные tools, дублировать их в результаты skill_search не имеет
        смысла (запутывает). Поднимаем True только если caller — UI/CLI,
        который хочет видеть всё.
        """
        self.scan()
        q = (query or "").lower().strip()
        q_words = [w for w in re.split(r"\W+", q) if len(w) >= 2]
        results: list[tuple[int, SkillEntry]] = []
        for entry in self.entries.values():
            if not include_hot and entry.name in _HOT_SKILLS:
                continue
            if category and entry.category != category:
                continue
            # Скор: сколько слов запроса встречается в (name + description)
            hay = f"{entry.name} {entry.description}".lower()
            score = 0
            if q in hay:
                score += 10  # бонус за точное substring-совпадение всей строки
            for w in q_words:
                if w in hay:
                    score += 2
                if w in entry.name.lower():
                    score += 3  # name важнее description
            # Если запрос пуст — возвращаем по алфавиту с маленьким positive score
            if not q_words and not q:
                score = 1
            if score > 0:
                results.append((score, entry))
        results.sort(key=lambda x: (-x[0], x[1].name))
        return [e for _, e in results[:top_k]]

    def get(self, name: str) -> SkillEntry | None:
        self.scan()
        return self.entries.get(name)


# ── Конвертация args (dict) → CLI-параметры PowerShell ─────────────────────


def _to_pascal_case(snake: str) -> str:
    """``form_path`` → ``FormPath``. Для аргументов PowerShell."""
    parts = re.split(r"[_\-]", snake)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def args_to_ps_cli(args: dict | None) -> list[str]:
    """Преобразует словарь аргументов из вызова tool в плоский список
    CLI-параметров PowerShell.

    Конвенции:
      • ``snake_case`` → ``-PascalCase``
      • Если значение — ``bool True`` → флаг без значения (``-Detailed``)
      • Если значение — ``bool False`` ИЛИ ``None`` ИЛИ ``""`` → пропуск
      • Списки → JSON-encoded string (на стороне скрипта может пригодиться)
      • Всё прочее → str(value)
    """
    if not args:
        return []
    out: list[str] = []
    import json as _json
    for raw_k, v in args.items():
        if v is None or v == "":
            continue
        pascal = _to_pascal_case(str(raw_k))
        if isinstance(v, bool):
            if v:
                out.append(f"-{pascal}")
            continue
        if isinstance(v, (list, dict)):
            out.extend([f"-{pascal}", _json.dumps(v, ensure_ascii=False)])
            continue
        out.extend([f"-{pascal}", str(v)])
    return out


# ── Глобальный singleton ────────────────────────────────────────────────────


_GLOBAL_REGISTRY: SkillRegistry | None = None


def get_registry(skills_root: Path | str | None = None) -> SkillRegistry:
    """Возвращает singleton-реестр. Первый вызов задаёт корневую папку.

    Обычно вызывается из sdk_tools при сборке MCP server'а с конкретным
    skills_root из client_cfg.
    """
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        if skills_root is None:
            # Дефолт — на случай отсутствия конфигурации (тесты и т.п.)
            skills_root = Path(__file__).parent.parent.parent / ".claude" / "skills"
        _GLOBAL_REGISTRY = SkillRegistry(Path(skills_root))
    return _GLOBAL_REGISTRY


def reset_registry() -> None:
    """Сброс singleton'а (для тестов и принудительной перезагрузки)."""
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = None
