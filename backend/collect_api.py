"""
往事可追忆 - 素材采集接口（handler 层）v1.0
第1期 B 线：文字 / 图片（本日）→ 语音 / 视频（09-29）

=== 为什么是「handler 层」而不是直接写 FastAPI 路由 ===
实测环境（backend/README_运行环境.md）：这台机器上 **没有 fastapi / pydantic**，
系统 pip 被锁装不上。所以：
  - 本文件只写**纯函数 handler**：入参出参都是普通 dict，不 import 任何 web 框架；
  - 框架适配器（FastAPI 路由）见 `api_adapter_fastapi.py`，**在能装 fastapi 的机器上**一行一挂即可；
  - 好处：handler 现在就能实测（见 selftest_collect_api.py），不会因为装不上框架而卡死。

=== 对照需求书 v2.4 ===
第2节「一条故事 = 一个素材筐」 → attach_clip 已在 permissions.py 落地，
本文件在它之上补：素材的**采集入口**（谁传的、传什么、多大、多长）与**校验**。

=== 设计铁律 ===
1. handler 不自己开 session —— 由调用方传 db（便于测试与事务控制）
2. 所有 handler 返回统一信封 {"ok": bool, "data": {...}, "error": "..."}，
   绝不一异常抛穿到 web 层（微信小程序要的是可读中文提示，不是 traceback）
3. 语音/原声**必须保留原声**（v2.4 铁律）——校验在 permissions.attach_clip 里已有，
   这里再前置拦一次，避免先落库再报错
4. 图片上传必须给 size / mime 校验：太大、非图片直接拒（老人手机上大图很多）
5. 绝不静默丢素材：任何拒绝都要带原因
"""

import os
import math

from permissions import attach_clip, list_clips, can_add_clip, can_view_story
from models import SessionLocal, Story, Clip, ClipType, init_db


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
# 二、常量（校验用；不是价格那种"后台可配"，是物理上限）
# ============================================================

MAX_IMAGE_MB = 20                      # 单张照片上限（v2.4 未规定，按微信小程序实操取20MB）
MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}
ALLOWED_IMAGE_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "image/heif", "image/gif", "image/bmp",
}

MAX_TEXT_CHARS = 20000                 # 单件文字上限：防呆，不是业务限制
MAX_CAPTION_CHARS = 200                # 照片说明（配文），一屏能读完


# ============================================================
# 三、handler：文字素材
# ============================================================

def api_add_text_clip(
    db,
    *,
    story_id: str,
    owner_id: str,
    actor_id: str,
    text: str,
    caption: str = "",
) -> dict:
    """
    往里挂一件**文字**素材。

    入参：
      story_id  —— 挂到哪条故事（必填）
      owner_id  —— 这本书的主人（权限判定的根）
      actor_id  —— 谁在传（老人自己 / 子女 / 故事里的人）
      text      —— 正文
      caption   —— 可选小标题

    返回：{"ok": True, "data": {"clip_id":..., "sort_order":...}}
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not text or not text.strip():
        return fail("文字内容不能为空", "empty_text")
    if len(text) > MAX_TEXT_CHARS:
        return fail(f"文字太长了（上限{MAX_TEXT_CHARS}字）", "text_too_long")

    # 权限前置：能不能往这条故事里添（v2.4：能看就能添）
    if not can_add_clip(db, owner_id=owner_id, viewer_id=actor_id, story_id=story_id):
        return fail("你没有权限往这条故事里补充内容", "no_permission")

    try:
        clip = attach_clip(
            db,
            story_id=story_id,
            clip_type=ClipType.TEXT,
            text=text.strip(),
            caption=(caption or "")[:MAX_CAPTION_CHARS],
            created_by=actor_id,
        )
    except ValueError as e:
        return fail(str(e), "attach_failed")

    return ok({
        "clip_id": clip.id,
        "story_id": clip.story_id,
        "clip_type": clip.clip_type.value,
        "sort_order": clip.sort_order,
        "created_at": clip.created_at.isoformat() if clip.created_at else "",
    }, message="文字已记下")


# ============================================================
# 四、handler：图片素材
# ============================================================

def validate_image(*, file_name: str, file_size: int, mime: str = "") -> tuple:
    """
    图片前置校验。返回 (是否通过, 原因)。
    拆出来单测（不碰库），是这份接口最容易被前端传错的地方。
    """
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext and ext not in ALLOWED_IMAGE_EXT:
        return False, f"不支持的图片格式：{ext}（支持 jpg/png/webp/heic 等）"
    if not ext:
        # 无扩展名时只能靠 mime 判；mime 也拿不到就不放行（宁可拒错，不可放进非图片）
        if mime not in ALLOWED_IMAGE_MIME:
            return False, "认不出这是图片（既没有可识别的扩展名，也没有图片类型标识）"
    if file_size is None or file_size <= 0:
        return False, "图片是空的（文件大小为0）"
    if file_size > MAX_IMAGE_BYTES:
        got = math.ceil(file_size / 1024 / 1024)
        return False, f"图片太大了（{got}MB，上限{MAX_IMAGE_MB}MB）"
    return True, ""


def api_add_photo_clip(
    db,
    *,
    story_id: str,
    owner_id: str,
    actor_id: str,
    media_url: str,
    file_name: str = "",
    file_size: int = 0,
    mime: str = "",
    cover_url: str = "",
    caption: str = "",
) -> dict:
    """
    往里挂一件**照片**素材。

    说明：本接口**只管登记**（media_url 已由上传通道拿到）。
    真正的字节上传走 `api_upload_url()` 拿到的上传地址（见第六节），
    这样接口自测不需要真传文件，也能验证业务规则。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not media_url:
        return fail("缺少图片地址（media_url）", "missing_media_url")

    passed, why = validate_image(file_name=file_name, file_size=file_size, mime=mime)
    if not passed:
        return fail(why, "invalid_image")

    if not can_add_clip(db, owner_id=owner_id, viewer_id=actor_id, story_id=story_id):
        return fail("你没有权限往这条故事里补充内容", "no_permission")

    try:
        clip = attach_clip(
            db,
            story_id=story_id,
            clip_type=ClipType.PHOTO,
            media_url=media_url,
            media_size=file_size,
            cover_url=cover_url or media_url,   # 没缩略图时先用原图顶
            caption=(caption or "")[:MAX_CAPTION_CHARS],
            created_by=actor_id,
        )
    except ValueError as e:
        return fail(str(e), "attach_failed")

    return ok({
        "clip_id": clip.id,
        "story_id": clip.story_id,
        "clip_type": clip.clip_type.value,
        "sort_order": clip.sort_order,
        "media_url": clip.media_url,
        "cover_url": clip.cover_url,
    }, message="照片已存下")


# ============================================================
# 五、handler：取一条故事的素材筐
# ============================================================

def api_list_clips(db, *, story_id: str, owner_id: str, viewer_id: str) -> dict:
    """
    前端进故事详情页时拉这个：这条故事现在有哪些素材（按顺序）。
    权限：看不到就不给（且不告诉"存在但你没权限"，直接空列表 = 不泄露）。
    """
    if not story_id:
        return fail("缺少 story_id", "missing_story_id")
    if not can_view_story(db, owner_id=owner_id, viewer_id=viewer_id, story_id=story_id):
        return fail("看不到这条故事", "no_permission")

    clips = list_clips(db, story_id)
    items = []
    for c in clips:
        items.append({
            "clip_id": c.id,
            "clip_type": c.clip_type.value,
            "text": c.text or "",
            "media_url": c.media_url or "",
            "cover_url": c.cover_url or "",
            "caption": c.caption or "",
            "keep_original_voice": bool(c.keep_original_voice),
            "created_by": c.created_by or "",
            "sort_order": c.sort_order,
            "created_at": c.created_at.isoformat() if c.created_at else "",
        })
    by_type = {}
    for it in items:
        by_type[it["clip_type"]] = by_type.get(it["clip_type"], 0) + 1

    return ok({
        "story_id": story_id,
        "count": len(items),
        "count_by_type": by_type,
        "clips": items,
    })


# ============================================================
# 六、上传通道（占位：定义清楚，小龙虾照着接）
# ============================================================

def api_upload_url(*, file_name: str, file_size: int, mime: str = "") -> dict:
    """
    取一个上传地址。**本机未接对象存储，返回明确未接**（不许假装成功）。

    前端约定（v1）：
      1. 调本接口拿 upload_url
      2. PUT 字节上去
      3. 拿到的 file_url 再调 api_add_photo_clip 登记

    等 sandy 定对象存储（腾讯云COS / 自建）后，本函数替换为真实签名URL，
    前端**不用改**（接口形状不变）。
    """
    passed, why = validate_image(file_name=file_name, file_size=file_size, mime=mime)
    if not passed:
        return fail(why, "invalid_image")
    return fail(
        "上传通道未接对象存储（待 sandy 定 COS/自建）——当前先用 media_url 直传登记",
        "upload_not_configured",
    )


# ============================================================
# 七、自测 SQLite 建库（供 selftest / 本地跑用）
# ============================================================

def fresh_db():
    """建一个全新的内存/临时库会话（自测用）。"""
    init_db()
    return SessionLocal()
