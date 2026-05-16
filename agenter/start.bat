@echo off
REM ============================================================================
REM Agenter - desktop app launcher (PyWebView + FastAPI + Claude Agent SDK).
REM
REM Single process: app/main.py starts FastAPI on localhost:8080, opens a native
REM window with the web UI, and runs the Claude Agent SDK loop.
REM
REM All dependencies live in backend/.venv/ (historically the project's single
REM venv). Closing the window terminates the whole app.
REM
REM This file is ASCII-only on purpose: cmd.exe reads .bat in the OEM code page
REM (CP866 on Russian Windows), so any UTF-8 Cyrillic here would be parsed as
REM garbage commands. Keep all comments and echo strings in plain ASCII.
REM ============================================================================

setlocal

set "AGENTER_ROOT=%~dp0"
set "PYTHON=%AGENTER_ROOT%backend\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at backend\.venv\.
    echo.
    echo Install dependencies first:
    echo   cd %AGENTER_ROOT%backend
    echo   python -m venv .venv
    echo   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

cd /d "%AGENTER_ROOT%app"
"%PYTHON%" main.py %*

endlocal
