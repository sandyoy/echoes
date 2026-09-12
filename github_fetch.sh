#!/bin/bash
# ============================================================
# 小鲸鱼 · GitHub 按需拉取同步脚本
# 替代会超时的 git pull --all
# 用法：bash ~/echoes/github_fetch.sh
# 原理：用 GitHub API 拿文件清单，用 raw CDN 逐个拉取未同步的文件
#       文本/小文件走 raw CDN（通），大文件(>1MB)单独标记，按需拉
# ============================================================
set -uo pipefail

cd ~/echoes
REPO="sandyoy/echoes"
BRANCH="main"
# 本地记录已同步文件清单的位置
SYNC_MANIFEST="/tmp/echoes_synced_manifest.txt"
: > "$SYNC_MANIFEST"

echo "🔍 获取远程文件清单 ($REPO/$BRANCH) ..."

# 用 GitHub API 递归拿到完整文件树
TREE_JSON=$(curl -s --max-time 60 "https://api.github.com/repos/$REPO/git/trees/$BRANCH?recursive=1")

# 提取文件路径列表（jq 若可用，否则 fallback）
if command -v jq >/dev/null 2>&1; then
  echo "$TREE_JSON" | jq -r '.tree[] | select(.type=="blob") | .path'
else
  echo "⚠️ 未安装 jq，改用 python 解析"
  echo "$TREE_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for t in data.get('tree', []):
        if t.get('type') == 'blob':
            print(t['path'])
except Exception as e:
    sys.stderr.write(f'解析失败: {e}\n')
"
fi > /tmp/echoes_remote_files.txt

TOTAL=$(wc -l < /tmp/echoes_remote_files.txt)
echo "📦 远程共有 $TOTAL 个文件"

# 顺便输出文件清单供小鲸鱼查看/分析
echo "=== 远程文件清单(按目录统计) ==="
awk -F/ '{print $1}' /tmp/echoes_remote_files.txt | sort | uniq -c | sort -rn | head -20

echo "✅ 清单获取完成: /tmp/echoes_remote_files.txt"
