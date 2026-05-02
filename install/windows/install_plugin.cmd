@echo off
REM ============================================================
REM BSK Atelier B plug-in installer (Windows)
REM
REM Copies the BSK Submission plug-in into the Atelier B
REM share\plugins\ folder so it appears as a "BSK Submission"
REM submenu under the Project menu.
REM
REM Run as administrator (right-click -> Run as administrator).
REM
REM If your Atelier B is installed somewhere other than the
REM default path below, set the ATB_ROOT environment variable
REM to its install root before running this script:
REM    set ATB_ROOT=C:\Path\To\Atelier B
REM    install_plugin.cmd
REM ============================================================

setlocal
set HERE=%~dp0
set ROOT=%HERE%..\..
set PLUGIN=%ROOT%\plugin

if defined ATB_ROOT (
    set ATBROOT=%ATB_ROOT%
) else (
    set ATBROOT=C:\Program Files\Atelier B Community Edition 24.04.2 24.04.2
)
set DST=%ATBROOT%\share\plugins

echo.
echo ===== BSK Atelier B plug-in -- Windows installer =====
echo Source : %PLUGIN%
echo Target : %DST%
echo.

if not exist "%ATBROOT%" (
    echo ERROR: Atelier B install not found at:
    echo   %ATBROOT%
    echo Set ATB_ROOT to the right path, then re-run.
    pause
    exit /b 1
)

if not exist "%DST%" (
    echo Creating %DST%
    mkdir "%DST%" || goto :fail
)

echo Copying plug-in files...
copy /Y "%PLUGIN%\BSKConnect.etool"  "%DST%\BSKConnect.etool"  || goto :fail
copy /Y "%PLUGIN%\BSKSubmit.etool"   "%DST%\BSKSubmit.etool"   || goto :fail
copy /Y "%PLUGIN%\bsk_run.cmd"       "%DST%\bsk_run.cmd"       || goto :fail
copy /Y "%PLUGIN%\bsk_client.py"     "%DST%\bsk_client.py"     || goto :fail
copy /Y "%PLUGIN%\bsk_connect.png"   "%DST%\bsk_connect.png"   || goto :fail
copy /Y "%PLUGIN%\bsk_submit.png"    "%DST%\bsk_submit.png"    || goto :fail

echo.
echo ============================================================
echo  Plug-in installed successfully.
echo.
echo  Next steps:
echo    1. Fully close Atelier B if it is currently running.
echo    2. Reopen Atelier B and open any B project.
echo    3. The Project menu now has a "BSK Submission" submenu
echo       with "Connect" and "Submit and verify" entries.
echo    4. Click "Connect" and enter your name + the classroom
echo       server URL given by the teacher.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ===== Install failed. =====
echo Likely cause: this script was not launched as administrator,
echo or Atelier B is currently running and holding files open.
pause
exit /b 1
