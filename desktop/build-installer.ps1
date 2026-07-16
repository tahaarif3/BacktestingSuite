# Builds the Windows NSIS installer for the BacktestingSuite desktop app.
#
#   powershell -File desktop\build-installer.ps1            # build only
#   powershell -File desktop\build-installer.ps1 -Publish   # build + create GitHub release
#
# Two stages, order matters:
#   1. PyInstaller freezes the FastAPI backend (spec includes public-safety
#      assertions that fail the build if private strategies or data leak in).
#   2. electron-builder bundles the frontend and packs everything into an
#      NSIS installer at desktop\frontend\release\BacktestingSuite-Setup-<version>.exe.
#
# For auto-update to work, a GitHub release must carry THREE assets: the Setup
# .exe, its .blockmap, and latest.yml (the updater fetches latest.yml first).
# -Publish creates that release via the gh CLI; otherwise the three files are
# printed for manual upload.
#
# Prerequisites: repo .venv with requirements.txt installed (incl. pyinstaller),
# npm install done in desktop\frontend, and Windows Developer Mode enabled
# (electron-builder needs symlink privileges). -Publish also needs the gh CLI
# (winget install GitHub.cli) authenticated with `gh auth login`.

param([switch]$Publish)

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

$pkg = Get-Content "$repo\desktop\frontend\package.json" -Raw | ConvertFrom-Json
$version = $pkg.version
$release = "$repo\desktop\frontend\release"
$assets = @(
    "$release\BacktestingSuite-Setup-$version.exe",
    "$release\BacktestingSuite-Setup-$version.exe.blockmap",
    "$release\latest.yml"
)

$missing = $assets | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "Expected release assets not found:`n$($missing -join "`n")" }

Write-Host ""
Write-Host "Installer built. Upload ALL THREE files to GitHub release v${version}:" -ForegroundColor Green
$assets | ForEach-Object { Write-Host "  $_" }

if ($Publish) {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) { throw "gh CLI not found. Install with: winget install GitHub.cli" }
    & gh release create "v$version" --repo tahaarif3/BacktestingSuite `
        --title "v$version" --generate-notes @assets
    if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }
    Write-Host "Release v$version published." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Re-run with -Publish to create the GitHub release via gh." -ForegroundColor Yellow
}
