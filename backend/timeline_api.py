"""
往事可追忆 - 时间轴（第2期「能排对」）接口 handler 层 v1.0
建立：2026-10-06（日历波谷日任务：出码卡在开发者工具，转做第2期后端）

=== 为什么是今天做 ===
日历 §四 把 10-06~10-07（等出码窗口）标为**天然波谷**：「这几天我转去做第2期时间轴算法设计，不空转」。
10-06 实测出码仍卡在微信开发者工具 IDE HTTP 端口未起（比登录态更靠前，需 sandy 在有屏机器手开 GUI）。
故本日做**第2期后端主线**——小龙虾 10-06 已交《第2期前端设计预案》，其 §4 明确在等
「小鲸鱼《时间轴接口定义》」（N1~N4）。本文件即该接口的后端实现。

=== 本文件干什么（覆盖 v2.4 §5 / §5.4 / §5.5）===
1. `api_get_timeline`     取整本时间轴（分节：有时间的按节排 + 【时间待定】单列）
2. `api_get_timeline_grouped` 同上，兼容旧前端「grouped」命名（第2期统一走 timeline）
3. `api_set_story_time`    ★「改时间」——用户手动把一段挪到新时间（最高优先级，不再被自动覆盖）
4. `api_timeline_pending`  取【时间待定】区（老人说了但听不出年份的，单列不猜）

=== 铁律（逐字执行，绝不打折扣）===
1. 无法判定 → 【时间待定】单列，**不瞎猜、不归错位**（v2.4 §5.4 保命线）
2. 模糊**原样保留**：`time_label` 直接用 `Story.time_label`（已带「（老人说的）」），
   本层**绝不重构时间文案**，避免把「1970年代（老人说的）」又凑成「1975年3月」
3. **精度不影响排序**：排序键一律用 `Story.time_sort_key`（int），不看 precision
4. **同一时间点允许多个故事**：一节下挂 N 张卡（v2.4 §5之二.2），本层按 sort_key 分组
5. **一旦用户手动改过（time_confirmed_by_user=True），后续自动提取不得覆盖**（v2.4 §5.5）
6. 权限沿用 permissions.can_view_story：家人看整本 / 故事成员只看命中那篇 / 外人 0 条

=== 设计口径（与 story_api/collect_api 一致）===
- handler 不自己开 session，db 由调用方传
- 统一信封 {ok, data, error, code}
- 时间解析复用 timeline.py 的 extract_time / extract_anchors，**不另造一套**
"""

from datetime import date

from permissions import can_view_story, visible_stories
from timeline import extract_time, extract_anchors, Precision as TLPrecision
from models import (
    SessionLocal, Story, Member, ClaimStatus, GrantVia,
    TimePrecision, init_db,
)

NO_PERMISSION = "你没有权限看这本书"
STORY_NOT_FOUND = "找不到这条故事"
CANNOT_EDIT = "你没有权限改这段的时间"

# timeline.py 的 Precision ⇄ models.TimePrecision 值域一致（year/season/month/day/fuzzy/unknown），
# 但两者是不同 Enum 类，需要按 **.value** 映射，禁止直接传对象（否则 SAEnum 落库会崩）。
_VALID_PRECISION = {e.value for e in TimePrecision}


# ============================================================
# 一、统一信封
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
# 二、内部：时间归一化（把用户手改的时间落成 Story 的 time_* 字段）
# ============================================================

def _norm_precision(p) -> str:
    """把外部传进来的精度收敛成 models.TimePrecision 的合法值。"""
    if p is None:
        return TimePrecision.UNKNOWN.value
    v = getattr(p, "value", p)
    v = str(v).strip().lower()
    return v if v in _VALID_PRECISION else TimePrecision.UNKNOWN.value


def _story_time_dict(s: Story) -> dict:
    """
    一条故事的时间四件套（前端时间轴页只认这个形状）。
    ⚠️ label 直接取库里的 time_label（原样、含「（老人说的）」），本层不重构。
    """
    return {
        "story_id": s.id,
        "title": s.title or "",
        "summary": s.summary or "",
        "time_raw": s.time_raw or "",
        "time_label": s.time_label or _fallback_label(s),
        "time_precision": getattr(s.time_precision, "value", s.time_precision) or TimePrecision.UNKNOWN.value,
        "time_sort_key": s.time_sort_key if s.time_sort_key is not None else 0,
        "time_extract_method": s.time_extract_method or "",
        "time_confirmed_by_user": bool(s.time_confirmed_by_user),
        "is_anchor": bool(_looks_like_anchor(s)),
    }


def _fallback_label(s: Story) -> str:
    """库里没 time_label 时的兜底展示：没有就老实说『时间待定』，不编。"""
    if s.time_sort_key and s.time_sort_key > 0:
        return f"{s.time_sort_key}年"
    return "时间待定"


# 人生锚点的关键词（v2.4 §5.3：锚点是让时间轴变准的核心，前端要标角标）
_ANCHOR_KEYWORDS = ("出生", "生的", "结婚", "嫁", "过门", "上小学", "上学", "退休", "生了")


def _looks_like_anchor(s: Story) -> bool:
    """
    粗判这条故事是不是人生锚点（出生/上学/结婚/生娃/退休）。
    只读 time_raw + title，命中关键词即认为是锚点 —— 用于前端「锚」角标。
    **仅作展示提示，不参与排序、不反推其它故事**（反推在 extract_time 的 anchors 入参里做）。
    """
    blob = f"{s.time_raw or ''} {s.title or ''} {s.summary or ''}"
    return any(k in blob for k in _ANCHOR_KEYWORDS)


# ============================================================
# 三、取整本时间轴（分节）
# ============================================================

def _collect_visible_stories(db, *, owner_id: str, viewer_id: str):
    """
    取 viewer 有权看的、属于 owner 这本书的全部故事。
    家人/主人 → 全本；故事成员 → 只看被点名那篇；外人 → 空。
    """
    # 主人本人
    if viewer_id and owner_id and viewer_id == owner_id:
        return db.query(Story).filter(Story.owner_id == owner_id).all()

    # 家人（FAMILY 已认领）→ 整本
    fam = db.query(Member).filter(
        Member.owner_id == owner_id,
        Member.user_id == viewer_id,
        Member.claim_status == ClaimStatus.CLAIMED,
        Member.granted_via == GrantVia.FAMILY,
    ).first()
    if fam is not None:
        return db.query(Story).filter(Story.owner_id == owner_id).all()

    # 故事成员（STORY 已认领）→ 只看绑定的那几篇
    rows = db.query(Member).filter(
        Member.owner_id == owner_id,
        Member.user_id == viewer_id,
        Member.claim_status == ClaimStatus.CLAIMED,
        Member.granted_via == GrantVia.STORY,
    ).all()
    ids = [m.story_id for m in rows if m.story_id]
    if not ids:
        return []
    return db.query(Story).filter(Story.id.in_(ids)).all()


def _build_timeline(db, *, owner_id: str, viewer_id: str) -> dict:
    """
    组装时间轴结构：
      nodes   = 有时间的故事，按 sort_key 分节（一节一时间点，可挂多故事）
      pending = 【时间待定】区（sort_key 空/0 的，单列底部，不参与排序）
    """
    stories = _collect_visible_stories(db, owner_id=owner_id, viewer_id=viewer_id)

    nodes_map: dict = {}
    pending: list = []
    for s in stories:
        item = _story_time_dict(s)
        sk = s.time_sort_key
        if sk is None or int(sk) <= 0:
            pending.append(item)
            continue
        nodes_map.setdefault(int(sk), []).append(item)

    nodes = []
    for key in sorted(nodes_map.keys()):
        cards = nodes_map[key]
        nodes.append({
            "node_id": f"n{key}",
            "time_sort_key": key,
            # 同一节点的展示文案：取该节第一条的 label（用户改过的优先展示）
            "label": _node_label(cards),
            "count": len(cards),
            "stories": cards,
        })

    # 待定区也按录入顺序稳定输出
    pending.sort(key=lambda x: x["story_id"])
    return {
        "owner_id": owner_id,
        "nodes": nodes,
        "pending": pending,
        "stats": {
            "total": len(stories),
            "placed": sum(n["count"] for n in nodes),
            "pending": len(pending),
            "node_count": len(nodes),
        },
    }


def _node_label(cards: list) -> str:
    """一节的时间文案：优先用「被用户确认过」的，其次第一条；没有就『时间待定』。"""
    for c in cards:
        if c["time_confirmed_by_user"] and c["time_label"]:
            return c["time_label"]
    for c in cards:
        if c["time_label"]:
            return c["time_label"]
    return "时间待定"


def api_get_timeline(db, *, owner_id: str = "", viewer_id: str = "") -> dict:
    """取整本时间轴。前端时间轴页（小龙虾 §1）直接渲染 nodes + pending。"""
    if not owner_id or not viewer_id:
        return fail("缺少 owner_id 或 viewer_id", "bad_request")
    data = _build_timeline(db, owner_id=owner_id, viewer_id=viewer_id)
    # 外人（无任何权限）→ 空轴，但**不报错**（不泄露"存在但你没权限"）
    return ok(data)


def api_get_timeline_grouped(db, *, owner_id: str = "", viewer_id: str = "") -> dict:
    """兼容旧前端命名（timeline_grouped）。与 api_get_timeline 同体。"""
    return api_get_timeline(db, owner_id=owner_id, viewer_id=viewer_id)


def api_timeline_pending(db, *, owner_id: str = "", viewer_id: str = "") -> dict:
    """只取【时间待定】区（老人说了但听不出年份的，单列不猜）。"""
    if not owner_id or not viewer_id:
        return fail("缺少 owner_id 或 viewer_id", "bad_request")
    data = _build_timeline(db, owner_id=owner_id, viewer_id=viewer_id)
    return ok({"owner_id": owner_id, "pending": data["pending"],
               "count": len(data["pending"])})


# ============================================================
# 四、★「改时间」——用户手动挪一段（v2.4 §5.5）
# ============================================================

def _can_edit_story_time(db, *, story: Story, actor_id: str) -> bool:
    """
    谁能改这段的时间：
      - 书主人本人 → 能
      - 家人（FAMILY 已认领）→ 能（帮老人整理是常态）
      - 故事成员 → **不能**（只能看他那篇，改时间归主人/家人）
    """
    if not actor_id or not story:
        return False
    if story.owner_id and actor_id == story.owner_id:
        return True
    m = db.query(Member).filter(
        Member.owner_id == story.owner_id,
        Member.user_id == actor_id,
        Member.claim_status == ClaimStatus.CLAIMED,
        Member.granted_via == GrantVia.FAMILY,
    ).first()
    return m is not None


def api_set_story_time(
    db,
    *,
    story_id: str = "",
    actor_id: str = "",
    new_time_text: str = "",
    anchors: dict = None,
    force_raw: str = "",
) -> dict:
    """
    用户手动改一段的时间（前端「改时间」弹层提交）。

    入参：
      story_id     要改的那条故事
      actor_id     谁改的（须为主人或家人）
      new_time_text 用户说的话 / 手动输入，如「1980年5月」「八十年代」「文革那会儿」
      anchors      已知人生锚点（可选），如 {'birth_year':1950}，用于把「我八岁那年」反推
      force_raw    只保留原话、不做解析时填（此时按待定处理但保留原话）

    行为：
      1. 解析 new_time_text（复用 timeline.extract_time，**不另造解析器**）
      2. 落 Story 的 time_raw / time_label / time_sort_key / time_precision / time_extract_method
      3. **置 time_confirmed_by_user = True** → 之后任何自动提取**都不得再覆盖**（v2.4 §5.5）
      4. 解析不出 → 落「时间待定」并**保留原话**，不瞎猜（返回 placed=False 让前端提示）

    返回：{ok, data:{story_id, placed, time:{...}, node_hint}}
    """
    if not story_id or not actor_id:
        return fail("缺少 story_id 或 actor_id", "bad_request")

    story = db.query(Story).filter(Story.id == story_id).first()
    if story is None:
        return fail(STORY_NOT_FOUND, "not_found")
    if not _can_edit_story_time(db, story=story, actor_id=actor_id):
        return fail(CANNOT_EDIT, "forbidden")

    raw = (new_time_text or "").strip()

    # 只保留原话（不解析）→ 视为待定但留原话
    if force_raw and not raw:
        raw = force_raw.strip()
        story.time_raw = raw
        story.time_label = raw or "时间待定"
        story.time_sort_key = 0
        story.time_precision = TimePrecision.UNKNOWN
        story.time_extract_method = "手动（仅留原话）"
        story.time_confirmed_by_user = True
        db.commit()
        return ok({
            "story_id": story.id, "placed": False,
            "time": _story_time_dict(story),
            "node_hint": "时间待定",
        })

    if not raw:
        return fail("请说一个时间", "bad_request")

    r = extract_time(raw, anchors or {})

    # 落库（precision 按 .value 映射，避免 SAEnum 落 Enum 类崩）
    story.time_raw = r.raw or raw
    story.time_label = r.label or raw
    story.time_precision = TimePrecision(_norm_precision(r.precision))
    story.time_extract_method = r.method or ""
    story.time_confirmed_by_user = True

    placed = r.sort_key is not None and int(r.sort_key) > 0
    if placed:
        story.time_sort_key = int(r.sort_key)
    else:
        # 解析不出 → 时间待定，但原话已保留，不瞎猜
        story.time_sort_key = 0
        story.time_precision = TimePrecision.UNKNOWN

    db.commit()
    return ok({
        "story_id": story.id,
        "placed": bool(placed),
        "time": _story_time_dict(story),
        "node_hint": story.time_label or ("时间待定"),
        "evidence": r.evidence or "",
        "confidence": r.confidence,
    })


# ============================================================
# 五、自动归位（保存即触发，v2.4 铁律 5）
# ============================================================

def auto_place_story(db, *, story_id: str) -> dict:
    """
    自动时间归位：从故事素材里抽时间，写入 Story.time_*。

    ⚠️ 铁律：若 `time_confirmed_by_user=True`（用户手动改过），**直接跳过不覆盖**（v2.4 §5.5）。
    ⚠️ 锚点反推：先把**同一本书**里已确认的锚点故事抽成 anchors，再解析（v2.4 §5.3）。
    返回 {ok, data:{story_id, placed, skipped, time:{...}}}
    """
    story = db.query(Story).filter(Story.id == story_id).first()
    if story is None:
        return fail(STORY_NOT_FOUND, "not_found")

    # 1. 用户手动改过 → 不覆盖
    if story.time_confirmed_by_user:
        return ok({"story_id": story.id, "placed": False, "skipped": True,
                   "reason": "用户已手动改过，不覆盖",
                   "time": _story_time_dict(story)})

    # 2. 取文本：优先 title/summary，其次该故事的文字素材
    texts = [story.title or "", story.summary or ""]
    try:
        from models import Clip  # 局部导入避免循环
        clips = db.query(Clip).filter(Clip.story_id == story.id).all()
        for c in clips:
            if c.text:
                texts.append(c.text)
            if c.transcript:
                texts.append(c.transcript)
    except Exception:
        pass
    blob = " ".join(t for t in texts if t).strip()

    # 3. 锚点：同书里已确认的锚点故事 → 反推用
    anchors = {}
    try:
        for s2 in db.query(Story).filter(Story.owner_id == story.owner_id).all():
            if s2.id == story.id:
                continue
            found = extract_anchors(f"{s2.time_raw or ''} {s2.title or ''} {s2.summary or ''}")
            for k, v in found.items():
                anchors.setdefault(k, v)
    except Exception:
        pass

    if not blob:
        return ok({"story_id": story.id, "placed": False, "skipped": False,
                   "reason": "无文本可解析", "time": _story_time_dict(story)})

    r = extract_time(blob, anchors)
    placed = r.sort_key is not None and int(r.sort_key) > 0

    story.time_raw = r.raw or story.time_raw or ""
    story.time_label = r.label or story.time_raw or "时间待定"
    story.time_precision = TimePrecision(_norm_precision(r.precision))
    story.time_extract_method = r.method or ""
    story.time_sort_key = int(r.sort_key) if placed else 0
    if not placed:
        story.time_precision = TimePrecision.UNKNOWN
    db.commit()

    return ok({"story_id": story.id, "placed": bool(placed), "skipped": False,
               "time": _story_time_dict(story)})


# ============================================================
# 六、自测（见 selftest_timeline_api.py，本文件不内联跑）
# ============================================================

if __name__ == '__main__':
    print("时间轴接口 v1.0 —— 请跑 selftest_timeline_api.py（本文件不内联自测）")
