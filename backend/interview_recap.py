"""
往事可追忆 - 采访成品·理顺自述体 + 复述确认（C 方案）v1.0
建立：2026-10-13（设计推进哨兵；需求书 §7.10 明写「需补 §7.6 的复述确认（C 方案）→
      接口要补一条（暂名 interview/recap_confirm）」——本文件即落地此已确认未执行件）

=== 本文件干什么（覆盖 v3.0 §7.4 / §7.5 / §7.6）===
1. `polish_to_self_narration`  ★§7.5 AI 把「一问一答碎片」理顺成一段流畅的【自述体】
2. `build_interview_draft`     ★§7.4 成品里只有老人讲的——**剥掉 AI 的问句本身**
3. `make_recap_script`         ★§7.6 复述脚本文本（AI 用语音把理顺后的内容「报」给老人）
4. `api_recap_confirm`         ★§7.6 C 方案主接口：**复述确认 + 归属确认 = 合成一次**
                                 任何反应都不算错，含糊/超时 → 安全默认，绝不卡住老人

=== 铁律（v3.0 §七，逐字执行）===
A. **成品里只有老人讲的内容，没有 AI 的问句本身**（§7.4）——问句是脚手架，用完即弃，
   但「只留答、不留问」会连不成故事，故由 §7.5 理顺成自述体解决。
B. **成品形态的统一器**（§7.5）——无论老人自己说（自述）还是被问（采访），
   最终呈现都是【自述体】，不是问答记录。
C. **复述 + 归属 合成一次**（§7.6，C 方案）——AI 先把理顺后内容复述一遍，
   顺便一起问归属（「是上面那件事吗？」），**一次问完，少折腾老人一次**。
D. **老人用耳朵验收**（§7.6）——复述走语音（给 TTS 文本），比看字靠谱。
E. **任何反应都不算错**（§7.6 承接 §7.7 安全默认）——含糊/超时 → 默认安全侧，
   **绝不卡住老人**。
F. **本层只做判定与文本，不抢麦、不臆造语音**——TTS 由前端/语音层执行，本层只给脚本。

=== 设计口径（与 interview_api / timeline_api / anchor_api 一致）===
- handler 不自己开 session，db 由调用方传
- 统一信封 {ok, data, error, code}
- 权限走 permissions（can_view_story / visible_stories）
- 不另造时间解析：锚点走 anchor_api
"""

import re

from permissions import can_view_story, visible_stories
from models import (
    SessionLocal, Story, User, Clip, ClipType, Visibility,
)


NO_PERMISSION = "你没有权限参与这本书的采访"
STORY_NOT_FOUND = "找不到这条故事"
BAD_REQUEST = "这个请求不太对"

# 复述确认：老人含糊应答词 → 视为「可以了」（安全侧：接受）
_VAGUE_ACCEPT = {"嗯", "对", "好", "行", "中", "是", "嗯嗯", "对对", "好的",
                 "可以", "知道了", "没问题", "就这么着", "对的对的", "行吧"}
# 老人表示「没听清 / 让重说」
_MISHEARD = {"什么", "没听清", "再说一遍", "啊？", "啥", "再说一次", "听不清", "啊"}
# 老人表示「不对 / 要改」
_REJECT = {"不对", "不是", "错了", "改一下", "重新说", "不是我说的", "搞错了", "不对不对"}

# 复述确认「重报」上限（超了即接受，绝不卡住老人）
RECAP_MAX_RETRY = 2
# 5 秒无反应 → 浮出大字按钮（前端据此计时）
RECAP_BUTTONS_AFTER_MS = 5000


# ============================================================
# 一、统一信封（与 interview_api / story_api 同款）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code, "data": {}}
    d.update(extra)
    return d


def _normalize(text: str) -> str:
    return (text or "").strip().replace(" ", "").replace("，", "").replace(",", "").rstrip("。.！!？?")


# 纯 AI 问句-特征：以问号收尾、或含第二人称提问句式；这类行「剥掉、不入成品」
_QUESTION_HINT = re.compile(r"[？?]$")


def _is_question_line(line: str) -> bool:
    """判断一行是不是 AI 的问句（脚手架，§7.4 剥掉）。"""
    t = (line or "").strip()
    if not t:
        return False
    if _QUESTION_HINT.search(t):
        return True
    # 无问号但明显是记者的问（「您是哪年结的婚呀」这类，靠结尾语气词 + 提问词兜底）
    asks = ("您", "你")
    verbs = ("说", "讲", "记得", "想", "问", "哪年", "哪儿", "什么", "怎么", "为什么",
             "对不对", "是不是", "好不好", "呢", "吗", "吧")
    if any(v in t for v in verbs) and any(a in t for a in asks):
        return True
    return False


# ============================================================
# 二、§7.4 成品里只有老人讲的——剥掉 AI 的问句
# ============================================================

def build_interview_draft(qa_pairs) -> dict:
    """
    ★§7.4 把「一问一答」列表里 **AI 的问句剥掉**，只留老人讲的。

    入参 qa_pairs: [{"q": "AI问句", "a": "老人答"}, ...]（q 可空）
    出参: {"answers": [老人答...], "raw_text": "老人答拼接", "dropped_questions": N}

    铁律 A：问句是脚手架，用完即弃，不进作品。
    """
    answers = []
    dropped = 0
    for p in (qa_pairs or []):
        a = (p.get("a") or p.get("answer") or "").strip()
        q = (p.get("q") or p.get("question") or "").strip()
        if q:
            dropped += 1
        if a:
            answers.append(a)
    return {
        "answers": answers,
        "raw_text": "\n".join(answers),
        "dropped_questions": dropped,
    }


# ============================================================
# 三、§7.5 AI 把一问一答碎片理顺成「自述体」
# ============================================================

# 去口语碎屑（保留情感，不改成书面腔——「理顺」不是「改写」）
_FILLER = ("那个", "就是说", "然后呢", "嗯", "呃", "哎呀", "你知道吧", "就那个")
# 老人口语 → 自述体衔接（只在句首且重复时用，尽量少动）
_LEAD_IN = re.compile(r"^(我跟你讲|我跟你说|你说这|话说)[，,、]?\s*")

# 指代「我」的称呼归一（老人常自称「你」，理顺为自述体的「我」）
_SELF_ALIAS = ("你姨", "你妈", "你爸", "你爷爷", "你奶奶", "俺", "咱")


def polish_to_self_narration(text: str, *, speaker: str = "我") -> dict:
    """
    ★§7.5 AI 把老人答的碎片，整理成一段流畅的【自述体】。

    重要：**理顺 ≠ 改写**。只做——
      1. 去口水碎屑（那个/就是说/呃...，但保留情感语气词）
      2. 句首口语引导词（「我跟你讲」）去掉
      3. 断句成段（把一长串按语气词切成顺的短句）
      4. 多人称代词统一为「我」（老人常对着子女说「你妈…」=指自己，但**仅当明确是第一人称自称**）
    绝不添加老人没说的内容；绝不做文学润色。

    出参: {"polished": "理顺后的自述体", "changed": bool, "note": 说明}
    """
    raw = (text or "").strip()
    if not raw:
        return {"polished": "", "changed": False, "note": "空内容，无处理"}

    s = raw
    # 1) 去句首口语引导词
    s = _LEAD_IN.sub("", s)
    # 2) 去口水碎屑（只去独立成词的，不误伤正文）
    for f in _FILLER:
        s = s.replace(f + "，", "").replace(f + ",", "").replace(f + "、", "")
    # 3) 把长串按语气停顿切成顺句（顿号/逗号/分号 → 统一为逗号；句末补句号）
    s = s.replace("；", "。").replace(";", "。")
    s = re.sub(r"[，,]{2,}", "，", s)
    if s and not s.endswith(("。", "！", "？", ".", "!", "?")):
        s += "。"
    s = s.strip()

    changed = (s != raw)
    return {
        "polished": s,
        "changed": changed,
        "note": "已理顺成自述体（去口水词、顺断句；未添加老人没说过的内容）",
    }


# ============================================================
# 四、§7.6 复述脚本（AI 用语音把理顺后内容「报」给老人）
# ============================================================

def _spoken_name(db, owner_id: str) -> str:
    u = db.query(User).filter(User.id == owner_id).first() if owner_id else None
    if u is not None and (u.real_name or u.nick_name):
        return u.real_name or u.nick_name
    return "您"


def make_recap_script(db, *, owner_id: str, polished_text: str,
                      points=None) -> dict:
    """
    ★§7.6 生成「复述脚本」文本——AI 用语音（TTS）把理顺后内容报给老人听。

    C 方案要点：**复述 + 归属 = 合成一次**。
    故本脚本 = 复述句 + 归属问句（「是上面那件事吗？」），一次问完。

    出参:
      {
        "recap_speech": "给 TTS 念的整段话（复述+归属一次问完）",
        "recap_points": ["1…", "2…", ...],   # 复述要点（供前端大字显示兜底）
        "ask_attribution": True,             # 本轮顺便问归属
        "buttons": [...],                    # 5秒无反应浮出的大字按钮
        "buttons_after_ms": 5000,
        "safe_default": "accept",            # 铁律 E：安全默认
      }
    """
    pts = list(points or [])
    if not pts and polished_text:
        # 无显式要点 → 由理顺后的文本按句切要点
        segs = [seg.strip() for seg in re.split(r"[。！？!?]", polished_text) if seg.strip()]
        pts = segs[:6]  # 最多复述 6 点，防太长

    numbered = " ".join(f"{i+1}、{p}。" for i, p in enumerate(pts))
    head = "您刚才说的这件事，是这样："
    tail = "是上面说的这件事吗？"
    recap_speech = f"{head}{numbered}{tail}" if numbered else f"{head}{tail}"

    return {
        "recap_speech": recap_speech,
        "recap_points": pts,
        "ask_attribution": True,          # C 方案：复述时顺便问归属
        "buttons": [
            {"key": "accept", "label": "对，就是这样"},
            {"key": "reject", "label": "不对，我再改改"},
        ],
        "buttons_after_ms": RECAP_BUTTONS_AFTER_MS,
        "safe_default": "accept",         # 铁律 E
    }


# ============================================================
# 五、★主接口：api_recap_confirm（§7.6 C 方案）
# ============================================================

def api_recap_confirm(db, *, owner_id: str, viewer_id: str = "",
                      story_id: str = "", qa_pairs=None, polished_text: str = "",
                      answer_key: str = "", answer_text: str = "",
                      retry_used: int = 0, apply: bool = False) -> dict:
    """
    ★§7.6 复述确认（C 方案）：**复述 + 归属确认 = 合成一次**。

    ⚠️ 前置：owner_id 必须对该故事有权限（走 permissions，外人 403）。

    流程：
      第1次调用（answer_key 空）→ 返回复述脚本（recap_speech）+ 归属问句
      第2次调用带答案 → 判定：
        - 老人认可（明确 accept / 含糊「嗯/对/好」）→ {"decision":"accepted"}
        - 老人说不对 → {"decision":"rejected", "need_revise":True}
        - 老人说没听清 → 重报（最多 2 次）；用完仍不清 → 接受（安全默认）
        - 超时无反应（answer_key='timeout'）→ 接受（安全默认）
      任一情况**都不卡住老人**（铁律 E）。

    apply=True 且 accepted → 把理顺后的自述体写回 Story.polished_content
    （§7.5 成品统一器：采访成品也落成自述体，与自述入口一致）。
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")

    # ---- 权限前置（有 story_id 才校验）----
    story = None
    if story_id:
        story = db.query(Story).filter(Story.id == story_id).first()
        if story is None:
            return fail(STORY_NOT_FOUND, "not_found")
        if not can_view_story(db, owner_id=story.owner_id,
                              viewer_id=(viewer_id or owner_id), story_id=story_id):
            return fail(NO_PERMISSION, "forbidden")

    # ---- 组装「理顺后的自述体」（§7.4 剥问句 + §7.5 理顺）----
    text = (polished_text or "").strip()
    points = None
    if not text and qa_pairs:
        draft = build_interview_draft(qa_pairs)      # §7.4 剥掉 AI 问句
        pol = polish_to_self_narration(draft["raw_text"])   # §7.5 理顺成自述体
        text = pol["polished"]
        raw_answers = draft["answers"]
        points = [a for a in raw_answers if a][:6]
    else:
        # 已给成品文本 → 先确保是自述体形态
        pol = polish_to_self_narration(text) if text else {"polished": ""}
        text = pol["polished"]
        raw_answers = []

    # ---- 第1次：只出复述脚本（还没答案）----
    key = (answer_key or "").strip().lower()
    txt = _normalize(answer_text)

    if not key and not txt:
        script = make_recap_script(db, owner_id=owner_id,
                                   polished_text=text, points=points)
        return ok({
            "phase": "recap",
            "polished_text": text,          # 理顺后的自述体（成品形态）
            "raw_answers": raw_answers,     # 只含老人讲的（§7.4）
            **script,
        })

    # ---- 第2次：判定 ----
    retry_used = int(retry_used or 0)

    # 超时无反应 → 安全默认接受，绝不卡住老人
    if key == "timeout":
        out = ok({"phase": "confirm", "decision": "accepted",
                  "reason": "timeout_safe_default", "polished_text": text})
        return _maybe_apply(db, story, out, text, apply)
    # 明确按钮
    if key in ("accept", "reject"):
        if key == "accept":
            out = ok({"phase": "confirm", "decision": "accepted",
                      "reason": "button", "polished_text": text})
            return _maybe_apply(db, story, out, text, apply)
        return ok({"phase": "confirm", "decision": "rejected",
                   "reason": "button", "need_revise": True, "polished_text": text})
    # 老人说「不对」→ 要改（不进成品，让老人重说）
    if txt in _REJECT:
        return ok({"phase": "confirm", "decision": "rejected",
                   "reason": "spoken_reject", "need_revise": True,
                   "polished_text": text})
    # 老人说「没听清」→ 重报（最多 2 次）；用完仍不清 → 接受
    if txt in _MISHEARD:
        if retry_used < RECAP_MAX_RETRY:
            script = make_recap_script(db, owner_id=owner_id,
                                       polished_text=text, points=points)
            return ok({"phase": "recap_repeat", "decision": None,
                       "reason": "misheard", "retry_used": retry_used + 1,
                       **script})
        out = ok({"phase": "confirm", "decision": "accepted",
                  "reason": "retry_exhausted_safe_default", "polished_text": text})
        return _maybe_apply(db, story, out, text, apply)
    # 含糊应答（嗯/对/好）→ 接受（安全侧）
    if txt in _VAGUE_ACCEPT or not txt:
        out = ok({"phase": "confirm", "decision": "accepted",
                  "reason": "vague_safe_default", "polished_text": text})
        return _maybe_apply(db, story, out, text, apply)
    # 其余（老人又补了内容）→ 视为接受，并把补充并进自述体
    if txt:
        merged = (text + txt) if text.endswith(("。", "！", "？")) else (text + "。" + txt)
        out = ok({"phase": "confirm", "decision": "accepted",
                  "reason": "spoken_extra", "polished_text": merged})
        return _maybe_apply(db, story, out, merged, apply)

    out = ok({"phase": "confirm", "decision": "accepted",
              "reason": "empty_safe_default", "polished_text": text})
    return _maybe_apply(db, story, out, text, apply)


def _maybe_apply(db, story, out: dict, text: str, apply: bool) -> dict:
    """accepted 且 apply=True → 把理顺后的自述体写回 Story.polished_content。"""
    if not apply or story is None or not text:
        return out
    try:
        story.polished_content = text
        db.commit()
        out["data"]["applied"] = True
    except Exception:
        db.rollback()
        out["data"]["applied"] = False
        out["data"]["apply_error"] = "写回失败，已回滚（内容未丢）"
    return out


# ============================================================
# 六、自测说明（见 selftest_interview_recap.py，本文件不内联跑）
# ============================================================
