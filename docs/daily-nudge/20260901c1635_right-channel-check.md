# 盯办明细 2026-09-01 16:35 (cron,1635轮)

## Echoes内测版盯办 + P0恢复对话通道

### 内测交付物状态
- **v5预览码已交付**：`docs/往事可追忆_内测预览二维码_v5_前端重写_20260901.png`（commit `0af7a7e` 14:09 小龙虾完成P0#1，含sandy 7f06847前端重写+295行，编译62.9KB>v4的59.6KB）。
- 15:00已做交付终报。ball在sandy扫码回归新前端（重点：自述录音ASR转文字 / 采访AI问答存回忆 / 统一时间轴；务必清缓存防扫旧码）。

### 新P0：恢复与sandy的微信对话通道（归我做）
- 小龙虾 15:35 发 P0 任务卡：sandy 微信唤不醒我（Open cloud 未连入），命令我恢复。
- **已认领 + 诊断**（agent.log铁证）：09-01 全天 ~19 次 `Connected to wss://openws.work.weixin.qq.com → 随即 Disconnected`（几百ms内）。
- 判定根因：**WeCom 应用侧 bot 订阅(subscription)/回调鉴权失效**（08-29 同源 `errcode 846609: aibot websocket not subscribed`）。网关每30min自动重连但 auth 每次被拒，本地进程重启大概率复现同一失败。
- **行动**：①认领+诊断写回 coop_task；②触发 gateway 进程重启（systemd on-failure 保拉起）尝试重新订阅握手；③若重启后仍"连上即断开"=订阅已在应用侧失效，需微信开放平台/企业微信后台重新绑定订阅（可能需人工/manual）。

### 今日已报sandy次数
- 本轮为当日首报（c1计），报一次【v5交付 + 对话通道P0诊断】组合状态。

### 下一步
- 重启后查 agent.log 是否出现 Reconnected 且不再 Disconnected。
- sandy：扫 v5 码回归新前端 + 留意对话通道恢复信号。
- 若订阅在应用侧失效，准备人工刷新订阅/重绑定。
