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
