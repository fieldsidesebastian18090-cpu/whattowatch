#!/bin/bash
echo "=========================================="
echo "  WhatToWatch - 流媒体智能推荐助手"
echo "=========================================="
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装："
    echo "  brew install python3"
    echo "  或从 https://www.python.org/downloads/ 下载"
    exit 1
fi

# Install dependencies
echo "[1/2] 正在安装依赖..."
pip3 install -q -r requirements.txt

# Start server
echo "[2/2] 正在启动服务..."
echo "打开浏览器访问: http://127.0.0.1:8000"
echo "按 Ctrl+C 停止服务"
echo
open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null
python3 run.py
