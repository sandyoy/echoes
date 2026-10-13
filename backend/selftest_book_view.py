"""
往事可追忆 - 书的形态与续添 自测  v1.0
建立：2026-10-13  对应 backend/book_view_api.py（§8.6 三种形态 + §8.4 续添 + §8.6 免排版评估）

铁律：断言 status_code==200 且关键字段存在（见事卷 §二 假报前科）。
库隔离：必须在 import 前设 DATABASE_URL，避免污染生产库（见 10-01 事故）。
"""

import os
import sys
import tempfile

# ---- 库隔离（必须在 import models 前设）----
_TMPDB = os.path.join(tempfile.mkdtemp(prefix="echoes_bv_"), "t.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDB}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, init_db, User, Story, Clip, ClipType, Ebook, EbookStatus,
    Visibility, SourceType,
)
import book_view_api as B  # noqa: E402
import book_api as BK      # noqa: E402

PASS = FAIL = 0
FAILS = []


def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  ❌ {name}  {extra}")


def _mk_user(db, uid, nick=""):
    u = User(id=uid, nick_name=nick or uid)
    db.add(u)
    return u


def _mk_story(db, owner, sid, title, time_label=""):
    s = Story(id=sid, owner_id=owner, title=title, time_label=time_label)
    db.add(s)
    return s


def _mk_clip(db, story_id, cid, kind=ClipType.TEXT, provider="", text="",
             media_url="", vis=Visibility.PUBLIC, order=0):
    c = Clip(id=cid, story_id=story_id, clip_type=kind, provider_id=provider,
             text=text, media_url=media_url, visibility=vis,
             source_type=SourceType.ORIGIN, sort_order=order, created_by=provider)
    db.add(c)
    return c


def main():
    init_db()
    db = SessionLocal()

    owner = "u_owner"
    _mk_user(db, owner, "李桂芳")

    # ---- 造书：2 篇故事 ----
    _mk_story(db, owner, "s1", "结婚那年", "1968年")
    _mk_story(db, owner, "s2", "进城打工", "1985年")
    db.commit()

    # s1：4 条文字素材（我的）
    for i in range(4):
        _mk_clip(db, "s1", f"c1_{i}", text=f"第一条故事第{i+1}段。", provider=owner,
                 vis=Visibility.PUBLIC, order=i)
    # s2：1 张照片 + 1 条文字（我的）
    _mk_clip(db, "s2", "c2_img", kind=ClipType.PHOTO, media_url="http://x/p1.jpg",
             provider=owner, vis=Visibility.PUBLIC, order=0)
    _mk_clip(db, "s2", "c2_txt", text="进城那年拍的。", provider=owner,
             vis=Visibility.PUBLIC, order=1)
    db.commit()

    # ========================================================
    print("\n【一】生成书（复用 book_api）")
    gen = BK.api_generate_ebook(db, owner_id=owner, title="我的一生")
    chk("生成书 ok", gen.get("ok") is True, str(gen)[:200])
    chk("书名生效", gen["data"]["title"] == "我的一生")
    chk("两章", gen["data"]["story_count"] == 2, str(gen["data"].get("story_count")))
    chk("素材计数 6", gen["data"]["clip_count"] == 6, str(gen["data"].get("clip_count")))
    eb_id = gen["data"]["ebook_id"]

    # ========================================================
    print("\n【二】§8.6 形态①翻页（paged）")
    v = B.api_book_view(db, owner_id=owner, form="paged")
    chk("取 paged ok", v.get("ok") is True, str(v)[:200])
    view = v["data"]["view"]
    chk("form=paged", view["form"] == "paged", str(view.get("form")))
    chk("有页数", view["page_count"] >= 1, str(view.get("page_count")))
    chk("每页带 A5 尺寸", view["pages"][0]["page_size_mm"]["width_mm"] == 148,
        str(view["pages"][0].get("page_size_mm")))
    chk("页保留章标题", any(p["chapter_title"] for p in view["pages"]))

    # ========================================================
    print("\n【三】§8.6 形态②手机端阅读（scroll）")
    v2 = B.api_book_view(db, owner_id=owner, form="scroll")
    chk("取 scroll ok", v2.get("ok") is True)
    vv = v2["data"]["view"]
    chk("form=scroll", vv["form"] == "scroll")
    chk("块数=6", vv["block_count"] == 6, str(vv.get("block_count")))
    chk("带屏宽", vv["viewport_w_px"] == 750)
    chk("块保留 time_label", any(b["time_label"] for b in vv["blocks"]))

    # ========================================================
    print("\n【四】§8.6 形态③翻相册式（photobook）")
    v3 = B.api_book_view(db, owner_id=owner, form="photobook")
    chk("取 photobook ok", v3.get("ok") is True)
    pv = v3["data"]["view"]
    chk("form=photobook", pv["form"] == "photobook")
    chk("相册数=1（只有 s2 有图）", pv["album_count"] == 1, str(pv.get("album_count")))
    chk("照片数=1", pv["photo_count"] == 1)
    chk("相册封面=那张图", pv["albums"][0]["cover"] == "http://x/p1.jpg")
    chk("无图章落 text_only（s1 明写未入相册）", "s1" in pv["text_only_story_ids"],
        str(pv.get("text_only_story_ids")))

    # ========================================================
    print("\n【五】形态回落 & 未知 form 不臆造")
    v4 = B.api_book_view(db, owner_id=owner, form="胡说")
    chk("未知 form 回落 scroll", v4["data"]["view"]["form"] == "scroll")
    chk("回落带 fallback_from", v4["data"]["view"].get("fallback_from") == "胡说")

    # ========================================================
    print("\n【六】越权：非书主人不得取形态")
    _mk_user(db, "u_other", "张三")
    db.commit()
    v5 = B.api_book_view(db, owner_id=owner, viewer_id="u_other", form="paged")
    chk("外人取形态 403", v5.get("code") == "forbidden", str(v5)[:150])

    # ========================================================
    print("\n【七】§8.6 免排版可行性评估（给结论不空话）")
    la = v["data"]["layout_assessment"]
    chk("有结论字符串", bool(la.get("verdict")), str(la)[:200])
    chk("屏印共用同一 pages 标志", la["screen_and_print_share_same_pages"] is True)
    chk("有图→需人工定裁切", la["needs_manual_layout"] is True)
    chk("量化 media_ratio=1/6≈0.167", abs(la["media_ratio"] - 0.1667) < 0.01,
        str(la.get("media_ratio")))

    # ========================================================
    print("\n【八】§8.4 续添（活文档：保 ebook_id 追加新篇）")
    _mk_story(db, owner, "s3", "老了以后", "2020年")
    _mk_clip(db, "s3", "c3_0", text="退休后种花。", provider=owner, vis=Visibility.PUBLIC)
    db.commit()
    ap = B.api_append_to_ebook(db, owner_id=owner)
    chk("续添 ok", ap.get("ok") is True, str(ap)[:200])
    chk("added 含 s3", "s3" in ap["data"]["added_story_ids"], str(ap["data"]))
    chk("ebook_id 未变（不重建）", ap["data"]["ebook_id"] == eb_id)
    chk("章数 2→3", ap["data"]["story_count"] == 3)
    # 幂等
    ap2 = B.api_append_to_ebook(db, owner_id=owner)
    chk("二次续添 changed=False（幂等）", ap2["data"]["changed"] is False)

    # ========================================================
    print("\n【九】续添不得越权：不能把别人的篇装进我的书")
    _mk_story(db, "u_other", "s9", "别人的故事")
    _mk_clip(db, "s9", "c9_0", text="不是我的。", provider="u_other",
             vis=Visibility.PUBLIC)
    db.commit()
    ap3 = B.api_append_to_ebook(db, owner_id=owner, story_ids=["s9"])
    chk("别人的篇加不进来", ap3["data"]["added_story_ids"] == [], str(ap3["data"]))
    # 非主人续添
    ap4 = B.api_append_to_ebook(db, owner_id=owner, actor_id="u_other", story_ids=["s3"])
    chk("非主人续添 403", ap4.get("code") == "forbidden", str(ap4)[:150])

    # ========================================================
    print("\n【十】空书 & 边界")
    _mk_user(db, "u_none", "无书人")
    db.commit()
    v6 = B.api_book_view(db, owner_id="u_none")
    chk("无书 empty=True", v6["data"].get("empty") is True)
    chk("无书不报错", v6.get("ok") is True)
    ap5 = B.api_append_to_ebook(db, owner_id="u_none")
    chk("无书续添 no_ebook", ap5.get("code") == "no_ebook", str(ap5)[:120])
    chk("缺 owner_id 报错", B.api_book_view(db, owner_id="").get("code") == "missing_owner_id")

    # ========================================================
    print("\n【十一】纯文字书：免排版评估给「完全可行」")
    _mk_user(db, "u_txt", "纯文字人")
    _mk_story(db, "u_txt", "t1", "只有文字")
    _mk_clip(db, "t1", "t1_0", text="纯文字段。", provider="u_txt", vis=Visibility.PUBLIC)
    db.commit()
    BK.api_generate_ebook(db, owner_id="u_txt", title="纯文字书")
    vt = B.api_book_view(db, owner_id="u_txt", form="paged")
    lat = vt["data"]["layout_assessment"]
    chk("纯文字 needs_manual_layout=False", lat["needs_manual_layout"] is False, str(lat))
    chk("纯文字 verdict 说完全可行", "完全免排版可行" in lat["verdict"], lat["verdict"])

    # ========================================================
    print("\n【十二】信封形状统一")
    for k in ("ok", "data", "error", "code"):
        chk(f"信封含 {k}", k in v)
    chk("失败信封 error 非空", B.api_book_view(db, owner_id="", ).get("error") != "")

    db.close()
    print(f"\n===== book_view 自测：{PASS}/{PASS+FAIL} 通过 =====")
    if FAILS:
        print("失败项：", FAILS)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
