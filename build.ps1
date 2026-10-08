$ErrorActionPreference = 'Stop'
$harborRoot = $PSScriptRoot
$harborPython = Join-Path $harborRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $harborPython)) { throw '请先按 README 创建 .venv 并安装 requirements.txt。' }
Push-Location $harborRoot
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $harborRoot '.build-cache'
    & $harborPython -m PyInstaller --noconfirm --onedir --windowed --name TG-Harbor --icon 'web\assets\icon.ico' --add-data 'web;web' --collect-all webview --collect-all telethon --hidden-import socks --hidden-import PIL.Image --hidden-import qrcode --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide6 --exclude-module tkinter app.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
    & $harborPython package_release.py
    if ($LASTEXITCODE -ne 0) { throw '发布文件整理失败。' }
    Write-Output 'Windows 程序已生成：dist\TG-Harbor\TG-Harbor.exe'
} finally { Pop-Location }
