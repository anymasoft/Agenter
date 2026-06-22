# start-mcp-servers.ps1 — idempotent-запуск дополнительных MCP-серверов
# для Agenter. Серверы от Дмитрия Иванова (comol на DockerHub).
#
# Использование:
#   .\start-mcp-servers.ps1 -All                     # запустить все
#   .\start-mcp-servers.ps1 -Syntax                  # только BSL-линтер
#   .\start-mcp-servers.ps1 -Help                    # только справка платформы
#   .\start-mcp-servers.ps1 -SSL                     # только справка БСП
#   .\start-mcp-servers.ps1 -Stop                    # остановить и удалить все
#   .\start-mcp-servers.ps1 -Status                  # текущее состояние
#
# Опционально для Help-сервера: укажи путь к платформе 1С через -V8Bin
#   .\start-mcp-servers.ps1 -Help -V8Bin "C:/Program Files/1cv8/8.3.27.1859/bin"
#
# Опционально для SSL-сервера: укажи версию БСП через -SslVersion
#   .\start-mcp-servers.ps1 -SSL -SslVersion 3.1.11

param(
    [switch]$All,
    [switch]$Syntax,
    [switch]$Help,
    [switch]$SSL,
    [switch]$Stop,
    [switch]$Status,
    [string]$V8Bin = "C:/Program Files/1cv8/8.3.27.1859/bin",
    [string]$SslVersion = "3.1.11",
    [string]$DataDir = "C:/BUFFER/ERP/agenter/data/mcp"
)

$ErrorActionPreference = "Stop"

# Лицензионные ключи зашиты автором (из инструкций в D:\CURSORIC\agenter\mcp-servers\)
$SYNTAX_KEY = "a3c617a9-11c2-4e92-8854-3e911c750176"
$HELP_KEY   = "fad9f22d-6242-4543-b311-e1973e46cb6b"
$SSL_KEY    = "fad9f22d-6242-4543-b311-e1973e46cb6b"

# Соответствие: container-name → (image, port, build-args-callback)
$CONTAINERS = @{
    "agenter-1c-syntax" = @{
        Image = "comol/1c_syntaxcheck_mcp:latest"
        Port  = 8002
        Build = { @("-e", "LICENSE_KEY=$SYNTAX_KEY") }
    }
    "agenter-1c-help"   = @{
        Image = "comol/1c_help_mcp:latest"
        Port  = 8003
        Build = {
            $cacheDir = "$DataDir/help-chroma"
            New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
            @(
                "-e", "LICENSE_KEY=$HELP_KEY",
                "-e", "1C_BIN_PATH=/1c_docs",
                "-e", "RESET_CACHE=false",
                "-e", "RESET_DATABASE=false",
                "-v", "${V8Bin}:/1c_docs",
                "-v", "${cacheDir}:/app/chroma_db"
            )
        }
    }
    "agenter-1c-ssl"    = @{
        Image = "comol/mcp_ssl_server:latest"
        Port  = 8008
        Build = {
            $cacheDir = "$DataDir/ssl-chroma"
            New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
            @(
                "-e", "LICENSE_KEY=$SSL_KEY",
                "-e", "SSL_VERSION=$SslVersion",
                "-e", "RESET_CACHE=false",
                "-e", "RESET_DATABASE=false",
                "-v", "${cacheDir}:/app/chroma_db"
            )
        }
    }
}

# ── Утилиты ───────────────────────────────────────────────────────────────

function Test-DockerAvailable {
    try {
        $null = docker info 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Get-ContainerStatus([string]$name) {
    # running | exists (stopped) | absent
    $running = docker ps --filter "name=$name" --format "{{.Names}}" 2>$null
    if ($running -eq $name) { return "running" }
    $any = docker ps -a --filter "name=$name" --format "{{.Names}}" 2>$null
    if ($any -eq $name) { return "exists" }
    return "absent"
}

function Start-Container([string]$name) {
    $cfg = $CONTAINERS[$name]
    if (-not $cfg) { Write-Warning "Unknown container: $name"; return }

    $status = Get-ContainerStatus $name
    Write-Host "[$name] status=$status port=$($cfg.Port) image=$($cfg.Image)" -ForegroundColor Cyan

    if ($status -eq "running") {
        Write-Host "  Уже запущен — пропускаю" -ForegroundColor Green
        return
    }
    if ($status -eq "exists") {
        Write-Host "  Контейнер существует, запускаю..." -ForegroundColor Yellow
        docker start $name | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "  OK" -ForegroundColor Green }
        else { Write-Warning "  Не удалось запустить — пересоздаю" ; docker rm -f $name 2>$null | Out-Null ; $status = "absent" }
    }
    if ($status -eq "absent") {
        Write-Host "  Создаю и запускаю..." -ForegroundColor Yellow
        $args = @(
            "run", "-d",
            "--name", $name,
            "-p", "$($cfg.Port):$($cfg.Port)"
        )
        $args += & $cfg.Build
        $args += $cfg.Image
        docker @args | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  OK — http://localhost:$($cfg.Port)/mcp" -ForegroundColor Green
        } else {
            Write-Error "  Ошибка docker run (exit=$LASTEXITCODE). Проверь Docker Desktop и интернет."
        }
    }
}

function Stop-Container([string]$name) {
    $status = Get-ContainerStatus $name
    if ($status -eq "absent") {
        Write-Host "[$name] не существует — пропускаю" -ForegroundColor DarkGray
        return
    }
    Write-Host "[$name] останавливаю..." -ForegroundColor Yellow
    docker stop $name 2>$null | Out-Null
    docker rm -f $name 2>$null | Out-Null
    Write-Host "  OK" -ForegroundColor Green
}

# ── Точка входа ───────────────────────────────────────────────────────────

if (-not (Test-DockerAvailable)) {
    Write-Error @"
Docker недоступен. Установи Docker Desktop:
  https://www.docker.com/products/docker-desktop/
И WSL2 (Windows). После установки — открой Docker Desktop, дождись зелёного
индикатора 'Engine running', и повтори команду.
"@
    exit 1
}

# Состояние
if ($Status) {
    Write-Host "`n=== MCP-серверы Agenter — состояние ===" -ForegroundColor Cyan
    foreach ($name in $CONTAINERS.Keys | Sort-Object) {
        $cfg = $CONTAINERS[$name]
        $st = Get-ContainerStatus $name
        $color = if ($st -eq "running") { "Green" } elseif ($st -eq "exists") { "Yellow" } else { "DarkGray" }
        Write-Host ("  {0,-22} {1,-9} port={2}  {3}" -f $name, $st, $cfg.Port, $cfg.Image) -ForegroundColor $color
    }
    Write-Host "`nДля включения серверов: .\start-mcp-servers.ps1 -All`n"
    exit 0
}

# Остановка
if ($Stop) {
    foreach ($name in $CONTAINERS.Keys) { Stop-Container $name }
    exit 0
}

# Запуск
$ranAny = $false
if ($All -or $Syntax) { Start-Container "agenter-1c-syntax" ; $ranAny = $true }
if ($All -or $Help)   { Start-Container "agenter-1c-help"   ; $ranAny = $true }
if ($All -or $SSL)    { Start-Container "agenter-1c-ssl"    ; $ranAny = $true }

if (-not $ranAny) {
    Write-Host @"

Что запустить? Используй один из флагов:
  -All        — все три сервера (Syntax + Help + SSL)
  -Syntax     — только BSL-линтер (порт 8002, лёгкий)
  -Help       — только справка платформы 1С (порт 8003, ~10 GB, ~часы индексации)
  -SSL        — только справка БСП (порт 8008, ~часы индексации)
  -Status     — текущее состояние контейнеров
  -Stop       — остановить и удалить все

После запуска — НЕ ЗАБУДЬ в config.json у соответствующих серверов
поставить "enabled": true, чтобы Agenter их подхватил.
"@ -ForegroundColor Yellow
    exit 0
}

Write-Host @"

Готово. Следующие шаги:
1) Открой config.json: D:\CURSORIC\agenter\agenter\config\config.json
   У запущенных серверов поставь "enabled": true
2) Перезапусти Agenter (Python-бэкенд)
3) В чате попробуй: 'Проверь синтаксис BSL-кода функции X' (Syntax)
   или 'Найди в справке 1С что такое БлокировкаДанных' (Help)

Логи контейнеров:  docker logs <container-name>
Остановка всех:    .\start-mcp-servers.ps1 -Stop

"@ -ForegroundColor Cyan
