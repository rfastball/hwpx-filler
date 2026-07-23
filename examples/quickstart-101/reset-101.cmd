@echo off
setlocal
REM ===================================================================
REM  101 example reset -- double-click to wipe practice state.
REM  Deletes ONLY app-generated files inside this folder, so you can
REM  start the tutorial from scratch. Committed example assets
REM  (templates/, text_templates/, data/, *.cmd, *.md, make_template.py)
REM  are never touched. Your real ~/.hwpxfiller is untouched too.
REM ===================================================================

cd /d "%~dp0"

echo This will delete practice state created by the app in this folder:
echo   jobs\  datasets\  mapping_bases\  webview\  out\  templates\Results\
echo   ui_settings.ini  settings.json
echo.
choice /m "Reset now"
if errorlevel 2 exit /b 0

for %%D in (jobs datasets mapping_bases webview out) do (
    if exist "%%D" rd /s /q "%%D"
)
if exist "templates\Results" rd /s /q "templates\Results"
if exist "ui_settings.ini" del /q "ui_settings.ini"
if exist "settings.json" del /q "settings.json"

echo.
echo Done. Run start-101.cmd to begin again from a clean state.
pause
endlocal
