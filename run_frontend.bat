@echo off
title Smart Campus - Frontend Web Server
color 0B
echo ====================================================
echo Starting Smart Campus Frontend (Port 5500)
echo ====================================================
cd /d "%~dp0frontend"
python -m http.server 5500
pause
