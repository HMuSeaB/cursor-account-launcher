# Build Cursor Launcher as a single-file exe (UTF-8 BOM required for PS 5.1)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pip = Join-Path $PSScriptRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path $python)) {
    Write-Output "[build] Creating virtual environment..."
    python -m venv .venv
    if (-not (Test-Path $python)) {
        Write-Error "Failed to create .venv. Is Python on PATH?"
    }
}

Write-Output "[build] Installing/updating dependencies..."
& $pip install -q -r requirements.txt "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed (exit $LASTEXITCODE)"
}

Write-Output "[build] Running PyInstaller (about 1-3 min)..."
& $python -m PyInstaller cursor-launcher.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed (exit $LASTEXITCODE)"
}

$exe = Join-Path $PSScriptRoot "dist\CursorLauncher.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Output ""
    Write-Output "[build] SUCCESS"
    Write-Output "  Path: $exe"
    Write-Output "  Size: ${size} MB"
    Write-Output ""
    Write-Output "Run dist\CursorLauncher.exe directly (Python not required)."
} else {
    Write-Error "Build finished but exe not found: $exe"
}
