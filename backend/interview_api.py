"""
往事可追忆 - 采访引导（AI 当记者）接口 handler 层 v1.0
建立：2026-10-08（日历 10-08 原文「按反馈修复」——出码仍卡 sandy 账号授权、
      真机反馈未到手，依硬规矩 5「卡点不架空日历」转做第2期后端 §七 采访引导）

=== 本文件干什么（覆盖 v2.4 §七 + §5.3）===
1. `api_start_interview`    开始一次采访：AI 记者主动出第一问（优先问「人生锚点」）
2. `api_next_question`      老人回答完 → 出下一问（**打断不丢话题**：先接回刚才那问）
3. `api_barge_in`           ★「老人打断」——老人一出声，判定 AI 该不该 1 秒内闭嘴
4. `api_ask_classify`       ★自述页归类问「这段是新的一件事吗？」（第2期真机试后启用）
5. `api_classify_answer`    老人对归类问的回答 → 归到「新建 / 某一件」（安全兜底：含糊=新建）
6. `api_set_interview_pref` 「别问了」开关 + 打断灵敏度档位（内部档）

=== 铁律（v2.4 §七，逐字执行）===
A. **打断要快**：老人出声 → AI 帧内停（`stop_tts=True`），后端只做判定，不抢麦
B. **打断不丢话题**：被打断时把「刚才问的」存进 `pending_question`，老人说完接着聊
C. **AI 主动让路**：每问完一句要留等待（`wait_ms`），不连珠炮
D. **允许跑题**：老人说别的，AI 顺着走（`follow_digression=True`），不硬拉
E. **灵敏度档位**：供嘈杂环境（免提/电视/哭声）调 `sensitivity`（low/normal/high）
F. **任何反应都不算错**：永远有安全默认（含糊→新建），绝不卡住老人
G. **频率保护（防烦）**：那年只有1件事 → 不弹；连续多段 → 攒起来一起问；说过「别问了」→ 不再问
H. **采访中应有意自然询问锚点**（"您是哪年结的婚呀？"）——不是闲聊，是给时间轴打地基（§5.3）
I. **【待验证】不得凭印象承诺**：1 秒延迟能否达成需真机测（本层只给判定接口，不做延迟承诺）

=== 设计口径（与 timeline_api / anchor_api 一致）===
- handler 不自己开 session，db 由调用方传
- 统一信封 {ok, data, error, code}
- 不另造时间解析：锚点走 anchor_api，权限走 permissions
"""

from datetime import datetime
import json

from permissions import can_view_story, visible_stories
from anchor_api import get_anchors, api_get_anchors
from models import (
    SessionLocal, Story, User, Member, LifeAnchor, TimePrecision,
)


NO_PERMISSION = "你没有权限参与这本书的采访"
STORY_NOT_FOUND = "找不到这条故事"
BAD_REQUEST = "这个请求不太对"


# ============================================================
# 一、统一信封（与 story_api / timeline_api / anchor_api 同款）
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
# 二、常量：锚点类型 → 自然询问话术（§5.3「有意自然询问」）
# ============================================================

# 顺序 = 询问优先级（先问最早、最根本的：出生年定了，后面全能反推）
ANCHOR_QUESTIONS = [
    ("birth",   "老人家，您是哪年出生的呀？",
                "那年您出生在什么地方、家里排行老几？"),
    ("work",    "您是哪年开始上班（下地干活）的？",
                "头一份活是干啥的？"),
    ("marriage", "您是哪年结的婚呀？",
                "那年办得热闹不？"),
    ("child_birth", "老大是哪年生的？",
                "生老大那会儿，家里什么光景？"),
    ("move",    "您是哪年搬到这儿的？",
                "为啥搬过来的？"),
]

# 锚点类型 → 展示名（与 anchor_api 口径一致）
ANCHOR_LABEL = {
    "birth": "出生", "work": "参加工作", "marriage": "结婚",
    "child_birth": "孩子出生", "move": "搬迁",
}

# 打断灵敏度档位 → 判定阈值（供真机校准；单位：毫秒）
# 老人说话音量超过阈值即判「真出声、该让路」，避免把电视/哭声误判成说话
SENSITIVITY = {
    "low":    {"energy_db": -20.0, "silence_ms": 350},   # 嘈杂环境：难触发、更稳
    "normal": {"energy_db": -32.0, "silence_ms": 250},   # 默认
    "high":   {"energy_db": -42.0, "silence_ms": 150},   # 安静/老人声音小：好触发
}

# 归类问：老人含糊应答词 → 视为「没答清楚」
_VAGUE_YES = {"嗯", "对", "好", "行", "中", "是", "嗯嗯", "对对", "好的", "知道了"}
# 老人表示「没听清 / 让重说」
_MISHEARD = {"什么", "没听清", "再说一遍", "啊？", "啥", "再说一次", "听不清"}


def _normalize(text: str) -> str:
    return (text or "").strip().replace(" ", "").replace("，", "").replace(",", "").rstrip("。.！!？?")


# ============================================================
# 三、采访会话语义（无状态：一次调用带齐上下文，便于前端切页/重试）
# ============================================================

def _anchor_of(db, *, owner_id: str, anchor_type: str):
    """取某个类型的锚点年份（已确认优先，其次任意采到的）。"""
    rows = (db.query(LifeAnchor)
              .filter(LifeAnchor.owner_id == owner_id,
                      LifeAnchor.anchor_type == anchor_type)
              .all())
    if not rows:
        return None
    confirmed = [r for r in rows if r.confirmed and r.year]
    if confirmed:
        return confirmed[0].year
    withyear = [r for r in rows if r.year]
    return withyear[0].year if withyear else None


def _missing_anchors(db, *, owner_id: str) -> list:
    """还缺哪些锚点（按 ANCHOR_QUESTIONS 优先级返回未采到的类型）。"""
    out = []
    for atype, q, _follow in ANCHOR_QUESTIONS:
        if _anchor_of(db, owner_id=owner_id, anchor_type=atype) is None:
            out.append(atype)
    return out


def _pick_anchor_question(db, *, owner_id: str):
    """挑下一句该问的锚点（§5.3：采访中应有意自然询问）。都齐了就返回 None。"""
    missing = _missing_anchors(db, owner_id=owner_id)
    if not missing:
        return None
    want = missing[0]
    for atype, q, follow in ANCHOR_QUESTIONS:
        if atype == want:
            return {
                "kind": "anchor",
                "anchor_type": atype,
                "anchor_label": ANCHOR_LABEL.get(atype, atype),
                "text": q,
                "follow_up": follow,
                "audio_hint": "语音播放（老人只用听）",
            }
    return None


def _fallback_question(db, *, owner_id: str) -> dict:
    """锚点问完了 → 用「最近一条待定故事」引一句开放问题，让老人接着讲。"""
    pend = (db.query(Story)
              .filter(Story.owner_id == owner_id)
              .order_by(Story.created_at.desc())
              .first())
    if pend is not None:
        raw = (pend.time_raw or "").strip()
        if raw:
            return {
                "kind": "open",
                "anchor_type": "",
                "anchor_label": "",
                "text": f"您刚说的「{raw}」那段，能再多讲讲不？",
                "follow_up": "想多说啥都行，我听着。",
                "audio_hint": "语音播放（老人只用听）",
            }
    return {
        "kind": "open",
        "anchor_type": "",
        "anchor_label": "",
        "text": "您想从哪段日子说起？",
        "follow_up": "想到哪儿说到哪儿，不着急。",
        "audio_hint": "语音播放（老人只用听）",
    }


# ============================================================
# 四、对外接口 1：开始采访 / 出下一问
# ============================================================

def api_start_interview(db, *, owner_id: str, viewer_id: str = "") -> dict:
    """
    开始一次采访：AI 记者主动出第一问（§7.1「主动引导老人讲」，不是干等）。
    优先级：先问「人生锚点」（§5.3 给时间轴打地基）→ 齐了再问开放问题。
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")
    if viewer_id and not can_view_story(db, owner_id=owner_id, viewer_id=viewer_id,
                                        story_id=""):
        # viewer 连「整本可见」都没有（既非主人也非家人）→ 拒绝
        return fail(NO_PERMISSION, "forbidden")

    q = _pick_anchor_question(db, owner_id=owner_id) or _fallback_question(db, owner_id=owner_id)
    missing = _missing_anchors(db, owner_id=owner_id)

    return ok({
        "question": q,
        "missing_anchors": missing,
        "state": "asking",
        # 「AI 主动让路」：问完留等待（不连珠炮），前端据此不立即追下一句
        "wait_ms": 1800,
        # 「允许跑题」：老人说别的，顺着走
        "follow_digression": True,
        "asked_at": datetime.utcnow().isoformat(),
    })


def api_next_question(db, *, owner_id: str, viewer_id: str = "",
                      last_answer: str = "", interrupted_question: str = "",
                      interrupt_count: int = 0) -> dict:
    """
    老人答完 → 出下一问。

    ★「打断不丢话题」（铁律 B）：若上一问被打断（interrupted_question 非空）
    且老人还没答清楚 → **先接回刚才那问**，不换题。
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")

    ans = _normalize(last_answer)
    pending_q = (interrupted_question or "").strip()

    # 被打断且老人这句没构成有效回答（空 or 含糊）→ 接回刚才的问题
    if pending_q and (not ans or ans in _VAGUE_YES):
        return ok({
            "question": {
                "kind": "resume",
                "anchor_type": "",
                "anchor_label": "",
                "text": pending_q,          # 原样接回，不换题
                "follow_up": "您慢慢说，我接着听。",
                "audio_hint": "语音播放（老人只用听）",
            },
            "state": "resumed",
            "wait_ms": 1800,
            "follow_digression": True,
        })

    # 正常出下一问
    q = _pick_anchor_question(db, owner_id=owner_id) or _fallback_question(db, owner_id=owner_id)
    return ok({
        "question": q,
        "missing_anchors": _missing_anchors(db, owner_id=owner_id),
        "state": "asking",
        "wait_ms": 1800,
        "follow_digression": True,
    })


# ============================================================
# 五、对外接口 2：★ 打断（barge-in）
# ============================================================

def api_barge_in(db, *, owner_id: str = "", energy_db: float = None,
                 assuming_norm: str = "") -> dict:
    """
    ★「老人打断」硬要求（§7.2）。

    本层只做**判定**：老人一出声 → 告诉前端「立刻停 TTS」；
    真实 1 秒延迟由前端录音/播放切换决定（【待验证】须真机测，本层不承诺）。

    输入（前端采集到的信号）：
    - energy_db：当前环境能量（dB），与灵敏度档位阈值比
    - assuming_norm：假噪声类型 normal / tv / crowd / baby（嘈杂环境用低灵敏）

    输出：
    - stop_tts：是否该1秒内闭嘴（True=停）
    - hold_topic：要不要记住刚才问的（打断后接着聊）
    - follow_digression：允许跑题
    """
    # 灵敏度：按 assume_norm 自动选档（嘈杂→low），否则默认 normal
    gear = "normal"
    if assuming_norm in ("tv", "crowd", "baby", "noisy"):
        gear = "low"
    thr = SENSITIVITY[gear]

    if energy_db is None:
        # 前端没给能量 → 只要它明确报「老人出声了」，就保守判「停」（安全侧）
        stop = True
    else:
        stop = float(energy_db) > thr["energy_db"]

    return ok({
        "stop_tts": stop,                 # 铁律 A：1 秒内停
        "hold_topic": True,               # 铁律 B：不丢话题
        "follow_digression": True,        # 铁律 D：允许跑题
        "sensitivity_gear": gear,         # 铁律 E：内部档位
        "silence_ms": thr["silence_ms"],  # 端到端静音判定窗（供前端校准）
    })


# ============================================================
# 六、对外接口 3：★ 自述页归类问（§7.3，第2期真机试后启用）
# ============================================================

# 频率保护：同一年/同一组攒够几段才问
CLASSIFY_MIN_CLUSTER = 2
# 重问上限
CLASSIFY_MAX_RETRY = 2


def api_ask_classify(db, *, owner_id: str, viewer_id: str = "",
                     new_story_id: str = "") -> dict:
    """
    自述页保存完 → 判断「要不要弹归类问」。

    ★频率保护（铁律 G，防烦）：
    - 那年（那段）只有 1 件事 → 不问（`ask=False`，理由 single_in_year）
    - 用户说过「别问了」→ 不问（`ask=False`，理由 muted）
    - 连续多段 → 攒够 CLASSIFY_MIN_CLUSTER 段才问一次

    问法（§7.3 结论）：语音问 + 大字按钮兜底，老人口头答。
    含糊（嗯/对）→ 默认新建（安全侧，铁律 F）。
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")

    # 「别问了」开关（存在 user 上；见 api_set_interview_pref）
    u = db.query(User).filter(User.id == owner_id).first()
    prefs = _load_prefs(u)
    if prefs.get("muted_ask"):
        return ok({"ask": False, "reason": "muted", "retry_left": 0})

    # 数该主人同一「时间桶」下有几条故事（同一年份/同一待定池）
    same_bucket = _count_same_bucket(db, owner_id=owner_id, story_id=new_story_id)
    if same_bucket < CLASSIFY_MIN_CLUSTER:
        return ok({"ask": False, "reason": "single_in_year", "cluster_n": same_bucket})

    return ok({
        "ask": True,
        "reason": "cluster",
        "cluster_n": same_bucket,
        "question": {
            "kind": "classify",
            "text": "这段是新的一件事吗？",
            "audio_hint": "自动语音播放（老人只用说）",
            "buttons": [
                {"key": "new", "label": "新的一件事"},
                {"key": "existing", "label": "是上面的某一件"},
            ],
            # 5 秒无反应 → 浮出大字按钮（前端据此计时）
            "fallback_buttons_after_ms": 5000,
        },
        "retry_left": CLASSIFY_MAX_RETRY,
        "safe_default": "new",           # 铁律 F：始终有安全默认
    })


def api_classify_answer(db, *, owner_id: str, viewer_id: str = "",
                        new_story_id: str = "", answer_text: str = "",
                        answer_key: str = "", retry_used: int = 0) -> dict:
    """
    老人对归类问的回答 → 决定归到「新建 / 某一件」。

    规则（§7.3，逐字执行）：
    - 答「是上面的某一件 / 说具体某事」→ existing（需前端再选具体哪件）
    - 含糊（「嗯/对/好」）→ **默认新建**（安全侧，铁律 F）
    - 「什么？/没听清」→ **重问，最多 2 次**；用完仍听不清 → 默认新建，不纠缠
    - 始终无反应 → 默认新建（前端在超时后按 safe_default 调本接口，answer_key='timeout'）
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")

    key = (answer_key or "").strip().lower()
    txt = _normalize(answer_text)
    retry_used = int(retry_used or 0)

    # 前端已判定超时无反应 → 不纠缠，直接默认新建
    if key == "timeout":
        return ok({"decision": "new", "retry": False, "reason": "timeout_safe_default"})

    # 明确的按钮选择
    if key in ("new", "existing"):
        return ok({"decision": key, "retry": False, "reason": "button"})

    # 老人说「没听清」→ 重问（最多 2 次）
    if txt in _MISHEARD:
        if retry_used < CLASSIFY_MAX_RETRY:
            return ok({
                "decision": None, "retry": True, "retry_used": retry_used + 1,
                "reason": "misheard",
                "question": {"kind": "classify", "text": "这段是新的一件事吗？",
                             "buttons": [
                                 {"key": "new", "label": "新的一件事"},
                                 {"key": "existing", "label": "是上面的某一件"},
                             ]},
            })
        # 重问用完仍听不清 → 默认新建，不纠缠
        return ok({"decision": "new", "retry": False, "reason": "retry_exhausted_safe_default"})

    # 含糊应答（嗯/对/好）→ 默认新建（安全侧）
    if txt in _VAGUE_YES or not txt:
        return ok({"decision": "new", "retry": False, "reason": "vague_safe_default"})

    # 其余（老人说了具体内容）→ 视为「是上面某一件」，需前端再定位
    return ok({"decision": "existing", "retry": False, "reason": "spoken",
               "need_pick_story": True})


def _count_same_bucket(db, *, owner_id: str, story_id: str) -> int:
    """
    数「同一时间桶」下有几条故事——用于频率保护（那年只有1件事则不弹）。
    时间桶口径：同 time_sort_key（有年份）；无年份的（待定）算同一个「待定池」。
    """
    if not story_id:
        # 没指定 → 用「待定池」条数近似
        return (db.query(Story)
                  .filter(Story.owner_id == owner_id,
                          Story.time_sort_key == 0)
                  .count())
    s = db.query(Story).filter(Story.id == story_id).first()
    if s is None:
        return 0
    if s.time_sort_key:
        return (db.query(Story)
                  .filter(Story.owner_id == owner_id,
                          Story.time_sort_key == s.time_sort_key)
                  .count())
    return (db.query(Story)
              .filter(Story.owner_id == owner_id,
                      Story.time_sort_key == 0)
              .count())


# ============================================================
# 七、对外接口 4：「别问了」开关 + 打断灵敏度档位
# ============================================================

def _load_prefs(u) -> dict:
    """
    从 User 上读采访偏好（存在 User.prefs JSON 扩展点；无则返回空 dict）。

    ⚠️ 铁律（10-08 踩过，真 bug）：**必须返回副本，不能把 u.prefs 本体返回出去**。
    否则调用方 in-place 改这个 dict（prefs["muted_ask"]=True）时，SQLAlchemy 的
    JSON 列**不跟踪原地修改**——它与加载快照比是 same object → 判为 unchanged →
    commit 不写回，值回退成库里旧值。故此处 copy 一份新 dict，调用方再赋值回去才会触发写。
    """
    if u is None:
        return {}
    raw = getattr(u, "prefs", None)
    if isinstance(raw, dict):
        return dict(raw)          # ← 副本，防原地改丢更新
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return dict(v) if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def api_set_interview_pref(db, *, owner_id: str, muted_ask: bool = None,
                           sensitivity: str = "") -> dict:
    """
    设置采访偏好：
    - muted_ask=True → 老人说过「别问了」，此后不再弹归类问（铁律 G）
    - sensitivity：打断灵敏度档位 low/normal/high（内部档，应付嘈杂环境）
    """
    if not owner_id:
        return fail(BAD_REQUEST, "bad_request")
    if sensitivity and sensitivity not in SENSITIVITY:
        return fail("灵敏度只能是 low / normal / high", "bad_request")

    u = db.query(User).filter(User.id == owner_id).first()
    prefs = _load_prefs(u)
    if muted_ask is not None:
        prefs["muted_ask"] = bool(muted_ask)
    if sensitivity:
        prefs["sensitivity"] = sensitivity
    if u is not None:
        try:
            u.prefs = prefs
            db.commit()
        except Exception:
            db.rollback()
            return fail("保存偏好失败（User.prefs 字段待补）", "storage_not_configured",
                        prefs=prefs)

    return ok({
        "prefs": prefs,
        "sensitivity": prefs.get("sensitivity", "normal"),
        "muted_ask": bool(prefs.get("muted_ask", False)),
        "muted_note": "已记下，往后不问了" if prefs.get("muted_ask") else "",
    })


# ============================================================
# 八、自测说明（见 selftest_interview_api.py，本文件不内联跑）
# ============================================================
