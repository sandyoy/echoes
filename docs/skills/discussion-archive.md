---
name: discussion-archive
description: "存档每轮讨论：按日期写日记到 docs/daily/，更新 INDEX.md，更新 memory 索引。每次聊完自动执行。"
---

# Discussion Archive（讨论存档技能）

每次与用户讨论结束时自动执行存档流程。
本规则由本地 Hermes 🦞 制定，云端小鲸鱼 🐳 共用。

---

## 触发条件

对话末尾，用户表示"没了"/"先这样"/"没了就存档吧"等确认结束的信号时执行。

## 执行步骤

### 第一步：收集本轮话题信息

从本轮对话中提取：
- 所有讨论过的话题
- 每个话题的：背景、讨论过程、决策、待办
- 新发现的用户偏好/习惯/决策风格

### 第二步：写日记文件

路径：`docs/daily/YYYY-MM-DD-session-N.md`

格式：
```
# 讨论记录
> 日期：YYYY-MM-DD
> 轮次：session-N

## 话题一：XXX
**背景：**
**讨论过程：**
**决策：**
**待办：**

## 新发现的用户偏好
...

## 待办事项
- [ ]
```

session 编号规则：同一天多轮对话按 1, 2, 3 递增。

### 第三步：更新 INDEX.md

路径：`docs/daily/INDEX.md`

追加一行表格记录：
```
YYYY-MM-DD | 话题1、话题2 | YYYY-MM-DD-session-N.md
```

### 第四步：更新 memory

用 `memory(action='add', target='memory')` 存一条索引：
```
讨论记录索引见 docs/daily/INDEX.md
```

如果这条已存在则跳过。

### 第五步：推送变更

```bash
git add docs/daily/
git commit -m "📝 讨论记录 YYYY-MM-DD session-N"
git push
```

## 注意事项

- 日记内容要完整，不要压缩成摘要——保留讨论细节和上下文
- 多话题跳跃时不要拆分，按时间顺序完整记录在一个文件里
- 用户偏好直接存入 memory（user 目标），不要只写在文档里
- 如果 git push 因网络问题失败，记下来下次再推
- 用户有两个项目：Echoes（往日可追忆）和体验点（社区健康体验点），日记中要区分标注
