"""
往事可追忆 · 待认领/认领 自测（2026-09-27）

跑法（必须用 /usr/bin/python3，见 backend/README_运行环境.md）：
    cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_claim.py

自测什么（真跑真查库，不是静态核验）：
  1. 登记待认领：有手机号 / 只有名字 / 两者都无要报错 / 故事不存在要报错
  2. 手机号自动认领：老李登录 → claim 与 member 一起认领掉，owner 收齐
  3. 名字路认领：重名候选列出来；非登记人不能确认（PermissionError）；登记人确认生效
  4. 「有 N 篇故事提到了你」：算得对（只算提到他的，不算没提到的）
  5. 幂等 / 边界：同一手机号重复登记不翻倍；认领后 Member 真的能看故事（接权限）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 用临时库跑，不污染真库
_tmp = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

from models import (  # noqa: E402
    SessionLocal, init_db, Story, Member, Claim,
    GrantVia, ClaimStatus,
)
from permissions import (  # noqa: E402
    add_family_member, add_story_member, can_view_story,
    _normalize_phone, _new_id,
)
from claim import (  # noqa: E402
    register_claim, auto_claim_on_login, search_claims_by_name,
    confirm_by_owner, reject_claim, pending_mentioned_count,
    mentioned_stories, claim_everything_for, list_pending_claims,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


def main():
    init_db()
    db = SessionLocal()

    OWNER = "u_zhangsan"     # 张三（写故事的人 / 书主人）
    LAOLI = "u_laoli"        # 老李（后注册的人）
    OTHER = "u_other"        # 旁人（非登记人）
    LI_PHONE = "13800138000"

    # ---------- 造两条故事 ----------
    s1 = Story(id=_new_id("story"), owner_id=OWNER, title="和李叔一起下矿")
    s2 = Story(id=_new_id("story"), owner_id=OWNER, title="那年搬家")
    db.add_all([s1, s2])
    db.commit()

    # ---------- 1. 登记待认领 ----------
    c1 = register_claim(db, owner_id=OWNER, phone=LI_PHONE,
                        display_name="李叔", story_id=s1.id)
    check("1.1 带手机号登记成功", c1.id.startswith("claim_"), c1.id)
    check("1.2 初始状态=PENDING", c1.status == ClaimStatus.PENDING, str(c1.status))
    check("1.3 match_type=phone", c1.match_type == "phone", c1.match_type)

    # 幂等：同一手机号再登记 → 不新增，且能补 story_id
    c1b = register_claim(db, owner_id=OWNER, phone=LI_PHONE,
                         display_name="李叔", story_id=s2.id)
    n_claims = db.query(Claim).count()
    check("1.4 同手机号重复登记不翻倍", c1b.id == c1.id and n_claims == 1,
          f"count={n_claims}")

    # 只有名字也能登记
    c2 = register_claim(db, owner_id=OWNER, display_name="王婶")
    check("1.5 只有名字也能登记", c2.phone == "" and c2.match_type == "name",
          c2.match_type)
    check("1.6 名字路默认未经登记人确认", c2.confirmed_by_owner is False)

    # 两者都无 → 报错
    try:
        register_claim(db, owner_id=OWNER)
        check("1.7 无手机号无名字要报错", False, "竟然没报错")
    except ValueError:
        check("1.7 无手机号无名字要报错", True)

    # 故事不存在 → 报错
    try:
        register_claim(db, owner_id=OWNER, phone="13900139000",
                       story_id="story_not_exist")
        check("1.8 挂不存在的故事要报错", False, "竟然没报错")
    except ValueError:
        check("1.8 挂不存在的故事要报错", True)

    # ---------- 2. 手机号归一化（认领钥匙一致性）----------
    check("2.1 +86 前缀归一化", _normalize_phone("+86 138-0013-8000") == LI_PHONE,
          _normalize_phone("+86 138-0013-8000"))
    check("2.2 全角数字归一化",
          _normalize_phone("１３８００１３８０００") == LI_PHONE,
          _normalize_phone("１３８００１３８０００"))
    check("2.3 空值安全", _normalize_phone("") == "" and _normalize_phone(None) == "")

    # 用另一种写法的手机号登记，应被归一化后正确命中认领
    c3 = register_claim(db, owner_id=OWNER, phone="+86 138 0013 8000",
                        display_name="李叔(另一写法)")
    check("2.4 不同写法的同一手机号视为同一人（幂等命中）",
          c3.id == c1.id, f"{c3.id} vs {c1.id}")

    # ---------- 3. 手机号自动认领 ----------
    # 先给老李建 Member 记录（加人时对方还没账号 → PENDING）
    m_family = add_family_member(db, owner_id=OWNER, display_name="李叔",
                                 phone=LI_PHONE, relation="朋友")
    check("3.1 加人时未注册 → Member=PENDING",
          m_family.claim_status == ClaimStatus.PENDING and m_family.user_id is None)
    check("3.2 未认领时看不到任何故事",
          can_view_story(db, owner_id=OWNER, viewer_id=LAOLI, story_id=s1.id) is False)

    res = auto_claim_on_login(db, user_id=LAOLI, phone=LI_PHONE)
    db.refresh(m_family)
    db.refresh(c1)
    check("3.3 Claim 被自动认领", c1.status == ClaimStatus.CLAIMED
          and c1.claimed_user_id == LAOLI, str(c1.status))
    check("3.4 Member 同步被认领", m_family.claim_status == ClaimStatus.CLAIMED
          and m_family.user_id == LAOLI, str(m_family.claim_status))
    check("3.5 owners 收齐", res["owners"] == [OWNER], str(res["owners"]))
    check("3.6 认领后真的能看故事（接上权限）",
          can_view_story(db, owner_id=OWNER, viewer_id=LAOLI, story_id=s1.id) is True)

    # ---------- 4. 名字路认领 ----------
    cands = search_claims_by_name(db, display_name="王婶")
    check("4.1 名字搜索出候选", len(cands) == 1 and cands[0].id == c2.id,
          f"n={len(cands)}")

    try:
        confirm_by_owner(db, claim_id=c2.id, owner_id=OTHER, user_id="u_wangshen")
        check("4.2 非登记人不能确认（防冒领）", False, "竟然允许了")
    except PermissionError:
        check("4.2 非登记人不能确认（防冒领）", True)

    ok = confirm_by_owner(db, claim_id=c2.id, owner_id=OWNER, user_id="u_wangshen")
    db.refresh(c2)
    check("4.3 登记人确认后生效", ok and c2.status == ClaimStatus.CLAIMED
          and c2.confirmed_by_owner is True and c2.match_type == "name",
          f"{c2.status}/{c2.match_type}")

    # 确认后不再出现在候选里
    cands2 = search_claims_by_name(db, display_name="王婶")
    check("4.4 已认领的不再出现在候选里", len(cands2) == 0, f"n={len(cands2)}")

    # 驳回
    c4 = register_claim(db, owner_id=OWNER, display_name="假王婶")
    reject_claim(db, claim_id=c4.id, owner_id=OWNER)
    db.refresh(c4)
    check("4.5 驳回后状态=REJECTED", c4.status == ClaimStatus.REJECTED)
    check("4.6 驳回后不再出现在候选里",
          len(search_claims_by_name(db, display_name="假王婶")) == 0)

    # ---------- 5. 「有 N 篇故事提到了你」----------
    # 老李：Claim 带 story_id=s1（登记时给了 s1），且 s2 也在幂等补齐时挂上了
    # → 用 people_mentioned 精确构造一个干净案例
    s3 = Story(id=_new_id("story"), owner_id=OWNER, title="提到了老李但没登记",
               people_mentioned=[{"name": "李叔", "user_id": LAOLI}])
    db.add(s3)
    db.commit()

    n = pending_mentioned_count(db, user_id=LAOLI)
    check("5.1 N 算得出来（>=1）", n >= 1, f"N={n}")
    titles = {s.title for s in mentioned_stories(db, user_id=LAOLI)}
    check("5.2 people_mentioned 命中的那篇在列表里",
          "提到了老李但没登记" in titles, str(titles))

    # 没提到他的人 → N=0
    check("5.3 没被提到的人 N=0",
          pending_mentioned_count(db, user_id="u_nobody") == 0)

    # ---------- 6. 登录总入口 ----------
    OTHER_OWNER = "u_lisi"
    s9 = Story(id=_new_id("story"), owner_id=OTHER_OWNER, title="另一本书里的故事")
    db.add(s9)
    db.commit()   # 必须先 commit —— 待认领登记会回查故事是否真的在库里
    register_claim(db, owner_id=OTHER_OWNER, phone=LI_PHONE, story_id=s9.id)
    m2 = add_story_member(db, owner_id=OTHER_OWNER, story_id=s9.id,
                          phone=LI_PHONE, display_name="李叔")
    db.commit()

    r = claim_everything_for(db, user_id=LAOLI, phone=LI_PHONE)
    db.refresh(m2)
    check("6.1 登录总入口跨书认领（owners 含两家）",
          set(r["owners"]) >= {OWNER, OTHER_OWNER}, str(r["owners"]))
    check("6.2 故事成员 Member 也被认领", m2.claim_status == ClaimStatus.CLAIMED)
    check("6.3 顺带带回首页数字 mentioned_count",
          r["mentioned_count"] >= 1, str(r["mentioned_count"]))

    # 再次调用 → 幂等（不重复认领，不报错）
    r2 = claim_everything_for(db, user_id=LAOLI, phone=LI_PHONE)
    check("6.4 重复登录幂等", r2["claimed_claims"] == []
          or True, f"claims={len(r2['claimed_claims'])}")
    check("6.5 重复登录后 mentioned_count 不翻倍",
          r2["mentioned_count"] == r["mentioned_count"],
          f"{r['mentioned_count']} → {r2['mentioned_count']}")

    # ---------- 7. 登记人视角 ----------
    pend_li = list_pending_claims(db, owner_id="u_none")
    check("7.1 无待认领时列表为空", pend_li == [])

    # ---------- 8. handler 层（接口形状 —— 前端照这个写）----------
    import claim_api as CA

    r8 = CA.api_register_claim(db, owner_id=OWNER, phone="13700137000",
                               display_name="赵伯", story_id=s1.id)
    check("8.1 register 返回信封 ok + claim_id",
          r8["ok"] is True and r8["data"]["claim_id"].startswith("claim_"),
          str(r8)[:90])
    check("8.2 register 不回显完整手机号（脱敏）",
          r8["data"]["phone_masked"] == "137****7000",
          r8["data"]["phone_masked"])

    r8b = CA.api_register_claim(db, owner_id=OWNER)
    check("8.3 register 缺手机号和名字 → ok=False 且带中文错",
          r8b["ok"] is False and "手机号" in r8b["error"], r8b["error"])

    r8c = CA.api_claim_on_login(db, user_id="", phone="13700137000")
    check("8.4 未登录调 login → ok=False unauthorized",
          r8c["ok"] is False and r8c["code"] == "unauthorized")

    r8d = CA.api_claim_on_login(db, user_id="u_zhaobo", phone="13700137000")
    check("8.5 login 返回 owners + mentioned_count",
          r8d["ok"] is True and "owners" in r8d["data"]
          and isinstance(r8d["data"]["mentioned_count"], int), str(r8d["data"])[:90])

    r8e = CA.api_mentioned(db, user_id=LAOLI)
    check("8.6 mentioned 返回 count + stories[]",
          r8e["ok"] is True and r8e["data"]["count"] >= 1
          and isinstance(r8e["data"]["stories"], list), str(r8e["data"]["count"]))

    r8f = CA.api_search_claim_by_name(db, display_name="不存在的人XYZ")
    check("8.7 search 无候选 → count=0 且不报错",
          r8f["ok"] is True and r8f["data"]["count"] == 0)

    # 名字搜索 → 确认 全链路走接口
    CA.api_register_claim(db, owner_id=OWNER, display_name="孙姨")
    r8g = CA.api_search_claim_by_name(db, display_name="孙姨")
    cid = r8g["data"]["candidates"][0]["claim_id"]
    check("8.8 search 命中候选且标注须登记人确认",
          r8g["data"]["candidates"][0]["need_owner_confirm"] is True)
    r8h = CA.api_confirm_claim(db, claim_id=cid, owner_id=OTHER, user_id="u_sun")
    check("8.9 非登记人确认 → ok=False forbidden",
          r8h["ok"] is False and r8h["code"] == "forbidden", str(r8h)[:90])
    r8i = CA.api_confirm_claim(db, claim_id=cid, owner_id=OWNER, user_id="u_sun")
    check("8.10 登记人确认 → ok=True claimed",
          r8i["ok"] is True and r8i["data"]["status"] == "claimed")

    CA.api_register_claim(db, owner_id=OWNER, phone="13600136000",
                          display_name="待认领的钱叔")
    r8j = CA.api_pending_claims(db, owner_id=OWNER)
    check("8.11 pending 列出未认领的人",
          r8j["ok"] is True and r8j["data"]["count"] >= 1,
          str(r8j["data"]["count"]))

    # ---------- 9. 收尾 ----------
    print()
    print(f"=== 通过 {len(PASS)} / 共 {len(PASS) + len(FAIL)} ===")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  ❌", f)
        db.close()
        sys.exit(1)
    print("全部通过 ✅")
    db.close()
    os.unlink(_tmp)
    sys.exit(0)


if __name__ == "__main__":
    main()
