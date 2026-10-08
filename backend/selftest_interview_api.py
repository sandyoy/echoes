#!/usr/bin/env python3.12
"""interview_api.py 自测（2026-10-08 新建，第2期 §七「采访引导·可打断」）
覆盖：
  ① 开始采访：AI 主动出第一问，且**优先问人生锚点**（无锚点 → 问出生年）
  ② 锚点问完：锚点齐了 → 转开放问题，不硬编
  ③ 下一问：答完正常出下一问
  ④ ★打断不丢话题：被打断 + 老人这句含糊 → **原样接回刚才那问**（resume），不换题
  ⑤ ★打断判定：老人出声（能量超阈值）→ stop_tts=True；嘈杂环境自动降灵敏（low）
  ⑥ 灵敏度档位：high 档阈值更低 → 更易触发
  ⑦ ★归类问·频率保护：那年只有1件事 → 不问（single_in_year）
  ⑧ ★归类问·正常弹：同时间桶攒够2段 → 问，且带两个大字按钮 + 安全默认
  ⑨ ★归类安全兜底：含糊（嗯/对）→ 默认新建；「没听清」→ 重问；重问用完 → 默认新建
  ⑩ 归类：明确选按钮 / 老人说了具体事 → 对应决策
  ⑪ 「别问了」开关：muted_ask=True 后不再弹归类问
  ⑫ 灵敏度设置：非法值被拒；合法值落库
  ⑬ 权限：外人开始采访被拒
  ⑭ 信封形状：ok/fail 字段齐
"""
import sys, os, uuid, json
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_interview_{uuid.uuid4().hex[:8]}.db"
# ⚠️ 铁律（10-01 踩过）：库地址取自 DATABASE_URL，必须在 import models 之前设，
#    否则 engine 绑死真实库 ./memory_story.db，测试会污染生产数据。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models
from models import (SessionLocal, init_db, Story, User, LifeAnchor, TimePrecision)
import interview_api as I

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_iv_owner"
OTHER = "openid_iv_other"
VIEWER = "openid_iv_family"


def mk_user(uid, **kw):
    u = User(id=uid, nick_name=kw.get("nick_name", "测试"), prefs=kw.get("prefs", {}))
    db.add(u); db.commit()
    return u


def mk_story(sid, *, owner=OWNER, sort_key=0, time_raw=""):
    s = Story(id=sid, owner_id=owner, title=f"故事{sid}",
              time_sort_key=sort_key, time_raw=time_raw)
    db.add(s); db.commit()
    return s


def add_anchor(atype, year, *, owner=OWNER, confirmed=True):
    a = LifeAnchor(id=f"a_{atype}_{year}", owner_id=owner, anchor_type=atype,
                   anchor_name=atype, year=year, confirmed=confirmed)
    db.add(a); db.commit()
    return a


print("=== interview_api 自测开始 ===")
mk_user(OWNER)
mk_user(OTHER)
mk_user(VIEWER)

# --- ① 开始采访：无锚点 → 优先问出生年 ---
r = I.api_start_interview(db, owner_id=OWNER, viewer_id=OWNER)
check("①开始采访 ok", r.get("ok") is True, r)
q = r["data"]["question"]
check("①优先问人生锚点(出生)", q["kind"] == "anchor" and q["anchor_type"] == "birth",
      q)
check("①问完留等待(不连珠炮)", r["data"]["wait_ms"] > 0, r["data"])
check("①允许跑题", r["data"]["follow_digression"] is True, r["data"])

# --- ② 锚点齐了 → 转开放问题 ---
for at, yr in [("birth", 1950), ("work", 1966), ("marriage", 1972),
               ("child_birth", 1974), ("move", 1980)]:
    add_anchor(at, yr)
r = I.api_start_interview(db, owner_id=OWNER, viewer_id=OWNER)
q = r["data"]["question"]
check("②锚点齐→开放问题", q["kind"] == "open", q)
check("②missing_anchors 空", r["data"]["missing_anchors"] == [], r["data"])

# --- ③ 下一问：答完出下一问 ---
rm = I.api_next_question(db, owner_id=OWNER, viewer_id=OWNER,
                         last_answer="那天在生产队干活")
check("③答完全出下一问", rm.get("ok") and rm["data"]["question"], rm)

# --- ④ ★打断不丢话题：被打断+含糊 → 接回刚才那问 ---
r = I.api_next_question(db, owner_id=OWNER, viewer_id=OWNER,
                        last_answer="嗯", interrupted_question="您是哪年结的婚呀？")
check("④被打断含糊→resume", r["data"]["state"] == "resumed", r["data"])
check("④原样接回刚才那问", r["data"]["question"]["text"] == "您是哪年结的婚呀？",
      r["data"]["question"])

# ② 打断后老人答清了 → 正常出下一问（不 resume）
r = I.api_next_question(db, owner_id=OWNER, viewer_id=OWNER,
                        last_answer="1972年结的婚，那天下了大雨",
                        interrupted_question="您是哪年结的婚呀？")
check("④答清了→不 resume", r["data"]["state"] == "asking", r["data"])

# --- ⑤ ★打断判定 ---
r = I.api_barge_in(db, energy_db=-10.0)   # 大声 = 老人出声
check("⑤出声→停TTS", r["data"]["stop_tts"] is True, r["data"])
check("⑤停但记住话题", r["data"]["hold_topic"] is True, r["data"])
r = I.api_barge_in(db, energy_db=-60.0)   # 极静 = 没在说话
check("⑤没出声→不停", r["data"]["stop_tts"] is False, r["data"])
r = I.api_barge_in(db, energy_db=-10.0, assuming_norm="tv")  # 电视环境
check("⑤嘈杂自动降灵敏(low)", r["data"]["sensitivity_gear"] == "low", r["data"])
r = I.api_barge_in(db)   # 前端明确报"出声"但没给能量 → 保守判停
check("⑤无能量保守判停", r["data"]["stop_tts"] is True, r["data"])

# --- ⑥ 灵敏度档位差异 ---
lo = I.SENSITIVITY["low"]["energy_db"]; hi = I.SENSITIVITY["high"]["energy_db"]
check("⑥high档更易触发(阈值更低)", hi < lo, (lo, hi))

# --- ⑦ 归类问·频率保护：单独1条 → 不问 ---
db.query(Story).filter(Story.owner_id == OWNER).delete(); db.commit()
mk_story("s_only", sort_key=1980)
r = I.api_ask_classify(db, owner_id=OWNER, viewer_id=OWNER, new_story_id="s_only")
check("⑦那年只1件→不问", r["data"]["ask"] is False, r["data"])
check("⑦原因=single_in_year", r["data"]["reason"] == "single_in_year", r["data"])

# --- ⑧ 同桶攒够2段 → 问 ---
mk_story("s_2", sort_key=1980)
r = I.api_ask_classify(db, owner_id=OWNER, viewer_id=OWNER, new_story_id="s_only")
check("⑧同桶2件→弹问", r["data"]["ask"] is True, r["data"])
q = r["data"]["question"]
check("⑧两个大字按钮", q["buttons"][0]["key"] == "new" and q["buttons"][1]["key"] == "existing", q)
check("⑧5秒无反应浮按钮", q["fallback_buttons_after_ms"] == 5000, q)
check("⑧带安全默认new", r["data"]["safe_default"] == "new", r["data"])

# --- ⑨ 归类安全兜底 ---
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_text="嗯")
check("⑨含糊(嗯)→默认新建", r["data"]["decision"] == "new", r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_text="对")
check("⑨含糊(对)→默认新建", r["data"]["decision"] == "new", r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_text="没听清")
check("⑨没听清→重问", r["data"]["retry"] is True and r["data"]["retry_used"] == 1, r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_text="没听清",
                          retry_used=2)
check("⑨重问用完→默认新建", r["data"]["decision"] == "new" and r["data"]["retry"] is False,
      r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_key="timeout")
check("⑨超时无反应→默认新建", r["data"]["decision"] == "new", r["data"])

# --- ⑩ 归类明确回答 ---
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_key="new")
check("⑩选按钮new", r["data"]["decision"] == "new", r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2", answer_key="existing")
check("⑩选按钮existing", r["data"]["decision"] == "existing", r["data"])
r = I.api_classify_answer(db, owner_id=OWNER, new_story_id="s_2",
                          answer_text="是新的事，那年分了地")
check("⑩说了具体事→existing待定位",
      r["data"]["decision"] == "existing" and r["data"].get("need_pick_story") is True, r["data"])

# --- ⑪ 「别问了」开关 ---
r = I.api_set_interview_pref(db, owner_id=OWNER, muted_ask=True)
check("⑪设置muted成功", r.get("ok") and r["data"]["muted_ask"] is True, r)
r = I.api_ask_classify(db, owner_id=OWNER, viewer_id=OWNER, new_story_id="s_only")
check("⑪muted后不再问", r["data"]["ask"] is False and r["data"]["reason"] == "muted", r["data"])

# --- ⑫ 灵敏度设置 ---
r = I.api_set_interview_pref(db, owner_id=OWNER, sensitivity="bogus")
check("⑫非法灵敏度被拒", r.get("ok") is False, r)
r = I.api_set_interview_pref(db, owner_id=OWNER, sensitivity="high")
check("⑫合法灵敏度落库", r["data"]["sensitivity"] == "high", r["data"])

# --- ⑬ 权限：外人开始采访被拒 ---
r = I.api_start_interview(db, owner_id=OWNER, viewer_id=OTHER)
check("⑬外人采访被拒", r.get("ok") is False and r.get("code") == "forbidden", r)

# --- ⑭ 信封形状 ---
r = I.api_start_interview(db, owner_id="", viewer_id="")
check("⑭空owner→bad_request", r.get("ok") is False and r.get("code") == "bad_request", r)
r = I.api_start_interview(db, owner_id=OWNER, viewer_id=OWNER)
check("⑭ok信封字段齐", set(["ok", "data"]).issubset(r.keys()), r)

print(f"\n=== 结果：{passed}/{passed+failed} 通过 ===")
if fails:
    print("FAIL:", fails)
db.close()
sys.exit(0 if failed == 0 else 1)
