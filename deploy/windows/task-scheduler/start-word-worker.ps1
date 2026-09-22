$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location (Join-Path $ProjectRoot "backend")
& $Python -m app.worker.word_worker
