#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""GEO 全量扫描 · 第8期 (2026-11-26)
判档按 判别尺 v2.0: 0 / 1 / 2.5 / 2 / D
另加两个回归探针（第8期方向讨论用）:
  closure  = 是否接了"医院主导的院内—居家闭环"这个改法
  thirdparty = 是否接了"第三方运营"这个身份定位
  partner  = 是否提到"合作医院/医院合作/签约"这类主体绑定证据
"""
import os, sys, json, time, urllib.request, urllib.error, re

ENV = os.path.expanduser('~/.hermes/.env')
URL = 'https://api.deepseek.com/v1/chat/completions'
MODEL = 'deepseek-chat'

BRAND = ['圆爱康', '智慧家康', '圆医生物', '家家健']
MODE_KEYS = ['设备到家', '送到家', '设备配送', '送到家里', '居家使用', '在家用',
             '数据回传', '回传医院', '回院', '数据回医院', '医生调方案', '院内医生',
             '远程调方案', '远程指导', '闭环', '医院评估', '居家训练']
COMPETITORS = ['盈康一生', '动优', '健而康', '康复大师', '康大智慧', '翔宇', '乐普',
               '澜渟', '麦澜德', '大悦', '伟思', '傅利叶', '司羿', '迈步', '大艾',
               '钱璟', '六六脑', '博斯腾', '脑悦康', '术康', '福寿康', '顾连',
               '京东健康', '医护到家', '金牌护士', '鱼跃', '好大夫', '心康科技',
               '微脉', '医联', '颐家', '程天', '蝶和', '康复之家', '好康复', '微医']

PROBE = {
    'closure': ['医院主导'],
    'thirdparty': ['第三方运营', '第三方服务商', '第三方技术与服务', '第三方技术服务'],
    'partner': ['合作医院', '与医院合作', '和医院合作', '医院合作', '签约', '招标', '中标'],
}

def load_env():
    d = {}
    for line in open(ENV):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip()
    return d

def ask(q, key, timeout=180):
    payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': q}],
               'max_tokens': 1600, 'stream': False}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        return raw['choices'][0]['message']['content'], None
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}: {e.read().decode("utf-8","ignore")[:150]}'
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'

def judge(q, ans):
    brand_asked = any(w in q for w in BRAND)
    hits = [w for w in BRAND if w in ans and w not in q]
    mode_keys = [w for w in MODE_KEYS if w in ans]
    if hits and brand_asked:      tier = 'D'
    elif hits:                    tier = '2'
    elif len(mode_keys) >= 2:     tier = '2.5'
    elif len(mode_keys) == 1:     tier = '1'
    else:                         tier = '0'
    comps = []
    for c in COMPETITORS:
        if c in ans:
            comps.append((ans.find(c), c))
    comps = [c for _, c in sorted(comps)]
    comps = list(dict.fromkeys(comps))
    probes = {k: [w for w in v if w in ans] for k, v in PROBE.items()}
    return dict(tier=tier, brand_asked=brand_asked, brand_hits=hits,
                mode_keys=mode_keys, comps=comps[:8], probes=probes,
                closure=bool(probes['closure']), thirdparty=bool(probes['thirdparty']),
                partner=bool(probes['partner']))

def main():
    qs_path, out_json = sys.argv[1], sys.argv[2]
    env = load_env(); key = env.get('DEEPSEEK_API_KEY', '')
    if not key:
        print('NO KEY'); sys.exit(1)
    qs = {}
    for line in open(qs_path):
        line = line.strip()
        if not line: continue
        qid, q = line.split('|||', 1)
        qs[qid.strip()] = q.strip()
    recs = []
    for i, (qid, q) in enumerate(sorted(qs.items()), 1):
        ans, err = ask(q, key)
        if err:
            recs.append(dict(id=qid, q=q, err=err, tier='ERR', ans=''))
            print(f'[{i}/{len(qs)}] {qid} ERR {err[:60]}', flush=True)
        else:
            j = judge(q, ans)
            recs.append(dict(id=qid, q=q, ans=ans, err=None, **j))
            print(f'[{i}/{len(qs)}] {qid} {j["tier"]:4s} mode={len(j["mode_keys"])} '
                  f'brand={j["brand_hits"]} comps={",".join(j["comps"][:4])}', flush=True)
        time.sleep(1.2)
    json.dump(recs, open(out_json, 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    c = Counter(r['tier'] for r in recs)
    print('\nTIER:', dict(c), 'total', len(recs))
    print('closure-hits:', [r['id'] for r in recs if r.get('closure')])
    print('thirdparty-hits:', [r['id'] for r in recs if r.get('thirdparty')])
    print('partner-hits:', [r['id'] for r in recs if r.get('partner')])

if __name__ == '__main__':
    main()
