@echo off
REM Start the BSK classroom submission server on this Windows machine.
REM First run installs dependencies into a local .venv. Subsequent runs reuse it.
REM
REM Usage:
REM   start_server.cmd                    -- start on default port 8000
REM   start_server.cmd 9000               -- start on port 9000
REM   start_server.cmd --clean            -- archive existing submissions, then start (port 8000)
REM   start_server.cmd --clean 9000       -- archive then start on 9000
REM   start_server.cmd --purge            -- DELETE existing submissions (dangerous; double-confirm)

setlocal EnableDelayedExpansion
set HERE=%~dp0
set ROOT=%HERE%..
set VENV=%HERE%.venv
set CLEAN=0
set PURGE=0
set PORT=8000

REM --- argument parsing -----------------------------------------------------
:parse
if "%~1"=="" goto :after_args
if /i "%~1"=="--clean" (
    set CLEAN=1
    shift
    goto :parse
)
if /i "%~1"=="--purge" (
    set PURGE=1
    shift
    goto :parse
)
set PORT=%~1
shift
goto :parse
:after_args

REM --- archive / purge step (before server launch) --------------------------
if %CLEAN%==1 call :archive_submissions
if %PURGE%==1 call :purge_submissions

REM --- venv setup -----------------------------------------------------------
if defined BSK_PYTHON (set PY=%BSK_PYTHON%) else (set PY=python)
if not exist "%VENV%\Scripts\python.exe" (
    echo Creating virtual environment at %VENV%
    "%PY%" -m venv "%VENV%" || goto :fail
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
    "%VENV%\Scripts\python.exe" -m pip install -r "%HERE%requirements.txt" || goto :fail
)

echo.
echo BSK classroom server starting on port %PORT%.
echo Dashboard: http://localhost:%PORT%/
echo Press Ctrl+C to stop.
echo.

"%VENV%\Scripts\python.exe" -m uvicorn server:app --app-dir "%HERE%" --host 0.0.0.0 --port %PORT%
exit /b %ERRORLEVEL%

REM ==========================================================================

:archive_submissions
set TS=%DATE:/=-%_%TIME::=-%
set TS=%TS: =0%
set TS=%TS:.=-%
set TS=%TS:,=-%
set ARCHIVE=%ROOT%\archives\%TS%

echo.
echo About to ARCHIVE existing submission state.
if exist "%ROOT%\submissions" (
    echo   - submissions\           -^> archives\%TS%\submissions\
    dir /b "%ROOT%\submissions" 2>nul
) else (
    echo   - submissions\         (none)
)
if exist "%ROOT%\server_workspace" (
    echo   - server_workspace\      -^> archives\%TS%\server_workspace\
) else (
    echo   - server_workspace\    (none)
)
echo.
set /p CONFIRM=Continue with archive? [y/N]:
if /i not "!CONFIRM!"=="y" (
    echo Aborted by user.
    exit /b 0
)

if not exist "%ARCHIVE%" mkdir "%ARCHIVE%"
if exist "%ROOT%\submissions"     move "%ROOT%\submissions"     "%ARCHIVE%\submissions"     >nul
if exist "%ROOT%\server_workspace" move "%ROOT%\server_workspace" "%ARCHIVE%\server_workspace" >nul
echo Archived to %ARCHIVE%
echo.
exit /b 0

:purge_submissions
echo.
echo *** WARNING ***  --purge will DELETE the following without recovery:
if exist "%ROOT%\submissions"      echo   - %ROOT%\submissions\
if exist "%ROOT%\server_workspace" echo   - %ROOT%\server_workspace\
echo.
set /p CONFIRM=Type DELETE to confirm:
if not "!CONFIRM!"=="DELETE" (
    echo Aborted -- nothing deleted.
    exit /b 0
)
if exist "%ROOT%\submissions"      rmdir /s /q "%ROOT%\submissions"
if exist "%ROOT%\server_workspace" rmdir /s /q "%ROOT%\server_workspace"
echo Purged.
echo.
exit /b 0

:fail
echo.
echo Server setup failed. Check that Python 3.9+ is installed and on PATH,
echo or set BSK_PYTHON=C:\path\to\python.exe before running this script.
pause
exit /b 1
