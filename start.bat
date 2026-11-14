@echo off
title YouTube Bulk & Shorts Downloader
cd /d "%~dp0"

echo ========================================================
echo   YouTube Bulk & Shorts Downloader
echo ========================================================
echo.

:: Check Python virtual environment from parent or system
if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=..\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Starting Downloader Server on http://localhost:5000 ...
start "" http://localhost:5000

"%PYTHON_EXE%" app.py
pause

