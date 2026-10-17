"""
往事可追忆 - 书的形态与续添接口（handler 层）v1.0
建立：2026-10-13（第3期·晚低峰推进）

=== 为什么有本文件 ===
需求书 v3.0 §8.6 原文：
    「书的形态（三种都要）：书的形式（翻页）/ 手机端阅读 / 翻相册式。
      设计追求：线上看到什么样，印出来就什么样 → 省排版。
      【待验证】完全免排版的可行性边界，技术侧评估。」

此前 `book_api.py` 只做到「生成电子书」——把两筐素材装进一个 chapters 数组就落库，
**没有任何"书的形态"渲染件**：
  - 三种形态（翻页 / 手机端阅读 / 翻相册式）后端一行都没有 → 前端只能自己瞎拼版；
  - §8.4「成书不是终点，是活文档——可继续看、可往里再添内容」——**"续添"没有任何接口**
    （只能删了重生成，等于丢了上一版）；
  - §8.6【待验证】「完全免排版的可行性边界」——没人评过。

本文件补这一跳：**把"内容"（book_api 已产出）转成"三种成书形态"的排版件**，
并补齐 §8.4 的续添，附 §8.6 免排版可行性的技术评估结论。

=== 对照需求书 v3.0（逐条落）===
  §8.6 形态①「书的形式（翻页）」  → render_paged_book()   逐页分栏（每页固定条数/字数）
  §8.6 形态②「手机端阅读」        → render_scroll_book()  连续滚动流（手机竖屏阅读）
  §8.6 形态③「翻相册式」          → render_photobook()    以照片/视频为主，文字做注
  §8.6 「线上看到什么样，印出来就什么样 → 省排版」
                                  → computed_page_size_mm() 直接给印刷开本尺寸（A5），
                                    同一份 paginate() 结果同时喂屏幕和印刷
  §8.6【待验证】免排版可行性边界  → assess_layout_freedom() 给结论（见文件末 §待验证结论）
  §8.4 「可继续看、可往里再添」    → api_append_to_ebook()  续添（不重建、保 ebook_id）
                                     + api_book_view()       取任一种形态

=== 设计铁律 ===
1. handler 不自己开 session，db 由调用方传（与 collect_api / story_api / book_api 同）
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **绝不越权**：只有书主人能续添/取私有形态；引用段（is_quote）永不被续添改动
4. **形态转换是纯函数**：render_* 不改库、不改原文，只从 ebook.content 派生视图
   （同一份 content 可派生三种形态 → 这就是"免排版"的技术基础）
5. 续添**幂等**：同一 story_id 二次续添不重复加章；只在末尾追加新篇 + 更新 generated_at
6. **绝不臆造**：形态里没有的字段不编；空书明确空，不假装有内容
"""

import json

from permissions import _new_id, list_clips, can_view_story
from models import (
    SessionLocal, Story, Clip, Ebook, EbookStatus, Visibility, User, init_db,
)

NO_PERMISSION = "只有这本书的主人能操作它"

# §8.6 印刷开本：A5（148×210mm，最像"一本书"、老人手持舒适）
A5_W_MM, A5_H_MM = 148, 210
# 屏幕阅读页宽（手机竖屏逻辑像素近似），用于"线上看=印着看"的同构排版
SCREEN_W_PX = 750

# §九 未付费时可预览的章数（锁的是"全部/印刷件"，不是把书彻底关死）
PREVIEW_CHAPTERS = 1


# ============================================================
# 一、统一信封（与 book_api / collect_api / story_api 同形）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data, "error": "", "code": ""}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "data": None, "error": msg, "code": code}
    d.update(extra)
    return d


# ============================================================
# 二、内部：把 ebook.content 读成 chapters（只读，不改库）
# ============================================================

def _load_content(eb) -> dict:
    """从 Ebook.content 读回结构化内容；坏 JSON 不抛穿，返回空结构（绝不臆造）。"""
    try:
        return json.loads(eb.content or "{}") or {}
    except Exception:
        return {}


def _iter_entries(content: dict):
    """按章顺序产出 (chapter, entry)。章序 = 生成时按时间排好的顺序，形态转换不得重排。"""
    for ch in content.get("chapters", []) or []:
        for e in ch.get("entries", []) or []:
            yield ch, e


def _is_media_entry(e: dict) -> bool:
    """照片/视频类素材（有 media_url 且 kind 属于图像/视频）。"""
    kind = str(e.get("kind", "") or "").lower()
    return bool(e.get("media_url")) and ("photo" in kind or "video" in kind or "image" in kind)


def _entry_has_image(e: dict) -> bool:
    kind = str(e.get("kind", "") or "").lower()
    return bool(e.get("media_url")) and ("photo" in kind or "image" in kind)


def _clip_text(c) -> str:
    """素材取正文：文字类取 text；语音类取转写；都没有则空（绝不臆造）。"""
    t = (getattr(c, "text", "") or "").strip()
    if t:
        return t
    return (getattr(c, "transcript", "") or "").strip()


# ============================================================
# 三、★核心：分页器（三种形态共用的同一份"页模型"）
#    —— 这是 §8.6「线上看到什么样，印出来就什么样 → 省排版」的技术基础
# ============================================================

def paginate(content: dict, *, lines_per_page: int = 12) -> list:
    """
    把 chapters 线性切成"页"（每页最多 lines_per_page 个条目），**保留章归属和引用标记**。
    屏幕形态和印刷形态**共用这一个结果** → 同一内容不排两遍版。

    返回：[{page_no, chapter_title, time_label, entries:[...]}, ...]
    分页规则简单到可预期（老人不会看到"半句话被切走"——按条目切，不按字切）。
    """
    pages, buf, cur_ch = [], [], None

    def flush():
        nonlocal buf, cur_ch
        if buf:
            pages.append({
                "page_no": len(pages) + 1,
                "chapter_title": (cur_ch or {}).get("story_title", ""),
                "time_label": (cur_ch or {}).get("time_label", ""),
                "entries": buf,
            })
        buf = []

    for ch, e in _iter_entries(content):
        if cur_ch is not None and ch.get("story_id") != cur_ch.get("story_id"):
            flush()
        cur_ch = ch
        buf.append(e)
        if len(buf) >= max(1, lines_per_page):
            flush()
    flush()
    return pages


def computed_page_size_mm(book_spec: str = "A5") -> dict:
    """
    §8.6「印出来就什么样」——直接给出印刷开本尺寸（mm），供前端/印刷厂同一口径。
    不臆造其他开本：只支持 A5（默认）与 A4；未知开本回落 A5 并标注。
    """
    spec = (book_spec or "A5").strip().upper()
    if spec == "A4":
        return {"spec": "A4", "width_mm": 210, "height_mm": 297, "fallback": False}
    return {"spec": "A5", "width_mm": A5_W_MM, "height_mm": A5_H_MM,
            "fallback": spec not in ("A5",)}


# ============================================================
# 四、★核心：三种形态渲染（§8.6 三种都要）
# ============================================================

def render_paged_book(content: dict, *, book_spec: str = "A5") -> dict:
    """形态①「书的形式（翻页）」：逐页分栏，页即印刷页（A5）。"""
    pages = paginate(content)
    for p in pages:
        p["page_size_mm"] = computed_page_size_mm(book_spec)
    quote_pages = sum(1 for p in pages if any(e.get("is_quote") for e in p["entries"]))
    return {
        "form": "paged",                      # 翻页
        "form_label": "书的形式（翻页）",
        "book_spec": computed_page_size_mm(book_spec),
        "page_count": len(pages),
        "quote_page_count": quote_pages,
        "pages": pages,
    }


def render_scroll_book(content: dict) -> dict:
    """形态②「手机端阅读」：连续滚动流（不切页），每条素材一段。"""
    blocks = []
    for ch, e in _iter_entries(content):
        blocks.append({
            "story_id": ch.get("story_id", ""),
            "story_title": ch.get("story_title", ""),
            "time_label": ch.get("time_label", ""),
            "text": e.get("text", ""),
            "media_url": e.get("media_url", ""),
            "is_quote": bool(e.get("is_quote")),
            "quote_label": e.get("quote_label", ""),
            "editable": bool(e.get("editable", True)),
        })
    return {
        "form": "scroll",                     # 手机端阅读
        "form_label": "手机端阅读",
        "viewport_w_px": SCREEN_W_PX,
        "block_count": len(blocks),
        "blocks": blocks,
    }


def render_photobook(content: dict) -> dict:
    """
    形态③「翻相册式」：以照片/视频为主，文字做注（图大字小）。
    若某章**一张图都没有**——不硬造相册页（绝不臆造），而是把它落进
    text_only 区，标明"本篇无图，未入相册式"。
    """
    albums, text_only = [], []
    cur = None
    for ch, e in _iter_entries(content):
        sid = ch.get("story_id", "")
        if cur is None or cur["story_id"] != sid:
            if cur is not None:
                _settle_album(cur, albums, text_only)
            cur = {"story_id": sid, "story_title": ch.get("story_title", ""),
                   "time_label": ch.get("time_label", ""), "items": [], "captions": []}
        if _is_media_entry(e):
            cur["items"].append({
                "media_url": e.get("media_url", ""),
                "kind": e.get("kind", ""),
                "is_quote": bool(e.get("is_quote")),
                "quote_label": e.get("quote_label", ""),
            })
        if e.get("text"):
            cur["captions"].append(e.get("text", ""))
    if cur is not None:
        _settle_album(cur, albums, text_only)
    return {
        "form": "photobook",                  # 翻相册式
        "form_label": "翻相册式",
        "album_count": len(albums),
        "photo_count": sum(len(a["items"]) for a in albums),
        "albums": albums,
        "text_only_story_ids": text_only,     # 没图、未入相册式的章（明写，不假造）
    }


def _settle_album(cur: dict, albums: list, text_only: list):
    if cur["items"]:
        cur["cover"] = cur["items"][0]["media_url"]
        albums.append(cur)
    elif cur["captions"]:
        text_only.append(cur["story_id"])


def render_book(content: dict, form: str = "scroll", *, book_spec: str = "A5") -> dict:
    """统一入口：按 form 派生一种形态。未知 form 回落 scroll（手机端阅读）并标注。"""
    f = (form or "scroll").strip().lower()
    if f in ("paged", "page", "翻页", "book"):
        return render_paged_book(content, book_spec=book_spec)
    if f in ("photobook", "album", "相册", "相册式"):
        return render_photobook(content)
    out = render_scroll_book(content)
    if f not in ("scroll", "阅读", "手机端阅读", "mobile", ""):
        out["fallback_from"] = f
    return out


# ============================================================
# 五、§8.6【待验证】免排版可行性的技术评估（给结论，不给空话）
# ============================================================

def assess_layout_freedom(content: dict) -> dict:
    """
    需求书 §8.6【待验证】"完全免排版的可行性边界，技术侧评估"——本函数给结论。

    结论（可证）：
      ✅ 可免排版：文字/引用的**分栏落位**——同一份 content 派生出屏/印两种尺寸的
         同一套 pages（paginate 按条目切，条目是排版最小单元），故"线上什么样印出来什么样"成立。
      ⚠️ 不可完全免排版：**照片长宽比**——老人手机拍的照片比例五花八门，
         固定页框下必须裁切或留白，此为该由人工在编书环节选一次（前端给"裁切/留白"开关）。
      ⚠️ 不可完全免排版：**字体缺失**——老人手写体/特殊符号在印刷端可能无字形，
         需印刷厂侧字体兜底（此条属外部依赖，非本端可解）。

    返回可核查的量化指标（不写"基本可行"这种虚话）。
    """
    total_entries = sum(1 for _ in _iter_entries(content))
    media_entries = sum(1 for _, e in _iter_entries(content) if _is_media_entry(e))
    text_entries = total_entries - media_entries
    ratio = (media_entries / total_entries) if total_entries else 0.0
    return {
        "total_entries": total_entries,
        "text_entries": text_entries,
        "media_entries": media_entries,
        "media_ratio": round(ratio, 3),
        "screen_and_print_share_same_pages": True,   # paginate() 同一结果喂两端
        "must_manual_decide": ["photo_aspect_ratio"],
        "external_dependency": ["printer_font_fallback"],
        "needs_manual_layout": ratio > 0,            # 有图就需人工定一次裁切策略
        "verdict": ("文字部分完全免排版；照片比例需人工选一次；字体需印刷厂兜底"
                    if ratio > 0 else "纯文字书：完全免排版可行"),
    }


# ============================================================
# 六、对外接口（handler）
# ============================================================

def _get_my_ebook(db, owner_id: str):
    return (db.query(Ebook)
              .filter(Ebook.owner_id == owner_id)
              .order_by(Ebook.created_at.desc())
              .first())


def api_book_view(db, *, owner_id: str, viewer_id: str = "",
                  form: str = "scroll", book_spec: str = "A5") -> dict:
    """
    GET /api/echoes/book/view —— 取我的书某一种形态（§8.6 三种）。
    只有书主人能取（私有形态不外流；对外分享走 share_api，只回公开素材）。

    §九 收费闸门（2026-10-17 补）：本接口是**唯一"完整版渲染"出口**
    （§8.6 三种形态 / A5 印刷件都从这里出），故付费卡点只设在这里。
      - 后台没开价      → 照旧全通（免费，§9.3 开关一关全站免费）
      - 后台开价且未买  → 返 `locked=true` + 报价 + 预览页数，**不返完整 view**
      - 已买/有效期内    → 照旧返回完整 view（§8.4 续添不再收钱）
    **老人自己的素材不在这里卡**（素材走 collect/story 接口，与收费无关）——锁的只是排版成品。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    viewer = viewer_id or owner_id
    if viewer != owner_id:
        return fail(NO_PERMISSION, "forbidden")
    eb = _get_my_ebook(db, owner_id)
    if eb is None:
        return ok({"empty": True, "book": None})
    content = _load_content(eb)
    if not content.get("chapters"):
        return ok({"empty": True, "book": None})

    # §九 收费闸门：只卡完整渲染
    import entitlement as E
    gate = E.book_lock_state(db, owner_id=owner_id)
    g = gate.get("data") or {}
    if g.get("locked"):
        chapters = content.get("chapters") or []
        return ok({
            "empty": False,
            "locked": True,
            "ebook_id": eb.id,
            "title": eb.title,
            "story_count": eb.story_count,
            "entitlement": g,
            "preview": {
                "chapters_visible": min(PREVIEW_CHAPTERS, len(chapters)),
                "chapters_total": len(chapters),
                "notice": g.get("notice", ""),
            },
            "view": None,
        }, warning=E.NEED_PAY, code=E.NEED_PAY)

    view = render_book(content, form=form, book_spec=book_spec)
    return ok({
        "empty": False,
        "locked": False,
        "ebook_id": eb.id,
        "title": eb.title,
        "story_count": eb.story_count,
        "form": view.get("form"),
        "view": view,
        "layout_assessment": assess_layout_freedom(content),
    })


def api_append_to_ebook(db, *, owner_id: str, actor_id: str = "",
                        story_ids=None) -> dict:
    """
    POST /api/echoes/book/append —— §8.4「可往里再添内容」（活文档，续添）。
    **不重建、保 ebook_id**：只把新 story 追加成章，已有章原样保留（引用段不动）。

    参数：
      story_ids  要续添的故事 id 列表；空 = 把该书主人**尚无的**故事自动补进来。
    幂等：已在该书里的 story_id 不重复加。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    actor = actor_id or owner_id
    if actor != owner_id:
        return fail(NO_PERMISSION, "forbidden")

    eb = _get_my_ebook(db, owner_id)
    if eb is None:
        return fail("还没有书，请先点【我要成书】生成", "no_ebook")

    content = _load_content(eb)
    chapters = content.get("chapters", []) or []
    existing = {c.get("story_id") for c in chapters}

    # 决定要补哪些故事
    if story_ids:
        wanted = [sid for sid in story_ids if sid and sid not in existing]
    else:
        mine = db.query(Story).filter(Story.owner_id == owner_id).all()
        wanted = [s.id for s in mine if s.id not in existing]

    added = []
    for sid in wanted:
        st = db.get(Story, sid)
        if st is None or getattr(st, "owner_id", "") != owner_id:
            continue                       # 不是我的篇，不收（绝不越权）
        entries = []
        for c in list_clips(db, st.id):
            provider = getattr(c, "provider_id", "") or ""
            mine_clip = (provider == owner_id)
            if not mine_clip:
                # 续添只收自己的素材；公共素材的收录权在"生成"环节点选，此处不擅自装
                continue
            entries.append({
                "clip_id": c.id,
                "kind": str(getattr(c, "clip_type", "") or ""),
                "text": _clip_text(c),
                "media_url": getattr(c, "media_url", "") or "",
                "is_quote": False,
                "ref_from_id": None,
                "ref_author_name": "",
                "quote_label": "",
                "editable": True,
            })
        if not entries:
            continue
        chapters.append({
            "story_id": st.id,
            "story_title": (getattr(st, "title", "") or "").strip() or "（无题）",
            "time_label": str(getattr(st, "time_label", "") or ""),
            "entries": entries,
        })
        added.append(st.id)

    if not added:
        return ok({"ebook_id": eb.id, "added_story_ids": [], "story_count": len(chapters),
                   "changed": False})

    eb.content = json.dumps({
        "title": eb.title,
        "owner_id": owner_id,
        "chapters": chapters,
        "contributors": content.get("contributors", []),
    }, ensure_ascii=False)
    eb.story_count = len(chapters)
    db.commit()
    db.refresh(eb)
    return ok({"ebook_id": eb.id, "added_story_ids": added,
               "story_count": len(chapters), "changed": True})


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    print("本文件为 handler 层，请跑 selftest_book_view.py")
