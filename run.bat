@echo off
title SonetQ BloodConnect Web Server
cd /d "%~dp0"

echo ============================================================
echo       Starting SonetQ BloodConnect Web Server...
echo ============================================================
echo.

if exist "C:\Users\hp\anaconda3\python.exe" (
    set "PYTHON_CMD=C:\Users\hp\anaconda3\python.exe"
) else (
    set "PYTHON_CMD=python"
)

echo Python Command: %PYTHON_CMD%
echo Opening browser to http://127.0.0.1:8000 ...
start "" "http://127.0.0.1:8000"

"%PYTHON_CMD%" blood_app.py web

echo.
echo Server stopped.
pause
