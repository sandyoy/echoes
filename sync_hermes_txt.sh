#!/bin/bash
# ============================================================
# 小鲸鱼 · 每日文本层同步脚本（与小龙虾互通免重复）
# 核心：只同步"互通必需"的文本小文件(能从raw CDN下载)，绕开大文件卡死
# 用法：直接运行，或设cron：0 8,20 * * * bash /home/ubuntu/echoes/sync_hermes_txt.sh
# ============================================================
set -uo pipefail
cd ~/echoes
REPO="sandyoy/echoes"; BRANCH="main"
REDIR="https://raw.githubusercontent.com/$REPO/$BRANCH"
LOG="/tmp/hermes_txt_sync.log"

# 1. 先尝试 git fetch（能fetch到就用git方式，更完整）
echo "===== 文本层同步 $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"
timeout 60 git fetch origin main 2>/dev/null && echo "git fetch OK" >> "$LOG" || echo "git fetch 超时/失败，改raw单文件拉" >> "$LOG"

# 2. 核心互通枢纽文件清单（固定路径，raw CDN逐个拉）
#    只包括必须互通的小文件：任务板、衔接文档、规范、项目简介、README
declare -a FILES=(
  "TASK_BOARD.md"
  "README.md"
  "docs/小龙虾给小鲸鱼的工作衔接说明.md"
  "docs/双Agent文件路径统一规范.md"
  "docs/投标合作铁律_给小鲸鱼_2026-08-03.md"
  "wiki/medical/更新日志.md"
)

OK=0; FAIL=0
for p in "${FILES[@]}"; do
  enc=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe='/'))" "$p")
  url="$REDIR/$enc"
  # 下载到临时，成功后覆盖（避免半截文件）
  if timeout 30 curl -s --max-time 25 -o "/tmp/_sync_tmp" "$url" && [ -s "/tmp/_sync_tmp" ]; then
    mkdir -p "$(dirname "$p")"
    cp "/tmp/_sync_tmp" "$p"
    OK=$((OK+1)); echo "✓ 已更新: $p" >> "$LOG"
  else
    FAIL=$((FAIL+1)); echo "✗ 失败: $p" >> "$LOG"
  fi
done
rm -f /tmp/_sync_tmp

echo "完成: 成功$OK / 失败$FAIL" >> "$LOG"
