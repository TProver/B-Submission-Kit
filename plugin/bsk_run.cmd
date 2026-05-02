@echo off
REM Thin wrapper that Atelier B launches via the BSK .etool files.
REM Finds a Python 3 interpreter and runs bsk_client.py with the passed args.
REM Usage (called by the .etool):
REM     bsk_run.cmd (connect|submit) <projectName> <projectBdp>

setlocal
set HERE=%~dp0

REM 1) BSK_PYTHON env var wins if set.
if defined BSK_PYTHON (
    "%BSK_PYTHON%" "%HERE%bsk_client.py" %*
    exit /b %ERRORLEVEL%
)

REM 2) Plain "python" on PATH.
where python >nul 2>nul
if %ERRORLEVEL% == 0 (
    python "%HERE%bsk_client.py" %*
    exit /b %ERRORLEVEL%
)

REM 3) Python launcher "py -3" (installed by python.org installer).
where py >nul 2>nul
if %ERRORLEVEL% == 0 (
    py -3 "%HERE%bsk_client.py" %*
    exit /b %ERRORLEVEL%
)

REM 4) Fallback: common install locations.
for %%P in (
    "C:\Python314\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if exist %%P (
        %%P "%HERE%bsk_client.py" %*
        exit /b %ERRORLEVEL%
    )
)

echo ERROR: Python 3 not found. Install Python 3 or set BSK_PYTHON to python.exe. 1>&2
exit /b 127
