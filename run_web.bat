@echo off
title SonetQ BloodConnect - Web Server
echo ============================================================
echo   SonetQ: Blood Donor Recommender & Request Scheduler
echo   OS + DBMS + ML Integrated Academic Prototype
echo ============================================================
echo.
echo Launching Flask Web Application...
echo Default accounts:
echo   - Admin:     username=admin     password=admin123
echo   - Staff:     username=staff     password=staff123
echo   - Requester: username=user10    password=user123
echo.
echo Open your browser at: http://127.0.0.1:8000
echo ============================================================
echo.
python blood_app.py web
if %errorlevel% neq 0 (
    echo.
    echo Trying with py launcher or python3...
    py blood_app.py web
)
pause
