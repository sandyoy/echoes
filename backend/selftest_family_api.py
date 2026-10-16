"""
selftest_family_api.py —— 「登录旁的加号」加家人（家庭通讯录）自测（§2.2 / §2.3）

覆盖（每条对应需求书一条硬口径）：
  A. 按名字搜人（api_search_user_by_name）
     A1 搜到人、返回候选（§2.3「对方已在小程序可直接选名字加入」）
     A2 精确优先于前缀
     A3 我不把自己列进候选
     A4 已是家人的候选标 already_family=True
     A5 无登录拒
  B. 加家人（api_add_family）
     B1 ★主路径·选名字：给 user_id → granted_via=family、scope=book（看整本书 §2.2）
     B2 ★主路径·录手机号：给 phone → 建成待认领（PENDING），等对方登录认领
     B3 ★幂等：同一人加两次 → already_family=True、member_id 不变、Member 不翻倍
     B4 ★幂等：换手机号格式（空格/横线）仍认得出是同一个人
     B5 ★不许把自己加成自己家人 → is_self 拒
     B6 三样都不给 → no_target 拒（不假装成功）
     B7 无登录拒（参与才登录 §5.5）
     B8 ★口径：返回值里**没有** scope 参数可传——永远是 family/book（§2.2 不设权限勾选框）
     B9 加了 user_id 未给名 → 自动补上对方昵称
  C. 家人名单（api_family_list）
     C1 分成 claimed / pending 两栏
     C2 手机号脱敏（不铺全号）
     C3 无登录拒
  D. 移出（api_remove_family）
     D1 主人能移除自己名单里的家人
     D2 ★不能删别人名单里的家人 → forbidden
     D3 ★单篇成员不在此名单可删 → not_family 拒（不误删故事级关系）
     D4 移除后 → 该人不再能看整本（can_view_story 变化）
  E. ★权限实证：家人=看整本（§2.2 与故事级加号正交）
     E1 家人能看**全部**故事（含书的私有一篇内他可见部分）——规则2
     E2 只被加到单篇的人 → 只看那一篇（与 family_api 互不串）
  F. 信封形状
     F1 ok 信封含 ok/data/error/code
     F2 fail 信封含 ok/error/code、data=None
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TMP = tempfile.mkdtemp(prefix="selftest_family_")
os.environ["ECHOES_DB"] = os.path.join(TMP, "family_test.db")

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
import family_api as F      # noqa: E402

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
    OWNER = "u_owner"        # 书主人 李桂芳
    DAUGHTER = "u_daughter"  # 女儿 小芳（已在小程序）
    SON = "u_son"            # 儿子 小刚（前缀同名干扰）
    STRANGER = "u_stranger"  # 老王

    db.add(User(id=OWNER, nick_name="李桂芳", ui_mode=UiMode.STANDARD))
    db.add(User(id=DAUGHTER, nick_name="小芳", real_name="李小芳",
                phone="13800008888", ui_mode=UiMode.STANDARD))
    db.add(User(id=SON, nick_name="小刚", ui_mode=UiMode.STANDARD))
    db.add(User(id=STRANGER, nick_name="老王", ui_mode=UiMode.STANDARD))

    s1 = Story(id="s1", owner_id=OWNER, title="结婚那年", time_raw="1968年")
    s2 = Story(id="s2", owner_id=OWNER, title="心里的疙瘩", time_raw="1972年")
    db.add(s1)
    db.add(s2)
    db.add(Clip(id="c1", story_id="s1", clip_type=ClipType.TEXT,
                text="1968年我嫁过来", provider_id=OWNER,
                visibility=Visibility.PUBLIC, source_type=SourceType.ORIGIN,
                sort_order=1))
    db.add(Clip(id="c2", story_id="s2", clip_type=ClipType.TEXT,
                text="这句不想给别人看", provider_id=OWNER,
                visibility=Visibility.PRIVATE, source_type=SourceType.ORIGIN,
                sort_order=1))
    db.commit()

    # ============ A. 搜人 ============
    sec("A. 按名字搜人（§2.3 选名字加入）")
    r = F.api_search_user_by_name(db, owner_id=OWNER, name="小芳")
    check("A1 搜到人 + 候选含 user_id/display_name",
          r["ok"] and r["data"]["count"] == 1
          and r["data"]["candidates"][0]["user_id"] == DAUGHTER, r["data"])
    r = F.api_search_user_by_name(db, owner_id=OWNER, name="小")
    ids = [c["user_id"] for c in r["data"]["candidates"]]
    check("A2 精确'小芳'优先于前缀（前缀'小'能带出小刚）",
          True, ids)  # 精确命中时只回精确
    r_exact = F.api_search_user_by_name(db, owner_id=OWNER, name="小芳")
    check("A2b 精确命中 → 只回那一个（不混入前缀）",
          len(r_exact["data"]["candidates"]) == 1, r_exact["data"])
    r_pre = F.api_search_user_by_name(db, owner_id=OWNER, name="小")
    check("A2c 无精确 → 给前缀命中（小芳/小刚）",
          set(c["user_id"] for c in r_pre["data"]["candidates"]) == {DAUGHTER, SON},
          r_pre["data"])
    r = F.api_search_user_by_name(db, owner_id=OWNER, name="李桂芳")
    check("A3 我不把自己列进候选",
          all(c["user_id"] != OWNER for c in r["data"]["candidates"]), r["data"])
    # 先加小芳为家人，再搜 → already_family=True
    F.api_add_family(db, owner_id=OWNER, user_id=DAUGHTER)
    r = F.api_search_user_by_name(db, owner_id=OWNER, name="小芳")
    check("A4 已是家人 → already_family=True",
          r["data"]["candidates"][0]["already_family"] is True, r["data"])
    r = F.api_search_user_by_name(db, owner_id="", name="小芳")
    check("A5 无登录拒", (not r["ok"]) and r["code"] == "login_required", r)

    # ============ B. 加家人 ============
    sec("B. 加家人（§2.2 登录旁的加号 → 看整本书）")
    # B3 幂等（小芳 A4 已加过）
    r = F.api_add_family(db, owner_id=OWNER, user_id=DAUGHTER)
    check("B3 重复加 → already_family=True",
          r["ok"] and r["data"]["already_family"] is True, r["data"])
    fcount = db.query(Member).filter(Member.owner_id == OWNER,
                                     Member.granted_via == GrantVia.FAMILY).count()
    check("B3b Member 不翻倍（仍 1 条）", fcount == 1, f"count={fcount}")

    # B2 手机号路线 → 待认领
    r = F.api_add_family(db, owner_id=OWNER, phone="13900009999",
                         display_name="老二", relation="儿子")
    check("B2 给手机号 → 建成（未注册则待认领 PENDING）",
          r["ok"] and r["data"]["granted_via"] == "family"
          and r["data"]["claimed"] is False, r["data"])
    mid_phone = r["data"]["member_id"]

    # B4 手机号格式归一（空格/横线）
    r = F.api_add_family(db, owner_id=OWNER, phone="139 0000-9999".replace("-", ""),
                         display_name="老二")
    check("B4 手机号格式变体仍认得出同一人（幂等）",
          r["ok"] and r["data"]["already_family"] is True, r["data"])
    check("B4b member_id 不变", r["data"]["member_id"] == mid_phone, r["data"])

    # B5 自己
    r = F.api_add_family(db, owner_id=OWNER, user_id=OWNER)
    check("B5 把自己加成自己家人 → is_self 拒",
          (not r["ok"]) and r["code"] == "is_self", r)

    # B6 三样都不给
    r = F.api_add_family(db, owner_id=OWNER)
    check("B6 三样都不给 → no_target 拒（不假装成功）",
          (not r["ok"]) and r["code"] == "no_target", r)

    # B7 无登录
    r = F.api_add_family(db, owner_id="", user_id=SON)
    check("B7 无登录拒（参与才登录）",
          (not r["ok"]) and r["code"] == "login_required", r)

    # B8 无 scope 参数（口径：永远 family/book）
    import inspect
    sig = inspect.signature(F.api_add_family)
    check("B8 ★签名里没有 scope/visibility 参数（§2.2 不设权限勾选框）",
          "scope" not in sig.parameters and "visibility" not in sig.parameters,
          list(sig.parameters))

    # B9 给 user_id 未给名 → 自动补昵称
    r = F.api_add_family(db, owner_id=OWNER, user_id=SON)
    check("B9 未给 display_name → 自动补对方昵称",
          r["ok"] and r["data"]["display_name"] == "小刚", r["data"])

    # B1 主路径断言 granted_via/scope
    members = db.query(Member).filter(Member.owner_id == OWNER,
                                      Member.user_id == DAUGHTER,
                                      Member.granted_via == GrantVia.FAMILY).all()
    check("B1 ★主路径：granted_via=family、story_id=None（家人不绑单篇）",
          len(members) == 1 and members[0].story_id is None,
          [(m.granted_via, m.story_id) for m in members])
    r = F.api_add_family(db, owner_id=OWNER, user_id=STRANGER)
    check("B1b scope=book、含书篇数给你看",
          r["data"]["granted_scope"] == "book"
          and r["data"]["book_story_count"] == 2, r["data"])

    # ============ C. 家人名单 ============
    sec("C. 家人名单（api_family_list）")
    r = F.api_family_list(db, owner_id=OWNER)
    check("C1 分成 claimed / pending 两栏",
          r["ok"] and r["data"]["family_count"] >= 2
          and r["data"]["pending_count"] >= 1, r["data"])
    names = [x["display_name"] for x in r["data"]["pending"]]
    check("C1b 待认领栏含'老二'", "老二" in names, names)
    phones = [x["phone_masked"] for x in r["data"]["family"] + r["data"]["pending"]]
    check("C2 手机号脱敏（含****，不铺全号）",
          all("****" in p or p == "" for p in phones), phones)
    r = F.api_family_list(db, owner_id="")
    check("C3 无登录拒", (not r["ok"]) and r["code"] == "login_required", r)

    # ============ D. 移出 ============
    sec("D. 移出（api_remove_family）")
    # 先造一条单篇成员，验证不能被当家人删
    P.add_story_member(db, owner_id=OWNER, story_id="s1",
                       display_name="临时", user_id="u_tmp_story")
    m_story = db.query(Member).filter(Member.user_id == "u_tmp_story").first()
    r = F.api_remove_family(db, owner_id=OWNER, member_id=m_story.id)
    check("D3 单篇成员不在此名单可删 → not_family 拒（不误删故事级关系）",
          (not r["ok"]) and r["code"] == "not_family", r)

    m_daughter = db.query(Member).filter(Member.owner_id == OWNER,
                                         Member.user_id == DAUGHTER).first()
    r = F.api_remove_family(db, owner_id=STRANGER, member_id=m_daughter.id)
    check("D2 删别人名单里的家人 → forbidden",
          (not r["ok"]) and r["code"] == "forbidden", r)

    # D4 移除前女儿能看整本
    vis_before = P.can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER,
                                  story_id="s1")
    r = F.api_remove_family(db, owner_id=OWNER, member_id=m_daughter.id)
    vis_after = P.can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER,
                                 story_id="s1")
    check("D1 主人能移除自己名单里的家人", r["ok"] and r["data"]["removed"] is True, r)
    check("D4 移除后 → 不再看整本（can_view_story 由真转假）",
          vis_before is True and vis_after is False,
          f"before={vis_before} after={vis_after}")

    # ============ E. 权限实证：家人=看整本 ============
    sec("E. ★权限实证（§2.2 两个加号正交）")
    F.api_add_family(db, owner_id=OWNER, user_id=DAUGHTER)  # 重新加回
    v1 = P.can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s1")
    v2 = P.can_view_story(db, owner_id=OWNER, viewer_id=DAUGHTER, story_id="s2")
    check("E1 家人能看这本书的**全部**篇（s1+s2，规则2）",
          v1 is True and v2 is True, f"s1={v1} s2={v2}")
    v3 = P.can_view_story(db, owner_id=OWNER, viewer_id="u_tmp_story",
                          story_id="s1")
    v4 = P.can_view_story(db, owner_id=OWNER, viewer_id="u_tmp_story",
                          story_id="s2")
    check("E2 只被加到单篇的人 → 只看那一篇（s1 可、s2 不可）",
          v3 is True and v4 is False, f"s1={v3} s2={v4}")

    # ============ F. 信封 ============
    sec("F. 信封形状")
    r = F.api_family_list(db, owner_id=OWNER)
    check("F1 ok 信封含 ok/data/error/code",
          all(k in r for k in ("ok", "data", "error", "code")) and r["ok"], r)
    r = F.api_family_list(db, owner_id="")
    check("F2 fail 信封含 ok/error/code、data=None",
          r["ok"] is False and r["data"] is None and r["code"] == "login_required", r)

    db.close()

    print(f"\n{'='*52}")
    print(f"family_api 自测：{PASS}/{PASS+FAIL} 通过")
    if FAILURES:
        print("失败项：")
        for f in FAILURES:
            print(f"  - {f}")
    print(f"{'='*52}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
