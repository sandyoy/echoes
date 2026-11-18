# -*- coding: utf-8 -*-
"""小桥 · 出题引擎 v1.0（本地出题侧）

设计口径（对应 小鲸鱼 2026-11-18 回执的三个漏洞）：
  漏洞1 线上死写 23 题        -> 本引擎按「天」算出当天题面，前端拉 api/quiz 渲染
  漏洞2 dayN.json 不可持续    -> 不落任何每天的文件，纯函数算：同一天永远同一套题（种子固定）
  漏洞3 不记「昨天错在哪」     -> 预留 review:true（由服务端从错题记录喂入），出同一知识点的变式题

内容归小龙虾（本地），管道归小鲸鱼（服务端）。
服务端只要：GET /api/quiz?day=N[&review=...] -> json.loads(quizgen.quiz_json(day))
本文件不依赖任何第三方库，可被 import；也可直接 python3 quizgen.py 12 看第12天题面。

题目结构（固定，谁改都别动字段名）：
  {v, day, title, subtitle, note,
   parts:[{name, tag, say(老师讲的话，可选),
           qs:[{id, stem, ans:[可接受答案], open:false, ref:可复制文本用的题目, ph:placeholder, ta:是否多行}]}]}
"""
import json
import random

SCHEMA_V = "1.0"

# ---------------------------------------------------------------- 知识地图
# tag: 每科每天最多 3 个新点（规则 v2.0 第二条），复习不限量
PLAN_DAYS = 185


def _mul_row(n):
    return [f"{n}×{i}={n * i}" for i in range(1, 10)]


def _new_points_for_day(n):
    """返回当天新知识点列表，每项 (tag, 标题, 题)。规则 v2.0 §二：每科最多 3 个新点。"""
    pts = []
    # 数学：第一轮乘法口诀+除法反推（20 天），之后按块推进（一年 185 天）
    m = n % 20 or 20
    if m in (1, 2):
        rows = [2, 3] if m == 1 else [4]
        for r in rows:
            pts.append(("数学", f"{r} 的口诀（顺着算）", _mul_qs(r, reverse=False)))
    elif m in (3, 4):
        rows = [5] if m == 3 else [6]
        for r in rows:
            pts.append(("数学", f"{r} 的口诀（顺着算）", _mul_qs(r, reverse=False)))
    elif m == 5:
        pts.append(("数学", "2-6 口诀倒着算", _div_qs([2, 3, 4, 5, 6])))
    elif m in (6, 7):
        r = 7 if m == 6 else 8
        pts.append(("数学", f"{r} 的口诀（顺 + 倒）", _mul_qs(r, reverse=False) + _mul_qs(r, reverse=True)))
    elif m in (8, 9):
        r = 8 if m == 8 else 9
        pts.append(("数学", f"{r} 的口诀（顺 + 倒）", _mul_qs(r, reverse=False) + _mul_qs(r, reverse=True)))
    elif m in (10, 11):
        pts.append(("数学", "9 的口诀（顺 + 倒 + 手指法）", _mul_qs(9, reverse=False) + _mul_qs(9, reverse=True)))
    elif m in (12, 13, 14, 15):
        pts.append(("数学", "口诀顺倒缺三向混合", _mix_qs()))
    else:
        pts.append(("数学", "有余数除法 + 除法竖式", _rem_qs()))
    # 语文：拼音（b/d、p/q 已过，不再考）→ 声调 → 音节 → 组词 → 部首；63 单元一年铺
    y = n % 10
    if y in (1, 2):
        pts.append(("语文", "拼音·声母拼读", _pinyin_shengmu(n)))
    elif y in (3, 4):
        pts.append(("语文", "拼音·标调", _pinyin_tone(n)))
    elif y in (5, 6):
        pts.append(("语文", "拼音·写音节", _pinyin_syllable(n)))
    elif y in (7, 8):
        pts.append(("语文", "认字·组词", _word_qs(n)))
    else:
        pts.append(("语文", "部首·偏旁", _radical_qs(n)))
    # 英语：语块组（每块必须有英文原样 + 中文意思 + 造句，规则 v2.0 §六）
    pts.append(("英语", "每日语块", _english_chunks(n)))
    return pts


def _mul_qs(r, reverse):
    rnd = random.Random(f"mul-{r}-{reverse}")
    qs = []
    picks = rnd.sample(range(1, 10), 4)
    for i, k in enumerate(picks, 1):
        if reverse:
            qs.append(dict(id=f"m{i}", stem=f"{r * k} ÷ {r} = ？", ans=[str(k)], ref=f"{r * k}÷{r}",
                           ph="填数字"))
        else:
            qs.append(dict(id=f"m{i}", stem=f"{r} × {k} = ？", ans=[str(r * k)], ref=f"{r}×{k}", ph="填数字"))
    return qs


def _div_qs(rows):
    rnd = random.Random(f"div-{sorted(rows)}")
    qs = []
    for i, r in enumerate(rnd.sample(rows, min(4, len(rows))), 1):
        k = rnd.randint(2, 9)
        qs.append(dict(id=f"m{i}", stem=f"{r * k} ÷ {r} = ？", ans=[str(k)], ref=f"{r * k}÷{r}", ph="填数字"))
    return qs


def _mix_qs():
    rnd = random.Random("mix")
    qs = []
    for i in range(1, 7):
        r = rnd.randint(2, 9)
        k = rnd.randint(2, 9)
        kind = rnd.choice(["mul", "div", "fill"])
        if kind == "mul":
            qs.append(dict(id=f"m{i}", stem=f"{r} × {k} = ？", ans=[str(r * k)], ref=f"{r}×{k}", ph="填数字"))
        elif kind == "div":
            qs.append(dict(id=f"m{i}", stem=f"{r * k} ÷ {k} = ？", ans=[str(r)], ref=f"{r * k}÷{k}", ph="填数字"))
        else:
            qs.append(dict(id=f"m{i}", stem=f"{r} × __ = {r * k}", ans=[str(k)], ref=f"{r}×{k}", ph="填数字"))
    return qs


def _rem_qs():
    rnd = random.Random("rem")
    qs = []
    for i in range(1, 5):
        d = rnd.randint(3, 9)
        q = rnd.randint(2, 9)
        rem = rnd.randint(1, d - 1)
        a = d * q + rem
        qs.append(dict(id=f"m{i}", stem=f"{a} ÷ {d} = ？余几？（不知道就空着）",
                       ans=[f"{q}...{rem}", f"{q}余{rem}", str(q)], ref=f"{a}÷{d}", ph="例：3...2"))
    return qs


_PY_SM = [("m", "妈"), ("h", "花"), ("sh", "水"), ("n", "你"), ("x", "小"), ("l", "老"), ("t", "天"), ("g", "狗")]
_PY_TONE = [("妈", "mā1"), ("麻", "má2"), ("马", "mǎ3"), ("骂", "mà4")]
_WORDS = [("妈", "妈妈"), ("花", "花朵"), ("水", "喝水"), ("天", "天空"), ("小", "小学生")]


def _pinyin_shengmu(n):
    rnd = random.Random(f"py-sm-{n}")
    qs = []
    for i, (s, ch) in enumerate(rnd.sample(_PY_SM, 4), 1):
        qs.append(dict(id=f"y{i}", stem=f"「{ch}」的拼音第一个字母是什么？", ans=[s], ref=ch, ph="写字母"))
    return qs


def _pinyin_tone(n):
    rnd = random.Random(f"py-tone-{n}")
    qs = []
    for i, (ch, a) in enumerate(rnd.sample(_PY_TONE, 3), 1):
        qs.append(dict(id=f"y{i}", stem=f"给「{ch}」标上声调（写拼音）", ans=[a, a[:-1]], ref=ch, ph="写带声调的拼音"))
    return qs


def _pinyin_syllable(n):
    pairs = [("b", "à", "爸"), ("x", "iǎo", "小"), ("m", "ā", "妈"), ("h", "uā", "花")]
    rnd = random.Random(f"py-syl-{n}")
    qs = []
    for i, (a, b, ch) in enumerate(rnd.sample(pairs, 3), 1):
        qs.append(dict(id=f"y{i}", stem=f"把 {a}—{b} 拼成一个音节，写出这个字是哪个", ans=[ch],
                       ref=f"{a}—{b}", ph="写字"))
    return qs


def _word_qs(n):
    rnd = random.Random(f"word-{n}")
    qs = []
    for i, (ch, w) in enumerate(rnd.sample(_WORDS, 3), 1):
        qs.append(dict(id=f"y{i}", stem=f"用「{ch}」组成一个词（不会就空着）", ans=[w, ch + "子", ch], ref=ch,
                       ph="写词语"))
    return qs


_RADICALS = [("妈", "女"), ("花", "艹"), ("河", "氵"), ("树", "木"), ("烧", "火")]


def _radical_qs(n):
    rnd = random.Random(f"rad-{n}")
    qs = []
    for i, (ch, rad) in enumerate(rnd.sample(_RADICALS, 3), 1):
        qs.append(dict(id=f"y{i}", stem=f"「{ch}」的偏旁是什么？", ans=[rad], ref=ch, ph="写偏旁"))
    return qs


_CHUNKS = [
    ("get up", "起床", "I get up at seven."),
    ("go to school", "上学", "I go to school at eight."),
    ("have breakfast", "吃早饭", "I have breakfast at seven thirty."),
    ("play football", "踢足球", "I play football after school."),
    ("go home", "回家", "I go home at five."),
    ("do homework", "做作业", "I do homework in the evening."),
    ("watch TV", "看电视", "I watch TV after dinner."),
    ("go to bed", "睡觉", "I go to bed at nine."),
]


def _english_chunks(n):
    rnd = random.Random(f"en-{n}")
    qs = []
    for i, (en, zh, sent) in enumerate(rnd.sample(_CHUNKS, 3), 1):
        qs.append(dict(id=f"e{i}", stem=f"「{zh}」用英语怎么说？", ans=[en], ref=zh, ph="写英文"))
        qs.append(dict(id=f"s{i}", stem=f"用「{en}」说一句话（不会就空着）", ans=[sent], ref=en, ph="写句子", ta=True))
    return qs


def _review_qs(err_upto):
    """复习区：从错题(知识点)里抽变式题。err_upto = [知识点题组列表]，服务端喂。"""
    if not err_upto:
        return None
    rnd = random.Random("review")
    pool = [q for grp in err_upto for q in grp]
    if not pool:
        return None
    picked = rnd.sample(pool, min(4, len(pool)))
    out = []
    for i, q in enumerate(picked, 1):
        out.append(dict(id=f"r{i}", stem=q["stem"], ans=list(q["ans"]), ref=q.get("ref", q["stem"]),
                        ph=q.get("ph", "填数字"), ta=q.get("ta", False)))
    return out


def _open_qs(n):
    prompts = ["今天学的这些东西里，你觉得哪一条最难？为什么？",
               "如果你来当小老师，你会怎么把这个讲给别人听？",
               "今天有没有哪道题是你猜的？猜的时候在想什么？"]
    rnd = random.Random(f"open-{n}")
    return [dict(id="o1", stem=prompts[n % len(prompts)], ans=[], ref="说一说", open=True,
                 ph="想到什么写什么，写不出来就空着", ta=True)]


def build_quiz(day, review_groups=None, learner="小桥"):
    n = max(1, int(day))
    rnd = random.Random(f"day-{n}")
    parts = []
    intro = {
        "say": "今天还是四块：拼音、乘法口诀、英语，最后跟我说三句话。做不出来的就空着，空着不是错，空着是告诉我「这里要教你」。"
    }
    parts.append(dict(name="开始", tag="", say=intro["say"], qs=[]))
    rv = _review_qs(review_groups)
    if rv:
        parts.append(dict(name="先复习一下（1-3-7）", tag="复习", say="先看看昨天、前几天的还记得不记得。忘了没关系，我会再讲一遍。",
                          qs=rv))
    buckets = {"语文": [], "数学": [], "英语": []}
    for tag, title, qs in _new_points_for_day(n):
        buckets[tag] += [(title, q) for q in qs]
    for tag in ("语文", "数学", "英语"):
        if buckets[tag]:
            parts.append(dict(name=f"{tag}", tag=tag, say="", qs=[q for _, q in buckets[tag]]))
    parts.append(dict(name="跟我说三句话", tag="聊一聊", say="最后随便跟我说说，没有对错。", qs=_open_qs(n)))
    title = f"第 {n} 天"
    total = sum(len(p["qs"]) for p in parts)
    return dict(v=SCHEMA_V, day=n, title=title, learner=learner,
                subtitle=f"{title} · 约 20 分钟 · 共 {total} 题",
                note=f"本套题由出题引擎按第 {n} 天规则生成（种子固定，同一天永远同一套）",
                parts=parts)


def quiz_json(day, review_groups=None, learner="小桥"):
    return json.dumps(build_quiz(day, review_groups, learner), ensure_ascii=False)


if __name__ == "__main__":
    import sys
    d = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(quiz_json(d))

# ---------------------------------------------------------------- 服务端接入
# 小鲸鱼侧（xiaoqiao/web/server.py）只需两行：
#   import quizgen
#   if qs has day: body = quizgen.handle_quiz_query(qs)
# 返回 str(JSON)。review 参数 = 昨天错题题的 ref 列表（逗号分隔），
# 用 ref 反查当天那类知识点，生成变式题放进「先复习一下（1-3-7）」区。
def _groups_from_refs(refs):
    refs = [r for r in (refs or []) if r]
    if not refs:
        return None
    out = []
    for r in refs:
        r = str(r).strip()
        g = []
        if '×' in r or '÷' in r:
            g = _mul_qs(7, False) + _div_qs([2, 3, 4, 5, 6, 7, 8, 9])
        elif len(r) == 1 and '\u4e00' <= r <= '\u9fff':
            g = _pinyin_shengmu(1) + _pinyin_tone(1) + _word_qs(1) + _radical_qs(1)
        else:
            g = _english_chunks(1)
        out.append(g[:2])
    return out


def handle_quiz_query(qs, default_day=1):
    """qs: dict（parse_qs 的扁平值也行）-> JSON 字符串"""
    def one(k, d=''):
        v = qs.get(k)
        if isinstance(v, list):
            v = v[0] if v else d
        return v if v is not None else d
    try:
        day = int(one('day', default_day))
    except Exception:
        day = default_day
    review = str(one('review', '')).split(',')
    learner = str(one('learner', '小桥'))
    return quiz_json(day, _groups_from_refs(review), learner)


def serve_quiz_fallback(handler):
    """给 SimpleHTTPRequestHandler 子类用：处理 GET /api/quiz?day=N。返回 True 表示已处理。"""
    from urllib.parse import urlparse, parse_qs
    u = urlparse(handler.path)
    if u.path not in ('/api/quiz', '/quiz'):
        return False
    qs = {k: v[0] for k, v in parse_qs(u.query).items()}
    body = handle_quiz_query(qs).encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True
