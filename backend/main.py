import asyncio
import json
import logging
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic
from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Пути относительно расположения backend/
_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
_AGENTER_ROOT = os.path.dirname(_BACKEND_DIR)          # agenter/
DB_PATH       = os.path.join(_BACKEND_DIR, "agenter.db")
# Эффективный лимит turns (то что считается «полезной работой»). Считается
# orchestrator_sdk через свой счётчик — ask_user НЕ инкрементирует его, чтобы
# уточнение от юзера не «штрафовало» агента. Override через config.json:
# поле max_iterations. Опыт: на 9-шаговом ТЗ реалистично ~36-50 tool calls
# + резерв на ошибки/уточнения. 120 даёт запас на 2-3 крупных задачи.
MAX_ITERATIONS = 120

# Сколько раз агент может вызвать ask_user в одной задаче. Защита от петли
# «ошибка → ask_user → ответ → опять ошибка → ask_user → ...». После 5
# попыток PreToolUse hook блокирует следующий ask_user — агент обязан
# завершить задачу финальным сообщением.
MAX_ASK_USER_PER_TASK = 5

# Жёсткий потолок SDK max_turns — страховка от бесконечности на случай если
# наш собственный счётчик не сработает (баг в hook, runaway состояние).
# Должен быть заметно больше MAX_ITERATIONS + MAX_ASK_USER_PER_TASK.
SDK_HARD_CAP_TURNS = 200
MAX_TOOL_RESULT = 50_000

# Loop detection: если N последних tool calls идентичны (тот же
# tool + те же параметры) — задача останавливается принудительно.
# 3 — типичный размер петли, при которой ясно что LLM в тупике.
LOOP_DETECT_WINDOW = 3

# При ошибке этих инструментов pipeline немедленно прерывается
CRITICAL_TOOLS = {"db_dump", "db_load"}

# ────────────────────────────────────────────────────────────────
# SYSTEM_PROMPT — стиль «оркестратор», БЕЗ примеров BSL-кода.
#
# Принципы (НЕ нарушать при правках):
#   • НИ ОДНОГО BSL-сниппета. Никаких ```bsl ... ```.
#   • НИ ОДНОГО конкретного имени метода/свойства/объекта 1С
#     (Контрагенты, ИсточникДанных, НаборЗаписей и т.п.) как примера.
#   • Только: роль агента, decision tree «когда какой инструмент»,
#     workflows как последовательности шагов, запреты, контекст клиента.
#
# Знания о синтаксисе/API/БСП агент получает через инструменты:
#   - bsl_* (поиск в реальной конфигурации клиента — источник правды)
#   - skills meta_compile/meta_edit (help-вывод при неверных аргументах)
#   - в будущем: MCP-серверы для платформенного API, БСП, шаблонов
#
# Если LLM что-то не знает — она должна сначала искать через инструменты,
# и только если не нашла — спрашивать пользователя. НЕ изобретать имена.
#
# История: до 2026-05-15 промпт содержал ~770 строк примеров BSL —
# это был «костыль», компенсирующий отсутствие knowledge-MCP.
# Удалён как часть архитектурного перехода на data-driven knowledge layers.
# ────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Ты — инженер-разработчик 1С:Предприятие. Ты работаешь СВОБОДНО: сам решаешь,
в каком порядке действовать, какие инструменты звать, как разбить задачу.
Для многошаговой работы планируй нативно (TodoWrite).

То, что ниже — НЕ маршрут и НЕ предписанная очерёдность шагов. Это ЗНАНИЕ о
1С, которого у тебя может не быть, плюс предупреждения о типичных граблях.
Ориентир, а не приказ. Когда задача неоднозначна — спроси (ask_user), не
угадывай.

═══════════════════════════════════════════════════════
 1. КОНТРАКТ С 1С
═══════════════════════════════════════════════════════

  • Изменения в 1С делай предпочтительно через санкционированные скиллы
    (meta-*, form-*, cfe-*, epf-*, erf-* и т.п.) — они знают канон платформы
    и генерируют корректные XML/структуры. НЕ дублируй платформу самописной
    валидацией: у скилла своя проверка — доверяй ей, а не переписывай поверх.
  • Один скилл = один канон. Если скилл умеет операцию — не делай её руками
    через Edit/Bash по XML метаданных.
  • db_load + apply-time = ФИНАЛЬНЫЙ АРБИТР. Изменение «применено» только
    после успешной загрузки в БД. Ошибки конфигурации платформа выдаёт на
    apply-time (обновление структуры БД), уже внутри 1С. До db_load всё, что
    ты сделал в ext_src/ — черновик.
  • Типичный поток модифицирующей задачи (ориентир, не догма): синхронизация
    из БД (db_dump) → правки через скиллы → проверка (cfe_validate) →
    применение (db_load). Периметр требует cfe_validate перед db_load — это
    не обойти, но порядок прочих шагов выбираешь ты.

  ЕДИНСТВЕННОЕ жёсткое «НЕЛЬЗЯ»:
    Запись в боевую БД — ТОЛЬКО через tool db_load. НЕ запускай напрямую
    (через Bash/PowerShell) `1cv8 DESIGNER /LoadConfigFromFiles … /UpdateDBCfg`,
    `/LoadCfg`, `ENTERPRISE /Execute` и подобное. Прямая загрузка минует
    снапшот (откат), биллинг и apply-gate. Защёлка периметра это и так
    заблокирует — знай причину, не трать на обходы шаги.

═══════════════════════════════════════════════════════
 2. КЛАССЫ ЗАДАЧ (ориентир выбора маршрута, не жёсткая ветка)
═══════════════════════════════════════════════════════

Распознай класс задачи по признакам — от него зависят инструменты и риск:

  A. РАСШИРЕНИЕ (ext_src) — доработка типовой конфигурации БЕЗ снятия её с
     поддержки. Объекты живут в ext_src/, заимствование типовых — через
     cfe-*, применение — cfe_validate → db_load. Самый частый класс.

  B. ВНЕШНЯЯ обработка/отчёт (.epf / .erf) — отдельный файл, который НЕ
     трогает конфигурацию базы. Самый безопасный класс: ничего не грузится в
     конфигурацию, нет apply-gate конфигурации. Инструменты — epf-*/erf-*.

  C. ОБЪЕКТ ОСНОВНОЙ КОНФИГУРАЦИИ (SCHEME) — встроенный объект самой
     конфигурации, не расширение.
     ВАЖНО (Р1): если типовая конфигурация НА ПОДДЕРЖКЕ — НЕ правь основную
     конфигурацию. Объясни пользователю, что объект на поддержке, и попроси
     снять его с поддержки вручную в Конфигураторе — это его решение, не
     твоё. Без этого корректная правка основной конфигурации невозможна.

При неоднозначности класса (например «сделай обработку» — внешнюю .epf или
объект конфигурации?) — спроси ask_user, не угадывай. Цена ошибки класса
высокая: применишь не туда.

═══════════════════════════════════════════════════════
 3. КАНАЛЫ ЗНАНИЙ О 1С (ищи, не выдумывай)
═══════════════════════════════════════════════════════

Ты НЕ обязан помнить наизусть API платформы, имена объектов и подсистем БСП,
полные сигнатуры. Когда не уверен — НАЙДИ, а не сочиняй: опечатка в имени
свойства/метода всплывёт только на apply-time, дорого.

  • platform_doc_lookup(name) / platform_doc_search(query) — официальная
    справка платформы 1С (shcntx_ru, проиндексирована локально). Зови ПЕРЕД
    использованием любого платформенного метода/свойства, в имени которого
    не уверен на 100%. found=0 → метода в платформе нет, НЕ выдумывай (может
    это метод БСП — проверь через bsl_*).
  • bsl-atlas (bsl_* инструменты) — поиск по реальному КОДУ клиентской базы:
    функции и процедуры, объекты метаданных, граф вызовов, семантический
    поиск. Это источник правды для ДАННОЙ базы (её версия платформы/БСП,
    локальные правки уже учтены). Зови, когда нужен живой образец кода или
    проверка существования объекта.

Стратегия: знаешь имя → структурный bsl_ (search_function / get_object /
metadatasearch); знаешь только смысл → семантический bsl_ или
platform_doc_search. Пусто у всех каналов → спроси пользователя, НЕ
продолжай на выдуманном имени.

Имена объектов НЕ ищи через Bash/os.walk по SCHEME — папки в cp1251, получишь
крокозябры и потеряешь шаги. Только bsl_*/metadatasearch.

═══════════════════════════════════════════════════════
 4. ГРАБЛИ 1С (предупреждения, не шаги)
═══════════════════════════════════════════════════════

  • Мультиязычные свойства. Synonym, ToolTip, Comment и подобные — это НЕ
    простая строка, а LocalStringType (набор пар «код языка → значение»).
    Задавай их в правильной структуре, иначе платформа не примет.
  • PropertyState. Пометка PropertyState=Changed/Original у свойств
    заимствованного объекта — ШТАТНАЯ пометка платформы (что свойство
    переопределено в расширении), НЕ ошибка. Не «чини» её.
  • Перехват методов. Ручной &ИзменениеИКонтроль хрупок — ломается при
    обновлении типовой. Предпочитай &Вместо с явным вызовом ПродолжитьВызов()
    — устойчивее к обновлениям.
  • db_load OK ≠ применено в работу. Успех вызова db_load означает, что
    загрузка стартовала; реальные ошибки конфигурации платформа выдаёт на
    apply-time. Дочитывай результат до apply-time, прежде чем сказать «готово».
  • Form.xml не редактируется регексом. XML формы — ~17 namespace-деклараций,
    ID-пулы, companion-элементы. Только через form-* скиллы (form_compile /
    form_edit / form_validate), никогда Edit/Bash по Form.xml.
  • Р5 — «ПЕРЕИМЕНОВАТЬ». По умолчанию «переименовать объект/реквизит» =
    сменить СИНОНИМ (отображаемое имя, Synonym) — это безопасно. Менять ИМЯ
    (Name) — это каскад по всем ссылкам в коде и метаданных, рискованно.
    Меняй Имя ТОЛЬКО при явном указании пользователя и предупреди о каскаде.

═══════════════════════════════════════════════════════
 КОНТЕКСТ КЛИЕНТА
═══════════════════════════════════════════════════════

Конкретные пути (ext_src, SCHEME, база, платформа), имя расширения и префикс
инжектятся в этот промпт в runtime — см. блок ниже. Все НОВЫЕ объекты
расширения именуй с префиксом расширения.
"""


def _extract_prefix(extension_name: str) -> str:
    """Извлекает префикс из имени расширения (например 'расш_' из 'РасшМоёРасширение')."""
    import re
    m = re.match(r"([A-Za-zА-Яа-яЁё]+_)", extension_name)
    if m:
        return m.group(1).lower()
    return ""


def _build_system_prompt(client_cfg: dict | None = None) -> str:
    """Строит системный промпт с добавлением контекста клиента если есть."""
    if not client_cfg:
        return SYSTEM_PROMPT
    ext      = client_cfg.get("extension", "")
    ext_src  = client_cfg.get("ext_src_path", "")
    scheme   = client_cfg.get("scheme_path", "")
    base     = client_cfg.get("base_path", "")
    v8       = client_cfg.get("v8_path", "")
    prefix   = _extract_prefix(ext)
    ctx = f"""

═══════════════════════════════════════════════════════
 КОНТЕКСТ ТЕКУЩЕГО КЛИЕНТА
═══════════════════════════════════════════════════════

  Расширение : {ext or "(не задано)"}
  Префикс    : {prefix or "(определить из кода)"}
  ext_src    : {ext_src or "(не задан)"}
  SCHEME     : {scheme or "(не задан — образцы брать из ext_src или bsl_* инструментов)"}
  База 1С    : {base or "(не задана)"}
  Платформа  : {v8 or "(не задана)"}

Все новые объекты расширения именуй с префиксом «{prefix or "???_"}».
При изменении существующих объектов базы — префикс в имени метода обязателен.
При чтении из SCHEME: read_file("SCHEME/Catalogs/ИмяОбъекта/ИмяОбъекта.xml").
"""
    return SYSTEM_PROMPT + ctx

TOOL_DEFINITIONS = [
    {
        "name": "db_dump",
        "description": "Синхронизировать БД 1С → ext_src/ (XML файлы). ОБЯЗАТЕЛЬНО вызывать первым.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "db_load",
        "description": (
            "Загрузить ext_src/ → БД 1С. ФИНАЛЬНЫЙ шаг модифицирующей задачи.\n"
            "ОБЯЗАТЕЛЬНЫЕ предусловия (если хотя бы одно НЕ выполнено — НЕ вызывай):\n"
            "  (1) cfe_validate выполнен в этой же задаче и вернул 0 errors\n"
            "  (2) Все запланированные изменения применены\n"
            "  (3) Если cfe_validate показал warnings — они проанализированы\n"
            "ЕСЛИ cfe_validate вернул errors — НЕ вызывай db_load. Сначала исправь."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "bsl_search_function",
        "description": (
            "Найти функцию/процедуру BSL по имени во всех модулях основной конфигурации "
            "(включая БСП). Use BEFORE writing any BSL-code which references a function/method:\n"
            "  • Не уверен в имени метода? — bsl_search_function ПЕРЕД написанием.\n"
            "  • Хочешь использовать функцию БСП? — найди её и убедись что существует.\n"
            "  • Нашёл? — посмотри её сигнатуру через bsl_get_module_functions.\n"
            "  • НЕ нашёл с exact=true? — попробуй exact=false (поиск подстрокой) или bsl_code_grep.\n"
            "  • Всё ещё не нашёл? — функции не существует. НЕ ВЫДУМЫВАЙ. Сообщи пользователю."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя функции/процедуры точно как в коде"},
                "exact": {"type": "boolean", "default": True, "description": "true=строгое равенство, false=поиск подстрокой"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "bsl_get_object",
        "description": (
            "Получить реквизиты, ТЧ, измерения, ресурсы и движения объекта метаданных 1С. "
            "Use BEFORE:\n"
            "  • заимствования объекта (cfe_borrow) — чтобы знать состав\n"
            "  • добавления реквизита к существующему объекту — чтобы не дублировать\n"
            "  • написания кода, обращающегося к ТЧ/реквизитам — чтобы знать точные имена\n"
            "  • любой ссылки на чужой объект в BSL — чтобы знать какие у него поля"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"full_name": {"type": "string", "description": "Полное имя: 'Catalog.Контрагенты' / 'Document.X' / 'AccumulationRegister.Y'"}},
            "required": ["full_name"],
        },
    },
    {
        "name": "bsl_code_grep",
        "description": (
            "Поиск текста/regex-паттерна в BSL-коде SCHEME с контекстом функции.\n"
            "Use когда:\n"
            "  • bsl_search_function не дал ответа (не знаешь точного имени)\n"
            "  • Ищешь паттерн использования (например 'БлокировкаДанных' или 'НаборЗаписей.*Записать')\n"
            "  • Хочешь увидеть КАК типовой код решает похожую задачу — найди образец и адаптируй\n"
            "  • Перед написанием НЕТРИВИАЛЬНОГО BSL (блокировки, движения, запросы, формы) — "
            "    ОБЯЗАТЕЛЬНО найди живой образец в основной конфигурации\n"
            "Возвращает фрагменты с именем функции, в которой найден паттерн.\n"
            "Если результат пуст — паттерн не используется в конфигурации. НЕ выдумывай — спроси пользователя."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Текст или regex для поиска"},
                "case_sensitive": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "bsl_get_function_context",
        "description": (
            "Граф вызовов функции: ЧТО она вызывает и КТО её вызывает (callers/callees). "
            "Use когда:\n"
            "  • Меняешь сигнатуру функции — нужно проверить кто её вызывает\n"
            "  • Понимаешь поведение через граф зависимостей\n"
            "  • Заимствуешь общий модуль и хочешь увидеть его связи"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"function_name": {"type": "string"}},
            "required": ["function_name"],
        },
    },
    {
        "name": "bsl_get_module_functions",
        "description": (
            "Список всех функций/процедур одного модуля + их сигнатуры. "
            "Use когда:\n"
            "  • Заимствовал модуль через cfe_borrow и нужно выбрать какой метод перехватывать\n"
            "  • Хочешь увидеть весь API общего модуля БСП перед использованием\n"
            "  • Анализируешь типовой модуль перед изменением"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"module_path": {"type": "string", "description": "Путь к модулю или его часть (поиск подстрокой)"}},
            "required": ["module_path"],
        },
    },
    {
        "name": "bsl_metadatasearch",
        "description": (
            "Поиск объектов метаданных 1С (Catalog, Document, регистры, перечисления) по названию. "
            "Use BEFORE:\n"
            "  • Заимствования объекта — убедись что он существует и правильно назван\n"
            "  • Создания связи (CatalogRef.X) — проверь что X действительно существует\n"
            "  • Использования регистра в коде — проверь точное имя\n"
            "Если запрос дал пусто — объекта НЕТ в конфигурации. НЕ выдумывай — спроси пользователя."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Имя или часть имени объекта"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bsl_codesearch",
        "description": (
            "Семантический поиск по BSL-коду конфигурации. Принимает запрос "
            "на естественном языке («блокировка остатков перед движениями», "
            "«создание документа и проведение») и находит участки кода с "
            "похожей семантикой. Используй когда не знаешь имени конкретной "
            "функции, но понимаешь ЧТО ищешь. Требует semantic-режим BSL Atlas — "
            "если вернёт ошибку, переключись на bsl_code_grep или bsl_search_function."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Запрос на естественном языке"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bsl_helpsearch",
        "description": (
            "Поиск в документации платформы 1С. Используй для уточнения сигнатур "
            "методов, имён свойств, поведения встроенных объектов 1С. "
            "Возвращает релевантные фрагменты официальной справки. Требует "
            "semantic-режим BSL Atlas — если ошибка, ищи образец через bsl_code_grep."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Что искать в справке (имя метода, концепция)"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bsl_search_code_filtered",
        "description": (
            "Семантический поиск по коду + структурные фильтры. Используй когда "
            "хочешь найти паттерн ИМЕННО в определённом контексте: только формы, "
            "только модули объектов, только функции по шаблону имени. Требует "
            "semantic-режим BSL Atlas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Семантический запрос"},
                "module_type": {
                    "type": "string",
                    "description": "Фильтр по типу модуля: ObjectModule | ManagerModule | FormModule | CommonModule",
                },
                "function_name_pattern": {
                    "type": "string",
                    "description": "Регулярка по имени функции",
                },
                "object_type": {
                    "type": "string",
                    "description": "Фильтр по типу объекта метаданных: Catalog | Document | …",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Прочитать файл из ext_src/.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Заменить old_str на new_str в файле (точное совпадение обязательно).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Создать или перезаписать файл в ext_src/. "
            "ТОЛЬКО для BSL-кода (*.bsl) и текстовых файлов. "
            "ЗАПРЕЩЕНО использовать для создания XML-файлов объектов метаданных 1С "
            "(Catalog.xml, Document.xml и подобных) — для этого используй clone_object."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_ext_files",
        "description": "Список всех файлов расширения в ext_src/.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_sample_object",
        "description": (
            "[DEPRECATED — НЕ ИСПОЛЬЗОВАТЬ] "
            "Этот инструмент остался для совместимости. Для создания нового объекта "
            "используй ТОЛЬКО meta_compile — он не требует образца, генерирует XML "
            "по канонической структуре платформы. Любой вызов get_sample_object — "
            "признак неправильного маршрута."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string"},
            },
            "required": ["object_type"],
        },
    },
    {
        "name": "clone_object",
        "description": (
            "[DEPRECATED — НЕ ИСПОЛЬЗОВАТЬ] "
            "Этот инструмент остался для совместимости. Для создания нового объекта "
            "метаданных используй ТОЛЬКО meta_compile — он генерирует правильный XML "
            "автоматически по JSON-описанию, без копирования образцов и ручной правки UUID. "
            "Любой вызов clone_object — ошибка маршрута: переключись на meta_compile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "new_name": {"type": "string"},
            },
            "required": ["source_path", "new_name"],
        },
    },
    {
        "name": "validate_ext_structure",
        "description": (
            "[DEPRECATED — НЕ ИСПОЛЬЗОВАТЬ] "
            "Заменён на cfe_validate, который делает полную проверку. "
            "Любой вызов validate_ext_structure — переключись на cfe_validate."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # ─────────────────────────────────────────────────────────────────────
    # Подключённые скиллы 1С — основные инструменты для работы с метаданными
    # ─────────────────────────────────────────────────────────────────────
    {
        "name": "meta_compile",
        "description": (
            "ОСНОВНОЙ инструмент СОЗДАНИЯ новых объектов метаданных. "
            "Принимает JSON-описание и генерирует правильный XML + регистрирует объект "
            "в Configuration.xml. Поддерживает все типы: Catalog, Document, "
            "InformationRegister, AccumulationRegister, AccountingRegister, Enum, "
            "Constant, CommonModule, HTTPService, Report, DataProcessor, ExchangePlan и др.\n"
            "Минимальный JSON: {\"type\": \"Catalog\", \"name\": \"МойСправочник\"}\n"
            "С реквизитами: {\"type\": \"Catalog\", \"name\": \"X\", \"attributes\": [\"ИНН: String(12)\", \"Сумма: Number(15,2) | req, index\"]}\n"
            "С ТЧ: {\"type\": \"Document\", \"name\": \"X\", \"tabularSections\": {\"Товары\": [\"Номенклатура: CatalogRef.Номенклатура\", \"Кол: Number(15,3)\"]}}\n"
            "Регистр: {\"type\": \"InformationRegister\", \"name\": \"X\", \"dimensions\": [...], \"resources\": [...]}\n"
            "Batch: массив [{...}, {...}].\n"
            "ВАЖНО: ИМЯ ДОЛЖНО НАЧИНАТЬСЯ С ПРЕФИКСА расширения (см. контекст клиента)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "definition": {
                    "description": "JSON-описание одного объекта (object) или нескольких (array of objects)",
                },
            },
            "required": ["definition"],
        },
    },
    {
        "name": "meta_edit",
        "description": (
            "ТОЧЕЧНОЕ РЕДАКТИРОВАНИЕ существующего объекта метаданных. "
            "ПРЕДПОЧТИТЕЛЬНЕЕ чем read_file+edit_file для типовых операций: "
            "добавить/удалить/переименовать реквизит, ТЧ, измерение, ресурс, "
            "изменить свойство объекта. Скилл сам разберёт XML и сделает правку безопасно.\n"
            "Примеры:\n"
            "  add-attribute, value=\"ИНН: String(12) | req\"\n"
            "  add-ts, value=\"Товары: Ном: CatalogRef.Ном, Кол: Number(15,3)\"\n"
            "  add-dimension, value=\"Организация: CatalogRef.Организации | master\"\n"
            "  modify-property, value=\"CodeLength=11 ;; DescriptionLength=150\"\n"
            "  remove-attribute, value=\"СтарыйРеквизит\"\n"
            "Batch через ';;'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_path": {
                    "type": "string",
                    "description": "Путь к объекту в ext_src, например 'Catalogs/МойСправочник' или 'Documents/Заказ'",
                },
                "operation": {
                    "type": "string",
                    "description": (
                        "Операция: add-attribute / add-ts / add-dimension / add-resource / "
                        "add-enumValue / add-column / add-form / add-template / add-command / "
                        "add-ts-attribute / remove-attribute / remove-ts / remove-ts-attribute / "
                        "modify-attribute / modify-ts-attribute / modify-ts / modify-property / "
                        "add-owner / add-registerRecord / add-basedOn / set-owners / "
                        "set-registerRecords / set-basedOn"
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "Значение в формате DSL скилла (см. описание инструмента). Batch через ';;'",
                },
            },
            "required": ["object_path", "operation", "value"],
        },
    },
    {
        "name": "cfe_borrow",
        "description": (
            "ЗАИМСТВОВАНИЕ объекта из основной конфигурации в расширение. "
            "Нужно ПЕРЕД тем как добавлять реквизиты к существующему типовому объекту "
            "или перехватывать его методы. Создаёт XML с ObjectBelonging=Adopted и "
            "регистрирует в Configuration.xml.\n"
            "Формат object: 'Catalog.Контрагенты' / 'Document.РТУ' / 'CommonModule.ОбщегоНазначения' / "
            "'Catalog.Контрагенты.Form.ФормаЭлемента' (для заимствования формы). Batch через ';;'.\n"
            "Для форм с реквизитами: borrow_main_attribute=\"Form\" (реквизиты с формы) или \"All\" (все)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object": {
                    "type": "string",
                    "description": "Полное имя заимствуемого объекта в нотации Type.Name[.Form.FormName]",
                },
                "borrow_main_attribute": {
                    "type": "string",
                    "enum": ["Form", "All"],
                    "description": "Опционально для форм: заимствовать ли реквизиты основного объекта",
                },
            },
            "required": ["object"],
        },
    },
    {
        "name": "cfe_patch_method",
        "description": (
            "СОЗДАНИЕ ПЕРЕХВАТЧИКА метода в заимствованном объекте. "
            "Генерирует BSL-функцию с правильным декоратором &Перед/&После/&ИзменениеИКонтроль и "
            "именем процедуры с префиксом расширения. Объект должен быть заимствован cfe_borrow заранее.\n"
            "ВАЖНО: cfe_patch_method создаёт только КАРКАС функции. Тело надо дописать через "
            "read_file → edit_file/write_file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "module_path": {
                    "type": "string",
                    "description": (
                        "Путь к модулю: 'Catalog.X.ObjectModule' / 'Catalog.X.ManagerModule' / "
                        "'Catalog.X.Form.ФормаЭлемента' / 'CommonModule.X' / "
                        "'Document.X.ObjectModule' и т.п."
                    ),
                },
                "method_name": {"type": "string", "description": "Имя оригинального метода (например 'ПриЗаписи', 'ОбработкаПроведения')"},
                "interceptor_type": {
                    "type": "string",
                    "enum": ["Before", "After", "ModificationAndControl"],
                    "description": "Before = &Перед, After = &После, ModificationAndControl = &ИзменениеИКонтроль (копия тела с маркерами #Вставка/#Удаление)",
                },
                "context": {
                    "type": "string",
                    "description": "Директива контекста: 'НаСервере' (по умолчанию), 'НаКлиенте', 'НаКлиентеНаСервереБезКонтекста'",
                },
                "is_function": {
                    "type": "boolean",
                    "description": "True если перехватываемый метод — функция (добавит Возврат в каркас)",
                },
            },
            "required": ["module_path", "method_name", "interceptor_type"],
        },
    },
    {
        "name": "cfe_validate",
        "description": (
            "ПОЛНАЯ ВАЛИДАЦИЯ расширения: XML-формат, свойства, состав, заимствованные объекты, "
            "согласованность Configuration.xml с файлами на диске. "
            "ОБЯЗАТЕЛЬНО вызывать ПЕРЕД db_load. Заменяет validate_ext_structure."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "platform_doc_lookup",
        "description": (
            "СТРОГАЯ платформенная справка 1С — официальная документация по методам, "
            "свойствам, событиям, объектам платформы. Источник: shcntx_ru.hbk от 1С, "
            "поставляется вместе с платформой, проиндексирован в Agenter (~25000 записей).\n\n"
            "ОБЯЗАТЕЛЬНО вызывай ПЕРЕД использованием ЛЮБОГО платформенного:\n"
            "  • Метода объекта (Заблокировать, Записать, Очистить, ...)\n"
            "  • Свойства (ИсточникДанных, Режим, Период, ...)\n"
            "  • События (ПередЗаписью, ОбработкаПроведения, ...)\n"
            "  • Объекта (БлокировкаДанных, НаборЗаписей, Запрос, ...)\n\n"
            "Стратегия поиска (lookup внутри сам это делает):\n"
            "  1. Точное совпадение имени_ru или имени_en\n"
            "  2. Case-insensitive\n"
            "  3. Подстрока в имени или полном пути\n"
            "  4. FTS5 fallback по описанию\n\n"
            "Возвращает: name, kind (method/property/object/event), full_path, parent, "
            "signature, description, params, returns, example, availability.\n\n"
            "Если found=0 — метод/свойство НЕ существует в платформе. НЕ ВЫДУМЫВАЙ — "
            "переключись на bsl_search_function (может это БСП) или спроси пользователя."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя на русском или английском, без скобок и параметров. "
                                   "Примеры: 'БлокировкаДанных', 'ИсточникДанных', 'НаборЗаписей.Записать', 'Lock'",
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Макс. количество результатов (часто одно имя имеет несколько контекстов: метод регистра + метод документа)",
                },
            },
            "required": ["name"],
        },
    },
]


# ---------------------------------------------------------------------------
# State (in-memory, достаточно для MVP)
# ---------------------------------------------------------------------------

class AppState:
    def __init__(self):
        self.desktop_ws: WebSocket | None = None
        self.web_clients: set[WebSocket] = set()
        self.pending_calls: dict[str, asyncio.Event] = {}
        self.call_results: dict[str, Any] = {}
        self.desktop_config: dict = {}   # конфиг клиента, присылается при подключении


state = AppState()


# ---------------------------------------------------------------------------
# Database (SQLite sync, через to_thread)
# ---------------------------------------------------------------------------

def _init_db():
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
    conn.commit()
    conn.close()


def _create_task(task_id: str, prompt: str) -> dict:
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
        (task_id, prompt, "pending", "", now, None),
    )
    conn.commit()
    conn.close()
    return {"id": task_id, "prompt": prompt, "status": "pending", "created_at": now}


def _get_task(task_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "prompt": row[1], "status": row[2],
        "log_jsonl": row[3], "created_at": row[4], "completed_at": row[5],
    }


def _update_status(task_id: str, status: str, completed_at: str | None = None):
    conn = sqlite3.connect(DB_PATH)
    if completed_at:
        conn.execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?",
                     (status, completed_at, task_id))
    else:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    conn.close()


def _append_log(task_id: str, entry: dict):
    conn = sqlite3.connect(DB_PATH)
    line = json.dumps(entry, ensure_ascii=False)
    conn.execute(
        "UPDATE tasks SET log_jsonl = log_jsonl || ? WHERE id=?",
        (line + "\n", task_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Broadcast & logging
# ---------------------------------------------------------------------------

async def broadcast(event: dict):
    dead: set[WebSocket] = set()
    for ws in state.web_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    state.web_clients -= dead


async def publish_log(task_id: str, text: str, meta: str = ""):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    entry = {"type": "log", "task_id": task_id, "ts": ts, "text": text, "meta": meta}
    await asyncio.to_thread(_append_log, task_id, entry)
    await broadcast(entry)


# ---------------------------------------------------------------------------
# Relay: Cloud → Desktop → Cloud
# ---------------------------------------------------------------------------

async def relay_tool_call(tool: str, params: dict, timeout: int = 300) -> str:
    if state.desktop_ws is None:
        raise RuntimeError("Desktop-ассистент не подключён")

    call_id = str(uuid.uuid4())
    event = asyncio.Event()
    state.pending_calls[call_id] = event

    try:
        await state.desktop_ws.send_json({
            "type": "tool_call",
            "call_id": call_id,
            "tool": tool,
            "params": params,
        })
    except Exception as e:
        state.pending_calls.pop(call_id, None)
        raise RuntimeError(f"Ошибка отправки tool_call: {e}")

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        state.pending_calls.pop(call_id, None)
        raise TimeoutError(f"Таймаут инструмента '{tool}' ({timeout}s)")

    result = state.call_results.pop(call_id, {})
    if not result.get("ok", False):
        raise RuntimeError(result.get("error", "Неизвестная ошибка от desktop"))

    raw = str(result.get("result", ""))
    return raw[:MAX_TOOL_RESULT]


# ---------------------------------------------------------------------------
# LLM Orchestrator
# ---------------------------------------------------------------------------

async def run_task(task_id: str, prompt: str):
    await asyncio.to_thread(_update_status, task_id, "running")
    await broadcast({"type": "status", "task_id": task_id, "status": "running"})
    await publish_log(task_id, "Задача принята, запускаю агента...")

    if not ANTHROPIC_API_KEY:
        await asyncio.to_thread(_update_status, task_id, "error", datetime.utcnow().isoformat())
        await broadcast({"type": "task_error", "task_id": task_id,
                         "error": "ANTHROPIC_API_KEY не установлен"})
        return

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    messages: list[dict] = [{"role": "user", "content": prompt}]

    try:
        for iteration in range(MAX_ITERATIONS):
            await publish_log(task_id, f"── Итерация {iteration + 1}/{MAX_ITERATIONS}")

            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8096,
                system=[{
                    "type": "text",
                    "text": _build_system_prompt(state.desktop_config),
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            # Логируем текстовые блоки
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    await publish_log(task_id, block.text)

            if response.stop_reason == "end_turn":
                await asyncio.to_thread(
                    _update_status, task_id, "done", datetime.utcnow().isoformat()
                )
                await broadcast({"type": "task_done", "task_id": task_id})
                await publish_log(task_id, "✓ Задача выполнена")
                # Уведомляем desktop-агент (для tray-нотификации)
                if state.desktop_ws:
                    try:
                        await state.desktop_ws.send_json(
                            {"type": "task_done_notify", "task_id": task_id}
                        )
                    except Exception:
                        pass
                return

            if response.stop_reason != "tool_use":
                await publish_log(task_id, f"Неожиданная остановка: {response.stop_reason}")
                break

            # Выполняем tool calls через relay
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                params_preview = json.dumps(tool_input, ensure_ascii=False)[:120]
                await publish_log(task_id, f"→ {tool_name}", params_preview)

                try:
                    result_text = await relay_tool_call(tool_name, tool_input)
                    await publish_log(
                        task_id,
                        f"← {tool_name}: OK",
                        f"{len(result_text)} симв.",
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
                except Exception as exc:
                    err_msg = str(exc)
                    await publish_log(task_id, f"← {tool_name}: ОШИБКА", err_msg[:300])
                    if tool_name in CRITICAL_TOOLS:
                        # Критический инструмент завершился с ошибкой —
                        # продолжать бессмысленно, pipeline остановлен
                        raise RuntimeError(
                            f"[{tool_name}] завершился с ошибкой — задача прервана.\n{err_msg}"
                        )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"ERROR: {err_msg}",
                        "is_error": True,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        # Превышен лимит итераций
        await asyncio.to_thread(
            _update_status, task_id, "error", datetime.utcnow().isoformat()
        )
        await broadcast({"type": "task_error", "task_id": task_id,
                         "error": f"Превышен лимит итераций ({MAX_ITERATIONS})"})

    except Exception as exc:
        log.exception("Ошибка выполнения задачи %s", task_id)
        await asyncio.to_thread(
            _update_status, task_id, "error", datetime.utcnow().isoformat()
        )
        await broadcast({"type": "task_error", "task_id": task_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _init_db()
    log.info("База данных инициализирована: %s", DB_PATH)
    yield


app = FastAPI(lifespan=lifespan, title="Agenter Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Раздаём frontend/ как статику
_frontend_dir = os.path.join(_AGENTER_ROOT, "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/ui", StaticFiles(directory=_frontend_dir, html=True), name="ui")


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    prompt: str
    project_id: str = "default"


@app.post("/tasks")
async def create_task(req: TaskRequest, bg: BackgroundTasks):
    task_id = str(uuid.uuid4())
    await asyncio.to_thread(_create_task, task_id, req.prompt)
    bg.add_task(run_task, task_id, req.prompt)
    return {"task_id": task_id, "status": "pending"}


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
        "desktop_connected": state.desktop_ws is not None,
        "web_clients": len(state.web_clients),
    }


@app.get("/desktop/status")
async def get_desktop_status():
    return {"connected": state.desktop_ws is not None}


# ---------------------------------------------------------------------------
# WebSocket: Desktop Agent
# ---------------------------------------------------------------------------

@app.websocket("/ws/desktop")
async def ws_desktop(ws: WebSocket):
    await ws.accept()
    state.desktop_ws = ws
    await broadcast({"type": "desktop_status", "status": "online"})
    log.info("Desktop подключён")

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "hello":
                # Десктоп присылает свой конфиг при подключении
                cfg = data.get("config", {})
                if cfg:
                    state.desktop_config = cfg
                    log.info("Desktop config: ext=%s ext_src=%s",
                             cfg.get("extension", "?"), cfg.get("ext_src_path", "?"))

            elif msg_type == "tool_result":
                call_id = data.get("call_id")
                state.call_results[call_id] = data
                event = state.pending_calls.pop(call_id, None)
                if event:
                    event.set()

            elif msg_type == "log":
                # Desktop шлёт свои логи (stdout скриптов)
                await broadcast(data)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "status":
                await broadcast(data)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("Desktop WS error: %s", exc)
    finally:
        state.desktop_ws = None
        # Разблокируем все ожидающие вызовы с ошибкой
        for call_id, event in list(state.pending_calls.items()):
            state.call_results[call_id] = {"ok": False, "error": "Desktop отключился"}
            event.set()
        state.pending_calls.clear()
        await broadcast({"type": "desktop_status", "status": "offline"})
        log.info("Desktop отключён")


# ---------------------------------------------------------------------------
# WebSocket: Web clients
# ---------------------------------------------------------------------------

@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    state.web_clients.add(ws)

    # Сразу сообщаем текущий статус
    await ws.send_json({
        "type": "desktop_status",
        "status": "online" if state.desktop_ws else "offline",
    })

    try:
        while True:
            # Просто держим соединение живым
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.web_clients.discard(ws)
