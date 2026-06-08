@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

where uv >nul 2>nul
if errorlevel 1 goto :venv_fallback

echo Creating uv virtual environment...
if not exist "%VENV_PY%" uv venv "%VENV_DIR%"
if errorlevel 1 goto :error

echo Installing Python dependencies into %VENV_DIR%...
uv pip install --python "%VENV_PY%" -r requirements.txt
if errorlevel 1 goto :error
goto :run_app

:venv_fallback
where py >nul 2>nul
if errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    set "PYTHON_CMD=py -3"
)

echo Creating Python virtual environment...
if not exist "%VENV_PY%" %PYTHON_CMD% -m venv "%VENV_DIR%"
if errorlevel 1 goto :error

echo Installing Python dependencies into %VENV_DIR%...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :error

"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

:run_app
echo Starting Pixel Fix...
"%VENV_PY%" app\main.py
exit /b %errorlevel%

:error
echo.
echo Failed to prepare the virtual environment or run Pixel Fix.
pause
exit /b 1
