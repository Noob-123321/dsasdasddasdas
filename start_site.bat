@echo off
setlocal
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
if "%WEB_PORT%"=="" set "WEB_PORT=8000"
if "%TVS_POLLER%"=="0" set "POLLER_ENABLED=0"

set "PYTHON_CMD=python"
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ was not found. Install Python and try again.
    pause
    exit /b 1
  )
)

echo Starting TVS Analytics on http://127.0.0.1:%WEB_PORT%
echo Close this window with Ctrl+C to stop the local server.
%PYTHON_CMD% -m alembic upgrade head
if errorlevel 1 goto failed
%PYTHON_CMD% -m uvicorn app.main:app --host 127.0.0.1 --port %WEB_PORT%
set "RC=%ERRORLEVEL%"
echo.
echo Server stopped with exit code %RC%.
pause
exit /b %RC%

:failed
echo.
echo Startup failed. Check the error above, then run:
echo   %PYTHON_CMD% -m pip install -r requirements.txt
pause
exit /b 1
