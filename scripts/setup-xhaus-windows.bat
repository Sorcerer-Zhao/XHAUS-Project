@echo off
setlocal
cd /d "%~dp0.."
echo [INFO] XHAUS Web setup (Windows)
echo [INFO] Repo root: %CD%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-xhaus-windows.ps1"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo [FAIL] Setup failed with exit code %EXITCODE%
  pause
  exit /b %EXITCODE%
)
echo.
pause
exit /b 0
