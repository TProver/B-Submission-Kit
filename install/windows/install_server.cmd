@echo off
REM ============================================================
REM BSK classroom server installer (Windows)
REM
REM Run this once on the teacher's PC to set up the Python venv
REM and install dependencies. After install, use start_server.cmd
REM (in receiver/) to launch the server on demand.
REM
REM Prerequisites:
REM   - Python 3.9+ on PATH, or set BSK_PYTHON to the python.exe
REM     full path before running this script.
REM   - Atelier B Community Edition 24.04.2+ installed (for bbatch).
REM   - ProB installed at C:\Tools\ProB (or set BSK_PROBCLI).
REM   - Microsoft Edge installed (used for PDF report rendering).
REM ============================================================

setlocal
set HERE=%~dp0
set ROOT=%HERE%..\..
set RECEIVER=%ROOT%\receiver
set VENV=%RECEIVER%\.venv

echo.
echo ===== BSK classroom server -- Windows installer =====
echo.

REM --- 1. locate Python ---------------------------------------------------
if defined BSK_PYTHON (
    set PY=%BSK_PYTHON%
) else (
    set PY=python
)
"%PY%" --version 2>nul
if errorlevel 1 (
    echo ERROR: Python 3 not found. Install Python 3.9+ from python.org
    echo with "Add to PATH" checked, or set BSK_PYTHON to python.exe.
    pause
    exit /b 1
)
echo [1/3] Python found:
"%PY%" --version

REM --- 2. create venv ----------------------------------------------------
if exist "%VENV%\Scripts\python.exe" (
    echo [2/3] Virtual environment already exists at %VENV%, reusing.
) else (
    echo [2/3] Creating virtual environment at %VENV%
    "%PY%" -m venv "%VENV%" || goto :fail
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
)

REM --- 3. install dependencies -------------------------------------------
echo [3/3] Installing dependencies from receiver\requirements.txt
"%VENV%\Scripts\python.exe" -m pip install -r "%RECEIVER%\requirements.txt" || goto :fail

echo.
echo ============================================================
echo  Server installed successfully.
echo.
echo  To start the server, run:
echo    %RECEIVER%\start_server.cmd
echo.
echo  Useful flags:
echo    start_server.cmd            ^(default port 8000^)
echo    start_server.cmd 9000       ^(use port 9000^)
echo    start_server.cmd --clean    ^(archive previous submissions^)
echo.
echo  Optional: allow inbound connections on port 8000 in Windows Firewall:
echo    netsh advfirewall firewall add rule name="BSK 8000" ^
echo      dir=in action=allow protocol=TCP localport=8000
echo  ^(run as administrator^).
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ===== Install failed. See messages above. =====
pause
exit /b 1
