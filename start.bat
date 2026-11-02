@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nav atrasts. Instale no https://www.python.org/downloads/ un atzime "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist "%USERPROFILE%\.estudijas_sync\.deps_ok" (
  echo Pirma palaisana: instale bibliotekas...
  python -m pip install -q -r requirements.txt || (pause & exit /b 1)
  python -m playwright install chromium || (pause & exit /b 1)
  if not exist "%USERPROFILE%\.estudijas_sync" mkdir "%USERPROFILE%\.estudijas_sync"
  echo ok > "%USERPROFILE%\.estudijas_sync\.deps_ok"
)
python run.py web
pause
