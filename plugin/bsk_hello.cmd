@echo off
setlocal
set LOGFILE=c:\tmp\bsk-hello.log
if not exist c:\tmp mkdir c:\tmp
echo [%DATE% %TIME%] BSK plug-in fired. projectName=%~1 projectBdp=%~2 >> "%LOGFILE%"
endlocal
