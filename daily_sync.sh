#!/bin/bash
# 小鲸鱼 · 每日双向同步 v5 —— 纯git checkout版(绝对稳定)
# 只做本地秒回操作: git checkout origin/main -- 单文件
# 注意: 依赖 origin/main 引用是最新的(需定期fetch刷新,见 daily_fetch.sh)
set -uo pipefail
cd ~/echoes
LOG="/tmp/daily_sync.log"

declare -a FILES=(
  "TASK_BOARD.md"
  "docs/小龙虾给小鲸鱼的工作衔接说明.md"
  "docs/双Agent文件路径统一规范.md"
)
OK=0; FAIL=0
for p in "${FILES[@]}"; do
  if git cat-file -e "origin/main:$p" 2>/dev/null; then
    git checkout "origin/main" -- "$p" 2>/dev/null && OK=$((OK+1))
  else
    FAIL=$((FAIL+1))
  fi
done
echo "[$(date '+%m-%d %H:%M')] 同步 成功$OK/失败$FAIL" >> "$LOG"
