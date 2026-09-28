#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""
跨篇重复检测（跨周同渠道）

用途：每篇稿写完，自动跟上两周同渠道的稿比一次，>30% 退回重写。
要点：先剥掉模板段（配图脚本/配色/清单/内部备注），只比正文——避免假警报。

用法：
    python3.12 scripts/check_cross_dup.py                     # 全量检测
    python3.12 scripts/check_cross_dup.py <目录>              # 检测指定交付包目录
    python3.12 scripts/check_cross_dup.py --file <文件路径>    # 只测一个文件（跟历史比）

退出码：0=通过，1=有超阈值项
"""
import os
import sys
import re
import difflib
import itertools

BASE = "/home/ubuntu/echoes/docs/GEO/内容成稿"
THRESHOLD = 0.30

# 模板段起始标记 —— 这些之后的内容全部剥掉（是给同事的操作模板，不属正文）
TEMPLATE_MARKERS = [
    "配图脚本",
    "【内部备注",
    "【提交前必须确认",
    "——————————————————————————————\n配图",
    "配图与发布说明",
    "发布检查清单",
    "配色与风格规范",
    "排版建议",
]

# 剥掉顶部的发布说明块
TOP_MARKERS = ["【发布前必读", "【提交前必须确认", "【内部"]


def strip_template(t: str) -> str:
    """剥掉模板段，只留正文"""
    # 砍掉模板标记之后的全部
    cut = len(t)
    for m in TEMPLATE_MARKERS:
        i = t.find(m)
        if 0 < i < cut:
            cut = i
    t = t[:cut]

    # 剥顶部说明块
    for m in TOP_MARKERS:
        if t.lstrip().startswith(m):
            j = t.find("】")
            if j > 0:
                k = t.find("\n\n", j)
                if k > 0:
                    t = t[k:]
            break

    # 去掉分隔线、免责声明、互动引导
    t = re.sub(r"[—\-]{3,}", "", t)
    t = re.sub(r"（以上内容仅为个人行业观察[^）]*）", "", t)
    t = re.sub(r"【互动引导】.*", "", t, flags=re.S)
    t = re.sub(r"（⚠️.*?）", "", t, flags=re.S)
    return t.strip()


def channel_key(filename: str) -> str:
    """从文件名提取渠道标识（用于同渠道分组）"""
    n = filename.replace(".txt", "").replace(".docx", "")
    # 取第一个下划线前的部分
    return n.split("_")[0]


def collect(dirpath: str):
    """收集目录下的成稿（只收 ①_渠道成稿 里的 txt）"""
    out = {}
    for root, dirs, files in os.walk(dirpath):
        if "_成稿Word" in root or "__pycache__" in root:
            continue
        for f in files:
            if not f.endswith(".txt"):
                continue
            p = os.path.join(root, f)
            try:
                raw = open(p, encoding="utf-8").read()
            except Exception:
                continue
            body = strip_template(raw)
            if len(body) < 150:      # 太短的跳过（不是正文）
                continue
            out[p] = body
    return out


def week_tag(path: str) -> str:
    """从路径里提取周次"""
    m = re.search(r"(第[一二三四五六七八九十\d]+周)", path)
    return m.group(1) if m else "?"


def main():
    args = sys.argv[1:]

    # 单文件模式
    if args and args[0] == "--file":
        target = args[1]
        body = strip_template(open(target, encoding="utf-8").read())
        ch = channel_key(os.path.basename(target))
        pool = {p: b for p, b in collect(BASE).items() if channel_key(os.path.basename(p)) == ch and p != target}
        print(f"检测：{os.path.basename(target)}（渠道 {ch}，对比 {len(pool)} 篇历史稿）")
        bad = compare_one(target, body, pool)
        return 1 if bad else 0

    # 目录/全量模式
    target_dir = args[0] if args else BASE
    files = collect(target_dir)
    print(f"收集到 {len(files)} 篇成稿（已剥模板），阈值 {THRESHOLD:.0%}\n")

    # 按渠道分组
    groups = {}
    for p, b in files.items():
        groups.setdefault(channel_key(os.path.basename(p)), []).append(p)

    problems = 0
    for ch, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        # 只比 不同周 之间，或同周不同篇（医院稿要骨架不同）
        for a, b in itertools.combinations(sorted(paths), 2):
            r = difflib.SequenceMatcher(None, files[a], files[b]).ratio()
            if r >= THRESHOLD:
                problems += 1
                wa, wb = week_tag(a), week_tag(b)
                same_week = (wa == wb)
                label = "同周不同篇" if same_week else "跨周"
                print(f"⚠️ [{ch}] {label} {r:.1%}")
                print(f"     A: {os.path.basename(a)}  ({wa})")
                print(f"     B: {os.path.basename(b)}  ({wb})")
                # 给出最长共同段，方便定位
                sm = difflib.SequenceMatcher(None, files[a], files[b])
                blocks = sorted(sm.get_matching_blocks(), key=lambda x: -x.size)
                for blk in blocks[:2]:
                    if blk.size >= 30:
                        print(f"     共同段({blk.size}字): {files[a][blk.a:blk.a+min(blk.size,70)]}...")
                print()

    if problems == 0:
        print("✅ 全部通过，无超阈值项")
    else:
        print(f"❌ 共 {problems} 项超阈值，需退回重写")

    return 1 if problems else 0


def compare_one(target, body, pool):
    bad = False
    for p, b in pool.items():
        r = difflib.SequenceMatcher(None, body, b).ratio()
        if r >= THRESHOLD:
            bad = True
            print(f"⚠️ {r:.1%} vs {os.path.basename(p)}")
        else:
            print(f"✅ {r:.1%} vs {os.path.basename(p)}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
