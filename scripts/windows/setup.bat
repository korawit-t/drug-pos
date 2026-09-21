@echo off
rem First-time install on the shop server. Needs Python 3.13 from python.org
rem and a built frontend (frontend\dist) copied from the development machine.
setlocal
cd /d "%~dp0..\..\backend"

where py >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.13 from https://www.python.org/downloads/ first.
  pause
  exit /b 1
)
if not exist "..\frontend\dist\index.html" (
  echo frontend\dist is missing. Run "npm run build" in the frontend folder first.
  pause
  exit /b 1
)

py -3.13 -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip || goto :error
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
.venv\Scripts\python manage.py migrate || goto :error
.venv\Scripts\python manage.py collectstatic --noinput || goto :error

echo.
echo Installed. Now create the owner account (used for the back office):
.venv\Scripts\python manage.py createsuperuser
echo.
echo Next: run start-server.bat
pause
exit /b 0

:error
echo Setup failed - see the message above.
pause
exit /b 1
