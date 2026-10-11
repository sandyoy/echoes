"""
往事可追忆 - 成书接口（handler 层）v1.0
建立：2026-10-11（第3期主体，sandy 要求「把表面那层做通、跳转要真能用」）

=== 为什么有本文件 ===
此前"成书"只有两个空壳：
  - story_api.api_create_book：只做"确保 owner 这个 User 存在"，根本不装素材；
  - 前端 pages/book/*：data:{} + wxml 写"第3期上线"，纯占位。
需求书 v3.0 §八「成书机制」写死的东西（两筐素材 / 谁成书谁是"我" / 引用不改写
/ 电子书先行），一条都没落到代码。本文件补这一跳。

=== 对照需求书 v3.0 §八（逐条落）===
  §8.1 成书顺序：电子书先（必有）→ 实体书后置      → 本接口只做①生成电子书
  §8.2 两筐素材：①自己的(无论公私)自动按时间装
                 ②公共的(别人公开的、与本书相关的) 点选装，不一定全装
  §8.2 引用段独立标记：公共素材里引用别人的话 → 标出处 + 不可改
  §8.2 署名：书署"我"(发书人)；引用段列贡献者/出处
  §8.3 书的"我"是谁：谁点成书谁是"我"；系统不转换人称
  §8.4 电子书：生成后可分享/续看/续添 —— 是活文档，不是终点

=== 设计铁律 ===
1. handler 不自己开 session，db 由调用方传（与 collect_api / story_api 同）
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **绝不越权**：只有书主人（owner）能给自己成书；引用别人的素材必须其已公开
4. 引用段**只读**：装进书里的公共素材，保留 ref_from_id + ref_author_name，
   正文里用独立标记包起来，后续任何编辑不得改动引用段内容
5. 生成是**幂等可重跑**的：ebook 已存在则覆盖内容（活文档），不重复建
"""

import json

from permissions import (
    _new_id, list_clips, can_view_story, can_quote_clip, visible_clips,
)
from models import (
    SessionLocal, Story, Clip, ClipType, Ebook, EbookStatus,
    Visibility, SourceType, User, init_db,
)

NO_PERMISSION = "只有这本书的主人能给它成书"
NO_STORIES = "这本书还没有故事，暂不能成书"


# ============================================================
# 一、统一信封（与 collect_api / story_api 同形，前端一套解析）
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
# 二、内部小工具
# ============================================================

def _clip_provider(clip) -> str:
    return (getattr(clip, "provider_id", "") or getattr(clip, "created_by", "") or "")


def _clip_visible(clip) -> bool:
    """素材是否已公开（默认私有 → 非 PUBLIC 一律算私有）"""
    v = getattr(clip, "visibility", None)
    if isinstance(v, Visibility):
        return v == Visibility.PUBLIC
    return str(v).lower().endswith("public")


def _clip_is_quote(clip) -> bool:
    st = getattr(clip, "source_type", None)
    if isinstance(st, SourceType):
        return st == SourceType.QUOTE
    return str(st).lower().endswith("quote")


def _clip_plain_text(clip) -> str:
    """把一件素材转成可入书的纯文本"""
    ct = getattr(clip, "clip_type", None)
    text = (getattr(clip, "text", "") or "").strip()
    if text:
        return text
    tr = (getattr(clip, "transcript", "") or "").strip()
    if tr:
        return tr
    if ct is not None and str(ct).lower().endswith("photo"):
        cap = (getattr(clip, "caption", "") or "").strip()
        return f"［照片］{cap}" if cap else "［照片］"
    if ct is not None and str(ct).lower().endswith("voice"):
        return "［一段语音］"
    if ct is not None and str(ct).lower().endswith("video"):
        return "［一段视频］"
    return "［一件素材］"


def _time_label(story) -> str:
    """故事的时间标签（用于入书排序与显示）"""
    lab = getattr(story, "time_label", "") or ""
    lab = str(lab).strip() if lab is not None else ""
    if lab:
        return lab
    key = getattr(story, "time_sort_key", "") or ""
    key = str(key).strip() if key is not None else ""
    return key or "时间待定"


def _sort_stories(db, stories):
    """按时间轴排序：有 sort_key 的在前按 key；无 key 的（时间待定）排最后"""
    def k(s):
        raw = getattr(s, "time_sort_key", "") or ""
        key = str(raw).strip() if raw is not None else ""
        return (0, key) if key else (1, str(getattr(s, "created_at", "") or ""))
    return sorted(stories, key=k)


# ============================================================
# 三、★核心：成书取材（§8.2 两筐素材）
# ============================================================

def api_book_source_baskets(db, *, owner_id: str, actor_id: str = "") -> dict:
    """
    成书前的「取材」预览：把两筐素材摆出来，让"我"看着点。

    筐① 自己的素材（自动装）：owner 拥有/提供的所有素材，无论公开私有
    筐② 公共素材（点选装）：**别人**公开的、且提到了 owner 的素材
                            → 给不给是"我"的权利，未必要收

    返回结构（前端 book 页直接用）：
    {
      "own":    [ {clip_id, story_id, story_title, time_label, kind, text, provider, is_quote} ],
      "public": [ {clip_id, story_id, story_title, time_label, kind, text,
                   provider, provider_name, ref_author_name, selected_hint} ],
      "own_count": N, "public_count": M
    }
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    actor = actor_id or owner_id
    if actor != owner_id:
        return fail(NO_PERMISSION, "forbidden")

    # owner 这本书下的全部故事
    stories = db.query(Story).filter(Story.owner_id == owner_id).all()
    if not stories:
        return ok({"own": [], "public": [], "own_count": 0, "public_count": 0,
                   "empty": True, "hint": NO_STORIES})

    own, public = [], []
    for st in stories:
        tlab = _time_label(st)
        for c in list_clips(db, st.id):
            item = {
                "clip_id": c.id,
                "story_id": st.id,
                "story_title": (getattr(st, "title", "") or "").strip() or "（无题）",
                "time_label": tlab,
                "kind": str(getattr(c, "clip_type", "") or ""),
                "text": _clip_plain_text(c),
                "media_url": getattr(c, "media_url", "") or "",
                "provider": _clip_provider(c),
                "is_quote": _clip_is_quote(c),
                "ref_author_name": getattr(c, "ref_author_name", "") or "",
            }
            if _clip_provider(c) == owner_id:
                # 我自己的：无论公私，自动装
                own.append(item)
            elif _clip_visible(c):
                # 别人公开的：进公共筐，等"我"点选
                # （能否引用：can_quote_clip 已保证"非本人须公开"）
                if can_quote_clip(db, clip=c, viewer_id=owner_id):
                    item["selected_hint"] = "public"   # 默认不选，由"我"决定
                    public.append(item)

    own = sorted(own, key=lambda x: (x["time_label"] == "时间待定", x["time_label"]))
    public = sorted(public, key=lambda x: (x["time_label"] == "时间待定", x["time_label"]))
    return ok({
        "own": own, "public": public,
        "own_count": len(own), "public_count": len(public),
        "empty": False,
    })


# ============================================================
# 四、★核心：生成电子书（§8.1 先电子书 + §8.2 两筐 + §8.3 谁成书谁是"我"）
# ============================================================

def api_generate_ebook(
    db,
    *,
    owner_id: str,
    actor_id: str = "",
    title: str = "",
    picked_public_ids=None,
    ebook_id: str = "",
) -> dict:
    """
    点【我要成书】→ 生成/刷新电子书。

    参数：
      owner_id      书的主人（= 点成书的"我"，§8.3）
      actor_id      实际操作人（必须 == owner_id，防止别人替你成书）
      title         书名（空则用昵称/「我的一生」）
      picked_public_ids  从公共筐里**点选**要装的素材 id 列表（§8.2 筐②）
                         None / [] = 一件公共素材都不装（也可）
      ebook_id      已有书 id → 覆盖刷新（§8.4 活文档，可续添后重生成）

    输出：
      {ebook_id, title, chapters:[...], story_count, clip_count,
       contributors:[...], generated_at}
    其中 chapters 里每章含 entries，entry 带 is_quote / ref_author_name，
    **引用段被独立标记**，前端照此渲染"这段来自张大叔的讲述"样式。
    """
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    actor = actor_id or owner_id
    if actor != owner_id:
        return fail(NO_PERMISSION, "forbidden")

    picked = set(picked_public_ids or [])

    stories = db.query(Story).filter(Story.owner_id == owner_id).all()
    if not stories:
        return fail(NO_STORIES, "no_stories")
    stories = _sort_stories(db, stories)

    # 书名：空则取昵称
    book_title = (title or "").strip()
    if not book_title:
        u = db.get(User, owner_id)
        book_title = (getattr(u, "nick_name", "") or "").strip() or "我的一生"

    chapters, contributors, clip_total = [], [], 0
    for st in stories:
        entries = []
        for c in list_clips(db, st.id):
            mine = _clip_provider(c) == owner_id
            is_public_other = (not mine) and _clip_visible(c)
            if mine:
                pass                                  # 筐①：自动装
            elif is_public_other and c.id in picked:  # 筐②：我点了才装
                pass
            else:
                continue                              # 未点选的公共素材：不装
            quote = _clip_is_quote(c) or (not mine)
            ref_name = (getattr(c, "ref_author_name", "") or "").strip()
            entries.append({
                "clip_id": c.id,
                "kind": str(getattr(c, "clip_type", "") or ""),
                "text": _clip_plain_text(c),
                "media_url": getattr(c, "media_url", "") or "",
                "is_quote": quote,
                "ref_from_id": getattr(c, "ref_from_id", None),
                "ref_author_name": ref_name,
                # 引用段渲染提示：前端据此画"这段来自XX的讲述"
                "quote_label": f"这段来自{ref_name}的讲述" if (quote and ref_name) else ("引用" if quote else ""),
                "editable": (not quote),   # §8.2 引用段不可改
            })
            clip_total += 1
            if quote and ref_name and ref_name not in contributors:
                contributors.append(ref_name)
        if entries:
            chapters.append({
                "story_id": st.id,
                "story_title": (getattr(st, "title", "") or "").strip() or "（无题）",
                "time_label": _time_label(st),
                "entries": entries,
            })

    if not chapters:
        return fail("书里还没有可装入的素材", "empty_book")

    # 落库（幂等：有 ebook_id 则覆盖 → 活文档）
    eb = db.get(Ebook, ebook_id) if ebook_id else None
    if eb is None:
        eb = Ebook(id=_new_id("ebook"), owner_id=owner_id)
        db.add(eb)
    eb.title = book_title
    eb.owner_id = owner_id
    eb.status = EbookStatus.GENERATED
    eb.story_count = len(chapters)
    eb.content = json.dumps({
        "title": book_title,
        "owner_id": owner_id,
        "chapters": chapters,
        "contributors": contributors,
    }, ensure_ascii=False)
    db.commit()
    db.refresh(eb)

    return ok({
        "ebook_id": eb.id,
        "title": eb.title,
        "chapters": chapters,
        "story_count": len(chapters),
        "clip_count": clip_total,
        "contributors": contributors,
        "generated_at": str(getattr(eb, "generated_at", "") or ""),
    })


# ============================================================
# 五、取我的电子书（前端 book 页进入时读）
# ============================================================

def api_my_ebook(db, *, owner_id: str, viewer_id: str = "") -> dict:
    """取这本书（owner）已生成的电子书；没有则返回 empty=True（前端显示"还没成书"）"""
    if not owner_id:
        return fail("缺少 owner_id", "missing_owner_id")
    eb = (db.query(Ebook)
            .filter(Ebook.owner_id == owner_id)
            .order_by(Ebook.created_at.desc())
            .first())
    if eb is None:
        return ok({"empty": True, "book": None})
    try:
        content = json.loads(eb.content or "{}")
    except Exception:
        content = {}
    return ok({
        "empty": False,
        "book": {
            "ebook_id": eb.id,
            "title": eb.title,
            "story_count": eb.story_count,
            "status": str(getattr(eb, "status", "") or ""),
            "chapters": content.get("chapters", []),
            "contributors": content.get("contributors", []),
        },
    })


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    print("本文件为 handler 层，请跑 selftest_book_api.py")
