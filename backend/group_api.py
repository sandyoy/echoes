"""
往事可追忆 - 归类与切分（第2期「能排对」的核心：时间 vs 故事 两个维度）接口 handler 层 v1.0
建立：2026-10-16（日历 §四 活线无卡点，设计哨兵自动推进 v3.0 §五之二）

=== 为什么是今天做 ===
v3.0 §五之二 把「时间」与「故事」定成**两个独立的维度**：
  - 时间 = 排序维度（决定**排在哪**）→ 已由 `timeline_api.py`（05-06 落地）负责
  - 故事 = 归属维度（决定**跟谁一组**）→ **全项目一行代码都没有**
`models.py` 里 `Story.group_id` / `ai_group_confidence` / `ai_group_source` 三个字段
是 09-25 建表时就预埋的，至今**无任何模块读写**（死字段）。本节把这块补上。

=== 本文件干什么（逐条对齐 v3.0 §五之二.3 / §4 / §5）===
§五之二.3  一段话含多个时间点：
   `segment_clip_by_time()`   → 把「我八岁那年上学，十七岁就去当兵了」切成 2 段，各带各的时间
   `api_segment_preview()`    → 给前端看"切出来是这样，要不要这样分"（**不落库，先给看**）
   `api_apply_segments()`     → 用户点头后真的切成多条 Story（**宁分不合**，见下）

§五之二.4  归类原则「宁可分错，不可错并」：
   ★ `decide_grouping()`      → 每条判定必须走这个函数，**分错可修、错并难修**
   判据：拿不准一律 `separate`（切），允许事后合并（`api_merge_stories` 兜底）

§五之二.5  系统怎么判断"是不是同一件事"（抽时间 → 抽主体 → 比对已有故事）：
   `extract_subject()`        → 抽主体（规则可解的部分：人物/地点/动作词，**不做语义猜测**）
   `find_merge_candidates()`  → 给**候选清单 + 相似度**，**助手不是判官**
   `api_group_candidates()`   → 接口：返回候选，由人确认
   ★ `api_merge_stories()`    → 只有**人点了确认**才合并（**禁止全自动合并**，铁律）

=== 铁律（逐字执行，绝不打折扣）===
A. **禁止全自动合并**（§5之二.5）：`find_merge_candidates` 只出候选 + 置信度，绝不自己调 merge。
   合并的唯一入口是 `api_merge_stories(..., user_confirmed=True)`，缺了它就拒。
B. **宁可分错，不可错并**（§5之二.4）：一切模糊 → 选 `separate`。默认值 = 分。
C. **不猜时间**（§5.4）：切出来的段若判不出时间 → 该段 `time_pending=True`，不硬塞年份。
D. **权限沿用 permissions.can_view_story**：改归属 = 改书的内容，只有能写这本书的人才能切/合。
E. handler 不自己开 session，db 由调用方传；统一信封 {ok,data,error,code}。
F. 切分**不丢原文**：每段 `raw_content` 是原文的**连续子串**，拼起来 == 原全文（可自证，见自测 T3）。

=== 与既有模块的边界 ===
- `timeline_api.py`：管「排在哪」。本文件管「跟谁一组」。两者**互不调用**，只在 api 层汇合。
- `interview_api.py` 的 `api_ask_classify`：**采访/自述当场**问老人「这段是新的一件事吗」。
  本文件是**事后**在时间轴/列表上做同一件事（老人当时没答、或答了又说不对）。
  两者共享同一个 `group_id` 落点，**不互相替代**。
"""

import re
from difflib import SequenceMatcher

from permissions import _new_id, can_view_story

from models import (
    SessionLocal, Story, Clip, ClipType,
    init_db,
)

NO_PERMISSION = "你没有权限改这本书"
STORY_NOT_FOUND = "找不到这条故事"
NEED_CONFIRM = "合并必须由人确认后才能执行"


# ============================================================
# 一、统一信封（与 collect_api / story_api 同形）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code, "data": {}}
    d.update(extra)
    return d


# ============================================================
# 二、§五之二.3 一段话含多个时间点 —— 切分
# ============================================================

# 切句：以句末标点 + 分号切。口语里老人常用「，」连两个时间，故「，」也当潜在切点。
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")
_CLAUSE_SPLIT = re.compile(r"(?<=[，,])")

# 时间线索的**出现位置探测**：复用 timeline.py 的正则口径（此处只判"有没有时间"和位置，
# 不判具体年份——具体解析仍走 timeline.extract_time，不另造一套算法）。
from timeline import (  # noqa: E402
    RE_YEAR_FULL, RE_YEAR_MONTH, RE_YEAR_MONTH_DAY,
    RE_DECADE_CN, RE_AGE_YEAR, RE_MARRIAGE_N, RE_CHILD_YEAR,
    HISTORY_EVENTS, extract_time,
)

# 所有"能定位到位置"的时间线索正则（用于切分找切点）
_TIME_LOCATORS = [
    RE_YEAR_MONTH_DAY, RE_YEAR_MONTH, RE_YEAR_FULL,
    RE_DECADE_CN, RE_AGE_YEAR, RE_MARRIAGE_N, RE_CHILD_YEAR,
]

# 历史事件词表（无位置正则，靠 str.find 定位）
_HISTORY_WORDS = sorted(HISTORY_EVENTS.keys(), key=len, reverse=True)


def _find_time_spans(text: str) -> list:
    """
    找出文本里所有**时间线索**的位置区间 [(start, end, hit), ...]，按出现顺序。
    同一位置重叠的只留最长的一个。
    """
    t = text or ""
    spans = []

    for rx in _TIME_LOCATORS:
        for m in rx.finditer(t):
            spans.append((m.start(), m.end(), m.group(0)))

    for w in _HISTORY_WORDS:
        start = 0
        while True:
            i = t.find(w, start)
            if i < 0:
                break
            spans.append((i, i + len(w), w))
            start = i + len(w)

    if not spans:
        return []

    # 去重叠：按 (start, -end) 排序，贪心取不重叠且最长的
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out = []
    last_end = -1
    for s in spans:
        if s[0] >= last_end:
            out.append(s)
            last_end = s[1]
    return out


def _split_sentences(text: str) -> list:
    """切成句子（保留标点），返回 [(sent_text, global_start_offset), ...]。"""
    t = text or ""
    out = []
    pos = 0
    for piece in _SENT_SPLIT.split(t):
        if piece == "":
            continue
        out.append((piece, pos))
        pos += len(piece)
    if not out and t:
        out = [(t, 0)]
    return out


def segment_clip_by_time(text: str, anchors=None) -> list:
    """
    §五之二.3 核心：**一段话含多个时间点 → 切**

    规则（逐条对齐 §五之二.3 三条）：
    1. 能明确切分 → 切成多段，各归各位（本函数主责）
    2. 紧密关联 → **不替他决定**，标 `needs_ask=True`（前端去问老人"算一件事吗"）
    3. 拿不准 → 切开，允许事后合并（默认动作 = 切，§五之二.4）

    返回 [segment, ...]，每段：
      {
        "index": 0,
        "text": "...",              # 该段原文（连续子串）
        "char_start": 0, "char_end": 12,
        "time_raw": "1968年",        # 该段里命中的时间原文（可能空）
        "time_hit": True,            # 本段是否含时间线索
        "time_pending": False,       # True = 判不出时间，不猜（§5.4 保命线）
        "needs_ask": False,          # True = 紧密关联，须问老人"算一件事吗"
        "time_profile": {...} | None # timeline.extract_time 的结果（含 label/precision/sort_key）
      }

    ★ **多时间点才切**：整段只有一个时间线索（或没有）时，返回**单段**（不硬切）。
    """
    t = (text or "").strip()
    if not t:
        return []

    spans = _find_time_spans(t)

    # 只有 ≤1 个时间线索 → 不切（单段），但把时间解析出来
    if len(spans) <= 1:
        seg = _make_segment(t, 0, len(t), anchors)
        seg["index"] = 0
        return [seg]

    # 有 ≥2 个时间线索 → 按"时间线索出现的句子"边界切
    sents = _split_sentences(t)

    # 给每个句子打标记：命中了第几个时间线索
    sent_marks = []
    for sent_text, sent_start in sents:
        sent_end = sent_start + len(sent_text)
        hit_idx = None
        for si, (ss, se, _hit) in enumerate(spans):
            if ss < sent_end and se > sent_start:
                hit_idx = si
                break
        sent_marks.append(hit_idx)

    # 一个句子含 ≥2 个时间线索 → 该句内部还要再切（按逗号）
    segments = []
    for (sent_text, sent_start), hit_idx in zip(sents, sent_marks):
        inner = _find_time_spans(sent_text)
        if len(inner) >= 2:
            segments.extend(_split_sentence_inner(sent_text, sent_start))
        else:
            segments.append((sent_text, sent_start, sent_start + len(sent_text), hit_idx))

    # 合并相邻的"无时间句子"到**前一段**（无时间的句子通常是上一句的延续）
    merged = []
    for seg_text, s0, s1, hit_idx in segments:
        has_time = bool(_find_time_spans(seg_text))
        if merged and not has_time:
            p_text, p0, _p1, p_hit = merged[-1]
            merged[-1] = (p_text + seg_text, p0, s1, p_hit)
        else:
            merged.append((seg_text, s0, s1, hit_idx))

    # 若合并后只剩 1 段（说明"多时间"其实在同一句里被合并了）→ 返回该单段
    out = []
    for i, (seg_text, s0, s1, _hi) in enumerate(merged):
        seg = _make_segment(seg_text, s0, s1, anchors)
        seg["index"] = i
        out.append(seg)

    if len(out) <= 1:
        seg = _make_segment(t, 0, len(t), anchors)
        seg["index"] = 0
        return [seg]

    # 标"紧密关联"：第 i 段与第 i+1 段时间**完全相同且都在同一年**（如都只说"那年"）
    #   → 无法明确切分 → needs_ask=True（§五之二.3 第2条：询问老人，不替他决定）
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if a.get("time_hit") and b.get("time_hit"):
            ka = (a.get("time_profile") or {}).get("sort_key")
            kb = (b.get("time_profile") or {}).get("sort_key")
            la = (a.get("time_profile") or {}).get("label")
            lb = (b.get("time_profile") or {}).get("label")
            if ka is not None and ka == kb and la == lb:
                a["needs_ask"] = True
                b["needs_ask"] = True

    return out


def _split_sentence_inner(sent_text: str, sent_start: int) -> list:
    """一个句子内有 ≥2 个时间线索 → 按逗号再切。"""
    out = []
    pos = 0
    for piece in _CLAUSE_SPLIT.split(sent_text):
        if not piece:
            continue
        out.append((piece, sent_start + pos, sent_start + pos + len(piece), None))
        pos += len(piece)
    if not out:
        out = [(sent_text, sent_start, sent_start + len(sent_text), None)]
    return out


def _make_segment(seg_text: str, s0: int, s1: int, anchors) -> dict:
    """把一段文本做成 segment dict（时间解析走 timeline.extract_time，不另造）。"""
    seg_text = seg_text or ""
    tr = extract_time(seg_text, anchors or {})
    has_hit = bool(_find_time_spans(seg_text))
    prof = tr.to_dict()
    # 判不出时间 → time_pending=True（§5.4 保命线：不猜）
    pending = (prof.get("precision") in ("unknown", None) or prof.get("sort_key") is None)
    return {
        "text": seg_text,
        "char_start": s0,
        "char_end": s1,
        "time_raw": prof.get("raw") or "",
        "time_hit": has_hit,
        "time_pending": bool(pending),
        "needs_ask": False,
        "time_profile": prof,
    }


def api_segment_preview(db=None, *, owner_id: str = "", viewer_id: str = "",
                        story_id: str = "", text: str = "", anchors=None) -> dict:
    """
    §五之二.3 接口：**先给看，不落库**。
    把一段（或某条故事已有的原文）切给用户看："是这样切成两件吗？"
    用户点头后才调 `api_apply_segments`。
    """
    actor = viewer_id or owner_id
    if not owner_id:
        return fail("bad_request")

    # 有 story_id → 从库里取原文（并校验权限）
    if story_id:
        s = db.query(Story).filter(Story.id == story_id).first()
        if not s:
            return fail(STORY_NOT_FOUND, "not_found")
        if s.owner_id != owner_id or not can_view_story(
                db, owner_id=owner_id, viewer_id=actor, story_id=story_id):
            return fail(NO_PERMISSION, "forbidden")
        if not text:
            text = _story_full_text(s)
    if not text:
        return fail("没有可切分的内容", "empty")

    segs = segment_clip_by_time(text, anchors)
    return ok({
        "story_id": story_id or None,
        "n_segments": len(segs),
        "will_separate": len(segs) > 1,
        "need_ask_user": any(x.get("needs_ask") for x in segs),
        "segments": segs,
        "hint": ("切出来 %d 段；拿不准的一律先切开，事后可合并（§五之二.4 宁可分错不可错并）"
                 % len(segs)),
    })


def _story_full_text(s: Story) -> str:
    """取一条故事的全文（raw_content 优先，含全文；否则拼 clips 的文字/转写）。"""
    if (s.raw_content or "").strip():
        return s.raw_content
    parts = []
    for c in (s.clips or []):
        if (getattr(c, "text", "") or "").strip():
            parts.append(c.text.strip())
        elif (getattr(c, "transcript", "") or "").strip():
            parts.append(c.transcript.strip())
    return "\n".join(parts)


def api_apply_segments(db, *, owner_id: str, viewer_id: str = "", story_id: str = "",
                       segments=None, user_confirmed: bool = False) -> dict:
    """
    §五之二.3 接口：用户点头后**真的切**。
    把原故事保留为第 1 段，其余段各自**新建一条 Story**（同 owner、同 group 原书），
    并把原文按段改写 raw_content（**不丢一个字**，拼接 == 原全文）。
    """
    actor = viewer_id or owner_id
    if not owner_id or not story_id:
        return fail("bad_request")
    if not user_confirmed:
        return fail("切分需用户确认（先调 segment/preview）", "need_confirm")

    s = db.query(Story).filter(Story.id == story_id).first()
    if not s:
        return fail(STORY_NOT_FOUND, "not_found")
    if s.owner_id != owner_id or not can_view_story(
            db, owner_id=owner_id, viewer_id=actor, story_id=story_id):
        return fail(NO_PERMISSION, "forbidden")

    segs = segments if segments else segment_clip_by_time(_story_full_text(s))
    if not isinstance(segs, list) or len(segs) < 2:
        return fail("只有一段，无需切分", "nothing_to_do")

    # 校验：段文本拼接 == 原全文（不丢字，铁律 F）
    full = _story_full_text(s)
    joined = "".join((x.get("text") or "") for x in segs)
    if joined.strip() != full.strip():
        return fail("切分结果与原文不一致（会丢字），已拒绝", "segment_mismatch")

    created = []
    # 第 1 段 → 保留在原故事（group 记到 story.group_id）
    gid = s.group_id or _new_id("grp")
    _apply_seg_to_story(s, segs[0])
    s.group_id = gid
    s.ai_group_source = "segment"
    db.flush()

    # 其余段 → 各建一条 Story，同 group_id（=同一件事的候选组，可事后拆/合）
    for seg in segs[1:]:
        ns = Story(
            id=_new_id("story"),
            owner_id=owner_id,
            title="",
            summary="",
            raw_content=seg.get("text") or "",
            group_id=gid,
            ai_group_confidence=0.5,   # 切出来的默认中等（不宣称确定）
            ai_group_source="segment",
            time_raw=seg.get("time_raw") or "",
            time_label=(seg.get("time_profile") or {}).get("label") or "",
            time_sort_key=int((seg.get("time_profile") or {}).get("sort_key") or 0),
            time_extract_method=(seg.get("time_profile") or {}).get("method") or "",
            narrator_id=owner_id,
            recorder_id=actor,
        )
        _set_precision(ns, (seg.get("time_profile") or {}).get("precision"))
        db.add(ns)
        db.flush()
        created.append(ns.id)

    db.commit()
    return ok({
        "group_id": gid,
        "kept_story_id": s.id,
        "new_story_ids": created,
        "n_segments": len(segs),
    })


def _apply_seg_to_story(s: Story, seg: dict):
    s.raw_content = seg.get("text") or ""
    prof = seg.get("time_profile") or {}
    if prof.get("label"):
        s.time_label = prof["label"]
    if prof.get("raw"):
        s.time_raw = prof["raw"]
    if prof.get("sort_key") is not None:
        s.time_sort_key = int(prof["sort_key"])
    if prof.get("method"):
        s.time_extract_method = prof["method"]
    _set_precision(s, prof.get("precision"))


def _set_precision(story: Story, precision_value):
    """把时间精度字符串安全落到 SAEnum（值域对齐，禁直接传对象）。"""
    from models import TimePrecision
    valid = {e.value for e in TimePrecision}
    if precision_value in valid:
        story.time_precision = TimePrecision(precision_value)
    else:
        story.time_precision = TimePrecision.UNKNOWN


# ============================================================
# 三、§五之二.4 「宁可分错，不可错并」—— 判定器（唯一真相源）
# ============================================================

SEPARATE = "separate"
MERGE_CANDIDATE = "merge_candidate"


def decide_grouping(*, same_time: bool, same_subject: bool,
                    subject_similarity: float = 0.0,
                    confirmed_by_user: bool = False) -> dict:
    """
    §五之二.4 铁律的唯一落地点：**合并损失 > 分离损失。**

    判据表（拿不准一律 separate）：
      - 时间不同 → separate（各归各位）
      - 时间同 + 主体不同 → separate
      - 时间同 + 主体同 + **人确认过** → merge_candidate
      - 时间同 + 主体同 + 无人确认 → 仍 separate（只给候选，禁止全自动合并 §5之二.5）

    返回 {"decision": separate|merge_candidate, "reason": ..., "conservative": bool}
    """
    if not same_time:
        return {"decision": SEPARATE, "reason": "different_time", "conservative": True}
    if not same_subject:
        return {"decision": SEPARATE, "reason": "different_subject", "conservative": True}
    if not confirmed_by_user:
        return {"decision": SEPARATE, "reason": "need_user_confirm",
                "conservative": True, "similarity": round(float(subject_similarity), 3)}
    if subject_similarity < 0.6:
        return {"decision": SEPARATE, "reason": "similarity_too_low",
                "conservative": True, "similarity": round(float(subject_similarity), 3)}
    return {"decision": MERGE_CANDIDATE, "reason": "same_time_same_subject_confirmed",
            "conservative": False, "similarity": round(float(subject_similarity), 3)}


# ============================================================
# 四、§五之二.5 抽主体 + 找候选（助手不是判官）
# ============================================================

# 主体线索（规则可解的部分，**不做语义猜测**——语义难度高于时间提取，§5之二.5 已标注待验证）
# ★实测修正（2026-10-16 晚自测发现）：老人说的是"盖的房子"，不是"盖房"。
#   原正则 `盖房` 匹配不到 → 真语料下抽不出动作。动作词写成"词根 + 允许的字"形式。
#   同理 `上班` 也漏了"上工"，`种地` 漏了"种田"。
RE_PERSON = re.compile(r"(?:我|俺)(?:们)?|[一-龥]{2,3}(?:大叔|大妈|大爷|婶|叔|姨|哥|姐|弟|妹|老师|师傅|同志)")
# 地名：★实测修正（2026-10-16 晚）——正则 "吞前导字" 是这类抽取的通病：
#   "我在王家村"会被整段吃掉（v1 抽成 "我在王家村"，v2 抽成 "年在王家村"）。
#   中文没有词边界，靠正则治不了；改为"正则粗抽 + 剥虚词尾巴"两步，
#   虚词表 _VIRTUAL_HEAD 见下。宁可抽得短（"王家村"），不可抽得脏（"我在王家村"）。
RE_PLACE = re.compile(r"[一-龥]{1,4}(?:村|镇|县|市|省|厂|队|公社|学校|中学|小学|部队)")

# 地名/人称前面会挂的虚词（时间词 + 代词 + 介词/助词），抽完逐个剥掉
_VIRTUAL_HEAD = set("我俺他她你您咱年在到回和跟与同及了的地得就都又还从对给让把")
# 动作：用"词根 + 可选修饰"覆盖真实口语变体（盖房/盖的房子/盖了三间房）
RE_ACTION = re.compile(
    r"(?:上学|念书|读书|考学"
    r"|结婚|出嫁|嫁人|成亲|娶亲|娶了"
    r"|当兵|参军|入伍"
    r"|盖(?:房|屋|的房子|了三间房|了新房)|盖房子"
    r"|种(?:地|田|庄稼)|进厂|入厂|下岗|退休"
    r"|工作|上班|上工|下地|干活|打工|做生意|经商|开店|摆摊"
    r"|搬家|分家|搬迁|调动|返乡|回城"
    r"|生(?:了|育|孩子|娃)|住院|治病)"
)

_STOPWORDS = {
    "那年", "那年头", "后来", "然后", "就是", "的时候", "那会儿", "这个", "那个",
    "我们", "他们", "什么", "怎么", "因为", "所以", "但是", "可是",
}


def extract_subject(text: str) -> dict:
    """
    第2步抽主体（§五之二.5）：**规则可解的部分**。
    返回 {"persons": [...], "places": [...], "actions": [...], "tokens": [...], "is_empty": bool}

    ★ 刻意**不做语义级主体识别**——§五之二.5 明写"语义难度高于时间提取，非规则可解，须评估"。
      这里只抽**可复现的规则信号**，供人看候选；语义判断留给人。
    """
    t = (text or "").strip()
    persons = _dedup([_strip_virtual_head(x) for x in RE_PERSON.findall(t)])
    places = _dedup([_strip_virtual_head(x) for x in RE_PLACE.findall(t)])
    actions = _dedup(RE_ACTION.findall(t))

    # tokens：去掉标点/停用词后的 2 字以上词块（用于相似度）
    raw_tokens = re.split(r"[，。！？、；：\s,.!?;:]+", t)
    tokens = []
    for tok in raw_tokens:
        tok = tok.strip()
        if len(tok) >= 2 and tok not in _STOPWORDS:
            tokens.append(tok)

    is_empty = not (persons or places or actions or tokens)
    return {
        "persons": persons, "places": places, "actions": actions,
        "tokens": tokens, "is_empty": is_empty,
    }


def _strip_virtual_head(word: str) -> str:
    """
    剥掉抽取结果前面的虚词/时间词（"我在王家村" → "王家村"；"跟我大哥" → "大哥"）。
    ★ 只剥头、不剥尾、不留空；剥到剩 2 字就停（中文地名/称呼最少 2 字）。
      宁可留短，不可留脏——脏主体会把相似度算歪，进而导致"错并"。
    """
    w = word or ""
    while len(w) > 2 and w[0] in _VIRTUAL_HEAD:
        w = w[1:]
    # 剥完只剩虚词的，算没抽到
    if w and all(ch in _VIRTUAL_HEAD or ch in "们" for ch in w):
        return ""
    return w


def _dedup(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def subject_similarity(a: dict, b: dict) -> float:
    """
    两段主体信号的相似度 0~1。
    权重：人物 0.4 / 地点 0.2 / 动作 0.2 / 词块 0.2。
    **偏保守**（宁可判低，不判高——高判会导致错并）。
    """
    if not a or not b:
        return 0.0
    if a.get("is_empty") or b.get("is_empty"):
        return 0.0

    def jac(xs, ys):
        sx, sy = set(xs or []), set(ys or [])
        if not sx and not sy:
            return 0.0
        return len(sx & sy) / len(sx | sy)

    p = jac(a.get("persons"), b.get("persons"))
    pl = jac(a.get("places"), b.get("places"))
    ac = jac(a.get("actions"), b.get("actions"))

    # 词块用 SequenceMatcher 取最高匹配（口语同样意思不同说法）
    ta, tb = "".join(a.get("tokens") or []), "".join(b.get("tokens") or [])
    tk = SequenceMatcher(None, ta, tb).ratio() if (ta and tb) else 0.0

    score = 0.4 * p + 0.2 * pl + 0.2 * ac + 0.2 * tk
    return round(min(1.0, max(0.0, score)), 3)


def find_merge_candidates(db, *, owner_id: str, story_id: str,
                          min_similarity: float = 0.3) -> list:
    """
    §五之二.5：拿一条故事，去跟同一个人（同 owner）的其它故事比，
    返回**候选清单 + 相似度**（不合并、不改库）。

    ★ 助手不是判官：只出候选，等人确认。confidence 原样给出，不做"自动采纳阈值"。
    """
    if not owner_id or not story_id:
        return []
    s = db.query(Story).filter(Story.id == story_id).first()
    if not s:
        return []
    base_txt = _story_full_text(s)
    base_subj = extract_subject(base_txt)
    base_key = s.time_sort_key or 0

    others = (db.query(Story)
                .filter(Story.owner_id == owner_id, Story.id != story_id)
                .all())

    out = []
    for o in others:
        o_txt = _story_full_text(o)
        sim = subject_similarity(base_subj, extract_subject(o_txt))
        same_time = (o.time_sort_key or 0) == base_key and base_key != 0
        if sim < min_similarity and not same_time:
            continue
        d = decide_grouping(same_time=same_time, same_subject=sim >= 0.3,
                            subject_similarity=sim, confirmed_by_user=False)
        out.append({
            "story_id": o.id,
            "title": o.title or "",
            "summary": o.summary or "",
            "similarity": sim,
            "same_time": same_time,
            "decision": d["decision"],        # 恒为 separate（无人确认）
            "reason": d["reason"],
            "snippet": o_txt[:40],
        })

    out.sort(key=lambda x: (-x["similarity"], x["story_id"]))
    return out[:10]


def api_group_candidates(db, *, owner_id: str, viewer_id: str = "",
                         story_id: str = "") -> dict:
    """§五之二.5 接口：返回候选清单（**由人确认，不自动合并**）。"""
    actor = viewer_id or owner_id
    if not owner_id or not story_id:
        return fail("bad_request")
    s = db.query(Story).filter(Story.id == story_id).first()
    if not s:
        return fail(STORY_NOT_FOUND, "not_found")
    if s.owner_id != owner_id or not can_view_story(
            db, owner_id=owner_id, viewer_id=actor, story_id=story_id):
        return fail(NO_PERMISSION, "forbidden")

    cands = find_merge_candidates(db, owner_id=owner_id, story_id=story_id)
    return ok({
        "story_id": story_id,
        "candidates": cands,
        "n": len(cands),
        # 铁律 A：决不自动合并
        "auto_merged": False,
        "hint": "这些是「可能是同一件事」的候选，要不要合并由你点（系统不替你决定）",
    })


# ============================================================
# 五、★ 合并（唯一入口，必须人确认）
# ============================================================

def api_merge_stories(db, *, owner_id: str, viewer_id: str = "",
                      story_ids=None, target_id: str = "",
                      user_confirmed: bool = False) -> dict:
    """
    §五之二.5 收口：**人确认后才合并**（禁止全自动合并，铁律 A）。

    做法：把 `story_ids` 里除了 `target_id` 之外的条，素材**并到 target 上**，
    其余条删除；target 记同一 group_id。
    target_id 缺省 = story_ids[0]。
    """
    actor = viewer_id or owner_id
    ids = [x for x in (story_ids or []) if x]
    if not owner_id or len(ids) < 2:
        return fail("至少两条才能合并", "bad_request")
    if not user_confirmed:
        return fail(NEED_CONFIRM, "need_confirm")

    target_id = target_id or ids[0]
    if target_id not in ids:
        return fail("target_id 不在 story_ids 里", "bad_request")

    stories = {s.id: s for s in db.query(Story).filter(Story.id.in_(ids)).all()}
    if len(stories) != len(ids):
        return fail(STORY_NOT_FOUND, "not_found")

    # 权限：全部必须属于同一 owner 且能写
    for sid in ids:
        s = stories[sid]
        if s.owner_id != owner_id or not can_view_story(
                db, owner_id=owner_id, viewer_id=actor, story_id=sid):
            return fail(NO_PERMISSION, "forbidden")

    target = stories[target_id]
    gid = target.group_id or _new_id("grp")

    moved = []
    for sid in ids:
        if sid == target_id:
            continue
        src = stories[sid]
        # ★实测修正（2026-10-16 晚）：必须用 DB 查 clip，不能用 src.clips。
        #   原因：调用方若在 add/clip 后没 commit，session 里的 relationship
        #   缓存可能是空的 → 合并时会**静默丢掉素材**（真语料下的数据丢失）。
        src_clips = db.query(Clip).filter(Clip.story_id == sid).all()
        for c in src_clips:
            # ★实测修正（2026-10-16 晚）：src.clips 若已加载，子行 FK 改走后
            #   ORM flush 会把它判为 orphan(cascade delete-orphan) → 静默删除素材。
            #   先把它从 src 的关系集合里摘掉，再改 FK。（不要写 src.clips = []，
            #   那等于"把 FK 全置 NULL"，同样丢素材。）
            try:
                src.clips.remove(c)
            except (ValueError, AttributeError, Exception):
                pass
            c.story_id = target_id
            # 挂到 target 的关系集合上，保持 ORM 一致
            try:
                if c not in target.clips:
                    target.clips.append(c)
            except Exception:
                pass
            moved.append(c.id)
        # 原文并到 target（保留两段原文，不丢字）
        extra = _story_full_text(src)
        if extra:
            base = (target.raw_content or "").rstrip()
            target.raw_content = (base + "\n" + extra.lstrip()) if base else extra
        if not target.time_raw and src.time_raw:
            target.time_raw = src.time_raw
        if not target.time_label and src.time_label:
            target.time_label = src.time_label
        if not target.time_sort_key and src.time_sort_key:
            target.time_sort_key = src.time_sort_key
        # ★实测修正（2026-10-16 晚）：**绝不要写 src.clips = []**。
        #   实测后果：ORM 会把这个"清空"当成"把 FK 置 NULL 再删子行"，
        #   于是刚迁到 target 的 clip 被 cascade 删掉 → 合并后素材凭空消失。
        #   正确做法：clip 已改 story_id 走 DB，直接 db.delete(src) 即可；
        #   删父行不会碰已改走子的行（FK 已不指向它）。
        db.delete(src)

    db.flush()
    target.group_id = gid
    target.ai_group_confidence = 1.0
    target.ai_group_source = "manual"
    db.commit()
    db.expire_all()

    return ok({
        "target_story_id": target_id,
        "group_id": gid,
        "merged_story_ids": [x for x in ids if x != target_id],
        "moved_clip_ids": moved,
        "n_stories": 1,
    })


# ============================================================
# 六、拆卸（分错可修 —— §五之二.4"分错可修"，给退路）
# ============================================================

def api_ungroup_story(db, *, owner_id: str, viewer_id: str = "",
                      story_id: str = "") -> dict:
    """把一条故事从它的 group 里摘出来（`group_id` 置空）——分错可修的退路。"""
    actor = viewer_id or owner_id
    if not owner_id or not story_id:
        return fail("bad_request")
    s = db.query(Story).filter(Story.id == story_id).first()
    if not s:
        return fail(STORY_NOT_FOUND, "not_found")
    if s.owner_id != owner_id or not can_view_story(
            db, owner_id=owner_id, viewer_id=actor, story_id=story_id):
        return fail(NO_PERMISSION, "forbidden")
    old = s.group_id
    s.group_id = None
    s.ai_group_source = "manual"
    s.ai_group_confidence = 0.0
    db.commit()
    return ok({"story_id": story_id, "old_group_id": old, "group_id": None})
