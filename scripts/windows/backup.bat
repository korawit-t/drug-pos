@echo off
rem Safe backup while the shop is open. Usage: backup.bat D:\DrugPOS-backup
rem Schedule it daily with Task Scheduler. Keeps the latest 30 copies.
cd /d "%~dp0..\..\backend"
set DEST=%~1
if "%DEST%"=="" set DEST=%USERPROFILE%\DrugPOS-backup
.venv\Scripts\python manage.py backup_db --dest "%DEST%"
