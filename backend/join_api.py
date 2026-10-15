"""
往事可追忆 - 「我也加进来」加入链路（handler 层）v1.0
建立：2026-10-15（设计推进哨兵）

=== 为什么今天做本文件（这是一条「已确认未落地」的活）===
需求书 v3.0 §8之二.5【情况①：有故事，分享故事给你看】写死了一条**完整链路**：
    「老人/子女选一篇故事 → 点【分享给朋友】→ 微信转发卡片 → 对方点开直接读（不用登录）
      → 篇末『这是李桂芳的故事，里面提到了你 [ 我也加进来 ]』→ 点按钮
      → 微信一键登录 → **默认加入"这一篇"**。」
§8之二.8 亦写死登录点：「① 收到故事的人 → 看完后、想加进来时 → 故事页底部按钮」。
§5.5/§十 精神：「看不用登录，参与才登录」——**参与那一下，必须有后端接住。**

**盘现状（10-15）：这条链路的头尾都在，中间断了一节：**
  [头]  `share_api.make_story_share` 造 token + `view_shared_story` 无登录读公开篇，
        并明确返回 `can_join: True`（"看完后想加进来 → 走登录"）。
  [断]  **`can_join=True` 之后没人接**：全仓库 58 个 handler 里，
        没有任何一条把"刚登录的人"挂进"他刚看完的那一篇"。
        `permissions.add_story_member()` 是个**内部函数**，只被自测调用过，
        **没有任何 API 入口通向它** → 前端拿到 can_join=True 却无处可点。
  [尾]  `can_view_story` 规则3（故事成员→只看这一篇）/ 规则5（被提及者→无需授权）已就绪。
**结论：链路在"点【我也加进来】"那一下断头。本件补的就是这一节。**

=== 对照需求书 v3.0 逐条落 ===
  §8之二.5 「点按钮 → 登录 → 默认加入"这一篇"」
       → ★api_join_by_share()：凭 share_token 加入那一篇（**默认粒度=单篇**，不是整本）
  §8之二.5 「被提一句的人，只看这一篇，不看全本——不需要任何授权」
       → 加入后 granted_via=STORY、story_id=那一篇 → can_view_story 规则3 只放这一篇
  §8之二.5 「只有一种情况要授权：他想看全本」→ 本件**不做**升全本（那是书主人决定的另一码事），
       只在返回里给 `can_upgrade_to_family=False` 的口径位（不擅自替书主人开门）
  §8之二.5 「走的是微信一键登录后才加进来」→ 本 handler **强制要 user_id**（登录态才调），
       无 user_id → `login_required`（不许无登录偷偷加人）
  §1.2 铁律3 / §8之二.7 v3.0 改 「私有库提到的人不给看」
       → ★加入时**必须先核这篇对他是可见的**：先过 `can_view_story`；
         若他既不是被提及者、又没有既有关系 → 拒绝（`not_mentioned`），
         不许凭一个 token 就把人塞进别人的私有篇
  §8之二.5 「这是<owner>的故事，里面提到了你」→ api_join_target() 给前端拼这句所需的一切
  §2.4/§5.5 「『有你的故事』入口」→ 加入后立即可在 api_mentioned 里出现（复用既有）

=== 设计铁律（与 collect_api / book_api / share_api / storage_api 同）===
1. handler 不自己开 session，db 由调用方传
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **幂等**：同一个人点两次 → 不重复建 Member（返回 already_joined=true、member_id 不变）
4. **绝不静默假装**：token 失效 / 不满足加入条件 → 明确 code，不返回假成功
5. **默认单篇**：加入粒度永远是"这一篇"；升全本不在这里擅自发生
"""

from sqlalchemy import select

from permissions import (
    _new_id, can_view_story, add_story_member,
)
from models import (
    SessionLocal, Story, Member, User, ClaimStatus, GrantVia,
)


# 中文口径（与其余 handler 同风格，不给老人看英文）
TOKEN_GONE = "这个分享打不开了（可能已被作者收回）"
NEED_LOGIN = "请先微信登录，再加入"
NOT_REACHABLE = "你还没有加入这篇的资格（这篇没有公开提到你，或作者已收回）"
ALREADY_FAMILY = "你已经能看这本书了，不用再加这一篇"


# ============================================================
# 一、统一信封
# ============================================================

def ok(data=None, **extra):
    out = {"ok": True, "data": data if data is not None else {}, "error": "", "code": ""}
    out.update(extra)
    return out


def fail(msg: str, code: str = "bad_request", **extra):
    out = {"ok": False, "data": None, "error": msg, "code": code}
    out.update(extra)
    return out


# ============================================================
# 二、内部工具
# ============================================================

def _owner_display_name(db, owner_id: str) -> str:
    """书主人显示名（篇末那句「这是<X>的故事」用）。"""
    u = db.get(User, owner_id)
    if u is None:
        return ""
    return (getattr(u, "nick_name", "") or getattr(u, "real_name", "") or "")


def _my_member_of_story(db, *, owner_id: str, user_id: str, story_id: str):
    """我在这本书里的成员记录（认领过的）。返回 Member 或 None。"""
    return db.scalar(
        select(Member).where(
            Member.owner_id == owner_id,
            Member.user_id == user_id,
            Member.claim_status == ClaimStatus.CLAIMED,
        ).limit(1)
    )


def _resolve_story_by_token(db, share_token: str):
    """
    把分享令牌解回 Story（复用 share_api 的同一算法，不另造第二套口径）。
    返回 Story 或 None。只有**仍可分享**（至少一条公开素材）的篇才解得开。
    """
    if not share_token or not share_token.startswith("s_"):
        return None
    from share_api import _make_token, can_share_story
    for s in db.scalars(select(Story)):
        if _make_token("s", s.id) == share_token:
            if can_share_story(db, story_id=s.id):
                return s
    return None


def _joinable(db, *, story, viewer_id: str) -> tuple:
    """
    ★ 核心判据：这个人**有没有资格**被加进这一篇？
    返回 (ok: bool, code: str, reason: str)

    许可来源（§8之二.5 / §1.2 铁律3）：
      a) 他是这篇的**被提及者**（story.people_mentioned 里 user_id 命中）→ 可以
      b) 他已通过别的路（家人 / 单篇授权）能看这篇 → 可以（幂等，不重复建）
      c) 两者都不是 → **拒绝**（不许凭一个 token 把他塞进别人的篇）
    """
    if viewer_id == story.owner_id:
        return (False, "is_owner", "这是你自己的故事，不用加")
    # a) 被提及者
    mentioned = False
    for p in (story.people_mentioned or []):
        if isinstance(p, dict) and p.get("user_id") == viewer_id:
            mentioned = True
            break
    # b) 已可看（家人/既有成员/单篇授权）
    already = can_view_story(db, owner_id=story.owner_id,
                             viewer_id=viewer_id, story_id=story.id)
    if mentioned or already:
        return (True, "", "")
    return (False, "not_mentioned", NOT_REACHABLE)


# ============================================================
# 三、对外接口（handler）
# ============================================================

def api_join_target(db, *, share_token: str, user_id: str = "") -> dict:
    """
    GET /api/echoes/join/target
    点开分享卡片后，**篇末那一块**要显示什么（§8之二.5 篇末那一句）。

    给前端：
      owner_display_name  "李桂芳"
      headline            "这是李桂芳的故事，里面提到了你"
      already_joined      我是不是已经加过了（决定按钮显示"我也加进来"还是"你已经加进来了"）
      can_join            我能不能加（被提及 或 已可看）
      need_login          无 user_id 时为 true → 前端此时先去走微信登录
      join_granularity    "story"（默认加入"这一篇"，§8之二.5）
      can_upgrade_to_family  false（升全本由书主人决定，不在这里开）
    """
    story = _resolve_story_by_token(db, share_token)
    if story is None:
        return fail(TOKEN_GONE, "share_gone")

    owner_name = _owner_display_name(db, story.owner_id)
    out = {
        "story_id": story.id,
        "title": story.title or "",
        "time_raw": story.time_raw or "",
        "owner_display_name": owner_name,
        "headline": f"这是{owner_name}的故事，里面提到了你" if owner_name
                    else "这个故事里提到了你",
        "join_granularity": "story",
        "can_upgrade_to_family": False,
        "need_login": not bool(user_id),
        "already_joined": False,
        "can_join": False,
    }

    if not user_id:
        # 看不用登录（§8之二.8）——这里只是拿不到"我加没加过"，不报错
        return ok(out)

    jm = _my_member_of_story(db, owner_id=story.owner_id,
                             user_id=user_id, story_id=story.id)
    if jm is not None:
        out["already_joined"] = True
        out["can_join"] = False
        out["member_id"] = jm.id
        return ok(out)

    can, code, reason = _joinable(db, story=story, viewer_id=user_id)
    out["can_join"] = bool(can)
    if not can:
        out["reason"] = reason
        out["reason_code"] = code
    return ok(out)


def api_join_by_share(db, *, share_token: str, user_id: str,
                      display_name: str = "", phone: str = "") -> dict:
    """
    POST /api/echoes/join/story
    ★ §8之二.5 那一下：看完 → 点【我也加进来】→ （已登录）→ **默认加入"这一篇"**。

    参数
      share_token   分享令牌（无登录读用的同一把钥匙）
      user_id       必填（登录态才调；§8之二.8「参与才登录」）
      display_name  可选，加入时的称呼（书主人那边看到的名）
      phone         可选，便于后续待认领对账

    返回
      joined / already_joined  —— 幂等
      member_id               —— 我在这本书里的成员记录
      granted_via = "story"   —— 只看这一篇（§8之二.5 不做全本）
      visible_story_ids       —— 加完后我能看的篇（= 这一篇，除非我本来就有别的身份）
    """
    if not user_id:
        return fail(NEED_LOGIN, "login_required")

    story = _resolve_story_by_token(db, share_token)
    if story is None:
        return fail(TOKEN_GONE, "share_gone")

    # 幂等：已经加过 → 直接回（member_id 不变）
    jm = _my_member_of_story(db, owner_id=story.owner_id,
                             user_id=user_id, story_id=story.id)
    if jm is not None:
        if jm.granted_via == GrantVia.FAMILY:
            return fail(ALREADY_FAMILY, "already_family",
                        member_id=jm.id, already_joined=True)
        return ok({**_joined_payload(db, story=story, member=jm, user_id=user_id),
                   "already_joined": True})

    # 资格闸门（§1.2 铁律3：不许凭 token 塞进别人的私有篇）
    can, code, reason = _joinable(db, story=story, viewer_id=user_id)
    if not can:
        return fail(reason, code)

    member = add_story_member(
        db, owner_id=story.owner_id, story_id=story.id,
        display_name=display_name, phone=phone, user_id=user_id,
    )
    payload = _joined_payload(db, story=story, member=member, user_id=user_id)
    payload["already_joined"] = False
    return ok(payload)


def api_my_memberships(db, *, user_id: str) -> dict:
    """
    GET /api/echoes/join/mine
    「我加入了哪些书 / 哪些篇」——加入之后，首页要能看见（否则加完就丢）。
    与 api_mentioned（§8之二.7 有 N 篇提到了你）互补：
      mentioned  = 别人写我（我被提及）
      memberships= 我主动加进去的
    """
    if not user_id:
        return fail(NEED_LOGIN, "login_required")

    rows = (
        db.query(Member)
          .filter(Member.user_id == user_id,
                  Member.claim_status == ClaimStatus.CLAIMED)
          .all()
    )
    families, story_members = [], []
    for m in rows:
        owner_name = _owner_display_name(db, m.owner_id)
        if m.granted_via == GrantVia.FAMILY:
            families.append({
                "member_id": m.id, "owner_id": m.owner_id,
                "owner_display_name": owner_name, "scope": "book",
            })
        else:
            s = db.get(Story, m.story_id) if m.story_id else None
            story_members.append({
                "member_id": m.id, "owner_id": m.owner_id,
                "owner_display_name": owner_name, "scope": "story",
                "story_id": m.story_id or "",
                "story_title": (s.title if s else "") or "",
            })
    return ok({
        "families": families,                       # 看整本
        "story_memberships": story_members,          # 只看这几篇
        "family_count": len(families),
        "story_count": len(story_members),
    })


def _joined_payload(db, *, story, member, user_id: str) -> dict:
    """加入成功后回给前端的载荷（也让前端知道"我现在能看什么"）。"""
    visible = []
    # 加完后我能看的篇：这一篇 + 我本来就能看的其它篇（家人则整本）
    all_s = db.query(Story).filter(Story.owner_id == story.owner_id).all()
    for s in all_s:
        if can_view_story(db, owner_id=story.owner_id,
                          viewer_id=user_id, story_id=s.id):
            visible.append(s.id)
    return {
        "story_id": story.id,
        "owner_id": story.owner_id,
        "owner_display_name": _owner_display_name(db, story.owner_id),
        "member_id": member.id,
        "granted_via": getattr(member.granted_via, "value", str(member.granted_via)),
        "granted_scope": ("book" if member.granted_via == GrantVia.FAMILY else "story"),
        "visible_story_ids": visible,
        "visible_count": len(visible),
    }
