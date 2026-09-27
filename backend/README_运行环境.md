# backend 运行环境说明（2026-09-26 实测）

## 能跑的解释器：`/usr/bin/python3`（Python 3.12.3）

```bash
cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_story_clip_perm.py
```

## 踩过的坑（下次直接用，别重踩）

| 现象 | 原因 | 正确做法 |
|---|---|---|
| `ModuleNotFoundError: No module named 'sqlalchemy'` | repo 里的 `.venv/` 是**空壳**：没装 pip、没装 sqlalchemy，只有 requests/tencentcloud | **不要用 `.venv/bin/python`** 跑后端 |
| 同上 | 默认 `python3` 指向 hermes 自带的 3.11 venv，也没有 sqlalchemy | 用 `/usr/bin/python3` |
| `pip3 install` 报 "not writeable" | 系统级 pip 被锁 | SQLAlchemy 2.0.54 其实**已装**在 `/home/ubuntu/.local/lib/python3.12/site-packages`，`/usr/bin/python3` 能直接 import |

## 结论
- 后端自测统一用 `/usr/bin/python3`，无需装任何东西。
- `.venv/` 目前是废的，**没有修的必要**（或后续统一改造再修）。

## 后端写代码时踩过的坑（2026-09-27 补）

| 现象 | 原因 | 正确做法 |
|---|---|---|
| `ValueError: 故事不存在：story_xxx`，明明刚 `db.add(s9)` | `register_claim` 会回查故事是否真在库里，但 `add` 后**没 commit** 还在会话内存里 | 造完 Story **先 `db.commit()`**，再登记/挂素材 |
| `owners` 第二次登录只返回新认领的那本，首页漏书 | 用「本次新认领的行」拼 owners，丢了历史 | owners 要**全量重查**（`Member.user_id==` + `Claim.claimed_user_id==`），不是增量 |
| SQLAlchemy 语义错乱/静默错误 | `.where()` 里塞 `A == x if cond else B == y`（三元优先级坑） | 先拼好条件元组再 `where(*cond)` |
| 同一人的手机号认不上 | 写法不一（`+86` / 横线 / 全角数字） | 认领钥匙一律走 `permissions._normalize_phone()` |
