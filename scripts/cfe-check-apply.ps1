# cfe-check-apply v1.0 — Apply-time шлюз расширения 1С [PATCH agenter]
# Проверяет, ПРИМЕНЯЕТСЯ ли расширение платформой (компиляция/контроль модулей).
# Ловит apply-time ошибки, которые db_load (загрузка исходников) НЕ проверяет:
# в частности &ИзменениеИКонтроль «Текст модуля для метода … изменился».
# Команда платформы: DESIGNER /CheckCanApplyConfigurationExtensions
# (подтверждена эмпирически: на сломанном модуле exit=1 + текст ошибки,
#  на корректном exit=0 + пустой лог). См. _inventory/method-interceptor-error-report.md.
[CmdletBinding()]
param(
    [string]$V8Path,
    [string]$InfoBasePath,
    [string]$InfoBaseServer,
    [string]$InfoBaseRef,
    [string]$UserName,
    [string]$Password,
    [string]$Extension
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Resolve V8 ---
if ($V8Path -and (Test-Path $V8Path -PathType Container)) {
    $V8Path = Join-Path $V8Path "1cv8.exe"
}
if (-not $V8Path -or -not (Test-Path $V8Path)) {
    Write-Host "Error: 1cv8.exe not found at '$V8Path'" -ForegroundColor Red
    exit 2
}
if (-not $InfoBasePath -and (-not $InfoBaseServer -or -not $InfoBaseRef)) {
    Write-Host "Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef" -ForegroundColor Red
    exit 2
}

$tempDir = Join-Path $env:TEMP "cfe_check_apply_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
try {
    $outFile = Join-Path $tempDir "apply_log.txt"

    $arguments = @("DESIGNER")
    if ($InfoBaseServer -and $InfoBaseRef) {
        $arguments += "/S", "`"$InfoBaseServer/$InfoBaseRef`""
    } else {
        $arguments += "/F", "`"$InfoBasePath`""
    }
    if ($UserName) { $arguments += "/N`"$UserName`"" }
    if ($Password) { $arguments += "/P`"$Password`"" }

    $arguments += "/CheckCanApplyConfigurationExtensions"
    if ($Extension) { $arguments += "-Extension", "`"$Extension`"" }
    $arguments += "/Out", "`"$outFile`"", "/DisableStartupDialogs"

    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru
    $exitCode = $process.ExitCode

    $log = ""
    if (Test-Path $outFile) {
        $log = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    }
    if ($log) { $log = $log.TrimStart([char]0xFEFF).Trim() }

    if ($exitCode -eq 0 -and -not $log) {
        Write-Host "apply-check OK: расширение применяется без ошибок"
        exit 0
    }

    Write-Host "APPLY-ERROR: расширение НЕ применяется платформой." -ForegroundColor Red
    Write-Host "Исходники загружены (db_load), но применение модуля отвергнуто — это НЕ «Применено в БД»."
    if ($log) {
        Write-Host "--- Платформа ---"
        Write-Host $log
        Write-Host "--- End ---"
    }
    if ($exitCode -eq 0) { $exitCode = 1 }
    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
