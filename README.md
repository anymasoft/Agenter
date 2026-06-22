# Agenter — локальный AI-агент для разработки расширений 1С

[![Status](https://img.shields.io/badge/status-early%20development-orange)](agenter/docs/external-audit/AUDIT_PROMPT.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Десктопное приложение для разработки расширений к платформе
**1С:Предприятие 8.3** через Claude Agent SDK. Один процесс, локальные
данные, веб-UI в нативном окне.

```
┌──────────────────────────────────────────────────────────────────┐
│  agenter/app/main.py — единый процесс                            │
│                                                                  │
│  PyWebView окно (frontend/)                                      │
│       <->                                                        │
│  FastAPI :8080 (REST + WebSocket)                                │
│       <->                                                        │
│  ToolExecutor (PowerShell + MCP + 67 skills)                     │
│       <->                                                        │
│  Claude Agent SDK loop (Anthropic API)                           │
└──────────────────────────────────────────────────────────────────┘
            |                                       |
            | HTTP                                  | stdin/stdout
            v                                       v
  +------------------+                  +----------------------+
  |  BSL Atlas       |                  |  1cv8.exe            |
  |  (SQLite-индекс  |                  |  Конфигуратор 1С     |
  |   конфигурации)  |                  |  для db_dump/db_load |
  +------------------+                  +----------------------+
```

## Что это

- **Веб-UI** в нативном окне (PyWebView), без браузера
- **Claude Agent SDK** ведёт LLM-цикл с детерминистической диспетчеризацией
  стадий — каждая стадия в плане имеет фиксированный ожидаемый tool
- **67 PowerShell-скиллов** для модификации XML-метаданных 1С
  (forked from [cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills),
  расширены с покрытием регрессионными тестами)
- **BSL Atlas** как внешняя зависимость для структурного и семантического
  поиска по конфигурации
- **Без облака**: всё локально, в Anthropic уходят только промпты и
  схемы tool-вызовов

## Принципы

- **Один процесс.** Никаких отдельных backend'ов, ассистентов, WS-relay'ев.
- **Локальные данные.** XML расширения, индекс, исходники не покидают машину.
- **PowerShell для модификации.** Изолированный язык, устойчиво к падению
  Python-процесса.
- **Test-first.** Каждый прод-баг превращается в регрессионный тест
  ДО фикса. Без этого 67 скиллов превращаются в whack-a-mole.

## Запуск

### Требования

- Windows 10/11
- Python 3.11+
- PowerShell 5.1 (встроен)
- 1С:Предприятие 8.3.27+ (для платформы и Конфигуратора)
- BSL Atlas (опционально, для поиска по конфе)
- Anthropic API key

### Установка

```powershell
git clone https://github.com/anymasoft/ERP.git D:\CURSORIC\agenter
cd D:\CURSORIC\agenter\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Настройка

```powershell
cd D:\CURSORIC\agenter\config
copy config.example.json config.json
notepad config.json
```

Заполните пути к 1С-платформе, базе, расширению (см. `config.example.json`).

API ключ — в файле `D:\CURSORIC\agenter\.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### Старт

```powershell
cd D:\CURSORIC\agenter
.\start.bat
```

Откроется нативное окно с веб-UI. Закрытие окна = выход.

### Тесты

```powershell
cd D:\CURSORIC\agenter
.\run-tests.bat
```

Полная прогонка ~7 секунд: 226 тестов в 67 файлах + аудит покрытия скиллов.

## Состояние

**Early development**, sole-founder. Внутренняя разработка для собственного
ERP-проекта на 1С, готовится к выходу в более широкое использование.

Регрессионная защита: см. `agenter/tests/audit/COVERAGE.md` (генерируется
автоматически — `python -m tests.audit.skill_audit`).

Документация — `agenter/README.md` (подробная) и `agenter/docs/`
(архитектура, ADR, прогресс, аудиты).

## Структура репозитория

```
.
|-- agenter/                     # Само приложение
|   |-- app/                     # Entry point (main.py) + оркестратор + планировщик
|   |-- backend/                 # Константы, requirements.txt
|   |-- desktop/                 # ToolExecutor (модуль)
|   |-- frontend/                # Веб-UI
|   |-- tests/                   # 226 тестов: skills/, app/, audit/, harness/
|   |-- docs/                    # Архитектура, ADR, external-audit/
|   |-- scripts/                 # Legacy PowerShell
|   |-- config/                  # config.example.json (config.json gitignored)
|   |-- start.bat                # Запуск
|   `-- run-tests.bat            # Тесты + аудит покрытия
|-- .claude/
|   `-- skills/                  # 67 PowerShell-скиллов для 1С
|-- CLAUDE.md                    # Правила проекта для Claude Code
|-- .v8-project.example.json     # Шаблон конфига 1С-баз
|-- .gitignore
|-- README.md                    # этот файл
`-- LICENSE                      # MIT
```

## Что НЕ в репо

- `SCHEME/` — XML-выгрузка конкретной 1С-конфигурации (вендорская IP)
- `ext_src/` — конкретное расширение разработчика (бизнес-код)
- `mcp-servers/`, `tsd-emulator/` — отдельные подпроекты
- `agenter/backend/.venv/`, `__pycache__/`, `agenter.db`, `op_state.json`,
  `logs/`, `.env` — runtime state и секреты

## Credits

PowerShell-скиллы — fork от **[cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills)**
(Николай Широков, MIT). Расширены регрессионными тестами и фиксами для
заимствованных подсистем (см. `agenter/tests/skills/test_subsystem_edit.py`,
`test_cfe_borrow.py`).

BSL Atlas — структурный/семантический поисковый индекс по 1С-конфе.

## License

MIT — см. [LICENSE](LICENSE).
