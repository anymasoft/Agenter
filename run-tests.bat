@echo off
REM Run the Agenter test harness.
REM  1. Refresh tests\audit\COVERAGE.md
REM  2. Run pytest on tests\
REM
REM Pass through extra args to pytest, e.g.:
REM   run-tests.bat -k subsystem_edit -v

setlocal
set "AGENTER_ROOT=%~dp0"
set "PYTHON=%AGENTER_ROOT%backend\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at backend\.venv\.
    echo Run: cd %AGENTER_ROOT%backend ^& python -m venv .venv ^& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

cd /d "%AGENTER_ROOT%"

echo === Skill coverage audit ===
"%PYTHON%" -m tests.audit.skill_audit
echo.
echo === pytest ===
"%PYTHON%" -m pytest tests %*
set "RC=%ERRORLEVEL%"

endlocal & exit /b %RC%
