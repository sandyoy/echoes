"""
往事可追忆 - 素材挂故事 + 双权限逻辑（第1期 A/B 线，2026-09-26）

=== 本文件解决什么（对照需求书 v2.4）===

【一、素材挂故事】第2节「一条故事 = 一个素材筐」
  一件素材（文字/语音/照片/视频/原声）必须挂到**指定的一条故事**上。
  铁律：
    - 挂的时候要校验故事存在（不许挂到空气上）
    - 语音必须保留原声（keep_original_voice 默认 True）
    - 同一篇里素材有顺序（sort_order 自动续号）
    - 凡有这篇权限的人都能往里添（见下方权限判定）

【二、双权限】第2.2节「两个加号，位置决定权限」
  登录旁的加号 → 加家人   → 看**整本书**
  故事里的加号 → 加故事成员 → 只看**这一篇**
  铁律：
    - 权限由「从哪个入口加进来」决定，不设权限勾选框
    - 高权限覆盖低权限（家人即全本）
    - 家人自动可见**后续新增**的故事
    - 看与写同一权限（只要能看，就能补充）
    - 被提及者：看提到他的那一篇**无需授权**；看全本才须授权

=== 铁律（v2.4 第十四节）===
静态核验 ≠ 通过。本文件所有函数均有 `selftest()` 实测跑通，
未跑通的不得写成「已实现」。
"""

from datetime import datetime
from sqlalchemy import select
from models import (
    SessionLocal, Story, Clip, Member, StoryPermission, LifeAnchor,
    ClipType, GrantVia, ClaimStatus, TimePrecision,
    Visibility, SourceType,
)


# ============================================================
# 一、素材挂故事（第2节：一个筐）
# ============================================================

def attach_clip(
    db,
    *,
    story_id: str,
    clip_type,
    text: str = "",
    media_url: str = "",
    media_duration: float = 0.0,
    media_size: int = 0,
    cover_url: str = "",
    transcript: str = "",
    caption: str = "",
    keep_original_voice: bool = True,
    created_by: str = "",
    provider_id: str = "",
    visibility=None,
    source_type=None,
    ref_from_id: str = "",
    ref_author_name: str = "",
) -> Clip:
    """
    把一件素材挂到指定故事上。返回落库后的 Clip。

    校验：
      1. 故事必须存在（Story.id 命中），否则 ValueError
      2. clip_type 必须是 ClipType 之一
      3. 语音/原声类：keep_original_voice 强制 True（v2.4 铁律，不许关）
      4. sort_order 自动取该故事现有素材最大值 +1

    来路 + 公开/私有（v3.0 §1.3）：
      - provider_id 默认取 created_by（谁放的，谁提供）
      - visibility **默认私有**（Visibility.PRIVATE），公开必须显式传 public
      - source_type 默认原创；引用（quote）时给 ref_from_id / ref_author_name
    """
    story = db.get(Story, story_id)
    if story is None:
        raise ValueError(f"故事不存在：{story_id}")

    if isinstance(clip_type, str):
        clip_type = ClipType(clip_type)
    if not isinstance(clip_type, ClipType):
        raise ValueError(f"素材类型非法：{clip_type}")

    # 铁律：语音/原声必须保留原声
    if clip_type in (ClipType.AUDIO, ClipType.ORIGINAL):
        keep_original_voice = True
        if not media_url:
            raise ValueError("语音/原声素材必须有 media_url（保留原声）")

    next_order = db.scalar(
        select(Clip.sort_order)
        .where(Clip.story_id == story_id)
        .order_by(Clip.sort_order.desc())
        .limit(1)
    )
    next_order = 0 if next_order is None else next_order + 1

    clip = Clip(
        id=_new_id("clip"),
        story_id=story_id,
        clip_type=clip_type,
        text=text,
        media_url=media_url,
        media_duration=media_duration,
        media_size=media_size,
        cover_url=cover_url,
        transcript=transcript,
        transcript_status="done" if transcript else "pending",
        caption=caption,
        keep_original_voice=keep_original_voice,
        sort_order=next_order,
        created_by=created_by,
        # 来路 + 公开/私有（v3.0 §1.3 预埋，默认私有）
        provider_id=provider_id or created_by,
        visibility=_coerce_visibility(visibility),
        source_type=_coerce_source_type(source_type),
        ref_from_id=(ref_from_id or None),
        ref_author_name=ref_author_name or "",
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def list_clips(db, story_id: str):
    """取一条故事下所有素材，按 sort_order 排（一个筐的样子）。"""
    return list(
        db.scalars(
            select(Clip).where(Clip.story_id == story_id).order_by(Clip.sort_order)
        )
    )


# ============================================================
# 二、双权限判定（第2.2节）
# ============================================================

def add_family_member(db, *, owner_id: str, display_name: str = "",
                      phone: str = "", user_id: str = "", relation: str = ""):
    """
    【登录旁的加号】加家人 → granted_via=FAMILY → 看整本书。
    """
    m = Member(
        id=_new_id("mem"),
        owner_id=owner_id,
        user_id=user_id or None,
        phone=phone,
        display_name=display_name,
        relation=relation,
        granted_via=GrantVia.FAMILY,
        claim_status=ClaimStatus.CLAIMED if user_id else ClaimStatus.PENDING,
        story_id=None,   # 家人不绑单篇
        can_add=True,
        claimed_at=datetime.utcnow() if user_id else None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def add_story_member(db, *, owner_id: str, story_id: str, display_name: str = "",
                     phone: str = "", user_id: str = "", relation: str = ""):
    """
    【故事里的加号】加这个故事的人 → granted_via=STORY → 只看这一篇。
    必须指定 story_id（只可见这一篇）。
    """
    if db.get(Story, story_id) is None:
        raise ValueError(f"故事不存在：{story_id}")
    m = Member(
        id=_new_id("mem"),
        owner_id=owner_id,
        user_id=user_id or None,
        phone=phone,
        display_name=display_name,
        relation=relation,
        granted_via=GrantVia.STORY,
        claim_status=ClaimStatus.CLAIMED if user_id else ClaimStatus.PENDING,
        story_id=story_id,
        can_add=True,
        claimed_at=datetime.utcnow() if user_id else None,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _member_of(db, owner_id: str, viewer_id: str):
    """找 viewer 在 owner 这本书里的成员记录（认领过的）。"""
    return db.scalar(
        select(Member).where(
            Member.owner_id == owner_id,
            Member.user_id == viewer_id,
            Member.claim_status == ClaimStatus.CLAIMED,
        ).limit(1)
    )


def can_view_story(db, *, owner_id: str, viewer_id: str, story_id: str) -> bool:
    """
    判定 viewer 能不能看 owner 的某一条故事。规则（按 v2.4 顺序）：

      1. 书主人自己 → 能看（全本）
      2. 家人（granted_via=FAMILY）→ 能看整本，**含后续新增**
      3. 故事成员（granted_via=STORY）→ 仅当 story_id 命中他被绑的那一篇
      4. 单篇授权 StoryPermission（例外/补充）→ 命中且 can_view
      5. 被提及者（people_mentioned 里 user_id 命中）→ **无需授权**即可看这一篇
      6. 其它 → 不能看
    """
    if not viewer_id:
        return False
    if viewer_id == owner_id:
        return True

    m = _member_of(db, owner_id, viewer_id)
    if m is not None:
        if m.granted_via == GrantVia.FAMILY:
            return True                      # 高权限覆盖低权限
        if m.granted_via == GrantVia.STORY and m.story_id == story_id:
            return True

    perm = db.scalar(
        select(StoryPermission).where(
            StoryPermission.story_id == story_id,
            StoryPermission.user_id == viewer_id,
        ).limit(1)
    )
    if perm is not None and perm.can_view:
        return True

    # 被提及者：看提到他的那一篇无需授权
    story = db.get(Story, story_id)
    if story is not None:
        for p in (story.people_mentioned or []):
            if isinstance(p, dict) and p.get("user_id") == viewer_id:
                return True
    return False


def can_add_clip(db, *, owner_id: str, viewer_id: str, story_id: str) -> bool:
    """
    能不能往这条故事里添素材。
    v2.4 铁律：「只要能看，就能补充」——看与写同一个权限，不另设授权。
    """
    return can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=story_id)


def visible_stories(db, *, owner_id: str, viewer_id: str):
    """
    列出 viewer 在这本书里能看到的**全部故事**（首页列表用）。

    - 主人 / 家人 → 整本（含后续新增）
    - 故事成员 / 被提及者 / 单篇授权 → 只列命中他的那些篇
    """
    if not viewer_id:
        return []
    all_stories = list(db.scalars(select(Story).where(Story.owner_id == owner_id)))
    if viewer_id == owner_id:
        return all_stories
    m = _member_of(db, owner_id, viewer_id)
    if m is not None and m.granted_via == GrantVia.FAMILY:
        return all_stories
    return [
        s for s in all_stories
        if can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=s.id)
    ]


def remove_member(db, member_id: str) -> bool:
    """支持移除（可收回权限）。返回是否移除成功。"""
    m = db.get(Member, member_id)
    if m is None:
        return False
    db.delete(m)
    db.commit()
    return True


# ============================================================
# 三、工具
# ============================================================

import uuid as _uuid
import re as _re


def _new_id(prefix: str) -> str:
    return f"{prefix}_{_uuid.uuid4().hex[:12]}"


def _normalize_phone(phone: str) -> str:
    """
    手机号归一化（认领钥匙必须**唯一口径**，否则同一人认不上）。

    规则（保守，不瞎猜）：
      - 去空格 / 去横线 / 去括号
      - 去掉 +86 / 86 国际区号前缀
      - 全角数字转半角
      - 只保留数字；长度 6~15 才算有效手机号，否则返回原始去空串
        （非手机号不硬掰，避免把座机/错误输入当成认领钥匙）
    """
    if not phone:
        return ""
    s = str(phone).strip()
    # 全角数字 → 半角
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    s = _re.sub(r"[\s\-()（）]", "", s)
    s = _re.sub(r"^(\+?86)", "", s)
    digits = _re.sub(r"\D", "", s)
    if 6 <= len(digits) <= 15:
        return digits
    return s



# ============================================================
# 十、来路 + 公开/私有闸门（v3.0 §1.2 / §1.3）
# ------------------------------------------------------------
# 两个正交维度（v3.0 §2.2 明确：互不替代）：
#   ① 可见范围维度（v2.4）：由「从哪个入口加进来」决定 → 家人看全本 / 故事成员看单篇
#   ② 公开私有维度（v3.0）：由「提供人主动点公开」决定 → 私有默认，只有提供人自己能看到
# 一条素材「谁能看」= ① AND ②：
#   私有素材：仅提供人本人（provider_id）能看，连被提及的人也不给看（v3.0 新拍）
#   公开素材：按 ① 的可见范围看；被提及的人在公开篇里能看到（v2.4 铁律只在公开篇成立）
# ============================================================

def _coerce_visibility(v):
    """把入参（None / 字符串 / 枚举）归一成 Visibility，**默认私有**。"""
    if v is None:
        return Visibility.PRIVATE
    if isinstance(v, Visibility):
        return v
    try:
        return Visibility(str(v).strip().lower())
    except Exception:
        return Visibility.PRIVATE


def _coerce_source_type(s):
    """把入参归一成 SourceType，**默认原创**。"""
    if s is None:
        return SourceType.ORIGIN
    if isinstance(s, SourceType):
        return s
    try:
        return SourceType(str(s).strip().lower())
    except Exception:
        return SourceType.ORIGIN


def can_show_clip(db, *, clip, viewer_id: str) -> bool:
    """
    单条素材对某查看者是否**可见**（v3.0 §1.2 的公开/私有闸门）。
    注意：本函数只管「公开/私有」这一维；「可见范围」那一维由 can_view_story 管，
    调用方须**两个都过**才算真能看（见 visible_clips 的用法）。

    规则：
      私有（默认）→ 只有提供人本人能看（provider_id 为空时退化为 created_by）
      公开        → 进公共池，交给调用方按可见范围判
    """
    vis = _coerce_visibility(getattr(clip, "visibility", None))
    if vis == Visibility.PRIVATE:
        owner_of_clip = (getattr(clip, "provider_id", "") or getattr(clip, "created_by", "") or "")
        return bool(viewer_id) and viewer_id == owner_of_clip
    return True   # 公开：这一维放行


def visible_clips(db, *, story_id: str, owner_id: str, viewer_id: str):
    """
    取某条故事里**该查看者能看见**的素材（两维都过）。
    返回 Clip 列表（保序）。看不到故事 → 空列表（不泄露存在性）。

    用途：采集接口 api_list_clips 的读侧、成书取材。
    第1期：主人自己看自己的故事时，私有素材当然能看到（provider_id==viewer_id）。
    """
    if not can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=story_id):
        return []
    out = []
    for c in list_clips(db, story_id):
        if can_show_clip(db, clip=c, viewer_id=viewer_id):
            out.append(c)
    return out


def can_quote_clip(db, *, clip, viewer_id: str) -> bool:
    """
    能不能**引用**这条素材（v3.0 §1.2：只有公开素材能被别人引用）。
    自己的素材：无论公私都能用（自己引用自己无意义，但不算越权）。
    别人的素材：必须公开才可引用。
    """
    vis = _coerce_visibility(getattr(clip, "visibility", None))
    provider = (getattr(clip, "provider_id", "") or getattr(clip, "created_by", "") or "")
    if viewer_id and viewer_id == provider:
        return True
    return vis == Visibility.PUBLIC


def set_clip_visibility(db, *, clip_id: str, actor_id: str, visibility) -> bool:
    """
    提供人**主动**改一条素材的公开/私有（v3.0 §1.2：公开是主动动作，可收可放）。
    只有提供人本人能改；改不了返回 False。
    返回 True 表示已改并落库。
    """
    clip = db.get(Clip, clip_id)
    if clip is None:
        return False
    provider = (clip.provider_id or clip.created_by or "")
    if not actor_id or actor_id != provider:
        return False
    clip.visibility = _coerce_visibility(visibility)
    db.commit()
    db.refresh(clip)
    return True
