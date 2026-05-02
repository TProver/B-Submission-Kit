@echo off
REM Install the BSKHello test plug-in into the Atelier B Community Edition plugins folder.
REM The AtelierB.exe binary searches "../share/plugins" for .etool files.
REM Run this as administrator (right-click -> Run as administrator).

set SRC=%~dp0
set ATBROOT=C:\Program Files\Atelier B Community Edition 24.04.2 24.04.2
set DST=%ATBROOT%\share\plugins

if not exist "%ATBROOT%" (
    echo ERROR: Atelier B install not found at:
    echo   %ATBROOT%
    echo Check the install path and edit this script if needed.
    pause
    exit /b 1
)

if not exist "%DST%" (
    echo Creating %DST%
    mkdir "%DST%" || goto :fail
)

echo Copying BSKHello.etool  -^> %DST%
copy /Y "%SRC%BSKHello.etool" "%DST%\BSKHello.etool" || goto :fail
echo Copying bsk_hello.cmd   -^> %DST%
copy /Y "%SRC%bsk_hello.cmd"  "%DST%\bsk_hello.cmd"  || goto :fail
echo Copying bsk_hello.png   -^> %DST%
copy /Y "%SRC%bsk_hello.png"  "%DST%\bsk_hello.png"  || goto :fail

echo.
echo OK. Restart Atelier B, open any project, press Ctrl+Alt+H (or find "BSK Hello" in the menu).
echo Then check c:\tmp\bsk-hello.log for a new line.
pause
exit /b 0

:fail
echo.
echo Copy failed. Usual cause: this script was not launched as administrator.
pause
exit /b 1
