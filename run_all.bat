@echo off
title Smart Campus - Full Stack Runner
echo ====================================================
echo Launching Smart Campus System (Backend + Frontend)
echo ====================================================
start "Smart Campus Backend" cmd /c "cd /d ""%~dp0backend"" && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "Smart Campus Frontend" cmd /c "cd /d ""%~dp0frontend"" && python -m http.server 5500"
timeout /t 1 /nobreak >nul
start http://localhost:5500
echo.
echo Both servers are starting up!
echo - Frontend: http://localhost:5500
echo - Backend:  http://127.0.0.1:8000
echo - API Docs: http://127.0.0.1:8000/docs
echo.
