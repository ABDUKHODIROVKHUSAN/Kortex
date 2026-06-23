# Kortex backend startup (Windows)
# Run from the backend folder: .\start.ps1

$ErrorActionPreference = "Stop"

Write-Host "Kortex backend startup" -ForegroundColor Cyan
Write-Host ""

# Stop stale processes on port 8000
$on8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $on8000) {
  if ($pid -and $pid -ne 0) {
    Write-Host "Stopping old process on port 8000 (PID $pid)..." -ForegroundColor Yellow
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
  }
}

# Check PostgreSQL
Write-Host "Checking PostgreSQL on port 5432..." -ForegroundColor Gray
$pg = Test-NetConnection -ComputerName localhost -Port 5432 -WarningAction SilentlyContinue
if (-not $pg.TcpTestSucceeded) {
  Write-Host ""
  Write-Host "PostgreSQL is NOT running." -ForegroundColor Red
  Write-Host "Start PostgreSQL first (pgAdmin / Services), then run this script again."
  Write-Host "The backend will hang without a database."
  exit 1
}
Write-Host "PostgreSQL OK" -ForegroundColor Green

if (-not (Test-Path ".\venv\Scripts\uvicorn.exe")) {
  Write-Host "Virtual env not found. Run: python -m venv venv && .\venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "Starting API on http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "First start can take 1-2 minutes on a slow PC. Wait for:" -ForegroundColor Yellow
Write-Host "  Application startup complete" -ForegroundColor Yellow
Write-Host ""
Write-Host "Do NOT use --reload on Windows if the server keeps crashing." -ForegroundColor Gray
Write-Host ""

& .\venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
