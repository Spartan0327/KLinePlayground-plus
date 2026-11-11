@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "webview_app\main_pywebview.py"
echo.
echo [exit code] %errorlevel%
pause