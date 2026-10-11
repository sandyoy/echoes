"""
往事可追忆 - 成书接口自测（§8.2 两筐素材 / §8.3 谁成书谁是"我" / §8.2 引用不改写）
运行：cd /home/ubuntu/echoes/backend && /usr/bin/python3 selftest_book_api.py

铁律（v2.4 第十四节）：静态核验 ≠ 通过。本脚本**真跑**每个 handler。
断言铁律（09-20 假报事故）：必须 status ok==True **且** 关键字段存在，两条都过才算通。
"""

import os
import sys
import json
import uuid

TEST_DB = os.path.join("/tmp", f"echoes_book_selftest_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

import models                                            # noqa: E402
from models import (Story, SessionLocal, init_db, ClipType, Visibility,  # noqa: E402
                    SourceType, Ebook)
from permissions import attach_clip, add_family_member  # noqa: E402
import book_api as api                                  # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"✅ {label}" + (f"  [{extra}]" if extra else ""))
    else:
        FAIL += 1
        print(f"❌ {label}" + (f"  [{extra}]" if extra else ""))


def new_story(db, sid, owner, title, key=""):
    s = Story(id=sid, owner_id=owner, title=title, time_sort_key=key, time_label=key)
    db.add(s)
    db.commit()
    return s


def main():
    init_db()
    db = SessionLocal()

    OWNER = "u_grandpa"      # 书的主人 = 点成书的"我"
    FRIEND = "u_neighbor"    # 别人（邻居，写了段公开的提到你）
    OTHER = "u_stranger"

    s1 = new_story(db, "s_1937", OWNER, "逃难那年", "1937")
    s2 = new_story(db, "s_1980", OWNER, "包产到户", "1980")

    # 筐①：自己的素材（一条公开 + 一条私有）
    c_own_pub = attach_clip(db, story_id="s_1937", clip_type=ClipType.TEXT,
                            text="我八岁那年，跟着家里往南走。",
                            provider_id=OWNER, created_by=OWNER,
                            visibility=Visibility.PUBLIC)
    c_own_priv = attach_clip(db, story_id="s_1980", clip_type=ClipType.TEXT,
                             text="分田到户那天我心里其实有点慌。（这句我不想给别人看）",
                             provider_id=OWNER, created_by=OWNER,
                             visibility=Visibility.PRIVATE)
    # 筐②：邻居公开的、提到我的素材（引用型）
    c_pub_other = attach_clip(db, story_id="s_1937", clip_type=ClipType.TEXT,
                              text="老张家那年也是往南走的，我们两家一道。",
                              provider_id=FRIEND, created_by=FRIEND,
                              visibility=Visibility.PUBLIC,
                              source_type=SourceType.QUOTE,
                              ref_author_name="李婶")
    # 邻居**私有**的（不该进公共筐）
    c_priv_other = attach_clip(db, story_id="s_1937", clip_type=ClipType.TEXT,
                               text="这句是别人私下的，谁都别想引用。",
                               provider_id=FRIEND, created_by=FRIEND,
                               visibility=Visibility.PRIVATE)

    print("=== 1. 取材·两筐 ===")
    r = api.api_book_source_baskets(db, owner_id=OWNER, actor_id=OWNER)
    check("取材返回 ok", r.get("ok") is True, str(r.get("error", "")))
    d = r.get("data", {})
    own_ids = {x["clip_id"] for x in d.get("own", [])}
    pub_ids = {x["clip_id"] for x in d.get("public", [])}
    check("筐①含自己的公开素材", c_own_pub.id in own_ids)
    check("筐①含自己的私有素材（自己的一定能装）", c_own_priv.id in own_ids)
    check("筐②含邻居公开素材", c_pub_other.id in pub_ids)
    check("筐②**不含**邻居私有素材（默认私有不可引用）", c_priv_other.id not in pub_ids)
    check("公共素材带出处署名", any(x.get("ref_author_name") == "李婶" for x in d.get("public", [])))

    print("=== 2. 越权·别人不能替你成书 ===")
    r = api.api_book_source_baskets(db, owner_id=OWNER, actor_id=OTHER)
    check("非本人取材被拒", r.get("ok") is False and r.get("code") == "forbidden")
    r = api.api_generate_ebook(db, owner_id=OWNER, actor_id=OTHER)
    check("非本人生成被拒", r.get("ok") is False and r.get("code") == "forbidden")

    print("=== 3. 生成·不点选公共素材（只装自己的）===")
    r = api.api_generate_ebook(db, owner_id=OWNER, actor_id=OWNER,
                               title="我的一生", picked_public_ids=[])
    check("生成返回 ok", r.get("ok") is True, str(r.get("error", "")))
    g = r.get("data", {})
    eid = g.get("ebook_id", "")
    check("返回 ebook_id", bool(eid))
    check("只装自己的=2件", g.get("clip_count") == 2, f"实际{g.get('clip_count')}")
    all_texts = json.dumps(g.get("chapters", []), ensure_ascii=False)
    check("私有素材也进书了（自己的）", "分田到户那天" in all_texts)
    check("未点选的公共素材**没**进书", "老张家那年" not in all_texts)
    check("章节按时间排序（1937在前）",
          [c["time_label"] for c in g.get("chapters", [])] == ["1937", "1980"],
          str([c["time_label"] for c in g.get("chapters", [])]))

    print("=== 4. 生成·点选公共素材（引用段）===")
    r = api.api_generate_ebook(db, owner_id=OWNER, actor_id=OWNER,
                               title="我的一生", picked_public_ids=[c_pub_other.id],
                               ebook_id=eid)
    check("重生成返回 ok", r.get("ok") is True, str(r.get("error", "")))
    g = r.get("data", {})
    check("装了3件（2自己+1点选）", g.get("clip_count") == 3, f"实际{g.get('clip_count')}")
    check("点选的公共素材进书了", "老张家那年" in json.dumps(g.get("chapters", []), ensure_ascii=False))
    # 找引用段
    quote_entries = []
    for ch in g.get("chapters", []):
        for e in ch.get("entries", []):
            if e.get("is_quote"):
                quote_entries.append(e)
    check("引用段被标记 is_quote=True", len(quote_entries) == 1, f"实际{len(quote_entries)}")
    if quote_entries:
        q = quote_entries[0]
        check("引用段带出处署名", q.get("ref_author_name") == "李婶")
        check("引用段有渲染提示语", "李婶" in q.get("quote_label", ""), q.get("quote_label", ""))
        check("引用段**不可改** editable=False", q.get("editable") is False)
    check("贡献者名单含引用出处", "李婶" in g.get("contributors", []))

    print("=== 5. 幂等·重生成不新建（活文档）===")
    cnt_before = db.query(Ebook).count()
    r = api.api_generate_ebook(db, owner_id=OWNER, actor_id=OWNER, ebook_id=eid,
                               picked_public_ids=[c_pub_other.id])
    cnt_after = db.query(Ebook).count()
    check("重生成未新增 ebook 行", cnt_before == cnt_after, f"{cnt_before}->{cnt_after}")

    print("=== 6. 取我的电子书 ===")
    r = api.api_my_ebook(db, owner_id=OWNER)
    check("取书返回 ok", r.get("ok") is True)
    b = r.get("data", {}).get("book") or {}
    check("取回的书写对 title", b.get("title") == "我的一生", str(b.get("title")))
    check("取回的书含章节", len(b.get("chapters", [])) >= 2)

    print("=== 7. 没书的人取书 → empty（不报错）===")
    r = api.api_my_ebook(db, owner_id="u_nobody")
    check("无书返回 empty=True", r.get("ok") is True and r.get("data", {}).get("empty") is True)

    print("=== 8. 空书成书 → 明确拒绝（不静默）===")
    r = api.api_generate_ebook(db, owner_id="u_empty_owner", actor_id="u_empty_owner")
    check("空书被拒且带原因", r.get("ok") is False and r.get("code") in ("no_stories", "empty_book"))

    db.close()
    print(f"\n===== 结果：{PASS} 通过 / {FAIL} 失败 =====")
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
