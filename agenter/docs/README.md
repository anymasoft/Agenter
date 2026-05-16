# Документация Agenter

Это главный индекс по всей документации проекта. Если открыл впервые — начинай с **ARCHITECTURE.md**.

## Структура документации

| Файл | Что внутри | Когда читать |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Общая архитектура: компоненты, потоки данных, расположение файлов | При входе в проект, перед крупными изменениями |
| [PROGRESS.md](PROGRESS.md) | Где мы сейчас по дорожной карте (фазы 1-5), что готово, что в работе | Каждый день — чтобы знать на чём остановились |
| [DECISIONS.md](DECISIONS.md) | ADR — все ключевые архитектурные решения с обоснованием | Перед изменением чего-то важного — проверь не было ли обсуждения |
| [CHANGELOG.md](CHANGELOG.md) | Лог изменений по фазам и датам | После завершения фазы / перед релизом |
| [PRO-EDITION-PLAN.md](PRO-EDITION-PLAN.md) | Полный план Фаз 1-5: открыть/закрыть/обновить | Когда меняется стратегия |
| [MCP-SERVERS.md](MCP-SERVERS.md) | DEPRECATED — устаревший план Docker-MCP-серверов | Только для истории |

## Структура исходного кода Agenter

```
agenter/
├── app/                       # Backend Python (FastAPI + Claude Agent SDK)
│   ├── main.py                # FastAPI приложение + lifecycle
│   ├── orchestrator_sdk.py    # LLM agent loop
│   ├── sdk_tools.py           # @tool обёртки для Claude
│   ├── ops_runner.py          # Длинные операции (db_dump, reindex, ...)
│   ├── mcp_registry.py        # Реестр MCP-клиентов (BSL Atlas и т.д.)
│   ├── platform_docs.py       # Индекс справки 1С (SQLite + FTS5)
│   ├── platform_docs_chroma.py # ChromaDB semantic-индекс (USER-bge-m3)
│   ├── xml_validator.py       # Валидация XML по XDTO-схемам
│   ├── cfe_validate_xml.py    # Доп. проверки расширений (R14-R20)
│   ├── tool_guards.py         # Защита от опасных операций
│   ├── _imports.py            # Импорты ToolExecutor из desktop/
│   └── metadata_utils/        # Порт MetadataViewer1C
│       ├── unicode_name.py
│       ├── metadata_scanner.py
│       ├── metadata_parser.py
│       ├── metadata_repository.py
│       ├── metadata_types.py
│       ├── predefined_parser.py
│       ├── role_parser.py
│       └── subsystem_membership.py
├── desktop/
│   └── main.py                # ToolExecutor + PyWebView entry
├── frontend/                  # React + Babel (без сборки)
│   ├── chat-screen.jsx
│   ├── metadata-tree.jsx
│   └── assets/
│       ├── icons/             # SVG объектов 1С (от MetadataViewer1C)
│       └── xslt/              # XSLT-рендер форм (на будущее)
├── scripts/                   # PowerShell-скиллы + утилиты
│   ├── db-dump-xml.ps1
│   ├── db-load-xml.ps1
│   ├── meta-edit/             # Редактирование объектов метаданных
│   ├── meta-compile/          # Создание объектов метаданных
│   ├── cfe-borrow/            # Заимствование типовых объектов
│   ├── cfe-validate/          # Валидация структуры расширения
│   ├── cfe-patch-method/      # Перехватчики методов
│   ├── start-mcp-servers.ps1  # DEPRECATED — Docker MCP-серверы
│   ├── install-cuda-torch.ps1 # Установка GPU-варианта PyTorch
│   ├── run_full_chroma_index.py # Standalone-запуск индексации
│   └── check_chroma_progress.py # Безопасный мониторинг прогресса
├── tools/                     # Встроенные ML-ресурсы
│   └── models/                # HuggingFace кэш модели USER-bge-m3 (1.37 ГБ)
├── data/                      # Пользовательские данные / индексы
│   ├── platform_docs.db       # Справка 1С (SQLite, 34 МБ, 25 509 записей)
│   ├── platform_docs_chroma/  # Векторный индекс (ChromaDB, ~300 МБ)
│   ├── xsd/                   # 27 XDTO JSON-схем от MetadataViewer1C
│   └── field_values.json      # Допустимые значения свойств метаданных
├── config/
│   └── config.json            # Пути, имя расширения, MCP-серверы
├── backend/
│   └── .venv/                 # Python venv (~1.5 ГБ)
├── logs/
└── docs/                      # ← эта документация
```

## Терминология

| Термин | Что значит |
|---|---|
| **SCHEME** | XML-выгрузка основной конфигурации 1С (источник истины) |
| **ext_src** | XML-выгрузка нашего расширения |
| **shcntx_ru.hbk** | Архив справки платформы 1С (поставляется с 1С Предприятие) |
| **БСП** | Библиотека Стандартных Подсистем 1С (встроена в ERP/УТ/УНФ) |
| **CFE** | Configuration Extension — расширение конфигурации |
| **MCP** | Model Context Protocol — стандарт коммуникации с LLM-tools |
| **DSL** | Domain-Specific Language — для команд meta-edit (`Name:Type|flags`) |

## Как обновлять документацию

Правило: **любое архитектурное решение → запись в DECISIONS.md**. Любое выполненное действие → запись в CHANGELOG.md. Каждый день в работе → обновить PROGRESS.md.

Это не бюрократия — это страховка от потери знаний при перезапусках Claude и при возврате к проекту через неделю.
