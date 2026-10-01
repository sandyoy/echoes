"""
往事可追忆 - 故事（一件事 / 一本书）接口 handler 层 v1.0
建立：2026-10-01（第1期，日历 10-01 任务）

=== 为什么有这个文件（今日发现的缺口）===
10-01 做**真 HTTP 端到端联调**（起 uvicorn 打 18 条路由）时发现：
  全部 18 条路由都**必须**带 `story_id`，但**没有任何一条接口负责产出 story_id**。
  → 前端第一次打开小程序，无书可建、无故事可写，整条动线在第一步就断了。
  → 前端只能写死一个假 story_id 来联调（小龙虾实际就是这么绕的）。

本文件补上这块：**建书 / 建故事 / 取我的书列表 / 取故事详情**。

=== 口径（与既有模块一致）===
- 权限：沿用 permissions.can_view_story（家人看整本 / 故事成员看单篇 / 被提及者免授权）
- 「书」与「故事」的关系（v2.4 第二节）：
    owner（书的主人=讲述人）这本书下，有 N 条故事（每件事一条）；
    素材（文字/语音/照片/视频）挂在**故事**上，不是直接挂书上。
  → 建书：只登记 owner（第1期不建独立 Book 表，一本书 = 一个 owner_id 的故事集合）
    这是第1期的简化口径，**第3期出电子书时再落 Book 表**（已记入需求跟踪）。

=== 设计铁律 ===
1. handler 不自己开 session，db 由调用方传（便于测试/事务）
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **绝不越权**：建/改故事必须校验 actor 对该 owner 有权限；
   取列表只看 viewer 有权看的（不泄露"存在但你没权限"）
4. id 一律 `_new_id("story")`，与 permissions/claim 同一套生成器
"""

from permissions import _new_id, can_view_story

from models import (
    SessionLocal, Story, Clip, ClipType,
    Member, ClaimStatus, GrantVia, User, init_db,
)

STORY_NOT_FOUND = "找不到这条故事"
NO_PERMISSION = "你没有权限看这本书"


# ============================================================
# 一、统一信封（与 collect_api / claim_api 同形，前端一套解析）
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
# 二、内部：权限小工具
# ============================================================

def _is_owner_of(db, *, owner_id: str, actor_id: str) -> bool:
    """actor 是不是这本书的主人本人。"""
    return bool(owner_id) and bool(actor_id) and owner_id == actor_id


def _can_write_to_book(db, *, owner_id: str, actor_id: str) -> bool:
    """
    谁能「往这本书里添故事」：
      - 书主人本人 → 能
      - 家人（granted_via=FAMILY，已认领）→ 能（家人帮老人录是常态）
      - 其它 → 不能（故事成员只能看他那一篇，不能新增故事）
    """
    if _is_owner_of(db, owner_id=owner_id, actor_id=actor_id):
        return True
    if not actor_id or not owner_id:
        return False
    m = db.query(Member).filter(
        Member.owner_id == owner_id,
        Member.user_id == actor_id,
        Member.claim_status == ClaimStatus.CLAIMED,
        Member.granted_via == GrantVia.FAMILY,
    ).first()
    return m is not None


def _story_summary(s: Story) -> dict:
    """列表里 stories 的展示字段（**不含正文**，列表要轻）。"""
    return {
        "story_id": s.id,
        "owner_id": s.owner_id or "",
        "title": s.title or "",
        "summary": s.summary or "",
        "time_label": s.time_label or "",
        "time_raw": s.time_raw or "",
        "time_start": s.time_start.isoformat() if s.time_start else "",
        "time_precision": (s.time_precision.value if s.time_precision else ""),
        "people_mentioned": s.people_mentioned or [],
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


# ============================================================
# 三、handler：建书（第1期简化口径：一本书 = 一个 owner 的故事集合）
# ============================================================

def api_create_book(db, *, owner_id: str, actor_id: str = "",
                    title: str = "", summary: str = "") -> dict:
    """
    「开一本新书」。第1期不建 Book 表——建书 = 确保 owner 这个 User 存在，
    并返回该书（owner）的基本信息。真正的故事由 api_create_story 逐条建。

    前端动线：进小程序 → 登录拿 user_id → 若「我有哪些书」为空 → 调本接口开书
              → 进采集页写第一条故事。
    """
    if not owner_id:
        return fail("缺少 owner_id（书的主人）", "missing_owner_id")
    actor = actor_id or owner_id
    # 开书：只有本人能给自己开（别人不能替你开书）
    if actor != owner_id:
        return fail("只能给自己开书", "forbidden")

    u = db.get(User, owner_id)
    if u is None:
        u = User(id=owner_id, nick_name="", ui_mode=None)
        db.add(u)
        db.commit()
    return ok({
        "owner_id": owner_id,
        "title": title or (getattr(u, "nick_name", "") or "我的一生"),
        "is_new": True,
    })


# ============================================================
# 四、handler：建一条故事（一件事）
# ============================================================

def api_create_story(db, *, owner_id: str, actor_id: str,
                     title: str = "", raw_content: str = "",
                     summary: str = "", time_raw: str = "",
                     people_mentioned=None, story_id: str = "") -> dict:
    """
    在 owner 的这本书里新建一条故事（= 一个素材筐）。

    - actor_id：谁在写（书主人本人 / 已认领的家人）
    - 返回 story_id —— **前端拿它去挂素材**（clip/text、clip/audio ...）
    - time_raw：原样保留老人说法（如"七几年"），归一化归 timeline 线
    - people_mentioned：[{"name":..,"phone":..,"user_id":..}]，被提及者后续免授权可看本篇

    幂等：传 story_id 且已存在 → 直接返回该条（避免弱网重试建重）。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    if not actor_id:
        return fail("缺少 actor_id（谁在写）", "missing_actor_id")
    if not _can_write_to_book(db, owner_id=owner_id, actor_id=actor_id):
        return fail("你没有权限往这本书里添故事", "forbidden")

    if story_id:
        exist = db.get(Story, story_id)
        if exist is not None:
            return ok({"story_id": exist.id, "is_new": False,
                       "story": _story_summary(exist)})

    if not story_id:
        story_id = _new_id("story")

    pm = people_mentioned or []
    if not isinstance(pm, list):
        return fail("people_mentioned 必须是列表", "bad_request")

    s = Story(
        id=story_id,
        owner_id=owner_id,
        title=(title or "").strip(),
        summary=(summary or "").strip(),
        raw_content=raw_content or "",
        time_raw=(time_raw or "").strip(),
        recorder_id=actor_id,
        narrator_id=owner_id,
        people_mentioned=pm,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok({"story_id": s.id, "is_new": True, "story": _story_summary(s)})


# ============================================================
# 五、handler：取我的书列表 / 书里的故事列表
# ============================================================

def api_my_books(db, *, user_id: str) -> dict:
    """
    「我有哪些书」——首页用。
      - 我自己是主人的书（我写的）
      - 我作为已认领成员被拉进去的书（家人的书）
    与 login_api.api_login 里的 owners 口径保持一致。
    """
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")

    owner_ids = set()
    owner_ids.add(user_id)

    ms = db.query(Member).filter(
        Member.user_id == user_id,
        Member.claim_status == ClaimStatus.CLAIMED,
    ).all()
    for m in ms:
        if m.owner_id:
            owner_ids.add(m.owner_id)

    books = []
    for oid in owner_ids:
        cnt = db.query(Story).filter(Story.owner_id == oid).count()
        u = db.get(User, oid)
        role = "owner" if oid == user_id else "family"
        books.append({
            "owner_id": oid,
            "title": (getattr(u, "nick_name", "") or "") or ("我的一生" if role == "owner" else "家人的书"),
            "story_count": cnt,
            "role": role,
        })
    return ok({"count": len(books), "books": books})


def api_list_stories(db, *, owner_id: str, viewer_id: str,
                     limit: int = 200, offset: int = 0) -> dict:
    """
    取「某人这本书」里的故事列表（**只返回 viewer 有权看的**）。
    看不到的**直接不出现**（不泄露"存在但你没权限"）。

    权限：书主人/家人 → 整本；故事成员/被提及者 → 只看命中那几篇。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    if not viewer_id:
        return fail("缺少 viewer_id", "missing_viewer_id")

    try:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        return fail("limit/offset 必须是整数", "bad_request")

    q = db.query(Story).filter(Story.owner_id == owner_id)
    total = q.count()
    rows = q.order_by(Story.time_sort_key.asc(), Story.created_at.asc()) \
            .offset(offset).limit(limit).all()

    visible = []
    for s in rows:
        # 被提及者/家人等：用统一的 can_view_story 判定
        if owner_id == viewer_id or _can_write_to_book(db, owner_id=owner_id, actor_id=viewer_id):
            visible.append(s)
        elif can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=s.id):
            visible.append(s)

    return ok({
        "owner_id": owner_id,
        "total": total,
        "count": len(visible),
        "stories": [_story_summary(s) for s in visible],
    })


# ============================================================
# 六、handler：取故事详情
# ============================================================

def api_get_story(db, *, story_id: str, owner_id: str, viewer_id: str) -> dict:
    """
    取一条故事详情（含正文）。**看不到就不给**，且不回"存在但你没权限"。
    owner_id 必传（权限判定的根，缺了会退化成放行——见 10-01 安全修复）。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not owner_id:
        return fail("缺少 owner_id（权限判定的根，必传）", "missing_owner_id")

    s = db.get(Story, story_id)
    if s is None:
        return fail(STORY_NOT_FOUND, "not_found")
    if not can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=story_id):
        # 不告诉"存在但你没权限"
        return fail(NO_PERMISSION, "no_permission")

    d = _story_summary(s)
    d["raw_content"] = s.raw_content or ""
    d["polished_content"] = s.polished_content or ""
    d["location"] = s.location or ""
    d["tags"] = s.tags or []
    return ok({"story": d})


# ============================================================
# 七、handler：删一条故事（软性：仅主人本人）
# ============================================================

def api_delete_story(db, *, story_id: str, owner_id: str, actor_id: str) -> dict:
    """
    删一条故事（连同它筐里的素材，靠 FK CASCADE）。
    **只有书主人本人**能删——家人不能替老人删。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not owner_id or actor_id != owner_id:
        return fail("只有这本书的主人本人能删除", "forbidden")
    s = db.get(Story, story_id)
    if s is None:
        return fail(STORY_NOT_FOUND, "not_found")
    if s.owner_id != owner_id:
        return fail("这条故事不属于你", "forbidden")
    db.delete(s)
    db.commit()
    return ok({"story_id": story_id, "deleted": True})
