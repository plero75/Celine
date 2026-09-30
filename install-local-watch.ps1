$ErrorActionPreference = "Stop"

Write-Host "Installation du watcher local Celine..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements-local.txt
python -m playwright install chromium

Write-Host ""
Write-Host "Installation terminee." -ForegroundColor Green
Write-Host "Lance ensuite : .\run-local-watch.ps1" -ForegroundColor Yellow
