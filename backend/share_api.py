"""
share_api.py —— 分享机制（v3.0 §八之二）· 后端 v1.0
=====================================================

依 2026-10-09 定稿的《需求书 v3.0 视角容器版》§八之二 实现。
此前**全无后端**：§八之二 从 v2.4 保留至今，却从未落过一行代码。
08 页原型图（"拿给别人看"）的前端要落地，必须先有这层。

=== 铁律（写在这里，防将来被"优化"掉）===
1. **分享只管公开素材**（§8之二.3，sandy 原话"我分享出去，证明它已经不是私有了"）。
   私有素材/私有篇**不进分享通道** —— 这条**不另定规则**，是从 §1.2「公开」定义
   里**自动长出来**的。本文件用 `_shareable_*` 单一判据落地它：
   **一条素材可被分享 ⇔ 它的 visibility == PUBLIC。**
2. **一篇故事"可分享"的判据 = 它至少有一条公开素材**（§8之二.3）。
   全私有的篇 → 分享时 `can_share=False`，且**不暴露内容**（只给"这篇还没公开"）。
3. **先看后登录**（§8之二.2 共同点）：`api_view_shared` 是**无登录**接口，
   只读公开内容；参与（加进来/开一本）才登录。
4. **待认领只登记公开篇提到的人**（§8之二.7 v3.0 改）：
   私有库里提到的人**不登记、不提醒**（否则=泄密）。--本条已回落到 claim.py 修。

=== 两种分享（§8之二.2）===
  ① 有故事 → 分享**那一篇**：收到的人直接读这篇（不用登录）
  ② 没故事 → 分享**小程序本身**：收到的人看到引导页（"给你家老人也做一本？"）

=== 对外 handler（5 个）===
  api_share_story     造一条故事分享（公开篇才给）；返回卡片数据/落地参数
  api_share_app       造一条"小程序本身"分享（无故事时用）
  api_view_shared     无登录读一条被分享的公开故事（先看不登录）
  api_share_book      分享整本书（§8之二.3.1：整本 + 单件都能分）
  api_share_card      生成"好看的卡片图"所需数据（§8之二.3.1 方式 B）

=== 自测 ===
  python3 backend/selftest_share_api.py   （依赖 DATABASE_URL 走内存库）
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select

from models import (
    SessionLocal, Story, Clip, Member,
    Visibility,
)
from permissions import (
    _new_id,
    can_view_story,
    visible_clips,
)


# ============================================================
# 信封（与全项目一致）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True}
    if data is not None:
        d["data"] = data
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code}
    d.update(extra)
    return d


# ============================================================
# 一、可分享判据（§8之二.3 —— 本文件单一真相源）
# ============================================================

def _clips_of(db, story_id: str):
    return list(db.scalars(select(Clip).where(Clip.story_id == story_id)))


def _public_clips(db, story_id: str):
    """这篇里**公开**的素材。全私有 → 空列表。"""
    return [c for c in _clips_of(db, story_id)
            if getattr(c, "visibility", None) == Visibility.PUBLIC]


def can_share_story(db, *, story_id: str) -> bool:
    """
    一篇故事能不能分享（§8之二.3）。
    判据：**至少一条公开素材**。全私有不给分——分享出去=已公开，天然排除私有。
    """
    if db.get(Story, story_id) is None:
        return False
    return len(_public_clips(db, story_id)) > 0


# ============================================================
# 二、分享一条故事（§8之二.5）
# ============================================================

def make_story_share(db, *, story_id: str, actor_id: str) -> dict:
    """
    造一条故事分享（登录态调用）。

    返回落地参数（前端拿去拼微信转发卡片 / 二维码 / 卡片图）：
      share_token   —— 分享令牌（无登录读这条的钥匙）
      path          —— 小程序落地路径 pages/shared/story?t=xxx
      title         —— 卡片标题（"李桂芳的故事里提到了你"由前端按场景拼）

    **全私有的篇 → raise PermissionError**（不造 token，不给分享）。
    """
    story = db.get(Story, story_id)
    if story is None:
        raise ValueError(f"故事不存在：{story_id}")
    if not can_share_story(db, story_id=story_id):
        raise PermissionError("这篇还没有公开的内容，先公开一段再分享")

    token = _make_token("s", story_id)
    return {
        "story_id": story_id,
        "share_token": token,
        "path": f"pages/shared/story?t={token}",
        "kind": "story",
        "public_clip_count": len(_public_clips(db, story_id)),
    }


def resolve_story_share(db, *, share_token: str):
    """
    把 share_token 解回 story_id。token 形如 s_<sha1(story_id)[:16]>。
    返回 story_id 或 None（不猜、不模糊匹配）。
    """
    if not share_token or not share_token.startswith("s_"):
        return None
    for s in db.scalars(select(Story)):
        if _make_token("s", s.id) == share_token:
            # 命中后再核一次可分享（可能分享后被改回私有）
            if can_share_story(db, story_id=s.id):
                return s.id
    return None


# ============================================================
# 三、无登录读一条被分享的公开故事（§8之二.2 先看不登录）
# ============================================================

def view_shared_story(db, *, share_token: str) -> dict:
    """
    **无登录**接口：读一条被分享的故事。

    ★ 关键（v3.0）：**只回公开素材**。私有素材连被提及者都不给看（§1.2 铁律3），
      这里无登录更不可能给。若这篇已被改成全私有 → 当作"打不开"，不泄任何内容。
    """
    story_id = resolve_story_share(db, share_token=share_token)
    if not story_id:
        return fail("这个分享打不开了（可能已被作者收回）", "share_gone")

    story = db.get(Story, story_id)
    pubs = _public_clips(db, story_id)
    if not pubs:
        return fail("这个分享打不开了（可能已被作者收回）", "share_gone")

    clips = []
    for c in sorted(pubs, key=lambda x: (x.created_at or datetime.min, x.id)):
        clips.append({
            "clip_id": c.id,
            "type": getattr(c.clip_type, "value", str(c.clip_type)),
            "text": c.text or "",
            "transcript": c.transcript or "",
            "media_url": c.media_url or "",
            "provider_id": c.provider_id or "",
            "spoken_by": _spoken_by(c),
            # 分享出去的都是公开的：source_type 引用/原创照带（署名要显）
            "source_type": getattr(c.source_type, "value", str(c.source_type)) if c.source_type else "origin",
            "ref_author_name": c.ref_author_name or "",
        })

    return ok({
        "story_id": story_id,
        "title": story.title or "",
        "time_raw": story.time_raw or "",
        "clip_count": len(clips),
        "clips": clips,
        # 篇末那一句（§8之二.5）由前端用 owner 名拼："这是<owner>的故事，里面提到了你"
        "owner_display_name": _owner_name(db, story.owner_id),
        "can_join": True,          # 看完后想加进来 → 走登录
    })


def _spoken_by(clip) -> str:
    """谁说的（署名用）。原声/语音记 provider 的称呼；没有则空。"""
    return (getattr(clip, "ref_author_name", "") or "")


def _owner_name(db, owner_id: str) -> str:
    try:
        from models import User
        u = db.get(User, owner_id)
        if u is not None:
            return getattr(u, "nick_name", "") or getattr(u, "real_name", "") or ""
    except Exception:
        pass
    return ""


# ============================================================
# 四、分享小程序本身（§8之二.6 没故事，觉得好玩）
# ============================================================

def make_app_share(db, *, actor_id: str = "") -> dict:
    """
    造一条"小程序本身"的分享（无故事时用；子女觉得好玩转同事）。
    卡片 = 产品本身，对方看到引导页（"给你家老人也做一本？"）。
    无需任何素材判据 —— 分的是产品，不是内容。
    """
    return {
        "share_token": _make_token("a", "app"),
        "path": "pages/index/index",
        "kind": "app",
        "invite_from": actor_id or "",
    }


# ============================================================
# 五、分享整本书（§8之二.3.1 整本 + 单件都能分）
# ============================================================

def make_book_share(db, *, owner_id: str, actor_id: str = "") -> dict:
    """
    分享整本书。**同样只管公开**：书里全私有的篇不会进分享清单。
    返回 landing 参数；点开的人是"看公开部分"，看不进的篇不出现。
    """
    if not db.get(__import__("models").User, owner_id):
        raise ValueError(f"用户不存在：{owner_id}")

    stories = list(db.scalars(select(Story).where(Story.owner_id == owner_id)))
    shareable = [s for s in stories if can_share_story(db, story_id=s.id)]
    if not shareable:
        raise PermissionError("这本书还没有公开的内容，先公开一段再分享")

    token = _make_token("b", owner_id)
    return {
        "owner_id": owner_id,
        "share_token": token,
        "path": f"pages/shared/book?t={token}&o={owner_id}",
        "kind": "book",
        "shareable_story_count": len(shareable),
        "total_story_count": len(stories),
    }


def view_shared_book(db, *, owner_id: str) -> dict:
    """无登录读一本被分享的书：只列**可分享（有公开内容）**的篇。"""
    stories = list(db.scalars(select(Story).where(Story.owner_id == owner_id)))
    shared = []
    for s in stories:
        pubs = _public_clips(db, s.id)
        if not pubs:
            continue
        shared.append({
            "story_id": s.id,
            "title": s.title or "",
            "time_raw": s.time_raw or "",
            "public_clip_count": len(pubs),
        })
    if not shared:
        return fail("这本书的分享打不开了（可能已被作者收回）", "share_gone")
    return ok({
        "owner_id": owner_id,
        "owner_display_name": _owner_name(db, owner_id),
        "story_count": len(shared),
        "stories": shared,
    })


# ============================================================
# 六、卡片图数据（§8之二.3.1 方式 B：做成一张好看的卡片图）
# ============================================================

def make_card_data(db, *, kind: str, target_id: str) -> dict:
    """
    给前端出卡片图用的数据（前端拿这个 + 模板渲图，或后端将来接图片服务）。
    kind = "story" | "book" | "app"
    """
    if kind == "app":
        return {
            "kind": "app",
            "headline": "给你家老人也做一本？",
            "sub": "把老人一辈子的故事，收进一本他自己的书",
        }

    if kind == "story":
        if not can_share_story(db, story_id=target_id):
            raise PermissionError("这篇还没有公开的内容，不能做分享卡片")
        s = db.get(Story, target_id)
        pubs = _public_clips(db, target_id)
        # 卡片取一句公开的原话作引子（有语音/文字公开素材才有）
        excerpt = ""
        for c in pubs:
            t = (c.text or c.transcript or "").strip()
            if t:
                excerpt = t[:40] + ("…" if len(t) > 40 else "")
                break
        return {
            "kind": "story",
            "headline": f"这是{_owner_name(db, s.owner_id)}的故事",
            "eyebrow": s.time_raw or "",
            "excerpt": excerpt,
            "public_clip_count": len(pubs),
        }

    if kind == "book":
        stories = list(db.scalars(select(Story).where(Story.owner_id == target_id)))
        shareable = [s for s in stories if can_share_story(db, story_id=s.id)]
        if not shareable:
            raise PermissionError("这本书还没有公开的内容，不能做分享卡片")
        return {
            "kind": "book",
            "headline": f"{_owner_name(db, target_id)}的这一本书",
            "sub": f"共 {len(shareable)} 篇故事",
        }

    raise ValueError(f"不认识的卡片类型：{kind}")


# ============================================================
# 七、工具
# ============================================================

def _make_token(prefix: str, seed: str) -> str:
    """稳定的分享令牌（同 seed 永远同 token，便于幂等/可复算）。"""
    h = hashlib.sha1(f"echoes:share:{seed}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


# ============================================================
# 八、对外 handler 层（信封 + 参数校验，供 fastapi 适配器挂）
# ============================================================

def api_make_share(db, *, actor_id: str, kind: str, target_id: str = "") -> dict:
    """统一分享入口：kind=story|book|app。"""
    try:
        if kind == "app":
            return ok(make_app_share(db, actor_id=actor_id))
        if kind == "story":
            return ok(make_story_share(db, story_id=target_id, actor_id=actor_id))
        if kind == "book":
            return ok(make_book_share(db, owner_id=target_id or actor_id, actor_id=actor_id))
        return fail(f"不认识的分型：{kind}", "bad_kind")
    except PermissionError as e:
        return fail(str(e), "not_shareable")
    except ValueError as e:
        return fail(str(e), "not_found")


def api_view_shared(db, *, share_token: str) -> dict:
    """无登录读分享（先看不登录）。token 前缀决定读故事还是读整本。"""
    if not share_token:
        return fail("缺少分享令牌", "missing_token")
    if share_token.startswith("b_"):
        return view_shared_book(db, owner_id=_owner_of_book_token(db, share_token))
    return view_shared_story(db, share_token=share_token)


def _owner_of_book_token(db, token: str) -> str:
    from models import User
    for u in db.scalars(select(User)):
        if _make_token("b", u.id) == token:
            return u.id
    # 兜底：找到任意一个其 token 命中的 owner
    for s in db.scalars(select(Story)):
        if _make_token("b", s.owner_id) == token:
            return s.owner_id
    return ""


def api_share_card(db, *, kind: str, target_id: str) -> dict:
    try:
        return ok(make_card_data(db, kind=kind, target_id=target_id))
    except PermissionError as e:
        return fail(str(e), "not_shareable")
    except ValueError as e:
        return fail(str(e), "bad_kind")
