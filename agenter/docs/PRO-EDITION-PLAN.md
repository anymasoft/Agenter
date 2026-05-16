# Agenter PRO — план реализации без Docker

## 0. Цель и контекст

**Цель:** свой собственный мощный сервис для 1С-разработки на базе Claude Code.
Все компоненты — встроены в Agenter, упаковываются в один инсталлятор.

**Что НЕ хотим:**
- Docker Desktop как зависимость (избыточно, лицензия, 3 GB на диске)
- Чужие лицензионные ключи в инсталляторе (риск отзыва)
- 5 терминалов / 3 контейнера на запуск
- Конфигурация в 4 местах одновременно

**Что хотим:**
- Один `Agenter-Setup.exe` → мастер установки → готово к работе
- Все возможности comol/* серверов (Syntax, Help, SSL, Templates, Forms)
- Полный контроль над компонентами (open-source, наша обёртка)

---

## 1. Архитектура целевого решения

### Структура каталогов после реализации

```
agenter/
├── app/                       # Backend Python (FastAPI + SDK)
│   ├── main.py
│   ├── orchestrator_sdk.py
│   ├── sdk_tools.py
│   ├── platform_docs.py       # РАСШИРИТЬ: + ChromaDB + БСП источник
│   ├── platform_docs_chroma.py  # НОВЫЙ: semantic-индекс
│   ├── ssl_docs.py            # НОВЫЙ: индексатор БСП
│   ├── templates_index.py     # НОВЫЙ: индексатор шаблонов кода
│   └── metadata_utils/        # уже сделано
├── desktop/
│   └── main.py                # ToolExecutor — добавить _bsl_lint
├── frontend/                  # как сейчас
├── scripts/
│   ├── db-dump-xml.ps1        # как сейчас
│   ├── db-load-xml.ps1        # как сейчас
│   ├── bsl-lint/              # НОВЫЙ скилл-пакет
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── bsl-lint.ps1
│   ├── meta-edit/             # как сейчас
│   ├── meta-compile/          # как сейчас
│   ├── cfe-borrow/            # как сейчас
│   ├── cfe-validate/          # как сейчас
│   ├── cfe-patch-method/      # как сейчас
│   └── start-mcp-servers.ps1  # удалить — Docker не нужен
├── tools/                     # НОВАЯ папка — встроенные бинари
│   ├── bsl-ls/
│   │   ├── bsl-language-server.jar     # ~50 MB
│   │   ├── jre/                        # ~150 MB portable JRE
│   │   └── version.txt                 # для апдейтов
│   └── platform-docs-models/
│       └── multilingual-e5-small/      # ~440 MB модель embedding
├── data/                      # пользовательские данные (создаются при первом запуске)
│   ├── platform_docs.db       # SQLite (есть)
│   ├── platform_docs_chroma/  # ChromaDB
│   ├── ssl_docs.db
│   ├── ssl_docs_chroma/
│   └── templates_chroma/
├── config/                    # как сейчас
├── docs/
│   ├── MCP-SERVERS.md         # удалить или пометить deprecated
│   └── PRO-EDITION-PLAN.md    # этот файл
├── installer/                 # НОВАЯ папка — материалы для сборки exe
│   ├── pyinstaller.spec
│   ├── inno-setup.iss         # Inno Setup script
│   └── post-install.ps1       # настройка после распаковки
└── README.md
```

### Поток данных

```
                      ┌──────────────────────────────┐
                      │  Agenter UI (PyWebView)      │
                      └──────────────┬───────────────┘
                                     │ http://localhost:8080
                      ┌──────────────▼───────────────┐
                      │  FastAPI backend (main.py)   │
                      └──────────────┬───────────────┘
                                     │ Claude Agent SDK
                      ┌──────────────▼───────────────┐
                      │  Orchestrator (LLM loop)     │
                      └─┬──┬──┬──┬──┬──┬──┬──┬──┬───┘
                        │  │  │  │  │  │  │  │  │
   ┌────────────────────┘  │  │  │  │  │  │  │  └──────────────────────┐
   │     ┌─────────────────┘  │  │  │  │  │  └─────────────────┐      │
   ▼     ▼                    │  │  │  │  └────────┐           ▼      ▼
 db_dump db_load              │  │  │  │           ▼         ssl    templates
 meta_edit cfe_borrow         │  │  │  │       bsl_lint    _lookup  _search
 (PowerShell скиллы)          │  │  │  │       (Java JAR)  (SQLite) (Chroma)
                              ▼  ▼  ▼  ▼
                         BSL Atlas / platform_doc_lookup
                         (структура / справка платформы)
```

---

## 2. Зависимости

### Open-source компоненты которые встраиваем

| Компонент | Версия | Лицензия | Размер | Источник |
|---|---|---|---|---|
| BSL Language Server | 0.24.x+ | Apache 2.0 | ~50 MB JAR | github.com/1c-syntax/bsl-language-server/releases |
| Eclipse Temurin JRE | 21 LTS | GPLv2 w/CE | ~150 MB | adoptium.net/temurin/releases |
| sentence-transformers | 3.x | Apache 2.0 | ~100 MB | pip |
| chromadb | 0.5.x | Apache 2.0 | ~30 MB | pip |
| onec_dtools | 0.5+ | MIT | <1 MB | pip (есть) |
| multilingual-e5-small | — | MIT | ~440 MB | huggingface.co/intfloat |
| PyInstaller | 6.x | GPL with exception | сборочный | pip |
| Inno Setup | 6.x | свободная | сборочный | jrsoftware.org |

**Все open-source. Лицензионных рисков нет.**

### Python-пакеты которые добавим в `requirements.txt`

```
sentence-transformers>=3.0,<4.0
chromadb>=0.5,<0.6
huggingface-hub>=0.24
# уже есть: onec_dtools, aiohttp, fastapi, claude-agent-sdk, lxml, pydantic, ...
```

### Внешние ресурсы которые нужны от пользователя (один раз при установке)

- `shcntx_ru.hbk` — справка платформы (в установке 1С: `<v8_path>\shcntx_ru.hbk`)
- `*.hbk` БСП — справка БСП (нужно найти в установке ERP, см. Фазу 3 секцию «Открытые вопросы»)
- Доступ к интернету для скачивания модели multilingual-e5-small (один раз)

---

## 3. Фаза 1 — BSL Language Server как наш скилл

### Цель
Встроить open-source BSL Language Server (Java JAR) в Agenter как ещё один PowerShell-скилл. Линт BSL-кода до db_load.

### Что делаем

#### 3.1 Скачивание и встраивание JAR
- Скачать релиз `bsl-language-server-X.Y.Z-exec.jar` (~50 MB) из GitHub releases
- Скачать portable JRE 21 (Eclipse Temurin) под Windows x64 (~150 MB)
- Распаковать в:
  ```
  agenter/tools/bsl-ls/
    bsl-language-server.jar
    jre/                 ← portable JRE без установки
    version.txt          ← "0.24.2 / JRE 21.0.5"
  ```

#### 3.2 Создание скилла bsl-lint
Файл: `agenter/scripts/bsl-lint/scripts/bsl-lint.ps1`

```powershell
# Параметры:
#   -SourcePath <путь>  — файл .bsl или папка
#   -ConfigPath <путь>  — bsl-language-server.json (опционально)
#   -Mode "report"|"fix"  — только проверка или авто-фикс

# Логика:
#   1. Найти JAR: ../../tools/bsl-ls/bsl-language-server.jar
#   2. Найти JRE: ../../tools/bsl-ls/jre/bin/java.exe
#   3. Запустить:
#      jre\bin\java.exe -jar bsl-language-server.jar `
#        --analyze --srcDir <path> --reporter json
#   4. Сохранить вывод JSON во временный файл, прочитать, привести к
#      компактному формату {file, line, severity, message, ruleId}
#   5. Вернуть итог в stdout
```

#### 3.3 Скилл-манифест
Файл: `agenter/scripts/bsl-lint/SKILL.md`
- Описание: «Линтер BSL-кода через BSL Language Server»
- Примеры использования
- Список правил (можно ссылку на BSL LS docs)

#### 3.4 Python-обёртка
В `agenter/desktop/main.py` метод `_bsl_lint(source_path)`:
- Резолв пути (как `_resolve_meta_object_path`)
- Вызов скилла через `run_powershell`
- Возврат JSON-строки

#### 3.5 SDK @tool
В `agenter/app/sdk_tools.py` новый @tool `bsl_lint`:
```python
@tool(
    "bsl_lint",
    "Проверить синтаксис BSL-кода через BSL Language Server. "
    "Запускай ПЕРЕД db_load после правки .bsl файлов. "
    "Возвращает массив проблем {file, line, severity (error/warn/info), "
    "message, ruleId}. Если массив пуст — код чистый.",
    {
        "type": "object",
        "properties": {
            "source_path": {
                "type": "string",
                "description": "Путь к .bsl файлу или папке (относительно ext_src/)"
            }
        },
        "required": ["source_path"]
    }
)
async def bsl_lint(args: dict) -> dict:
    return await _safe_call(executor._bsl_lint, args["source_path"])
```

Добавить `mcp__agenter__bsl_lint` в `AGENTER_TOOL_NAMES`.

#### 3.6 Подсказка в system prompt
В `_build_client_context` добавить пункт:
```
Перед db_load обязательно вызывай bsl_lint на изменённых .bsl файлах.
Если bsl_lint вернул errors — исправь и повтори. Не вызывай db_load
если есть errors — это сэкономит итерации и не положит кривое в БД.
```

### Файлы для изменения
- `agenter/desktop/main.py` — +метод `_bsl_lint` (+30 строк)
- `agenter/app/sdk_tools.py` — +@tool `bsl_lint` (+30 строк)
- `agenter/scripts/bsl-lint/SKILL.md` — новый (~100 строк)
- `agenter/scripts/bsl-lint/scripts/bsl-lint.ps1` — новый (~80 строк)
- `agenter/tools/bsl-ls/` — новая папка с JAR + JRE (~200 MB, не в git)

### Smoke-критерии завершения
- [ ] `.\bsl-lint.ps1 -SourcePath "C:\BUFFER\ERP\ext_src\Catalogs\Банки\Ext\ManagerModule.bsl"` возвращает JSON
- [ ] `_bsl_lint()` корректно вызывается из ToolExecutor
- [ ] LLM-агент видит `mcp__agenter__bsl_lint` в tools list
- [ ] Намеренная ошибка в .bsl (например `Если Это` без `Тогда`) ловится линтером
- [ ] Корректный код проходит без warnings

### Сложность / время
**Сложность:** низкая. Это вариация наших существующих скиллов (как db-dump-xml).
**Время:** 1 день (включая скачивание JAR/JRE, написание скилла, тесты, документация).

### Риски
- BSL LS может выдавать слишком много warnings на типовом коде → нужно подобрать конфиг с разумным набором правил
- JRE 21 на Windows 7/8 не пойдёт → задокументировать что нужна Windows 10+

---

## 4. Фаза 2 — ChromaDB поверх platform_docs

### Цель
Добавить semantic-поиск по справке платформы 1С. Сейчас у нас точное FTS5 — он не ловит запросы вида «как заблокировать данные» если в справке написано «использование блокировок».

### Что делаем

#### 4.1 Скачивание модели
- Модель: `intfloat/multilingual-e5-small` (~440 MB) — лучшая для многоязычного semantic-поиска
- Скачать через `huggingface-hub` при первом запуске или вшить в инсталлятор
- Класть в `agenter/tools/platform-docs-models/multilingual-e5-small/`

#### 4.2 Расширение platform_docs.py
Текущий код:
```python
def build_index(hbk_path) -> dict:
    # парсит .hbk, кладёт в SQLite + FTS5
```

Добавить:
```python
def build_index(hbk_path, build_chroma=True) -> dict:
    # 1. как сейчас — SQLite + FTS5
    # 2. дополнительно — ChromaDB-коллекция

def search_semantic(query: str, limit: int = 5) -> list[dict]:
    # ChromaDB.query() с embedding модели
```

#### 4.3 Новый @tool
```python
@tool(
    "platform_doc_search",
    "Семантический поиск по справке платформы 1С. Принимает фразу/вопрос, "
    "возвращает наиболее близкие по смыслу разделы. Используй когда не "
    "знаешь точное имя метода ('как сделать X'). Для точного поиска по "
    "имени используй platform_doc_lookup.",
    {...}
)
```

#### 4.4 Интеграция с UI
- В правой панели Agenter (Состояние базы) — расширить OpRow «Документация платформы»:
  - Сейчас: `25 509 записей · БД 34 МБ`
  - Добавить: `+ ChromaDB 280 МБ` если индекс построен

### Файлы для изменения
- `agenter/app/platform_docs.py` — расширить функциями chromadb (+150 строк)
- `agenter/app/platform_docs_chroma.py` — новый, ChromaDB wrapper (~200 строк)
- `agenter/app/sdk_tools.py` — +@tool `platform_doc_search`
- `agenter/app/main.py` — +stats для UI
- `agenter/app/requirements.txt` — +chromadb, +sentence-transformers
- `agenter/data/platform_docs_chroma/` — auto-create

### Smoke-критерии
- [ ] При первом запуске модель скачивается успешно
- [ ] ChromaDB-индекс построен за разумное время (~5-10 мин на 25k записей)
- [ ] `platform_doc_search("как заблокировать данные")` возвращает релевантные результаты
- [ ] Эстетика: ChromaDB не ломает существующий platform_doc_lookup
- [ ] Размер на диске: ~50 МБ на ChromaDB + 440 МБ модель = ~490 МБ доп.

### Сложность / время
**Сложность:** средняя. Нужно понять как ChromaDB и sentence-transformers работают вместе.
**Время:** 2-3 дня.

### Риски
- Скачивание модели зависит от huggingface.co — если у клиента нет интернета, модель надо вшить в инсталлятор (но это +440 МБ к exe). Решение: предложить два варианта (скачивание / встраивание) в мастере установки.
- Производительность: первая загрузка модели в память ~3-5 сек. Кешировать в процессе.

---

## 5. Фаза 3 — Справка БСП (через BSL-комментарии модулей)

### Цель
Индексировать справку БСП. Сейчас 90% методов в ERP-коде — это БСП (ОбщегоНазначения.*, ПравоДоступа.*, и т.п.), и без неё агент часто пишет код вместо использования готовых функций.

### Источник данных — РЕШЕНО (15.05.2026)

Разведка .hbk файлов в установке пользователя показала: **отдельного .hbk БСП нет**. Документация БСП поставляется через ИТС-подписку (its.1c.ru/db/bspdoc) или встроена в исходники модулей.

**Решение:** парсим стандартизованные комментарии-DocString'ы из исходников БСП.

В `SCHEME/CommonModules/*/Ext/Module.bsl` есть процедуры/функции с шаблонным комментарием:
```bsl
// <Описание процедуры одной строкой>
//
// Параметры:
//   ИмяПараметра - Тип - описание.
//
// Возвращаемое значение:
//   Тип - описание.
//
// Пример:
//   Результат = ОбщегоНазначения.МетодХ(Параметры);
//
Процедура / Функция ИмяМетода(Параметры) Экспорт
```

**Преимущества этого подхода vs .hbk:**
- Актуальная документация именно для версии БСП в конкретной ERP пользователя
- Не требует подписки ИТС
- Покрывает 100% Export-методов БСП (которые видны из расширений)
- Source-of-truth — синхронизировано с реальным кодом

**Что парсим:**
- Имя процедуры/функции + Export-флаг
- Полный путь: `CommonModules/<ModuleName>/<ProcedureName>`
- Краткое описание (первая строка комментария)
- Параметры с типами
- Возвращаемое значение (для функций)
- Пример использования (если есть в комментарии)
- Полное тело комментария (для отображения LLM)

#### 5.2 Расширение индексатора
- В `agenter/app/ssl_docs.py` (новый файл) — повторить логику platform_docs.py, но для БСП
- Источник: `<ERP_install>/External/БСП.hbk` или аналог
- Та же структура: SQLite (FTS5) + ChromaDB

#### 5.3 Новые @tools
```python
@tool("ssl_doc_lookup", "Точный поиск метода БСП по имени", ...)
@tool("ssl_doc_search", "Семантический поиск по справке БСП", ...)
```

#### 5.4 Объединённый поиск
Опционально: `unified_doc_search(query, sources=["platform","ssl"])` — общий поиск по обоим источникам.

### Файлы
- `agenter/app/ssl_docs.py` — новый (~300 строк)
- `agenter/app/sdk_tools.py` — +2 @tools
- `agenter/app/ops_runner.py` — +`rebuild_ssl_docs` (как `rebuild_platform_docs`)
- `agenter/app/main.py` — +OpRow в правой панели

### Smoke-критерии
- [ ] `ssl_doc_lookup("СсылкаСуществует")` находит `ОбщегоНазначения.СсылкаСуществует` с сигнатурой
- [ ] `ssl_doc_search("проверить право пользователя")` находит `ПравоДоступа.*`
- [ ] Размер: ~30 МБ SQLite + ~30 МБ ChromaDB
- [ ] OpRow «Справка БСП» в UI показывает корректную статистику

### Сложность / время
**Сложность:** низкая (если .hbk БСП доступен) — это копия Фазы 2 для другого источника.
**Время:** 1-2 дня + время на разведку.

### Риски
- БСП может быть не в формате .hbk → нужна альтернативная стратегия (парсить из текстовых файлов БСП).
- Версии БСП различны в разных конфигурациях → нужно автодетектить версию.

---

## 6. Фаза 4 — Templates индекс (опционально)

### Цель
Поиск по шаблонам кода 1С с fastcode.im. Также — наши собственные шаблоны под `пгт_`-префикс.

### Что делаем

#### 6.1 Сбор корпуса шаблонов
- Скрейпинг fastcode.im (с уважением robots.txt)
- Или альтернатива: использовать публичные GitHub-репозитории с 1С-шаблонами
- Сохранить в `agenter/data/templates_corpus/` как набор JSON {name, description, code, tags}

#### 6.2 Индексация
- ChromaDB-коллекция templates
- Та же модель multilingual-e5-small

#### 6.3 Свои шаблоны
- Папка `agenter/data/templates_custom/` — пользователь кладёт свои паттерны
- Mar Auto-индекс при изменении папки

#### 6.4 @tool
```python
@tool("template_search", "Поиск кода-шаблонов 1С по описанию задачи", ...)
```

### Сложность / время
**Сложность:** средняя.
**Время:** 2-3 дня.

### Риски
- Скрейпинг fastcode.im может потребовать капчу/авторизацию.
- Качество шаблонов варьируется — нужна модерация.

---

## 7. Фаза 5 — Упаковка в инсталлятор

### Цель
Один `Agenter-Setup.exe` ~600-1000 МБ → запустил → готово.

### Что делаем

#### 7.1 PyInstaller bundle
Файл: `installer/agenter.spec`
- Включить: app/, desktop/, frontend/
- Bundle: chromadb, sentence-transformers, claude-agent-sdk, fastapi, lxml...
- Hidden imports для динамической загрузки моделей
- Резалт: `dist/Agenter/` с `Agenter.exe` ~80 МБ

#### 7.2 Tools папка
Скопировать как есть в `dist/Agenter/tools/`:
- bsl-ls/ (~200 МБ)
- platform-docs-models/multilingual-e5-small/ (~440 МБ)

#### 7.3 Inno Setup
Файл: `installer/agenter.iss`
- Метаданные: имя, версия, иконка, лицензия
- Файлы: всё содержимое dist/Agenter/
- Установка в: `C:\Program Files\Agenter\`
- Создать ярлык на рабочем столе и в меню Пуск
- Файлы пользователя: `%USERPROFILE%\AppData\Local\Agenter\data\`

#### 7.4 Мастер первого запуска
При первом запуске Agenter:
1. Проверить наличие 1С: посмотреть `C:\Program Files\1cv8\*\bin\1cv8.exe`
2. Спросить путь к `shcntx_ru.hbk`
3. Спросить путь к .hbk БСП (или пропустить если не найден)
4. Запустить фоновую индексацию → progress bar
5. Готово → открыть UI

#### 7.5 Авто-обновление (опционально)
- Проверка GitHub releases при старте
- Скачивание дельты (новый Agenter.exe или новый bsl-ls JAR)
- Уведомление пользователю

### Файлы
- `installer/agenter.spec` (PyInstaller)
- `installer/agenter.iss` (Inno Setup)
- `installer/post-install.ps1` (настройки после распаковки)
- `installer/README.md` (документация сборщику)

### Smoke-критерии
- [ ] PyInstaller собрал .exe без warnings про missing modules
- [ ] Inno Setup создал .exe инсталлятора ~600-1000 МБ
- [ ] На чистой VM Windows 10/11 инсталлятор отрабатывает без ошибок
- [ ] Первый запуск проходит мастер настройки
- [ ] Все 4 категории tools (skills, BSL LS, platform docs, SSL docs) работают
- [ ] Удаление через панель управления — чисто

### Сложность / время
**Сложность:** высокая. PyInstaller с ChromaDB/sentence-transformers — известно капризный.
**Время:** 3-5 дней (включая тестирование на чистой VM).

### Риски
- ChromaDB иногда плохо упаковывается через PyInstaller — может потребоваться workaround с DLL-копированием
- Большой размер дистрибутива (~1 GB) — нужен installer с компрессией LZMA/LZMA2
- Антивирусы могут флагнуть unsigned PyInstaller exe → нужно code-signing certificate (опционально)

---

## 8. Финальный размер дистрибутива

| Компонент | Размер |
|---|---|
| Agenter Python код (frozen) | ~80 МБ |
| chromadb + dependencies | ~30 МБ |
| sentence-transformers + torch | ~150 МБ |
| BSL Language Server JAR | ~50 МБ |
| Eclipse Temurin JRE 21 | ~150 МБ |
| multilingual-e5-small модель | ~440 МБ |
| Frontend (JSX/CSS/иконки) | ~5 МБ |
| **Итого распакованный** | **~900 МБ** |
| **После Inno Setup LZMA2** | **~500-600 МБ** |

Для AI-инструмента с собственной semantic-моделью — нормальный размер.

---

## 9. Открытые вопросы (нужно решить до старта)

### Технические
- [ ] **Где взять .hbk БСП?** Нужно проверить установку ERP пользователя. Если нет — альтернативный источник.
- [ ] **Какая версия BSL LS?** Последняя стабильная или закрепить конкретную (для воспроизводимости сборки).
- [ ] **Какая модель embedding?** multilingual-e5-small (440 МБ, баланс) или multilingual-e5-base (1 GB, точнее)?
- [ ] **PyInstaller или Nuitka?** PyInstaller проще, Nuitka даёт меньший размер и быстрее.

### Архитектурные
- [ ] **Online или offline-only?** Если offline-only — вшить модель в инсталлятор (+440 МБ). Online — мастер качает при первом запуске.
- [ ] **Авто-обновление?** Реализовывать GitHub release-checker или ручной апдейт?
- [ ] **Лицензия Agenter?** MIT, Apache 2.0 или закрытый код (для себя)?

### Пользовательские (под себя)
- [ ] Сколько ERP-инсталляций будет на одном ПК (одна-две / много)?
- [ ] Нужны ли разные профили (test/prod ERP)?

---

## 10. Порядок реализации (после ответов на открытые вопросы)

| # | Фаза | Время | Критичность |
|---|---|---|---|
| 1 | BSL LS как скилл | 1 день | ⭐⭐⭐ |
| 2 | Найти и индексировать БСП (Фаза 3) | 2 дня | ⭐⭐⭐ |
| 3 | ChromaDB для platform docs (Фаза 2) | 2-3 дня | ⭐⭐ |
| 4 | Templates индекс (Фаза 4) | 2-3 дня | ⭐ |
| 5 | PyInstaller сборка | 2-3 дня | ⭐⭐ |
| 6 | Inno Setup инсталлятор | 2 дня | ⭐⭐ |
| 7 | Тестирование на чистой VM | 2 дня | ⭐⭐⭐ |
| **Итого** | | **~2 недели активной работы** | |

---

## 10.6 Фаза 6 — Multi-model + multi-provider (среднесрочно)

### Цель
Снизить стоимость API на простых задачах в 3-5×, дать гибкость выбора LLM-провайдера.

### Что делаем

#### 10.6.1 Переключатель модели в config.json
```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6",   // или claude-haiku-4-5 / claude-opus-4
    "fallback_model": null
  }
}
```
В `orchestrator_sdk.py` читать модель из config вместо хардкода `"claude-sonnet-4-6"`.

#### 10.6.2 Multi-model routing
Логика выбора модели по типу задачи:
- **Haiku**: routing-решения (какой tool вызвать), парсинг результатов tool, финальный ответ пользователю
- **Sonnet**: генерация BSL кода, проектирование архитектуры, СКД-схемы
- **Opus**: только если Sonnet провалил с первой попытки и задача очень сложная

Реализация: pre/post-hooks в orchestrator переключают модель между шагами.

#### 10.6.3 OpenRouter как альтернативный провайдер
- Единый API для Anthropic + OpenAI + DeepSeek + Qwen + Local (через Ollama)
- В `config.json` `"provider": "openrouter"` + `"openrouter_key"`
- Цены через OpenRouter обычно с +10% маржей, но даёт гибкость

#### 10.6.4 Provider abstraction layer
`app/llm_providers.py` с интерфейсом:
```python
class LLMProvider(ABC):
    async def query(prompt, tools, history) -> Response
    
class AnthropicProvider(LLMProvider): ...
class OpenAIProvider(LLMProvider): ...
class OpenRouterProvider(LLMProvider): ...
class LocalOllamaProvider(LLMProvider): ...
```

Все tools (наши custom @tool и MCP) одинаково работают на любом провайдере.

### Размер работ
~3-5 дней (тестирование на разных моделях критично).

### Когда делать
Когда первый клиент покупает Agenter ИЛИ когда личный расход на API > $50/мес.

---

## 10.7 Фаза 7 — Бизнес-модель и distribution (долгосрочно)

### Цель
Подготовить Agenter к продаже без операционных затрат на стороне продавца.

### Стратегия "BYOK + лицензия"

**Bring Your Own Key:**
- Клиент сам регистрируется на console.anthropic.com (или OpenRouter)
- Получает API-ключ
- В Agenter вводит ключ в `config.json` → начинает работу
- Платит провайдеру API напрямую за токены
- Мы продаём только сам Agenter

**Преимущества:**
- ✅ Ноль операционных затрат у нас
- ✅ Ноль финансовых рисков (клиент сжёг $200 — это его проблема)
- ✅ Простая инфраструктура (только web-сайт для покупки + автодоставка инсталлятора)
- ✅ Прозрачность: клиент видит свой реальный расход на токены

**Ценовая политика (стартовая):**
- **Личная лицензия** — $300 одноразово (free updates 1 год) ИЛИ $20/мес
- **Корпоративная** (3+ workplace) — $25/мес/место
- **Pro** (с расширенным функционалом — future tier) — $50/мес

### Альтернативные модели (если BYOK не сработает)
- **Pay-per-credit** (модель Replit): клиент покупает пакеты $20/$50/$100, мы посредник
- **Subscription proxy** (модель Cursor v2): $30-40/мес, мы проксируем все API запросы

### Требования для прода
- Code-signing certificate для exe (~$300/год)
- License-server для активации (минималистичный — один Cloudflare Worker)
- Telegram-канал/Discord для поддержки
- Документация на русском
- Лендинг + видеодемо

### Когда делать
После завершения Фаз 1-5 + минимум 20 часов реального использования Agenter (чтобы убедиться в стабильности).

---

## 11. Что НЕ делаем в этом плане

Намеренно вне scope:
- **1С:Напарник AI** (требует партнёрский токен 1С, недоступен)
- **Graph metadata search через Neo4j** (избыточно, BSL Atlas + наш metadata_repository уже покрывают)
- **Forms RAG-генератор** (наш form-compile/form-edit достаточен)
- **Облачная подписка / SaaS-инфраструктура** (это для прод-продаж, не для личного использования)
- **Apple Silicon / Linux сборки** (только Windows x64 пока)

Если в процессе работы окажется что что-то из перечисленного критично — расширим план.

---

## 12. Что в итоге получится

После всех фаз:

```
[Один exe инсталлятор] →
   ├── Agenter (UI + backend + agent loop)
   ├── BSL Atlas (структурный поиск)
   ├── platform_docs (SQLite + ChromaDB) — справка платформы 1С
   ├── ssl_docs (SQLite + ChromaDB) — справка БСП
   ├── bsl-ls (Java JAR + JRE) — линтер BSL
   ├── templates_index (ChromaDB) — шаблоны кода
   └── data/ — пользовательские индексы (создаются при первом запуске)
```

Tools у LLM (полный список):
- File ops: Read, Write, Edit, Glob, Grep, Bash, TodoWrite, Agent
- 1С write: db_dump, db_load, meta_compile, meta_edit, cfe_borrow, cfe_patch_method, cfe_validate
- 1С read: bsl_lint (Java), platform_doc_lookup/search, ssl_doc_lookup/search, template_search
- BSL Atlas: search_function, get_module_functions, get_function_context, metadatasearch, get_object_details, code_grep

**Покрытие задач — максимально возможное.** Что вне этого — реально требует внешних AI-сервисов (типа 1С:Напарника), либо ChromaDB-нагрузка такая, что нужна GPU.

Готовый личный инструмент, без сторонних зависимостей кроме самой 1С платформы.
