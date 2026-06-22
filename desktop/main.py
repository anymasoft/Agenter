"""
agenter/desktop/main.py — модуль `ToolExecutor`.

Несмотря на историческое название «desktop», это НЕ отдельный процесс и НЕ
WS-relay к облачному backend'у. После перехода на монолитную архитектуру
(см. `app/main.py`) этот файл — обычный библиотечный модуль: его класс
`ToolExecutor` импортируется и инстанцируется единым приложением.

`ToolExecutor` инкапсулирует все локальные операции с 1С:
  • PowerShell-скиллы из `<project>/.claude/skills/` (form_*, meta_*, cfe_*,
    subsystem-edit, skill_run и т.п.) — через `_run_skill_with_args`
  • Прямые скрипты в `agenter/scripts/` (db-dump-xml, db-load-xml)
  • MCP-обёртки в `platform_doc_*`, `syntax_check`, файловые операции
  • Резолв путей `ext_src/`, `SCHEME/` относительно `config.json`

В конце файла остался legacy WS-relay код (websockets.connect к backend) —
он работает, если запустить файл напрямую (`python desktop/main.py`), но
в актуальной архитектуре эта точка входа не используется. Запускается
приложение через `app/main.py` (см. `start.bat` в корне `agenter/`).
"""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

from typing import Any

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

# Пути к скриптам и конфигу — с учётом PyInstaller frozen mode
if getattr(sys, "frozen", False):
    # Скомпилированный EXE: скрипты извлечены в sys._MEIPASS, конфиг рядом с EXE
    _SCRIPTS_DIR = Path(sys._MEIPASS) / "scripts"
    _CONFIG_DIR  = Path(sys.executable).parent / "config"
    # В frozen-режиме .claude/skills/ тоже извлекается рядом
    _DEFAULT_SKILLS_DIR = Path(sys._MEIPASS) / ".claude" / "skills"
else:
    _DESKTOP_DIR  = Path(__file__).parent.resolve()
    _AGENTER_ROOT = _DESKTOP_DIR.parent                # agenter/
    _SCRIPTS_DIR  = _AGENTER_ROOT / "scripts"
    _CONFIG_DIR   = _AGENTER_ROOT / "config"
    # Скиллы живут в <project_root>/.claude/skills/, а project_root = parent of agenter/
    _DEFAULT_SKILLS_DIR = _AGENTER_ROOT.parent / ".claude" / "skills"

# config.json берётся из agenter/config/, не рядом с main.py
CONFIG_FILE = _CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "backend_ws_url": "ws://localhost:8080/ws/desktop",
    "bsl_atlas_url":  "http://localhost:8000",
    # --- заполняется пользователем в config/config.json ---
    "ext_src_path": "",          # абсолютный путь к ext_src/ вашего расширения
    "scheme_path":  "",          # путь к SCHEME/ (XML-выгрузка основной конфигурации)
    "v8_path":      "",          # C:\Program Files\1cv8\X.X.XX.XXXX\bin
    "base_path":    "",          # путь к папке базы 1С или строка Srvr=...
    "username":     "",
    "password":     "",
    "extension":    "",          # имя расширения
    # пути к скриптам — автоматически из agenter/scripts/
    "dump_script": str(_SCRIPTS_DIR / "db-dump-xml.ps1"),
    "load_script": str(_SCRIPTS_DIR / "db-load-xml.ps1"),
    # Корень папки скиллов. Внутри ожидается meta-compile/, meta-edit/,
    # cfe-borrow/, cfe-patch-method/, cfe-validate/ каждый со scripts/<name>.ps1
    # Скиллы лежат в <project>/.claude/skills/ — НЕ путать с agenter/scripts/
    # (там только legacy db-dump-xml.ps1 / db-load-xml.ps1).
    "skills_dir":  str(_DEFAULT_SKILLS_DIR),
    # Максимум итераций LLM-цикла на одну задачу.
    # Защита: при зацикливании 3 одинаковых tool calls подряд → автостоп
    # независимо от этого лимита. Лимит — верхняя граница для совсем
    # длинных задач (сложные ТЗ типа складского учёта).
    "max_iterations": 50,
}


def load_config() -> dict:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        cfg = {**DEFAULT_CONFIG, **loaded}
        # Пути скриптов: из config.json если файл существует, иначе дефолт
        for _key in ("dump_script", "load_script"):
            _val = loaded.get(_key, "")
            cfg[_key] = _val if (_val and Path(_val).exists()) else DEFAULT_CONFIG[_key]
    else:
        cfg = DEFAULT_CONFIG.copy()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"\n[!] Создан config/config.json — заполни обязательные поля:\n"
              f"    ext_src_path, v8_path, base_path, username, extension\n"
              f"    Файл: {CONFIG_FILE}\n")
    return cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BSL Atlas MCP клиент
# ---------------------------------------------------------------------------

class BslAtlasClient:
    """HTTP-клиент к BSL Atlas MCP-серверу (localhost:8000)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session_id: str | None = None
        self._call_counter = 0

    async def _initialize(self):
        """Инициализировать MCP-сессию."""
        payload = {
            "jsonrpc": "2.0", "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "agenter-desktop", "version": "1.0"},
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/mcp",
                json=payload,
                headers={"Accept": "application/json, text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                self.session_id = resp.headers.get("mcp-session-id")
                if not self.session_id:
                    raise RuntimeError("BSL Atlas не вернул session-id")
                log.info("BSL Atlas сессия: %s", self.session_id)

    async def ensure_session(self):
        if not self.session_id:
            await self._initialize()

    def _parse_sse(self, text: str) -> Any:
        """Парсит SSE-ответ, возвращает поле result или бросает исключение."""
        for line in text.split("\n"):
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            data = json.loads(raw)
            if "error" in data:
                raise RuntimeError(f"BSL Atlas error: {data['error']['message']}")
            if "result" in data:
                return data["result"]
        raise RuntimeError(f"BSL Atlas: нет result в ответе: {text[:200]}")

    async def call_tool(self, name: str, arguments: dict) -> str:
        await self.ensure_session()
        self._call_counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._call_counter,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/mcp",
                    json=payload,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "mcp-session-id": self.session_id,
                    },
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    text = await resp.text()
                    result = self._parse_sse(text)
                    return json.dumps(result, ensure_ascii=False)
        except aiohttp.ClientError as e:
            # Попробуем пересоздать сессию при следующем вызове
            self.session_id = None
            raise RuntimeError(f"BSL Atlas недоступен: {e}")


# ---------------------------------------------------------------------------
# PowerShell runner
# ---------------------------------------------------------------------------

POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


async def run_powershell(script: str, *args: str, timeout: int = 600) -> str:
    """Запустить PowerShell-скрипт через системный PowerShell 5.1."""
    cmd = [POWERSHELL, "-ExecutionPolicy", "Bypass", "-NonInteractive", "-File", script, *args]
    log.info("PS: %s %s ...", POWERSHELL, script)

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Скрипт завис ({timeout}s): {script}")

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"PowerShell exit {proc.returncode}:\n{output[-2000:]}")
    return output


# ---------------------------------------------------------------------------
# Tool Executor
# ---------------------------------------------------------------------------

class _ConfigError(RuntimeError):
    """Ошибка конфигурации — путь не задан или файл не найден."""


# ---------------------------------------------------------------------------
# Нормализация DSL для meta-edit:
#   - Русские названия типов 1С → английские (Строка → String, Число → Number, ...)
#   - "Имя Тип" → "Имя:Тип" (когда пользователь забыл двоеточие)
#   - "Имя Type=Тип" → "Имя:Тип"
# ---------------------------------------------------------------------------

# Скалярные типы 1С: русский → английский (как ожидает meta-edit.ps1)
_RU_TYPE_TO_EN: dict[str, str] = {
    "Строка":                  "String",
    "Число":                   "Number",
    "Дата":                    "Date",
    "Булево":                  "Boolean",
    "ХранилищеЗначения":       "ValueStorage",
    "УникальныйИдентификатор": "UUID",
}

# Reference-типы 1С: русский префикс → английский
_RU_REF_PREFIX_TO_EN: dict[str, str] = {
    "СправочникСсылка":                "CatalogRef",
    "ДокументСсылка":                  "DocumentRef",
    "ПеречислениеСсылка":              "EnumRef",
    "ПланСчетовСсылка":                "ChartOfAccountsRef",
    "ПланВидовРасчетаСсылка":          "ChartOfCalculationTypesRef",
    "ПланВидовХарактеристикСсылка":    "ChartOfCharacteristicTypesRef",
    "БизнесПроцессСсылка":             "BusinessProcessRef",
    "ЗадачаСсылка":                    "TaskRef",
    "ПланОбменаСсылка":                "ExchangePlanRef",
    # Регистры — для add-dimension/resource/recorder
    "РегистрНакопленияСсылка":         "AccumulationRegisterRef",
    "РегистрСведенийСсылка":           "InformationRegisterRef",
    "РегистрБухгалтерииСсылка":        "AccountingRegisterRef",
    "РегистрРасчетаСсылка":            "CalculationRegisterRef",
}


def _translate_type_to_en(type_str: str) -> str:
    """Переводит русское название типа 1С в английское, понятное meta-edit.

    Примеры:
        Строка(50)              → String(50)
        Число(15,2)             → Number(15,2)
        Дата                    → Date
        СправочникСсылка.Банки  → CatalogRef.Банки   (имя объекта остаётся!)
        String(50)              → String(50)         (already English, no-op)
    """
    s = type_str.strip()
    if not s:
        return s

    # Reference-типы: <RuPrefix>.<ObjectName> → <EnPrefix>.<ObjectName>
    if "." in s:
        prefix, dot, rest = s.partition(".")
        en_prefix = _RU_REF_PREFIX_TO_EN.get(prefix)
        if en_prefix:
            return f"{en_prefix}.{rest}"
        return s  # неизвестный префикс — оставляем

    # Скалярные типы: <Type>(args)? → <En>(args)?
    base = s
    args = ""
    if "(" in s:
        paren_idx = s.index("(")
        base = s[:paren_idx]
        args = s[paren_idx:]
    en_base = _RU_TYPE_TO_EN.get(base)
    if en_base:
        return f"{en_base}{args}"
    return s


def _normalize_meta_edit_value(operation: str, value: str) -> str:
    """Нормализует value для meta-edit перед передачей в PowerShell-скилл.

    Поправляет частые ошибки LLM-агента:
        - "Город Строка(50)"        → "Город:String(50)"
        - "Город Type=String(50)"   → "Город:String(50)"
        - "Город : Строка ( 50 )"   → "Город:String(50)"

    Применяется только к add-* операциям с shorthand `Name:Type[|flags]`.
    Для modify/remove/set операций value не трогаем.
    """
    if not value or not operation.startswith("add-"):
        return value

    # add-property не имеет shorthand с типом
    if operation == "add-property":
        return value

    # Batch: "a;;b;;c" → нормализуем каждую часть отдельно.
    # Для add-ts используем специальный парсер (там вложенные attrs внутри ТЧ).
    parts = value.split(";;")
    out_parts: list[str] = []
    is_ts = operation == "add-ts"
    for raw in parts:
        s = raw.strip()
        if is_ts:
            out_parts.append(_normalize_ts_shorthand(s))
        else:
            out_parts.append(_normalize_one_shorthand(s))
    return ";;".join(out_parts)


# ---------------------------------------------------------------------------
# Серверная валидация имён реквизитов 1С (NCName)
# ---------------------------------------------------------------------------

# 1С разрешает в именах: латиница, кириллица, цифры (со 2-го символа),
# подчёркивание. Запрещены: пробелы, скобки, точки, запятые, дефис, спецсимволы.
_BAD_NAME_CHAR = __import__("re").compile(r"[^A-Za-zА-Яа-яЁё0-9_]")
_MAX_NAME_LEN = 128  # лимит платформы 1С


def _validate_meta_name(name: str) -> str | None:
    """Возвращает None если имя валидно, иначе строку с описанием ошибки.

    Проверки:
        - не пустое
        - не длиннее 128 символов
        - не начинается с цифры
        - содержит только буквы (лат/кир), цифры и подчёркивание
    """
    if not name:
        return "пустое имя"
    if len(name) > _MAX_NAME_LEN:
        return f"имя длиннее {_MAX_NAME_LEN} символов ({len(name)})"
    if name[0].isdigit():
        return "имя не может начинаться с цифры"
    m = _BAD_NAME_CHAR.search(name)
    if m:
        ch = m.group()
        ch_repr = repr(ch) if ch.strip() else "пробел"
        return f"недопустимый символ {ch_repr} на позиции {m.start() + 1}"
    return None


def _split_by_comma_outside_parens(s: str) -> list[str]:
    """Разделяет строку по запятым, не считая запятые внутри (), [], {}.
    Нужно для add-ts: 'Количество:Number(15,3), Сумма:Number(10,2)'."""
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in s:
        if ch in "([{":
            depth += 1
            current += ch
        elif ch in ")]}":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def _extract_names_from_value(operation: str, value: str) -> list[str]:
    """Извлекает все НОВЫЕ имена объектов метаданных, которые будут созданы.

    Не извлекает:
        - имена-ссылки в modify-/remove-/set- операциях (это existing имена,
          валидация имени там не имеет смысла — они либо в БД либо нет)
        - имена внутри типа (CatalogRef.Контрагенты — Контрагенты не наше)
    """
    if not value or not operation.startswith("add-"):
        return []
    # add-property — modify-like, set-like; имени реквизита нет
    if operation == "add-property":
        return []
    # Операции добавления ссылок на существующие объекты — имена там не валидируем
    if operation in ("add-owner", "add-registerRecord", "add-basedOn", "add-inputByString"):
        return []

    import re as _re

    names: list[str] = []
    for raw in value.split(";;"):
        s = raw.strip()
        if not s:
            continue
        # Снять флаги (после |)
        if "|" in s:
            s = s.split("|", 1)[0]
        # Снять positional markers (>>after / <<before)
        s = _re.sub(r"\s*(>>|<<)\s*(after|before)\s+\S+\s*$", "", s).strip()

        if operation == "add-ts":
            # "ТабЧасть: Атр1:Тип, Атр2:Тип, ..." или просто "ТабЧасть"
            if ":" in s:
                ts_name, _, attrs_part = s.partition(":")
                names.append(ts_name.strip())
                for attr in _split_by_comma_outside_parens(attrs_part):
                    attr = attr.strip()
                    if not attr:
                        continue
                    if "|" in attr:
                        attr = attr.split("|", 1)[0]
                    if ":" in attr:
                        a_name, _, _ = attr.partition(":")
                        names.append(a_name.strip())
                    else:
                        names.append(attr)
            else:
                names.append(s)
        else:
            # Простой shorthand: "Name:Type" или просто "Name"
            if ":" in s:
                name, _, _ = s.partition(":")
                names.append(name.strip())
            else:
                names.append(s)
    return names


def _normalize_ts_shorthand(s: str) -> str:
    """Нормализация для add-ts: имя ТЧ остаётся, attrs внутри проходят через
    обычный shorthand-нормализатор (русские типы → английские)."""
    if ":" not in s:
        return s
    ts_name, _, attrs_part = s.partition(":")
    attrs_raw = _split_by_comma_outside_parens(attrs_part)
    attrs_normalized = [
        _normalize_one_shorthand(attr.strip()) for attr in attrs_raw if attr.strip()
    ]
    if attrs_normalized:
        return f"{ts_name.strip()}: {', '.join(attrs_normalized)}"
    return ts_name.strip()


def _normalize_one_shorthand(s: str) -> str:
    """Нормализует один shorthand вида 'Name:Type[|flags]'."""
    if not s:
        return s

    # Отделяем флаги (после |) — их не трогаем.
    # Сохраняем пробелы вокруг |, чтобы вход "X | req" не превращался в "X|req".
    if "|" in s:
        main, sep, flags = s.partition("|")
        pre = " " if main.endswith(" ") else ""
        post = " " if flags.startswith(" ") else ""
        flags_suffix = pre + sep + post + flags.lstrip()
    else:
        main = s
        flags_suffix = ""

    # Отделяем positional-маркеры (>>after, <<before) — не трогаем
    pos_suffix = ""
    import re as _re
    m_pos = _re.search(r"\s*(>>|<<)\s*(after|before)\s+\S+\s*$", main)
    if m_pos:
        pos_suffix = main[m_pos.start():]
        main = main[: m_pos.start()].rstrip()

    main = main.strip()

    # Убираем "Type=" если есть
    main = _re.sub(r"\s+Type\s*=\s*", " ", main)

    # Если нет ':' но есть пробел — первый токен это имя, остальное тип
    if ":" not in main:
        m = _re.match(r"^(\S+)\s+(.+)$", main)
        if m:
            name = m.group(1).strip()
            type_str = m.group(2).strip()
            main = f"{name}:{type_str}"

    # Теперь у нас "Name:Type" — переводим Type
    if ":" in main:
        name, _, type_str = main.partition(":")
        type_str = _translate_type_to_en(type_str.strip())
        main = f"{name.strip()}:{type_str}" if type_str else name.strip()

    return main + pos_suffix + flags_suffix


def _validate_definition_names(definition: dict) -> list[str]:
    """Проверяет все имена объектов внутри meta-edit definition.

    Возвращает список ошибок в формате '<контекст>: <имя> - <причина>'.
    Пустой список = всё валидно.

    Покрытие:
      add.attributes[*].name
      add.tabularSections[*].name + .attrs[*].name
      add.dimensions[*].name, add.resources[*].name, add.enumValues[*].name
      add.forms / add.templates / add.commands (строки)
      modify.attributes — ключи + value.name (переименование)
      modify.tabularSections — ключи + .add.attrs[*].name + .modify.* + .remove.*
      remove.* — массивы строк (должны быть валидными именами)
    """
    errors: list[str] = []

    def _check(name: object, context: str) -> None:
        if not isinstance(name, str):
            errors.append(f"{context}: тип {type(name).__name__}, ожидается строка")
            return
        err = _validate_meta_name(name)
        if err:
            errors.append(f"{context} '{name}' — {err}")

    add = definition.get("add") or {}
    if isinstance(add, dict):
        for item in add.get("attributes") or []:
            if isinstance(item, dict):
                _check(item.get("name"), "add.attributes[].name")
        for ts in add.get("tabularSections") or []:
            if isinstance(ts, dict):
                _check(ts.get("name"), "add.tabularSections[].name")
                for attr in ts.get("attrs") or []:
                    if isinstance(attr, dict):
                        _check(attr.get("name"), f"add.tabularSections.{ts.get('name','?')}.attrs[].name")
        for kind in ("dimensions", "resources", "enumValues"):
            for item in add.get(kind) or []:
                if isinstance(item, dict):
                    _check(item.get("name"), f"add.{kind}[].name")
        for kind in ("forms", "templates", "commands"):
            for name in add.get(kind) or []:
                _check(name, f"add.{kind}[]")

    modify = definition.get("modify") or {}
    if isinstance(modify, dict):
        # properties — это поля XML, не имена реквизитов, не валидируем
        for old_name, changes in (modify.get("attributes") or {}).items():
            # ключ — существующее имя в БД, не валидируем (оно либо есть либо нет)
            if isinstance(changes, dict) and "name" in changes:
                _check(changes["name"], f"modify.attributes.{old_name}.name (переименование)")
        for ts_name, ts_changes in (modify.get("tabularSections") or {}).items():
            if isinstance(ts_changes, dict):
                # add внутри ts — массив shorthand-строк (формат скилла) ИЛИ объектов
                # их валидирует сам скилл. Объектную форму проверяем.
                for entry in ts_changes.get("add") or []:
                    if isinstance(entry, dict):
                        _check(entry.get("name"), f"modify.tabularSections.{ts_name}.add[].name")
                # modify — словарь имя→изменения, валидируем только переименования
                for old_attr, changes in (ts_changes.get("modify") or {}).items():
                    if isinstance(changes, dict) and "name" in changes:
                        _check(changes["name"], f"modify.tabularSections.{ts_name}.modify.{old_attr}.name")

    # remove — список существующих имён, теоретически они уже валидны в БД
    # Но если LLM передал явно невалидное (с пробелом) — это всё равно ошибка
    remove = definition.get("remove") or {}
    if isinstance(remove, dict):
        for kind in ("attributes", "tabularSections", "dimensions", "resources",
                     "enumValues", "forms", "templates", "commands"):
            for name in remove.get(kind) or []:
                _check(name, f"remove.{kind}[]")

    return errors


def _resolve_meta_object_path(p: Path) -> Path | None:
    """Резолвит путь объекта метаданных 1С в фактический файл/папку.

    1С-расширения хранят объекты в двух форматах:
        - Плоский XML:   Catalogs/Банки.xml          (без модулей)
        - С подпапкой:   Catalogs/Банки/Банки.xml    (есть модули/формы/...)

    cfe_borrow создаёт плоский XML, но при наличии модулей объект
    может быть структурно полным. Эта функция пробует обе раскладки.

    Returns:
        Path до фактического файла или папки-с-XML, либо None если
        ничего подходящего не найдено.
    """
    # 1) Передан абсолютный путь к файлу — используем как есть
    if p.is_file():
        return p

    # 2) Передана папка — meta-edit.ps1 сам найдёт Имя.xml внутри
    if p.is_dir():
        return p

    # 3) Передан путь без расширения — пробуем добавить .xml
    with_xml = p.with_suffix(".xml")
    if with_xml.is_file():
        return with_xml

    # 4) Передан путь без расширения — пробуем как папку с одноимённым XML
    nested = p / f"{p.name}.xml"
    if nested.is_file():
        return nested

    # 5) Передан путь с .xml но файла нет — попробуем папку без .xml
    if p.suffix.lower() == ".xml":
        as_dir = p.with_suffix("")
        # Catalogs/Банки.xml → Catalogs/Банки/Банки.xml (предпочитаем файл)
        nested2 = as_dir / p.name
        if nested2.is_file():
            return nested2
        if as_dir.is_dir():
            return as_dir

    return None


class ToolExecutor:
    def __init__(self, cfg: dict, bsl: BslAtlasClient):
        self.cfg = cfg
        self.bsl = bsl
        # Логируем статус конфигурации при старте
        _ext = cfg.get("ext_src_path", "") or "<не задан>"
        log.info("ext_src   : %s  (exists=%s)", _ext, Path(_ext).exists() if _ext != "<не задан>" else False)
        log.info("dump_script: %s  (exists=%s)", cfg.get("dump_script"),
                 Path(cfg.get("dump_script", "")).exists())
        log.info("load_script: %s  (exists=%s)", cfg.get("load_script"),
                 Path(cfg.get("load_script", "")).exists())

    # ── Внутренние проверки ────────────────────────────────────────────────

    def _require_ext_src(self) -> Path:
        """Проверяет ext_src_path и возвращает Path. Бросает _ConfigError если нет."""
        raw = self.cfg.get("ext_src_path", "").strip()
        if not raw:
            raise _ConfigError(
                "ext_src_path не задан.\n"
                "Откройте мастер Desktop-ассистента и укажите путь к папке ext_src."
            )
        p = Path(raw)
        if not p.exists():
            raise _ConfigError(
                f"Папка ext_src не найдена: {p}\n"
                "Проверьте ext_src_path в config/config.json."
            )
        return p

    def _require_script(self, key: str) -> str:
        """Возвращает путь к скрипту или бросает _ConfigError."""
        path = self.cfg.get(key, "").strip()
        if not path:
            raise _ConfigError(
                f"Путь к скрипту '{key}' не задан в config/config.json.\n"
                "Пройдите мастер подключения в Desktop-ассистенте."
            )
        if not Path(path).exists():
            raise _ConfigError(
                f"Скрипт не найден: {path}\n"
                f"Проверьте значение '{key}' в config/config.json."
            )
        return path

    def _skill_script(self, skill_name: str) -> str:
        """Возвращает путь к PowerShell-скрипту скилла.
        Структура: <skills_dir>/<skill_name>/scripts/<skill_name>.ps1

        Резолв в порядке приоритета:
          1. skills_dir из config.json (если файл существует)
          2. <project_root>/.claude/skills/ — стандартное расположение
          3. _SCRIPTS_DIR (исторический, для legacy db-dump-xml/db-load-xml)
        Это защищает от устаревших config.json (где skills_dir указывал на
        agenter/scripts/, а реальные скиллы переехали в .claude/skills/).
        """
        candidates: list[Path] = []
        skills_dir = (self.cfg.get("skills_dir") or "").strip()
        if skills_dir:
            candidates.append(Path(skills_dir) / skill_name / "scripts" / f"{skill_name}.ps1")
        # Стандартное расположение .claude/skills/ — пробуем как fallback,
        # даже если skills_dir указан (на случай устаревшей конфигурации).
        std_candidate = _DEFAULT_SKILLS_DIR / skill_name / "scripts" / f"{skill_name}.ps1"
        if std_candidate not in candidates:
            candidates.append(std_candidate)
        # Историческое расположение — legacy для db-dump-xml/db-load-xml,
        # они лежат прямо в _SCRIPTS_DIR без вложенной <name>/scripts/ структуры.
        legacy_candidate = _SCRIPTS_DIR / skill_name / "scripts" / f"{skill_name}.ps1"
        if legacy_candidate not in candidates:
            candidates.append(legacy_candidate)
        for script in candidates:
            if script.exists():
                return str(script)
        # Не нашли — даём подробное сообщение со всеми пробованными путями
        tried = "\n  ".join(str(p) for p in candidates)
        raise _ConfigError(
            f"Скрипт скилла '{skill_name}' не найден. Пробовали:\n  {tried}\n"
            f"Проверьте 'skills_dir' в config.json. Стандартное расположение: "
            f"{_DEFAULT_SKILLS_DIR}"
        )

    async def execute(self, tool: str, params: dict) -> str:
        match tool:
            case "db_dump":
                return await self._db_dump()
            case "db_load":
                return await self._db_load()
            case "bsl_search_function":
                return await self.bsl.call_tool("search_function", {
                    "name": params["name"],
                    "exact": params.get("exact", True),
                })
            case "bsl_get_object":
                return await self.bsl.call_tool("get_object_details", {
                    "full_name": params["full_name"],
                })
            case "bsl_code_grep":
                return await self.bsl.call_tool("code_grep", {
                    "pattern": params["pattern"],
                    "case_sensitive": params.get("case_sensitive", False),
                    "limit": params.get("limit", 20),
                })
            case "bsl_get_function_context":
                return await self.bsl.call_tool("get_function_context", {
                    "function_name": params["function_name"],
                })
            case "bsl_get_module_functions":
                return await self.bsl.call_tool("get_module_functions", {
                    "module_path": params["module_path"],
                })
            case "bsl_metadatasearch":
                return await self.bsl.call_tool("metadatasearch", {
                    "query": params["query"],
                    "limit": params.get("limit", 10),
                })
            # ── Semantic-инструменты BSL Atlas (требуют full mode) ────────
            # Доступны, когда BSL Atlas запущен с INDEXING_MODE=full +
            # CHROMADB_AUTO_INDEX=true. В fast-режиме сервер вернёт ошибку,
            # LLM в этом случае должен переключиться на структурные bsl_*.
            case "bsl_codesearch":
                return await self.bsl.call_tool("codesearch", {
                    "query": params["query"],
                    "limit": params.get("limit", 10),
                })
            case "bsl_helpsearch":
                return await self.bsl.call_tool("helpsearch", {
                    "query": params["query"],
                    "limit": params.get("limit", 10),
                })
            case "bsl_search_code_filtered":
                args = {"query": params["query"], "limit": params.get("limit", 10)}
                for k in ("module_type", "function_name_pattern", "object_type"):
                    if params.get(k):
                        args[k] = params[k]
                return await self.bsl.call_tool("search_code_filtered", args)
            case "read_file":
                return self._read_file(params["path"])
            case "edit_file":
                return self._edit_file(params["path"], params["old_str"], params["new_str"])
            case "write_file":
                return self._write_file(params["path"], params["content"])
            case "list_ext_files":
                return self._list_ext_files()
            case "get_sample_object":
                return self._get_sample_object(params["object_type"])
            case "clone_object":
                return self._clone_object(params["source_path"], params["new_name"])
            case "validate_ext_structure":
                return self._validate_ext_structure()
            # ── Новые tools через подключённые скиллы ─────────────────────
            case "meta_compile":
                return await self._meta_compile(params.get("definition"))
            case "meta_edit":
                return await self._meta_edit(
                    params["object_path"],
                    params["operation"],
                    params["value"],
                )
            case "cfe_borrow":
                return await self._cfe_borrow(
                    params["object"],
                    params.get("borrow_main_attribute"),
                )
            case "cfe_patch_method":
                return await self._cfe_patch_method(
                    params["module_path"],
                    params["method_name"],
                    params["interceptor_type"],
                    params.get("context", "НаСервере"),
                    bool(params.get("is_function", False)),
                )
            case "cfe_validate":
                return await self._cfe_validate()
            case "platform_doc_lookup":
                return await self._platform_doc_lookup(
                    params["name"],
                    int(params.get("limit", 5)),
                )
            case _:
                raise ValueError(f"Неизвестный инструмент: {tool}")

    # --- Платформенная справка 1С (shcntx_ru.hbk → SQLite индекс) ---

    _platform_docs_module = None  # ленивый импорт, один раз

    async def _platform_doc_lookup(self, name: str, limit: int = 5) -> str:
        """Lookup в индексе платформенной справки 1С.
        Источник: shcntx_ru.hbk из установки 1С, проиндексированный в SQLite.
        Импорт ленивый — модуль platform_docs.py лежит в app/, грузим через importlib."""
        if ToolExecutor._platform_docs_module is None:
            import importlib.util
            _desktop_dir = Path(__file__).parent.resolve()
            _agenter_root = _desktop_dir.parent
            _pd_path = _agenter_root / "app" / "platform_docs.py"
            if not _pd_path.exists():
                return json.dumps({
                    "error": f"platform_docs.py not found at {_pd_path}. "
                             f"Запусти build_index() для генерации БД."
                }, ensure_ascii=False)
            spec = importlib.util.spec_from_file_location(
                "agenter_platform_docs", _pd_path,
            )
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ToolExecutor._platform_docs_module = mod

        pd = ToolExecutor._platform_docs_module

        def _do_lookup():
            return pd.lookup_by_name(name, limit=limit)

        results = await asyncio.to_thread(_do_lookup)
        if not results:
            return json.dumps({
                "found": 0,
                "name": name,
                "message": (
                    f"Не найдено в платформенной справке 1С. "
                    f"Возможно: (1) ты ошибся в имени, (2) это метод БСП — "
                    f"ищи через bsl_search_function/bsl_code_grep, "
                    f"(3) это пользовательская функция конфигурации — "
                    f"ищи через bsl_search_function."
                ),
            }, ensure_ascii=False)

        return json.dumps({
            "found": len(results),
            "query": name,
            "results": results,
        }, ensure_ascii=False, indent=2)

    _platform_chroma_module = None

    async def _platform_doc_search(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
    ) -> str:
        """Семантический поиск в ChromaDB-индексе справки платформы.

        Lazy-импорт platform_docs_chroma.py (тяжёлые зависимости —
        sentence-transformers и chromadb загружаются только при первом вызове).
        """
        if ToolExecutor._platform_chroma_module is None:
            import importlib.util
            _desktop_dir = Path(__file__).parent.resolve()
            _agenter_root = _desktop_dir.parent
            _pdc_path = _agenter_root / "app" / "platform_docs_chroma.py"
            if not _pdc_path.exists():
                return json.dumps({
                    "error": f"platform_docs_chroma.py не найден: {_pdc_path}"
                }, ensure_ascii=False)
            spec = importlib.util.spec_from_file_location(
                "agenter_platform_docs_chroma", _pdc_path,
            )
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ToolExecutor._platform_chroma_module = mod

        pdc = ToolExecutor._platform_chroma_module
        kind_filter = [kind] if kind else None

        def _do_search():
            return pdc.search_semantic(query, limit=limit, kind_filter=kind_filter)

        results = await asyncio.to_thread(_do_search)
        if not results:
            return json.dumps({
                "found": 0,
                "query": query,
                "message": "Не найдено похожих разделов в семантическом индексе.",
            }, ensure_ascii=False)

        # Проверим что нет error-сообщения от модуля (например когда индекс не построен)
        if isinstance(results, list) and results and "_error" in results[0]:
            return json.dumps({
                "found": 0,
                "query": query,
                "error": results[0]["_error"],
                "hint": "Запусти операцию 'rebuild-platform-docs-semantic' "
                        "из UI (правая панель) чтобы построить ChromaDB-индекс.",
            }, ensure_ascii=False)

        return json.dumps({
            "found": len(results),
            "query": query,
            "results": results,
        }, ensure_ascii=False, indent=2)

    # --- 1С операции ---

    # Стандартные папки в корне 1С-выгрузки. Используется в safety-check
    # перед очисткой ext_src. Должно совпадать с _KNOWN_1C_DIRS в ops_runner.py.
    _CLEAR_KNOWN_NAMES: set[str] = {
        "Catalogs", "Documents", "CommonModules",
        "InformationRegisters", "AccumulationRegisters", "AccountingRegisters",
        "CalculationRegisters", "Reports", "DataProcessors",
        "Enums", "HTTPServices", "WebServices", "WSReferences",
        "Languages", "Roles", "CommonAttributes", "CommonForms",
        "CommonTemplates", "CommonPictures", "CommonCommands",
        "ExchangePlans", "ChartsOfAccounts", "Subsystems",
        "ChartsOfCharacteristicTypes", "ChartsOfCalculationTypes",
        "BusinessProcesses", "Tasks", "Constants", "Sequences",
        "DocumentJournals", "DocumentNumerators", "EventSubscriptions",
        "ScheduledJobs", "FunctionalOptions", "FunctionalOptionsParameters",
        "FilterCriteria", "SettingsStorages", "StyleItems", "Styles",
        "ExternalDataSources", "DefinedTypes", "SessionParameters",
        "CommandGroups", "InterfacesAddon", "Ext",
        "Configuration.xml", "ParentConfigurations.bin",
        "ConfigDumpInfo.xml", "Configuration.xml.bak",
    }

    def _is_safe_to_clear_1c_dir(self, p: Path) -> tuple[bool, str]:
        """True если папка безопасна для очистки (выглядит как 1С-выгрузка)."""
        if not p.exists():
            return True, "пусто"
        if not p.is_dir():
            return False, "не папка"
        items = list(p.iterdir())
        if not items:
            return True, "пусто"
        if (p / "Configuration.xml").exists():
            return True, "найден Configuration.xml"
        foreign = [it.name for it in items if it.name not in self._CLEAR_KNOWN_NAMES]
        if not foreign:
            return True, "только 1С-папки"
        return False, f"в корне нестандартное: {', '.join(foreign[:3])}"

    def _clear_1c_dir(self, p: Path) -> tuple[int, str]:
        """Удаляет содержимое папки (но не саму папку)."""
        import shutil
        if not p.exists():
            return 0, "нет папки"
        deleted = 0
        for child in p.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                deleted += 1
            except Exception as e:
                return deleted, f"удалено {deleted}, не смогли удалить {child.name}: {e}"
        return deleted, f"удалено {deleted}"

    async def _db_dump(self) -> str:
        script = self._require_script("dump_script")
        cfg = self.cfg
        ext_src = Path(self.cfg.get("ext_src_path", ""))

        # Очистка ext_src перед выгрузкой. Без этого 1С перезапишет только
        # пересекающиеся файлы, и старые объекты (например удалённые в Конфигураторе
        # вручную) останутся как «файлы-сироты». Агент потом видит их через
        # list_ext_files и путается.
        cleared_msg = ""
        if ext_src.exists():
            safe, reason = self._is_safe_to_clear_1c_dir(ext_src)
            if safe:
                n_before = sum(1 for _ in ext_src.rglob("*"))
                if n_before > 0:
                    log.info("db_dump: очищаю %s (было %d элементов · %s)", ext_src, n_before, reason)
                    deleted, msg = self._clear_1c_dir(ext_src)
                    cleared_msg = f" · очистка: {msg}"
            else:
                log.warning("db_dump: НЕ очищаю %s (%s) — оставляю как есть", ext_src, reason)
                cleared_msg = f" · очистка пропущена ({reason})"

        log.info("db_dump: скрипт=%s ext_src=%s", script, ext_src)
        out = await run_powershell(
            script,
            "-V8Path",       cfg["v8_path"],
            "-InfoBasePath", cfg["base_path"],
            "-UserName",     cfg["username"],
            "-Password",     cfg["password"],
            "-ConfigDir",    cfg["ext_src_path"],
            "-Extension",    cfg["extension"],
            "-Mode",         "Full",
        )
        files = list(ext_src.rglob("*")) if ext_src.exists() else []
        return f"db_dump OK{cleared_msg}. ext_src: {ext_src} · файлов: {len(files)}\n{out[-800:]}"

    async def _db_load(self) -> str:
        script = self._require_script("load_script")
        cfg = self.cfg
        log.info("db_load: скрипт=%s ext_src=%s", script, cfg.get("ext_src_path"))
        out = await run_powershell(
            script,
            "-V8Path",       cfg["v8_path"],
            "-InfoBasePath", cfg["base_path"],
            "-UserName",     cfg["username"],
            "-Password",     cfg["password"],
            "-ConfigDir",    cfg["ext_src_path"],
            "-Extension",    cfg["extension"],
            "-UpdateDB",
            "-StrictLog",
        )
        return f"db_load OK\n{out[-800:]}"

    # ── Sprint 1 Step 2: Hot tools — обёртки над skill'ами ────────────────
    #
    # Универсальный runner для скилла из .claude/skills/<name>/scripts/<name>.ps1.
    # Используется специальными методами ниже (_form_*, _meta_*, _db_*).
    # Когда будет Sprint 1 Step 3 (Skill Registry) — этот же метод вызовется
    # из generic skill_run, без дополнительной обвязки.

    async def _run_skill_with_args(
        self,
        skill_name: str,
        *args: str,
        timeout: int = 600,
    ) -> str:
        """Generic runner: `.claude/skills/<skill>/scripts/<skill>.ps1` с
        произвольными CLI-параметрами PowerShell. Возвращает stdout скрипта.
        """
        script = self._skill_script(skill_name)
        return await run_powershell(script, *args, timeout=timeout)

    async def _syntax_check(
        self,
        target_path: str,
        *,
        timeout: int = 120,
    ) -> str:
        """Sprint 2 S2.1: проверка BSL через нативный BSL Language Server
        (без Docker). При отсутствии LS на машине — Python-fallback (грубая
        проверка балансировки блоков).

        Возвращает компактный сводный отчёт. Подробное сообщение в начале
        говорит каким режимом проверки воспользовались.
        """
        # Импорт лениво — bsl_ls живёт в agenter/app/, а desktop/main.py может
        # быть запущен из другого контекста (Tk-приложение десктопа).
        try:
            from bsl_ls import check_bsl_path, format_diagnostics_summary
        except ImportError:
            try:
                import sys as _sys
                from pathlib import Path as _P
                _sys.path.insert(0, str(_P(__file__).parent.parent / "app"))
                from bsl_ls import check_bsl_path, format_diagnostics_summary
            except Exception as e:
                return f"syntax_check: bsl_ls модуль недоступен ({e})"
        diags, mode = await asyncio.to_thread(
            check_bsl_path, target_path, timeout=timeout,
        )
        summary = format_diagnostics_summary(diags)
        return f"syntax_check [{mode}]:\n{summary}"

    async def _run_skill_by_path(
        self,
        script_path: str,
        *args: str,
        timeout: int = 600,
    ) -> str:
        """Generic runner с готовым путём к скрипту (произвольное имя файла).

        Используется ``skill_run`` через SkillRegistry — там путь известен,
        и он может не совпадать с именем скилла (например для form-remove
        скрипт называется ``remove-form.ps1``).

        Поддерживает .ps1 (через run_powershell) и .py (через Python).
        """
        from pathlib import Path as _P
        p = _P(script_path)
        if not p.exists():
            raise _ConfigError(f"Скрипт не найден: {script_path}")
        if p.suffix.lower() == ".ps1":
            return await run_powershell(str(p), *args, timeout=timeout)
        if p.suffix.lower() == ".py":
            # Python-скилл: запускаем тем же интерпретатором.
            import sys as _sys, asyncio as _asyncio
            cmd = [_sys.executable, str(p), *args]
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=timeout)
            except _asyncio.TimeoutError:
                proc.kill()
                raise _ConfigError(f"Скрипт превысил таймаут {timeout}s: {p.name}")
            txt = (stdout or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                raise _ConfigError(
                    f"Скрипт вернул код {proc.returncode}\n{txt[-2000:]}"
                )
            return txt
        raise _ConfigError(
            f"Неподдерживаемый тип скрипта: {p.suffix} (нужен .ps1 или .py)"
        )

    # ── form-* ────────────────────────────────────────────────────────────

    async def _form_info(
        self,
        form_path: str,
        expand: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        """Структура управляемой формы. Куда дешевле в turns, чем Read XML."""
        args = ["-FormPath", form_path]
        if expand: args.extend(["-Expand", expand])
        if limit:  args.extend(["-Limit", str(int(limit))])
        if offset: args.extend(["-Offset", str(int(offset))])
        out = await self._run_skill_with_args("form-info", *args)
        return f"form-info OK\n{out[-3000:]}"

    async def _form_validate(
        self,
        form_path: str,
        detailed: bool = False,
        max_errors: int = 30,
    ) -> str:
        """Валидация Form.xml ДО db_load — ловит DataPath-ошибки локально."""
        args = ["-FormPath", form_path]
        if detailed:           args.append("-Detailed")
        if max_errors != 30:   args.extend(["-MaxErrors", str(int(max_errors))])
        out = await self._run_skill_with_args("form-validate", *args)
        return f"form-validate OK\n{out[-3000:]}"

    async def _form_edit(self, form_path: str, json_path: str) -> str:
        """Добавление элементов/реквизитов/команд в готовый Form.xml."""
        if not form_path or not json_path:
            return "form-edit: оба параметра обязательны (form_path, json_path)"
        out = await self._run_skill_with_args(
            "form-edit",
            "-FormPath", form_path,
            "-JsonPath", json_path,
        )
        return f"form-edit OK\n{out[-2500:]}"

    async def _form_compile(
        self,
        output_path: str,
        json_path: str = "",
        from_object: bool = False,
    ) -> str:
        """Генерация Form.xml из JSON-DSL ИЛИ автогенерация из метаданных
        объекта (если from_object=True; json_path тогда игнорируется)."""
        if from_object:
            args = ["-FromObject", "-OutputPath", output_path]
        else:
            if not json_path:
                return "form-compile: укажи json_path или from_object=True"
            args = ["-JsonPath", json_path, "-OutputPath", output_path]
        out = await self._run_skill_with_args("form-compile", *args)
        return f"form-compile OK\n{out[-2500:]}"

    # ── meta-* ────────────────────────────────────────────────────────────

    async def _meta_info(
        self,
        object_path: str,
        mode: str = "overview",
        name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        """Сводка структуры объекта метаданных без чтения XML."""
        args = ["-ObjectPath", object_path]
        if mode and mode != "overview":
            args.extend(["-Mode", mode])
        if name:   args.extend(["-Name", name])
        if limit:  args.extend(["-Limit", str(int(limit))])
        if offset: args.extend(["-Offset", str(int(offset))])
        out = await self._run_skill_with_args("meta-info", *args)
        return f"meta-info OK\n{out[-3000:]}"

    async def _meta_validate(
        self,
        object_path: str,
        detailed: bool = False,
        max_errors: int = 30,
    ) -> str:
        """Локальная валидация объекта метаданных — ДО полной cfe_validate."""
        args = ["-ObjectPath", object_path]
        if detailed:         args.append("-Detailed")
        if max_errors != 30: args.extend(["-MaxErrors", str(int(max_errors))])
        out = await self._run_skill_with_args("meta-validate", *args)
        return f"meta-validate OK\n{out[-2500:]}"

    # ── subsystem-* ──────────────────────────────────────────────────────
    # Sprint 2 hotfix-5: подсистемы — частая операция (include в подсистему,
    # дочерние подсистемы, свойства). Без hot tool агент пытается Edit XML
    # вручную и ломает структуру (см. лог 2026-05-16: задача «Включи в
    # подсистему Финансы»). Hot tool делает добавление содержимого однострочной
    # операцией.

    async def _plan_task(
        self,
        task_id: str,
        stages: list[dict],
    ) -> str:
        """Sprint 4 S4.3: принимает план задачи от агента, валидирует,
        сохраняет в БД, возвращает форматированный план обратно.

        stages — список объектов с полями:
          • kind         — один из 22 STAGE_KIND (детерминированный enum)
          • description  — человекочитаемое описание стадии
          • args_hint    — опц. подсказка args для будущего вызова tool

        После plan_task на каждой стадии разрешён только expected_tool
        (см. is_tool_allowed_for_stage). Это и есть суть детерминированной
        диспетчеризации.
        """
        # Импорт лениво — task_planner живёт в agenter/app/
        try:
            from task_planner import (
                validate_stages, render_plan_for_agent, normalize_tool_name,
            )
        except ImportError:
            try:
                import sys as _sys
                from pathlib import Path as _P
                _sys.path.insert(0, str(_P(__file__).parent.parent / "app"))
                from task_planner import (
                    validate_stages, render_plan_for_agent, normalize_tool_name,
                )
            except Exception as e:
                return f"plan_task: модуль task_planner недоступен ({e})"

        parsed, errors = validate_stages(stages)
        if errors:
            return (
                "plan_task: план НЕ принят, ошибки валидации:\n  • "
                + "\n  • ".join(errors)
                + "\n\nИсправь и повтори plan_task."
            )

        # Сохраняем план в БД через прямой SQL — _save_task_stages живёт
        # в main.py, импорт оттуда создаёт циклическую зависимость.
        # Делаем то же самое локально.
        import sqlite3 as _sql, json as _json
        from datetime import datetime as _dt
        from pathlib import Path as _P
        db_path = _P(__file__).parent.parent / "app" / "agenter.db"
        now = _dt.utcnow().isoformat()
        conn = _sql.connect(str(db_path))
        try:
            conn.execute("DELETE FROM task_stages WHERE task_id=?", (task_id,))
            for s in parsed:
                args_json = _json.dumps(s.args_hint or {}, ensure_ascii=False)
                # Sprint 4 hotfix-6: первая стадия = 'in_progress' (а не 'pending').
                # Это даёт консистентную семантику для auto-advance:
                # current = in_progress → completed → next pending становится in_progress.
                init_status = "in_progress" if s.index == 1 else "pending"
                conn.execute(
                    "INSERT INTO task_stages "
                    "(task_id, stage_index, kind, description, expected_tool, "
                    " args_hint, status, started_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id, s.index, s.kind, s.description,
                        normalize_tool_name(s.expected_tool),
                        args_json, init_status,
                        now if s.index == 1 else None,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        # Возвращаем форматированный план обратно агенту — он увидит свой
        # же план как подтверждение и подсказку tool'ов для каждой стадии.
        text = render_plan_for_agent(parsed)
        return (
            f"План задачи принят ({len(parsed)} стадий). Дальше выполняй стадии "
            f"по порядку, на каждой вызывая ИМЕННО expected tool.\n\n{text}"
        )

    async def _subsystem_edit(
        self,
        subsystem_path: str,
        operation: str,
        value: str | None = None,
        no_validate: bool = False,
    ) -> str:
        """Точечная правка XML подсистемы.

        operation: add-content | remove-content | add-child | remove-child |
                   set-property
        value: строка ('Catalog.X') ИЛИ JSON-массив '["Catalog.X","Document.Y"]'
               для add/remove-content; имя для add/remove-child;
               JSON-объект {"name":"prop","value":"val"} для set-property.

        Скилл сам разбирается со структурой ChildObjects / Properties / Content,
        не требуя ручной правки XML.
        """
        if not subsystem_path or not operation:
            return "subsystem_edit: subsystem_path и operation обязательны"
        args = ["-SubsystemPath", subsystem_path, "-Operation", operation]
        if value is not None and value != "":
            args.extend(["-Value", str(value)])
        if no_validate:
            args.append("-NoValidate")
        out = await self._run_skill_with_args("subsystem-edit", *args)
        return f"subsystem_edit OK\n{out[-2000:]}"

    # ── db-* (open / update) ─────────────────────────────────────────────

    async def _db_update(
        self,
        dynamic: str | None = None,
        extension: str | None = None,
        all_extensions: bool = False,
    ) -> str:
        """UpdateDBCfg — применяет загруженную конфигурацию к БД.
        Все параметры подключения берутся из client_cfg (как у db_dump/db_load)."""
        cfg = self.cfg
        args = [
            "-V8Path",       cfg["v8_path"],
            "-InfoBasePath", cfg["base_path"],
            "-UserName",     cfg["username"],
            "-Password",     cfg["password"],
        ]
        if extension:
            args.extend(["-Extension", extension])
        elif all_extensions:
            args.append("-AllExtensions")
        elif cfg.get("extension"):
            # Типичный кейс: обновляем именно наше расширение.
            args.extend(["-Extension", cfg["extension"]])
        if dynamic in ("+", "-"):
            args.extend(["-Dynamic", dynamic])
        out = await self._run_skill_with_args("db-update", *args)
        return f"db-update OK\n{out[-1500:]}"

    async def _db_run(
        self,
        execute: str | None = None,
        url: str | None = None,
        c_param: str | None = None,
    ) -> str:
        """Запуск 1С:Предприятие в фоне (Start-Process без -Wait)."""
        cfg = self.cfg
        args = [
            "-V8Path",       cfg["v8_path"],
            "-InfoBasePath", cfg["base_path"],
            "-UserName",     cfg["username"],
            "-Password",     cfg["password"],
        ]
        if execute: args.extend(["-Execute", execute])
        if url:     args.extend(["-URL", url])
        if c_param: args.extend(["-CParam", c_param])
        out = await self._run_skill_with_args("db-run", *args)
        return f"db-run OK (started)\n{out[-800:]}"

    # --- Файловые операции ---

    def _resolve_path(self, path: str) -> Path:
        """Резолвит путь относительно ext_src/ или SCHEME/ (по префиксу)."""
        norm = path.replace("\\", "/")

        # SCHEME/ → scheme_path из конфига
        if norm.upper().startswith("SCHEME/"):
            scheme_raw = self.cfg.get("scheme_path", "").strip()
            if not scheme_raw:
                raise _ConfigError(
                    "scheme_path не задан в конфиге.\n"
                    "Укажите путь к SCHEME/ в мастере настройки Desktop-ассистента."
                )
            return Path(scheme_raw) / norm[7:]

        p = Path(path)
        if p.is_absolute():
            # Абсолютный путь разрешён только внутри ext_src или scheme_path
            ext_src = self._require_ext_src()
            scheme_raw = self.cfg.get("scheme_path", "").strip()
            allowed = [ext_src.resolve()]
            if scheme_raw:
                allowed.append(Path(scheme_raw).resolve())
            rp = p.resolve()
            if any(str(rp).startswith(str(a)) for a in allowed):
                return p
            raise PermissionError(f"Путь за пределами разрешённых папок: {path}")

        # Обычный относительный путь → ext_src
        ext_src = self._require_ext_src()
        resolved = ext_src / path
        try:
            resolved.resolve().relative_to(ext_src.resolve())
        except ValueError:
            raise PermissionError(f"Путь за пределами ext_src/: {path}")
        return resolved

    def _read_file(self, path: str) -> str:
        p = self._resolve_path(path)
        if not p.exists():
            raise FileNotFoundError(f"Файл не найден: {p}")
        content = p.read_text(encoding="utf-8-sig")
        log.info("read_file: %s (%d символов)", p, len(content))
        return content[:50_000]

    def _edit_file(self, path: str, old_str: str, new_str: str) -> str:
        p = self._resolve_path(path)
        if not p.exists():
            raise FileNotFoundError(f"Файл не найден: {p}")
        content = p.read_text(encoding="utf-8-sig")
        if old_str not in content:
            content_unix = content.replace("\r\n", "\n").replace("\r", "\n")
            old_unix = old_str.replace("\r\n", "\n").replace("\r", "\n")
            if old_unix in content_unix:
                new_content = content_unix.replace(old_unix, new_str, 1)
                p.write_text(new_content, encoding="utf-8")
                log.info("edit_file OK (unix lineends): %s", p)
                return f"edit_file OK: {p}"
            raise ValueError(f"old_str не найден в {p.name}")
        new_content = content.replace(old_str, new_str, 1)
        p.write_text(new_content, encoding="utf-8")
        log.info("edit_file OK: %s", p)
        return f"edit_file OK: {p}"

    def _write_file(self, path: str, content: str) -> str:
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if not p.exists():
            raise RuntimeError(f"write_file: файл не создан после записи: {p}")
        log.info("write_file OK: %s (%d символов)", p, len(content))
        return f"write_file OK: {p} ({len(content)} символов)"

    def _list_ext_files(self) -> str:
        ext_src = self._require_ext_src()
        files = sorted(
            str(f.relative_to(ext_src))
            for f in ext_src.rglob("*")
            if f.is_file()
        )
        header = f"ext_src: {ext_src} · файлов: {len(files)}"
        return header + ("\n" + "\n".join(files[:200]) if files else "\n(пусто)")

    def _get_sample_object(self, object_type: str) -> str:
        """Найти первый существующий объект нужного типа в ext_src."""
        ext_src = self._require_ext_src()
        type_to_folder = {
            "Catalog": "Catalogs",
            "Справочник": "Catalogs",
            "Document": "Documents",
            "Документ": "Documents",
            "InformationRegister": "InformationRegisters",
            "РегистрСведений": "InformationRegisters",
            "AccumulationRegister": "AccumulationRegisters",
            "РегистрНакопления": "AccumulationRegisters",
            "AccountingRegister": "AccountingRegisters",
            "РегистрБухгалтерии": "AccountingRegisters",
            "CommonModule": "CommonModules",
            "ОбщийМодуль": "CommonModules",
            "DataProcessor": "DataProcessors",
            "Обработка": "DataProcessors",
            "Report": "Reports",
            "Отчет": "Reports",
            "Enum": "Enums",
            "Перечисление": "Enums",
            "HTTPService": "HTTPServices",
        }
        folder_name = type_to_folder.get(object_type)
        if not folder_name:
            raise ValueError(
                f"Неизвестный тип: '{object_type}'. "
                f"Допустимые: {', '.join(sorted(set(type_to_folder.keys())))}"
            )
        folder = ext_src / folder_name
        if not folder.exists():
            return json.dumps(
                {"found": False, "message": f"В ext_src нет папки {folder_name}"},
                ensure_ascii=False,
            )
        for item in sorted(folder.iterdir()):
            if item.is_dir():
                xml_file = item / f"{item.name}.xml"
                if xml_file.exists():
                    content = xml_file.read_text(encoding="utf-8-sig")
                    log.info("get_sample_object: %s → %s", object_type, xml_file)
                    return json.dumps({
                        "found": True,
                        "name": item.name,
                        "path": str(xml_file.relative_to(ext_src)),
                        "xml": content[:8000],
                    }, ensure_ascii=False)
        return json.dumps(
            {"found": False, "message": f"В {folder_name} нет объектов"},
            ensure_ascii=False,
        )

    def _clone_object(self, source_path: str, new_name: str) -> str:
        """Клонировать объект: скопировать XML, заменить имя и все UUID."""
        import re
        import uuid as _uuid

        ext_src = self._require_ext_src()
        source = self._resolve_path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Исходный файл не найден: {source}")

        content = source.read_text(encoding="utf-8-sig")
        old_name = source.parent.name

        uuid_map: dict[str, str] = {}

        def _replace_uuid(m: re.Match) -> str:
            key = m.group(0).lower()
            if key not in uuid_map:
                uuid_map[key] = str(_uuid.uuid4())
            return uuid_map[key]

        content = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            _replace_uuid, content, flags=re.IGNORECASE,
        )
        content = content.replace(old_name, new_name)

        # Сохраняем рядом с образцом — та же папка типа объектов
        new_dir = source.parent.parent / new_name
        new_file = new_dir / f"{new_name}.xml"
        new_dir.mkdir(parents=True, exist_ok=True)
        new_file.write_text(content, encoding="utf-8")

        log.info("clone_object: %s → %s (%d UUID)", old_name, new_name, len(uuid_map))
        return json.dumps({
            "ok": True,
            "new_path": str(new_file.relative_to(ext_src)),
            "old_name": old_name,
            "new_name": new_name,
            "uuids_replaced": len(uuid_map),
        }, ensure_ascii=False)

    # ──────────────────────────────────────────────────────────────────
    # Подключённые скиллы 1С (см. agenter/scripts/<skill>/scripts/<skill>.ps1)
    # ──────────────────────────────────────────────────────────────────

    async def _meta_compile(self, definition) -> str:
        """Создание объекта метаданных по JSON-определению.
        definition: dict (один объект) или list[dict] (batch).
        Скрипт сам пишет XML и регистрирует объект в Configuration.xml."""
        if definition is None:
            raise ValueError("meta_compile: параметр 'definition' обязателен")

        # SDK передаёт definition как строку (MCP schema type=string) — парсим
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except json.JSONDecodeError as exc:
                raise ValueError(f"meta_compile: definition не является валидным JSON: {exc}") from exc

        # Sprint 2 S2.2: для batch'а — топологически сортируем по
        # cross-references. Если объект B ссылается на A в том же batch'е —
        # A создаётся первым. Без сортировки PS-скрипт мог упасть на forward ref.
        try:
            from tool_guards import topological_sort_meta_definitions
            sorted_def, sort_notes = topological_sort_meta_definitions(definition)
            if sort_notes:
                for note in sort_notes:
                    log.info("meta_compile: %s", note)
            definition = sorted_def
        except Exception as e:
            log.warning("meta_compile: topo-sort skipped: %s", e)

        ext_src = self._require_ext_src()
        script = self._skill_script("meta-compile")

        import tempfile
        # Сохраняем JSON во временный файл — скилл читает из него
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(definition, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name

        try:
            log.info("meta_compile: JSON=%s OutputDir=%s", tmp_path, ext_src)
            out = await run_powershell(
                script,
                "-JsonPath",  tmp_path,
                "-OutputDir", str(ext_src),
                timeout=180,
            )
            return f"meta_compile OK\n{out[-1500:]}"
        finally:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

    async def _meta_edit(self, object_path: str, definition: dict) -> str:
        """Редактирование существующего объекта метаданных через структурированный JSON.

        object_path: путь к объекту относительно ext_src/ или абсолютный.
                     Поддерживаются 3 формата раскладки:
                       Catalogs/Контрагенты            — без расширения
                       Catalogs/Контрагенты.xml        — плоский XML
                       Catalogs/Контрагенты/Контрагенты.xml — формат с папкой

        definition: dict с секциями add/modify/remove/set.
                    Передаётся в PowerShell-скилл через -DefinitionFile <temp.json>.
                    Никакой DSL-конвертации — JSON напрямую (PS-скилл сам читает).

                    Примеры:
                      {"add": {"attributes": [{"name": "Город", "type": "Строка(50)"}]}}
                      {"modify": {"properties": {"CodeLength": 11}}}
                      {"remove": {"attributes": ["СтароеПоле"]}}

        Валидация: имена объектов (NCName) проверяются ДО передачи в PS-скилл,
        чтобы LLM получил понятную ошибку и в БД не попадал мусор.
        """
        import json as _json
        import tempfile as _tempfile

        ext_src = self._require_ext_src()
        script = self._skill_script("meta-edit")

        # 1. Резолв пути объекта (плоский / папка)
        p = Path(object_path)
        if not p.is_absolute():
            p = ext_src / object_path
        resolved = _resolve_meta_object_path(p)
        if resolved is None:
            tried = [str(p), str(p) + ".xml", str(p / f"{p.name}.xml")]
            raise FileNotFoundError(
                "Объект не найден в ext_src. Проверено:\n  "
                + "\n  ".join(tried)
                + "\n\nЕсли объект ещё не заимствован — вызови cfe_borrow."
            )
        p = resolved

        # 2. Валидация — definition должен быть dict
        if not isinstance(definition, dict):
            raise ValueError(
                f"definition должен быть JSON-объектом (dict), получено: {type(definition).__name__}. "
                "Передавай как нативный dict, НЕ как строку."
            )

        # 3. Валидация имён всех создаваемых элементов
        name_errors = _validate_definition_names(definition)
        if name_errors:
            raise ValueError(
                "Имя реквизита/объекта не соответствует требованиям 1С (NCName):\n"
                + "\n".join(f"  • {e}" for e in name_errors)
                + "\n\nИмя должно: содержать только буквы (лат/кир), цифры и подчёркивание; "
                f"не начинаться с цифры; не содержать пробелов/скобок/спецсимволов; "
                f"быть не длиннее {_MAX_NAME_LEN} символов."
            )

        # 4. Запись definition в temp JSON-файл (UTF-8 БЕЗ BOM для PS Get-Content)
        json_text = _json.dumps(definition, ensure_ascii=False, indent=2)
        tmp = _tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="meta_edit_",
            encoding="utf-8", delete=False,
        )
        tmp.write(json_text)
        tmp.close()
        tmp_path = tmp.name

        try:
            log.info(
                "meta_edit: %s -DefinitionFile %s (size=%d chars)",
                p, tmp_path, len(json_text),
            )
            out = await run_powershell(
                script,
                "-DefinitionFile", tmp_path,
                "-ObjectPath",     str(p),
                timeout=120,
            )
            return f"meta_edit OK\n{out[-1500:]}"
        finally:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

    async def _cfe_borrow(self, object_name: str, borrow_main_attribute: str | None = None) -> str:
        """Заимствование объекта из основной конфигурации в расширение.
        object_name: 'Catalog.Контрагенты' или 'Catalog.Контрагенты.Form.ФормаЭлемента',
                     batch через ';;'.
        borrow_main_attribute: 'Form' / 'All' / None — для форм."""
        ext_src = self._require_ext_src()
        scheme_path = (self.cfg.get("scheme_path") or "").strip()
        if not scheme_path:
            raise _ConfigError(
                "Для cfe_borrow нужен scheme_path в config.json — это XML "
                "основной конфигурации, из которой заимствуем."
            )
        if not Path(scheme_path).exists():
            raise _ConfigError(f"scheme_path не существует: {scheme_path}")

        script = self._skill_script("cfe-borrow")
        args = [
            script,
            "-ExtensionPath", str(ext_src),
            "-ConfigPath",    scheme_path,
            "-Object",        object_name,
        ]
        if borrow_main_attribute:
            args.extend(["-BorrowMainAttribute", borrow_main_attribute])

        log.info("cfe_borrow: %s (BorrowMain=%s)", object_name, borrow_main_attribute)
        out = await run_powershell(*args, timeout=240)
        return f"cfe_borrow OK\n{out[-1500:]}"

    async def _cfe_patch_method(
        self,
        module_path: str,
        method_name: str,
        interceptor_type: str,
        context: str = "НаСервере",
        is_function: bool = False,
    ) -> str:
        """Создание перехватчика метода для заимствованного объекта.
        module_path: 'Catalog.X.ObjectModule' / 'Document.X.Form.Y' / 'CommonModule.X' / и т.д.
        method_name: имя оригинального метода
        interceptor_type: 'Before' / 'After' / 'ModificationAndControl'
        context: '&НаСервере' (по умолчанию) или '&НаКлиенте'
        is_function: True если перехватываемый метод — функция (нужен Возврат)"""
        if interceptor_type not in ("Before", "After", "ModificationAndControl"):
            raise ValueError(
                f"cfe_patch_method: interceptor_type должен быть Before/After/ModificationAndControl, получено '{interceptor_type}'"
            )

        ext_src = self._require_ext_src()
        script = self._skill_script("cfe-patch-method")
        args = [
            script,
            "-ExtensionPath",    str(ext_src),
            "-ModulePath",       module_path,
            "-MethodName",       method_name,
            "-InterceptorType",  interceptor_type,
            "-Context",          context,
        ]
        if is_function:
            args.append("-IsFunction")

        log.info("cfe_patch_method: %s.%s [%s]", module_path, method_name, interceptor_type)
        out = await run_powershell(*args, timeout=60)
        return f"cfe_patch_method OK\n{out[-1000:]}"

    async def _cfe_validate(self) -> str:
        """Полная валидация расширения (XML, состав, заимствованные объекты).
        Вызывать перед db_load.

        Состоит из двух частей:
        1) cfe-validate.ps1 — структурный CFE-валидатор (13 проверок: ObjectBelonging,
           ExtendedConfigurationObject, ChildObjects, Borrowed forms, и т.п.)
        2) cfe_validate_xml.py — дополнительные XML-проверки, которые ловят
           конкретные ошибки db_load: Help/ru.html, СКД-шаблоны (2 файла + role),
           неподдерживаемые свойства (Leading/Recorder), '--' в комментариях,
           согласованность Subsystems.
        """
        import asyncio as _asyncio
        ext_src = self._require_ext_src()
        script = self._skill_script("cfe-validate")
        log.info("cfe_validate: %s", ext_src)
        ps_out = await run_powershell(
            script,
            "-ExtensionPath", str(ext_src),
            timeout=180,
        )

        # Дополнительные XML-проверки (Python, CPU-bound — выносим в thread).
        # Импортируем лениво, чтобы запуск agenter не падал при отсутствии модуля.
        try:
            # cfe_validate_xml лежит в agenter/app, который должен быть в sys.path
            # (добавляется в _imports.py при загрузке executor).
            from cfe_validate_xml import validate_extension_xml
            xml_result = await _asyncio.to_thread(
                validate_extension_xml, str(ext_src)
            )
            extras_text = xml_result.get("text", "")
            extras_errors = xml_result.get("errors", 0)
            log.info(
                "cfe_validate XML extras: %d errors, %d warnings",
                extras_errors, xml_result.get("warnings", 0),
            )
        except Exception as e:
            log.warning("cfe_validate_xml не запустился: %s", e)
            extras_text = f"[WARN]  Дополнительные XML-проверки не запустились: {e}"

        # Объединяем оба отчёта. PS-вывод обрезаем чтобы оставить место для extras.
        combined = (ps_out[-2200:] if ps_out else "") + "\n\n" + extras_text
        return combined[-4000:]

    def _validate_ext_structure(self) -> str:
        """Проверить соответствие Configuration.xml реальным файлам ext_src.
        Возвращает список проблем; агент должен исправить их через edit_file перед db_load."""
        ext_src = self._require_ext_src()
        config_xml = ext_src / "Configuration.xml"

        if not config_xml.exists():
            return json.dumps(
                {"ok": False, "error": "Configuration.xml не найден в ext_src"},
                ensure_ascii=False,
            )

        # Папки → тип объекта 1С
        FOLDER_TYPE = {
            "Catalogs": "Catalog",
            "Documents": "Document",
            "InformationRegisters": "InformationRegister",
            "AccumulationRegisters": "AccumulationRegister",
            "AccountingRegisters": "AccountingRegister",
            "CommonModules": "CommonModule",
            "DataProcessors": "DataProcessor",
            "Reports": "Report",
            "Enums": "Enum",
            "HTTPServices": "HTTPService",
            "ExchangePlans": "ExchangePlan",
            "ChartsOfAccounts": "ChartOfAccounts",
            "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
        }

        # Сканируем реальную структуру ext_src
        real: dict[str, dict] = {}  # name → {folder, xml_ok, path}
        for folder_name in FOLDER_TYPE:
            folder = ext_src / folder_name
            if not folder.exists():
                continue
            for item in sorted(folder.iterdir()):
                if not item.is_dir():
                    continue
                xml_file = item / f"{item.name}.xml"
                real[item.name] = {
                    "folder": folder_name,
                    "type": FOLDER_TYPE[folder_name],
                    "xml_exists": xml_file.exists(),
                    "xml_path": f"{folder_name}/{item.name}/{item.name}.xml",
                }

        config_text = config_xml.read_text(encoding="utf-8-sig")
        issues: list[dict] = []

        # Объекты в ext_src — проверяем что XML файл на месте
        for name, info in real.items():
            if not info["xml_exists"]:
                issues.append({
                    "severity": "ERROR",
                    "kind": "missing_xml",
                    "object": name,
                    "message": f"Папка {info['folder']}/{name} существует, но XML-файл {info['xml_path']} отсутствует",
                })

        # Объекты в ext_src — проверяем что они зарегистрированы в Configuration.xml
        for name, info in real.items():
            if name not in config_text:
                issues.append({
                    "severity": "WARNING",
                    "kind": "not_in_config",
                    "object": name,
                    "folder": info["folder"],
                    "message": f"Объект '{name}' ({info['type']}) есть в ext_src, но НЕ найден в Configuration.xml",
                    "action": f"Добавить <{info['type']}>{name}</{info['type']}> в соответствующую секцию Configuration.xml",
                })

        # Ищем ссылки в Configuration.xml на несуществующие объекты
        import re
        for folder_name, type_name in FOLDER_TYPE.items():
            for m in re.finditer(rf"<{type_name}>([^<]+)</{type_name}>", config_text):
                obj_name = m.group(1).strip()
                if obj_name and obj_name not in real:
                    issues.append({
                        "severity": "ERROR",
                        "kind": "dangling_ref",
                        "object": obj_name,
                        "type": type_name,
                        "message": f"Configuration.xml ссылается на {type_name} '{obj_name}', но папки {folder_name}/{obj_name} не существует",
                        "action": f"Удалить строку <{type_name}>{obj_name}</{type_name}> из Configuration.xml",
                    })

        errors = [i for i in issues if i["severity"] == "ERROR"]
        warnings = [i for i in issues if i["severity"] == "WARNING"]
        ok = len(errors) == 0

        log.info("validate_ext_structure: объектов=%d, ошибок=%d, предупреждений=%d",
                 len(real), len(errors), len(warnings))

        return json.dumps({
            "ok": ok,
            "ext_src": str(ext_src),
            "objects_found": len(real),
            "real_objects": [f"{v['folder']}/{k}" for k, v in real.items()],
            "errors": errors,
            "warnings": warnings,
            "summary": (
                "Структура корректна — можно запускать db_load" if ok
                else f"Найдено {len(errors)} критических ошибок — исправить перед db_load"
            ),
        }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# WebSocket клиент с автопереподключением
# ---------------------------------------------------------------------------

class AgentWSClient:
    RECONNECT_DELAY_INIT = 5
    RECONNECT_DELAY_MAX = 60
    HEARTBEAT_INTERVAL = 30

    def __init__(self, url: str, executor: ToolExecutor, cfg: dict | None = None):
        self.url = url
        self.executor = executor
        self.cfg = cfg or {}
        self._ws = None
        self._reconnect_delay = self.RECONNECT_DELAY_INIT

    async def run(self):
        log.info("Подключаюсь к backend: %s", self.url)
        while True:
            try:
                await self._connect_and_loop()
                self._reconnect_delay = self.RECONNECT_DELAY_INIT
            except Exception as exc:
                log.warning("WS ошибка: %s — повтор через %ds", exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self.RECONNECT_DELAY_MAX)

    async def _connect_and_loop(self):
        async with websockets.connect(
            self.url,
            ping_interval=self.HEARTBEAT_INTERVAL,
            ping_timeout=60,
            open_timeout=30,
        ) as ws:
            self._ws = ws
            log.info("✓ Подключён к backend")
            # Отправляем конфиг клиента — бэкенд вставит его в system prompt
            _cfg_safe = {k: v for k, v in self.cfg.items() if k != "password"}
            await ws.send(json.dumps({
                "type": "hello", "version": "1.0.0", "config": _cfg_safe
            }))

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "tool_call":
                    asyncio.create_task(self._handle_tool_call(ws, msg))
                elif msg_type == "pong":
                    pass  # heartbeat ответ

    async def _handle_tool_call(self, ws, msg: dict):
        call_id = msg["call_id"]
        tool = msg["tool"]
        params = msg.get("params", {})

        log.info("tool_call: %s %s", tool, str(params)[:100])
        try:
            result = await self.executor.execute(tool, params)
            response = {
                "type": "tool_result",
                "call_id": call_id,
                "ok": True,
                "result": result,
            }
            log.info("tool_result OK: %s (%d символов)", tool, len(result))
        except Exception as exc:
            err = str(exc)
            log.error("tool_result ERROR: %s — %s", tool, err)
            response = {
                "type": "tool_result",
                "call_id": call_id,
                "ok": False,
                "error": err,
            }

        try:
            await ws.send(json.dumps(response, ensure_ascii=False))
        except ConnectionClosed:
            log.warning("WS закрыт при отправке tool_result %s", call_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    cfg = load_config()
    bsl = BslAtlasClient(cfg["bsl_atlas_url"])
    executor = ToolExecutor(cfg, bsl)

    log.info("ext_src: %s", cfg["ext_src_path"])
    log.info("BSL Atlas: %s", cfg["bsl_atlas_url"])
    log.info("Backend: %s", cfg["backend_ws_url"])

    # Проверим BSL Atlas при старте
    try:
        await bsl.ensure_session()
        log.info("✓ BSL Atlas доступен")
    except Exception as e:
        log.warning("⚠ BSL Atlas недоступен: %s", e)

    client = AgentWSClient(cfg["backend_ws_url"], executor)
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
