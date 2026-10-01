#!/usr/bin/env python3.12
"""story_api.py 自测（2026-10-01 新建）
覆盖：建书 / 建故事 / 幂等 / 权限（主人·家人·外人·故事成员）/ 列表过滤 / 详情 / 删除。
"""
import sys, os, uuid
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_story_{uuid.uuid4().hex[:8]}.db"
# models.py 的库地址取自 DATABASE_URL 环境变量（**不是** DB_PATH / ECHOES_DB）。
# 必须在 import models 之前设好，否则 engine 绑死真实库 ./memory_story.db，
# 测试会往生产数据里写脏数据（曾出现 n=4/n=6 与 users.id UNIQUE 冲突）。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import importlib
import models
importlib.reload(models)

from models import SessionLocal, init_db, Story, User, Member, ClaimStatus, GrantVia, Clip, ClipType
import story_api as S

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_owner_laoren"
FAMILY = "openid_family_erzi"
MEMBER = "openid_story_member"
STRANGER = "openid_stranger"

print("=== ① 建书 ===")
r = S.api_create_book(db, owner_id=OWNER, actor_id=OWNER, title="我的一生")
check("建书 ok", r.get("ok"), r)
r = S.api_create_book(db, owner_id=OWNER, actor_id=STRANGER)
check("别人不能替你开书", not r.get("ok") and r.get("code") == "forbidden", r)

print("=== ② 建故事 ===")
r = S.api_create_story(db, owner_id=OWNER, actor_id=OWNER, title="村口那棵树",
                       raw_content="1968年我在村口种下第一棵树", time_raw="七几年")
check("主人建故事 ok", r.get("ok"), r)
sid1 = (r.get("data") or {}).get("story_id")
check("返回 story_id", bool(sid1), r)
check("time_raw 原样保留", (r.get("data") or {}).get("story", {}).get("time_raw") == "七几年", r)

print("=== ③ 幂等：同 story_id 重试不重复建 ===")
r2 = S.api_create_story(db, owner_id=OWNER, actor_id=OWNER, title="xxx", story_id=sid1)
n_story = db.query(Story).filter(Story.owner_id == OWNER).count()
check("幂等返回 is_new=False", r2.get("ok") and (r2.get("data") or {}).get("is_new") is False, r2)
check("库里仍 1 条", n_story == 1, f"n={n_story}")

print("=== ④ 外人写：应拒 ===")
r = S.api_create_story(db, owner_id=OWNER, actor_id=STRANGER, title="偷偷加")
check("外人不能添故事", not r.get("ok") and r.get("code") == "forbidden", r)

print("=== ⑤ 家人写：应允许 ===")
db.add(User(id=FAMILY, nick_name="大儿子")); db.commit()
db.add(Member(id="mem_f1", owner_id=OWNER, user_id=FAMILY,
              granted_via=GrantVia.FAMILY, claim_status=ClaimStatus.CLAIMED)); db.commit()
r = S.api_create_story(db, owner_id=OWNER, actor_id=FAMILY, title="爸爸讲的第二件事")
check("家人能添故事", r.get("ok"), r)
sid2 = (r.get("data") or {}).get("story_id")

print("=== ⑥ 故事成员写：应拒（只能看他那一篇）===")
db.add(Member(id="mem_m1", owner_id=OWNER, user_id=MEMBER,
              granted_via=GrantVia.STORY, story_id=sid1,
              claim_status=ClaimStatus.CLAIMED)); db.commit()
r = S.api_create_story(db, owner_id=OWNER, actor_id=MEMBER, title="我也加一条")
check("故事成员不能添故事", not r.get("ok"), r)

print("=== ⑦ 我的书列表 ===")
r = S.api_my_books(db, user_id=OWNER)
check("主人看到 1 本（自己）", r.get("ok") and (r.get("data") or {}).get("count") >= 1, r)
r = S.api_my_books(db, user_id=FAMILY)
books = (r.get("data") or {}).get("books", [])
roles = {b["role"] for b in books}
check("家人看到自己的书+家人的书", "family" in roles, r)

print("=== ⑧ 故事列表：主人看全本，故事成员只看命中那篇 ===")
r = S.api_list_stories(db, owner_id=OWNER, viewer_id=OWNER)
n_owner = (r.get("data") or {}).get("count")
check("主人看到 2 条", n_owner == 2, f"n={n_owner} {r}")
r = S.api_list_stories(db, owner_id=OWNER, viewer_id=MEMBER)
n_mem = (r.get("data") or {}).get("count")
check("故事成员只看到 1 条", n_mem == 1, f"n={n_mem} {r}")
r = S.api_list_stories(db, owner_id=OWNER, viewer_id=STRANGER)
n_st = (r.get("data") or {}).get("count")
check("外人看到 0 条", n_st == 0, f"n={n_st} {r}")

print("=== ⑨ 故事详情：权限 ===")
r = S.api_get_story(db, story_id=sid1, owner_id=OWNER, viewer_id=OWNER)
check("主人能看详情", r.get("ok"), r)
r = S.api_get_story(db, story_id=sid1, owner_id=OWNER, viewer_id=STRANGER)
check("外人被拒不泄露", not r.get("ok") and r.get("code") == "no_permission", r)
r = S.api_get_story(db, story_id=sid2, owner_id=OWNER, viewer_id=MEMBER)
check("故事成员看别人那篇被拒", not r.get("ok"), r)

print("=== ⑩ owner_id 缺失必须硬拒（防权限退化放行）===")
r = S.api_get_story(db, story_id=sid1, owner_id="", viewer_id=STRANGER)
check("缺 owner_id 报错不放行", not r.get("ok") and r.get("code") == "missing_owner_id", r)
r = S.api_list_stories(db, owner_id="", viewer_id=STRANGER)
check("列表缺 owner_id 报错", not r.get("ok"), r)

print("=== ⑪ 被提及者免授权看本篇 ===")
r = S.api_create_story(db, owner_id=OWNER, actor_id=OWNER, title="提到老李",
                       people_mentioned=[{"name": "老李", "user_id": "openid_laoli"}])
sid3 = (r.get("data") or {}).get("story_id")
r = S.api_get_story(db, story_id=sid3, owner_id=OWNER, viewer_id="openid_laoli")
check("被提及者能看本篇", r.get("ok"), r)
r = S.api_get_story(db, story_id=sid1, owner_id=OWNER, viewer_id="openid_laoli")
check("被提及者看不到别篇", not r.get("ok"), r)

print("=== ⑫ 删除：只有主人本人 ===")
r = S.api_delete_story(db, story_id=sid2, owner_id=OWNER, actor_id=FAMILY)
check("家人不能删", not r.get("ok"), r)
r = S.api_delete_story(db, story_id=sid2, owner_id=OWNER, actor_id=OWNER)
check("主人能删", r.get("ok"), r)
check("删后库里少一条", db.get(Story, sid2) is None, "")

print("=== ⑬ 边界：people_mentioned 非列表应拒 ===")
r = S.api_create_story(db, owner_id=OWNER, actor_id=OWNER, title="x", people_mentioned="不是列表")
check("非列表被拒", not r.get("ok"), r)

print()
print(f"===== story_api 自测：{passed}/{passed+failed} 通过 =====")
if fails: print("失败项：", fails)
try:
    os.remove(TEST_DB)
except OSError:
    pass
raise SystemExit(0 if failed == 0 else 1)
