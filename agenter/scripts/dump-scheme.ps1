<#
.SYNOPSIS
    Выгружает конфигурацию 1С в XML-файлы (аналог SCHEME/).
    Используется для построения индекса BSL Atlas.

.PARAMETER V8Path
    Папка бинарников платформы 1С, напр. C:\Program Files\1cv8\8.3.27.1859\bin

.PARAMETER InfoBasePath
    Путь к файловой базе (C:\...\База) или строка сервера (Srvr=host:port;Ref=name)

.PARAMETER UserName
    Логин пользователя 1С

.PARAMETER Password
    Пароль пользователя 1С

.PARAMETER SchemeDir
    Куда сохранить XML (будет создана если не существует)

.EXAMPLE
    .\dump-scheme.ps1 -V8Path "C:\Program Files\1cv8\8.3.27.1859\bin" `
        -InfoBasePath "C:\Users\User\Documents\1C\ERP" `
        -UserName "Администратор" -Password "" `
        -SchemeDir "C:\AgenterData\scheme"
#>
param(
    [Parameter(Mandatory=$true)][string]$V8Path,
    [Parameter(Mandatory=$true)][string]$InfoBasePath,
    [string]$UserName = "",
    [string]$Password = "",
    [Parameter(Mandatory=$true)][string]$SchemeDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Проверка 1cv8.exe
$1cv8 = Join-Path $V8Path "1cv8.exe"
if (-not (Test-Path $1cv8)) {
    Write-Error "1cv8.exe не найден: $1cv8"
    exit 1
}

# Создать выходную папку
New-Item -ItemType Directory -Force -Path $SchemeDir | Out-Null

# Строка подключения к базе
# Файловая база: /F"путь"
# Серверная: /S"host\basename" или /S"Srvr=...;Ref=...;"
if ($InfoBasePath -match '^Srvr\s*=' -or $InfoBasePath -match '^File\s*=') {
    # Уже в формате строки подключения — передаём как есть через /IBConnectionString
    $ConnArg = "/IBConnectionString`"$InfoBasePath`""
} elseif ($InfoBasePath -match '\\\\' -or ($InfoBasePath -match '^[a-zA-Z]:' -and (Test-Path $InfoBasePath))) {
    # Файловая база — локальный путь
    $ConnArg = "/F`"$InfoBasePath`""
} else {
    # Серверная база в формате server\basename
    $ConnArg = "/S`"$InfoBasePath`""
}

# Временный лог-файл для перехвата вывода 1С
$LogFile = [System.IO.Path]::Combine($env:TEMP, "agenter_scheme_$(Get-Random).log")

Write-Host "[dump-scheme] Платформа : $1cv8"
Write-Host "[dump-scheme] База      : $InfoBasePath"
Write-Host "[dump-scheme] Выход     : $SchemeDir"
Write-Host "[dump-scheme] Запуск 1cv8.exe DESIGNER /DumpConfigToFiles..."

# Аргументы командной строки
$Args = @(
    "DESIGNER",
    $ConnArg
)
if ($UserName) { $Args += "/N`"$UserName`"" }
if ($Password) { $Args += "/P`"$Password`"" }
$Args += "/DumpConfigToFiles"
$Args += "`"$SchemeDir`""
$Args += "/DisableStartupDialogs"
$Args += "/Out"
$Args += "`"$LogFile`""

Write-Host "[dump-scheme] Командная строка: 1cv8.exe $($Args -join ' ')"
Write-Host "[dump-scheme] Это может занять 20-40 минут для большой базы..."

$Proc = Start-Process -FilePath $1cv8 `
    -ArgumentList $Args `
    -Wait `
    -PassThru `
    -WindowStyle Hidden

# Вывести лог если есть
if (Test-Path $LogFile) {
    $LogContent = Get-Content $LogFile -Encoding UTF8 -Raw
    if ($LogContent) {
        Write-Host "[dump-scheme] Лог 1С:"
        Write-Host $LogContent
    }
    Remove-Item $LogFile -Force -ErrorAction SilentlyContinue
}

if ($Proc.ExitCode -ne 0) {
    Write-Error "[dump-scheme] 1cv8.exe завершился с кодом $($Proc.ExitCode). Проверьте лог выше."
    exit $Proc.ExitCode
}

# Считаем файлы
$FileCount = (Get-ChildItem -Path $SchemeDir -Recurse -File -ErrorAction SilentlyContinue).Count
Write-Host ("[dump-scheme] OK: выгружено {0} файлов -> {1}" -f $FileCount, $SchemeDir)
exit 0
