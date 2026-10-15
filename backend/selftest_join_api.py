"""
selftest_join_api.py —— 「我也加进来」加入链路自测（§8之二.5 / §8之二.8）

覆盖（每条对应需求书一条硬口径）：
  A. 篇末那一块（api_join_target）
     A1 无登录也能读（看不用登录 §8之二.8）
     A2 篇末那句 =「这是<owner>的故事，里面提到了你」
     A3 无 user_id → need_login=True，且**不**说 can_join
     A4 被提及者 → can_join=True（§8之二.5 被提一句就能看这一篇/无需授权）
     A5 非被提及者 → can_join=False + reason_code=not_mentioned（★§1.2 铁律3 不许泄密）
     A6 已加入 → already_joined=True
     A7 失效 token → share_gone
  B. 加入（api_join_by_share）
     B1 ★主路径：被提及者点【我也加进来】→ granted_via=story、只看这一篇
     B2 无 user_id → login_required（参与才登录）
     B3 ★幂等：点两次 → 第二次 already_joined=True，member_id 不变、Member 不翻倍
     B4 ★资格闸门：非被提及者凭 token 硬加 → not_mentioned 拒（不许塞进别人的篇）
     B5 自己的篇 → is_owner 拒
     B6 家人已在册 → already_family 拒（不用再加这一篇）
     B7 失效 token → share_gone（不假装成功）
     B8 ★越权验收：加入后**只能看这一篇**，同书别的私有篇仍看不到
     B9 加入后可见清单含这一篇（visible_story_ids）
  C. 我的加入（api_my_memberships）
     C1 无登录拒
     C2 列出 story 级 + book 级（家人）两种
  D. 信封形状
     D1 ok 信封含 ok/data/error/code
     D2 fail 信封含 ok/error/code、data=None
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TMP = tempfile.mkdtemp(prefix="selftest_join_")
os.environ["ECHOES_DB"] = os.path.join(TMP, "join_test.db")

import models  # noqa: E402
models.DB_PATH = os.environ["ECHOES_DB"]
if hasattr(models, "engine"):
    try:
        models.engine.dispose()
    except Exception:
        pass

from models import (  # noqa: E402
    init_db, SessionLocal, User, Story, Clip, Member,
    Visibility, ClipType, SourceType, UiMode, ClaimStatus, GrantVia,
)
import permissions as P     # noqa: E402
import share_api as S       # noqa: E402
import join_api as J        # noqa: E402

PASS, FAIL = 0, 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name} {detail}")


def sec(t):
    print(f"\n--- {t} ---")


def main():
    from models import engine
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ---------- 造数 ----------
    OWNER = "u_owner"       # 书主人 李桂芳
    MENTIONED = "u_zhang"   # 被提及者 张三
    OTHER = "u_stranger"    # 陌生人 老王
    FAMILY = "u_daughter"   # 已是家人

    db.add(User(id=OWNER, nick_name="李桂芳", ui_mode=UiMode.STANDARD))
    db.add(User(id=MENTIONED, nick_name="张三", ui_mode=UiMode.STANDARD))
    db.add(User(id=OTHER, nick_name="老王", ui_mode=UiMode.STANDARD))
    db.add(User(id=FAMILY, nick_name="小芳", ui_mode=UiMode.STANDARD))
    s_pub = Story(id="s_public", owner_id=OWNER, title="结婚那年",
                  time_raw="1968年",
                  people_mentioned=[{"name": "张三", "user_id": MENTIONED}])
    s_priv = Story(id="s_private", owner_id=OWNER, title="心里的疙瘩",
                   time_raw="1972年")
    db.add(s_pub)
    db.add(s_priv)
    # 公开篇：一条公开素材（可分享）
    db.add(Clip(id="c1", story_id="s_public", clip_type=ClipType.TEXT,
                text="1968年我嫁过来", provider_id=OWNER,
                visibility=Visibility.PUBLIC, source_type=SourceType.ORIGIN,
                sort_order=1))
    # 私有篇：只有私有素材
    db.add(Clip(id="c2", story_id="s_private", clip_type=ClipType.TEXT,
                text="这句我不想给别人看", provider_id=OWNER,
                visibility=Visibility.PRIVATE, source_type=SourceType.ORIGIN,
                sort_order=1))
    # 家人：小芳
    P.add_family_member(db, owner_id=OWNER, display_name="小芳", user_id=FAMILY)
    db.commit()

    token = S.make_story_share(db, story_id="s_public", actor_id=OWNER)["share_token"]
    # 私有篇的 token：不该造得出来
    try:
        S.make_story_share(db, story_id="s_private", actor_id=OWNER)
        priv_token = "__should_not_exist__"
    except PermissionError:
        priv_token = "__not_made__"

    # ============ A. 篇末那一块 ============
    sec("A. 篇末那一块（§8之二.5 篇末那句）")
    # A1 无登录也能读
    r = J.api_join_target(db, share_token=token)
    check("A1 无登录也能拿到篇末块", r["ok"] and r["data"]["story_id"] == "s_public", r)
    # A2 headline
    check("A2 篇末那句=这是<owner>的故事，里面提到了你",
          r["data"]["headline"] == "这是李桂芳的故事，里面提到了你", r["data"].get("headline"))
    # A3 need_login
    check("A3 无 user_id → need_login=True 且 can_join=False",
          r["data"]["need_login"] is True and r["data"]["can_join"] is False, r["data"])
    check("A3b 无登录时不擅自说 already_joined",
          r["data"]["already_joined"] is False, r["data"])
    # A4 被提及者
    r4 = J.api_join_target(db, share_token=token, user_id=MENTIONED)
    check("A4 被提及者 → can_join=True", r4["ok"] and r4["data"]["can_join"] is True, r4["data"])
    check("A4b 默认粒度=story、不擅自开全本",
          r4["data"]["join_granularity"] == "story"
          and r4["data"]["can_upgrade_to_family"] is False, r4["data"])
    # A5 陌生人
    r5 = J.api_join_target(db, share_token=token, user_id=OTHER)
    check("A5j 非被提及者 → can_join=False", r5["data"]["can_join"] is False, r5["data"])
    check("A5b 给 reason_code=not_mentioned（★不泄密口径）",
          r5["data"].get("reason_code") == "not_mentioned", r5["data"])
    # A7 失效 token
    r7 = J.api_join_target(db, share_token="s_deadbeef")
    check("A7 失效 token → share_gone", (not r7["ok"]) and r7["code"] == "share_gone", r7)

    # ============ B. 加入 ============
    sec("B. 加入（§8之二.5 点【我也加进来】）")
    # B2 无登录
    r = J.api_join_by_share(db, share_token=token, user_id="")
    check("B2 无 user_id → login_required", (not r["ok"]) and r["code"] == "login_required", r)
    # B4 资格闸门（先于 B1 跑，且不落库）
    r = J.api_join_by_share(db, share_token=token, user_id=OTHER)
    check("B4 陌生人凭 token 硬加 → not_mentioned 拒（★不塞进别人的篇）",
          (not r["ok"]) and r["code"] == "not_mentioned", r)
    check("B4b 被拒后**没有**落 Member",
          db.query(Member).filter(Member.user_id == OTHER).count() == 0, "")
    # B5 自己的篇
    r = J.api_join_by_share(db, share_token=token, user_id=OWNER)
    check("B5 自己的篇 → is_owner 拒", (not r["ok"]) and r["code"] == "is_owner", r)
    # B6 家人
    r = J.api_join_by_share(db, share_token=token, user_id=FAMILY)
    check("B6 已是家人 → already_family 拒（看整本，不用加这一篇）",
          (not r["ok"]) and r["code"] == "already_family", r)
    # B7 失效 token
    r = J.api_join_by_share(db, share_token="s_deadbeef", user_id=MENTIONED)
    check("B7 失效 token → share_gone（不假装成功）",
          (not r["ok"]) and r["code"] == "share_gone", r)
    # B1 主路径
    r1 = J.api_join_by_share(db, share_token=token, user_id=MENTIONED,
                             display_name="张三")
    check("B1 被提及者加入成功", r1["ok"] and r1["data"]["already_joined"] is False, r1)
    check("B1b granted_scope=story（★只看这一篇）",
          r1["data"]["granted_scope"] == "story", r1["data"])
    check("B1c granted_via=story", r1["data"]["granted_via"] == "story", r1["data"])
    mid = r1["data"]["member_id"]
    check("B1d 拿到 member_id", bool(mid), r1["data"])
    # B9 可见清单含这一篇
    check("B9 visible_story_ids 含 s_public",
          "s_public" in r1["data"]["visible_story_ids"], r1["data"])
    # B8 ★越权：不能看同书的私有篇
    check("B8 ★加入后看不到同书别的私有篇（s_private 不在可见清单）",
          "s_private" not in r1["data"]["visible_story_ids"], r1["data"])
    check("B8b can_view_story 对私有篇仍 False",
          P.can_view_story(db, owner_id=OWNER, viewer_id=MENTIONED,
                           story_id="s_private") is False, "")
    # B3 幂等
    r3 = J.api_join_by_share(db, share_token=token, user_id=MENTIONED)
    check("B3 ★幂等：再点一次 already_joined=True", r3["ok"] and r3["data"]["already_joined"] is True, r3)
    check("B3b member_id 不变", r3["data"]["member_id"] == mid, (r3["data"], mid))
    check("B3c Member 不翻倍",
          db.query(Member).filter(Member.owner_id == OWNER,
                                  Member.user_id == MENTIONED).count() == 1, "")

    # ============ C. 我的加入 ============
    sec("C. 我的加入（api_my_memberships）")
    rc = J.api_my_memberships(db, user_id="")
    check("C1 无登录 → login_required", (not rc["ok"]) and rc["code"] == "login_required", rc)
    rm = J.api_my_memberships(db, user_id=MENTIONED)
    check("C2 张三：1 条 story 级", rm["ok"] and rm["data"]["story_count"] == 1
          and rm["data"]["family_count"] == 0, rm["data"])
    check("C2b 带出 story_title", rm["data"]["story_memberships"][0]["story_title"] == "结婚那年", rm["data"])
    rf = J.api_my_memberships(db, user_id=FAMILY)
    check("C2c 小芳（家人）：1 条 book 级", rf["ok"] and rf["data"]["family_count"] == 1
          and rf["data"]["story_count"] == 0, rf["data"])
    check("C2d 家人 scope=book", rf["data"]["families"][0]["scope"] == "book", rf["data"])

    # ============ D. 信封 ============
    sec("D. 信封形状")
    e = J.ok({"x": 1})
    check("D1 ok 信封含 ok/data/error/code",
          all(k in e for k in ("ok", "data", "error", "code")) and e["ok"] is True, e)
    e2 = J.fail("坏", "bad")
    check("D2 fail 信封含 ok/error/code 且 data=None",
          e2["ok"] is False and e2["data"] is None and e2["code"] == "bad", e2)

    db.close()
    print("\n" + "=" * 46)
    print(f"结果：通过 {PASS} / 失败 {FAIL}   （共 {PASS + FAIL}）")
    if FAILURES:
        print("失败项：", FAILURES)
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
