@echo off
setlocal
REM ===================================================================
REM  101 example launcher -- double-click to run.
REM  Sets THIS folder as HWPXFILLER_HOME, so its templates and text
REM  drafts appear in the app (your real ~/.hwpxfiller is untouched).
REM
REM  First time only, install the pinned Rust and Node toolchains.
REM  After that, just double-click this file (or run start-101.cmd).
REM ===================================================================

set "HWPXFILLER_HOME=%~dp0"
REM repo root = two levels up from this file
pushd "%~dp0..\.."

echo Starting app...  HWPXFILLER_HOME=%HWPXFILLER_HOME%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\run-filler.ps1"
set "RC=%ERRORLEVEL%"

popd
if not "%RC%"=="0" (
    echo.
    echo [app exited with code %RC%]
    pause
)
endlocal
