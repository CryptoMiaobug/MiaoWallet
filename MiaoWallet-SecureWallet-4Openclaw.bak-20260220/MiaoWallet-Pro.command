#!/bin/bash
# MiaoWallet Pro - 网页版启动器
# 双击此文件即可启动 MiaoWallet Pro 网页版

cd "$(dirname "$0")"

echo "🔐 启动 MiaoWallet Pro 网页版..."
echo "========================================"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 错误: 找不到虚拟环境 'venv'"
    echo "请先运行: python3 -m venv venv"
    echo "然后运行: source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查Python依赖
if ! python3 -c "import http.server, json, webbrowser, socket" 2>/dev/null; then
    echo "⚠️  缺少Python标准库，但应该没问题..."
fi

# 检查数据文件
if [ ! -f ".wallet_addresses.json" ]; then
    echo "⚠️  警告: 找不到钱包数据文件 .wallet_addresses.json"
    echo "将显示空页面，你可以通过网页界面添加钱包"
fi

# 启动网页版
echo "🚀 正在启动 MiaoWallet Pro 网页版 (v2.0)..."
echo "请稍等..."

# 运行最新稳定版
python3 miaowallet_webgui.py

echo ""
echo "👋 MiaoWallet Pro 已关闭"
echo "========================================"