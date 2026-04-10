@echo off
chcp 65001 >nul
title WhatToWatch - 流媒体智能推荐助手
echo ==========================================
echo   WhatToWatch - 流媒体智能推荐助手
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

REM Install dependencies
echo [1/2] 正在安装依赖...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM Start server
echo [2/2] 正在启动服务...
echo 打开浏览器访问: http://127.0.0.1:8000
echo.
echo 按 Ctrl+C 停止服务
echo.
start http://127.0.0.1:8000
python run.py
pause
