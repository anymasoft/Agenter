# Changelog

Все значимые изменения проекта. Формат [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **2026-05-15 (вечер)**: Полная ChromaDB-индексация на GPU успешно прошла
  - **25,509 / 25,509** векторов закодированы, ChromaDB 217.9 МБ, время ~20 минут
  - RTX 3050 Laptop GPU использован на 100%, без свопа после оптимизаций (ADR-010)
  - Тест 1 (точный поиск): `platform_doc_lookup("БлокировкаДанных")` — отлично работает
  - Тест 2 (семантика): `platform_doc_search` (4 запроса) — релевантные результаты по 3500+ симв.
  - Агент сам разделяет точный/семантический поиск по описанию tools
- **2026-05-15 (вечер)**: System prompt принудительно на русском
  - Добавлен блок «ЯЗЫК ОТВЕТОВ И МЫШЛЕНИЯ» в orchestrator_sdk._build_client_context
  - Thinking-блоки `💭 The user wants...` → `💭 Пользователь хочет...`
  - Технические термины (BSL/PowerShell/MCP/JSON) — остаются как есть
- **2026-05-15**: ChromaDB semantic-индекс справки платформы 1С
  - `app/platform_docs_chroma.py` — модуль с `build_chroma_index` и `search_semantic`
  - Модель: `deepvk/USER-bge-m3` (1.37 ГБ, Apache 2.0, контекст 8192 токенов, dim=1024)
  - Метрика: cosine via `hnsw:space: cosine`
  - @tool `platform_doc_search(query)` в sdk_tools.py
  - OpRow «Семантический поиск платформы» в правой панели
  - Операция `rebuild-platform-docs-semantic` в ops_runner.py
  - Auto-detection device (cuda/mps/cpu) для GPU-ускорения (ADR-007)
  - File-lock против параллельных индексаций (ADR-008)
  - Per-batch логирование + per-doc fallback при ошибках
- **2026-05-15**: GPU-ускорение опционально через CUDA-torch
  - `scripts/install-cuda-torch.ps1` — установка `torch+cuXXX` с авто-детекцией CUDA driver
  - `scripts/check_chroma_progress.py` — безопасный мониторинг индексации
  - В сообщения ops_runner добавлена информация об устройстве (GPU/CPU)
- **2026-05-15**: Полная документация проекта
  - `docs/README.md` — главный индекс
  - `docs/ARCHITECTURE.md` — архитектура компонентов и потоки данных
  - `docs/DECISIONS.md` — 9 ADR с обоснованиями
  - `docs/PROGRESS.md` — статус всех фаз и задач
  - `docs/CHANGELOG.md` — этот файл
  - `docs/PRO-EDITION-PLAN.md` — план Фаз 1-5
- **2026-05-15**: Защита meta_edit от форматных ошибок LLM (3 слоя)
  - `_resolve_meta_object_path` — резолв пути (плоский XML / папка с XML)
  - `_normalize_meta_edit_value` — нормализатор DSL: русские типы → английские, `Имя Тип` → `Имя:Тип`, `Type=` → `:`
  - `_validate_meta_name` — серверная валидация имени NCName (буквы лат/кир + цифры + `_`)
  - `_extract_names_from_value` — извлекает имена из batch/add-ts
  - Расширенный docstring tool с примерами правильного DSL
  - Покрытие: 23/23 нормализация, 15/15 валидация, 10/10 извлечение, 7/7 path resolver
- **2026-05-15**: Layout UI — метаданные в левую панель
  - Sidebar: «Мои базы» / «Метаданные конфигурации» (flex: 1) / «История задач» / Пользователь
  - RightPanel: «Локальный агент» / «Состояние базы» / «Последние изменения»
  - Убрана секция «Быстрые команды» с плейсхолдерами
  - Иконка-кнопка отправки/стопа со CSS-спиннером
  - Числовые формы русского языка (`pluralRu` функция)
  - Растяжимый скролл дерева метаданных (`flex: 1, minHeight: 0`)
- **2026-05-15**: 44 типа метаданных — правильные plural-формы
  - Заменён алгоритм `_pluralize_ru` на словарь `_DISPLAY_NAME_PLURAL`
  - 44 типа с явными формами: Справочники, Документы, Регистры сведений, Бизнес-процессы и т.д.
  - Поправлен `type_dir` для нестандартных латинских plural (BusinessProcesses, FilterCriteria)
  - Добавлен тип `Language`
- **2026-05-15**: BSL Atlas авто-старт + защита от port-conflict
  - Порт перенесён с 8000 на 8765 (избежание конфликта с torgovыми ботами)
  - `BslAtlasPortConflictError` — стоп при занятом порту с native dialog
  - `_identify_port_holder` — PID + имя процесса через netstat+tasklist
  - `_looks_like_bsl_atlas` — детекция настоящего BSL Atlas via /health
- **2026-05-14/15**: Phase 0 — Интеграция MetadataViewer1C
  - Скопированы 27 JSON-схем XDTO в `data/xsd/`
  - Скопированы 98 SVG-иконок объектов 1С в `frontend/assets/icons/{dark,light}/`
  - Скопированы 8 XSLT-шаблонов в `frontend/assets/xslt/`
  - Портированы 8 Python-модулей в `app/metadata_utils/`
  - 442 справочных значения свойств в `data/field_values.json`
  - 4 FastAPI-эндпоинта для дерева метаданных + SSE-стрим
  - React-компонент MetadataTree.jsx с прогрессивной загрузкой и иконками
  - Правило R20 в `cfe_validate_xml.py` (структура XML по XDTO)
  - Операция `validate-xdto` в ops_runner.py
- **2026-05-14**: UI — реальные stats операций в правой панели
  - `_derive_op_state` синтезирует state из файлов на диске
  - OpRow.subtitleWithStats показывает конкретные числа (XML, объекты, размер)
  - Сохранение между перезапусками через op_state.json

### Fixed
- **2026-05-15**: Двойной запуск индексации → коллизия → ChromaDB NotFoundError
  - File-lock в `build_chroma_index`
- **2026-05-15**: meta_edit падал с «Объект не найден» когда cfe_borrow создал плоский XML
  - `_resolve_meta_object_path` пробует 3 варианта раскладки
- **2026-05-15**: meta_edit принимал `Город Строка(50)` как имя реквизита (имя с пробелом и скобками)
  - 3-слойная защита: нормализатор + валидатор + расширенный docstring
- **2026-05-15**: Сообщение «Первый запуск — скачивание модели 1.37 ГБ» показывалось всегда
  - Проверка размера локального кэша моделей

### Deprecated
- **2026-05-15**: `docs/MCP-SERVERS.md` (Docker MCP-сервера comol/*) — заменяется на встроенные собственные реализации в PRO-edition Фазы 1-3
- **2026-05-15**: `scripts/start-mcp-servers.ps1` — не нужен после Фазы 1

### Removed
— (ничего пока не удаляли)
