"""
往事可追忆 - 待认领 / 认领（第1期 A 线，2026-09-27）

=== 本文件解决什么（对照需求书 v2.4 第八之二节）===

【场景】写故事的人（张三）要把老李写进故事，但**老李可能还没有账号**。
       因此必须先按「手机号 / 名字」把人登记下来，形成一条「待认领」。

【两条认领路】
  ① 手机号匹配 → **自动认领**（无需对方点任何东西，登录即认领）
  ② 手机号对不上 → **按名字搜索认领**（须写故事方 = 登记人确认）

【铁律】
  - 写故事的人**必须能先把人写进去**，不能因为对方没账号就写不成
  - 对方**什么时候上来都行**，早来晚来都能认到自己那份
  - **不需要事先通知他、不需要他同意**
  - 认领成功 → 首页出现「**有 N 篇故事提到了你**」
  - 被提到的人看「提到自己的那篇」**永远不需要授权**；授权只出现在「他想要全本」

=== 本文件落地的东西 ===
  register_claim()        登记一条待认领（手机号 or 名字）
  auto_claim_on_login()   手机号自动认领：老李注册/登录 → 认领所有等他的记录，
                          并**顺带把 Member 也认领掉**（权限生效的最后一步）
  search_claims_by_name() 名字搜索认领（候选列表，等登记人确认）
  confirm_by_owner()      登记人确认（写故事方点头才生效）
  pending_mentioned_count()/mentioned_stories()  「有 N 篇故事提到了你」
  claim_everything_for()  一次性把这个人所有待认领都认掉（登录时调用）

=== 铁律（v2.4 第十四节）===
静态核验 ≠ 通过。本文件所有函数均有 selftest() 实测跑通（见 selftest_claim.py），
未跑通的不得写成「已实现」。
"""

from datetime import datetime

from sqlalchemy import select, func

from models import (
    SessionLocal, Story, Member, Claim,
    GrantVia, ClaimStatus,
)
from permissions import _new_id, _normalize_phone  # noqa: F401  (复用同一套工具)


# ============================================================
# 一、登记（写故事的人把人写进去 —— 对方还没账号也行）
# ============================================================

def register_claim(db, *, owner_id: str, phone: str = "", display_name: str = "",
                   story_id: str = None) -> Claim:
    """
    登记一条「待认领」。

    参数：
      owner_id     写故事的人（登记人）
      phone        手机号（认领钥匙；优先）
      display_name 名字（手机号对不上时的备选认领路）
      story_id     可选。指名道姓提到谁时传入；不传 = 泛泛登记一个人

    校验：
      - phone 与 display_name 至少有一个，否则无法认领（ValueError）
      - story_id 若给了，故事必须存在
      - 同一手机号 + 同一登记人 + 未认领 → 不重复登记（返回已有那条，幂等）
    """
    phone = _normalize_phone(phone)
    display_name = (display_name or "").strip()

    if not phone and not display_name:
        raise ValueError("登记待认领至少需要 手机号 或 名字 之一")
    if story_id and db.get(Story, story_id) is None:
        raise ValueError(f"故事不存在：{story_id}")

    # 幂等：同一登记人对同一手机号只留一条未认领记录
    if phone:
        exist = db.scalar(
            select(Claim).where(
                Claim.owner_id == owner_id,
                Claim.phone == phone,
                Claim.status == ClaimStatus.PENDING,
            ).limit(1)
        )
        if exist is not None:
            # 补齐名字 / 补 story_id（允许后续追加提到的那一篇）
            changed = False
            if display_name and not exist.display_name:
                exist.display_name = display_name
                changed = True
            if story_id and exist.story_id is None:
                exist.story_id = story_id
                changed = True
            if changed:
                db.commit()
                db.refresh(exist)
            return exist

    c = Claim(
        id=_new_id("claim"),
        story_id=story_id,
        owner_id=owner_id,
        phone=phone,
        display_name=display_name,
        match_type="phone" if phone else "name",
        status=ClaimStatus.PENDING,
        confirmed_by_owner=(not phone),   # 无手机号只能走名字路 —— 但名字路须确认，
                                          # 这里登记时尚不确认，见 confirm_by_owner
    )
    if not phone:
        c.match_type = "name"
        c.confirmed_by_owner = False
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ============================================================
# 二、认领路 ①：手机号自动认领（无需对方点任何东西）
# ============================================================

def auto_claim_on_login(db, *, user_id: str, phone: str) -> dict:
    """
    老李注册/登录（带手机号）→ 系统自动认领所有等他的记录。

    做三件事：
      1. 把 Claim 里 phone 命中、状态 PENDING 的全部标记 CLAIMED
      2. 把 Team 表（Member）里 phone 命中、状态 PENDING 的也认领掉
         —— 权限生效的最后一步（家人/故事成员由此真正可看）
      3. 返回此人现在能看到的所有 owner（书的拥有者）集合

    返回 dict：
      {"claimed_claims": [...], "claimed_members": [...],
       "owners": [...], "count_stories": N}
    """
    phone = _normalize_phone(phone)
    if not phone:
        raise ValueError("手机号为空，无法自动认领")
    if not user_id:
        raise ValueError("user_id 为空")

    now = datetime.utcnow()

    # --- 1. 认领 Claim ---
    claims = list(db.scalars(
        select(Claim).where(
            Claim.phone == phone,
            Claim.status == ClaimStatus.PENDING,
        )
    ))
    for c in claims:
        c.status = ClaimStatus.CLAIMED
        c.claimed_user_id = user_id
        c.claimed_at = now

    # --- 2. 认领 Member（同一手机号、同样还没认领的成员记录）---
    members = list(db.scalars(
        select(Member).where(
            Member.phone == phone,
            Member.claim_status == ClaimStatus.PENDING,
        )
    ))
    for m in members:
        m.user_id = user_id
        m.claim_status = ClaimStatus.CLAIMED
        m.claimed_at = now

    db.commit()

    # owners 必须返回**此人全部**归属（不只是本次新认领的）——
    # 否则第二次登录只会返回增量，首页会漏掉以前认领过的书。
    owners = sorted(
        {m.owner_id for m in db.scalars(
            select(Member).where(
                Member.user_id == user_id,
                Member.claim_status == ClaimStatus.CLAIMED,
            )
        )}
        | {c.owner_id for c in db.scalars(
            select(Claim).where(
                Claim.claimed_user_id == user_id,
                Claim.status == ClaimStatus.CLAIMED,
            )
        )}
    )

    return {
        "claimed_claims": [c.id for c in claims],
        "claimed_members": [m.id for m in members],
        "owners": owners,
        "count_stories": len(_mentioned_story_ids(db, user_id=user_id, owners=owners)),
    }


# ============================================================
# 三、认领路 ②：按名字搜索认领（须写故事方确认）
# ============================================================

def search_claims_by_name(db, *, display_name: str, exclude_user_id: str = "") -> list:
    """
    手机号对不上时，按名字搜索我可能是谁的待认领记录。
    返回候选 Claim 列表（**只是候选，还没生效**，须登记人确认）。
    """
    display_name = (display_name or "").strip()
    if not display_name:
        return []
    return list(db.scalars(
        select(Claim).where(
            Claim.display_name == display_name,
            Claim.status == ClaimStatus.PENDING,
        )
    ))


def confirm_by_owner(db, *, claim_id: str, owner_id: str, user_id: str) -> bool:
    """
    登记人（写故事方）确认「对，这就是他」→ 名字路认领生效。

    铁律：按名字认领**必须**写故事方确认（防止重名冒领）。
    只有 claim.owner_id == owner_id 的登记人有权确认。
    确认后同步把该 owner 下同 phone/名字 的 Member 也认领掉。
    """
    c = db.get(Claim, claim_id)
    if c is None:
        return False
    if c.owner_id != owner_id:
        raise PermissionError("只有登记人本人能确认这条认领")
    if c.status == ClaimStatus.CLAIMED:
        return True

    now = datetime.utcnow()
    c.status = ClaimStatus.CLAIMED
    c.claimed_user_id = user_id
    c.confirmed_by_owner = True
    c.match_type = "name"
    c.claimed_at = now

    # 同步认领 Member（这条 claim 对应的成员记录）
    cond = (Member.owner_id == owner_id,
            Member.claim_status == ClaimStatus.PENDING)
    if c.phone:
        cond = cond + (Member.phone == c.phone,)
    elif c.display_name:
        cond = cond + (Member.display_name == c.display_name,)
    else:
        cond = cond + (Member.id == "__none__",)   # 既无手机号也无名字：不同步
    members = list(db.scalars(select(Member).where(*cond)))
    for m in members:
        m.user_id = user_id
        m.claim_status = ClaimStatus.CLAIMED
        m.claimed_at = now

    db.commit()
    return True


def reject_claim(db, *, claim_id: str, owner_id: str) -> bool:
    """登记人否认「这不是他」→ 标记 REJECTED，不再出现在候选里。"""
    c = db.get(Claim, claim_id)
    if c is None:
        return False
    if c.owner_id != owner_id:
        raise PermissionError("只有登记人本人能驳回这条认领")
    c.status = ClaimStatus.REJECTED
    db.commit()
    return True


# ============================================================
# 四、「有 N 篇故事提到了你」（首页提示 —— v2.4 明确要求）
# ============================================================

def _mentioned_story_ids(db, *, user_id: str, owners=None) -> list:
    """
    找出所有「提到了这个 user_id」的故事 id。

    命中三条路（任一即算提到）：
      ① story.people_mentioned 里 user_id 命中
      ② Claim 表里 claimed_user_id == user_id 且带 story_id
      ③ Member 表里 user_id 命中且带 story_id（被绑到单篇的故事成员）
    """
    if not user_id:
        return []
    hit = set()

    q = select(Story)
    if owners:
        q = q.where(Story.owner_id.in_(list(owners)))
    for s in db.scalars(q):
        for p in (s.people_mentioned or []):
            if isinstance(p, dict) and p.get("user_id") == user_id:
                hit.add(s.id)

    for c in db.scalars(select(Claim).where(
        Claim.claimed_user_id == user_id,
        Claim.status == ClaimStatus.CLAIMED,
    )):
        if c.story_id:
            hit.add(c.story_id)

    for m in db.scalars(select(Member).where(
        Member.user_id == user_id,
        Member.claim_status == ClaimStatus.CLAIMED,
    )):
        if m.story_id:
            hit.add(m.story_id)

    return sorted(hit)


def mentioned_stories(db, *, user_id: str):
    """首页提示用：返回提到了这个人的 Story 列表。"""
    ids = _mentioned_story_ids(db, user_id=user_id)
    if not ids:
        return []
    return list(db.scalars(select(Story).where(Story.id.in_(ids))))


def pending_mentioned_count(db, *, user_id: str) -> int:
    """「有 N 篇故事提到了你」里的 N。"""
    return len(_mentioned_story_ids(db, user_id=user_id))


# ============================================================
# 五、登录时总入口（前端登录后调这一个就够）
# ============================================================

def claim_everything_for(db, *, user_id: str, phone: str = "") -> dict:
    """
    登录后调这一个：把这个人所有待认领的都认掉，并返回首页要用的数字。

    返回：
      {"owners": [...], "claimed_claims": [...], "claimed_members": [...],
       "mentioned_count": N}
    """
    if phone:
        r = auto_claim_on_login(db, user_id=user_id, phone=phone)
    else:
        # 无手机号（微信用户常见：不一定绑手机）也要给出正确首页数字。
        # 09-29 修复：原先这里 owners/count_stories 直接置空，
        # 导致「有 N 篇提到了你」在未绑手机用户上**静默显示 0**——
        # 而该用户其实早就是某些书的家人/成员（此前登录认领过）。
        owners = sorted({
            m.owner_id for m in db.scalars(
                select(Member).where(
                    Member.user_id == user_id,
                    Member.claim_status == ClaimStatus.CLAIMED,
                )
            )
        })
        r = {"claimed_claims": [], "claimed_members": [], "owners": owners,
             "count_stories": 0}
    # count_stories 一律按「被提到的篇数」重算；无 owners 时不按书范围收窄，
    # 保证未绑手机用户也能看到"谁提到了我"。
    r["count_stories"] = len(_mentioned_story_ids(db, user_id=user_id,
                                                  owners=r.get("owners") or None))
    r["mentioned_count"] = pending_mentioned_count(db, user_id=user_id)
    return r


def list_pending_claims(db, *, owner_id: str) -> list:
    """登记人视角：我还有哪些人没被认领（后台/提醒用）。"""
    return list(db.scalars(
        select(Claim).where(
            Claim.owner_id == owner_id,
            Claim.status == ClaimStatus.PENDING,
        )
    ))


# ============================================================
# 六、自测（真跑真查库）
# ============================================================

def selftest():
    """
    自测不依赖临时库注入 —— 由 selftest_claim.py 统一跑。
    这里给一个最小自检，方便单文件 import 时快速验通路。
    """
    raise SystemExit("请跑 python3 selftest_claim.py（需要临时库隔离）")
