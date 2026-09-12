#!/bin/bash
# ============================================================
# 小鲸鱼 · 智能知识库同步：先拉文本类核心文件
# ============================================================
set -uo pipefail

cd ~/echoes
REPO="sandyoy/echoes"
BRANCH="main"
REDIR="https://raw.githubusercontent.com/$REPO/$BRANCH"

# 已存在则跳过（避免重复下载）
SYNCED=0
SKIPPED=0
FAILED=0

while IFS= read -r relpath; do
  # 只处理文本类小文件
  case "$relpath" in
    *.md|*.py|*.js|*.json|*.wxml|*.wxss|*.txt|*.sh|*.css|*.html|*.svg|*.yaml|*.yml|*.csv)
      ;;
    *) continue ;;
  esac

  # 目标路径
  local_path="$relpath"
  if [ -f "$local_path" ]; then
    # 已存在，跳过
    SKIPPED=$((SKIPPED+1))
    continue
  fi

  # 从 raw CDN 下载
  url="$REDIR/$relpath"
  # URL 编码中文路径
  url_encoded=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1] if not sys.argv[1].startswith('/') else sys.argv[1][1:], safe='/'))" "$relpath")
  url_full="https://raw.githubusercontent.com/$REPO/$BRANCH/$url_encoded"

  if mkdir -p "$(dirname "$local_path")" 2>/dev/null && curl -s --max-time 40 -o "$local_path" "$url_full"; then
    if [ -s "$local_path" ]; then
      SYNCED=$((SYNCED+1))
      echo "✓ $relpath"
    else
      rm -f "$local_path"
      FAILED=$((FAILED+1))
    fi
  else
    FAILED=$((FAILED+1))
  fi
done < /tmp/echoes_remote_files.txt

echo ""
echo "======== 同步完成 ========"
echo "✅ 新增: $SYNCED"
echo "⏭️  已存在跳过: $SKIPPED"
echo "❌ 失败: $FAILED"
