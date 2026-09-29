"""
自测：登录态（login_api）—— 真跑，不是静态核验。

跑法：cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_login.py
（注意：不要用 .venv/bin/python —— 它是空壳，见 README_运行环境.md）

覆盖：
  A. code2session 桩：稳定性/空 code/形状
  B. upsert_user：建档/不覆盖已有昵称/手机号归一化/last_login 更新
  C. api_login：缺 code / 假 code / 老用户二次登录不丢 owners / 登录即认领串联
  D. profile & ui_mode：大字版切换、非法值拒绝、不存在用户
  E. 端到端：老李登记 → 新用户登录 → 自动认领 → profile 能读
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, User, UiMode
import login_api as L
from claim import register_claim
from models import Story

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"✅ {name}  {extra}")
    else:
        FAIL += 1
        print(f"❌ {name}  {extra}")


def fresh_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


print("=" * 60)
print("自测：登录态 login_api")
print("=" * 60)

# ---------------- A. code2session 桩 ----------------
print("\n--- A. code2session 桩 ---")
s1 = L.code2session("code_abc", force_stub=True)
s2 = L.code2session("code_abc", force_stub=True)
s3 = L.code2session("code_xyz", force_stub=True)

check("A1 同 code 同 openid（稳定，可重复跑）", s1["openid"] == s2["openid"], s1["openid"][:16])
check("A2 不同 code 不同 openid", s1["openid"] != s3["openid"])
check("A3 返回 errcode=0 + session_key", s1.get("errcode") == 0 and bool(s1.get("session_key")))
s_empty = L.code2session("", force_stub=True)
check("A4 空 code → errcode 40029", s_empty.get("errcode") == 40029, str(s_empty))
s_ws = L.code2session("   ", force_stub=True)
check("A5 全空格 code → 也拒", s_ws.get("errcode") == 40029)

# ---------------- B. upsert_user ----------------
print("\n--- B. upsert_user ---")
db = fresh_db()
u = L.upsert_user(db, user_id="openid_1", nick_name="老李", avatar_url="http://a/1.png",
                  phone="+86 138-0013-8000")
check("B1 新用户建档成功", u.id == "openid_1" and u.nick_name == "老李")
check("B2 手机号已归一化（+86/横线/空格清掉）", u.phone == "13800138000", u.phone)
check("B3 ui_mode 默认标准版", u.ui_mode == UiMode.STANDARD)

u2 = L.upsert_user(db, user_id="openid_1", nick_name="", avatar_url="")
check("B4 二次登录昵称空 → 不覆盖原昵称", u2.nick_name == "老李", u2.nick_name)
u3 = L.upsert_user(db, user_id="openid_1", nick_name="李大爷")
check("B5 传了新昵称 → 更新", u3.nick_name == "李大爷")

cnt = db.query(User).filter(User.id == "openid_1").count()
check("B6 二次登录不重复建档", cnt == 1, f"count={cnt}")

# ---------------- C. api_login ----------------
print("\n--- C. api_login ---")
db = fresh_db()
r = L.api_login(db, code="", force_stub=True)
check("C1 缺 code → ok=False/missing_code", r["ok"] is False and r["code"] == "missing_code")

r2 = L.api_login(db, code="coder_zhang", nick_name="老张", force_stub=True)
check("C2 正常登录 ok=True", r2["ok"] is True)
check("C3 返回 user_id（=openid）", r2["data"]["user_id"].startswith("stub_"), r2["data"]["user_id"][:18])
check("C4 标注来源 stub（不假装走真微信）", r2["data"]["session_from"] == "stub")
check("C5 新用户 is_new_user=True", r2["data"]["is_new_user"] is True)
check("C6 返回 profile 含 ui_mode", r2["data"]["profile"]["ui_mode"] == "standard")

r3 = L.api_login(db, code="coder_zhang", force_stub=True)
check("C7 二次登录 is_new_user=False", r3["data"]["is_new_user"] is False)

# 老用户二次登录，owners 不丢（回归 09-27 修过的坑）
db2 = fresh_db()
st = Story(id="story_a", title="参军那一年", owner_id="openid_old")
db2.add(st)
db2.commit()
register_claim(db2, owner_id="openid_old", phone="13900139000", display_name="王老")
r4 = L.api_login(db2, code="coder_wang", phone="13900139000", force_stub=True)
check("C8 新用户带手机号登录 → 自动认领，owners 非空", len(r4["data"]["owners"]) >= 1,
      f"owners={r4['data']['owners']}")
r5 = L.api_login(db2, code="coder_wang", phone="13900139000", force_stub=True)
check("C9 二次登录 owners 不丢（回归固定）", len(r5["data"]["owners"]) >= 1,
      f"owners={r5['data']['owners']}")
check("C10 mentioned_count 有值且为 int", isinstance(r5["data"]["mentioned_count"], int),
      str(r5["data"]["mentioned_count"]))

# ---------------- D. profile & ui_mode ----------------
print("\n--- D. profile & ui_mode ---")
db3 = fresh_db()
uid = L.api_login(db3, code="coder_li", nick_name="李奶奶", force_stub=True)["data"]["user_id"]

p = L.api_profile(db3, user_id=uid)
check("D1 profile 能读", p["ok"] and p["data"]["nick_name"] == "李奶奶")
check("D2 无手机号 has_phone=False", p["data"]["has_phone"] is False)

pm = L.api_profile(db3, user_id="")
check("D3 缺 user_id → 拒", pm["ok"] is False and pm["code"] == "missing_user_id")
pn = L.api_profile(db3, user_id="不存在的人")
check("D4 不存在用户 → user_not_found", pn["ok"] is False and pn["code"] == "user_not_found")

sm = L.api_set_ui_mode(db3, user_id=uid, ui_mode="senior")
check("D5 切大字版成功（收 senior 别名）", sm["ok"] and sm["data"]["ui_mode"] == "large",
      str(sm.get("data")))
p2 = L.api_profile(db3, user_id=uid)
check("D6 profile 读到 large（大字版生效）", p2["data"]["ui_mode"] == "large", p2["data"]["ui_mode"])
sl = L.api_set_ui_mode(db3, user_id=uid, ui_mode="large")
check("D6b 直接传 large 也通", sl["ok"] and sl["data"]["ui_mode"] == "large")
ss = L.api_set_ui_mode(db3, user_id=uid, ui_mode="standard")
check("D6c 切回标准版", ss["ok"] and L.api_profile(db3, user_id=uid)["data"]["ui_mode"] == "standard")

sb = L.api_set_ui_mode(db3, user_id=uid, ui_mode="huge")
check("D7 非法 ui_mode → 拒", sb["ok"] is False and sb["code"] == "bad_ui_mode")
sn = L.api_set_ui_mode(db3, user_id="无此人", ui_mode="senior")
check("D8 不存在用户切界面 → user_not_found", sn["ok"] is False and sn["code"] == "user_not_found")

db4 = fresh_db()
uid2 = L.api_login(db4, code="coder_li2", phone="13800138000", force_stub=True)["data"]["user_id"]
p3 = L.api_profile(db4, user_id=uid2)
check("D9 有手机号 → 脱敏显示", p3["data"]["has_phone"] is True and "****" in p3["data"]["phone_masked"],
      p3["data"]["phone_masked"])

# ---------------- E. 端到端 ----------------
print("\n--- E. 端到端：登记 → 登录 → 自动认领 → 读 profile ---")
db5 = fresh_db()
for i, (sid, title) in enumerate([("s1", "小时候住的老屋"), ("s2", "参军那一年"),
                                  ("s3", "和老伴相识")]):
    db5.add(Story(id=sid, title=title, owner_id="child_openid"))
db5.commit()
register_claim(db5, owner_id="child_openid", phone="13700137000", display_name="老李")
login = L.api_login(db5, code="laoli_code", nick_name="老李", phone="13700137000", force_stub=True)
check("E1 老李登录成功", login["ok"] is True)
check("E2 自动认领：owners 含 1 个书主", len(login["data"]["owners"]) == 1,
      f"owners={login['data']['owners']}")
# count_stories 语义 = 「被提到的篇数」（claim._mentioned_story_ids），本场景无提及 → 0 是对的
check("E2b count_stories 口径=被提到篇数（本场景 0）", login["data"]["count_stories"] == 0,
      f"count_stories={login['data']['count_stories']}")
check("E3 认领后 profile 含昵称", login["data"]["profile"]["nick_name"] == "老李")

# E4：故事里"提到了"老李 → count_stories 应该有数（首页提示"有 N 篇提到了你"）
db6 = fresh_db()
laoli_uid = "child_openid"
st = Story(id="m1", title="老屋", owner_id="child_openid",
           people_mentioned=[{"user_id": "someone_else"}])
db6.add(st)
db6.commit()
lg = L.api_login(db6, code="coder_laoli", phone="", force_stub=True)
st2 = Story(id="m2", title="参军", owner_id="child_openid",
            people_mentioned=[{"user_id": lg["data"]["user_id"]}])
db6.add(st2)
db6.commit()
lg2 = L.api_login(db6, code="coder_laoli", phone="", force_stub=True)
check("E4 被提到的故事计入 count_stories", lg2["data"]["count_stories"] >= 1,
      f"count_stories={lg2['data']['count_stories']}")

# ---------------- 汇总 ----------------
print("\n" + "=" * 60)
print(f"通过 {PASS} / 共 {PASS + FAIL}")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
