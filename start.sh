#!/bin/bash
# =====================================================
#  🚀 Echoes（往事可追忆）— 一键启动脚本
#  适用于技术小白，只需执行：bash start.sh
# =====================================================

set -e

# ---- 颜色输出 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  🚀 Echoes（往事可追忆）启动中...${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# ---- 1. 检测 Node.js ----
echo -e "${YELLOW}[1/4] 检测 Node.js 环境...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 错误：未检测到 Node.js，请先安装 Node.js (v16+)${NC}"
    echo "   安装方法请参考：https://nodejs.org/"
    exit 1
fi

NODE_VER=$(node -v)
echo -e "   ✅ Node.js 版本: ${GREEN}$NODE_VER${NC}"

# ---- 2. 安装后端依赖 ----
echo -e "${YELLOW}[2/4] 检查并安装后端依赖...${NC}"
cd "$(dirname "$0")/backend"

if [ ! -d "node_modules" ]; then
    echo "   📦 正在安装依赖（首次运行可能需要一分钟）..."
    npm install --loglevel=error
    echo -e "   ✅ 依赖安装完成"
else
    echo -e "   ✅ 依赖已存在，跳过安装"
fi

# ---- 3. 检查前端文件 ----
echo -e "${YELLOW}[3/4] 检查前端文件...${NC}"
FRONTEND_DIR="../web/frontend"
if [ -f "$FRONTEND_DIR/index.html" ]; then
    echo -e "   ✅ 前端文件正常（${FRONTEND_DIR}）"
else
    echo -e "${RED}❌ 错误：未找到前端文件（${FRONTEND_DIR}/index.html）${NC}"
    exit 1
fi

# ---- 4. 启动后端服务 ----
echo -e "${YELLOW}[4/4] 启动后端服务...${NC}"
echo ""

# 检查端口 3000 是否已被占用
if lsof -i :3000 -sTCP:LISTEN &>/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  端口 3000 已被占用，尝试关闭旧进程...${NC}"
    lsof -ti :3000 | xargs kill -9 2>/dev/null || true
    sleep 1
    echo "   ✅ 旧进程已关闭"
fi

echo -e "${GREEN}🎉 服务启动中，请访问：${NC}"
echo -e "${GREEN}   http://localhost:3000${NC}"
echo ""
echo -e "${YELLOW}提示：按 Ctrl+C 可停止服务${NC}"
echo ""

# 启动后端（前台运行，方便 Ctrl+C 停止）
exec node server.js
