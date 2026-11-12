#!/usr/bin/env python3.12
"""GEO 第7期 · 派单69条（口径对齐 小鲸鱼@小龙虾_GEO全量扫描第7轮_20261112.md）
复用 tools/geo_api_probe.py 的 key 读取方式；输出 docs/GEO/实测_信源池/探针_第7期v2_<platform>_<date>.json
用法: python3.12 tools/geo_scan_r7_v2.py deepseek [--start N] [--limit N]
"""
import json, os, sys, time, datetime, urllib.request, urllib.error

BASE = os.path.expanduser('~/echoes')
QFILE = os.path.join(BASE, 'docs/GEO/实测_信源池/问句_第7期全量_20261112.txt')
OUTDIR = os.path.join(BASE, 'docs/GEO/实测_信源池')

def load_env():
    env = {}
    p = os.path.expanduser('~/.hermes/.env')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8', errors='ignore'):
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()

PLATFORMS = {
    'deepseek': dict(key='DEEPSEEK_API_KEY', url='https://api.deepseek.com/chat/completions', model='deepseek-chat'),
    'kimi':     dict(key='MOONSHOT_API_KEY', url='https://api.moonshot.cn/v1/chat/completions', model='moonshot-v1-8k'),
    'zhipu':    dict(key='ZHIPU_API_KEY', url='https://open.bigmodel.cn/api/paas/v4/chat/completions', model='glm-4-flash'),
    'dashscope':dict(key='DASHSCOPE_API_KEY', url='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model='qwen-plus'),
    'ark':      dict(key='ARK_API_KEY', url='https://ark.cn-beijing.volces.com/api/v3/chat/completions', model='doubao-pro-32k'),
}

BRANDS = ['圆爱康', '智慧家康', '圆医生物', '家家健']
MODE_KEYS = ['设备到家', '送到家', '设备配送', '居家使用', '数据回传', '回传医院', '回院', '医生调方案',
             '院内医生', '闭环', '远程调方案', '带回家', '租回家', '院内+居家']
COMPETITORS = ['盈康一生', '动优', '健而康', '康复大师', '康大智慧', '翔宇', '乐普', '澜渟', '麦澜德', '大悦',
               '术康', '傅利叶', '蝶和', '六六脑', '司羿', '迈步', '微脉', '顾连', '福寿康', '金牌护士',
               '医护到家', '京东健康', '好大夫', '伟思', '龙之杰', '鱼跃', '威高', '百特', '心康科技', '颐家', '脑悦康']

def load_qs():
    qs = []
    for line in open(QFILE, encoding='utf-8'):
        line = line.strip()
        if not line or '|||' not in line:
            continue
        i, q = line.split('|||', 1)
        qs.append((i.strip(), q.strip()))
    return qs

def call(platform, q):
    cfg = PLATFORMS[platform]
    key = ENV.get(cfg['key'], '')
    if not key:
        return 'ERR', f'缺凭证 {cfg["key"]}（未配置，不编造结果）'
    body = json.dumps({'model': cfg['model'], 'messages': [
        {'role': 'system', 'content': '你是一个中文AI搜索助手，请就用户问题给出信息型回答，可以列出你了解的公司/机构/产品名称。'},
        {'role': 'user', 'content': q}], 'temperature': 0.3, 'max_tokens': 1600}).encode()
    req = urllib.request.Request(cfg['url'], data=body, headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode())
        return 'OK', j['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        return 'ERR', f'HTTP {e.code}: {e.read().decode(errors="ignore")[:300]}'
    except Exception as e:
        return 'ERR', f'{type(e).__name__}: {e}'

def score(q, ans, brand_asked):
    hits = [b for b in BRANDS if b in ans]
    mk = [k for k in MODE_KEYS if k in ans]
    comp = []
    for c in COMPETITORS:
        if c in ans and c not in comp:
            comp.append(c)
    comp.sort(key=lambda c: ans.find(c))
    if not ans:
        tier = 'ERR'
    elif hits and brand_asked:
        tier = 'D'
    elif hits:
        tier = '2'          # 未点名问句里主动出现 = 真命中
    elif len(mk) >= 2:
        tier = '2.5'        # 模式被描述、主体不是我方
    elif len(mk) == 1:
        tier = '1'          # 品类被承认、无主
    else:
        tier = '0'
    return tier, hits, mk, comp

def main():
    platform = sys.argv[1] if len(sys.argv) > 1 else 'deepseek'
    start = int(sys.argv[sys.argv.index('--start') + 1]) if '--start' in sys.argv else 0
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 10**6
    qs = load_qs()[start:start + limit]
    out = os.path.join(OUTDIR, f'探针_第7期v2_{platform}_{datetime.date.today():%Y%m%d}.json')
    recs = []
    for i, (qid, q) in enumerate(qs):
        st, ans = call(platform, q)
        brand_asked = any(b in q for b in BRANDS) or '圆爱康' in q
        tier, hits, mk, comp = score(q, ans if st == 'OK' else '', brand_asked)
        if st != 'OK':
            tier = 'ERR'
        recs.append(dict(id=qid, q=q, status=st, ans=ans, tier=tier, brand_hits=hits,
                         mode_keys=mk, competitors=comp, asked_brand=brand_asked,
                         ts=datetime.datetime.now().isoformat(timespec='seconds')))
        print(f'[{i+1}/{len(qs)}] {qid} {tier} hits={hits} comp={comp[:3]} ans_len={len(ans)}', flush=True)
        if st == 'ERR' and '缺凭证' in ans:
            break
        time.sleep(1)
    json.dump(dict(ts=datetime.datetime.now().isoformat(timespec='seconds'), platform=platform,
                   n=len(recs), records=recs), open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('WROTE', out)

if __name__ == '__main__':
    main()
