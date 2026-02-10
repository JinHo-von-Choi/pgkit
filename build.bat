@echo off
echo ============================================
echo  PostgreSQL DB Setup Tool - Build Script
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.9+ and add to PATH.
    pause
    exit /b 1
)

echo [1/4] Installing dependencies...
pip install psycopg2-binary pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] Package install failed.
    pause
    exit /b 1
)
echo       Done.

echo.
echo [2/4] Killing existing process...
taskkill /F /IM PGSetupTool.exe >nul 2>&1
if exist dist\PGSetupTool.exe del /f /q dist\PGSetupTool.exe
echo       Done.

echo.
echo [3/4] Building... (1-2 min)
python -m PyInstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo       Done.

echo.
echo [4/4] Cleaning up...
if exist build rmdir /s /q build
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo       Done.

echo.
echo ============================================
echo  Build successful!
echo  Output: dist\PGSetupTool.exe
echo ============================================
echo.

pause
