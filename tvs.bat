@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" goto menu

set "PYTHON_CMD=python"
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
%PYTHON_CMD% "%~dp0scripts\tvs.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%

:menu
echo.
echo ==========================================
echo        TVS Analytics helper
echo ==========================================
echo  1) Start local server
echo  2) Docker release: up
echo  3) Status
echo  4) Logs
echo  5) Backup
echo  6) Safe update
echo  7) Run checks
echo  8) Show main admin key (local)
echo  Q) Quit
 echo.
set /p "CHOICE=Choose an option: "
if "%CHOICE%"=="1" call "%~dp0tvs.bat" local
if "%CHOICE%"=="2" call "%~dp0tvs.bat" up
if "%CHOICE%"=="3" call "%~dp0tvs.bat" status
if "%CHOICE%"=="4" call "%~dp0tvs.bat" logs
if "%CHOICE%"=="5" call "%~dp0tvs.bat" backup
if "%CHOICE%"=="6" call "%~dp0tvs.bat" update
if "%CHOICE%"=="7" call "%~dp0tvs.bat" check
if "%CHOICE%"=="8" call "%~dp0tvs.bat" show-admin-key
if /i "%CHOICE%"=="Q" exit /b 0
echo.
pause
exit /b 0
