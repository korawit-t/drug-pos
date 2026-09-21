@echo off
rem Starts Drug POS for the shop LAN. For start-on-boot, install this as a
rem Windows service (see README: "run as a service").
cd /d "%~dp0..\..\backend"
set DRUGPOS_DEBUG=0
.venv\Scripts\python serve.py --port 8000
