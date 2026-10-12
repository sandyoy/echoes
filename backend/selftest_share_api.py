"""
selftest_share_api.py —— 分享机制（v3.0 §八之二）自测
========================================================
实跑，不静态核验。依赖 DATABASE_URL 走内存库（严禁污染生产库 memory_story.db）。

覆盖：
  ① 全私有的篇 → 不可分享（can_share_story=False；make_story_share raise）
  ② 有一条公开素材 → 可分享，token 稳定、path 对
  ③ 无登录读分享：**只回公开素材**（私有素材一条都不漏）
  ④ 分享后被改回全私有 → 分享打不开（share_gone，不泄内容）
  ⑤ 分享小程序本身：无素材也能分（分的是产品）
  ⑥ 分享整本书：只含有公开内容的篇
  ⑦ 卡片图数据：全私有 → 拒绝；有公开 → 出引子
  ⑧ **v3.0 mention 闸门**：私有篇提到的人 → 不提示（N=0）；公开篇 → 提示（N=1）
  ⑨ **v3.0 登记闸门**：给"只有私有素材的篇"登记被提到的人 → 被拒
  ⑩ 信封形状（ok/code）
"""

import os
import sys

# ★ 必须在 import models 之前设库（models 读 DATABASE_URL）
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ECHOES_DB"] = ":memory:"
os.environ["DB_PATH"] = ":memory:"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, Base, engine, User, Story, Clip, ClipType, Visibility, SourceType,
)
import share_api as S  # noqa: E402
import claim as C  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    # --- 造数据：李桂芳（老人 owner）+ 张大叔（被提到的人）---
    laoli = User(id="u_laoli", nick_name="李桂芳")
    zhang = User(id="u_zhang", nick_name="张大叔")
    db.add_all([laoli, zhang])

    # 故事A：全私有（还没想好要不要说）
    storyA = Story(id="s_A", owner_id="u_laoli", title="1979年那场大水",
                   time_raw="1979年", people_mentioned=[{"name": "张大叔", "user_id": "u_zhang"}])
    # 故事B：有一条公开
    storyB = Story(id="s_B", owner_id="u_laoli", title="嫁过来第二年",
                   time_raw="嫁过来第二年", people_mentioned=[{"name": "张大叔", "user_id": "u_zhang"}])
    db.add_all([storyA, storyB])
    db.commit()

    # A：只有私有素材（提到张大叔）
    db.add(Clip(id="c_A1", story_id="s_A", clip_type=ClipType.TEXT,
                text="那年水好大，张大叔家的麦子全淹了",
                provider_id="u_laoli", visibility=Visibility.PRIVATE))
    # B：一条私有 + 一条公开
    db.add(Clip(id="c_B1", story_id="s_B", clip_type=ClipType.TEXT,
                text="张大叔那天来帮忙", provider_id="u_laoli",
                visibility=Visibility.PRIVATE))
    db.add(Clip(id="c_B2", story_id="s_B", clip_type=ClipType.TEXT,
                text="我嫁过来第二年，村里通了电", provider_id="u_laoli",
                visibility=Visibility.PUBLIC))
    db.commit()

    print("\n=== ① 全私有的篇不可分享 ===")
    check("A 全私有 → can_share_story False", S.can_share_story(db, story_id="s_A") is False)
    check("B 有公开 → can_share_story True", S.can_share_story(db, story_id="s_B") is True)
    try:
        S.make_story_share(db, story_id="s_A", actor_id="u_laoli")
        check("A 造分享应被拒", False, "(没报错)")
    except PermissionError as e:
        check("A 造分享 raise PermissionError", True)

    print("\n=== ② 造分享 token/path ===")
    sh = S.make_story_share(db, story_id="s_B", actor_id="u_laoli")
    check("token 以 s_ 开头", sh["share_token"].startswith("s_"), sh["share_token"])
    check("path 对", sh["path"] == f"pages/shared/story?t={sh['share_token']}", sh["path"])
    check("public_clip_count=1", sh["public_clip_count"] == 1, sh["public_clip_count"])
    # 幂等：同篇再算一次 token 一样
    sh2 = S.make_story_share(db, story_id="s_B", actor_id="u_laoli")
    check("token 稳定（同篇同 token）", sh["share_token"] == sh2["share_token"])

    print("\n=== ③ 无登录读分享：只回公开素材 ===")
    v = S.api_view_shared(db, share_token=sh["share_token"])
    check("读成功 ok=True", v.get("ok") is True, v)
    check("只回 1 条（公开那条）", v["data"]["clip_count"] == 1, v["data"]["clip_count"])
    check("回的正是 c_B2（公开）", v["data"]["clips"][0]["clip_id"] == "c_B2",
          v["data"]["clips"][0]["clip_id"])
    texts = " ".join(c["text"] for c in v["data"]["clips"])
    check("私有素材文字未泄漏", "帮忙" not in texts, texts)

    print("\n=== ④ 分享后改回全私有 → 打不开 ===")
    # 把 B 的唯一公开素材改回私有
    from permissions import set_clip_visibility
    set_clip_visibility(db, clip_id="c_B2", actor_id="u_laoli", visibility=Visibility.PRIVATE)
    v2 = S.api_view_shared(db, share_token=sh["share_token"])
    check("改私有后打不开（share_gone）", v2.get("code") == "share_gone", v2)
    # 还原
    set_clip_visibility(db, clip_id="c_B2", actor_id="u_laoli", visibility=Visibility.PUBLIC)

    print("\n=== ⑤ 分享小程序本身（无素材也能分）===")
    app = S.api_make_share(db, actor_id="u_laoli", kind="app")
    check("app 分享 ok", app.get("ok") is True, app)
    check("path=首页", app["data"]["path"] == "pages/index/index", app["data"]["path"])
    check("kind=app", app["data"]["kind"] == "app")

    print("\n=== ⑥ 分享整本书：只含公开篇 ===")
    bk = S.make_book_share(db, owner_id="u_laoli", actor_id="u_laoli")
    check("可分享篇数=1（A 全私有不算）", bk["shareable_story_count"] == 1, bk["shareable_story_count"])
    check("总篇数=2", bk["total_story_count"] == 2, bk["total_story_count"])
    vb = S.view_shared_book(db, owner_id="u_laoli")
    check("书分享只列 1 篇", vb["data"]["story_count"] == 1, vb["data"])
    check("列的正是 B", vb["data"]["stories"][0]["story_id"] == "s_B", vb["data"]["stories"])

    print("\n=== ⑦ 卡片图数据 ===")
    try:
        S.make_card_data(db, kind="story", target_id="s_A")
        check("A 全私有做卡片应被拒", False, "(没报错)")
    except PermissionError:
        check("A 全私有做卡片 raise", True)
    card = S.make_card_data(db, kind="story", target_id="s_B")
    check("B 卡片出引子", card["excerpt"] != "", card)
    check("B 卡片 headline 带 owner 名", "李桂芳" in card["headline"], card["headline"])

    print("\n=== ⑧ v3.0 mention 闸门（关键：私有篇不提示）===")
    # 张大叔：A（私有）提到他、B（公开）提到他 → 只应算 B 一篇
    n = C.pending_mentioned_count(db, user_id="u_zhang")
    check("张大叔 N=1（只公开篇 B 算）", n == 1, n)
    titles = {s.id for s in C.mentioned_stories(db, user_id="u_zhang")}
    check("命中的正是 s_B", titles == {"s_B"}, titles)

    # 把 A 也变成公开篇（加一条公开素材）→ N 应变 2
    db.add(Clip(id="c_A2", story_id="s_A", clip_type=ClipType.TEXT,
                text="水退了以后大家互相帮衬", provider_id="u_laoli",
                visibility=Visibility.PUBLIC))
    db.commit()
    n2 = C.pending_mentioned_count(db, user_id="u_zhang")
    check("A 转公开后 N=2", n2 == 2, n2)

    print("\n=== ⑨ v3.0 登记闸门 ===")
    # 新建一篇只有私有素材的篇，给它登记被提到的人 → 应被拒
    sP = Story(id="s_P", owner_id="u_laoli", title="还没想好")
    db.add(sP)
    db.add(Clip(id="c_P1", story_id="s_P", clip_type=ClipType.TEXT,
                text="私事", provider_id="u_laoli", visibility=Visibility.PRIVATE))
    db.commit()
    try:
        C.register_claim(db, owner_id="u_laoli", phone="13800000000", story_id="s_P")
        check("私有篇登记应被拒", False, "(没报错)")
    except PermissionError:
        check("私有篇登记 raise PermissionError", True)
    # 空篇（还没素材）登记 → 放行（新建故事先登记人）
    sE = Story(id="s_E", owner_id="u_laoli", title="空篇")
    db.add(sE)
    db.commit()
    try:
        C.register_claim(db, owner_id="u_laoli", phone="13900000000", story_id="s_E")
        check("空篇登记放行（新建故事先登记人）", True)
    except Exception as e:
        check("空篇登记放行", False, str(e))

    print("\n=== ⑩ 信封形状 ===")
    bad = S.api_view_shared(db, share_token="s_deadbeef")
    check("坏 token → ok=False + code", bad.get("ok") is False and "code" in bad, bad)
    check("缺 token → code=missing_token",
          S.api_view_shared(db, share_token="").get("code") == "missing_token")

    db.close()
    print(f"\n===== 分享机制自测：{PASS}/{PASS+FAIL} 通过 =====")
    if FAIL:
        print(f"❌ 有 {FAIL} 条失败")
        sys.exit(1)
    print("✅ 全绿")


if __name__ == "__main__":
    main()
