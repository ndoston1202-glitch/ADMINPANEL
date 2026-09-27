@echo off
chcp 65001 >nul
title Obuna Admin
cd /d "%~dp0"
rem Dasturlaringiz obunalarini boshqarish paneli (faqat shu kompyuterda ochiladi)
where python >nul 2>nul
if errorlevel 1 (
    echo Python topilmadi! https://www.python.org/downloads/ dan o'rnating ^("Add Python to PATH"^).
    pause
    exit /b 1
)
where pythonw >nul 2>nul
if errorlevel 1 (
    start "" python "%~dp0admin.py"
) else (
    start "" pythonw "%~dp0admin.py"
)
