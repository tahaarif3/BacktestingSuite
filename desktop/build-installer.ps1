# Builds the Windows NSIS installer for the BacktestingSuite desktop app.
#
#   powershell -File desktop\build-installer.ps1
#
# Two stages, order matters:
#   1. PyInstaller freezes the FastAPI backend (spec includes public-safety
#      assertions that fail the build if private strategies or data leak in).
#   2. electron-builder bundles the frontend and packs everything into an
#      NSIS installer at desktop\frontend\release\BacktestingSuite-Setup-<version>.exe.
#
# Prerequisites: repo .venv with requirements.txt installed (incl. pyinstaller),
# npm install done in desktop\frontend, and Windows Developer Mode enabled
# (electron-builder needs symlink privileges).

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

# Clean previous backend build so stale modules can't linger in the bundle.
Remove-Item -Recurse -Force "$repo\desktop\backend\dist", "$repo\desktop\backend\build" -ErrorAction SilentlyContinue

# 1) Freeze the FastAPI backend. Explicit --distpath: extraResources in
#    frontend/package.json expects ../backend/dist/BacktestApiServer, but
#    PyInstaller's default distpath is relative to the cwd.
& "$repo\.venv\Scripts\python.exe" -m PyInstaller desktop\backend\BacktestApiServer.spec `
    --noconfirm --distpath desktop\backend\dist --workpath desktop\backend\build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 2) Build the renderer and pack the NSIS installer.
Set-Location "$repo\desktop\frontend"
npm run dist
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }

Write-Host ""
Write-Host "Installer built:" -ForegroundColor Green
Get-ChildItem "$repo\desktop\frontend\release\*.exe" | ForEach-Object { Write-Host "  $($_.FullName)" }
