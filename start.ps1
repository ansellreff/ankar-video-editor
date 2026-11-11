# AnKar Video Editor launcher — runs entirely from this folder's .venv (nothing installed system-wide).
# Usage: right-click > "Run with PowerShell", or in a terminal:  .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating the virtual environment (.venv)..." -ForegroundColor Yellow
    python -m venv .venv
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r requirements.txt -q
}
Write-Host "AnKar Video Editor -> http://localhost:8765  (Ctrl+C to stop)" -ForegroundColor Cyan
& $py -m app.server
