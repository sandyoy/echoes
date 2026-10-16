"""
往事可追忆 - 「登录旁的加号」加家人（家庭通讯录）链路（handler 层）v1.0
建立：2026-10-16（设计推进哨兵）

=== 为什么今天做本文件（这是一条「已确认未落地」的活）===
需求书 v3.0 §2.2【两个"加号"，位置决定权限】把权限模型钉死在两个入口上：
    | 加号位置          | 作用               | 可见范围          |
    | 登录旁的加号      | 加**家人**（家庭通讯录） | 看**整本书**（全部故事）|
    | 故事里的加号      | 加**这个故事的人**  | 只看**这一篇**     |
§2.3 补操作方式：「用**手机号**录入；对方已在小程序可直接**选名字**加入；加入后对方账号出现入口。」

**盘现状（10-16）：这两个加号，故事那个已经通了，家人那个还是断头。**
  [故事里的加号] 10-15 已落 `join_api.py`（§8之二.5「我也加进来」→ granted_via=STORY → 只看这一篇）。
  [登录旁的加号] **依旧是断头**：`permissions.add_family_member()` 是**内部函数**，
        全仓库 63 条路由**没有一条**通向它 → 前端"登录旁那个加号"无处可点。
        这跟 10-15 之前 join 链路的病是同一个：**头尾都在，中间断一节。**
  [尾] `can_view_story` 规则2「家人（granted_via=FAMILY）→ 能看整本，含后续新增」已就绪（permissions.py:220）。

**结论：本件就是把「登录旁加号」这一节补上，让 §2.2 两个加号在 API 层对称闭合。**

=== 与 join_api（故事级）的分工 · 不许串 ===
  join_api.py   = 故事里的加号  → granted_via=STORY → 只看这一篇（已落 10-15）
  family_api.py = 登录旁的加号  → granted_via=FAMILY → 看整本书（本件 10-16）
  两者**粒度不同、不能互相替代**；本件**绝不**代替书主人给人开全本给一个"只看过一篇"的人。

=== 对照需求书 v3.0 逐条落 ===
  §2.3「用手机号录入」      → ★api_add_family(phone=...) 登记：对方还没上过就 PENDING（待认领），
                              上了就由 claim_on_login 用同一手机号自动认领（复用既有 claim 机制）
  §2.3「对方已在小程序可直接选名字加入」→ ★api_search_user_by_name() 先搜出人（昵称/真名），
                              再由前端带着 user_id 调 api_add_family(user_id=...) 直接建成 CLAIMED
  §2.2「登录旁的加号 → 看整本书」  → ★granted_via=FAMILY、story_id=None（家人不绑单篇）→ can_view_story 规则2 放全本
  §2.3「加入后对方账号出现入口」   → 家属在我（书主人）这边的家庭通讯录里立即可见（api_family_list），
                              在对方那边走既有 api_my_memberships（families 段）+ api_mentioned
  §2.2「权限由从哪个入口加进来决定，不设权限勾选框」→ 本件**不提供任何 scope 参数**：
                              从这里进来**永远**是 FAMILY（看整本），没有第二个选项可勾
  §2.2 v3.0 补充「可见范围 与 公开/私有 是正交两维」→ 家人能看"整本书"指的是**书里对他可见的部分**，
                              不是"整本连别人私有篇都看"——可见性仍逐篇由 can_view_story 判（本件不动那道闸门）

=== 设计铁律（与 collect_api / join_api / book_api / share_api / storage_api 同）===
1. handler 不自己开 session，db 由调用方传
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **幂等**：同一个人加两次 → 不重复建 Member（返回 already_family=true、member_id 不变）
4. **绝不静默假装**：手机号/名字/user_id 一个都没给 → 明确 code，不返回假成功
5. **必须登录态才调**（加人是"参与"，§5.5「看不用登录，参与才登录」）
6. **不许把自己加成自己的家人**（is_self 拒）
7. **不提供 scope 参数**——从这里进来永远是 FAMILY（§2.2 铁律：不设权限勾选框）
"""

from sqlalchemy import select

from permissions import (
    _new_id, can_view_story, add_family_member,
)
from models import (
    SessionLocal, Story, Member, User, ClaimStatus, GrantVia,
)


# 中文口径（与其余 handler 同风格，不给老人看英文系统词）
NEED_LOGIN = "请先微信登录，再添加家人"
NO_TARGET = "请填手机号，或从名单里选一个家人"
IS_SELF = "这是你自己，不用加"
ALREADY_FAMILY = "这位家人已经在你的名单里了"


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

def _mask_phone(phone: str) -> str:
    """脱敏展示：138****8888。前端列表里给主人自己看也不铺全号。"""
    p = (phone or "").strip()
    if len(p) < 7:
        return p
    return p[:3] + "****" + p[-4:]


def _norm_phone(phone: str) -> str:
    """手机号归一：去空格/横线，保留数字。为认领对账用同一口径。"""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _display_of(db, user_id: str) -> str:
    u = db.get(User, user_id)
    if u is None:
        return ""
    return (getattr(u, "nick_name", "") or getattr(u, "real_name", "") or "")


def _find_user_by_name(db, name: str):
    """按名字搜人（§2.3「对方已在小程序可直接选名字加入」）。
    只按昵称/真名精确 + 前缀匹配，绝不做模糊猜测把人认错。"""
    n = (name or "").strip()
    if not n:
        return []
    rows = db.query(User).all()
    exact, prefix = [], []
    for u in rows:
        nick = (getattr(u, "nick_name", "") or "")
        real = (getattr(u, "real_name", "") or "")
        if n == nick or n == real:
            exact.append(u)
        elif nick.startswith(n) or real.startswith(n):
            prefix.append(u)
    # 精确优先；精确为零时给前缀命中（前端让用户再点一下确认）
    return exact if exact else prefix


def _existing_family(db, *, owner_id: str, user_id: str = "", phone: str = ""):
    """我（owner）的名单里，是否已有这条家人记录（幂等判据）。
    命中规则：user_id 相等 或 归一手机号相等。"""
    rows = db.query(Member).filter(
        Member.owner_id == owner_id,
        Member.granted_via == GrantVia.FAMILY,
    ).all()
    np = _norm_phone(phone)
    for m in rows:
        if user_id and m.user_id == user_id:
            return m
        if np and _norm_phone(m.phone) == np:
            return m
    return None


# ============================================================
# 三、对外接口（handler）
# ============================================================

def api_search_user_by_name(db, *, owner_id: str, name: str) -> dict:
    """
    GET /api/echoes/family/search?name=小李
    §2.3「对方已在小程序，可直接选名字加入」——先搜出人，前端列出来给主人点。
    返回候选（含 user_id / 显示名 / 是否已是家人），**只暴露最少信息**（不返手机号）。
    """
    if not owner_id:
        return fail(NEED_LOGIN, "login_required")
    hits = _find_user_by_name(db, name)
    cands = []
    for u in hits:
        if u.id == owner_id:
            continue  # 自己不作为候选
        disp = getattr(u, "nick_name", "") or getattr(u, "real_name", "") or ""
        existing = _existing_family(db, owner_id=owner_id, user_id=u.id)
        cands.append({
            "user_id": u.id,
            "display_name": disp,
            "already_family": existing is not None,
            "relation": (existing.relation if existing else ""),
        })
    return ok({"candidates": cands, "count": len(cands)})


def api_add_family(db, *, owner_id: str, user_id: str = "",
                   phone: str = "", display_name: str = "",
                   relation: str = "") -> dict:
    """
    POST /api/echoes/family/add
    ★ §2.2「登录旁的加号」：加**家人**（家庭通讯录）→ granted_via=FAMILY → **看整本书**。

    参数（§2.3 两条路，二选一，至少给一个）
      user_id       对方已在小程序（走「选名字」那条路），直接建成 CLAIMED
      phone         对方还没上过（走「手机号录入」那条路），建成 PENDING 待认领，
                    对方以后用同一手机号登录 → claim_on_login 自动认领（复用既有机制）
      display_name  可选，名单里显示的名（未注册也能显示）
      relation      可选，称呼：女儿/儿子/朋友

    ★ 注意：**没有 scope 参数**。从这里进来永远是 FAMILY（看整本）——
      这是 §2.2 铁律「权限由从哪个入口加进来决定，不设权限勾选框」的代码体现。
    """
    if not owner_id:
        return fail(NEED_LOGIN, "login_required")

    np = _norm_phone(phone)
    if not user_id and not np and not (display_name or "").strip():
        return fail(NO_TARGET, "no_target")

    # 不许把自己加成自己的家人
    if user_id and user_id == owner_id:
        return fail(IS_SELF, "is_self")

    # 幂等：名单里已经有了 → 原样返回，不翻倍
    existing = _existing_family(db, owner_id=owner_id, user_id=user_id, phone=np)
    if existing is not None:
        return ok({
            **_family_payload(db, owner_id=owner_id, member=existing),
            "already_family": True,
        })

    # 若给了 user_id，把显示名/手机号补齐（前端只带了 id 也能建成完整记录）
    if user_id and not (display_name or "").strip():
        display_name = _display_of(db, user_id)
    if user_id and not np:
        u = db.get(User, user_id)
        np = _norm_phone(getattr(u, "phone", "") if u else "")

    member = add_family_member(
        db, owner_id=owner_id,
        display_name=display_name, phone=np,
        user_id=user_id, relation=relation,
    )
    payload = _family_payload(db, owner_id=owner_id, member=member)
    payload["already_family"] = False
    return ok(payload)


def api_family_list(db, *, owner_id: str) -> dict:
    """
    GET /api/echoes/family/list
    §2.3「加入后对方账号出现入口」——书主人这边的**家庭通讯录**：
    我加了哪些家人、谁是待认领（还没上过）、谁能看整本。
    """
    if not owner_id:
        return fail(NEED_LOGIN, "login_required")

    rows = db.query(Member).filter(
        Member.owner_id == owner_id,
        Member.granted_via == GrantVia.FAMILY,
    ).all()

    claimed, pending = [], []
    for m in rows:
        item = {
            "member_id": m.id,
            "user_id": m.user_id or "",
            "display_name": m.display_name or _display_of(db, m.user_id or ""),
            "relation": m.relation or "",
            "phone_masked": _mask_phone(m.phone or ""),
            "scope": "book",                     # 家人=看整本（§2.2）
            "claimed": m.claim_status == ClaimStatus.CLAIMED,
        }
        (claimed if item["claimed"] else pending).append(item)
    return ok({
        "family": claimed,          # 已上过、已认领的家人
        "pending": pending,         # 待认领（还没上过，靠手机号等着）
        "family_count": len(claimed),
        "pending_count": len(pending),
    })


def api_remove_family(db, *, owner_id: str, member_id: str) -> dict:
    """
    POST /api/echoes/family/remove
    我从名单里移出一个家人 → 他不再能看整本（但**不动**他作为"故事成员"的单篇关系）。
    只允许书主人本人删自己名单里的家人；不能删别人的名单。
    """
    if not owner_id:
        return fail(NEED_LOGIN, "login_required")
    if not member_id:
        return fail("缺少 member_id", "bad_request")

    m = db.get(Member, member_id)
    if m is None:
        return fail("名单里没这条记录", "not_found")
    if m.owner_id != owner_id:
        return fail("这不是你名单里的家人", "forbidden")
    if m.granted_via != GrantVia.FAMILY:
        return fail("这条是单篇成员，不在家人名单里（请到那一篇里移除）", "not_family")

    db.delete(m)
    db.commit()
    return ok({"removed": True, "member_id": member_id})


# ============================================================
# 四、返回载荷
# ============================================================

def _family_payload(db, *, owner_id: str, member) -> dict:
    """加家人成功后回给前端的载荷：告诉他"这位家人现在能看整本"。"""
    total = db.query(Story).filter(Story.owner_id == owner_id).count()
    return {
        "member_id": member.id,
        "owner_id": owner_id,
        "user_id": member.user_id or "",
        "display_name": member.display_name or _display_of(db, member.user_id or ""),
        "relation": member.relation or "",
        "phone_masked": _mask_phone(member.phone or ""),
        "granted_via": "family",
        "granted_scope": "book",              # ★ 看整本书（§2.2）
        "claimed": member.claim_status == ClaimStatus.CLAIMED,
        "book_story_count": total,            # 这本书现在有多少篇，家人能看的就是这些（对他可见的部分）
    }
