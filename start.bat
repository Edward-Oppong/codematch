@echo off
rem CodeMatch: double-click to start. The first run sets things up (needs internet once); later runs just start.
title CodeMatch
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" goto run

echo Setting up CodeMatch for the first time. This takes a minute...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% -m venv venv
if errorlevel 1 goto nopython
"venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Couldn't install what CodeMatch needs. Check your internet connection and run start.bat again.
  rmdir /s /q venv
  pause
  exit /b 1
)

:run
echo Starting CodeMatch. Your browser will open at http://127.0.0.1:5000
echo Keep this window open while you use it; close it to stop CodeMatch.
set CODEMATCH_OPEN=1
"venv\Scripts\python.exe" run.py
echo.
echo CodeMatch stopped.
pause
exit /b 0

:nopython
echo.
echo Python 3 isn't installed. Get it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during the install, then run start.bat again.
pause
exit /b 1
