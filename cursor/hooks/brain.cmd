@echo off
start "" /b "C:\Program Files\python\python.exe" "C:\benji\brain\hb.py" >nul 2>&1
"C:\Program Files\python\python.exe" "%~dp0brain_hook.py" %1
