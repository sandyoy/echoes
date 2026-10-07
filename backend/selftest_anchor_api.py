#!/usr/bin/env python3.12
"""anchor_api.py 自测（2026-10-07 新建，第2期 §5.3「人生锚点表」）
覆盖：
  ① 采集：扫正文（不只标题）能采到「我1950年出生」「1972年结的婚」
  ② 采集：扫**语音转写**（Clip.transcript）也能采到锚点
  ③ 落库：harvest 后 LifeAnchor 表真有行，且 get_anchors 返回正确键名
  ④ 幂等：重复 harvest 不产生脏行、结果一致
  ⑤ 不瞎猜：无锚点陈述 → 不写任何锚点（表里 0 行）
  ⑥ 用户确认优先：confirmed=True 的锚点，harvest 不得覆盖
  ⑦ 反推联动：★有锚点后「我八岁那年」能落地；无锚点则【时间待定】
  ⑧ 手工 upsert：能纠正年份并置 confirmed=True；非法年份被拒
  ⑨ 端到端：story 正文里写锚点 → auto_place_story 真把另一条「嫁过来第二年」排对
"""
import sys, os, uuid
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_anchor_{uuid.uuid4().hex[:8]}.db"
# ⚠️ 铁律（10-01 踩过）：库地址取自 DATABASE_URL，必须在 import models 之前设，
#    否则 engine 绑死真实库 ./memory_story.db，测试会污染生产数据。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models
from models import (SessionLocal, init_db, Story, Clip, ClipType, LifeAnchor,
                    TimePrecision)
import anchor_api as A
import timeline_api as T
import timeline

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_anchor_owner"
OTHER = "openid_anchor_other"


def mk_story(story_id, *, owner=OWNER, title="", summary="", raw_content="",
             polished="", time_raw="", time_label=""):
    s = Story(id=story_id, owner_id=owner, title=title, summary=summary,
              raw_content=raw_content, polished_content=polished,
              time_raw=time_raw, time_label=time_label,
              time_precision=TimePrecision.UNKNOWN, time_sort_key=0)
    db.add(s); db.commit()
    return s


def mk_clip(clip_id, story_id, *, text="", transcript=""):
    c = Clip(id=clip_id, story_id=story_id, clip_type=ClipType.AUDIO,
             text=text, transcript=transcript)
    db.add(c); db.commit()
    return c


print("=" * 62)
print("往事可追忆 · 人生锚点表 接口 · 自测")
print("=" * 62)
print(f"临时库：{TEST_DB}")

# ------------------------------------------------------------
print("\n【① 采集：正文里的锚点（不只标题）】")
mk_story("s_birth", title="我的来历",
         raw_content="我是1950年生的，老家在山东。")
r = A.harvest_anchors(db, owner_id=OWNER)
check("harvest 成功", r["ok"], str(r))
check("从正文采到 birth_year", r["data"]["harvested"].get("birth") == 1950,
      str(r["data"]["harvested"]))
rows = db.query(LifeAnchor).filter(LifeAnchor.owner_id == OWNER).all()
check("LifeAnchor 表真有 1 行", len(rows) == 1, f"rows={len(rows)}")
check("行为 birth / 1950 / 未确认",
      rows and rows[0].anchor_type == "birth" and rows[0].year == 1950
      and rows[0].confirmed is False, str([(x.anchor_type, x.year) for x in rows]))

# ------------------------------------------------------------
print("\n【② 采集：语音转写里的锚点】")
mk_story("s_marriage", title="成家")
mk_clip("c1", "s_marriage", transcript="我是1972年结的婚，那年我二十二。")
r2 = A.harvest_anchors(db, owner_id=OWNER)
check("从语音转写采到 marriage_year",
      r2["data"]["harvested"].get("marriage") == 1972, str(r2["data"]["harvested"]))

# ------------------------------------------------------------
print("\n【③ 读取：get_anchors 键名对齐 extract_time】")
amap = A.get_anchors(db, owner_id=OWNER)
check("返回 birth_year", amap.get("birth_year") == 1950, str(amap))
check("返回 marriage_year", amap.get("marriage_year") == 1972, str(amap))

# ------------------------------------------------------------
print("\n【④ 幂等：重复 harvest 结果一致、不脏】")
n_before = db.query(LifeAnchor).filter(LifeAnchor.owner_id == OWNER).count()
r3 = A.harvest_anchors(db, owner_id=OWNER)
n_after = db.query(LifeAnchor).filter(LifeAnchor.owner_id == OWNER).count()
check("行数不变", n_before == n_after, f"{n_before} -> {n_after}")
check("结果仍然正确", A.get_anchors(db, owner_id=OWNER) == amap,
      str(A.get_anchors(db, owner_id=OWNER)))

# ------------------------------------------------------------
print("\n【⑤ 不瞎猜：没有明确锚点陈述 → 不写】")
r4 = A.harvest_anchors(db, owner_id=OTHER)
check("无锚点的书 harvested 为空", r4["data"]["harvested"] == {}, str(r4["data"]))
check("OTHER 表里 0 行",
      db.query(LifeAnchor).filter(LifeAnchor.owner_id == OTHER).count() == 0)

# ------------------------------------------------------------
print("\n【⑥ 用户确认优先：confirmed 不被覆盖】")
# 用户手工把出生年改成 1949 并确认
ur = A.api_upsert_anchor(db, owner_id=OWNER, anchor_type="birth", year=1949,
                         confirm=True)
check("手工 upsert 成功", ur["ok"], str(ur))
check("返回 confirmed=True", ur["data"]["anchor"]["confirmed"] is True, str(ur["data"]))
# 再 harvest：正文还写着 1950，但已确认 1949 不得被覆盖
r5 = A.harvest_anchors(db, owner_id=OWNER)
check("harvest 未覆盖确认值", A.get_anchors(db, owner_id=OWNER)["birth_year"] == 1949,
      str(A.get_anchors(db, owner_id=OWNER)))
check("kept_confirmed 里有 birth", r5["data"]["kept_confirmed"].get("birth") == 1949,
      str(r5["data"]["kept_confirmed"]))

# ------------------------------------------------------------
print("\n【⑦ 反推联动：有锚点→能落地；无锚点→待定】")
# 有锚点（birth=1949）
res_yes = timeline.extract_time("我八岁那年", {"birth_year": 1949})
check("有 birth 锚点：「我八岁那年」→ 1957",
      res_yes.sort_key is not None and res_yes.label.startswith("1957"),
      f"sort_key={res_yes.sort_key} label={res_yes.label} method={res_yes.method}")
# 无锚点
res_no = timeline.extract_time("我八岁那年", {})
check("无锚点：「我八岁那年」→ sort_key=None 不落地（不瞎猜）",
      res_no.sort_key is None,
      f"sort_key={res_no.sort_key} label={res_no.label}")
check("无锚点：label 原样保留老人说法（不凑整）",
      "8岁那年" in (res_no.label or ""), f"label={res_no.label}")

# ------------------------------------------------------------
print("\n【⑧ 手工 upsert 边界】")
bad = A.api_upsert_anchor(db, owner_id=OWNER, anchor_type="birth", year="不是年份")
check("非法年份被拒", bad["ok"] is False and bad["code"] == "BAD_YEAR", str(bad))
bad2 = A.api_upsert_anchor(db, owner_id=OWNER, anchor_type="天外飞仙", year=1950)
check("非法类型被拒", bad2["ok"] is False and bad2["code"] == "BAD_TYPE", str(bad2))
bad3 = A.api_upsert_anchor(db, owner_id=OWNER, anchor_type="birth", year=1200)
check("超范围年份被拒", bad3["ok"] is False and bad3["code"] == "BAD_YEAR", str(bad3))

# ------------------------------------------------------------
print("\n【⑨ 端到端：story 写锚点 → auto_place 把「嫁过来第二年」排对】")
# 书主人 OWNER：正文里已写「我是1949年生的」→ 锚点 birth=1949
# 新增一条故事，time_raw 用相对表述「嫁过来第二年」，无锚点时应尽量落地
# 先保证 marriage 锚点在（1972，见 ②）
mk_story("s_rel", title="嫁过来头两年", time_raw="嫁过来第二年")
ap = T.auto_place_story(db, story_id="s_rel")
check("auto_place 成功", ap["ok"], str(ap))
# 用 anchor_api 的锚点喂 extract_time，验证「嫁过来第二年」能算出 1973
anchors_now = A.get_anchors(db, owner_id=OWNER)
res_mar = timeline.extract_time("嫁过来第二年", anchors_now)
check("有 marriage 锚点：「嫁过来第二年」→ 1973",
      res_mar.sort_key is not None and res_mar.label.startswith("1973"),
      f"anchors={anchors_now} sort_key={res_mar.sort_key} label={res_mar.label}")
# auto_place 落到 s_rel 上的结果（extract_time 直接吃 anchor_api 的锚点）
row = db.query(Story).filter(Story.id == "s_rel").first()
check("s_rel 被真的归位（sort_key>0）", (row.time_sort_key or 0) > 0,
      f"time_label={row.time_label} sort_key={row.time_sort_key} method={row.time_extract_method}")

# ------------------------------------------------------------
print("\n【⑩ 接口：api_get_anchors 返回形状】")
ga = A.api_get_anchors(db, owner_id=OWNER)
check("api_get_anchors 成功", ga["ok"], str(ga))
check("anchors 非空且含 anchor_map",
      len(ga["data"]["anchors"]) >= 2 and "anchor_map" in ga["data"], str(ga["data"]))
check("每条含前端要的字段",
      all(k in ga["data"]["anchors"][0]
          for k in ("anchor_type", "anchor_name", "year", "confirmed")),
      str(ga["data"]["anchors"][0]))

# ------------------------------------------------------------
print("\n" + "=" * 62)
print(f"结果：{passed} passed / {failed} failed / 共 {passed + failed}")
if fails:
    print("失败项：" + "、".join(fails))
print("=" * 62)
db.close()
sys.exit(1 if failed else 0)
