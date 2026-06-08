@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py -3"
) else (
    set "PYTHON_CMD=python"
)

echo Installing Python dependencies...
%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 goto :error

%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Generating application icon...
%PYTHON_CMD% app\build_icon.py app\assets\icon.svg app\assets\icon.ico "#000000"
if errorlevel 1 goto :error
%PYTHON_CMD% app\build_icon.py app\assets\icon.svg app\assets\icon-white.ico "#ffffff"
if errorlevel 1 goto :error

set "APP_ICON=app\assets\icon.ico"
for /f "tokens=3" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v AppsUseLightTheme 2^>nul') do set "APPS_USE_LIGHT_THEME=%%A"
if /i "%APPS_USE_LIGHT_THEME%"=="0x0" set "APP_ICON=app\assets\icon-white.ico"

echo Building Pixel Fix executable...
%PYTHON_CMD% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name pixel-fix ^
    --icon "%APP_ICON%" ^
    --paths app ^
    --collect-all webview ^
    --add-data "app\gui;gui" ^
    --add-data "app\assets;assets" ^
    app\main.py
if errorlevel 1 goto :error

echo.
echo Done. Executable created at:
echo %cd%\dist\pixel-fix.exe
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
