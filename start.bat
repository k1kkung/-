@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PROJECT_ROOT=%CD%"
set "CACHE_DIR=%PROJECT_ROOT%\cache"
set "TEMP_DIR=%CACHE_DIR%\temp"
set "PIP_CACHE_DIR=%CACHE_DIR%\pip"
set "PYTHONPYCACHEPREFIX=%CACHE_DIR%\python-pycache"
set "WEBVIEW2_USER_DATA_FOLDER=%CACHE_DIR%\webview"
set "TEMP=%TEMP_DIR%"
set "TMP=%TEMP_DIR%"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if not exist "%WEBVIEW2_USER_DATA_FOLDER%" mkdir "%WEBVIEW2_USER_DATA_FOLDER%"
if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"

set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "VENV_PYTHONW=%PROJECT_ROOT%\.venv\Scripts\pythonw.exe"

if not exist "%VENV_PYTHON%" (
    echo [SOUP.AI] Creating the D-drive virtual environment...
    python -m venv "%PROJECT_ROOT%\.venv"
    if errorlevel 1 goto :error
)

"%VENV_PYTHON%" -c "import webview, requests" >nul 2>nul
if errorlevel 1 (
    echo [SOUP.AI] Installing desktop dependencies...
    "%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%\requirements.txt" --disable-pip-version-check --no-warn-script-location
    if errorlevel 1 goto :error
)

"%VENV_PYTHON%" "%PROJECT_ROOT%\backend\export_frontend_data.py" >nul 2>nul

title SOUP.AI Turtle Soup
if exist "%VENV_PYTHONW%" (
    "%VENV_PYTHONW%" "%PROJECT_ROOT%\backend\app.py"
) else (
    "%VENV_PYTHON%" "%PROJECT_ROOT%\backend\app.py"
)
goto :eof

:error
echo.
echo [SOUP.AI] Startup preparation failed. Logs: %PROJECT_ROOT%\logs
pause
endlocal
