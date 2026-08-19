#!/bin/bash
# 财务记账工具 — 启动脚本
# 用法: ./start.sh [端口号]

PORT=${1:-8008}
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==================================="
echo "  财务记账工具 v1.0"
echo "==================================="
echo ""
echo "📦 检查依赖..."
cd "$DIR/backend"

# 安装依赖
pip3 install -r requirements.txt -q 2>/dev/null

echo "🚀 启动服务 (端口: $PORT)..."
echo "   访问地址: http://localhost:$PORT"
echo "   默认账号: admin / admin123"
echo ""
echo "   如需外网访问，请配置 Nginx 反向代理"
echo "==================================="
echo ""

# 启动
PORT=$PORT python3 main.py
