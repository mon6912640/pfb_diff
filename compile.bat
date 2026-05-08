
@echo off
chcp 65001 >nul
echo ==========================================
echo  PfbDiff Build Script
echo ==========================================

:: Check PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller not found. Please install:
    echo   pip install pyinstaller
    pause
    exit /b 1
)

:: Get tkinterdnd2 path
for /f "delims=" %%i in ('python -c "import tkinterdnd2, os; print(os.path.dirname(tkinterdnd2.__file__))"') do set TKDND_PATH=%%i

echo [INFO] tkinterdnd2 path: %TKDND_PATH%

:: Clean old builds
echo [INFO] Cleaning old builds...
if exist build rmdir /s /q build
if exist PfbDiff.exe del PfbDiff.exe
if exist PfbDiff.spec del PfbDiff.spec

:: Build
echo [INFO] Starting build...
python -m PyInstaller ^
    --name PfbDiff ^
    --onefile ^
    --noconsole ^
    --clean ^
    --icon=icon.ico ^
    --distpath . ^
    --add-data "%TKDND_PATH%\tkdnd;tkinterdnd2\tkdnd" ^
    --hidden-import tkinterdnd2 ^
    --hidden-import tkinterdnd2.TkinterDnD ^
    --add-data "icon.ico;." ^
    gui.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Build complete!
echo  Output: PfbDiff.exe
echo ==========================================
pause
