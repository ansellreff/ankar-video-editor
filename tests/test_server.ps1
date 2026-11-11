# Starts an isolated TEST server on http://localhost:8766 (own projects/exports in cache/test_*), so automated tests
# never touch the user's real projects while the editor (port 8765) is in use.  Usage: .\tests\test_server.ps1 [-Stop]
param([switch]$Stop)
$root = Split-Path $PSScriptRoot -Parent
$c = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if ($c) { Stop-Process -Id $c.OwningProcess -Force; Start-Sleep 1 }
if ($Stop) { "test server stopped"; return }
$env:VLOG_PORT = "8766"; $env:VLOG_OPEN = "0"
$env:VLOG_PROJECTS_DIR = "$root\cache\test_projects"; $env:VLOG_EXPORTS_DIR = "$root\cache\test_exports"
New-Item -ItemType Directory -Force $env:VLOG_PROJECTS_DIR, $env:VLOG_EXPORTS_DIR | Out-Null
$p = Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList "-m","app.server" -WorkingDirectory $root `
  -RedirectStandardOutput "$root\cache\test_server.out.log" -RedirectStandardError "$root\cache\test_server.err.log" -WindowStyle Hidden -PassThru
Remove-Item Env:VLOG_PORT, Env:VLOG_OPEN, Env:VLOG_PROJECTS_DIR, Env:VLOG_EXPORTS_DIR
Start-Sleep 5
"test server pid $($p.Id) on :8766 running: " + [bool](Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
