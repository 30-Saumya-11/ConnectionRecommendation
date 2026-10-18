@echo off
title SonetQ - Generate Word Project Report
echo ============================================================
echo   Generating Final Project Report (.docx)
echo   Target: SonetQ_BloodDonation_Final_Project_Report.docx
echo ============================================================
echo.
python generate_word_report.py
if %errorlevel% neq 0 (
    py generate_word_report.py
)
echo.
pause
