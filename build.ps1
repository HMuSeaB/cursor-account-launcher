# 打包 Cursor Launcher 为单文件 exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pip = Join-Path $PSScriptRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path $python)) {
    Write-Host "未找到 .venv，正在创建虚拟环境…" -ForegroundColor Yellow
    python -m venv .venv
}

Write-Host "安装/更新打包依赖…" -ForegroundColor Cyan
& $pip install -q -r requirements.txt pyinstaller>=6.0

Write-Host "开始 PyInstaller 打包（约 1–3 分钟）…" -ForegroundColor Cyan
& $python -m PyInstaller cursor-launcher.spec --noconfirm --clean

$exe = Join-Path $PSScriptRoot "dist\CursorLauncher.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "打包成功！" -ForegroundColor Green
    Write-Host "  路径: $exe"
    Write-Host "  大小: ${size} MB"
    Write-Host ""
    Write-Host "双击 dist\CursorLauncher.exe 即可运行，无需安装 Python。"
} else {
    Write-Host "打包失败，请查看上方 PyInstaller 输出。" -ForegroundColor Red
    exit 1
}
