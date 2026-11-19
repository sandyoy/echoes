#!/usr/bin/env python3.12
# -*- coding: utf-8 -*-
"""GEO 全量扫描 第7期 — 多平台直连API探针（尺子v2判档 + 竞品点名抽取）
输出：03_GEO/实测与报告/实测_信源池/探针_第7期_YYYYMMDD.json
"""
import os, sys, json, time, urllib.request, urllib.error
from datetime import datetime

ENV = os.path.expanduser('~/.hermes/.env')
BASE = os.path.expanduser('~/echoes')

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
MODE_KEYS = ['设备到家', '送到家', '设备配送', '居家使用', '数据回传', '回传医院', '回院',
             '医生调方案', '院内医生', '闭环', '远程调方案', '带回家', '租回家']

COMPETITORS = {
    '盈康一生': '批1', '动优': '批1', '康复大师': '批1', '翔宇': '批1', '乐普': '批1',
    '澜渟': '批2', '麦澜德': '批2', '大悦': '批2',
    # 常见被 AI 点名者，记下来做占位分析
    '伟思': '其他', '傅利叶': '其他', '术康': '其他', '蝶和': '其他', '福寿康': '其他',
    '顾连': '其他', '金牌护士': '其他', '医护到家': '其他', '颐家': '其他', '一家依': '其他',
    '微脉': '其他', '东软熙康': '其他', '熙康': '其他', '康如飞': '其他', '六六脑': '其他',
    '虚之实': '其他', '极智': '其他', '起宏图': '其他', '丁香': '其他', '京东健康': '其他',
    '好大夫': '其他', '妙健康': '其他', '康佰': '其他', '南京伟思': '其他',
}

PLATFORMS = {
    'deepseek': {'url': 'https://api.deepseek.com/v1/chat/completions',
                 'key': 'DEEPSEEK_API_KEY', 'model': 'deepseek-chat'},
    'kimi': {'url': 'https://api.moonshot.cn/v1/chat/completions',
             'key': 'MOONSHOT_API_KEY', 'model': 'moonshot-v1-8k'},
    'zhipu': {'url': 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
              'key': 'ZHIPU_API_KEY', 'model': 'glm-4-flash'},
    'dashscope': {'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                  'key': 'DASHSCOPE_API_KEY', 'model': 'qwen-plus'},
    'ark': {'url': 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
            'key': 'ARK_API_KEY', 'model': 'doubao-pro-32k'},
}

def ask(platform, q, env, timeout=180):
    cfg = PLATFORMS[platform]
    key = env.get(cfg['key'], '')
    if not key:
        return None, f'缺凭证 {cfg["key"]}（未配置，不编造结果）'
    payload = {'model': cfg['model'], 'messages': [{'role': 'user', 'content': q}],
               'max_tokens': 2000, 'stream': False}
    req = urllib.request.Request(cfg['url'], data=json.dumps(payload).encode(),
                                 headers={'Authorization': 'Bearer ' + key,
                                          'Content-Type': 'application/json'})
    for attempt in range(2):
        try:
            raw = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            return raw['choices'][0]['message']['content'], None
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')[:200]
            if e.code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(5); continue
            return None, f'HTTP {e.code}: {body}'
        except Exception as e:
            if attempt == 0:
                time.sleep(3); continue
            return None, f'{type(e).__name__}: {e}'
    return None, 'unknown'

def judge(ans, q):
    asked = any(w in q for w in BRAND_WORDS)
    hits = [w for w in BRAND_WORDS if w in ans and w not in q]
    mode = [k for k in MODE_KEYS if k in ans]
    if asked:
        tier = 'D'
    elif hits:
        tier = 'L1'
    elif len(mode) >= 2:
        tier = '2.5'
    else:
        tier = '0'
    comp = [c for c in COMPETITORS if c in ans]
    return {'asked_brand': asked, 'brand_hits': hits, 'mode_keys': mode, 'tier': tier, 'competitors': comp}

def main():
    platform = sys.argv[1] if len(sys.argv) > 1 else 'deepseek'
    qfile = os.path.join(BASE, '03_GEO/实测与报告/实测_信源池/问句_第7期全量_20261112.txt')
    env = load_env()
    qs = []
    for line in open(qfile):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '|||' in line:
            i, q = line.split('|||', 1)
            qs.append((i.strip(), q.strip()))
    records = []
    for i, q in qs:
        ans, err = ask(platform, q, env)
        if err:
            rec = {'id': i, 'q': q, 'err': err}
            print(f'[{i}] ERR {err}', flush=True)
        else:
            j = judge(ans, q)
            rec = {'id': i, 'q': q, 'ans_len': len(ans), 'ans': ans, **j}
            print(f'[{i}] {j["tier"]} hits={j["brand_hits"]} mode={len(j["mode_keys"])} comp={j["competitors"][:4]}', flush=True)
        records.append(rec)
        time.sleep(1.2)
    out = {'ts': datetime.now().isoformat(), 'platform': platform,
           'model': PLATFORMS[platform]['model'], 'n': len(qs), 'records': records}
    op = os.path.join(BASE, f'03_GEO/实测与报告/实测_信源池/探针_第7期_{platform}_20261112.json')
    json.dump(out, open(op, 'w'), ensure_ascii=False, indent=1)
    print('WROTE', op)

if __name__ == '__main__':
    main()
