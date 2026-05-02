@echo off
REM Install the BSK Submission plug-in into Atelier B.
REM Copies the two .etool descriptors, the Python client, and the icons.
REM Run as administrator (right-click -> Run as administrator).

setlocal
set SRC=%~dp0
set ATBROOT=C:\Program Files\Atelier B Community Edition 24.04.2 24.04.2
set DST=%ATBROOT%\share\plugins

if not exist "%ATBROOT%" (
    echo ERROR: Atelier B install not found at:
    echo   %ATBROOT%
    echo Edit this script if your install path differs.
    pause
    exit /b 1
)

if not exist "%DST%" (
    echo Creating %DST%
    mkdir "%DST%" || goto :fail
)

echo.
echo Installing BSK Submission plug-in to:
echo   %DST%
echo.
copy /Y "%SRC%BSKConnect.etool"  "%DST%\BSKConnect.etool"  || goto :fail
copy /Y "%SRC%BSKSubmit.etool"   "%DST%\BSKSubmit.etool"   || goto :fail
copy /Y "%SRC%bsk_run.cmd"       "%DST%\bsk_run.cmd"       || goto :fail
copy /Y "%SRC%bsk_client.py"     "%DST%\bsk_client.py"     || goto :fail
copy /Y "%SRC%bsk_connect.png"   "%DST%\bsk_connect.png"   || goto :fail
copy /Y "%SRC%bsk_submit.png"    "%DST%\bsk_submit.png"    || goto :fail
copy /Y "%SRC%bsk_logo.png"      "%DST%\bsk_logo.png"      || goto :fail

echo.
echo Install complete. Next steps:
echo   1. Fully close and reopen Atelier B.
echo   2. Open a B project.
echo   3. Project menu -^> BSK Submission -^> Connect (Ctrl+Alt+C).
echo   4. First run prompts for student name and server URL.
echo   5. Project menu -^> BSK Submission -^> Submit and verify (Ctrl+Alt+S).
echo.
echo The classroom server must be running on the configured URL.
echo Start it from receiver\start_server.cmd on the teacher's PC.
echo.
pause
exit /b 0

:fail
echo.
echo Install failed. Usual cause: this script was not launched as administrator.
pause
exit /b 1
