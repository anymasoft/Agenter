"""
Операции вне LLM-цикла (выгрузка/индексация/загрузка/создание расширения).
Диспетчируются из main._run_operation по имени операции.

Каждая функция:
- принимает (cfg: dict, on_log: Callable[[str, str], Awaitable[None]])
- может посылать промежуточные логи через on_log(text, meta)
- возвращает {"info": str, "tail": str} для отображения результата
- бросает Exception при ошибке (текст ошибки уже humanized через humanize_1c_error)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from _imports import run_powershell

LogFn = Callable[[str, str], Awaitable[None]]


def _require(cfg: dict, key: str, what: str) -> str:
    v = (cfg.get(key) or "").strip()
    if not v:
        raise RuntimeError(f"В config.json не задан '{key}' ({what}). Открой Настройки и заполни.")
    return v


def _file_exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except Exception:
        return False


def _count_files(folder: str, pattern: str = "*") -> int:
    p = Path(folder)
    if not p.exists():
        return 0
    return sum(1 for _ in p.rglob(pattern))


def _dir_size_bytes(folder: str) -> int:
    """Суммарный размер всех файлов в папке (рекурсивно). 0 если папки нет
    или нет доступа. Не падает на отдельных недоступных файлах."""
    p = Path(folder)
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            # Файл могли удалить во время обхода, или нет прав — пропускаем
            continue
    return total


def _bytes_to_mb(n: int) -> float:
    """Перевод в МБ с округлением до десятых."""
    return round(n / 1024 / 1024, 1)


def _chroma_total(chroma) -> int | None:
    """Суммарное число документов в коллекциях ChromaDB из /health.

    Нужно фолбэку ожидания reindex (старый BSL Atlas без флага in_progress):
    во время векторной индексации это число растёт, а по завершении замирает.
    """
    if not isinstance(chroma, dict):
        return None
    total = 0
    for v in chroma.values():
        if isinstance(v, (int, float)):
            total += int(v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, (int, float)):
                    total += int(vv)
    return total


# Стандартные папки в корне XML-выгрузки конфигурации/расширения 1С.
# Используется в safety-check перед очисткой целевой папки.
_KNOWN_1C_DIRS: set[str] = {
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
    # Файлы (не папки) в корне выгрузки:
    "Configuration.xml", "ParentConfigurations.bin",
    "ConfigDumpInfo.xml", "Configuration.xml.bak",
}


def _is_safe_to_clear(p: Path) -> tuple[bool, str]:
    """Можно ли безопасно стереть содержимое папки?
    True если папка пуста, не существует, или содержит только стандартные
    1С-объекты в корне. False для произвольных путей (защита от опечатки).

    Возвращает (safe, reason).
    """
    if not p.exists():
        return True, "папка не существует"
    if not p.is_dir():
        return False, f"это не папка: {p}"

    items = list(p.iterdir())
    if not items:
        return True, "папка пуста"

    if (p / "Configuration.xml").exists():
        return True, "найден Configuration.xml — это 1С-выгрузка"

    foreign = [it.name for it in items if it.name not in _KNOWN_1C_DIRS]
    if not foreign:
        return True, "в корне только стандартные 1С-папки"

    return False, f"в корне нестандартные элементы: {', '.join(foreign[:5])}"


def _clear_dump_dir(p: Path) -> tuple[int, str]:
    """Удаляет содержимое папки (но не саму папку).
    Возвращает (count_deleted, message). При ошибке внутри отдельного
    файла — продолжает, общее count показывает сколько удалось."""
    import shutil

    if not p.exists():
        return 0, "не было что удалять"

    deleted = 0
    for child in p.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=False)
            else:
                child.unlink()
            deleted += 1
        except Exception as e:
            # Файлы могут быть открыты другим процессом (BSL Atlas индексирует)
            # — не валим всю операцию, просто пропускаем.
            return deleted, f"удалено {deleted}, не получилось удалить {child.name}: {e}"

    return deleted, f"удалено {deleted} элементов"


# ──────────────────────────────────────────────────────────────────────────
# Humanizer ошибок 1С — паттерны известных проблем
# ──────────────────────────────────────────────────────────────────────────

# (regex, обработчик) — первый совпавший паттерн выигрывает.
# Обработчик принимает (match, cfg) и возвращает строку.
_ERROR_PATTERNS: list[tuple[re.Pattern, Callable[[re.Match, dict], str]]] = [
    (
        re.compile(r"ошибка\s+блокировки\s+информационной\s+базы\s+для\s+конфигурирования", re.IGNORECASE),
        lambda m, cfg: (
            "База 1С заблокирована: в ней уже открыт Конфигуратор (или другой "
            "сеанс монопольно владеет базой).\n"
            "\n"
            "Конфигуратор 1С нельзя открывать одновременно с операциями выгрузки/"
            "загрузки расширения — они требуют исключительный доступ к базе.\n"
            "\n"
            "Что сделать:\n"
            "1. Закрой Конфигуратор (если он был открыт для проверки)\n"
            "2. Закрой все клиенты «1С:Предприятие» если они работают с этой базой\n"
            "3. Проверь нет ли висящих процессов 1cv8.exe в Диспетчере задач\n"
            "4. Повтори задачу"
        ),
    ),
    (
        re.compile(r"Пользователь ИБ не идентифицирован", re.IGNORECASE),
        lambda m, cfg: (
            "Не удалось войти в базу 1С — пользователь не идентифицирован.\n"
            "\n"
            "Возможные причины:\n"
            "• Указан неверный пароль (или пароль не указан, а в базе он установлен)\n"
            "• Указан неверный логин\n"
            "• У этого пользователя нет права на вход в Конфигуратор\n"
            "\n"
            f"Текущие настройки: логин «{cfg.get('username', '')}», "
            f"пароль {'установлен' if cfg.get('password') else 'НЕ задан'}.\n"
            "\n"
            "Действие: открой Настройки (шестерёнка слева внизу) → проверь поля "
            "«Логин 1С» и «Пароль 1С»."
        ),
    ),
    (
        re.compile(r"(не\s+удается|невозможно)\s+открыть\s+файл\s+базы", re.IGNORECASE),
        lambda m, cfg: (
            "Не удалось открыть файл базы 1С — база занята другим процессом.\n"
            "\n"
            "Действие: закрой все запущенные клиенты 1С (Предприятие, Конфигуратор) "
            "и повтори операцию."
        ),
    ),
    (
        re.compile(r"внутри\s+(базы|информационной\s+базы)\s+существуют?\s+(другие\s+)?сеансы?", re.IGNORECASE),
        lambda m, cfg: (
            "База занята другими сеансами 1С.\n"
            "\n"
            "Действие: закрой все клиенты 1С (Предприятие, Конфигуратор) и повтори "
            "операцию. Если есть фоновые задания — дождись завершения или прерви их."
        ),
    ),
    (
        re.compile(r"расширение\s+конфигурации\s+(.+?)\s+не\s+(найдено|существует)", re.IGNORECASE),
        lambda m, cfg: (
            f"Расширение «{cfg.get('extension', m.group(1))}» не найдено в этой базе 1С.\n"
            "\n"
            "Возможные действия:\n"
            "• Проверить имя расширения в Настройках (точное совпадение, регистр важен)\n"
            "• Создать расширение в базе через кнопку «Создать расширение» "
            "(появится в следующем микрошаге)\n"
            "• Создать расширение вручную в Конфигураторе 1С"
        ),
    ),
    (
        re.compile(r"файл\s+объекта\s+не\s+существует\s*[-:]\s*(.+?)(?:\n|$)", re.IGNORECASE),
        lambda m, cfg: (
            f"Несогласованность XML расширения: Configuration.xml ссылается на файл "
            f"«{m.group(1).strip()}», которого нет на диске.\n"
            "\n"
            "Это обычно происходит когда агент создал объект, добавил его в "
            "Configuration.xml, но не создал XML-файл. Решается через ручную "
            "правку Configuration.xml или повторный запуск задачи."
        ),
    ),
    (
        re.compile(r"конфигурация\s+(базы\s+данных\s+)?(не\s+соответствует|изменена)", re.IGNORECASE),
        lambda m, cfg: (
            "Конфигурация в файлах отличается от конфигурации БД, требуется "
            "обновление (UpdateDBCfg).\n"
            "\n"
            "Действие: нажми кнопку «Загрузить в БД» в правой панели — это применит "
            "изменения. Если не помогает — открой Конфигуратор и сделай Обновление "
            "конфигурации базы данных (F7)."
        ),
    ),
    (
        re.compile(r"(не\s+удается|невозможно)\s+(соединиться|подключиться)\s+(с|к)\s+сервер", re.IGNORECASE),
        lambda m, cfg: (
            "Не удалось подключиться к серверу 1С.\n"
            "\n"
            "Действие: проверь что сервер 1С работает и доступен по сети. "
            "Открой Настройки → проверь поле «Путь к информационной базе»."
        ),
    ),
]


def humanize_1c_error(raw: str, cfg: dict) -> str:
    """Превращает stderr 1С в человекочитаемое сообщение.
    Если паттерн не распознан — возвращает оригинальный текст с заголовком.
    Публичная функция — используется и из ops (правая панель),
    и из orchestrator (LLM tool calls)."""
    if not raw:
        return "Операция завершилась с ошибкой без описания."

    for pattern, fn in _ERROR_PATTERNS:
        m = pattern.search(raw)
        if m:
            return fn(m, cfg)

    # Не распознали — обрезаем PowerShell-обёртку и возвращаем суть.
    # Часто полезное находится между "--- Log ---" и "--- End ---"
    log_match = re.search(r"---\s*Log\s*---\s*(.+?)\s*---\s*End\s*---", raw, re.DOTALL | re.IGNORECASE)
    if log_match:
        inner = log_match.group(1).strip()
        if inner and len(inner) < 800:
            return f"Ошибка 1С:\n\n{inner}\n\n(если непонятно — пришли этот текст в поддержку)"

    return f"Операция завершилась с ошибкой. Подробности:\n\n{raw}"


async def _run_ps_humanized(cfg: dict, *args, **kwargs) -> str:
    """Обёртка над run_powershell которая humanize'ит ошибки 1С."""
    try:
        return await run_powershell(*args, **kwargs)
    except RuntimeError as e:
        raise RuntimeError(humanize_1c_error(str(e), cfg)) from e


def _is_extension_absent(err_text: str) -> bool:
    """True, если ошибка означает «такого расширения нет в базе» (а не реальный
    сбой). Ловит и сырой текст 1С, и уже humanize'нутое сообщение."""
    t = (err_text or "").lower()
    if "не найдено в этой базе" in t:          # humanize'нутая формулировка
        return True
    if re.search(r"расширени\w*\s+конфигурации\s+.+?\s+не\s+(найден|существ)", t):
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# Проверка авторизации в 1С (используется в POST /config)
# ──────────────────────────────────────────────────────────────────────────

async def reindex_bsl_atlas(cfg: dict, on_log: LogFn, *, force: bool = False) -> dict[str, Any]:
    """Триггерит переиндексацию BSL Atlas через HTTP /reindex.

    force=False → инкрементально (только изменённые файлы) — для лёгкой
    авто-сверки. force=True → ПОЛНАЯ пересборка индекса с нуля — обязательно
    при СМЕНЕ базы 1С: инкрементальная сверка не распознаёт оптом подменённую
    конфигурацию и индекс остаётся от старой базы.

    Важно: BSL Atlas индексирует свою конфигурированную папку (SOURCE_PATH из
    его .env), а не наш scheme_path напрямую. Эта функция говорит ему
    «переиндексируй то, что у тебя настроено». Если SOURCE_PATH ≠ scheme_path
    (например после смены базы пути разошлись) — предупреждаем в логе.
    """
    import json as _json
    import aiohttp as _aiohttp

    url = (cfg.get("bsl_atlas_url") or "").rstrip("/")
    if not url:
        raise RuntimeError("URL BSL Atlas не задан. Открой Настройки и заполни поле «URL BSL Atlas».")

    await on_log(f"Подключаюсь к BSL Atlas: {url}", "")

    import asyncio as _asyncio
    summary = "переиндексация запущена"
    detail = ""
    stats: dict[str, Any] = {}

    timeout_total = _aiohttp.ClientTimeout(total=1800)  # 30 минут
    async with _aiohttp.ClientSession(timeout=timeout_total) as session:
        # BSL Atlas v2.0.0: прямой HTTP-эндпоинт POST /reindex (фоновая задача).
        # force=false → инкрементально (только изменённые файлы);
        # force=true  → полная пересборка с нуля (нужно при смене базы).
        mode = "полная пересборка" if force else "инкрементально"
        await on_log(f"Запускаю reindex (POST /reindex, {mode})…", f"force={force}")
        try:
            async with session.post(
                f"{url}/reindex",
                json={"force": force},
                timeout=_aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"BSL Atlas /reindex вернул HTTP {resp.status}: {body[:200]}"
                    )
                try:
                    started = _json.loads(body)
                except _json.JSONDecodeError:
                    started = {"message": body[:200]}
        except _aiohttp.ClientError as e:
            raise RuntimeError(f"Не удалось подключиться к BSL Atlas ({url}): {e}")

        detail = str(started.get("message", "")).strip()
        await on_log(f"BSL Atlas: {detail or 'reindex запущен'}", "")

        # Переиндексация идёт ФОНОМ внутри BSL Atlas (Starlette BackgroundTask),
        # ответ POST /reindex приходит мгновенно. Раньше мы выходили по первому
        # же /health, где sqlite.symbols != None — но это поле непустое ВСЕГДА
        # (отдаёт старый/частичный индекс), поэтому операция рапортовала
        # «готово» уже через ~1 сек: спиннер в UI гас, а индексация реально шла
        # ещё минуты (видно в Диспетчере задач). Теперь ждём, пока BSL Atlas сам
        # не сообщит reindex.in_progress == False — честный спиннер на всё время.
        import time as _time
        deadline = _time.monotonic() + 1700  # < session total(1800) с запасом на хвост
        saw_in_progress = False
        last_report = 0.0
        last_counts = None
        stable_polls = 0
        poll = 0
        while _time.monotonic() < deadline:
            poll += 1
            await _asyncio.sleep(2.0)
            try:
                async with session.get(
                    f"{url}/health", timeout=_aiohttp.ClientTimeout(total=5)
                ) as h:
                    hd = await h.json()
            except Exception:
                continue

            sq = (hd or {}).get("sqlite") or {}
            if sq.get("symbols") is not None:
                stats["symbols_count"] = sq.get("symbols")
                stats["objects_count"] = sq.get("objects")
                summary = f"{sq.get('symbols')} символов, {sq.get('objects')} объектов"

            rx = (hd or {}).get("reindex")
            if isinstance(rx, dict) and "in_progress" in rx:
                # Новый BSL Atlas: точный сигнал о фоновой индексации.
                if rx.get("in_progress"):
                    saw_in_progress = True
                    now = _time.monotonic()
                    if now - last_report >= 4.0:
                        last_report = now
                        phase = rx.get("phase") or rx.get("mode") or ""
                        cnt = sq.get("symbols")
                        await on_log(
                            "Индексация идёт…" + (f" ({phase})" if phase else ""),
                            (f"{cnt} символов" if cnt is not None else ""),
                        )
                    continue
                # in_progress == False
                if saw_in_progress or poll >= 2:
                    break  # завершилось (или быстрый инкрементальный reindex)
            else:
                # Старый BSL Atlas без флага: эвристика стабилизации счётчиков,
                # чтобы не рапортовать «готово» мгновенно и не зависнуть навсегда.
                cur = (sq.get("symbols"), sq.get("objects"),
                       _chroma_total((hd or {}).get("chromadb")))
                stable_polls = stable_polls + 1 if cur == last_counts else 0
                last_counts = cur
                now = _time.monotonic()
                if now - last_report >= 4.0:
                    last_report = now
                    await on_log("Индексация идёт…", f"{sq.get('symbols')} символов")
                # счётчики не меняются ~6 сек и индекс непустой → считаем готовым
                if stable_polls >= 3 and sq.get("symbols") is not None:
                    break
        else:
            await on_log("Истёк лимит ожидания reindex (30 мин) — проверь BSL Atlas", "")

    # Размер SQLite-индекса BSL Atlas (если доступен по умолчанию)
    db_candidates = [
        Path("D:/CURSORIC/_data/bsl-atlas-index/bsl_index.db"),
    ]
    for cand in db_candidates:
        try:
            if cand.exists():
                stats["db_size_mb"] = _bytes_to_mb(cand.stat().st_size)
                stats["db_path"] = str(cand)
                break
        except OSError:
            continue

    stats["url"] = url

    return {"info": summary, "tail": detail[:800], "stats": stats}


async def test_1c_auth(cfg: dict) -> dict:
    """Лёгкая проверка входа в 1С через db-dump-xml -Mode UpdateInfo.
    Это самая дешёвая команда, требующая логин: 1С только обновит
    ConfigDumpInfo.xml (метаданные о последней выгрузке).

    Возвращает:
      { "ok": True,  "message": "Авторизация в 1С прошла успешно" }
      { "ok": False, "message": <человекочитаемая>, "raw": <stderr> }
    """
    script  = (cfg.get("dump_script") or "").strip()
    v8_path = (cfg.get("v8_path") or "").strip()
    base    = (cfg.get("base_path") or "").strip()
    ext_src = (cfg.get("ext_src_path") or "").strip()

    missing = [k for k, v in {
        "v8_path": v8_path, "base_path": base,
        "ext_src_path": ext_src, "dump_script": script,
    }.items() if not v]
    if missing:
        return {
            "ok": False,
            "message": f"Не заданы обязательные поля: {', '.join(missing)}. Заполни их в Настройках.",
        }

    if not Path(script).exists():
        return {"ok": False, "message": f"Скрипт не найден: {script}"}

    # ConfigDir должен существовать (создадим если нет — UpdateInfo не разрушает)
    Path(ext_src).mkdir(parents=True, exist_ok=True)

    try:
        await run_powershell(
            script,
            "-V8Path",       v8_path,
            "-InfoBasePath", base,
            "-UserName",     cfg.get("username", ""),
            "-Password",     cfg.get("password", ""),
            "-ConfigDir",    ext_src,
            "-Mode",         "UpdateInfo",
            timeout=120,  # 2 мин — UpdateInfo это просто запуск 1С + обновление одного файла
        )
        return {"ok": True, "message": "Авторизация в 1С прошла успешно"}
    except RuntimeError as e:
        raw = str(e)
        return {
            "ok": False,
            "message": humanize_1c_error(raw, cfg),
            "raw": raw,
        }


# ──────────────────────────────────────────────────────────────────────────
# 1. Выгрузка расширения (то что уже было в _run_operation)
# ──────────────────────────────────────────────────────────────────────────

async def dump_extension(cfg: dict, on_log: LogFn) -> dict[str, Any]:
    """Выгружает указанное расширение в ext_src_path."""
    script   = _require(cfg, "dump_script", "путь к скрипту db-dump-xml.ps1")
    ext_src  = _require(cfg, "ext_src_path", "папка ext_src/")
    ext_name = _require(cfg, "extension", "имя расширения")
    v8_path  = _require(cfg, "v8_path", "путь к платформе 1С")
    base     = _require(cfg, "base_path", "путь к базе 1С")

    if not _file_exists(script):
        raise RuntimeError(f"Скрипт не найден: {script}")
    Path(ext_src).mkdir(parents=True, exist_ok=True)

    # Очищаем папку перед выгрузкой — иначе 1С перезапишет только пересекающиеся
    # файлы, а остатки от другого расширения / прошлой версии останутся.
    ext_path = Path(ext_src)
    safe, reason = _is_safe_to_clear(ext_path)
    if safe:
        n_before = _count_files(ext_src, "*")
        if n_before > 0:
            await on_log(f"Очищаю {ext_src} перед свежей выгрузкой", f"{reason}")
            deleted, msg = _clear_dump_dir(ext_path)
            await on_log(f"Очистка: {msg}", "")
    else:
        await on_log(f"ВНИМАНИЕ: папку не очищаю автоматически", reason)
        await on_log("Выгрузка может оставить файлы от прошлой версии. Удали их вручную если нужна чистая выгрузка.", "")

    await on_log(f"db-dump-xml -Extension «{ext_name}»", f"→ {ext_src}")

    try:
        out = await _run_ps_humanized(
            cfg,
            script,
            "-V8Path",       v8_path,
            "-InfoBasePath", base,
            "-UserName",     cfg.get("username", ""),
            "-Password",     cfg.get("password", ""),
            "-ConfigDir",    ext_src,
            "-Extension",    ext_name,
            "-Mode",         "Full",
            timeout=600,  # 10 минут — расширения обычно небольшие
        )
    except RuntimeError as e:
        # База без этого расширения — это НЕ сбой пайплайна (частый случай для
        # свежей/типовой базы). Не валим операцию красной ошибкой, а мягко
        # пропускаем: с основной конфигурацией работать всё равно можно.
        if _is_extension_absent(str(e)):
            await on_log(
                f"Расширение «{ext_name}» не найдено в базе — пропускаю",
                "норма для базы без расширений; работа с конфигурацией доступна",
            )
            return {
                "info": f"расширение «{ext_name}» отсутствует в базе — пропущено",
                "skipped": True,
                "tail": "",
                "stats": {
                    "ext_name":    ext_name,
                    "xml_count":   0,
                    "files_count": 0,
                    "size_mb":     0,
                    "absent":      True,
                    "path":        str(Path(ext_src).resolve()),
                },
            }
        raise

    xml_count = _count_files(ext_src, "*.xml")
    files_count = _count_files(ext_src, "*")
    size_mb = _bytes_to_mb(_dir_size_bytes(ext_src))
    info = f"{xml_count} XML, {files_count} файлов"

    return {
        "info": info,
        "tail": (out or "")[-800:],
        "stats": {
            "ext_name":    ext_name,
            "xml_count":   xml_count,
            "files_count": files_count,
            "size_mb":     size_mb,
            "path":        str(Path(ext_src).resolve()),
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# 2. Выгрузка основной конфигурации (SCHEME) — БЕЗ -Extension
# ──────────────────────────────────────────────────────────────────────────

async def dump_config(cfg: dict, on_log: LogFn) -> dict[str, Any]:
    """Выгружает основную конфигурацию 1С в scheme_path (без -Extension)."""
    script  = _require(cfg, "dump_script", "путь к скрипту db-dump-xml.ps1")
    scheme  = _require(cfg, "scheme_path", "папка SCHEME для выгрузки конфигурации")
    v8_path = _require(cfg, "v8_path", "путь к платформе 1С")
    base    = _require(cfg, "base_path", "путь к базе 1С")

    if not _file_exists(script):
        raise RuntimeError(f"Скрипт не найден: {script}")
    Path(scheme).mkdir(parents=True, exist_ok=True)

    # Очищаем папку перед выгрузкой — иначе остатки от прошлой конфигурации
    # смешаются с новой (если пользователь переключился на другую базу 1С).
    scheme_path_obj = Path(scheme)
    safe, reason = _is_safe_to_clear(scheme_path_obj)
    if safe:
        n_before = _count_files(scheme, "*")
        if n_before > 0:
            await on_log(f"Очищаю {scheme} перед свежей выгрузкой", f"было {n_before} файлов · {reason}")
            deleted, msg = _clear_dump_dir(scheme_path_obj)
            await on_log(f"Очистка: {msg}", "")
            if "не получилось" in msg:
                # Скорее всего BSL Atlas держит файлы — нужно его остановить
                await on_log("СОВЕТ: останови BSL Atlas (закрой start.bat), это освободит файлы для удаления", "")
    else:
        await on_log(f"ВНИМАНИЕ: папку не очищаю автоматически", reason)
        await on_log("Файлы прошлой выгрузки останутся вперемешку с новыми. Удали их вручную если нужна чистая выгрузка.", "")

    await on_log(f"db-dump-xml (без -Extension)", f"→ {scheme}")
    await on_log("ВНИМАНИЕ: крупные конфигурации (ERP) выгружаются 10–20 мин", "")

    out = await _run_ps_humanized(
        cfg,
        script,
        "-V8Path",       v8_path,
        "-InfoBasePath", base,
        "-UserName",     cfg.get("username", ""),
        "-Password",     cfg.get("password", ""),
        "-ConfigDir",    scheme,
        "-Mode",         "Full",
        # БЕЗ -Extension — это и есть ключевое отличие от dump_extension
        timeout=2400,  # 40 минут — для крупных конфигураций
    )

    xml_count = _count_files(scheme, "*.xml")
    all_count = _count_files(scheme, "*")
    size_mb = _bytes_to_mb(_dir_size_bytes(scheme))
    info = f"{xml_count} XML-файлов"

    # Считаем уникальные топ-папки — это типы объектов метаданных
    p = Path(scheme)
    top_folders = sorted({x.name for x in p.iterdir() if x.is_dir()}) if p.exists() else []
    if top_folders:
        info += f", {len(top_folders)} типов объектов"

    return {
        "info": info,
        "tail": (out or "")[-800:],
        "stats": {
            "xml_count":     xml_count,
            "files_count":   all_count,
            "size_mb":       size_mb,
            "object_types":  len(top_folders),
            "path":          str(p.resolve()),
        },
    }


async def validate_xdto(cfg: dict, on_log: LogFn) -> dict[str, Any]:
    """Валидирует все XML в ext_src/ по XDTO-схемам платформы 1С.

    Использует xml_validator.validate_directory с extension_mode=True.
    Extension-specific теги (ObjectBelonging и т.п.) и minOccurs переводятся
    в warnings — для расширений это допустимо.
    """
    ext_src = _require(cfg, "ext_src_path", "папка ext_src/")
    ext_path = Path(ext_src)
    if not ext_path.exists():
        raise RuntimeError(f"Папка расширения не существует: {ext_src}")

    await on_log(f"Проверка XDTO-структуры всех XML", f"в {ext_src}")

    import asyncio as _asyncio
    from xml_validator import validate_directory

    def _run() -> Any:
        return validate_directory(
            ext_path,
            max_files=None,
            max_errors_per_file=10,
            extension_mode=True,
        )

    bulk = await _asyncio.to_thread(_run)

    schemas_str = ", ".join(f"{s}={n}" for s, n in bulk.by_schema.items())
    info = (
        f"{bulk.checked_files} XML · "
        f"{bulk.total_errors} ошибок · "
        f"{bulk.total_warnings} предупреждений · "
        f"схемы: {schemas_str}"
    )
    await on_log(info, "")

    # Покажем первые ошибки в логе
    if bulk.errors_by_file:
        await on_log("Первые ошибки:", "")
        shown = 0
        for file_path, errs in bulk.errors_by_file.items():
            if shown >= 3:
                break
            try:
                rel = Path(file_path).relative_to(ext_path)
            except ValueError:
                rel = Path(file_path).name
            await on_log(f"  {rel}", f"{len(errs)} нарушений: {errs[0][:120]}")
            shown += 1

    return {
        "info": info,
        "tail": "",
        "stats": {
            "checked_files":       bulk.checked_files,
            "files_with_errors":   bulk.files_with_errors,
            "files_with_warnings": bulk.files_with_warnings,
            "total_errors":        bulk.total_errors,
            "total_warnings":      bulk.total_warnings,
            "by_schema":           dict(bulk.by_schema),
            "path":                str(ext_path.resolve()),
        },
    }


async def rebuild_platform_docs(cfg: dict, on_log: LogFn) -> dict[str, Any]:
    """Пересобирает индекс платформенной справки 1С из shcntx_ru.hbk
    в директории v8_path пользователя. Запускается из UI при первой настройке
    или когда пользователь обновил платформу 1С.

    Источник: <v8_path>/shcntx_ru.hbk (~25-40 МБ, поставляется с любой
    установкой 1С Предприятие).
    Результат: agenter/data/platform_docs.db (SQLite + FTS5).
    """
    v8_path = _require(cfg, "v8_path", "путь к платформе 1С")
    hbk_path = Path(v8_path) / "shcntx_ru.hbk"
    if not hbk_path.exists():
        # Альтернатива — корневой root-файл (английский для некоторых версий)
        alt = Path(v8_path) / "shcntx_root.hbk"
        if alt.exists():
            hbk_path = alt
        else:
            raise RuntimeError(
                f"Файл справки 1С не найден: {hbk_path}\n"
                "Проверь что v8_path указывает на папку bin/ установки 1С "
                "(там должен быть 1cv8.exe и shcntx_ru.hbk)."
            )

    size_mb = hbk_path.stat().st_size / 1024 / 1024
    await on_log(f"Источник: {hbk_path.name} ({size_mb:.1f} МБ)", "")
    await on_log("Распаковка и парсинг ~25 000 страниц справки", "обычно 5–15 секунд")

    # Импортируем модуль платформенной справки и строим индекс.
    # asyncio.to_thread — build_index синхронный (CPU-bound).
    import asyncio as _asyncio
    from platform_docs import build_index, stats, DOCS_DB_PATH

    def _build():
        return build_index(hbk_path)

    result = await _asyncio.to_thread(_build)

    db_stats = stats()
    db_size_bytes = db_stats.get("db_size_bytes", 0)
    db_size_mb = db_size_bytes / 1024 / 1024
    records_count = int(result.get("inserted", 0))
    info = (
        f"{records_count:,} записей · "
        f"БД {db_size_mb:.1f} МБ"
    )
    by_kind = result.get("by_kind") or {}
    if by_kind:
        kinds_summary = ", ".join(
            f"{v:,} {k}" for k, v in sorted(by_kind.items(), key=lambda x: -x[1])
        )
        info += f" · {kinds_summary}"

    return {
        "info": info,
        "tail": str(DOCS_DB_PATH),
        "stats": {
            "records_count": records_count,
            "db_size_mb":    round(db_size_mb, 1),
            "db_path":       str(DOCS_DB_PATH),
            "hbk_path":      str(hbk_path),
            "hbk_size_mb":   round(size_mb, 1),
            "by_kind":       {k: int(v) for k, v in by_kind.items()},
        },
    }


async def rebuild_platform_docs_semantic(cfg: dict, on_log: LogFn) -> dict[str, Any]:
    """Строит ChromaDB semantic-индекс поверх существующей SQLite БД справки.

    Не парсит .hbk заново — берёт готовые ~25 000 записей из platform_docs.db
    и кодирует их через sentence-transformers (deepvk/USER-bge-m3 — SOTA RU).

    Что даёт:
        - семантический поиск ('как заблокировать данные' → ИспользованиеБлокировки)
        - поиск нечётких сходств (Lock ↔ Блокировка)
        - дополнение к точному FTS5 lookup (он остаётся)

    Стоимость: ~5-15 минут на CPU + ~50-100 МБ диска (ChromaDB) + кэш модели
    ~1.4 ГБ (один раз).
    """
    import asyncio as _asyncio
    from platform_docs_chroma import (
        DOCS_DB_PATH, build_chroma_index, stats as chroma_stats
    )

    if not DOCS_DB_PATH.exists():
        raise RuntimeError(
            f"Сначала нужно построить SQLite-индекс справки (rebuild-platform-docs): "
            f"файл не найден — {DOCS_DB_PATH}"
        )

    sqlite_size_mb = DOCS_DB_PATH.stat().st_size / 1024 / 1024
    await on_log(
        f"Источник: {DOCS_DB_PATH.name} ({sqlite_size_mb:.1f} МБ)",
        "переиндексирую через USER-bge-m3"
    )

    # Проверяем — модель уже в локальном кэше или будет скачиваться
    models_dir = Path(__file__).parent.parent / "tools" / "models"
    model_cached = False
    if models_dir.exists():
        # Любой файл > 500 MB в кэше — значит модель скачана
        try:
            for f in models_dir.rglob("*"):
                if f.is_file() and f.stat().st_size > 500 * 1024 * 1024:
                    model_cached = True
                    break
        except OSError:
            pass

    # Определяем используемое устройство (CPU / CUDA) — для информативного сообщения
    device_info = "CPU"
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            try:
                gpu_name = torch.cuda.get_device_name(0)
                vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
                device_info = f"GPU: {gpu_name} ({vram_gb:.1f} ГБ)"
            except Exception:
                device_info = "GPU (CUDA)"
    except ImportError:
        pass

    if model_cached:
        await on_log(
            f"Модель USER-bge-m3 в кэше · вычисления на {device_info}",
            "загружаю в RAM (~10 сек), затем кодирование 25k записей",
        )
    else:
        await on_log(
            "Первый запуск — скачивание модели (1.37 ГБ из HuggingFace)",
            f"затем кодирование 25k записей на {device_info}",
        )

    # Прогресс — пушим в UI через WebSocket. Делаем редкие апдейты чтобы не спамить.
    last_log_at = [0.0]
    loop = _asyncio.get_event_loop()
    pending: list = []

    def _progress(current: int, total: int, eta_sec: float) -> None:
        import time as _t
        now = _t.time()
        if now - last_log_at[0] < 3.0:  # не чаще раза в 3 секунды
            return
        last_log_at[0] = now
        msg = f"Индексация {current:,}/{total:,}"
        sub = f"ETA {int(eta_sec)}с"
        # on_log — coroutine; вызываем из sync через run_coroutine_threadsafe
        try:
            pending.append(
                _asyncio.run_coroutine_threadsafe(on_log(msg, sub), loop)
            )
        except Exception:
            pass

    def _build() -> Any:
        return build_chroma_index(progress_callback=_progress)

    result = await _asyncio.to_thread(_build)

    indexed = int(result.get("indexed", 0))
    chroma_mb = float(result.get("chroma_size_mb", 0))
    elapsed = float(result.get("elapsed_sec", 0))
    dim = int(result.get("dim", 0))

    info = (
        f"{indexed:,} записей закодированы · "
        f"ChromaDB {chroma_mb:.1f} МБ · "
        f"dim={dim} · "
        f"{elapsed:.0f}с"
    )

    return {
        "info": info,
        "tail": result.get("chroma_path", ""),
        "stats": {
            "indexed":         indexed,
            "model":           result.get("model", ""),
            "dim":             dim,
            "chroma_size_mb":  round(chroma_mb, 1),
            "chroma_path":     result.get("chroma_path", ""),
            "elapsed_sec":     elapsed,
        },
    }
