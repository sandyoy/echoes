#!/bin/bash
# =====================================================
#  🚀 Echoes（往事可追忆）— 部署脚本
#  启动后端服务器并自动打开浏览器
#  小白友好：bash deploy.sh 即可
# =====================================================

set -e

# ---- 颜色输出 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🚀 Echoes（往事可追忆）部署脚本        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# ---- 1. 检测 Node.js ----
echo -e "${YELLOW}[1/5] 🔍 检测 Node.js 环境...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ 错误：未检测到 Node.js${NC}"
    echo "   👉 请前往 https://nodejs.org/ 下载安装 Node.js (推荐 v18 或 v20)"
    exit 1
fi

NODE_VER=$(node -v)
echo -e "   ✅ 当前版本: ${GREEN}$NODE_VER${NC}"

# ---- 2. 检测 npm ----
echo -e "${YELLOW}[2/5] 🔍 检测 npm 包管理器...${NC}"
if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ 错误：未检测到 npm${NC}"
    exit 1
fi
NPM_VER=$(npm -v)
echo -e "   ✅ 当前版本: ${GREEN}$NPM_VER${NC}"

# ---- 3. 安装依赖 ----
echo -e "${YELLOW}[3/5] 📦 安装后端依赖...${NC}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend"

# 如果 node_modules 不存在或 package-lock.json 有更新，则重新安装
if [ ! -d "node_modules" ]; then
    echo "   ⏳ 首次运行，正在安装依赖..."
    npm install --loglevel=error
    echo -e "   ✅ 依赖安装完成"
else
    echo "   ✅ node_modules 已存在"
    # 检查是否需要更新
    if [ "package-lock.json" -nt "node_modules/.package-lock.json" ] 2>/dev/null; then
        echo "   ⏳ 检测到依赖变化，正在更新..."
        npm install --loglevel=error
        touch node_modules/.package-lock.json
        echo -e "   ✅ 依赖更新完成"
    else
        echo "   ✅ 依赖为最新状态，跳过安装"
    fi
fi

# 创建 data 目录（如果不存在）
mkdir -p ./data

# ---- 4. 检查前端文件 ----
echo -e "${YELLOW}[4/5] 📂 检查前端文件...${NC}"
FRONTEND_DIR="$SCRIPT_DIR/web/frontend"
if [ -f "$FRONTEND_DIR/index.html" ]; then
    echo -e "   ✅ 前端文件就绪"
    echo -e "   📁 路径: ${CYAN}$FRONTEND_DIR${NC}"
else
    echo -e "${RED}❌ 错误：未找到前端入口文件${NC}"
    echo "   📁 期望路径: $FRONTEND_DIR/index.html"
    exit 1
fi

# ---- 5. 清理旧进程 & 启动 ----
echo -e "${YELLOW}[5/5] 🚀 启动后端服务...${NC}"

# 检查端口 3000 是否被占用
if command -v lsof &> /dev/null; then
    if lsof -i :3000 -sTCP:LISTEN &>/dev/null 2>&1; then
        echo -e "   ${YELLOW}⚠️  端口 3000 已被占用，正在关闭旧进程...${NC}"
        OLD_PID=$(lsof -ti :3000 2>/dev/null)
        kill -9 $OLD_PID 2>/dev/null || true
        sleep 1
        echo -e "   ✅ 旧进程 (PID: $OLD_PID) 已关闭"
    fi
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🎉 服务启动成功！                        ║${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}║   📍 访问地址：                           ║${NC}"
echo -e "${GREEN}║   ${CYAN}http://localhost:3000${GREEN}                   ║${NC}"
echo -e "${GREEN}║                                          ║${NC}"
echo -e "${GREEN}║   ℹ️  按 ${YELLOW}Ctrl+C${GREEN} 停止服务              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""

# ---- 自动打开浏览器 ----
echo -e "${YELLOW}🌐 正在尝试自动打开浏览器...${NC}"
if command -v xdg-open &> /dev/null; then
    # Linux (图形界面)
    xdg-open http://localhost:3000 &
elif command -v open &> /dev/null; then
    # macOS
    open http://localhost:3000 &
elif command -v start &> /dev/null; then
    # Windows (Git Bash / WSL)
    start http://localhost:3000 &
else
    echo -e "   ${YELLOW}⚠️  未能自动打开浏览器，请手动访问 http://localhost:3000${NC}"
fi

echo ""
echo -e "${BLUE}📋 启动日志：${NC}"

# 启动后端（前台运行，方便 Ctrl+C）
exec node server.js
