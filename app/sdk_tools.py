"""
agenter/app/sdk_tools.py — SDK @tool wrappers для 1С-specific custom tools.

Built-in tools (Read/Write/Edit/Bash/Grep/Glob/TodoWrite/Agent) приходят
из claude_agent_sdk напрямую — для общих файловых и оболочечных операций.

BSL Atlas — отдельный HTTP MCP server (регистрируется в orchestrator_sdk
через mcp_servers options).

Здесь — только то, что специфично для 1С и не покрывается built-in:
  • 5 PowerShell-skills (db_dump, db_load, meta_compile, meta_edit, cfe_borrow,
                         cfe_patch_method, cfe_validate)
  • platform_doc_lookup из локального SQLite индекса shcntx_ru.hbk

Каждый wrapper делегирует в существующие методы ToolExecutor (которые
живут в desktop/main.py и реализуют всю логику). Это минимизирует
дублирование — SDK получает декларации, business logic остаётся в одном месте.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

# Sprint 1 Step 3 — Skill Registry для cold skills (mxl/skd/role/subsystem/…)
from skill_registry import get_registry, args_to_ps_cli

log = logging.getLogger(__name__)


def _ok(text: str) -> dict:
    """Стандартный успешный ответ tool в формате SDK."""
    return {"content": [{"type": "text", "text": text}]}


def _err(text: str) -> dict:
    """Стандартный ответ-ошибка."""
    return {"content": [{"type": "text", "text": text}], "is_error": True}


async def _safe_call(executor_method, *args, **kwargs) -> dict:
    """Универсальный wrapper: вызывает async/sync метод executor'а,
    приводит результат к строке, на исключении возвращает is_error."""
    try:
        result = await executor_method(*args, **kwargs)
        return _ok(str(result))
    except Exception as exc:
        log.exception("Tool execution failed")
        return _err(f"ERROR: {exc}")


def make_agenter_tools(
    executor,
    *,
    ask_user_ctx: dict | None = None,
):
    """Создаёт набор SDK custom tools, забинженных в переданный ToolExecutor.

    Возвращает SDK MCP server, готовый к подключению через
    ClaudeAgentOptions(mcp_servers={"agenter": server}).

    ask_user_ctx — опц. контекст {"task_id": str, "on_ask_user": coro}
    для регистрации блокирующего tool ask_user. Если None — tool не
    регистрируется (агент не сможет остановиться и задать вопрос).
    """

    # ── 1С операции (критичные — на ошибке прерывается вся задача) ─────────

    @tool(
        "db_dump",
        "Синхронизировать БД 1С → ext_src/ (выгрузка XML расширения). "
        "ВСЕГДА вызывай первым в модифицирующей задаче — чтобы локальная копия "
        "ext_src/ совпадала с реальной БД (пользователь мог менять конфигурацию "
        "напрямую). Без параметров.",
        {"type": "object", "properties": {}},
    )
    async def db_dump(args: dict) -> dict:
        return await _safe_call(executor._db_dump)

    @tool(
        "db_load",
        "Загрузить ext_src/ → БД 1С. ФИНАЛЬНЫЙ шаг модифицирующей задачи. "
        "ОБЯЗАТЕЛЬНЫЕ предусловия: (1) cfe_validate выполнен в этой же задаче и "
        "вернул 0 errors; (2) все запланированные изменения применены. "
        "Если cfe_validate показал errors — НЕ вызывай. Без параметров.",
        {"type": "object", "properties": {}},
    )
    async def db_load(args: dict) -> dict:
        return await _safe_call(executor._db_load)

    # ── Скиллы метаданных ───────────────────────────────────────────────────

    @tool(
        "meta_compile",
        "ОСНОВНОЙ инструмент создания НОВЫХ объектов метаданных 1С. Принимает "
        "JSON-описание (объект или массив объектов для batch) и генерирует "
        "корректный XML + регистрирует объект в Configuration.xml. "
        "Минимальный пример: {\"type\":\"Catalog\",\"name\":\"Префикс_Название\"}. "
        "Поддерживает Catalog, Document, InformationRegister, AccumulationRegister, "
        "AccountingRegister, Enum, Constant, CommonModule, HTTPService, Report, "
        "DataProcessor, ExchangePlan. Имя объекта ОБЯЗАТЕЛЬНО начинается с префикса "
        "расширения (см. контекст клиента в system prompt).",
        # Полный JSON Schema — `definition` принимает object ИЛИ array (batch).
        # Шорткат {"definition": "object"} не работал — SDK видел "object" как
        # строку и делал schema {type:"string"}, из-за чего LLM сериализовал
        # dict в JSON-строку и meta-compile ломался.
        {
            "type": "object",
            "properties": {
                "definition": {
                    "description": (
                        "JSON-объект ИЛИ массив объектов (batch). "
                        "Передавай как нативный объект/массив, НЕ как строку."
                    ),
                },
            },
            "required": ["definition"],
        },
    )
    async def meta_compile(args: dict) -> dict:
        definition = args.get("definition")
        # Если Claude всё-таки передал строку (на всякий случай) — парсим
        if isinstance(definition, str):
            import json as _json
            try:
                definition = _json.loads(definition)
            except _json.JSONDecodeError as e:
                return _err(f"meta_compile: definition не парсится как JSON: {e}")
        return await _safe_call(executor._meta_compile, definition)

    @tool(
        "meta_edit",
        (
            "Редактирование существующего объекта метаданных (Catalog/Document/"
            "Register/Enum/...) через СТРУКТУРИРОВАННЫЙ JSON-DSL. "
            "Передавай объект `definition` с секциями add/modify/remove/set. "
            "Тип реквизита задаётся СТРОКОЙ — на любом из языков:\n"
            "  ru: 'Строка(50)', 'Число(15,2)', 'Дата', 'Булево', "
            "'СправочникСсылка.Контрагенты'\n"
            "  en: 'String(50)', 'Number(15,2)', 'Date', 'Boolean', "
            "'CatalogRef.Контрагенты'\n"
            "Имена объектов — БЕЗ пробелов и скобок, латиница/кириллица + "
            "цифры (со 2-го символа) + подчёркивание.\n\n"
            "Примеры definition:\n"
            "  {\"add\": {\"attributes\": [{\"name\": \"Город\", \"type\": \"Строка(50)\"}]}}\n"
            "  {\"add\": {\"tabularSections\": [{\"name\": \"Товары\", \"attrs\": "
            "[{\"name\":\"Номенклатура\",\"type\":\"CatalogRef.Номенклатура\"}, "
            "{\"name\":\"Количество\",\"type\":\"Число(15,3)\"}]}]}}\n"
            "  {\"modify\": {\"properties\": {\"CodeLength\": 11}}}\n"
            "  {\"modify\": {\"attributes\": {\"Город\": {\"type\": \"Строка(100)\"}}}}\n"
            "  {\"remove\": {\"attributes\": [\"ОтжившийРеквизит\"]}}"
        ),
        {
            "type": "object",
            "properties": {
                "object_path": {
                    "type": "string",
                    "description": (
                        "Путь к объекту относительно ext_src/. Допустимы форматы: "
                        "'Catalogs/Контрагенты', 'Documents/РеализацияТоваровУслуг', "
                        "'AccumulationRegisters/Продажи'."
                    ),
                },
                "definition": {
                    "type": "object",
                    "description": (
                        "Структурированное описание изменений. Любое сочетание "
                        "секций add/modify/remove/set. См. подробности в "
                        "описании tool."
                    ),
                    "properties": {
                        "add": {
                            "type": "object",
                            "properties": {
                                "attributes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "description": (
                                                    "Имя реквизита (NCName). "
                                                    "Только буквы, цифры (со 2-й), "
                                                    "подчёркивание. БЕЗ пробелов "
                                                    "и скобок."
                                                ),
                                                "pattern": "^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$",
                                                "minLength": 1,
                                                "maxLength": 128,
                                            },
                                            "type": {
                                                "type": "string",
                                                "description": (
                                                    "Тип значения: 'Строка(50)', "
                                                    "'Число(15,2)', 'Дата', "
                                                    "'CatalogRef.Контрагенты' и т.п."
                                                ),
                                            },
                                            "indexing": {
                                                "type": "string",
                                                "enum": ["DontIndex", "Index", "IndexWithAdditionalOrder"],
                                            },
                                            "fillChecking": {
                                                "type": "string",
                                                "enum": ["DontCheck", "ShowError", "ShowWarning"],
                                            },
                                            "synonym": {"type": "string"},
                                            "comment": {"type": "string"},
                                        },
                                        "required": ["name", "type"],
                                    },
                                },
                                "tabularSections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "pattern": "^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$",
                                                "maxLength": 128,
                                            },
                                            "attrs": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "name": {
                                                            "type": "string",
                                                            "pattern": "^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$",
                                                            "maxLength": 128,
                                                        },
                                                        "type": {"type": "string"},
                                                    },
                                                    "required": ["name", "type"],
                                                },
                                            },
                                        },
                                        "required": ["name"],
                                    },
                                },
                                "dimensions": {
                                    "type": "array",
                                    "description": "Для регистров — измерения. Структура как attributes.",
                                    "items": {"type": "object"},
                                },
                                "resources": {
                                    "type": "array",
                                    "description": "Для регистров — ресурсы. Структура как attributes.",
                                    "items": {"type": "object"},
                                },
                                "enumValues": {
                                    "type": "array",
                                    "description": "Для Enum — значения перечисления.",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {
                                                "type": "string",
                                                "pattern": "^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$",
                                            },
                                            "synonym": {"type": "string"},
                                        },
                                        "required": ["name"],
                                    },
                                },
                                "forms":     {"type": "array", "items": {"type": "string"}},
                                "templates": {"type": "array", "items": {"type": "string"}},
                                "commands":  {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "modify": {
                            "type": "object",
                            "properties": {
                                "properties": {
                                    "type": "object",
                                    "description": (
                                        "Изменить свойства объекта. Примеры ключей: "
                                        "CodeLength, DescriptionLength, Hierarchical, "
                                        "Owners (массив), RegisterRecords (массив)."
                                    ),
                                },
                                "attributes": {
                                    "type": "object",
                                    "description": (
                                        "Изменить существующие реквизиты. Ключ — "
                                        "текущее имя, значение — словарь изменений "
                                        "{name? (переименование), type?, synonym?, ...}"
                                    ),
                                },
                                "tabularSections": {"type": "object"},
                            },
                        },
                        "remove": {
                            "type": "object",
                            "properties": {
                                "attributes":      {"type": "array", "items": {"type": "string"}},
                                "tabularSections": {"type": "array", "items": {"type": "string"}},
                                "dimensions":      {"type": "array", "items": {"type": "string"}},
                                "resources":       {"type": "array", "items": {"type": "string"}},
                                "enumValues":      {"type": "array", "items": {"type": "string"}},
                                "forms":           {"type": "array", "items": {"type": "string"}},
                                "templates":       {"type": "array", "items": {"type": "string"}},
                                "commands":        {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "set": {
                            "type": "object",
                            "description": (
                                "Установить целиком сложные свойства (старое содержимое "
                                "заменяется). Ключи: owners, registerRecords, basedOn, "
                                "inputByString — массивы ссылок 'Type.Name'."
                            ),
                        },
                    },
                },
            },
            "required": ["object_path", "definition"],
        },
    )
    async def meta_edit(args: dict) -> dict:
        return await _safe_call(
            executor._meta_edit,
            args["object_path"],
            args["definition"],
        )

    @tool(
        "cfe_borrow",
        "Заимствование типового объекта из основной конфигурации в расширение. "
        "Нужно ПЕРЕД добавлением реквизитов к типовому объекту или перехватом "
        "его методов. Формат object: 'Catalog.Name' / 'Document.Name' / "
        "'CommonModule.Name' / 'Catalog.Name.Form.FormName'. "
        "Batch через ';;'. Для форм с реквизитами: borrow_main_attribute = "
        "'Form' (реквизиты с формы) или 'All' (всё).",
        {
            "type": "object",
            "properties": {
                "object": {"type": "string", "description": "Полное имя в нотации Type.Name[.Form.FormName]"},
                "borrow_main_attribute": {"type": "string", "enum": ["Form", "All"], "description": "Опционально для форм"},
            },
            "required": ["object"],
        },
    )
    async def cfe_borrow(args: dict) -> dict:
        return await _safe_call(
            executor._cfe_borrow,
            args["object"],
            args.get("borrow_main_attribute") or None,
        )

    @tool(
        "cfe_patch_method",
        "Создать каркас перехватчика метода в заимствованном объекте 1С. "
        "Генерирует BSL-каркас с директивой (&Перед / &После / &Вместо / "
        "&ИзменениеИКонтроль) и именем процедуры с префиксом расширения. "
        "Объект должен быть заимствован через cfe_borrow ЗАРАНЕЕ. "
        "ПРАВИЛО ВЫБОРА МЕХАНИЗМА: по умолчанию 'Instead' (&Вместо) + "
        "ПродолжитьВызов — он общий (код до ПродолжитьВызов = «перед», после = "
        "«после», без вызова = полная замена) и НЕ требует копии оригинала. "
        "'ModificationAndControl' (&ИзменениеИКонтроль) ВРУЧНУЮ ЗАПРЕЩЁН: требует "
        "байт-точной копии тела оригинала, которую правкой не воспроизвести — "
        "платформа выдаст «Текст модуля для метода … изменился» при ПРИМЕНЕНИИ "
        "(db_load это НЕ ловит — ловит apply-проверка). "
        "ВАЖНО: создаёт только КАРКАС — тело дописывается через Read + Edit; для "
        "&Вместо сигнатура повторяет параметры оригинала и передаёт их в "
        "ПродолжитьВызов.",
        {
            "type": "object",
            "properties": {
                "module_path":      {"type": "string", "description": "'Catalog.X.ObjectModule' / 'CommonModule.Y' / 'Document.X.ObjectModule' / 'Catalog.X.Form.Y'"},
                "method_name":      {"type": "string", "description": "'ПриЗаписи', 'ОбработкаПроведения', ..."},
                "interceptor_type": {"type": "string", "enum": ["Before", "After", "Instead", "ModificationAndControl"], "description": "Instead (&Вместо)+ПродолжитьВызов — КАНОНИЧЕСКИЙ выбор, без копии оригинала. Before/After — точечно. ModificationAndControl — НЕ использовать вручную (хрупкая байт-копия)."},
                "context":          {"type": "string", "description": "'НаСервере' (по умолч.) / 'НаКлиенте' / 'НаКлиентеНаСервереБезКонтекста'"},
                "is_function":      {"type": "boolean", "description": "true если оригинал — функция"},
            },
            "required": ["module_path", "method_name", "interceptor_type"],
        },
    )
    async def cfe_patch_method(args: dict) -> dict:
        return await _safe_call(
            executor._cfe_patch_method,
            args["module_path"],
            args["method_name"],
            args["interceptor_type"],
            args.get("context") or "НаСервере",
            bool(args.get("is_function", False)),
        )

    @tool(
        "cfe_validate",
        "Полная валидация расширения: XML-формат, свойства, согласованность "
        "Configuration.xml с файлами, заимствованные объекты. "
        "ОБЯЗАТЕЛЬНО вызывать ПЕРЕД db_load. Без параметров.",
        {"type": "object", "properties": {}},
    )
    async def cfe_validate(args: dict) -> dict:
        return await _safe_call(executor._cfe_validate)

    # ── Платформенная справка 1С (локальный SQLite индекс shcntx_ru.hbk) ────

    @tool(
        "platform_doc_lookup",
        "СТРОГАЯ платформенная справка 1С — официальная документация из "
        "shcntx_ru.hbk (~25 000 записей). ОБЯЗАТЕЛЬНО вызывай ПЕРЕД "
        "использованием ЛЮБОГО платформенного метода/свойства/события/объекта "
        "1С. Возвращает signature, description, params, returns, example. "
        "Если found=0 — этого нет в платформе, не выдумывай.",
        {
            "type": "object",
            "properties": {
                "name":  {"type": "string", "description": "Имя на ru или en, без скобок. 'БлокировкаДанных', 'ИсточникДанных', 'Lock'"},
                "limit": {"type": "integer", "default": 5, "description": "Макс. результатов (одно имя часто имеет несколько контекстов)"},
            },
            "required": ["name"],
        },
    )
    async def platform_doc_lookup(args: dict) -> dict:
        return await _safe_call(
            executor._platform_doc_lookup,
            args["name"],
            int(args.get("limit", 5)),
        )

    @tool(
        "platform_doc_search",
        "СЕМАНТИЧЕСКИЙ поиск по платформенной справке 1С (ChromaDB + bge-m3). "
        "Используй когда не знаешь точное имя метода — задавай ВОПРОС или "
        "ФРАЗУ: 'как заблокировать данные перед записью', 'способы поиска "
        "в справочнике по реквизиту', 'обработка проведения документа'. "
        "Для точного поиска по известному имени (например 'Блокировка"
        "Данных') используй platform_doc_lookup — он точнее. "
        "Возвращает топ-5 наиболее близких по смыслу разделов с similarity "
        "score (0..1) и кратким снижетом.",
        {
            "type": "object",
            "properties": {
                "query":  {"type": "string", "description": "Запрос на русском или английском, фраза/вопрос"},
                "limit":  {"type": "integer", "default": 5, "description": "Сколько топ-результатов вернуть"},
                "kind":   {"type": "string", "description": "Опц. фильтр по типу: method, property, event, object, ..."},
            },
            "required": ["query"],
        },
    )
    async def platform_doc_search(args: dict) -> dict:
        return await _safe_call(
            executor._platform_doc_search,
            args["query"],
            int(args.get("limit", 5)),
            args.get("kind") or None,
        )

    # ── Sprint 1 Step 2: Hot tools для форм/метаданных/БД ─────────────────
    # Обёртки над .claude/skills/* — заменяют ручной Edit/Bash XML на
    # структурные операции. Снимают «слепые» Edit+regex циклы на Form.xml
    # (главная причина 4 из 5 провалов Промпт.txt по аудиту 2026-05-15).

    @tool(
        "form_info",
        "Сводка структуры управляемой формы 1С (Form.xml): дерево элементов, "
        "реквизиты с типами, команды, события. ИСПОЛЬЗУЙ ВМЕСТО Read для "
        "понимания формы — Read XML съедает в 5-10 раз больше turns и шумит. "
        "Возвращает компактный самодокументированный вывод.",
        {
            "type": "object",
            "properties": {
                "form_path": {"type": "string", "description": "Путь к Form.xml (абс. или относ. ext_src)"},
                "expand":    {"type": "string", "description": "Опц. раскрыть секцию по имени или '*' — все"},
                "limit":     {"type": "integer", "minimum": 1, "maximum": 5000, "description": "Опц. лимит строк, default 150"},
                "offset":    {"type": "integer", "minimum": 0, "description": "Опц. пропустить N строк (пагинация)"},
            },
            "required": ["form_path"],
        },
    )
    async def form_info(args: dict) -> dict:
        return await _safe_call(
            executor._form_info,
            args.get("form_path", ""),
            args.get("expand") or None,
            args.get("limit"),
            args.get("offset"),
        )

    @tool(
        "form_validate",
        "Локальная валидация управляемой формы 1С (Form.xml): уникальность ID, "
        "companion-элементы, корректность DataPath, ссылок на команды. "
        "ОБЯЗАТЕЛЬНО вызывай после form_edit / form_compile ДО cfe_validate / "
        "db_load — ловит DataPath-ошибки локально, без обращения к 1С (на "
        "порядок быстрее и не съедает квоту turns).",
        {
            "type": "object",
            "properties": {
                "form_path":  {"type": "string", "description": "Путь к Form.xml"},
                "detailed":   {"type": "boolean", "description": "Опц. подробный вывод (включая успешные проверки)"},
                "max_errors": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Опц. остановиться после N ошибок (default 30)"},
            },
            "required": ["form_path"],
        },
    )
    async def form_validate(args: dict) -> dict:
        return await _safe_call(
            executor._form_validate,
            args.get("form_path", ""),
            bool(args.get("detailed", False)),
            int(args.get("max_errors") or 30),
        )

    @tool(
        "form_edit",
        "Добавление элементов / реквизитов / команд в СУЩЕСТВУЮЩИЙ Form.xml "
        "через JSON-описание. Автоматически выделяет ID из правильного пула, "
        "генерирует companion-элементы (ContextMenu, ExtendedTooltip) и обработчики. "
        "Для extension-форм (с <BaseForm>) автоматически включает extension-режим. "
        "ИСПОЛЬЗУЙ ВМЕСТО ручного Edit Form.xml — Edit'ом XML невозможно сделать "
        "корректно (companions, ID, namespace). JSON-файл нужно создать "
        "Write-tool'ом заранее (см. подробности параметров в SKILL.md form-edit).",
        {
            "type": "object",
            "properties": {
                "form_path": {"type": "string", "description": "Путь к существующему Form.xml"},
                "json_path": {"type": "string", "description": "Путь к JSON-файлу с описанием добавлений (создай его через Write)"},
            },
            "required": ["form_path", "json_path"],
        },
    )
    async def form_edit(args: dict) -> dict:
        return await _safe_call(
            executor._form_edit,
            args.get("form_path", ""),
            args.get("json_path", ""),
        )

    @tool(
        "form_compile",
        "Генерация Form.xml с НУЛЯ. Два режима:\n"
        "  • from_object=true → автоматически по метаданным объекта (типовая "
        "форма ERP-preset). Объект и purpose извлекаются из output_path вида "
        "'.../TypePlural/ObjectName/Forms/FormName/Ext/Form.xml'. json_path не нужен.\n"
        "  • from_object=false (default) → из JSON-DSL (json_path обязателен). "
        "Подробности JSON-формата — в SKILL.md form-compile.\n"
        "ВСЕГДА вызывай вместо ручного Write Form.xml.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Путь куда писать Form.xml"},
                "json_path":   {"type": "string", "description": "Путь к JSON-DSL (нужно если from_object=false)"},
                "from_object": {"type": "boolean", "description": "Опц. true → автогенерация по метаданным объекта"},
            },
            "required": ["output_path"],
        },
    )
    async def form_compile(args: dict) -> dict:
        return await _safe_call(
            executor._form_compile,
            args.get("output_path", ""),
            args.get("json_path", "") or "",
            bool(args.get("from_object", False)),
        )

    @tool(
        "meta_info",
        "Сводка структуры объекта метаданных 1С (Catalog / Document / Register / "
        "Enum / HTTPService / WebService / ...): реквизиты с типами, ТЧ, формы, "
        "движения. ИСПОЛЬЗУЙ ВМЕСТО Read XML — даёт компактный самодокументированный "
        "вывод. Три режима через mode: 'overview' (default, ключевые свойства), "
        "'brief' (одной строкой), 'full' (всё раскрыто). name — drill-down по "
        "конкретному реквизиту / ТЧ / шаблону URL / операции.",
        {
            "type": "object",
            "properties": {
                "object_path": {"type": "string", "description": "Путь к .xml объекта или к каталогу (авто-резолв <name>/<name>.xml)"},
                "mode":        {"type": "string", "enum": ["overview", "brief", "full"], "description": "Режим вывода, default overview"},
                "name":        {"type": "string", "description": "Опц. имя элемента для drill-down (ТЧ, реквизит, операция)"},
                "limit":       {"type": "integer", "minimum": 1, "maximum": 5000},
                "offset":      {"type": "integer", "minimum": 0},
            },
            "required": ["object_path"],
        },
    )
    async def meta_info(args: dict) -> dict:
        return await _safe_call(
            executor._meta_info,
            args.get("object_path", ""),
            args.get("mode") or "overview",
            args.get("name") or None,
            args.get("limit"),
            args.get("offset"),
        )

    @tool(
        "meta_validate",
        "Локальная валидация ОДНОГО объекта метаданных 1С — ДО полной "
        "cfe_validate. Дешевле, чем cfe_validate (та проходит по всему "
        "расширению). Для batch'а — передавай несколько путей через '|': "
        "'Catalogs/A|Documents/B'.",
        {
            "type": "object",
            "properties": {
                "object_path": {"type": "string", "description": "Путь к XML или папке объекта (для batch — pipe-separated)"},
                "detailed":    {"type": "boolean"},
                "max_errors":  {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["object_path"],
        },
    )
    async def meta_validate(args: dict) -> dict:
        return await _safe_call(
            executor._meta_validate,
            args.get("object_path", ""),
            bool(args.get("detailed", False)),
            int(args.get("max_errors") or 30),
        )

    @tool(
        "subsystem_edit",
        "Sprint 2 hotfix-5: Точечная правка подсистемы 1С (включение объекта "
        "в подсистему, добавление дочерней подсистемы, изменение свойств). "
        "Решает в 1 turn задачу типа «Включи справочник X в подсистему Y». "
        "ВСЕГДА используй ВМЕСТО Edit XML на Subsystems/*.xml — структура "
        "ChildObjects/Properties/Content имеет специфичную разметку, "
        "Edit ломает её.\n\n"
        "Operations:\n"
        "  • add-content — value='Catalog.X' или JSON-массив объектов\n"
        "  • remove-content — value='Catalog.X' или JSON-массив\n"
        "  • add-child — value='ИмяДочернейПодсистемы'\n"
        "  • remove-child — value='ИмяДочернейПодсистемы'\n"
        "  • set-property — value='{\"name\":\"...\",\"value\":\"...\"}'",
        {
            "type": "object",
            "properties": {
                "subsystem_path": {
                    "type": "string",
                    "description": "Путь к XML подсистемы (например Subsystems/Финансы.xml)",
                },
                "operation": {
                    "type": "string",
                    "enum": ["add-content", "remove-content", "add-child",
                             "remove-child", "set-property"],
                    "description": "Тип операции",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Значение операции. Для add/remove-content: 'Type.Name' "
                        "или JSON-массив. Для add/remove-child: имя подсистемы. "
                        "Для set-property: JSON {'name':..,'value':..}."
                    ),
                },
                "no_validate": {
                    "type": "boolean",
                    "description": "Пропустить авто-валидацию",
                },
            },
            "required": ["subsystem_path", "operation"],
        },
    )
    async def subsystem_edit(args: dict) -> dict:
        return await _safe_call(
            executor._subsystem_edit,
            args.get("subsystem_path", ""),
            args.get("operation", ""),
            args.get("value") or None,
            bool(args.get("no_validate", False)),
        )

    @tool(
        "db_update",
        "UpdateDBCfg — применяет загруженную конфигурацию к БД. "
        "Иногда нужен после db_load (если 1С не применила структуру автоматически) — "
        "например при добавлении/удалении реквизитов. Реквизиты подключения "
        "берутся из client_cfg автоматически.",
        {
            "type": "object",
            "properties": {
                "dynamic":        {"type": "string", "enum": ["+", "-"], "description": "Опц. '+' — динамическое, '-' — отключить"},
                "extension":      {"type": "string", "description": "Опц. override имени расширения. Если пусто — берём cfg.extension"},
                "all_extensions": {"type": "boolean", "description": "Опц. обновить ВСЕ расширения. Игнорируется если задан extension"},
            },
        },
    )
    async def db_update(args: dict) -> dict:
        return await _safe_call(
            executor._db_update,
            args.get("dynamic") or None,
            args.get("extension") or None,
            bool(args.get("all_extensions", False)),
        )

    @tool(
        "db_run",
        "Запуск 1С:Предприятие в пользовательском режиме (на фоне). Используй "
        "когда нужно открыть базу для ручной проверки результата. Реквизиты "
        "подключения берутся из client_cfg.",
        {
            "type": "object",
            "properties": {
                "execute": {"type": "string", "description": "Опц. путь к .epf — запустить обработку сразу после старта"},
                "url":     {"type": "string", "description": "Опц. навигационная ссылка вида 'e1cib/data/Справочник.X'"},
                "c_param": {"type": "string", "description": "Опц. параметр запуска (/C)"},
            },
        },
    )
    async def db_run(args: dict) -> dict:
        return await _safe_call(
            executor._db_run,
            args.get("execute") or None,
            args.get("url") or None,
            args.get("c_param") or None,
        )

    @tool(
        "syntax_check",
        "Sprint 2 S2.1: Локальная проверка BSL-кода через BSL Language Server "
        "(нативный .exe, без Docker и без Java). Используй ПОСЛЕ правки .bsl-"
        "файла и ДО cfe_validate — синтаксические ошибки и нарушения стиля 1С "
        "ловятся локально, без обращения к 1С. Если BSL LS не установлен на "
        "машине — fallback на легковесную Python-проверку (только баланс "
        "Процедура/КонецПроцедуры и т.п.). Setup BSL LS: положи "
        "bsl-language-server.exe в D:\\CURSORIC\\agenter\\mcp-servers\\bsl-ls\\ "
        "(скачай с github.com/1c-syntax/bsl-language-server/releases).",
        {
            "type": "object",
            "properties": {
                "target_path": {
                    "type": "string",
                    "description": (
                        "Путь к .bsl-файлу (или папке с BSL-исходниками). "
                        "Например: ext_src/CommonModules/Foo/Ext/Module.bsl"
                    ),
                },
                "timeout_sec": {
                    "type": "integer", "minimum": 5, "maximum": 600,
                    "description": "Опц. таймаут запуска LS (default 120)",
                },
            },
            "required": ["target_path"],
        },
    )
    async def syntax_check(args: dict) -> dict:
        return await _safe_call(
            executor._syntax_check,
            args.get("target_path", ""),
            timeout=int(args.get("timeout_sec") or 120),
        )

    # ── Sprint 1 Step 3: Skill Registry — cold skills через мета-tool'ы ──
    # 53 «холодных» скилла (mxl-, skd-, role-, subsystem-, epf-, erf-, web-, …)
    # доступны не как первоклассные tools (раздуло бы tool-list на ~5KB и
    # запутало бы LLM похожими именами), а через дискавери:
    #   1. agent зовёт skill_search("СКД отчёт") → топ-5 кандидатов
    #   2. agent зовёт skill_run("skd-compile", {"json_path": "...", ...})
    # Hot skills (form-/meta-/db-* которые уже первоклассные) из skill_search
    # исключены автоматически — чтобы не дублировались.

    # Инициализируем реестр с правильным skills_root из client_cfg (или auto).
    _skills_root = (getattr(executor, "cfg", {}) or {}).get("skills_dir")
    _registry = get_registry(_skills_root)

    @tool(
        "skill_search",
        "Поиск по каталогу из 60+ готовых 1С-скиллов (макеты MXL, СКД, роли, "
        "подсистемы, внешние обработки/отчёты, веб-публикация, и пр.). "
        "ВСЕГДА вызывай ПЕРЕД тем как делать что-то нестандартное руками через "
        "Edit/Bash/Write XML — велик шанс что уже есть готовый скилл. "
        "Запрос — фраза по существу задачи (русский или английский): "
        "'компиляция СКД', 'добавить роль', 'веб-публикация'. "
        "Возвращает топ-5 кандидатов с описанием и подсказкой по аргументам. "
        "После найденного — вызывай skill_run(name, args).",
        {
            "type": "object",
            "properties": {
                "query":    {"type": "string", "minLength": 1, "description": "Что нужно сделать (фраза)"},
                "category": {"type": "string", "description": "Опц. фильтр по категории: 'Форма', 'СКД', 'Роль', 'Подсистема', 'Макет MXL', 'Внешняя обработка', 'Внешний отчёт', 'База данных', 'Расширение', 'Веб-публикация' и т.п."},
                "top_k":    {"type": "integer", "minimum": 1, "maximum": 10, "description": "Сколько кандидатов вернуть, default 5"},
            },
            "required": ["query"],
        },
    )
    async def skill_search(args: dict) -> dict:
        query    = (args.get("query") or "").strip()
        category = args.get("category") or None
        top_k    = int(args.get("top_k") or 5)
        try:
            results = _registry.search(query, category=category, top_k=top_k)
        except Exception as exc:
            log.exception("skill_search failed")
            return _err(f"skill_search ERROR: {exc}")
        if not results:
            return _ok(f"Не найдено скиллов по запросу «{query}». "
                       f"Попробуй другие слова или используй встроенные tools "
                       f"(Read/Write/Edit/Bash).")
        lines = [f"Найдено {len(results)} скилл(а):", ""]
        for e in results:
            lines.append(f"• {e.name}  [{e.category}]")
            if e.description:
                lines.append(f"    {e.description}")
            if e.args_hint:
                lines.append(f"    Аргументы: {e.args_hint}")
            lines.append("")
        lines.append("Вызов: skill_run(name='<имя>', args={…})")
        return _ok("\n".join(lines))

    @tool(
        "skill_run",
        "Выполняет скилл из каталога .claude/skills/ — найди подходящий через "
        "skill_search, потом вызови skill_run с его name. Аргументы передавай "
        "в args как dict с ключами в snake_case — они автоматически "
        "конвертируются в PowerShell-параметры PascalCase. "
        "Пример: skill_run('skd-compile', {'json_path': 'tmp/skd.json', 'output_path': 'Reports/X/Templates/Main/Ext/Template.xml'}). "
        "Bool True → флаг без значения (например {'detailed': true} → '-Detailed').",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 2, "description": "Имя скилла (например 'skd-compile', 'role-compile', 'mxl-compile')"},
                "args": {"type": "object", "description": "Параметры. Ключи в snake_case, конвертятся в -PascalCase. Bool true → флаг. Null/'' → пропуск."},
                "timeout_sec": {"type": "integer", "minimum": 10, "maximum": 3600, "description": "Опц. таймаут в секундах (default 600)"},
            },
            "required": ["name"],
        },
    )
    async def skill_run(args: dict) -> dict:
        name = (args.get("name") or "").strip()
        raw_args = args.get("args") or {}
        timeout = int(args.get("timeout_sec") or 600)
        if not name:
            return _err("skill_run: пустое имя скилла")
        entry = _registry.get(name)
        if entry is None:
            return _err(
                f"skill_run: скилл '{name}' не найден. "
                f"Используй skill_search чтобы найти доступные."
            )
        if not isinstance(raw_args, dict):
            return _err(f"skill_run: args должен быть object/dict, получен {type(raw_args).__name__}")
        cli = args_to_ps_cli(raw_args)
        try:
            out = await executor._run_skill_by_path(
                str(entry.script_path),
                *cli,
                timeout=timeout,
            )
        except Exception as exc:
            log.exception("skill_run %s failed", name)
            return _err(f"skill_run('{name}') ERROR: {exc}")
        # Префиксуем имя скилла и обрезаем хвост, чтобы не съедать turn-quota
        tail = out[-3000:] if len(out) > 3000 else out
        return _ok(f"{name} OK\n{tail}")

    # ── ask_user: блокирующий вопрос к юзеру ───────────────────────────────
    # Регистрируется только если task_id + on_ask_user переданы — иначе агенту
    # некуда «спросить». Это намеренно: tool появляется в списке allowed только
    # когда есть инфраструктура для модалки.

    tools = [
        db_dump, db_load,
        meta_compile, meta_edit,
        cfe_borrow, cfe_patch_method, cfe_validate,
        platform_doc_lookup, platform_doc_search,
        # Sprint 1 Step 2 — hot tools (form/meta/db)
        form_info, form_validate, form_edit, form_compile,
        meta_info, meta_validate,
        subsystem_edit,  # Sprint 2 hotfix-5
        db_update, db_run,
        # Sprint 2 S2.1 — native BSL Language Server (без Docker)
        syntax_check,
        # Sprint 1 Step 3 — skill registry meta-tools
        skill_search, skill_run,
    ]

    if ask_user_ctx and ask_user_ctx.get("on_ask_user") and ask_user_ctx.get("task_id"):
        _task_id = ask_user_ctx["task_id"]
        _on_ask_user = ask_user_ctx["on_ask_user"]

        @tool(
            "ask_user",
            (
                "Спросить ПОЛЬЗОВАТЕЛЯ уточнение. Используй когда:\n"
                "  • упёрся в неустранимое препятствие (например preflight "
                "отвергает корректный объект, ТЗ противоречит существующей "
                "конфигурации, неоднозначное название);\n"
                "  • нужно принять ключевое решение, которое нельзя угадать "
                "(префикс расширения, политика именования, выбор между "
                "несколькими существующими справочниками);\n"
                "  • та же ошибка повторилась подряд после исправления.\n"
                "НЕ используй для тривиальных решений, которые можешь "
                "принять сам (выбор имени реквизита по ТЗ, формат XML и т.п.) — "
                "это раздражает юзера.\n"
                "Тооl БЛОКИРУЮЩИЙ: возвращает текст ответа когда юзер ответит. "
                "Если задача отменена — вернёт '[CANCELLED: ...]'. "
                "Если юзер не ответил за 10 минут — '[TIMEOUT: ...]'."
            ),
            {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 2000,
                        "description": (
                            "Чёткий вопрос юзеру на русском. Без воды, "
                            "одно предложение или короткий абзац. Указывай "
                            "почему ты остановился."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 200},
                        "maxItems": 6,
                        "description": (
                            "Опц. варианты ответа (2-6). Если заданы — UI "
                            "покажет radio-buttons. Если нет — свободный ввод."
                        ),
                    },
                },
                "required": ["question"],
            },
        )
        async def ask_user(args: dict) -> dict:
            q = (args.get("question") or "").strip()
            if not q:
                return _err("ask_user: question пустой — нечего спросить")
            opts = args.get("options") or []
            if not isinstance(opts, list):
                opts = []
            try:
                answer = await _on_ask_user(_task_id, q, opts)
            except Exception as exc:
                log.exception("ask_user failed")
                return _err(f"ask_user ERROR: {exc}")
            return _ok(answer)

        tools.append(ask_user)

    # ── Создаём SDK MCP server из всего набора ─────────────────────────────

    server = create_sdk_mcp_server(
        name="agenter",
        version="1.0.0",
        tools=tools,
    )
    return server


# Список tool-имён в формате SDK (mcp__agenter__<name>) — для allowed_tools.
AGENTER_TOOL_NAMES = [
    "mcp__agenter__db_dump",
    "mcp__agenter__db_load",
    "mcp__agenter__meta_compile",
    "mcp__agenter__meta_edit",
    "mcp__agenter__cfe_borrow",
    "mcp__agenter__cfe_patch_method",
    "mcp__agenter__cfe_validate",
    "mcp__agenter__platform_doc_lookup",
    "mcp__agenter__platform_doc_search",
    # Sprint 1 Step 2 — hot tools (form/meta/db skill wrappers).
    "mcp__agenter__form_info",
    "mcp__agenter__form_validate",
    "mcp__agenter__form_edit",
    "mcp__agenter__form_compile",
    "mcp__agenter__meta_info",
    "mcp__agenter__meta_validate",
    "mcp__agenter__subsystem_edit",  # Sprint 2 hotfix-5
    "mcp__agenter__db_update",
    "mcp__agenter__db_run",
    # Sprint 2 S2.1 — native BSL Language Server check
    "mcp__agenter__syntax_check",
    # Sprint 1 Step 3 — skill registry meta-tools (доступ к 50+ cold skills)
    "mcp__agenter__skill_search",
    "mcp__agenter__skill_run",
    # ask_user: зарегистрирован всегда в allowlist, но сам tool существует
    # в SDK MCP server только если run_task получил on_ask_user (см. orchestrator_sdk).
    "mcp__agenter__ask_user",
]
