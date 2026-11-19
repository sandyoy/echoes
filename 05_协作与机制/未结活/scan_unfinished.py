#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
未结活自检：扫 ~/.hermes/未结活/README.md
输出 = 空（正常静默） / 有内容（需要我立刻去干）
关键：报的时候必须报出"这一步该干什么"，不是只报"你超期了"。
"""
import re, pathlib, datetime

LEDGER = pathlib.Path.home() / ".hermes" / "未结活" / "README.md"

def parse_items(text):
    items = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^###\s+(\S+)\s*·\s*(.+)$", line.strip())
        if m:
            cur = {"id": m.group(1), "title": m.group(2).strip(),
                   "status": "", "assigned": "", "goal": "", "next": "", "log": []}
            items.append(cur)
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("- **状态**"):
            st = re.search(r"[（(]?([A-Z]+)", s.replace("**", ""))
            if st:
                cur["status"] = st.group(1)
        elif s.startswith("- **派活**"):
            cur["assigned"] = s.split("：")[-1].strip()
        elif s.startswith("- **【目标】**"):
            cur["goal"] = s.replace("- **【目标】**", "").strip()
        elif s.startswith("- **下一步**"):
            cur["next"] = s.replace("- **下一步**", "").strip()
        elif s.startswith("- 1") and ("-" in s):
            cur["log"].append(s)
    return items

def main():
    if not LEDGER.exists():
        print("⚠️ 未结活清单不存在：%s" % LEDGER)
        return
    text = LEDGER.read_text(encoding="utf-8")
    items = parse_items(text)
    opens = [i for i in items if i["status"] == "OPEN"]

    # 超期判断：看这条最后的日期（从"聊到哪"里取最大日期）
    today = datetime.date(2026, 11, 19)
    stale = []
    for it in opens:
        days = None
        dates = []
        for lg in it["log"]:
            m = re.match(r"- (\d{1,2})-(\d{1,2})", lg)
            if m:
                try:
                    dates.append(datetime.date(2026, int(m.group(1)), int(m.group(2))))
                except ValueError:
                    pass
        if dates:
            days = (today - max(dates)).days
        if days is None or days >= 1:
            stale.append((it, days))

    if not stale:
        return  # 静默

    print("【未结活 · 目标未达成】%d 件 OPEN，%d 件今天没推进：" % (len(opens), len(stale)))
    for it, days in stale:
        print("")
        print("▶ %s %s（%s）" % (it["id"], it["title"], ("%d天没动" % days) if days is not None else "未记录推进"))
        if it["goal"]:
            print("  目标：%s" % it["goal"][:120])
        print("  【现在就要做的这一步】%s" % (it["next"] or "⚠️ 没写下一步——先想清楚再动"))
    print("")
    print("规矩：目标没达成不许停、不许换下一件。干完把进展和日期写进那条底下。")

if __name__ == "__main__":
    main()
