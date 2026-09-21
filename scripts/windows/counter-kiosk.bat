@echo off
rem Opens the sales screen full screen on a counter PC, printing without dialogs.
rem Change SERVER to the shop server's fixed IP. Exit kiosk mode with Alt+F4.
set SERVER=http://192.168.1.10:8000
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk --kiosk-printing --user-data-dir=C:\DrugPOS-chrome %SERVER%
