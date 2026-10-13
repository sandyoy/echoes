#!/usr/bin/env python3.12
"""interview_recap.py 自测（2026-10-13 新建，第2期 §7.4/§7.5/§7.6）
覆盖：
  ① §7.4 剥问句：一问一答列表 → 成品只留老人讲的，AI 问句被剥掉（dropped_questions 计数对）
  ② §7.5 理顺自述体：去口水碎屑、句首引导词、断句补句号；**不添加老人没说过的内容**
  ③ §7.5 空内容：不报错，polished="" changed=False
  ④ §7.6 复述脚本：recap_speech = 复述句 + 归属问句（复述+归属一次问完）；带大字按钮+安全默认
  ⑤ §7.6 第一次调用（无答案）→ phase=recap，出 recap_speech + 理顺后自述体
  ⑥ §7.6 老人认可（按钮 accept）→ decision=accepted；apply=True 写回 Story.polished_content
  ⑦ §7.6 老人含糊（嗯/对）→ accepted（安全侧）
  ⑧ §7.6 老人说「不对」→ rejected + need_revise（不进成品）
  ⑨ §7.6 老人说「没听清」→ 重报（recap_repeat）；重报用完 → 接受（安全默认）
  ⑩ §7.6 超时无反应 → accepted（安全默认，绝不卡住老人）
  ⑪ §7.6 权限：外人（无权限）被拒 403
  ⑫ §7.6 故事不存在 → not_found
  ⑬ 铁律：owner_id 空 → bad_request
  ⑭ 信封形状：ok/fail 字段齐
"""
import sys, os, uuid
sys.path.insert(0, "/home/ubuntu/echoes/backend")

TEST_DB = f"/tmp/echoes_selftest_recap_{uuid.uuid4().hex[:8]}.db"
# ⚠️ 铁律（10-01 踩过）：库地址取自 DATABASE_URL，必须在 import models 之前设。
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models
from models import SessionLocal, init_db, Story, User
import interview_recap as R

init_db()
db = SessionLocal()

passed = 0; failed = 0; fails = []

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  [PASS] {name}")
    else:
        failed += 1; fails.append(name); print(f"  [FAIL] {name}  {detail}")

OWNER = "openid_rc_owner"
OTHER = "openid_rc_other"


def mk_user(uid, **kw):
    u = User(id=uid, nick_name=kw.get("nick_name", "测试"), real_name=kw.get("real_name", ""))
    db.add(u); db.commit()
    return u


def mk_story(sid, *, owner=OWNER):
    s = Story(id=sid, owner_id=owner, title=f"故事{sid}")
    db.add(s); db.commit()
    return s


mk_user(OWNER, real_name="张大叔")
mk_user(OTHER)


# ------------------------------------------------------------------
print("① §7.4 剥掉 AI 问句（成品只留老人讲的）")
qa = [
    {"q": "您是哪年结的婚呀？", "a": "六八年结的婚。"},
    {"q": "那年办得热闹不？", "a": "摆了两桌，队里人都来了。"},
    {"q": "哦，那后来呢？", "a": "后来就一直在村里过日子。"},
]
draft = R.build_interview_draft(qa)
check("答案条数=3（只留老人讲的）", len(draft["answers"]) == 3, draft)
check("问句计数=3", draft["dropped_questions"] == 3, draft)
check("成品不含问号句", "？" not in draft["raw_text"] and "?" not in draft["raw_text"], draft["raw_text"])
check("成品含老人原话", "六八年结的婚" in draft["raw_text"], draft["raw_text"])


# ------------------------------------------------------------------
print("② §7.5 理顺成自述体")
raw = "我跟你讲，那个，六八年结的婚，,，那年可热闹了"
pol = R.polish_to_self_narration(raw)
check("句首引导词去掉", not pol["polished"].startswith("我跟你讲"), pol)
check("口水词「那个」去掉", "那个" not in pol["polished"], pol)
check("重复逗号合并", "，，" not in pol["polished"] and ",," not in pol["polished"], pol)
check("句末补句号", pol["polished"].endswith("。"), pol)
check("changed=True", pol["changed"] is True, pol)
# 不添加内容：理顺后去掉标点后长度 ≤ 原文
check("未添加老人没说过的内容（去标点后不超原文）",
      len(pol["polished"].replace("，", "").replace("。", "")) <= len(raw.replace("，", "").replace(",", "")) + 2,
      (raw, pol))

print("③ §7.5 空内容不报错")
pol2 = R.polish_to_self_narration("")
check("空内容 polished=''", pol2["polished"] == "" and pol2["changed"] is False, pol2)


# ------------------------------------------------------------------
print("④ §7.6 复述脚本=复述句+归属问句（一次问完）")
script = R.make_recap_script(db, owner_id=OWNER,
                             polished_text="六八年结的婚。那年摆了两桌。")
check("含复述引导句", "您刚才说的这件事" in script["recap_speech"], script)
check("含归属问句（一次问完）", "是上面说的这件事吗" in script["recap_speech"], script)
check("带大字按钮", len(script["buttons"]) == 2, script)
check("安全默认=accept", script["safe_default"] == "accept", script)


# ------------------------------------------------------------------
print("⑤ §7.6 第一次调用 → phase=recap")
s1 = mk_story("story_rc_1")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1", qa_pairs=qa)
check("ok", r["ok"] is True, r)
check("phase=recap", r["data"]["phase"] == "recap", r["data"])
check("出 recap_speech", bool(r["data"]["recap_speech"]), r["data"])
check("出理顺后自述体（成品形态）", bool(r["data"]["polished_text"]), r["data"])
check("raw_answers 只含老人讲的", all("？" not in a for a in r["data"]["raw_answers"]), r["data"])


# ------------------------------------------------------------------
print("⑥ 老人认可（按钮）→ accepted + 写回")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_key="accept", apply=True)
check("decision=accepted", r["data"]["decision"] == "accepted", r["data"])
check("reason=button", r["data"]["reason"] == "button", r["data"])
check("applied=True", r["data"].get("applied") is True, r["data"])
db.refresh(s1)
check("已写回 Story.polished_content", bool(s1.polished_content), s1.polished_content)

print("⑦ 老人含糊（嗯）→ accepted（安全侧）")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_text="嗯")
check("含糊→accepted", r["data"]["decision"] == "accepted" and r["data"]["reason"] == "vague_safe_default", r["data"])

print("⑧ 老人说「不对」→ rejected + need_revise")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_text="不对")
check("→rejected", r["data"]["decision"] == "rejected", r["data"])
check("need_revise=True", r["data"].get("need_revise") is True, r["data"])

print("⑨ 老人说「没听清」→ 重报；用完 → 接受")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_text="没听清", retry_used=0)
check("→recap_repeat", r["data"]["phase"] == "recap_repeat", r["data"])
check("重报带 retry_used", r["data"].get("retry_used") == 1, r["data"])
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_text="没听清", retry_used=R.RECAP_MAX_RETRY)
check("重报用完→accepted（安全默认）", r["data"]["decision"] == "accepted"
      and "safe_default" in r["data"]["reason"], r["data"])

print("⑩ 超时无反应 → accepted（安全默认）")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="story_rc_1",
                        qa_pairs=qa, answer_key="timeout")
check("timeout→accepted", r["data"]["decision"] == "accepted"
      and r["data"]["reason"] == "timeout_safe_default", r["data"])


# ------------------------------------------------------------------
print("⑪ 权限：外人被拒")
r = R.api_recap_confirm(db, owner_id=OTHER, viewer_id=OTHER, story_id="story_rc_1", qa_pairs=qa)
# OTHER 是 owner_id 却不是该故事的 owner → can_view_story(owner=story.owner_id=OWNER, viewer=OTHER)
check("外人 forbidden", r["ok"] is False and r["code"] == "forbidden", r)

print("⑫ 故事不存在 → not_found")
r = R.api_recap_confirm(db, owner_id=OWNER, story_id="no_such_story", qa_pairs=qa)
check("not_found", r["ok"] is False and r["code"] == "not_found", r)

print("⑬ owner_id 空 → bad_request")
r = R.api_recap_confirm(db, owner_id="", qa_pairs=qa)
check("bad_request", r["ok"] is False and r["code"] == "bad_request", r)

print("⑭ 信封形状")
check("ok 信封", R.ok({"x": 1})["ok"] is True and "data" in R.ok({"x": 1}))
check("fail 信封", R.fail("m")["ok"] is False and "error" in R.fail("m") and "code" in R.fail("m"))


# ------------------------------------------------------------------
print(f"\n=== interview_recap 自测：{passed}/{passed+failed} 通过 ===")
if fails:
    print("失败项：", fails)
db.close()
sys.exit(0 if failed == 0 else 1)
