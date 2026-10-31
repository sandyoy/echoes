#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""
知乎真实问题采集器
用法：python3.12 zhihu_question_scraper.py 关键词1 关键词2 ...
输出：/home/ubuntu/echoes/docs/GEO/问答/捡问题_<关键词>.json
原理：知乎站内搜索 403，改用搜狗 site:zhihu.com/question + 关键词，
      从结果页提取 question ID → 拼出 https://www.zhihu.com/question/<id>
      → 用 oembed 接口取真实标题（无需登录）。
"""
import sys, re, json, time, urllib.parse, subprocess, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUT = "/home/ubuntu/echoes/docs/GEO/问答"
os.makedirs(OUT, exist_ok=True)


def curl(url, timeout=25):
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", str(timeout), "-A", UA,
             "-H", "Accept-Language: zh-CN,zh;q=0.9", url],
            capture_output=True, text=True, errors="ignore")
        return r.stdout or ""
    except Exception:
        return ""


def sogou_ids(kw, pages=2):
    ids = []
    for p in range(pages):
        q = urllib.parse.quote(f"site:zhihu.com/question {kw}")
        url = f"https://www.sogou.com/web?query={q}" + (f"&page={p+1}" if p else "")
        h = curl(url)
        ids += re.findall(r"zhihu\.com/question/(\d+)", h)
        time.sleep(1.5)
    # 去重保序
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def title_of(qid):
    """oembed 取标题，免登录"""
    u = f"https://www.zhihu.com/api/v4/questions/{qid}/oembed?format=json"
    t = curl(u, timeout=12)
    try:
        d = json.loads(t)
        return (d.get("title") or "").strip()
    except Exception:
        return ""


def main():
    kws = sys.argv[1:]
    if not kws:
        print("用法: python3.12 zhihu_question_scraper.py 关键词...")
        return
    all_res = {}
    for kw in kws:
        ids = sogou_ids(kw)
        rows = []
        for qid in ids:
            ti = title_of(qid)
            rows.append({"qid": qid, "title": ti,
                         "url": f"https://www.zhihu.com/question/{qid}",
                         "kw": kw})
            if ti:
                print(f"  [{qid}] {ti}")
            time.sleep(0.4)
        all_res[kw] = rows
        good = [r for r in rows if r["title"]]
        print(f"== {kw}: 抓到 {len(rows)} 条，取到标题 {len(good)} 条")
    fn = os.path.join(OUT, f"捡问题_{time.strftime('%Y%m%d_%H%M')}.json")
    json.dump(all_res, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已存", fn)


if __name__ == "__main__":
    main()
