#!/bin/bash
# 小鲸鱼 · 低频fetch刷新引用(独立于sync，避免阻塞)
# 只刷新 origin/main 引用，供 daily_sync.sh 的checkout读取最新
set -uo pipefail
cd ~/echoes
LOG="/tmp/daily_fetch.log"
echo "[$(date '+%m-%d %H:%M:%S')] 开始fetch" >> "$LOG"
# 用nohup后台执行fetch，父脚本绝不阻塞
nohup git fetch origin main --depth=20 --filter=blob:none >> "$LOG" 2>&1 &
echo "fetch已转入后台 PID=$!" >> "$LOG"
