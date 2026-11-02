@echo off
title Smart Campus - Backend API Server
color 0A
echo ====================================================
echo Starting Smart Campus Backend API (FastAPI + MySQL)
echo ====================================================
cd /d "%~dp0backend"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
