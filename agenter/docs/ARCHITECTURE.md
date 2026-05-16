# Архитектура Agenter

## Что это

Десктопный AI-агент для разработки в 1С:Enterprise. Один Python-процесс крутит FastAPI + Claude Agent SDK + PyWebView UI. Агент использует tools для работы с конфигурацией 1С (выгрузка XML, редактирование метаданных, заимствование объектов, проверка кода).

## Компоненты

```
┌───────────────────────────────────────────────────────────────────────┐
│  PyWebView Window                                                     │
│  ┌──────────────┬──────────────────────────────┬──────────────────┐  │
│  │  Sidebar     │   Chat area                  │  RightPanel       │  │
│  │  - Проекты   │   - User message             │  - Agent status   │  │
│  │  - Дерево    │   - Agent steps              │  - Состояние БД   │  │
│  │    метадан.  │   - Tool calls               │  - Изменения      │  │
│  │  - История   │                              │                   │  │
│  └──────────────┴──────────────────────────────┴──────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ HTTP / WebSocket (http://localhost:8080)
                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│  FastAPI backend (app/main.py)                                        │
│    /tasks          — создать задачу                                   │
│    /ops/{op}       — запустить ops_runner-операцию                    │
│    /ops/state      — статус всех операций                             │
│    /metadata/tree  — структура SCHEME                                 │
│    /ws/events      — стрим логов агента                               │
└───────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ orchestrator_sdk.run_task()
                                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│  Claude Agent SDK loop                                                │
│    1. system_prompt с контекстом проекта                              │
│    2. user prompt                                                     │
│    3. tools/list (всё что зарегистрировано)                           │
│    4. LLM выбирает tool → tools/call                                  │
│    5. Результат tool возвращается в LLM                               │
│    6. Loop пока не финальный ответ                                    │
└───────────────────────────────────────────────────────────────────────┘
       │                                              │
       │ Built-in tools                               │ MCP tools
       │ (Read/Write/Edit/Glob/Grep/Bash/...)         │
       ▼                                              ▼
┌─────────────────────────┐         ┌──────────────────────────────────┐
│  Custom @tool (SDK)     │         │  External MCP servers (HTTP)     │
│  app/sdk_tools.py       │         │  app/mcp_registry.py             │
│  - db_dump              │         │  - bsl-atlas (структура SCHEME)  │
│  - db_load              │         │  [потенциально: syntax, help,    │
│  - meta_compile         │         │   ssl — но через свои Python-    │
│  - meta_edit            │         │   реализации, не Docker]         │
│  - cfe_borrow           │         └──────────────────────────────────┘
│  - cfe_patch_method     │
│  - cfe_validate         │
│  - platform_doc_lookup  │  ← FTS5 точный
│  - platform_doc_search  │  ← ChromaDB семантический (НОВОЕ)
└─────────────────────────┘
       │
       │ ToolExecutor (desktop/main.py)
       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  PowerShell skills (scripts/)                                         │
│    - db-dump-xml.ps1     (1С Конфигуратор)                            │
│    - db-load-xml.ps1     (1С Конфигуратор)                            │
│    - meta-edit/*.ps1     (XML манипуляции)                            │
│    - cfe-borrow/*.ps1                                                 │
│    - cfe-validate/*.ps1                                               │
└───────────────────────────────────────────────────────────────────────┘
```

## Внешние сервисы

### BSL Atlas (отдельный процесс)
- Путь: `C:\BUFFER\tools\bsl-atlas\` (вне agenter)
- Запускается автоматически Agenter'ом при старте
- Порт: `localhost:8765`
- Tools: `search_function`, `metadatasearch`, `get_object_details`, `code_grep`
- Источник данных: `SCHEME/` (XML-выгрузка конфигурации, ~9 ГБ, 122k файлов)

### 1С Платформа (внешняя)
- Путь: `C:\Program Files\1cv8\8.3.27.1859\bin\`
- Используется для запуска Конфигуратора (`db-dump-xml`, `db-load-xml`)
- shcntx_ru.hbk — источник справки платформы

## Индексы (data/)

| Индекс | Что индексирует | Размер | Использование |
|---|---|---|---|
| `platform_docs.db` (SQLite + FTS5) | shcntx_ru.hbk → 25 509 методов/свойств/объектов | ~34 МБ | Точный поиск: `platform_doc_lookup("БлокировкаДанных")` |
| `platform_docs_chroma/` (ChromaDB + USER-bge-m3) | те же 25 509 записей в векторах 1024-dim | ~300 МБ | Семантический поиск: `platform_doc_search("как заблокировать данные")` |
| `xsd/*.json` (от MetadataViewer1C) | 27 XDTO-схем платформы | ~600 КБ | Валидация структуры XML |
| `bsl-atlas/bsl_index.db` (SQLite) | SCHEME/ → ~16 500 объектов метаданных | ~2.6 ГБ | Структурный поиск через bsl-atlas |

## Поток выполнения задачи

```
User: "Добавь в справочник Банки реквизит Город — Строка(50)"
  │
  ▼
LLM (Claude Sonnet 4):
  1. Понял задачу — модифицирующая
  2. db_dump → синхронизация ext_src/ из БД (защита от затирания ручных правок)
  3. meta_edit Catalogs/Банки add-attribute "Город:String(50)"
     ├── Python-обёртка нормализует value (Город Строка(50) → Город:String(50))
     ├── Python-обёртка валидирует имя (NCName)
     └── PowerShell-скилл вставляет XML
  4. cfe_validate → проверка структуры расширения
  5. db_load → загрузка в БД 1С
  6. Финальный ответ пользователю
```

## Архитектурные принципы

1. **Tools-first** — вся логика в дискретных tools которые LLM может комбинировать. Никаких больших монолитных команд.
2. **Read-side через индексы** — поиск метаданных/справки/кода не идёт в БД и не парсит файлы каждый раз. Всё через SQLite/ChromaDB.
3. **Write-side через PowerShell-скиллы** — модификация XML и работа с 1С Конфигуратором — через standalone PowerShell-скрипты. Это устойчиво к зависанию Python-процесса.
4. **Python-обёртки защищают** — нормализация, валидация, file-lock между Python и PowerShell. LLM ошибается → обёртка перехватывает до записи на диск.
5. **Open-source стек** — никаких чужих лицензионных ключей, никакого Docker как зависимости. Всё что используется встраивается в дистрибутив.
6. **Index immutability** — индексы пересобираются по команде пользователя или после `db_dump`. Не во время агента (не блокируем запросы).

## Зависимости (Python)

- `claude-agent-sdk` — Claude Code SDK
- `fastapi` + `uvicorn` — HTTP backend
- `pywebview` — десктопное окно
- `aiohttp` — HTTP-клиент для MCP
- `chromadb` — векторная БД
- `sentence-transformers` + `torch` — embedding-модель
- `huggingface-hub` — загрузка моделей
- `lxml` (потенциально) — парсинг XML (сейчас xml.etree)
- `onec_dtools` — парсер .hbk справки 1С
- `pydantic` — модели данных

## Зависимости (внешние)

- **1С Предприятие 8.3.27** — конфигуратор, shcntx_ru.hbk
- **PowerShell 5.1** — встроенный в Windows 10/11
- **Python 3.11** — runtime для venv
- **(опц.) NVIDIA driver + CUDA 12.x** — для GPU-ускорения embeddings
