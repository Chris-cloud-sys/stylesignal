@echo off
cd /d "C:\Users\Chris\source\repos\stylesignal\mobile"
:loop
echo [StyleSignal Metro] starting...
call npx expo start --dev-client --lan
echo [StyleSignal Metro] exited, restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto loop
