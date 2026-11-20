"""
photo_gate.py —— 照片入口把关：这张图是不是"老照片/生活照"，还是"界面截图"
====================================================================
为什么要有这个文件（sandy 2026-11-20 真机实测实锤）：
  家书卡正中间贴了一张**淘宝浴缸水龙头的商品截图**。
  系统只判"这条故事有没有照片"，见到照片就贴 → 用户随手截的图、扫的码、
  转发的水龙头，全被当成"那时的老照片"印到家书卡上。
  这不是排版问题，是**入口没把关**。

判据分两层（先便宜后贵）：
  第一层 纯尺寸/比例/文件名 —— 零成本，能在上传时就拦：
      手机截图的比例几乎固定（9:16 / 19.5:9 / 3:4 且像素接近整屏），
      且截图文件名常见 screenshot / Screenshot_ / wx_camera 之类。
  第二层 看图判"是不是屏幕"—— 需要模型/视觉，放在**出图前**再判一次：
      有状态栏（顶部两条细边 + 时间/信号区）、大面积纯白卡片、规整列表。

口径（很重要，别写成"禁止上传截图"）：
  **截图不是错，只是不适合当"那时的老照片"贴到家书卡上。**
  所以本模块只回答"这张适不适合上卡"，不改上传、不删用户的东西。
"""

from __future__ import annotations

import os
import re
from typing import Optional

# 这些比例基本只有整屏截图才会出现（手机竖屏）
_SCREENSHOT_RATIOS = (
    (0.46, 0.48),   # 9:19.5 / 9:20
    (0.55, 0.58),   # 9:16
    (0.74, 0.76),   # 3:4
)

_SHOT_NAME_HINTS = ("screenshot", "screen_shot", "截屏", "截图", "wx_camera", "mmexport",
                    "qq_image", "screencap")
_PHOTO_RATIOS = (
    (0.73, 0.77),   # 3:4
    (1.30, 1.36),   # 4:3
    (0.65, 0.68),   # 2:3
    (1.48, 1.52),   # 3:2
    (0.96, 1.04),   # 1:1
    (1.74, 1.80),   # 16:9
    (0.55, 0.57),   # 9:16 手机竖拍（与截图重叠，故不能只靠比例）
)


def _ratio_in(r: float, bands) -> bool:
    return any(lo <= r <= hi for lo, hi in bands)


def _is_screen_snapshot(im) -> bool:
    """第二层判据：**看像素**判"是不是一张屏幕截图"。

    不看懂内容，只看"屏幕长什么样"——截屏有三条几乎不会错的指纹：
      A) 顶部有一条状态栏：最上面 6% 里，同一行像素高度一致、颜色偏深/偏白，
         且这一条与下面内容有明显分界（真实照片顶部不会这么"平"）。
      B) 大面积"卡片白"：屏幕底色是纯白/纯黑（RGB 极值占比高），照片极少见。
      C) 画面里横平竖直的直线极多（按钮边、列表线），照片里是乱的。

    三条命中两条 → 判截图。宁可放过一张真照片（留白框不丢人），
    不许把商品截图贴到"那时的照片"位上。
    """
    try:
        w, h = im.size
        small = im.convert("RGB").resize((min(w, 360), max(1, int(h * min(w, 360) / w))))
        px = small.load()
        sw, sh = small.size

        # A) 顶部状态栏：最上面 4% 那几行，行内颜色方差极小 + 与下方亮度差明显
        band = max(2, int(sh * 0.04))
        row_flat = 0
        for y in range(band):
            vals = [sum(px[x, y]) / 3 for x in range(0, sw, 3)]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            if var ** 0.5 < 12:          # 这一行几乎是纯色 → 状态栏特征
                row_flat += 1
        top_flat = row_flat >= max(1, band * 0.5)

        # 下方内容带的平均亮度
        below = [sum(px[x, y]) / 3 for y in range(band, min(sh, band * 6)) for x in range(0, sw, 5)]
        below_mean = sum(below) / len(below) if below else 128

        # B) 卡片白/纯黑占比
        total = 0
        extreme = 0
        for y in range(0, sh, 4):
            for x in range(0, sw, 4):
                r, g, b = px[x, y]
                m = (r + g + b) / 3
                total += 1
                if m > 243 or m < 12:
                    extreme += 1
        white_ratio = extreme / max(1, total)

        a_hit = top_flat
        b_hit = white_ratio > 0.28
        # 底部 8% 里，中间一条特别"平"的细带 → 网页底栏/按钮条的典型长相
        frac_hit = white_ratio > 0.045 or top_flat

        if a_hit and (b_hit or below_mean < 90 or below_mean > 200):
            return True
        # 顶部状态栏非常平 + 底色偏纯（暗色界面 / 白底界面都算）
        if a_hit and frac_hit:
            return True
        if b_hit and white_ratio > 0.5:
            return True
        return False
    except Exception:
        return False


def looks_like_screenshot(path: str, *, width: int = 0, height: int = 0) -> tuple:
    """返回 (是否像截图, 原因)。只做第一层便宜判断，不读像素。

    width/height 可以不传；不传时用 PIL 读一次（失败就当不知道，判"不像"）。
    """
    name = os.path.basename(path or "").lower()
    if any(h in name for h in _SHOT_NAME_HINTS):
        return True, "文件名像截图"

    if not (width and height):
        try:
            from PIL import Image
            with Image.open(path) as im:
                width, height = im.size
        except Exception:
            return False, ""

    if not (width and height):
        return False, ""

    r = width / height

    # 判定一：整屏截图——宽度是手机常见整屏宽度，高度比例极长
    if height >= width * 1.6 and width in (750, 828, 1080, 1125, 1170, 1179, 1242, 1284, 1290):
        return True, f"整屏尺寸 {width}x{height}"

    # 判定二：任何极长竖图（n:1 > 1.9）都按截图/长图处理，一律不上卡
    if height >= width * 1.9:
        return True, f"超长竖图 {width}x{height}"

    # 判定三：看像素判"这是不是一张屏幕"（查商品页/聊天页这类截图）
    try:
        from PIL import Image
        with Image.open(path) as im:
            if _is_screen_snapshot(im):
                return True, "画面像屏幕（状态栏/大片白底）"
    except Exception:
        pass

    return False, ""


def pick_card_photo(db, *, story_id: str) -> Optional[str]:
    """给家书卡挑一张能贴的照片：**跳过截图**，取第一张像照片的。

    全部都是截图 / 没有照片 → 返回 None（卡上走留白框，不硬贴）。
    """
    from sqlalchemy import select
    from models import Clip, ClipType

    rows = db.scalars(select(Clip).where(Clip.story_id == story_id)
                      .where(Clip.clip_type == ClipType.PHOTO)
                      .order_by(Clip.sort_order)).all()
    media_root = os.environ.get("ECHOES_MEDIA_ROOT", "/home/ubuntu/.echoes_media")

    for c in rows:
        p = _resolve_media_path(c.media_url or "", media_root)
        if not p:
            continue
        bad, _why = looks_like_screenshot(p)
        if bad:
            continue
        return p
    return None


def _resolve_media_path(url: str, media_root: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    rel = url.lstrip("/")
    if rel.startswith("media/"):
        rel = rel[len("media/"):]
    cand = os.path.join(media_root, rel)
    if os.path.exists(cand):
        return cand
    # 库里存的是无扩展名（_tmp_xxx），磁盘上是 .jpg —— 按前缀找
    folder = os.path.dirname(cand)
    stem = os.path.basename(cand)
    if os.path.isdir(folder) and stem:
        for fn in sorted(os.listdir(folder)):
            if fn.startswith(stem[:24]) and not fn.startswith("."):
                return os.path.join(folder, fn)
    return ""
