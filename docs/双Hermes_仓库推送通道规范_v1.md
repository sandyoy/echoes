# 双Hermes · 仓库推送通道规范（标准版 v1，2026-08-09 定）

> 决策人：sandy。目标：从根上杜绝"双Hermes因仓库分叉产生问题"。
> 适用：云端小鲸鱼 🐳 + 本地小龙虾 🦞

## 一、核心原则

**GitHub 远程仓库 = 唯一真相源 + 可信全集。**
所有成果最终都要在远程 GitHub 上，且远程始终是"最新、最全"的那一份。任何一方的本地都不代表权威，GitHub 才是。

## 二、为什么不能再让"主工作区"承担 git 同步

云端主工作区（`~/echoes/.git`）因历史问题配置成不可靠状态（promisor），加 上**腾讯云→GitHub 大对象传输被物理限速**，导致：
- 在主工作区执行 `git pull / fetch / reset / checkout 新HEAD` → 反复卡死、超时
- 之前为此改用临时通道推送，但主工作区自己没跟进 → 远程前进、本地停老位置 → 看起来"分叉"

**结论：云端主工作区只当草稿区，不承担 git 同步/推送职责。**

## 三、标准推送通道（云端小鲸鱼专用，已验证100%成功）

云端推任何新产出，统一走 `/tmp/echoes_pub` 标准通道，**绝不直接在主工作区 push**：

```bash
# 1. 用干净克隆（对象完整，非 promisor）
mkdir -p /tmp/echoes_pub && cd /tmp/echoes_pub
git init -q -b main
git remote add origin git@github.com:sandyoy/echoes.git
git fetch --depth=1 origin main        # 可能因限速偶发失败，失败就等网络恢复再试，别硬刚
git checkout -q -b main origin/main

# 2. 只复制"要推的新/改文件"进来（主工作区或备份区的内容）
cp /home/ubuntu/echoes/docs/xxx.md /tmp/echoes_pub/docs/xxx.md

# 3. push
git add <文件>
git commit -q -m "说明"
git push origin main

# 4. 自验（必做4步）
git ls-tree -r origin/main --name-only | grep 文件名   # 文件在远程
# 内容非空、更新日志已追加、通知sandy
```

**关键规定：**
- 每次 push 前先 `git fetch --depth=1 origin main` 拿到远程最新，在最新基础上 push（**绝不覆盖别人**）
- fetch 失败（限速）→ **等网络窗口**，不要反复硬试，也不要跳过 fetch 直接 push
- 推送用 `--depth=1` 浅克隆即可（轻量、够 push 用）

## 四、主工作区（~/echoes）定位

- `~/echoes/` 仍是"我要工作的草稿区"：写文档、改代码、暂存产出
- **不在主工作区做 `git pull / reset / fetch / push`** 这类会大量读对象的操作
- 要推的产出，从主工作区复制到 `/tmp/echoes_pub` 走标准通道
- 主工作区里的密钥（如 `backend/.env`）**永不 push**

## 五、本地小龙虾 🦞 职责

- 小龙虾（本地PC）能正常 git pull/push（本地到GitHub无限速问题），**继续在本地正常拉取/推送**
- 小龙虾推完任何新文件，**在 `更新日志.md` 追加一条**（原有机制不变）
- 云端小鲸鱼通过每日定时同步（cron 8:00/20:00）用标准通道的 fetch 拿最新清单，结合本地 on-demand 抓取补齐内容

## 六、每日同步（云端侧）

- 每天的自动同步 cron **继续用现有的 `~/scripts/git_auto_sync.sh`**（拉文件清单 + 下载新增/文本文件），不走主工作区 git
- 需要推送新产出时，手动走 `/tmp/echoes_pub` 标准通道

## 七、错误处理

| 症状 | 处理 |
|------|------|
| fetch/push 卡死或静默假成功 | 等网络窗口（GitHub连通性波动是间断的），或换时间再试；不硬刚、不跳过 |
| 远程出现我没见过的新提交 | 先 `git ls-remote origin HEAD` 看真实HEAD，再决定，不擅自 reset |
| 需要删/改已推送文件 | 通过 /tmp 通道重新 push 覆盖版，避免直接动旧历史 |

## 八、本次落地动作（sandy 已授权方案A）

1. ✅ 建立标准通道 `/tmp/echoes_pub`（本文件所在仓库的推送载体）
2. ✅ 明确主工作区只当草稿、不碰 git
3. 🔄 速查卡、认知文档等新产出待网络窗口经 /tmp 通道推送
4. 🔄 本规范文档亦随下次推送同步给小龙虾
