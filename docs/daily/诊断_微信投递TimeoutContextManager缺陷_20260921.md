# 诊断：微信投递「Timeout context manager should be used inside a task」长期静默丢消息缺陷

- **日期**：2026-09-21 23:2x
- **发现者**：小龙虾（本地 Hermes），job `8b1ab5e9bb61`（自愈-避峰）
- **触发来源**：兄弟 job `8b1ab5e9bb61` 于 23:10 的自检报告（原报告列在 `~/.hermes/cron/output/8b1ab5e9bb61/2026-09-21_23-10-16.md`），把该错误列为"疑似网络抖动"。本轮**推翻该定性**，查实为**确凿的代码层缺陷**。
- **处置**：仅诊断 + 上报。**未修改任何生产代码、未重启 gateway**（理由见 §5）。

---

## 1. 现象

投递到 sandy 微信（chat_id `o9cq803D`）时，日志反复出现：

```
ERROR gateway.platforms.weixin: [Weixin] send failed to=o9cq803D: Timeout context manager should be used inside a task
```

伴随 3 次重试全败：

```
WARNING ... send chunk failed to=o9cq803D attempt=1/3, retrying in 1.00s: Timeout context manager should be used inside a task
WARNING ... send chunk failed to=o9cq803D attempt=2/3, retrying in 2.00s: Timeout context manager should be used inside a task
ERROR   ... send failed  to=o9cq803D: Timeout context manager should be used inside a task
```

## 2. 关键证据：不是瞬时抖动，而是跨 3 个月复发

对 `~/.hermes/logs/*.log` 全量 grep 该错误串，命中时间点（按日归并）：

| 日期 | 说明 |
|---|---|
| 2026-06-10 23:10 | 首次出现（紧跟在 `iLink sendmessage error: ret=-2` 之后） |
| 2026-06-11 00:13 / 00:44 / 00:46 | 同簇反复 |
| 2026-06-24 12:56 / 13:29 / 13:40 / 15:09 / 15:24 | 一日内多簇 |
| …（中间多日） | |
| 2026-09-16 17:06 | |
| 2026-09-17 14:15 | chunk 1/3、2/3、send failed 三连 |
| 2026-09-19 01:55 | 三连 |
| 2026-09-21 21:06 | 三连 |

- 跨 **3 个多月**、**多日、多簇**复发 —— 排除"网络抖动"的一次性解释。
- 收件人**恒为 `o9cq803D`**（即 sandy）。
- 每次复发都造成**一条消息静默丢失**。

## 3. 触发链（逐行勘 code）

以 2026-09-21 21:06 这一簇为例（`gateway.log` 行 19815–19821）：

```
21:06:04 WARNING send chunk failed ... Cannot connect to host ilinkai.weixin.qq.com:443 ssl:default [nodename nor servname provided, or not known]
21:06:05 WARNING send chunk failed ... （同上，DNS 失败）
21:06:07 ERROR   send failed ...            （DNS 失败，3 次全败）
21:06:08 INFO    weixin: restored 1 context token(s) for 39a0e315    ← 触发重连/重建会话
21:06:08 WARNING send chunk failed ... Timeout context manager should be used inside a task   ← 新的、不可恢复的错误
21:06:11 ERROR   send failed ...            Timeout context manager should be used inside a task
```

**因果链**：

1. 先发生一次 **DNS 连接失败**（`Cannot connect to host ilinkai.weixin.qq.com:443`）。
2. 该失败触发 weixin 适配器的**重连分支**：`gateway/platforms/weixin.py:1205-1207` 重新创建 `_poll_session` / `_send_session`（`aiohttp.ClientSession(...)`），并
   `self._token_store.restore(self._account_id)`（日志中即 `restored 1 context token(s)`）。
3. 紧接着，**下一次发送**就报 `Timeout context manager should be used inside a task` —— 即**重建后的 aiohttp 会话超时上下文无法在其被使用的事件循环 Task 中找到**。
4. `_send_text_chunk`（`weixin.py:1485`）的 3 次重试打在**同一个已损坏的 session 对象**上 → 3 次全败（错误串完全一致，非超时、非网络）。
5. **微信通道自此持续静默丢消息，直到 gateway 被重启**。

## 4. 可疑引入点

上游 commit **`5ca52bae5b` — `fix(gateway/weixin): split poll/send sessions, reuse live adapter for cron & send_message`**。

该 commit 让 `send_message` 的一次性助手**复用活适配器**（`weixin.py:1983-1989`）：

```python
live_adapter = _LIVE_ADAPTERS.get(resolved_token)
send_session = getattr(live_adapter, '_send_session', None)
if live_adapter is not None and send_session is not None and not send_session.closed:
    ...
    last_result = await live_adapter.send(chat_id, cleaned)   # ← 直接调用活适配器
```

- 该路径**绕过**了适配器自身的 `_send_lock` 与 session 守卫。
- 当它与**重连过程中的 session 重建**并发时，即触发本错误。
- 兼容性旁证：`cron/scheduler.py:412-434` 的 live-adapter 路径同样通过
  `asyncio.run_coroutine_threadsafe(runtime_adapter.send(...), loop)` 复用活适配器 —— 这正是 cron 投递受此 bug 牵连的原因。

## 5. 为什么不自修（依铁律 0-C + 四点七第 3 条权衡）

| 维度 | 判断 |
|---|---|
| 文件归属 | `~/.hermes/hermes-agent/` 是**上游第三方代码**（`git remote` = gitcode.com/hermes-agent；本地 `main` 落后 `origin/main` **15906** commits）。改它 = 维护分叉。 |
| 生效条件 | 修改后需**重启生产 gateway** 才生效 —— 即本会话早前已明确判为**越权**的高影响动作（铁律 0-C：危险动作不得自主执行）。 |
| 失败代价 | gateway 是 sandy **唯一**的微信消息通道；错改会**彻底打断通道**。 |
| 铁律 0-C | "改配置/动生产服务"属危险动作 → **只记录 + 上报**。 |

→ 结论：**不自修，只给修复方向供 sandy 拍板。**

## 6. 建议的最小修复方向（待 sandy 决策）

三选一，风险由低到高：

1. **最快止血（无代码改动）**：发现微信投递失败时**重启 gateway** 即可临时恢复（本错误在 gateway 进程生命周期内不可自愈）。
2. **首选代码修复（小、稳）**：让 `send_message` 一次性助手**不再复用活适配器的 `_send_session`**，而是**始终走 `weixin.py:2010` 的独立 `async with aiohttp.ClientSession(...)` 分支**（该分支在自己的 Task/事件循环内创建并使用 session，不存在跨 Task 超时上下文问题）。即把 1983-1989 的"复用活适配器"快路径降级为"仅当适配器空闲/无重连时使用"，或直接移除。
3. **加固重试**：`_send_text_chunk`(1485) 的重试在遇到 `Timeout context manager should be used inside a task` 这类**会话级损坏**错误时，应**先重建 session 再重试**，而非在原损坏 session 上重试（当前正是"3 次打在坏 session 上"导致全败）。

> 无论选哪条，**都建议先在一个隔离环境（非生产 gateway）验证**，再决定是否重启生产 gateway 上线。
