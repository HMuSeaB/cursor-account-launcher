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
& $pip install -q -r requirements.txt "pyinstaller>=6.0" pillow
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed (exit $LASTEXITCODE)"
}

Write-Output "[build] Rendering app icon..."
& $python (Join-Path $PSScriptRoot "scripts\make_icon.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "make_icon.py failed (exit $LASTEXITCODE)"
}

$icon = Join-Path $PSScriptRoot "assets\icon.ico"
if (-not (Test-Path $icon)) {
    Write-Error "Missing $icon"
}

Write-Output "[build] Running PyInstaller (about 1-3 min)..."
& $python -m PyInstaller cursor-launcher.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed (exit $LASTEXITCODE)"
}

$exe = Join-Path $PSScriptRoot "dist\CursorLauncher.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build finished but exe not found: $exe"
}

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Output ""
Write-Output "[build] SUCCESS"
Write-Output "  Path: $exe"
Write-Output "  Size: ${size} MB"

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($iscc) {
    Write-Output "[build] Compiling installer..."
    & $iscc (Join-Path $PSScriptRoot "installer\cursor-launcher.iss")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ISCC failed (exit $LASTEXITCODE)"
    }
    $setup = Join-Path $PSScriptRoot "dist\CursorLauncherSetup.exe"
    if (Test-Path $setup) {
        $setupSize = [math]::Round((Get-Item $setup).Length / 1MB, 1)
        Write-Output "  Installer: $setup"
        Write-Output "  Size: ${setupSize} MB"
    }
} else {
    Write-Output "[build] Inno Setup 6 not found; skipped installer (exe is still ready)."
}

Write-Output ""
Write-Output "Portable: dist\CursorLauncher.exe"
Write-Output "Installer: dist\CursorLauncherSetup.exe (optional desktop shortcut checkbox)."
