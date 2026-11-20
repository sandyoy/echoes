"""
card_render_v2.py —— 「做成一张图」= 家书卡（sandy 2026-11-20 定形态）
====================================================================
什么时候用：用户在小程序里点「做成一张图 / 把这件事做成一张图」。
产出物是什么：一张竖版 1080x1440 的图 —— **一段话 + 一张照片 + 一个年份**，
             能直接发家族群、能打印贴墙。不是插图、不是画、不是把整本书压成一张。

形态是 sandy 拍定的（2026-11-20 原型图确认）：
    上：家书 · 年份
    中：照片位（有照片贴照片，没照片留白框）
    下：标题 + 一段话
    底：落款「讲给孩子们听」

★ 权限逻辑（sandy 2026-11-20 拍板，覆盖此前 card_render.py 的老规矩）：
    **做图这件事本身就是用户的意愿声明** —— 他愿意做，就说明他愿意给人看。
    做好之后发不发是他在微信里自己点的，系统不该在生成前再让他勾一遍。
    所以：本文件**不再因为"素材是私有"就拒绝出图**。
    `visibility=private` 这个字段保留，但只在真正的场景用（如子女代填、涉及别人私事），
    形态是「这段不给别人看」默认关闭 —— 默认都能看，用户主动排除。
    老逻辑"全私有 → PermissionError → 页面空白一行红字"是**欠妥的**：
    用户从没在界面上见过这个开关，等于系统拿一个只有它自己知道的状态判他不能做。

★ 内容清洗（出图前必做，否则会把用户的吐槽印到图上）：
    1) 剥掉 ASR/界面残留（"回去看吐了截图"这类非口述内容）；
    2) 剥掉用户对产品的不满/吐槽（"你怎么还是总是问我呢"）——
       那是他在测试，不是在讲自己的故事；
    3) 剥掉纯寒暄/纯问答碎片（"我想问一个问题"、"1939年。"这种回声）；
    4) 长口述去口语水词，但**一个字都不改写内容**。
    清洗后一句可用的话都没有 → 抛 NeedMoreContent（前端明说原因，页面不许空白）。
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ---- 家书卡配色（和 sandy 确认过的原型一致）----
PAPER = (250, 246, 238)       # 米黄信纸底
EDGE = (220, 208, 188)        # 信纸细边
INK = (48, 42, 36)            # 墨色正文
INK_LIGHT = (120, 108, 94)    # 次要字
GOLD = (176, 141, 87)         # 落款/年份的金

W, H = 1080, 1440             # 3:4：微信发出去不变形，打印 A4 也够
MARGIN = 80

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
_FONT_CACHE: dict = {}


class NeedMoreContent(Exception):
    """内容还不够做图（给前端一句人话，页面不许空白）。"""


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                _FONT_CACHE[size] = ImageFont.truetype(p, size)
                return _FONT_CACHE[size]
            except Exception:
                continue
    raise RuntimeError("card_render_v2: 本机找不到中文字体")


# ============================================================
# 一、内容清洗（出图前必过；治「把吐槽和截图名印到图上」）
# ============================================================

# 明显不是口述内容的东西：界面操作残留、ASR 噪声
_NOT_NARRATIVE = (
    "回去看吐了截图", "截图", "点了", "返回", "刷新一下", "重新进",
)

# 用户对产品的不满/测试吐槽 —— 他是在挑毛病，不是在讲自己的事
_COMPLAINT = (
    "你怎么还是", "总是问我", "你是不是应该听", "我问一下", "我想问一个问题",
    "这是什么意思", "怎么又是", "别再问", "不要问",
)


def _is_noise(sentence: str) -> bool:
    s = sentence.strip()
    if not s:
        return True
    for k in _NOT_NARRATIVE:
        if k in s:
            return True
    for k in _COMPLAINT:
        if k in s:
            return True
    # 纯回声：只有年份/只有重复两三个字
    if re.fullmatch(r"\d{4}\s*年?。?", s):
        return True
    if len(re.sub(r"[\s，。！？、；：,.]", "", s)) <= 2:
        return True
    return False


def clean_sentences(raw: str) -> List[str]:
    """把一段口述切成句子，去掉噪声与吐槽。**不改写任何一个字**。"""
    text = (raw or "").replace("\r", "")
    # 分行当句子边界 + 句读切
    chunks: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[。！？])", line)
        for p in parts:
            p = p.strip()
            if p:
                chunks.append(p)
    out = [c for c in chunks if not _is_noise(c)]
    return out


def build_card_text(raw: str, *, max_chars: int = 330) -> Tuple[str, str]:
    """返回 (标题, 正文)。

    ★ 2026-11-20（sandy 拍定）：正文**不是转写原文**，而是整理过的自述。
       "所以的话。，我就现在做了几件事情啊" 这种实录印在卡上，老人念着尴尬。
       整理走 narrative_polish（只整理不编造；整理不出退回原文句子）。
    """
    sentences = clean_sentences(raw)
    if not sentences:
        raise NeedMoreContent(
            "这段话里还没有能印出来的内容（可能是语音没转好，或者只有聊天没讲到事）。"
            "回去再补一两句，或者点「我说什么」重新说一遍。"
        )

    used_raw = "".join(sentences)
    body = ""
    try:
        import narrative_polish
        paras = narrative_polish.polish(used_raw)
        body = narrative_polish.join_for_card(paras, max_chars=max_chars)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("自述整理失败，退回原文", exc_info=True)

    if not body:
        # 降级：原文句子拼起来（至少保证不空手）
        parts, used = [], 0
        for s in sentences:
            if used + len(s) > max_chars and parts:
                break
            parts.append(s)
            used += len(s)
        body = "".join(parts)

    # 标题：★ 统一交模型起（规则只做兜底），起不出就留空让界面引导起名
    title = ""
    try:
        import collect_av
        title = collect_av._ai_title(body) or ""
        if not title:
            cand = collect_av._make_title(body)
            # 规则兜底也要求"像一句话"：太短/带残句尾巴的一律不要
            if cand and len(cand) >= 6 and not cand.endswith(("一就", "就是", "因为", "的")):
                title = cand
    except Exception:
        title = ""
    return title, body


# ============================================================
# 二、画图
# ============================================================

def _draw_center(d, y, text, f, fill, width=W):
    box = d.textbbox((0, 0), text, font=f)
    x = (width - (box[2] - box[0])) / 2 - box[0]
    d.text((x, y), text, font=f, fill=fill)
    return y + (box[3] - box[1])


def _wrap_px(d, text, f, max_w):
    """按像素换行（中文逐字断）。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if d.textlength(cur + ch, font=f) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def render_family_letter(
    *,
    year_label: str = "",
    title: str = "",
    body: str = "",
    photo_path: str = "",
    signature: str = "—— 讲给孩子们听",
) -> bytes:
    """画一张家书卡，返回 PNG 字节。

    参数全部是**已清洗过**的内容；本函数只管画，不判权限、不编造。
    """
    from io import BytesIO

    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)

    # 信纸细边
    d.rectangle([28, 28, W - 28, H - 28], outline=EDGE, width=2)

    y = MARGIN + 6
    y = _draw_center(d, y, "家　书", _font(40), GOLD) + 24
    if year_label:
        y = _draw_center(d, y, year_label, _font(50), INK) + 26

    # ---- 照片位 ----
    ph_top = y
    ph_h_max = 440
    inner_w = W - MARGIN * 2 - 40
    placed_photo = False
    if photo_path and os.path.exists(photo_path):
        try:
            p = Image.open(photo_path).convert("RGB")
            ratio = inner_w / p.width
            p = p.resize((inner_w, max(1, int(p.height * ratio))), Image.LANCZOS)
            if p.height > ph_h_max:
                # 居中裁，不压缩变形
                top = (p.height - ph_h_max) // 2
                p = p.crop((0, top, inner_w, top + ph_h_max))
            im.paste(p, ((W - p.width) // 2, y))
            y += p.height + 38
            placed_photo = True
        except Exception:
            placed_photo = False

    if not placed_photo:
        d.rectangle([MARGIN, y, W - MARGIN, y + ph_h_max], outline=EDGE, width=2)
        hint = "（这里放一张那时的照片）"
        box = d.textbbox((0, 0), hint, font=_font(30))
        d.text(((W - (box[2] - box[0])) / 2 - box[0], y + ph_h_max / 2 - 22),
               hint, font=_font(30), fill=INK_LIGHT)
        y += ph_h_max + 38

    # ---- 标题 ----
    if title:
        f_title = _font(46)
        for line in _wrap_px(d, title, f_title, W - MARGIN * 2):
            y = _draw_center(d, y, line, f_title, INK) + 16
        y += 14

    # ---- 正文（居中，像信纸上的手写）----
    f_body = _font(34)
    for line in _wrap_px(d, body, f_body, W - MARGIN * 2):
        if y > H - MARGIN - 120:
            break
        y = _draw_center(d, y, line, f_body, INK) + 14

    # ---- 落款（永远贴底，不随内容浮动）----
    _draw_center(d, H - MARGIN - 46, signature, _font(28), INK_LIGHT)

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ============================================================
# 三、给接口层用的高层入口（前端只调这个）
# ============================================================

def _title_looks_complete(t: str) -> bool:
    """库里的标题能不能直接印：不能是"话说到一半"的残句。

    残句的典型长相（全是从真实数据里捡出来的）：
      "我出生在1973年，我有一个"   ← 逗号后面没下文
      "我爸是一就"                 ← 明显转写错误，句子没完
      "我是1939年出生。"            ← 带句号的一句话，不长
      "我想问一个问题"              ← 老人反问助手的话，不是标题
    判据：不短于 4 字、不以"我有一个/是一就/因为/就是/但是"这类未完的词收尾、
          不含问号（问句是老人的追问，不是这段的标题）。
    """
    t = (t or "").strip(" ，。、；：")
    if len(t) < 4:
        return False
    if "？" in t or "?" in t:
        return False
    if t.endswith(("我有一个", "一个", "一就", "就是", "因为", "但是", "而且",
                   "所以", "然后", "还有", "一下", "并且", "于是", "的话")):
        return False
    # 逗号收尾 = 话没说完
    if (t or "").endswith(("，", ",")):
        return False
    return True


def render_story_card(db, *, story_id: str) -> bytes:
    """一条故事 → 家书卡。要求：有可用内容。**不再要求"公开素材"。**"""
    from models import Story
    import share_api as S

    s = db.get(Story, story_id)
    if s is None:
        raise ValueError("这段故事不存在")

    raw = (getattr(s, "raw_content", "") or "").strip()
    title, body = build_card_text(raw)

    # ★ 2026-11-20：库里的标题**只有在"像一句话"时才用**。
    #   老数据里存着一堆残句（"我出生在1973年，我有一个" / "我爸是一就"），
    #   以前无脑优先用库里的，结果卡上印的就是残句。现在反过来：
    #   库里有像样的标题 → 用；像残句 → 让 build_card_text 现起的顶上。
    db_title = (getattr(s, "title", "") or "").strip()
    if db_title and _title_looks_complete(db_title):
        title = db_title

    photo_path = _first_photo_path(db, story_id=story_id)
    return render_family_letter(
        year_label=(getattr(s, "time_label", "") or ""),
        title=title,
        body=body,
        photo_path=photo_path,
    )


def render_book_card(db, *, owner_id: str) -> bytes:
    """整本书 → 家书卡（多段拼一张，用于"这本书整体做个封面卡"）。"""
    from models import Story
    from sqlalchemy import select

    stories = list(db.scalars(select(Story).where(Story.owner_id == owner_id)
                              .order_by(Story.created_at)))
    texts = []
    year_label = ""
    photo_path = ""
    for s in stories:
        if not year_label and getattr(s, "time_label", ""):
            year_label = s.time_label
        if not photo_path:
            photo_path = _first_photo_path(db, story_id=s.id)
        try:
            _t, b = build_card_text(getattr(s, "raw_content", "") or "")
            texts.append(b)
        except NeedMoreContent:
            continue
    if not texts:
        raise NeedMoreContent(
            "这本书还没有能印出来的内容。先讲一两段，再来做这张图。"
        )
    body = "".join(texts)[:300]
    title = ""
    for s in stories:
        if (getattr(s, "title", "") or "").strip():
            title = s.title.strip()
            break
    return render_family_letter(
        year_label=year_label, title=title, body=body, photo_path=photo_path,
    )


def _first_photo_path(db, *, story_id: str) -> str:
    """这条故事里第一张**能当老照片用**的图（供贴图用）；没有就空串。

    ★ 2026-11-20：加了截图过滤。以前是"见到照片就贴"，结果把用户随手截的
      淘宝商品图贴到家书卡正中间。截图不是错，但不适合当"那时的照片"。
      全是截图 → 返回空串，卡上走留白框（不硬贴、不假装有老照片）。
    """
    from sqlalchemy import select
    from models import Clip, ClipType
    import photo_gate

    rows = db.scalars(select(Clip).where(Clip.story_id == story_id)
                      .where(Clip.clip_type == ClipType.PHOTO)
                      .order_by(Clip.sort_order)).all()
    media_root = os.environ.get("ECHOES_MEDIA_ROOT", "/home/ubuntu/.echoes_media")
    for c in rows:
        url = (c.media_url or "").strip()
        if not url:
            continue
        rel = url.lstrip("/")
        if rel.startswith("media/"):
            rel = rel[len("media/"):]
        cand = os.path.join(media_root, rel)
        if not os.path.exists(cand):
            # 库里存的是无扩展名（_tmp_xxx），磁盘上是 .jpg —— 按前缀找
            folder = os.path.dirname(cand)
            stem = os.path.basename(cand)
            cand = ""
            if os.path.isdir(folder) and stem:
                for fn in sorted(os.listdir(folder)):
                    if fn.startswith(stem[:24]) and not fn.startswith("."):
                        cand = os.path.join(folder, fn)
                        break
        if not cand:
            continue
        try:
            bad, _why = photo_gate.looks_like_screenshot(cand)
        except Exception:
            bad = False
        if bad:
            continue
        return cand
    return ""
