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
echo [1/3] 正在安装依赖...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM Check TMDB API Key
if "%TMDB_API_KEY%"=="" (
    echo.
    echo [提示] 未检测到 TMDB API Key
    echo   豆瓣同步可以正常使用，但流媒体平台匹配需要 TMDB Key
    echo   免费注册: https://www.themoviedb.org/settings/api
    echo   获取后运行: set TMDB_API_KEY=你的key
    echo   或将 key 写入同目录下的 .env 文件
    echo.
)

REM Load .env if exists
if exist .env (
    echo [提示] 检测到 .env 文件，正在加载...
    for /f "usebackq tokens=1,* delims==" %%A in (.env) do (
        set "%%A=%%B"
    )
)

REM Start server
echo [2/3] 正在启动服务...
echo [3/3] 打开浏览器访问: http://127.0.0.1:8000
echo.
echo 按 Ctrl+C 停止服务
echo.
start http://127.0.0.1:8000
python run.py
pause
