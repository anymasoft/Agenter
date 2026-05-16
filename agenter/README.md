# Agenter — десктопный AI-агент для 1С

Локальное приложение для разработки в 1С:Предприятие через Claude Agent SDK.
Открывает нативное окно (PyWebView) с веб-UI, внутри встроенный FastAPI и
LLM-цикл. Один процесс — никаких отдельных сервисов, никакого Docker,
никакого облачного backend'а.

## Архитектура

```
┌──────────────────────────────────────────────────────────────────────┐
│  agenter/app/main.py — единый процесс                                │
│                                                                      │
│  ┌─────────────────┐   ┌───────────────────┐   ┌─────────────────┐   │
│  │  PyWebView окно │ ↔ │  FastAPI :8080    │ ↔ │ ToolExecutor    │   │
│  │  (frontend/)    │   │  (REST + WS)      │   │ (PowerShell +   │   │
│  └─────────────────┘   └───────────────────┘   │  MCP + skills)  │   │
│                                  │             └─────────────────┘   │
│                                  ▼                                   │
│                    ┌────────────────────────┐                        │
│                    │  Claude Agent SDK loop │                        │
│                    │  (Anthropic API)       │                        │
│                    └────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────┘
              │                                       │
              │ HTTP                                  │ stdin/stdout
              ▼                                       ▼
   ┌────────────────────┐                  ┌──────────────────────┐
   │ BSL Atlas :8765    │                  │  1cv8.exe (1С)       │
   │ (отд. процесс,     │                  │  Конфигуратор        │
   │ запускается        │                  │  для db_dump/db_load │
   │ автоматически)     │                  └──────────────────────┘
   └────────────────────┘
```

**Что где живёт:**

| Папка | Роль | Запускается? |
|---|---|---|
| `app/main.py` | **Точка входа** — FastAPI + LLM-цикл + PyWebView UI | ✓ единственный entry-point |
| `app/orchestrator_sdk.py` | Claude Agent SDK orchestrator | импорт |
| `app/task_planner.py` | Детерминированная диспетчеризация стадий (Sprint 4) | импорт |
| `app/tool_guards.py` | PreToolUse-проверки (XML/path guards, R7, stage-dispatch) | импорт |
| `app/sdk_tools.py` | Декларации MCP-tool'ов через `@tool` SDK | импорт |
| `backend/main.py` | Модуль с `SYSTEM_PROMPT`, `MAX_ITERATIONS` и др. константами | импорт |
| `backend/.venv/` | **Единый venv** со всеми зависимостями | – |
| `desktop/main.py` | Модуль с `ToolExecutor` — обёртки для PowerShell-скриллов | импорт |
| `frontend/` | Статика веб-UI (раздаётся FastAPI'ем по `/ui/`) | – |
| `scripts/` | Legacy PS-скрипты (`db-dump-xml.ps1`, `db-load-xml.ps1`) | вызываются ToolExecutor'ом |
| `config/config.json` | Настройки 1С (пути, креды, имя расширения) | читается при старте |

**Скиллы конфигурации 1С** лежат в `<project_root>/.claude/skills/` —
это ~60 PowerShell-скриллов (form-edit, meta-compile, subsystem-edit, …),
доступных через hot-tools и `skill_search`/`skill_run`.

**Принципы:**

- **Один процесс** — никаких отдельных backend'ов, ассистентов, WS-relay'ев
- **Данные 1С только локально** — XML, индекс, ext_src не покидают машину
- **LLM-вызовы в Anthropic** — только текст промптов и tool-схемы уходят в облако
- **PowerShell для записи в 1С** — устойчиво к зависанию Python-процесса

---

## Запуск

### Один раз — установка зависимостей

```powershell
cd C:\BUFFER\ERP\agenter\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Это создаёт `backend/.venv/` со всеми пакетами для приложения целиком
(historical name; реально используется и `app/`, и `backend/`, и `desktop/`).

### Один раз — настройка конфига

```powershell
cd C:\BUFFER\ERP\agenter\config
copy config.example.json config.json
notepad config.json
```

Поля для заполнения (`config.json`):

| Поле | Описание | Пример |
|---|---|---|
| `ext_src_path` | Папка `ext_src/` вашего расширения | `C:\BUFFER\ERP\ext_src` |
| `scheme_path` | XML-выгрузка основной конфигурации | `C:\BUFFER\ERP\SCHEME` |
| `v8_path` | `bin/` платформы 1С | `C:\Program Files\1cv8\8.3.27.1859\bin` |
| `base_path` | Папка базы или строка `Srvr=...` | `C:\Users\User\Documents\1C\MyDB` |
| `username` / `password` | Логин/пароль 1С | `Администратор` / *(пусто или ваш пароль)* |
| `extension` | Имя расширения | `МоеРасширение` |
| `skills_dir` | Корень с папками скиллов | `C:\BUFFER\ERP\.claude\skills` |

`ANTHROPIC_API_KEY` — в `agenter/.env` (берётся через `python-dotenv`):
```
ANTHROPIC_API_KEY=sk-ant-...
```

### Запуск приложения

**Самый короткий путь** — `start.bat` в корне `agenter/`:

```powershell
cd C:\BUFFER\ERP\agenter
.\start.bat
```

**Эквивалентная команда вручную:**

```powershell
cd C:\BUFFER\ERP\agenter\app
..\backend\.venv\Scripts\python.exe main.py
```

При старте откроется нативное окно с UI. За кулисами:
1. Поднимется FastAPI на `localhost:8080` (раздаёт `/ui/*` и API)
2. PyWebView откроет окно, навигированное на `localhost:8080/ui/app.html`
3. Автоматически запустится BSL Atlas (`localhost:8765`) — отдельным процессом
4. SDK-loop с Anthropic API подхватывается при первой задаче

Закрытие окна = выход из приложения (stop_bsl_atlas вызывается в finally).

---

## Внешние зависимости

- **Python 3.11+** (для запуска)
- **1С:Предприятие 8.3.27+** (для Конфигуратора и `shcntx_ru.hbk` справки)
- **PowerShell 5.1** (встроен в Windows 10/11; для запуска скриллов)
- **BSL Atlas** в `C:\BUFFER\tools\bsl-atlas\` — запускается автоматически

---

## Первая задача

1. Открыть Agenter (см. «Запуск приложения»)
2. В правой панели «Подключение» должна быть зелёная отметка
3. Написать задачу в чат, нажать **Ctrl+Enter**
4. Наблюдать за ExecLog в реальном времени

Простейший тест:
```
Создай справочник "Острова"
```

Должно отработать за ~10 turns: `plan_task → db_dump → meta_compile → cfe_validate → db_load`.

---

## Документация

- `docs/ARCHITECTURE.md` — компоненты, индексы, поток выполнения задачи
- `docs/DECISIONS.md` — ADR'ы (важные архитектурные решения)
- `docs/PROGRESS.md` — состояние спринтов
- `docs/CHANGELOG.md` — что меняется от версии к версии
- `docs/audit-2026-05-15.md` — последний полный аудит

---

## Структура проекта

```
agenter/
├── app/                          # ТОЧКА ВХОДА
│   ├── main.py                   # FastAPI + PyWebView + LLM loop
│   ├── orchestrator_sdk.py       # Claude Agent SDK runner
│   ├── task_planner.py           # 22 STAGE_KIND + диспетчер (Sprint 4)
│   ├── tool_guards.py            # PreToolUse-проверки
│   ├── sdk_tools.py              # MCP @tool declarations
│   ├── skill_registry.py         # Реестр cold skills
│   ├── bsl_ls.py                 # BSL Language Server интеграция
│   ├── agenter.db                # SQLite (tasks, sessions, stages, phases)
│   └── op_state.json             # Состояние операций
├── backend/
│   ├── main.py                   # SYSTEM_PROMPT, MAX_ITERATIONS и др. константы
│   ├── requirements.txt
│   └── .venv/                    # Единый venv приложения
├── desktop/
│   └── main.py                   # Модуль ToolExecutor (импортируется)
├── frontend/                     # Веб-UI (раздаётся FastAPI'ем)
│   ├── app.html
│   ├── css/
│   └── js/
├── scripts/                      # Legacy скрипты
│   ├── db-dump-xml.ps1
│   └── db-load-xml.ps1
├── config/
│   ├── config.json               # Настройки (gitignore)
│   └── config.example.json
├── data/                         # MEMORY.md, proposals, snapshots
├── docs/                         # Архитектура, ADR, прогресс
├── logs/                         # Создаётся автоматически
├── .env                          # ANTHROPIC_API_KEY (gitignore)
├── .env.example
└── start.bat                     # Удобный запуск приложения
```
