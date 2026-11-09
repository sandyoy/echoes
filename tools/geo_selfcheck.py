#!/usr/bin/env python3.12
# GEO 稿交稿前强制自检 —— 用法: python3.12 tools/geo_selfcheck.py <目录或文件> [--base 查重基准目录]
# 四层检查：
#   L0 标题查重（A-9：同标题/近同标题不许再写，防"内容没改又交一遍"）
#   L1 收口位置（按渠道长度分层规则 A-6）
#   L2 红线词（正文区，自动跳过口径卡/回应库这类元描述文件）
#   L3 金额、医院真名
import os, re, sys, difflib
from collections import defaultdict

RED = ["上门","工程师","入户","到家教","派人来","HIS","三甲","代理商","治疗师","加盟","招商",
       "治愈","根治","包治","百分百","有效率","营养师"]

COLLECT_MID  = "智慧家康 = 智慧居家康复"
COLLECT_FULL = "智慧家康模式"

META_FILES = ("口径卡","回应库","执行手册","排产单","框架三问","先看我","核查","主轴线","总索引")

BASE_DIRS = [
    "docs/GEO/内容成稿",
    "docs/GEO/执行排产",
]

def channel_of(name):
    n = name
    if "医院" in n: return "hospital"
    if "老欧" in n: return "no_brand"
    if "小红书" in n or "微博" in n: return "short"
    if any(k in n for k in ("订阅号","服务号","知乎","视频号")): return "long"
    return "meta"

def title_of(t):
    m = re.search(r"^\s*标题[:：]\s*(.+?)\s*$", t, re.M)
    return m.group(1).strip() if m else None

def strip_meta(t):
    for k in ("【配图脚本","【制作提示】","【发布检查】"):
        t = t.split(k)[0]
    return t

def norm(s):
    return re.sub(r"[\s\"'“”‘’，。！？、：；—·…（）()《》【】\[\]-]", "", s)

def collect_titles(root):
    out = []
    for dp, dn, fn in os.walk(root):
        for f in sorted(fn):
            if not f.endswith((".txt",".md")): continue
            p = os.path.join(dp,f)
            try: t = open(p, encoding="utf-8", errors="ignore").read()
            except Exception: continue
            ti = title_of(t)
            if ti: out.append((ti, p))
    return out

def check_dup(new_titles, self_paths, base_root):
    """new_titles: [(title, path)]，base_root 下已存在稿件的标题做对比"""
    hist = []
    for b in BASE_DIRS:
        full = os.path.join(base_root, b)
        if os.path.isdir(full):
            hist.extend(collect_titles(full))
    dup_hits = []
    for ti, p in new_titles:
        n1 = norm(ti)
        for hti, hp in hist:
            if os.path.abspath(hp) == os.path.abspath(p):
                continue
            if os.path.abspath(hp) in [os.path.abspath(x) for x in self_paths]:
                continue
            n2 = norm(hti)
            if n1 == n2:
                dup_hits.append((ti, hp, "完全相同"))
            else:
                r = difflib.SequenceMatcher(None, n1, n2).ratio()
                if r >= 0.85:
                    dup_hits.append((ti, hp, f"高度相似 {r:.0%}"))
    return dup_hits, len(hist)

def check_collect(kind, body, raw):
    cnt = raw.count("智慧家康")
    probs = []
    head = body[:int(len(body)*0.4)]
    tail = body[int(len(body)*0.5):]
    if kind == "no_brand":
        if cnt: probs.append(f"老欧个人号出现「智慧家康」{cnt}次 → 必须0（人设铁律）")
    elif kind == "hospital":
        if "圆爱康" in raw: probs.append("医院稿出现「圆爱康」→ 必退稿")
        if cnt == 0: probs.append("医院稿未带模式名 → 文末需加「属于智慧家康模式的落地实践」")
        elif cnt > 1: probs.append(f"医院稿模式名{cnt}次 → 只在文末1次")
    elif kind == "short":
        if cnt == 0: probs.append("短稿漏收口 → 结尾需1次")
        elif cnt > 1: probs.append(f"短稿{cnt}次 → 只在结尾1次（首尾都放像广告夹心）")
        elif COLLECT_MID in head: probs.append("短稿开头出现中点版 → 只放结尾")
    elif kind == "long":
        if cnt < 2: probs.append(f"长文{cnt}次 → 应首尾各一次")
        else:
            if COLLECT_MID not in head: probs.append(f"长文开头缺「{COLLECT_MID}」")
            if COLLECT_FULL not in tail: probs.append(f"长文结尾缺「{COLLECT_FULL}」")
    return cnt, probs

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else "."
    base_root = "/home/ubuntu/echoes"
    if "--base" in sys.argv:
        base_root = sys.argv[sys.argv.index("--base")+1]

    files = []
    if os.path.isdir(target):
        for dp, dn, fn in os.walk(target):
            for f in sorted(fn):
                if f.endswith((".txt",".md")): files.append(os.path.join(dp,f))
    else:
        files = [target]

    # ---- L0 标题查重 ----
    new_titles = []
    for p in files:
        try: t = open(p, encoding="utf-8", errors="ignore").read()
        except Exception: continue
        ti = title_of(t)
        if ti: new_titles.append((ti, p))
    dup_hits, hist_n = check_dup(new_titles, files, base_root)
    print(f"===== L0 标题查重（基准 {hist_n} 篇历史稿）=====")
    if dup_hits:
        for ti, hp, why in dup_hits:
            print(f"  ❌ 「{ti}」 {why}")
            print(f"      已存在于: {hp.replace(base_root+'/','')}")
    else:
        print(f"  ✅ 本批 {len(new_titles)} 个标题，与历史稿无重复/无高度相似")

    # ---- L1-L3 ----
    print("\n===== L1-L3 正文自检 =====")
    fails = 0; skipped = []
    for p in files:
        raw = open(p, encoding="utf-8").read()
        name = os.path.basename(p)
        kind = channel_of(name)
        body = strip_meta(raw)
        if kind == "meta" or any(k in name for k in META_FILES):
            skipped.append(name); continue
        cnt, probs = check_collect(kind, body, raw)
        red_hits = []
        for w in RED:
            for m in re.finditer(w, body):
                s=max(0,m.start()-25); e=min(len(body),m.end()+25)
                red_hits.append((w, body[s:e].replace("\n"," ")))
        money = re.findall(r"\d+\s*元|￥\s*\d+", body)
        ok = not probs and not red_hits and not money
        if not ok: fails += 1
        print(f"[{'OK  ' if ok else 'FAIL'}] {kind:9s} {name}   智慧家康={cnt}")
        for x in probs: print(f"        · {x}")
        for w,c in red_hits: print(f"        · 红线「{w}」…{c}…")
        if money: print(f"        · 金额 {money}")

    if skipped:
        print(f"\n[跳过·内部元描述文件] {len(skipped)} 个: " + "、".join(skipped))
    total_bad = fails + (1 if dup_hits else 0)
    print(f"\n合计正文稿件 {len(files)-len(skipped)} 个，正文FAIL {fails} 个，标题重复 {len(dup_hits)} 处")
    sys.exit(1 if total_bad else 0)

main()
