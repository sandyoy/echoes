#!/usr/bin/env python3
"""
自测：归类与切分（§五之二.3 多时间点切分 / §五之二.4 宁可分错不可错并 / §五之二.5 抽主体找候选）
建立：2026-10-16

跑法（★必须用 /usr/bin/python3，环境坑见 README_运行环境.md）：
    cd /home/ubuntu/echoes/backend && DATABASE_URL="sqlite:///:memory:" /usr/bin/python3 selftest_group_api.py

铁律自证：
- 硬规矩2「说已通要自证」：本脚本输出 N/N 通过 + EXIT 码
- 铁律 A「禁止全自动合并」：T12 断言 find_merge_candidates 不改库、T15 断言 no-confirm 被拒
- 铁律 F「切分不丢字」：T3 断言拼接 == 原文
"""
import os
import sys

# ★必须在 import models 之前设库地址（坑：models 取 DATABASE_URL，设 ECHOES_DB 无效）
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    init_db, SessionLocal, Story, Clip, ClipType, User,
)
from group_api import (  # noqa: E402
    segment_clip_by_time, api_segment_preview, api_apply_segments,
    decide_grouping, extract_subject, subject_similarity,
    find_merge_candidates, api_group_candidates, api_merge_stories,
    api_ungroup_story, SEPARATE, MERGE_CANDIDATE,
)

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ❌ {name}  {extra}")


def new_story(db, *, sid, owner, text="", ts=0, label="", raw_time=""):
    s = Story(id=sid, owner_id=owner, raw_content=text,
              time_sort_key=ts, time_label=label, time_raw=raw_time,
              narrator_id=owner)
    db.add(s)
    db.flush()
    return s


def main():
    init_db()
    db = SessionLocal()
    OWNER = "u_owner"
    db.add(User(id=OWNER, nick_name="李桂芳"))
    db.flush()

    print("\n=== T1 多时间点 → 切成多段（§五之二.3 第1条「能明确切分」）===")
    txt = "我八岁那年上学。十七岁那年就去当兵了。"
    segs = segment_clip_by_time(txt, {"birth_year": 1950})
    check("T1 切出 2 段", len(segs) == 2, f"got {len(segs)}")
    check("T1 段1 含'上学'", "上学" in segs[0]["text"])
    check("T1 段2 含'当兵'", "当兵" in segs[1]["text"])
    check("T1 段1 有年份(1958)", (segs[0]["time_profile"] or {}).get("sort_key") == 1958,
          f"got {segs[0]['time_profile']}")
    check("T1 段2 有年份(1967)", (segs[1]["time_profile"] or {}).get("sort_key") == 1967,
          f"got {segs[1]['time_profile']}")

    print("\n=== T2 单时间点 → 不硬切（保命线：不无中生有）===")
    segs2 = segment_clip_by_time("1978年包产到户，我们家分了地。", None)
    check("T2 只有 1 段", len(segs2) == 1, f"got {len(segs2)}")

    print("\n=== T3 切分不丢一个字（铁律 F：拼接 == 原文）===")
    joined = "".join(x["text"] for x in segs)
    check("T3 拼接 == 原文", joined.strip() == txt.strip(), f"joined={joined!r}")

    print("\n=== T4 判不出时间 → time_pending=True（§5.4 不猜）===")
    segs4 = segment_clip_by_time("后来就那样过着。再后来孩子都大了。嗯。", None)
    # 无时间线索 → 单段且 pending
    check("T4 无时间线索 → 单段", len(segs4) == 1, f"got {len(segs4)}")
    check("T4 标 time_pending", segs4[0]["time_pending"] is True)

    print("\n=== T5 历史事件也可当切点（§5.2 线索②）===")
    segs5 = segment_clip_by_time("文革那会儿我还小。改革开放以后我进了厂。", None)
    check("T5 切出 2 段", len(segs5) == 2, f"got {len(segs5)}")
    check("T5 段1 命中文革(1966)", (segs5[0]["time_profile"] or {}).get("sort_key") == 1966,
          f"got {segs5[0]['time_profile']}")
    check("T5 段2 命中改革开放(1978)", (segs5[1]["time_profile"] or {}).get("sort_key") == 1978,
          f"got {segs5[1]['time_profile']}")

    print("\n=== T6 紧密关联（同一年同一说法）→ needs_ask（§五之二.3 第2条：不替他决定）===")
    segs6 = segment_clip_by_time("1968年我下乡了。1968年我还认识了你爸。", None)
    check("T6 切出 2 段", len(segs6) == 2, f"got {len(segs6)}")
    check("T6 标 needs_ask", any(x["needs_ask"] for x in segs6),
          f"flags={[x['needs_ask'] for x in segs6]}")

    print("\n=== T7 decide_grouping：宁可分错不可错并（§五之二.4）===")
    d1 = decide_grouping(same_time=False, same_subject=True, subject_similarity=0.9)
    check("T7 时间不同 → separate", d1["decision"] == SEPARATE, d1)
    d2 = decide_grouping(same_time=True, same_subject=False, subject_similarity=0.0)
    check("T7 主体不同 → separate", d2["decision"] == SEPARATE, d2)
    d3 = decide_grouping(same_time=True, same_subject=True, subject_similarity=0.9,
                         confirmed_by_user=False)
    check("T7 都对但没人确认 → 仍 separate（铁律A）", d3["decision"] == SEPARATE, d3)
    check("T7 理由=need_user_confirm", d3["reason"] == "need_user_confirm", d3)
    d4 = decide_grouping(same_time=True, same_subject=True, subject_similarity=0.9,
                         confirmed_by_user=True)
    check("T7 都对且人确认 → merge_candidate", d4["decision"] == MERGE_CANDIDATE, d4)
    d5 = decide_grouping(same_time=True, same_subject=True, subject_similarity=0.5,
                         confirmed_by_user=True)
    check("T7 相似度太低 → 仍 separate", d5["decision"] == SEPARATE, d5)

    print("\n=== T8 抽主体（§五之二.5 第2步：规则可解的部分）===")
    subj = extract_subject("我在王家村跟我大哥一起盖的房子，那时候我妈还在。")
    check("T8 抽到地点(村)", any("村" in p for p in subj["places"]), subj["places"])
    check("T8 抽到动作(盖的房子)", any("盖" in a for a in subj["actions"]), subj["actions"])
    check("T8 地名不含虚词(不是'我在村')",
          all(p.startswith("王家") or len(p) <= 4 for p in subj["places"]), subj["places"])
    check("T8 有 tokens", len(subj["tokens"]) > 0, subj["tokens"])
    empty = extract_subject("")
    check("T8 空文本 is_empty=True", empty["is_empty"] is True)

    print("\n=== T9 主体相似度：偏保守（高判会导致错并）===")
    a = extract_subject("1978年在王家村盖了三间房")
    b = extract_subject("1978年在王家村盖房，累坏了")
    c = extract_subject("1990年去城里做生意了")
    sim_ab = subject_similarity(a, b)
    sim_ac = subject_similarity(a, c)
    check("T9 相似 > 不相似", sim_ab > sim_ac, f"ab={sim_ab} ac={sim_ac}")
    check("T9 空主体 → 0.0", subject_similarity({}, a) == 0.0)

    print("\n=== T10 find_merge_candidates 只出候选、不改库（铁律A）===")
    db.rollback()
    db.query(Clip).delete()
    db.query(Story).delete()
    db.flush()
    new_story(db, sid="s1", owner=OWNER, text="1978年在王家村盖了三间房",
              ts=1978, label="1978年", raw_time="1978年")
    new_story(db, sid="s2", owner=OWNER, text="1978年在王家村盖房，累坏了",
              ts=1978, label="1978年", raw_time="1978年")
    new_story(db, sid="s3", owner=OWNER, text="1990年去城里做生意了",
              ts=1990, label="1990年", raw_time="1990年")
    db.commit()
    before = db.query(Story).count()
    cands = find_merge_candidates(db, owner_id=OWNER, story_id="s1")
    db.commit()
    after = db.query(Story).count()
    check("T10 候选数 ≥1", len(cands) >= 1, cands)
    check("T10 s2 在候选里", any(x["story_id"] == "s2" for x in cands), cands)
    check("T10 库条数不变（没自动合并）", before == after, f"{before}->{after}")
    check("T10 候选 decision 恒为 separate（无人确认）",
          all(x["decision"] == SEPARATE for x in cands), cands)
    check("T10 带 similarity 字段", all("similarity" in x for x in cands), cands)

    print("\n=== T11 api_group_candidates：接口出候选 + 明写 auto_merged=False ===")
    r = api_group_candidates(db, owner_id=OWNER, viewer_id=OWNER, story_id="s1")
    check("T11 ok=True", r["ok"] is True, r)
    check("T11 auto_merged=False", r["data"]["auto_merged"] is False, r["data"])
    check("T11 有 hint 提示由人点", "由你点" in r["data"]["hint"], r["data"]["hint"])
    r_bad = api_group_candidates(db, owner_id=OWNER, viewer_id="u_stranger", story_id="s1")
    check("T11 外人被拒", r_bad["ok"] is False and r_bad["code"] == "forbidden", r_bad)

    print("\n=== T12 api_segment_preview：先给看、不落库 ===")
    n_before = db.query(Story).count()
    rp = api_segment_preview(db, owner_id=OWNER, viewer_id=OWNER, story_id="s3")
    n_after = db.query(Story).count()
    check("T12 ok=True", rp["ok"] is True, rp)
    check("T12 不落库", n_before == n_after, f"{n_before}->{n_after}")

    print("\n=== T13 api_apply_segments：人确认后真切 ===")
    db.query(Clip).delete()
    db.query(Story).delete()
    db.flush()
    new_story(db, sid="m1", owner=OWNER,
              text="我八岁那年上学。十七岁那年就去当兵了。", ts=0,
              label="", raw_time="")
    db.commit()
    ra = api_apply_segments(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1",
                            user_confirmed=True)
    check("T13 ok=True", ra["ok"] is True, ra)
    check("T13 切出 1 条新故事", len(ra["data"]["new_story_ids"]) == 1, ra["data"])
    check("T13 有 group_id", bool(ra["data"]["group_id"]), ra["data"])
    check("T13 库里现有 2 条", db.query(Story).count() == 2, db.query(Story).count())
    kept = db.query(Story).filter(Story.id == "m1").first()
    newone = db.query(Story).filter(Story.id == ra["data"]["new_story_ids"][0]).first()
    check("T13 两段同 group_id", kept.group_id == newone.group_id,
          f"{kept.group_id} / {newone.group_id}")
    check("T13 不丢字（拼接==原文）",
          (kept.raw_content + newone.raw_content).strip()
          == "我八岁那年上学。十七岁那年就去当兵了。".strip(),
          f"{kept.raw_content!r}+{newone.raw_content!r}")

    print("\n=== T14 api_apply_segments 未确认 → 拒（防误切）===")
    rn = api_apply_segments(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1")
    check("T14 no-confirm 被拒", rn["ok"] is False and rn["code"] == "need_confirm", rn)

    print("\n=== T15 api_merge_stories：★必须人确认（铁律A）===")
    rm_no = api_merge_stories(db, owner_id=OWNER, viewer_id=OWNER,
                              story_ids=["m1", newone.id], target_id="m1")
    check("T15 no-confirm 被拒", rm_no["ok"] is False and rm_no["code"] == "need_confirm", rm_no)
    check("T15 库里仍 2 条（没偷偷合）", db.query(Story).count() == 2, db.query(Story).count())

    # 给 newone 挂一个 clip，验证合并时素材跟着走
    c1 = Clip(id="c1", story_id=newone.id, clip_type=ClipType.TEXT, text="当兵去了")
    db.add(c1)
    db.commit()

    rm = api_merge_stories(db, owner_id=OWNER, viewer_id=OWNER,
                           story_ids=["m1", newone.id], target_id="m1",
                           user_confirmed=True)
    check("T15 确认后合并 ok", rm["ok"] is True, rm)
    check("T15 库里剩 1 条", db.query(Story).count() == 1, db.query(Story).count())
    check("T15 clip 已迁到 target", db.query(Clip).filter(Clip.story_id == "m1").count() == 1)
    tgt = db.query(Story).filter(Story.id == "m1").first()
    check("T15 target 标 manual", tgt.ai_group_source == "manual", tgt.ai_group_source)
    check("T15 两段原文都在", "当兵" in tgt.raw_content and "上学" in tgt.raw_content,
          tgt.raw_content)

    print("\n=== T16 api_ungroup_story：分错可修的退路（§五之二.4）===")
    ru = api_ungroup_story(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1")
    check("T16 ok=True", ru["ok"] is True, ru)
    check("T16 group_id 已清空", ru["data"]["group_id"] is None, ru["data"])
    check("T16 有 old_group_id 记录", bool(ru["data"]["old_group_id"]), ru["data"])

    print("\n=== T17 权限：外人不能切/合/摘 ===")
    r_forbid = api_apply_segments(db, owner_id=OWNER, viewer_id="u_outsider",
                                  story_id="m1", user_confirmed=True)
    check("T17 外人切分被拒", r_forbid["ok"] is False and r_forbid["code"] == "forbidden", r_forbid)
    r_forbid2 = api_ungroup_story(db, owner_id=OWNER, viewer_id="u_outsider", story_id="m1")
    check("T17 外人摘组被拒", r_forbid2["ok"] is False and r_forbid2["code"] == "forbidden", r_forbid2)

    print("\n=== T18 信封形状一致（前端一套解析）===")
    for r in (api_group_candidates(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1"),
              api_segment_preview(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1"),
              api_ungroup_story(db, owner_id=OWNER, viewer_id=OWNER, story_id="m1")):
        check(f"T18 信封 ok/data", r.get("ok") is True and "data" in r, r)
    rf = api_segment_preview(db, owner_id="", viewer_id="")
    check("T18 失败信封有 error/code", rf["ok"] is False and "code" in rf and "error" in rf, rf)

    print("\n=== T19 边界：空文本 / 单条合并 / target 不在列表 ===")
    check("T19 空文本 → []", segment_clip_by_time("") == [])
    r1 = api_merge_stories(db, owner_id=OWNER, viewer_id=OWNER,
                           story_ids=["m1"], user_confirmed=True)
    check("T19 单条合并被拒", r1["ok"] is False, r1)
    r2 = api_merge_stories(db, owner_id=OWNER, viewer_id=OWNER,
                           story_ids=["m1", "s1"], target_id="sX", user_confirmed=True)
    check("T19 target 不在列表被拒", r2["ok"] is False, r2)

    print(f"\n{'='*50}")
    print(f"结果：{PASS}/{PASS+FAIL} 通过")
    if FAILED:
        print("失败项：")
        for f in FAILED:
            print("  -", f)
    print(f"{'='*50}")
    db.close()
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
