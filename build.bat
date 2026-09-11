@echo off
setlocal EnableDelayedExpansion
title Mango Studio - Automated EXE Builder

REM ═══════════════════════════════════════════════════════════
REM Mango Studio - Automated Windows Build Script
REM Fixes PySide6 DLL conflicts (Ordinal 380) and Icon errors.
REM ═══════════════════════════════════════════════════════════

set "PY_VERSION=3.12.4"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-amd64.exe"
set "PY_INSTALLER=%TEMP%\python-installer-mango.exe"
set "PYTHON_CMD="

echo.
echo =================================================================
echo   Mango Studio - Automated EXE Builder
echo =================================================================
echo.

REM --- STEP 1: FIND PYTHON ---
echo [Step 1] Searching for Python installation...

where python >nul 2>nul
if %errorlevel%==0 (
    python --version >nul 2>nul
    if !errorlevel!==0 (
        set "PYTHON_CMD=python"
        goto python_ready
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 --version >nul 2>nul
    if !errorlevel!==0 (
        set "PYTHON_CMD=py -3"
        goto python_ready
    )
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%~D\python.exe" set "PYTHON_CMD=%%~D\python.exe"
)
if defined PYTHON_CMD goto python_ready

for /d %%D in ("%ProgramFiles%\Python*") do (
    if exist "%%~D\python.exe" set "PYTHON_CMD=%%~D\python.exe"
)
if defined PYTHON_CMD goto python_ready

set "PF86=%ProgramFiles(x86)%"
if defined PF86 (
    for /d %%D in ("%PF86%\Python*") do (
        if exist "%%~D\python.exe" set "PYTHON_CMD=%%~D\python.exe"
    )
)
if defined PYTHON_CMD goto python_ready


REM --- STEP 2: INSTALL PYTHON AUTOMATICALLY ---
echo.
echo [Setup] Python was not found. Installing Python %PY_VERSION%...
where curl >nul 2>nul
if %errorlevel%==0 (
    curl -L --fail -o "%PY_INSTALLER%" "%PY_URL%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%'"
)

start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Include_tcltk=1 Include_doc=0 Include_dev=0
if errorlevel 1 goto install_failed

set "PYTHON_CMD="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%~D\python.exe" set "PYTHON_CMD=%%~D\python.exe"
)
if defined PYTHON_CMD goto python_ready
goto install_failed


:python_ready
echo [Success] Found Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM --- STEP 3: SETUP VIRTUAL ENVIRONMENT ---
echo [Step 3] Setting up isolated virtual environment (.venv)...

REM Alte .venv löschen, falls DLL-Konflikte aus vorherigen Builds bestehen
if exist ".venv" (
    echo         Removing old .venv to ensure clean DLLs...
    rmdir /s /q ".venv"
)

%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
    echo [Error] Failed to create virtual environment.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

REM WICHTIG: Verhindert, dass PyInstaller globale Site-Packages durchsucht (Fix für Ordinal 380)
set "PYTHONNOUSERSITE=1"

echo [Success] Virtual environment activated.
echo.

REM --- STEP 4: INSTALL DEPENDENCIES ---
echo [Step 4] Installing dependencies (PySide6, Pillow, PyInstaller)...
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [Error] Failed to install dependencies.
    pause
    exit /b 1
)
pip install pyinstaller
if errorlevel 1 (
    echo [Error] Failed to install PyInstaller.
    pause
    exit /b 1
)
echo [Success] All dependencies installed.
echo.

REM --- STEP 5: CLEAN & BUILD THE EXE ---
echo [Step 5] Cleaning old builds and building MangoStudio.exe...

REM Alte Build-Artefakte löschen, um DLL-Leichen zu entfernen
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "MangoStudio.spec.bak" del "MangoStudio.spec.bak"

pyinstaller MangoStudio.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [Error] PyInstaller build failed! Check the output above.
    pause
    exit /b 1
)

echo.
echo =================================================================
echo   BUILD SUCCESSFUL!
echo =================================================================
echo.
echo Your executable is ready at:
echo   %CD%\dist\MangoStudio\MangoStudio.exe
echo.
pause
exit /b 0

:install_failed
echo [Error] Python installation failed.
pause
exit /b 1