# PocketSmart Server Launcher for PowerShell
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "Starting PocketSmart: AI Budget & Recommendation Assistant" -ForegroundColor Green
Write-Host "Default App URL: http://localhost:8000" -ForegroundColor Yellow
Write-Host "===================================================" -ForegroundColor Cyan

# Open default browser link automatically
Start-Process "http://localhost:8000"

$pythonExe = "C:\Users\DELL\AppData\Local\Python\pythoncore-3.14-64\python.exe"

if (Test-Path $pythonExe) {
    & $pythonExe app.py
} else {
    python app.py
}

