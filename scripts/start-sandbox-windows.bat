@echo off
setlocal
cd /d "%~dp0.."
echo [INFO] XHAUS sandbox start (Windows)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-sandbox-windows.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo [FAIL] Exit code %EXITCODE%
  pause
  exit /b %EXITCODE%
)
pause
exit /b 0
