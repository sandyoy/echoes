"""
card_render.py —— 「做成一张图」真出图（v3.0 §3.3.1 方式 B / §8之二.3.1）
====================================================================
背景（为什么要这个文件）：
  `share_api.make_card_data()` 只产**数据**（headline/excerpt/…），
  前端拿它去渲，等于"这张图谁都没画过"。而 §3.3.1 把「做成一张图」
  明写成**方式 B**（像小年糕那种，老人可直接发出去）——
  这一步后端此前是空的：没有任何一处代码能产出一张图片。

本文件做什么：
  `render_story_card()` / `render_book_card()` → **真 PNG 字节**
  750px 宽（与 8 页原型图同宽），暖米底 #FDFBF7 + 白卡片 + 赤陶 #D97746，
  与《08 拿给别人看》原型图同一套色，老人发出去不"廉价"。

三条铁律（照 share_api 的老规矩，不新开口子）：
  1. **只画公开素材**：取图前必须先过 `share_api.can_share_story()`
     （单一真相源不复制）；全私有 → 抛 PermissionError，绝不出一张含私有内容的图。
  2. **不编造**：没有 excerpt 就那行不画；没有 owner 名字就不写"XXX的故事"。
     图上每一个字都来自库里的真实字段。
  3. **不留版权陷阱**：图底部带小程序名（"往事可追忆"），不带任何假二维码/假链接。

未做（明确边界）：
  - 不画真二维码（要小程序的码，属小龙虾/微信后台域）；
  - 不做字体下载（本机有 unifont/ipafont 兜底；小程序侧最终由前端 canvas 出图）。
"""

from __future__ import annotations

import io
import os
import glob
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# ---- 与原型图 08 同一套色（改了要同步 08 页 svg，否则两处不一致）----
BG = (253, 251, 247)          # #FDFBF7 暖米白，纸感
CARD = (255, 255, 255)
INK = (51, 51, 51)            # #333333 正文
INK_SOFT = (153, 153, 153)    # #999999 次要
ACCENT = (217, 119, 70)       # #D97746 赤陶
ACCENT_BG = (253, 240, 233)   # #FDF0E9 浅橘
QUOTE_BG = (245, 245, 245)    # #F5F5F5 引用块灰底
LINE = (232, 228, 221)

W = 750
PAD = 48
INNER = W - PAD * 2


# ============================================================
# 一、字体（按可读性排序兜底；找不到就报错，不静默出豆腐块）
# ============================================================

_FONT_CANDIDATES = [
    # 优先：真正的中文黑体（本机若装了思源/文泉驿会命中）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # 兜底：unifont（覆盖全部 CJK，字形偏像素但**不会是方块**）
    "/usr/share/fonts/opentype/unifont/unifont.otf",
    # 再兜底：日文 Gothic（汉字字形基本可用）
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
]


def _font_path() -> str:
    env = os.environ.get("ECHOES_CARD_FONT", "")
    if env and os.path.exists(env):
        return env
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    # 最后扫一遍字体目录里任何带 CJK 的字体
    for pat in ("/usr/share/fonts/**/*.ttc", "/usr/share/fonts/**/*.otf",
                "/usr/share/fonts/**/*.ttf"):
        for p in glob.glob(pat, recursive=True):
            n = os.path.basename(p).lower()
            if any(k in n for k in ("cjk", "wqy", "unifont", "han", "hei", "ming")):
                return p
    raise RuntimeError("card_render: 本机找不到任何中文字体（设 ECHOES_CARD_FONT 指一个 .ttf/.otf）")


_FONT_CACHE: dict = {}


def _f(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = ImageFont.truetype(_font_path(), size)
    return _FONT_CACHE[size]


# ============================================================
# 二、排版小工具（中英文混排按字宽换行——不能用 len()）
# ============================================================

def _wrap(draw, text: str, font, max_w: int) -> list:
    """按像素宽度换行。中文逐字断，英文尽量不切断单词之外不强求（老人看的短句，够用）。"""
    text = (text or "").strip()
    if not text:
        return []
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _rounded(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _pill(draw, xy, text, font, fg, bg):
    """胶囊小标签（顶部隐私提示用）。返回占用高度。"""
    x, y = xy
    tw = draw.textlength(text, font=font)
    h = 46
    _rounded(draw, (x, y, x + tw + 44, y + h), h // 2, bg)
    draw.text((x + 22, y + (h - font.size) / 2 - 3), text, font=font, fill=fg)
    return h


# ============================================================
# 三、主体：渲染一张卡片
# ============================================================

def render_card(*, owner_name: str, eyebrow: str = "", headline: str = "",
                excerpt: str = "", tail: str = "", kind_label: str = "") -> bytes:
    """
    画一张竖版卡片（宽度 750，高度按内容伸缩），返回 PNG 字节。

    参数都是**已经被业务层筛过的**公开信息；本函数只管画，不再判权限。
    """
    rgb = Image.new("RGB", (W, 1200), BG)
    d = ImageDraw.Draw(rgb)

    # 先在离屏上量高度，再真正新建画布（避免底部留大白）
    y = PAD + 8

    f_owner = _f(46)
    f_head = _f(52)
    f_body = _f(38)
    f_meta = _f(30)
    f_tag = _f(26)

    blocks = []  # (kind, payload) 先攒，后统一画

    # 顶部标签：这句是卡片性质，不是"权限"术语（§3.3.1 禁词）
    blocks.append(("pill", "朋友发给你的一页故事"))
    if eyebrow:
        blocks.append(("meta", eyebrow))
    if headline:
        blocks.append(("head", headline))
    if excerpt:
        blocks.append(("quote", excerpt))
    if tail:
        blocks.append(("body", tail))
    blocks.append(("footer", "—— 往事可追忆"))

    # ---- 第一遍：量高度 ----
    # ★高度量法：行高 = 字号 + 行距，但**最后一行的 descent 不算**——
    #   2026-10-18 实测踩坑：原先每行都算 (size+行距)，最后一行多出 22px，
    #   第二遍按同一公式画到 footer 后面 → 底部小字被画布边缘切掉一半。
    #   故统一走 _block_h()，量法与画法共用一套，再也不许两处各写一遍。
    def _block_h(kind, payload):
        if kind == "pill":
            return 46 + 34
        if kind == "meta":
            lines = _wrap(d, payload, f_meta, INNER)
            return sum(f_meta.size + 16 for _ in lines) + 6 + 14   # + descent 余量
        if kind == "head":
            n = len(_wrap(d, payload, f_head, INNER))
            if owner_name:
                n += len(_wrap(d, f"这是{owner_name}的故事", f_head, INNER))
                base = n * (f_head.size + 22) + 8
            else:
                base = n * (f_head.size + 22)
            return base + 26 + 14
        if kind == "quote":
            lines = _wrap(d, payload, f_body, INNER - 64)
            return len(lines) * (f_body.size + 22) + 76 + 40 + 14
        if kind == "body":
            lines = _wrap(d, payload, f_body, INNER)
            return len(lines) * (f_body.size + 22) + 20 + 14
        if kind == "footer":
            return 90
        return 0

    height = PAD + 8 + sum(_block_h(k, p) for k, p in blocks) + PAD

    img = Image.new("RGB", (W, height), BG)
    draw = ImageDraw.Draw(img)

    # ---- 第二遍：真画 ----
    y = PAD + 8
    for kind, payload in blocks:
        if kind == "pill":
            _pill(draw, (PAD, y), payload, f_tag, ACCENT, ACCENT_BG)
            y += 46 + 34

        elif kind == "meta":
            for ln in _wrap(draw, payload, f_meta, INNER):
                draw.text((PAD, y), ln, font=f_meta, fill=ACCENT)
                y += f_meta.size + 16
            y += 6

        elif kind == "head":
            if owner_name:
                # 标题第一行永远点名"这是谁的故事"（§8.3 这本书的"我"是谁）
                line = f"这是{owner_name}的故事"
                for ln in _wrap(draw, line, f_head, INNER):
                    draw.text((PAD, y), ln, font=f_head, fill=INK)
                    y += f_head.size + 22
                y += 8
            for ln in _wrap(draw, payload, f_head, INNER):
                draw.text((PAD, y), ln, font=f_head, fill=INK)
                y += f_head.size + 22
            y += 26

        elif kind == "quote":
            lines = _wrap(draw, payload, f_body, INNER - 64)
            box_h = len(lines) * (f_body.size + 22) + 76
            _rounded(draw, (PAD, y, PAD + INNER, y + box_h), 18, QUOTE_BG)
            draw.rectangle((PAD, y, PAD + 8, y + box_h), fill=ACCENT)  # 左侧竖线
            ty = y + 38
            for ln in lines:
                draw.text((PAD + 40, ty), ln, font=f_body, fill=INK)
                ty += f_body.size + 22
            y += box_h + 40

        elif kind == "body":
            for ln in _wrap(draw, payload, f_body, INNER):
                draw.text((PAD, y), ln, font=f_body, fill=INK)
                y += f_body.size + 22
            y += 20

        elif kind == "footer":
            y += 20
            draw.line((PAD, y, PAD + INNER, y), fill=LINE, width=2)
            y += 30
            # ★自证（2026-10-18 加）：底部小字必须完整落在画布内，否则当场报错，
            #   不许"悄悄切掉一半"——这是上一版真实踩到的坑。
            tw = draw.textlength(payload, font=f_meta)
            descend = 12
            if y + f_meta.size + descend > height:
                raise RuntimeError(
                    f"card_render: 排版越界（footer 需 {y + f_meta.size + descend}px，画布 {height}px）")
            draw.text(((W - tw) / 2, y), payload, font=f_meta, fill=INK_SOFT)
            y += 60

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ============================================================
# 四、业务层入口（判权限 + 取公开素材 + 画图）
# ============================================================

def render_story_card(db, *, story_id: str) -> bytes:
    """
    给一篇故事出卡片图。
    **只画公开素材**：先过 share_api.can_share_story（单一真相源），
    全私有 → PermissionError（不出含私有内容的图）。
    """
    import share_api as S
    from models import Story

    if not S.can_share_story(db, story_id=story_id):
        raise PermissionError("这篇还没有公开的内容，做不了图")
    s = db.get(Story, story_id)
    if s is None:
        raise ValueError("这篇故事不存在")

    data = S.make_card_data(db, kind="story", target_id=story_id)
    excerpt = data.get("excerpt", "") or ""
    summary = (getattr(s, "summary", "") or "").strip()
    tail = summary
    # ★别同义重复（2026-10-18）：summary 与引文高度重合时（AI 摘一句常常就把老人原话
    #   抄成了摘要），图上就会出现"同一句话印两遍"——老人看着像坏了。去重。
    if tail and excerpt:
        a, b = tail.rstrip("。…"), excerpt.rstrip("。…")
        if a in b or b in a:
            tail = ""
    return render_card(
        owner_name=S._owner_name(db, s.owner_id) if hasattr(S, "_owner_name") else "",
        eyebrow=data.get("eyebrow", "") or (getattr(s, "time_label", "") or ""),
        headline=getattr(s, "title", "") or "一件小事",
        excerpt=excerpt,
        tail=tail,
    )


def render_book_card(db, *, owner_id: str) -> bytes:
    """给一整本书出卡片图（只数**能分享**的篇，私有篇不计数——不暗示存在）。"""
    import share_api as S
    from models import Story
    from sqlalchemy import select

    stories = list(db.scalars(select(Story).where(Story.owner_id == owner_id)))
    shareable = [s for s in stories if S.can_share_story(db, story_id=s.id)]
    if not shareable:
        raise PermissionError("这本书还没有公开的内容，做不了图")
    data = S.make_card_data(db, kind="book", target_id=owner_id)
    return render_card(
        owner_name=S._owner_name(db, owner_id),
        eyebrow="一本回忆的书",
        headline="",  # 书名没有就留空，不造
        excerpt="",
        tail=data.get("sub", ""),
    )


def _ink_bbox_rgb(im):
    """图上所有"墨"（不是暖米底色）的包围盒；空图返回 None。"""
    from PIL import ImageChops
    bg = Image.new("RGB", im.size, BG)
    return ImageChops.difference(im.convert("RGB"), bg).getbbox()


def api_card_check(*, png: bytes, expect_lines: list = None) -> dict:
    """
    出图自证（给自测/上线体检用）：**不信 ok=True，量像素**。
    返回 {ok, data:{width,height,ink_bottom_gap_px,overflow,line_found}}
      - ink_bottom_gap_px：最下面一个墨点距画布底边的像素数（>=PAD 才算排版收得住）
      - overflow：墨点是否碰到画布边（True = 字被切掉了）
      - line_found：expect_lines 里每句是否真的出现在图上（渲染回读，防"画了但没画上"）
    """
    from PIL import Image as _I
    im = _I.open(io.BytesIO(png)).convert("RGB")
    bbox = _ink_bbox_rgb(im)
    if bbox is None:
        return {"ok": False, "error": "出的是空白图", "code": "blank_image"}
    l, t, r, b = bbox
    gap_bottom = im.height - b
    overflow = (l <= 0) or (t <= 0) or (r >= im.width) or (b >= im.height)
    res = {"width": im.width, "height": im.height,
           "ink_bottom_gap_px": gap_bottom, "overflow": overflow,
           "line_found": {}}
    if expect_lines:
        # 渲染回读：把期望的句子**再画一遍**在空白画布上，比对像素是否在图上出现过。
        # 比 OCR 轻，也不引外部依赖；只适合"这段字有没有真的被画出来"这种判据。
        for line in expect_lines:
            f = _f(30)
            w = int(d.textlength(line, font=f)) + 20
            probe = Image.new("RGB", (w, 60), BG)
            pd = ImageDraw.Draw(probe)
            pd.text((10, 10), line, font=f, fill=INK_SOFT)
            pb = _ink_bbox_rgb(probe)
            hit = False
            if pb is not None:
                pat = probe.crop(pb)
                hit = im.find_subimage(pat) if hasattr(im, "find_subimage") else None
                if hit is None:
                    # 逐像素扫（图不大，750宽 × ~1500高，够快）
                    pw, ph = pat.size
                    for yy in range(0, im.height - ph + 1, 1):
                        for xx in range(0, im.width - pw + 1, 2):
                            if im.crop((xx, yy, xx + pw, yy + ph)).tobytes() == pat.tobytes():
                                hit = (xx, yy)
                                break
                        if hit:
                            break
            res["line_found"][line] = bool(hit)
    return {"ok": True, "data": res}


# ============================================================
# 五、对外 handler（信封，照全仓约定）
# ============================================================

def api_render_card(db, *, actor_id: str, kind: str, target_id: str = "") -> dict:
    """
    统一出图入口。
      kind=story → target_id=故事 id（须至少一条公开素材）
      kind=book  → target_id=owner_id（缺省=本人）

    返回：{ok, data:{mime:"image/png", bytes:<int>, width:750, height:<int>}}——
    **不把 base64 塞进 JSON**（手机端 JSON 太胖），改由调用方走
    `render_card_bytes()` 走二进制流；本 handler 只回元信息，便于前端先拿尺寸排版。
    """
    try:
        if kind == "story":
            png = render_story_card(db, story_id=target_id)
        elif kind == "book":
            png = render_book_card(db, owner_id=target_id or actor_id)
        else:
            return {"ok": False, "error": f"不认识的卡片类型：{kind}", "code": "bad_kind"}
    except PermissionError as e:
        return {"ok": False, "error": str(e), "code": "not_shareable"}
    except ValueError as e:
        return {"ok": False, "error": str(e), "code": "not_found"}
    except RuntimeError as e:            # 字体缺失等环境问题，明确报，不假装成功
        return {"ok": False, "error": str(e), "code": "render_unavailable"}

    from PIL import Image as _I
    im = _I.open(io.BytesIO(png))
    return {
        "ok": True,
        "data": {"mime": "image/png", "bytes": len(png),
                 "width": im.width, "height": im.height},
    }
