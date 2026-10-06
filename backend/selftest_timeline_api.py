#!/usr/bin/env python3.12
"""timeline_api.py 自测（2026-10-06 新建，第2期「能排对」）
覆盖：
  ① 分节：同时间点挂多故事（一节 N 卡）
  ② 【时间待定】单列、不猜、不参与排序
  ③ 精度不影响排序（模糊/年/月混排仍按 sort_key）
  ④ 模糊原样保留（time_label 不得被本层重构）
  ⑤ ★改时间：用户手动改后 time_confirmed_by_user=True，自动归位不得再覆盖
  ⑥ 改时间越权（故事成员不能改）
  ⑦ 权限：主人/家人看整本，故事成员只看命中那篇，外人空轴
  ⑧ 锚点反推：同书锚点故事 → 让「我八岁那年」能落地
  ⑨ 信封形状 + node 文案取「被确认过的」优先
"""
import sys, os, uuid
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_timeline_{uuid.uuid4().hex[:8]}.db"
# ⚠️ 铁律（10-01 踩过）：库地址取自 DATABASE_URL，必须在 import models 之前设，
#    否则 engine 绑死真实库 ./memory_story.db，测试会污染生产数据。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import importlib
import models
importlib.reload(models)

from models import (SessionLocal, init_db, Story, Member, ClaimStatus, GrantVia,
                    TimePrecision, Clip, ClipType)
import timeline_api as T

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_owner"
FAMILY = "openid_family"
MEMBER = "openid_member"
STRANGER = "openid_stranger"


def mk(story_id, *, time_raw="", time_label="", sort_key=0, precision=TimePrecision.UNKNOWN,
       confirmed=False, title="", summary="", owner=OWNER):
    s = Story(id=story_id, owner_id=owner, title=title, summary=summary,
              time_raw=time_raw, time_label=time_label, time_sort_key=sort_key,
              time_precision=precision, time_confirmed_by_user=confirmed)
    db.add(s); db.commit()
    return s


print("=== ① 分节：同一时间点挂多个故事 ===")
mk("s_1979_a", time_raw="1979年", time_label="1979年", sort_key=1979,
   precision=TimePrecision.YEAR, title="分到第一套房")
mk("s_1979_b", time_raw="1979年", time_label="1979年", sort_key=1979,
   precision=TimePrecision.YEAR, title="女儿出生")
mk("s_1968", time_raw="1968年", time_label="1968年", sort_key=1968,
   precision=TimePrecision.YEAR, title="下乡那年")
r = T.api_get_timeline(db, owner_id=OWNER, viewer_id=OWNER)
check("取时间轴 ok", r.get("ok"), r)
nodes = (r.get("data") or {}).get("nodes") or []
check("分了2个时间节", len(nodes) == 2, nodes)
n1979 = [n for n in nodes if n["time_sort_key"] == 1979]
check("1979节存在", len(n1979) == 1, nodes)
check("1979节挂2张卡", n1979 and n1979[0]["count"] == 2, n1979)
check("节按时间正序", [n["time_sort_key"] for n in nodes] == [1968, 1979], nodes)

print("=== ② 【时间待定】单列、不猜、不排序 ===")
mk("s_unknown", time_raw="那年水来得快", time_label="", sort_key=0,
   precision=TimePrecision.UNKNOWN, title="大水")
r = T.api_get_timeline(db, owner_id=OWNER, viewer_id=OWNER)
data = r.get("data") or {}
check("待定进 pending 而非 nodes", any(p["story_id"] == "s_unknown" for p in data.get("pending", [])), data.get("pending"))
check("待定不混进 nodes", all(not any(c["story_id"] == "s_unknown" for c in n["stories"]) for n in data["nodes"]), data["nodes"])
check("待定 label 兜底为『时间待定』",
      all(p["time_label"] == "时间待定" for p in data["pending"] if p["story_id"] == "s_unknown"),
      data.get("pending"))
check("stats 计数对", data["stats"]["total"] == 4 and data["stats"]["placed"] == 3
      and data["stats"]["pending"] == 1 and data["stats"]["node_count"] == 2, data["stats"])

print("=== ③ 精度不影响排序（模糊年在年后仍按 sort_key 排） ===")
mk("s_fuzzy", time_raw="七几年那场大水", time_label="1970年代（老人说的）",
   sort_key=1970, precision=TimePrecision.FUZZY, title="七几年")
r = T.api_get_timeline(db, owner_id=OWNER, viewer_id=OWNER)
keys = [n["time_sort_key"] for n in (r["data"]["nodes"])]
check("模糊年 1970 插在 1968 与 1979 之间", keys == [1968, 1970, 1979], keys)

print("=== ④ 模糊原样保留（本层不得重构 label） ===")
n1970 = [n for n in r["data"]["nodes"] if n["time_sort_key"] == 1970][0]
check("模糊节文案原样（带『（老人说的）』）",
      n1970["label"] == "1970年代（老人说的）", n1970["label"])

print("=== ⑤ ★改时间：手改后自动归位不得覆盖 ===")
r = T.api_set_story_time(db, story_id="s_fuzzy", actor_id=OWNER, new_time_text="1975年3月")
check("改时间 ok", r.get("ok"), r)
check("改为 1975", (r["data"]["time"]["time_sort_key"]) == 1975, r["data"]["time"])
check("落 time_confirmed_by_user=True", r["data"]["time"]["time_confirmed_by_user"] is True, r["data"]["time"])
check("placed=True", r["data"]["placed"] is True, r["data"])
# 手动改过的，自动归位必须跳过
r2 = T.auto_place_story(db, story_id="s_fuzzy")
check("自动归位 skip（不覆盖手改）", r2["data"]["skipped"] is True, r2["data"])
s = db.query(Story).filter(Story.id == "s_fuzzy").first()
check("库里 sort_key 仍为 1975（未被覆盖）", s.time_sort_key == 1975, s.time_sort_key)
check("库里 label 仍为 1975年3月", s.time_label == "1975年3月", s.time_label)

print("=== ⑥ 改时间越权 ===")
r = T.api_set_story_time(db, story_id="s_1968", actor_id=STRANGER, new_time_text="1960年")
check("外人不能改", not r.get("ok") and r.get("code") == "forbidden", r)
r = T.api_set_story_time(db, story_id="s_1968", actor_id=OWNER, new_time_text="")
check("空时间被拒", not r.get("ok") and r.get("code") == "bad_request", r)
r = T.api_set_story_time(db, story_id="s_nonexistent", actor_id=OWNER, new_time_text="1960年")
check("不存在的故事报 not_found", not r.get("ok") and r.get("code") == "not_found", r)

print("=== ⑦ 权限：家人看整本 / 故事成员看单篇 / 外人空轴 ===")
db.add(Member(id="m_fam", owner_id=OWNER, user_id=FAMILY,
              granted_via=GrantVia.FAMILY, claim_status=ClaimStatus.CLAIMED))
db.add(Member(id="m_st", owner_id=OWNER, user_id=MEMBER,
              granted_via=GrantVia.STORY, claim_status=ClaimStatus.CLAIMED,
              story_id="s_1968"))
db.commit()
rf = T.api_get_timeline(db, owner_id=OWNER, viewer_id=FAMILY)
check("家人能看到全部5条", rf["data"]["stats"]["total"] == 5, rf["data"]["stats"])
rm = T.api_get_timeline(db, owner_id=OWNER, viewer_id=MEMBER)
check("故事成员只看1条（命中那篇）", rm["data"]["stats"]["total"] == 1, rm["data"]["stats"])
check("故事成员看到的就是 s_1968",
      rm["data"]["nodes"] and rm["data"]["nodes"][0]["stories"][0]["story_id"] == "s_1968",
      rm["data"]["nodes"])
rs = T.api_get_timeline(db, owner_id=OWNER, viewer_id=STRANGER)
check("外人空轴（不报错）", rs.get("ok") and rs["data"]["stats"]["total"] == 0, rs)

print("=== ⑧ 锚点反推：同书锚点 → 「我八岁那年」落地 ===")
db.add(Story(id="s_birth", owner_id=OWNER, title="我1950年出生的",
             time_raw="1950年", time_label="1950年", time_sort_key=1950,
             time_precision=TimePrecision.YEAR))
db.add(Story(id="s_age8", owner_id=OWNER, title="我八岁那年上小学"))
db.commit()
r = T.auto_place_story(db, story_id="s_age8")
check("锚点反推 → 1958", r["data"]["time"]["time_sort_key"] == 1958, r["data"])
s = db.query(Story).filter(Story.id == "s_age8").first()
check("落库 sort_key=1958", s.time_sort_key == 1958, s.time_sort_key)
check("标注方法=人生锚点", s.time_extract_method == "人生锚点", s.time_extract_method)

print("=== ⑨ 信封 / node 文案优先级 / 待定区接口 ===")
r = T.api_get_timeline(db, owner_id="", viewer_id=OWNER)
check("缺参报 bad_request", not r.get("ok") and r.get("code") == "bad_request", r)
r = T.api_timeline_pending(db, owner_id=OWNER, viewer_id=OWNER)
check("待定区接口 ok", r.get("ok"), r)
check("待定区 count 与 pending 一致",
      r["data"]["count"] == len(r["data"]["pending"]), r["data"])
# node 文案优先取「被确认过的」
mk("s_conf_a", time_raw="1980年代", time_label="1980年代（老人说的）", sort_key=1980,
   precision=TimePrecision.FUZZY, title="A")
mk("s_conf_b", time_raw="1980年5月", time_label="1980年5月", sort_key=1980,
   precision=TimePrecision.MONTH, confirmed=True, title="B")
r = T.api_get_timeline(db, owner_id=OWNER, viewer_id=OWNER)
n1980 = [n for n in r["data"]["nodes"] if n["time_sort_key"] == 1980][0]
check("节点文案取被确认过的那条", n1980["label"] == "1980年5月", n1980["label"])
check("节点挂2张卡", n1980["count"] == 2, n1980)

print("\n" + "=" * 56)
print(f"结果：{passed} passed / {failed} failed   合计 {passed + failed}")
if fails:
    print("FAILED:", fails)
print("=" * 56)
sys.exit(0 if failed == 0 else 1)
