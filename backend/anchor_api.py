"""
往事可追忆 - 人生锚点表 接口 handler 层 v1.0
建立：2026-10-07（日历波谷日任务：出码仍卡在开发者工具/sandy账号授权，转做第2期后端）

=== 为什么是今天做 ===
日历 10-06~10-07 标为**天然波谷**（等出码窗口），规矩是"不空转、转做第2期"。
第2期核心 = 时间轴「能排对」。而「能排对」的灵魂是 **§5.3 人生锚点表**：
    一旦采到锚点（出生年/结婚年/老大出生年），后续所有「我八岁那年」「嫁过来第二年」
    这类**相对时间**才能自动换算成绝对年份，否则只能全丢进【时间待定】。
现状：models.py §八 已有 LifeAnchor 表，timeline.py 已有 extract_time(anchors=..) / extract_anchors()，
      **但两者之间没有任何代码把它们接起来**——表是死的，锚点采集只扫 title/summary（漏掉正文/语音转写），
      且从不落库。本文件就是把这条链路接通。

=== 本文件干什么（覆盖 v2.4 §5.3）===
1. `harvest_anchors(db, owner_id)`  扫整本书的正文/标题/摘要/语音转写 → 采集锚点 → 落 LifeAnchor 表（幂等 upsert）
2. `get_anchors(db, owner_id)`      把 LifeAnchor 表读成 extract_time 要的 {'birth_year':.., 'marriage_year':..} dict
3. `api_get_anchors(owner_id)`      前端可查"这本书已知道哪些锚点"
4. `api_upsert_anchor(...)`         用户手动纠正/确认锚点（最高优先级，confirmed=True 不再被自动覆盖）

=== 铁律（逐字执行）===
1. **不瞎猜**：extract_anchors 只认「明确的年份陈述」（"1950年出生""1972年结的婚"），
   采不到就**不写**，绝不用相对表述去凑一个锚点（v2.4 §5.4 保命线）。
2. **只在后端算**：锚点采集/换算全在后端，前端零计算（时间轴接口定义 §三铁律①）。
3. **用户确认优先**：confirmed=True 的锚点，harvest 不得覆盖（同 §5.5 的"改过不许被覆盖"）。
4. **幂等**：同一 (owner_id, anchor_type) 只一行；重复 harvest 结果一致，不产生脏行。
5. **隔离**：本层不碰生产库路径；测试一律走 /tmp 临时库（见 selftest）。

=== 设计口径（与 story_api / timeline_api 一致）===
- handler 不自己开 session，db 由调用方传
- 统一信封 {ok, data, error, code}
- 时间解析复用 timeline.py 的 extract_anchors，**不另造一套**
"""

import uuid

from models import (
    Story, Clip, LifeAnchor, ClaimStatus,
    TimePrecision,
)
from timeline import extract_anchors


# ============================================================
# 信封（与 story_api / timeline_api 同款）
# ============================================================

def ok(data=None):
    return {"ok": True, "data": data if data is not None else {}, "error": "", "code": "OK"}


def fail(code, error):
    return {"ok": False, "data": {}, "error": error, "code": code}


# ============================================================
# 锚点类型 → 展示名 / extract_anchors 键 的映射
# ============================================================

# extract_anchors() 返回的键 → 本层 anchor_type
_KEY_TO_TYPE = {
    "birth_year": "birth",
    "marriage_year": "marriage",
    "child_birth_year": "child_birth",
}

_TYPE_TO_KEY = {v: k for k, v in _KEY_TO_TYPE.items()}

_ANCHOR_NAME = {
    "birth": "出生",
    "marriage": "结婚",
    "child_birth": "老大出生",
}

# 允许用户手动录入的类型（与 extract_anchors 对齐，不扩语义）
VALID_TYPES = tuple(_ANCHOR_NAME.keys())


# ============================================================
# 一、采集：扫整本书 → 落 LifeAnchor 表
# ============================================================

def _story_texts(db, story):
    """把一条故事里所有**可能含时间陈述**的文本拼出来（标题/摘要/原文/润色/原话/语音转写）。"""
    parts = [
        story.time_raw or "",
        story.title or "",
        story.summary or "",
        story.raw_content or "",
        story.polished_content or "",
    ]
    for c in db.query(Clip).filter(Clip.story_id == story.id).all():
        if c.text:
            parts.append(c.text)
        if c.transcript:
            parts.append(c.transcript)
        if c.caption:
            parts.append(c.caption)
    return " ".join(p for p in parts if p).strip()


def harvest_anchors(db, *, owner_id: str, commit: bool = True) -> dict:
    """
    扫 book owner 的全部故事，采集人生锚点，落 LifeAnchor 表。

    幂等：同一 (owner_id, anchor_type) 只一行。
    保护：confirmed=True 的锚点不被自动采集覆盖（v2.4 §5.5）。
    返回 {ok, data:{owner_id, harvested:{type:year}, kept_confirmed:{...}}}
    """
    if not owner_id:
        return fail("BAD_OWNER", "缺少 owner_id")

    stories = db.query(Story).filter(Story.owner_id == owner_id).all()

    # 1. 合并采集：全部故事里出现的锚点（同类型取**首次出现**，先到先得，不反复覆盖）
    found = {}          # key(e.g. birth_year) -> (year, story_id)
    for s in stories:
        blob = _story_texts(db, s)
        if not blob:
            continue
        got = extract_anchors(blob)
        for key, year in got.items():
            if key not in found:
                found[key] = (int(year), s.id)

    # 2. 已存在的行
    existing = {
        a.anchor_type: a
        for a in db.query(LifeAnchor).filter(LifeAnchor.owner_id == owner_id).all()
    }

    harvested = {}
    kept_confirmed = {}

    for key, (year, story_id) in found.items():
        anchor_type = _KEY_TO_TYPE.get(key)
        if not anchor_type:
            continue

        cur = existing.get(anchor_type)

        # 2a. 用户确认过的 → 不覆盖，只记录
        if cur is not None and cur.confirmed:
            kept_confirmed[anchor_type] = cur.year
            continue

        if cur is None:
            db.add(LifeAnchor(
                id=uuid.uuid4().hex,
                owner_id=owner_id,
                anchor_type=anchor_type,
                anchor_name=_ANCHOR_NAME[anchor_type],
                year=year,
                time_precision=TimePrecision.YEAR,
                source_story_id=story_id,
                confirmed=False,
            ))
        else:
            # 已存在但未确认 → 用新采到的年份更新（保留最早的来源标注）
            cur.year = year
            cur.source_story_id = story_id or cur.source_story_id
            cur.time_precision = TimePrecision.YEAR

        harvested[anchor_type] = year

    if commit:
        db.commit()
    else:
        # ⚠️ 2026-10-07 坑：本工程 SessionLocal 关掉了 autoflush（autoflush=False），
        #    不 flush 的话同一 session 里紧接着的 query 看不到刚 add 的行 →
        #    get_anchors 会返回 {}（明明 harvested 里有）。必须显式 flush。
        db.flush()

    return ok({
        "owner_id": owner_id,
        "stories_scanned": len(stories),
        "harvested": harvested,
        "kept_confirmed": kept_confirmed,
    })


# ============================================================
# 二、读取：LifeAnchor 表 → extract_time 要的 dict
# ============================================================

def get_anchors(db, *, owner_id: str) -> dict:
    """
    读 LifeAnchor 表，转成 timeline.extract_time(anchors=..) 要的键名。
    返回 {'birth_year':1950, 'marriage_year':1972, 'child_birth_year':1975}
    （只有已采到的才有键；没有锚点的书返回 {}，extract_time 自然走【待定】，不瞎猜）
    """
    rows = db.query(LifeAnchor).filter(LifeAnchor.owner_id == owner_id).all()
    out = {}
    for a in rows:
        if a.year is None:
            continue
        key = _TYPE_TO_KEY.get(a.anchor_type)
        if key:
            out[key] = int(a.year)
    return out


# ============================================================
# 三、对外接口：查锚点 / 手工纠正锚点
# ============================================================

def _anchor_dict(a: LifeAnchor) -> dict:
    return {
        "anchor_type": a.anchor_type,
        "anchor_name": a.anchor_name or _ANCHOR_NAME.get(a.anchor_type, ""),
        "year": a.year,
        "precision": a.time_precision.value if a.time_precision else "year",
        "source_story_id": a.source_story_id or "",
        "confirmed": bool(a.confirmed),
    }


def api_get_anchors(db, *, owner_id: str, harvest: bool = True) -> dict:
    """
    查这本书的人生锚点。
    harvest=True（默认）先扫一遍正文再返回，保证"刚写的故事里的锚点"也能立刻出现。
    """
    if not owner_id:
        return fail("BAD_OWNER", "缺少 owner_id")

    if harvest:
        h = harvest_anchors(db, owner_id=owner_id, commit=True)
        if not h["ok"]:
            return h

    rows = db.query(LifeAnchor).filter(LifeAnchor.owner_id == owner_id).all()
    anchors = [_anchor_dict(a) for a in rows]
    # 稳定排序：先按类型固定序，方便前端展示
    order = {t: i for i, t in enumerate(VALID_TYPES)}
    anchors.sort(key=lambda d: order.get(d["anchor_type"], 99))
    return ok({"owner_id": owner_id, "anchors": anchors,
               "anchor_map": get_anchors(db, owner_id=owner_id)})


def api_upsert_anchor(db, *, owner_id: str, anchor_type: str,
                      year, source_story_id: str = "", confirm: bool = True) -> dict:
    """
    手动设置/纠正一个锚点（用户拍板 → confirmed=True，之后采集不得覆盖）。
    year 允许 int 或 "1950" 字符串；非法年份拒绝。
    """
    if not owner_id:
        return fail("BAD_OWNER", "缺少 owner_id")
    if anchor_type not in VALID_TYPES:
        return fail("BAD_TYPE", f"不支持的锚点类型：{anchor_type}")

    try:
        y = int(year)
    except (TypeError, ValueError):
        return fail("BAD_YEAR", "年份必须是整数")
    if not (1900 <= y <= 2100):
        return fail("BAD_YEAR", "年份超出合理范围（1900-2100）")

    cur = (db.query(LifeAnchor)
             .filter(LifeAnchor.owner_id == owner_id,
                     LifeAnchor.anchor_type == anchor_type)
             .first())

    if cur is None:
        cur = LifeAnchor(
            id=uuid.uuid4().hex,
            owner_id=owner_id,
            anchor_type=anchor_type,
            anchor_name=_ANCHOR_NAME[anchor_type],
            year=y,
            time_precision=TimePrecision.YEAR,
            source_story_id=source_story_id or None,
            confirmed=bool(confirm),
        )
        db.add(cur)
    else:
        cur.year = y
        cur.anchor_name = _ANCHOR_NAME[anchor_type]
        cur.time_precision = TimePrecision.YEAR
        if source_story_id:
            cur.source_story_id = source_story_id
        cur.confirmed = bool(confirm)

    db.commit()
    return ok({"owner_id": owner_id, "anchor": _anchor_dict(cur)})


# ============================================================
# 四、自测说明（见 selftest_anchor_api.py，本文件不内联跑）
# ============================================================

if __name__ == '__main__':
    print("人生锚点表接口 v1.0 —— 请跑 selftest_anchor_api.py（本文件不内联自测）")
