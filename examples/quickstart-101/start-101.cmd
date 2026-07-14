@echo off
setlocal
REM ===================================================================
REM  101 example launcher -- double-click to run.
REM  Sets THIS folder as HWPXFILLER_HOME, so its templates and text
REM  drafts appear in the app (your real ~/.hwpxfiller is untouched).
REM
REM  First time only, from the repo root, install dependencies:
REM      uv sync --locked --all-extras --group dev --group build
REM  After that, just double-click this file (or run start-101.cmd).
REM ===================================================================

set "HWPXFILLER_HOME=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM repo root = two levels up from this file
pushd "%~dp0..\.."

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv not found on PATH.
    echo         Install uv, then from the repo root run once:
    echo             uv sync --locked --all-extras --group dev --group build
    popd
    pause
    exit /b 1
)

echo Starting app...  HWPXFILLER_HOME=%HWPXFILLER_HOME%
uv run --no-sync --extra gui python -m hwpxfiller.webapp
set "RC=%ERRORLEVEL%"

popd
if not "%RC%"=="0" (
    echo.
    echo [app exited with code %RC%]
    pause
)
endlocal
