# -*- coding: utf-8 -*-
"""
selftest_print_api.py —— v3.0 §8.1/§8.5 实体书通道自测（2026-10-17）

覆盖：
  ① 未成书 → can_print=False / quote 被 no_ebook 拒（§8.1 实体书后置铁律）
  ② 可印信息：页数/条目数/开本尺寸（与 book_view.paginate 同口径，不另算）
  ③ 未带价 → status=pending（不臆造价格）；带价 → status=quoted + 总价=单价×册数
  ④ 册数越界、单价为负、单价非数字 → 全拒（不静默落值）
  ⑤ 越权：非主人建单/查单/改状态 → forbidden
  ⑥ 状态机：合法迁移走通；跨级（quoted→done）拒；终态不可回写；**幂等** unchanged
  ⑦ 野状态值（"发货了"）→ bad_status，不静默写库
  ⑧ 书续添后（新电子书）→ catalog 标 stale_against_last_order=True（防印旧版）
  ⑨ 信封形状 + 我的印单列表

跑法：cd backend && /usr/bin/python3 selftest_print_api.py
"""

import os
import sys
import uuid

TEST_DB = os.path.join("/tmp", f"echoes_selftest_print_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, init_db, Story, Clip, ClipType, Visibility, SourceType, User,
)
from permissions import _new_id  # noqa: E402
import book_api          # noqa: E402
import book_view_api as BV  # noqa: E402
import print_api as P    # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


def new_story(db, sid, owner, title, texts):
    db.add(Story(id=sid, owner_id=owner, title=title))
    db.commit()
    for t in texts:
        db.add(Clip(id=_new_id("clip"), story_id=sid, clip_type=ClipType.TEXT,
                    provider_id=owner, text=t, visibility=Visibility.PUBLIC,
                    source_type=SourceType.ORIGIN))
    db.commit()


def main():
    init_db()
    db = SessionLocal()
    OWNER = "u_owner"
    OTHER = "u_other"
    db.add(User(id=OWNER, nick_name="李桂芳"))
    db.add(User(id=OTHER, nick_name="邻居老王"))
    db.commit()

    print("【① 未成书时不许印（§8.1 实体书后置）】")
    r = P.api_print_catalog(db, owner_id=OWNER)
    check("未成书 can_print=False", r["ok"] and r["data"]["can_print"] is False, r)
    check("未成书 reason=no_ebook", r["data"]["reason"] == "no_ebook", r["data"])
    check("未成书给老人话术", "电子书" in r["data"]["notice"], r["data"])
    q = P.api_print_quote(db, owner_id=OWNER, copies=1, unit_price=20)
    check("未成书建单被拒 no_ebook", q["ok"] is False and q["code"] == "no_ebook", q)
    r = P.api_print_catalog(db, owner_id="")
    check("缺 owner_id 拒", r["ok"] is False and r["code"] == "missing_owner_id", r)

    print("【② 成书后可印信息（页数/条目/开本）】")
    new_story(db, "s1", OWNER, "小时候", ["我八岁那年下了很大的雪", "妈妈背着我去上学"])
    new_story(db, "s2", OWNER, "工作", ["我十九岁进了纺织厂"])
    gen = book_api.api_generate_ebook(db, owner_id=OWNER)
    check("成书成功", gen["ok"], gen)
    eid = gen["data"]["ebook_id"]

    r = P.api_print_catalog(db, owner_id=OWNER)
    d = r["data"]
    check("可印 can_print=True", d["can_print"] is True, d)
    check("条目数=3（与成书一致）", d["specs"]["entry_count"] == 3, d["specs"])
    content = BV._load_content(db.get(__import__("models").Ebook, eid))
    check("页数与 paginate 同口径", d["specs"]["page_count"] == len(BV.paginate(content)), d["specs"])
    check("A5 尺寸 148×210", (d["specs"]["width_mm"], d["specs"]["height_mm"]) == (148, 210), d["specs"])
    check("catalog 不含任何价格字段", "price" not in d["specs"], d["specs"])
    check("无印单时 last_print_order=None", d["last_print_order"] is None, d)
    check("无印单时 stale=False", d["stale_against_last_order"] is False, d)

    r = P.api_print_catalog(db, owner_id=OWNER, book_spec="B6")
    check("未知开本回落 A5 并标 fallback", r["data"]["specs"]["book_spec"] == "A5"
          and r["data"]["specs"]["fallback"] is True, r["data"]["specs"])

    print("【③ 报价：不带价 vs 带价】")
    r = P.api_print_quote(db, owner_id=OWNER, copies=2, vendor="某某印务")
    d = r["data"]
    check("不带价 → status=pending", r["ok"] and d["status"] == "pending", r)
    check("不带价 → price=0 不臆造", d["price"] == 0.0, d)
    check("不带价给解释话术", "不填默认价" in d["quote"]["notice"], d["quote"])
    pid_pending = d["print_order_id"]

    r = P.api_print_quote(db, owner_id=OWNER, copies=3, vendor="某某印务", unit_price=28.5)
    d = r["data"]
    check("带价 → status=quoted", d["status"] == "quoted", d)
    check("总价=单价×册数 85.5", abs(d["price"] - 85.5) < 1e-6, d["price"])
    check("单价原样回显", abs(d["quote"]["unit_price"] - 28.5) < 1e-6, d["quote"])
    pid = d["print_order_id"]
    check("书主人正确", d["owner_id"] == OWNER, d)

    print("【④ 参数越界一律拒】")
    check("册数 0 拒", P.api_print_quote(db, owner_id=OWNER, copies=0)["code"] == "bad_copies")
    check("册数负数拒", P.api_print_quote(db, owner_id=OWNER, copies=-3)["code"] == "bad_copies")
    check("册数非数字拒", P.api_print_quote(db, owner_id=OWNER, copies="三本")["code"] == "bad_copies")
    check("册数超上限拒", P.api_print_quote(db, owner_id=OWNER, copies=P.MAX_COPIES + 1)["code"] == "too_many_copies")
    check("单价负数拒", P.api_print_quote(db, owner_id=OWNER, copies=1, unit_price=-1)["code"] == "bad_price")
    check("单价非数字拒", P.api_print_quote(db, owner_id=OWNER, copies=1, unit_price="很便宜")["code"] == "bad_price")

    print("【⑤ 越权】")
    check("别人替我建单 forbidden", P.api_print_quote(db, owner_id=OWNER, actor_id=OTHER)["code"] == "forbidden")
    check("别人查我印单 forbidden", P.api_print_order(db, print_order_id=pid, actor_id=OTHER)["code"] == "forbidden")
    check("无登录查单 forbidden", P.api_print_order(db, print_order_id=pid)["code"] == "forbidden")
    check("别人改我印单状态 forbidden",
          P.api_print_set_status(db, print_order_id=pid, actor_id=OTHER, status="confirmed")["code"] == "forbidden")
    check("查不存在的单 not_found", P.api_print_order(db, print_order_id="print_xxx", actor_id=OWNER)["code"] == "not_found")

    print("【⑥ 状态机 + 幂等】")
    r = P.api_print_order(db, print_order_id=pid, actor_id=OWNER)
    check("查单 ok 且 next 含 confirmed", r["ok"] and "confirmed" in r["data"]["next_status"], r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="confirmed")
    check("quoted→confirmed 合法", r["ok"] and r["data"]["status"] == "confirmed", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="confirmed")
    check("幂等：同状态 unchanged=True 不报错", r["ok"] and r["data"]["unchanged"] is True, r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="done")
    check("跨级 confirmed→done 拒 bad_transition", r["code"] == "bad_transition", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="printing")
    check("confirmed→printing 通", r["data"]["status"] == "printing", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="cancelled")
    check("已开印不许取消", r["code"] == "bad_transition", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="shipped", vendor="实际印务")
    check("printing→shipped 通且回填厂商", r["data"]["status"] == "shipped" and r["data"]["vendor"] == "实际印务", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="done")
    check("shipped→done 通", r["data"]["status"] == "done", r)
    r = P.api_print_set_status(db, print_order_id=pid, actor_id=OWNER, status="quoted")
    check("终态不许回写", r["code"] == "bad_transition", r)

    print("【⑦ 野状态值不静默落库】")
    r = P.api_print_set_status(db, print_order_id=pid_pending, actor_id=OWNER, status="发货了")
    check("野状态 bad_status", r["code"] == "bad_status", r)
    r = P.api_print_set_status(db, print_order_id=pid_pending, actor_id=OWNER, status="cancelled")
    check("pending→cancelled 合法", r["data"]["status"] == "cancelled", r)

    print("【⑧ 续添后防印旧版】")
    # §8.4：往里再添一篇 → 电子书时间戳晚于上一张未取消印单
    new_story(db, "s3", OWNER, "晚年", ["我六十岁学了画画"])
    gen2 = book_api.api_generate_ebook(db, owner_id=OWNER)
    check("续添重生成成功", gen2["ok"], gen2)
    r = P.api_print_catalog(db, owner_id=OWNER, book_spec="A5")
    d = r["data"]
    check("条目数随续添增长到 4", d["specs"]["entry_count"] == 4, d["specs"])
    check("last_print_order 给最近一张", d["last_print_order"] is not None, d)

    print("【⑨ 信封 + 我的印单列表】")
    r = P.api_print_my_orders(db, owner_id=OWNER)
    check("列表 count>=2", r["ok"] and r["data"]["count"] >= 2, r["data"].get("count"))
    check("列表按新在前", r["data"]["orders"][0]["created_at"] >= r["data"]["orders"][-1]["created_at"], r["data"])
    r = P.api_print_my_orders(db, owner_id=OTHER)
    check("别人看不到我的印单", r["data"]["count"] == 0, r["data"])
    r = P.api_print_my_orders(db, owner_id="")
    check("缺 owner_id 拒", r["ok"] is False and r["code"] == "missing_owner_id")
    r = P.api_print_quote(db, owner_id=OWNER, copies=1, unit_price=10)
    check("信封四键齐", set(["ok", "data", "error", "code"]).issubset(set(r.keys())), r.keys())

    print(f"\n通过 {PASS} 项，失败 {FAIL} 项")
    try:
        db.close()
    except Exception:
        pass
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
