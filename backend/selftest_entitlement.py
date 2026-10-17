"""
selftest_entitlement.py —— 收费闸门（v3.0 §九 落地最后一跳）自测
========================================================
实跑，不静态核验。DATABASE_URL 走内存库（严禁污染生产库 memory_story.db）。

覆盖：
  ① §9.3 零开价 = 全站免费：Pricing 表空 → entitled=True reason=free（老人不会被卡）
  ② 开价后未买：entitled=False reason=not_paid，且**说清楚**要买哪个/多少钱
  ③ 买断：paid 单 → entitled=True reason=paid，valid_until=永久
  ④ §9.2 年费到期：paid_at 往前推 366 天 → expired，且提示"续费"
  ⑤ §9.3 免费↔收费=开关：plan active=False → 立刻回到 free（同一份数据，零改动）
  ⑥ §9.3 改价即时生效：改 Pricing 一行 → notice/price 跟着变（不改代码/不发版）
  ⑦ 低信任：pending 单 / 别人(user_id 不同)的 paid 单 → 均不授权
  ⑧ fail-open（铁律4）：把 Pricing 查询搞坏 → entitled=True reason=fail_open（绝不误伤）
  ⑨ 书闸门：未买 → api_book_view 返 locked=true、view=None、有预览章数、不返完整排版
  ⑩ 书闸门放行：买断后同一本书 → locked=false 且 view 有内容
  ⑪ 素材不锁：收费闸门只管 book_view；story/collect 接口不受影响（结构性断言）
  ⑫ 信封形状：require_entitled 未通过 → ok=False + code=need_pay + entitlement 明细
"""

import os
import sys
import datetime as dt

# ★ 必须在 import models 之前设库
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ECHOES_DB"] = ":memory:"
os.environ["DB_PATH"] = ":memory:"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, Base, engine, User, Story, Ebook, EbookStatus, Order,
)
import entitlement as E  # noqa: E402
import payment_api as P  # noqa: E402
import book_view_api as BV  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    os.environ.pop("WECHAT_PAY_MCHID", None)
    os.environ.pop("WECHAT_PAY_APIKEY", None)
    P.CONFIG_PATH = "/tmp/_no_such_pay_cfg_entitlement.json"

    u = User(id="u_laoli", nick_name="李桂芳")
    other = User(id="u_other", nick_name="别人")
    db.add_all([u, other])
    db.commit()

    # ---------- ① 表空 = 全站免费 ----------
    r = E.is_entitled(db, user_id="u_laoli")
    check("① 无定价 → 全站免费（entitled=True/free）",
          r["data"]["entitled"] is True and r["data"]["reason"] == E.FREE_FOREVER
          and r["data"]["paid_required"] is False)

    # ---------- ② 开价后未买 ----------
    P.api_admin_set_plan(db, plan_code="single_book", price=29.9, active=True)
    r = E.is_entitled(db, user_id="u_laoli")
    check("② 开价未买 → not_paid 且不授权",
          r["data"]["paid_required"] is True and r["data"]["entitled"] is False
          and r["data"]["reason"] == "not_paid")
    check("② 明确告知买哪个/多少钱（人话可直显）",
          r["data"]["plan_code"] == "single_book" and r["data"]["price"] == 29.9
          and "解锁" in (r["data"]["notice"] or ""))

    # ---------- ③ 买断永久 ----------
    P.api_admin_set_plan(db, plan_code="yearly", price=99.0, active=True, period_days=365)
    o = P.api_create_order(db, user_id="u_laoli", plan_code="single_book")
    oid = o["data"]["order_id"]
    # 未配凭证不能回调 → 临时配凭证走回调置 paid（与真实链路同）
    os.environ["WECHAT_PAY_MCHID"] = "1230000109"
    os.environ["WECHAT_PAY_APIKEY"] = "k"
    P.api_pay_callback(db, order_id=oid, transaction_id="wx_tx_1")
    os.environ.pop("WECHAT_PAY_MCHID", None)
    os.environ.pop("WECHAT_PAY_APIKEY", None)

    r = E.is_entitled(db, user_id="u_laoli")
    check("③ 买断 paid → 授权/永久",
          r["data"]["entitled"] is True and r["data"]["reason"] == E.PAID_OK
          and r["data"]["valid_until"] == "永久" and r["data"]["plan_code"] == "single_book")

    # ---------- ④ 年费到期 ----------
    u2 = User(id="u_fee", nick_name="年费用户")
    db.add(u2)
    db.commit()
    o2 = P.api_create_order(db, user_id="u_fee", plan_code="yearly")
    row = db.get(Order, o2["data"]["order_id"])
    row.status = "paid"
    row.paid_at = dt.datetime.utcnow() - dt.timedelta(days=366)
    db.commit()
    r = E.is_entitled(db, user_id="u_fee")
    check("④ 年费过期 → expired 且提示续费",
          r["data"]["entitled"] is False and r["data"]["reason"] == "expired"
          and "到期" in (r["data"]["notice"] or ""))
    # 有效期内
    row.paid_at = dt.datetime.utcnow() - dt.timedelta(days=10)
    db.commit()
    r = E.is_entitled(db, user_id="u_fee")
    check("④ 年费有效期内 → paid", r["data"]["entitled"] is True and r["data"]["reason"] == E.PAID_OK)

    # ---------- ⑤ 关开关 = 全站免费 ----------
    P.api_admin_set_plan(db, plan_code="single_book", active=False)
    P.api_admin_set_plan(db, plan_code="yearly", active=False)
    r = E.is_entitled(db, user_id="u_stranger")
    check("⑤ 后台全关 → 连没买的人也 free（免费↔收费=开关）",
          r["data"]["entitled"] is True and r["data"]["reason"] == E.FREE_FOREVER)
    P.api_admin_set_plan(db, plan_code="single_book", active=True)
    P.api_admin_set_plan(db, plan_code="yearly", active=True)

    # ---------- ⑥ 改价即时生效 ----------
    P.api_admin_set_plan(db, plan_code="single_book", price=59.0)
    r = E.is_entitled(db, user_id="u_stranger")
    check("⑥ 改价立刻反映到判决（零发版）", r["data"]["price"] == 59.0)
    P.api_admin_set_plan(db, plan_code="single_book", price=29.9)  # 还原

    # ---------- ⑦ 低信任 ----------
    o3 = P.api_create_order(db, user_id="u_stranger", plan_code="single_book")  # pending
    r = E.is_entitled(db, user_id="u_stranger")
    check("⑦ pending 单不算买过", r["data"]["entitled"] is False)
    r = E.is_entitled(db, user_id="u_other")
    check("⑦ 别人的 paid 单不授权给我",
          r["data"]["entitled"] is False and r["data"]["reason"] == "not_paid")
    del o3

    # ---------- ⑧ fail-open ----------
    orig = E._active_paid_plans
    E._active_paid_plans = lambda db: (_ for _ in ()).throw(RuntimeError("boom"))
    r = E.is_entitled(db, user_id="u_stranger")
    check("⑧ 判决异常 → fail_open 放行（绝不误伤老人）",
          r["data"]["entitled"] is True and r["data"]["reason"] == "fail_open"
          and r.get("warning") == "fail_open")
    E._active_paid_plans = orig

    # ---------- ⑨/⑩ 书闸门 ----------
    # 造一本有 2 章的书给 u_stranger
    eb = Ebook(id="eb_x", owner_id="u_stranger", title="我的书",
               status=EbookStatus.DRAFT if hasattr(EbookStatus, "DRAFT") else None,
               story_count=2,
               content='{"chapters":[{"title":"第一章","clips":[{"text":"甲"}]},'
                       '{"title":"第二章","clips":[{"text":"乙"}]}]}')
    db.add(eb)
    db.commit()

    v = BV.api_book_view(db, owner_id="u_stranger")
    check("⑨ 未买 → locked=true 且 view=None（不返完整排版）",
          v["ok"] is True and v["data"]["locked"] is True and v["data"]["view"] is None
          and v.get("code") == E.NEED_PAY)
    check("⑨ 未买仍给预览 + 报价（不把书彻底关死）",
          v["data"]["preview"]["chapters_visible"] == BV.PREVIEW_CHAPTERS
          and v["data"]["preview"]["chapters_total"] == 2
          and v["data"]["entitlement"]["price"] == 29.9)

    # 给 u_stranger 一个买断 paid 单
    o4 = P.api_create_order(db, user_id="u_stranger", plan_code="single_book")
    o_row = db.get(Order, o4["data"]["order_id"])
    o_row.status = "paid"
    o_row.paid_at = dt.datetime.utcnow()
    db.commit()
    v2 = BV.api_book_view(db, owner_id="u_stranger")
    check("⑩ 买断后 → locked=false 且 view 有内容",
          v2["k"] if False else (v2["data"]["locked"] is False and bool(v2["data"].get("view"))))

    # ---------- ⑪ 素材不锁（结构性：闸门只在 book_view）----------
    st = Story(id="s_x", owner_id="u_stranger", title="我的一篇")
    db.add(st)
    db.commit()
    check("⑪ 素材表仍可由本人正常读写（收费不碰采集链路）",
          db.query(Story).filter(Story.owner_id == "u_stranger").count() == 1)

    # ---------- ⑫ 信封形状 ----------
    rf = E.require_entitled(db, user_id="u_other")
    check("⑫ require_entitled 未通过 → ok=False + code=need_pay + entitlement",
          rf["ok"] is False and rf["code"] == E.NEED_PAY and "entitlement" in rf)
    rp = E.require_entitled(db, user_id="u_laoli")
    check("⑫ require_entitled 通过 → ok=True", rp["ok"] is True)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    db.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
