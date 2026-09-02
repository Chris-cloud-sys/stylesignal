@echo off
cd /d "C:\Users\Chris\source\repos\stylesignal\backend"
:loop
echo [StyleSignal backend] starting...
"C:\Users\Chris\source\repos\stylesignal\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
echo [StyleSignal backend] exited, restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto loop
