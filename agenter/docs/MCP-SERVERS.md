# Внешние MCP-серверы Agenter

Помимо встроенного [BSL Atlas](../../tools/bsl-atlas), Agenter умеет подключаться
к дополнительным MCP-серверам по HTTP. Три полезных сервера от Дмитрия Иванова
(`comol` на DockerHub) разворачиваются в Docker и расширяют возможности агента
на read-стороне (поиск, справка, валидация). Write-инструменты (`db_load`,
`meta_edit`, `cfe_borrow`, ...) остаются в Python-обёртке Agenter.

## Доступные серверы

| Сервер | Image | Порт | Что даёт |
|---|---|---|---|
| **syntax-check** | `comol/1c_syntaxcheck_mcp` | 8002 | BSL Language Server — мгновенный линтер кода перед `db_load` |
| **help-platform** | `comol/1c_help_mcp` | 8003 | RAG-поиск по справке платформы 1С (shcntx) вашей версии |
| **ssl-search** | `comol/mcp_ssl_server` | 8008 | Справка по БСП (Библиотека Стандартных Подсистем) |

Все по транспорту HTTP `/mcp`. Лицензионные ключи зашиты в `start-mcp-servers.ps1`
(взяты из `C:\BUFFER\ERP\mcp-servers\*.txt`).

## Установка

### 1. Docker Desktop

Нужен Docker Desktop + WSL2. Скачать: <https://www.docker.com/products/docker-desktop/>.
После установки — открыть Docker Desktop, дождаться зелёного «Engine running».

### 2. Запустить контейнеры

```powershell
cd C:\BUFFER\ERP\agenter\scripts

# Начни с легковесного — sanity check
.\start-mcp-servers.ps1 -Syntax

# Или сразу все три (Help и SSL индексируются часы при первом запуске!)
.\start-mcp-servers.ps1 -All

# Проверь состояние
.\start-mcp-servers.ps1 -Status
```

`Help` и `SSL` при первом старте качают ~10 GB модели + индексируют данные
несколько часов. Видеть прогресс: `docker logs -f agenter-1c-help`.

### 3. Включить в Agenter

В `config\config.json` найди массив `mcp_servers` и поставь `"enabled": true`
у нужных серверов:

```json
{
  "name": "syntax-check",
  "transport": "http",
  "url": "http://localhost:8002",
  "enabled": true,
  "description": "BSL Language Server — линтер кода"
}
```

### 4. Перезапустить Agenter backend

```powershell
# В терминале где запущен agenter — Ctrl+C, потом:
cd C:\BUFFER\ERP\agenter\app
..\backend\.venv\Scripts\python.exe main.py
```

При старте в логе должна быть строка:
```
MCP registry started: ['bsl-atlas', 'syntax-check', 'help-platform', 'ssl-search']
```

## Что попробовать в чате

После подключения сервера агент видит его tools через MCP-handshake и сам
выбирает их по контексту. Примеры запросов:

**syntax-check:**
```
Проверь синтаксис BSL-кода в модуле Catalog.Контрагенты.ObjectModule
```

**help-platform:**
```
Найди в справке 1С что такое БлокировкаДанных и как её использовать
Какие параметры у метода НайтиПоНаименованию()?
```

**ssl-search:**
```
Найди в справке БСП метод для получения текущего пользователя
Как работает ОбщегоНазначения.СсылкаСуществует?
```

## Остановка / удаление

```powershell
.\start-mcp-servers.ps1 -Stop
```

Контейнеры останавливаются и удаляются. ChromaDB-кэш остаётся в
`agenter\data\mcp\*-chroma\` — следующий запуск переиспользует индексы.

Для полного сброса:
```powershell
.\start-mcp-servers.ps1 -Stop
Remove-Item -Recurse -Force C:\BUFFER\ERP\agenter\data\mcp
```

## Graceful degradation

Если контейнер не запущен или упал, Agenter продолжает работать без этого
сервера — `health_check` помечает его `unhealthy`, агент видит только tools
остальных серверов. Никаких ошибок в основном flow.

Это значит **безопасно держать `enabled: true` для всех серверов** — даже если
контейнер сейчас остановлен, ничего не сломается.

## Troubleshooting

**`Не удалось соединиться` при первом обращении агента:**
- Проверь `docker ps` — контейнер должен быть running
- Help/SSL могут ещё индексироваться: `docker logs -f agenter-1c-help` —
  смотри прогресс. До завершения индексации они не отвечают на /mcp.

**`mcp-session-id отсутствует`:**
- Сервер не успел инициализироваться. Подожди 30 сек и повтори.

**`Lic key invalid`:**
- Ключ в скрипте устарел или версия серверов сменилась.
  Открой `C:\BUFFER\ERP\mcp-servers\*.txt` — там актуальные ключи.

**Хочу сменить порт:**
- Поправь и в `start-mcp-servers.ps1` (переменная `Port` в `$CONTAINERS`),
  и в `config.json` (`url` соответствующей записи). Перезапусти оба.
