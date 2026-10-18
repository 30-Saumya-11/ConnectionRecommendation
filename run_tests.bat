@echo off
title SonetQ - Run Unit Tests
echo ============================================================
echo   Running SonetQ Test Suite (36 Automated Unit Tests)
echo   Validates: Auth, RBAC, OS Scheduler, DBMS ACID, ML Model
echo ============================================================
echo.
python -m unittest discover -s tests -v
if %errorlevel% neq 0 (
    py -m unittest discover -s tests -v
)
echo.
pause
