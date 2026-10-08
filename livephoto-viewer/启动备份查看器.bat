@echo off
chcp 65001 >nul
title 实况照片备份查看器
cd /d "%~dp0"

rem 检查 Python
python -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [提示] 未检测到 Python，请访问 https://www.python.org/downloads/ 安装后重试。
    pause
    exit /b
)

rem 检查并安装依赖
python -c "import PIL, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 (
    echo 首次运行，正在安装所需组件（仅需一次，请稍候）...
    pip install --quiet pillow imageio-ffmpeg
)

rem 启动图形界面
start "" python "LivePhoto_Backup.pyw"
