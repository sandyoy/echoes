#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""GEO 直连 API 探针 v1.0 — 2026-11-05
用途：不靠浏览器、不撞登录墙，直接打 AI 平台开放 API，问判定问句，看答案里有没有圆爱康/智慧家康。
用法：
  python3.12 geo_api_probe.py --platform deepseek --questions questions.txt --out out.md
平台开关：deepseek（已通） / metaso（需 METASO_API_KEY）
"""
import os, sys, json, time, argparse, urllib.request, urllib.error
from datetime import datetime

ENV = os.path.expanduser('~/.hermes/.env')

def load_env():
    d = {}
    if os.path.exists(ENV):
        for line in open(ENV):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                d[k.strip()] = v.strip()
    return d

BRAND_WORDS = ['圆爱康', '智慧家康', '圆医生物', '家家健']

ENDPOINTS = {
    'deepseek': {
        'url': 'https://api.deepseek.com/v1/chat/completions',
        'key': 'DEEPSEEK_API_KEY',
        'model': 'deepseek-chat',
    },
    'metaso': {
        'url': 'https://metaso.cn/api/v1/chat/completions',
        'key': 'METASO_API_KEY',
        'model': 'metaso-chat',
    },
}

def ask(platform, q, env, timeout=180):
    cfg = ENDPOINTS[platform]
    key = env.get(cfg['key'], '')
    if not key:
        return None, f'⚠️ 缺 {cfg["key"]}（未配置，不编造结果）'
    payload = {
        'model': cfg['model'],
        'messages': [{'role': 'user', 'content': q}],
        'max_tokens': 1500,
        'stream': False,
    }
    req = urllib.request.Request(
        cfg['url'], data=json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        ans = raw['choices'][0]['message']['content']
        return ans, None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')[:200]
        return None, f'HTTP {e.code}: {body}'
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'

def judge(ans, q=''):
    # 假阳性防线：问句本身含品牌词时，答案里出现同词不算命中
    hits = [w for w in BRAND_WORDS if w in ans and w not in q]
    return hits

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--platform', default='deepseek')
    ap.add_argument('--questions', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sleep', type=float, default=1.0)
    ap.add_argument('--model', default='')
    a = ap.parse_args()

    env = load_env()
    if a.model:
        ENDPOINTS[a.platform]['model'] = a.model
    qs = [l.strip() for l in open(a.questions) if l.strip() and not l.startswith('#')]
    rows = []
    for i, q in enumerate(qs, 1):
        ans, err = ask(a.platform, q, env)
        hits = judge(ans, q) if ans else []
        tier = 'HIT' if hits else ('ERR' if err else 'MISS')
        rows.append({'no': i, 'q': q, 'tier': tier, 'hits': hits, 'err': err,
                     'ans': (ans or '')[:400], 'len': len(ans or '')})
        tag = f' [{"/".join(hits)}]' if hits else ''
        print(f'[{i}/{len(qs)}] {tier} {q[:30]}{tag}{" ERR:"+err if err else ""}', flush=True)
        time.sleep(a.sleep)

    hit = sum(1 for r in rows if r['tier'] == 'HIT')
    err = sum(1 for r in rows if r['tier'] == 'ERR')
    ok = len(rows) - err
    lines = [
        f'# GEO 直连 API 探针 · {a.platform}',
        '',
        f'> 跑法：不靠浏览器、不撞登录墙，直接打 {a.platform} 开放 API｜{datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'> 样本：{len(rows)} 问｜有效 {ok}｜报错 {err}｜品牌命中 **{hit}**',
        '',
        '| # | 问句 | 判定 | 命中词 | 答长 |',
        '|---|---|---|---|---|',
    ]
    for r in rows:
        mark = {'HIT': '✅ 命中', 'MISS': '❌ 无品牌', 'ERR': '⚠️ 未跑成'}[r['tier']]
        lines.append(f'| {r["no"]} | {r["q"]} | {mark} | {"、".join(r["hits"]) or "—"} | {r["len"]} |')
    lines += ['', '## 逐条答案节选（前 400 字）', '']
    for r in rows:
        lines.append(f'### {r["no"]}. {r["q"]}')
        if r['err']:
            lines.append(f'> ⚠️ 未跑成：{r["err"]}')
        else:
            lines.append(r['ans'].replace('\n', ' ') + ' …')
        lines.append('')
    open(a.out, 'w').write('\n'.join(lines))
    print(f'\nDONE hit={hit}/{len(rows)} err={err} -> {a.out}')

if __name__ == '__main__':
    main()
