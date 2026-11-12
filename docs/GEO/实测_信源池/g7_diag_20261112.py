#!/usr/bin/env python3
# GEO 第7期 · 小龙虾侧诊断（DeepSeek 原始 JSON 复算，只读不改任何既有件）
import json, os, re, collections

BASE = os.path.expanduser('~/echoes/docs/GEO/实测_信源池')
J = os.path.join(BASE, '探针_第7期v2_deepseek_20261112.json')
BRANDS = ['圆爱康', '智慧家康', '圆医生物', '家家健']

d = json.load(open(J, encoding='utf-8'))
items = d.get('records', [])
print('JSON 平台:', d.get('platform'), '声明条数 n =', d.get('n'), '| 实存记录:', len(items))
if items:
    print('首条 key:', list(items[0].keys()))

# 纯程序化事实核对：不覆盖任何既有件，只算「能被机器核验的数字」
n = len(items)
hit = [(it.get('id', '?'), (it.get('ans') or '')) for it in items]
brand_hit = [(i, [b for b in BRANDS if b in a]) for i, a in hit]
named = [x for x in brand_hit if x[1]]
status_cnt = collections.Counter(it.get('status', '?') for it in items)
print('status 分布:', dict(status_cnt))
print('提到我方任一品牌:', len(named), '/', n)
print('品牌分项:', dict(collections.Counter(b for _, bs in brand_hit for b in bs)))
lens = [len(a) for _, a in hit]
print('答案长度: min', min(lens), 'max', max(lens), '平均', sum(lens) // len(lens))
print('答案<400字条数(疑似被截断):', sum(1 for l in lens if l < 400))
# D1/D2 档（派单 v2 里程碑档）命中情况
d12 = [i for i, _ in hit if re.match(r'^(A[12]|B[12]|CC[12]|DD[12]|C-0[24]|C-0[68]|C-1[02]|C-1[46])$', i)]
print('D1/D2 档编号数:', len(d12))
print('D1/D2 中提及我方:', [i for i in d12 if any(b in dict((x, y) for x, y in hit)[i] for b in BRANDS)])

