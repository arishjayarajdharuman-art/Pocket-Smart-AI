@echo off
title PocketSmart AI Server
echo ===================================================
echo Starting PocketSmart: AI Budget & Recommendation Assistant
echo Default App URL: http://localhost:8000
echo ===================================================

start http://localhost:8000

set "PYTHON_EXE=C:\Users\DELL\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" app.py
) else (
    python app.py
)
pause

