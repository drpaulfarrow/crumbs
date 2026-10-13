# One-time setup: Python venv, dependencies, block lists, config, Crumbs resolver check.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
    else { throw "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." }
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements-dev.txt

if (-not (Test-Path "demo_config.json")) {
    Copy-Item demo_config.example.json demo_config.json
    Write-Host "Created demo_config.json: put your Monetize placement ID in it."
}

Write-Host "`nDownloading EasyPrivacy and EasyList..."
try { & $venvPy -m crumbs_demo update-lists } catch { Write-Warning "List download failed; the bundled seed lists will be used." }

Write-Host "`nChecking the Crumbs resolver from this network..."
& $venvPy -m crumbs_demo check-crumbs

Write-Host "`nRunning tests..."
& $venvPy -m pytest -q tests

Write-Host "`nSetup done. Start the demo with: scripts\windows\start-demo.ps1"
