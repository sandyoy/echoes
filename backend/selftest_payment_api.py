"""
selftest_payment_api.py —— 收付款后台配置化（v3.0 §九）自测
========================================================
实跑，不静态核验。依赖 DATABASE_URL 走内存库（严禁污染生产库 memory_story.db）。

覆盖：
  ① 后台开价：set_plan 建 single_book=29.9 并 active → list_plans 能读到
  ② §9.1 零写死：quote 的金额来自 Pricing 表（改表 → 报价跟着变），非代码常量
  ③ §9.2 三模式预留：free / single_book / yearly 都能配
  ④ free 模式：quote payable=False、下单直接 paid amount=0（不走支付通道）
  ⑤ §9.3 免费↔收费=开关：plan active=False → quote 拒（plan_inactive）
  ⑥ §9.4 渠道：未配凭证 → create_order 单落 pending 且 code=not_configured（**不假成功**）
  ⑦ 凭证配置后 load_pay_config.enabled=True；此时下单给 pay_not_implemented（不臆造 prepay）
  ⑧ 防篡改：quote 不看请求体金额（接口无 amount 入参）——由用例②间接证
  ⑨ 回调幂等：paid 单重复回调 idempotent=True；未配凭证时回调被拒（防伪造白嫖）
  ⑩ 查单越权：非本人单 → forbidden；本人 → 可见
  ⑪ 信封形状（ok/code）
"""

import os
import sys

# ★ 必须在 import models 之前设库（models 读 DATABASE_URL）
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ECHOES_DB"] = ":memory:"
os.environ["DB_PATH"] = ":memory:"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (  # noqa: E402
    SessionLocal, Base, engine, User,
)
import payment_api as P  # noqa: E402

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

    # 干净环境：确保环境变量没配凭证
    os.environ.pop("WECHAT_PAY_MCHID", None)
    os.environ.pop("WECHAT_PAY_APIKEY", None)
    # 避免落盘配置干扰
    P.CONFIG_PATH = "/tmp/_no_such_pay_cfg_selftest.json"

    u = User(id="u_laoli", nick_name="李桂芳")
    db.add(u)
    db.commit()

    # ---------- ① 后台开价 ----------
    r = P.api_admin_set_plan(db, plan_code="single_book", price=29.9, active=True)
    check("① set_plan 建 single_book=29.9 active", r["ok"] and r["data"]["price"] == 29.9 and r["data"]["active"])
    r = P.api_admin_set_plan(db, plan_code="yearly", price=99.0, active=True, period_days=365)
    check("① set_plan 建 yearly=99/365天", r["ok"] and r["data"]["period_days"] == 365)
    r = P.api_list_plans(db)
    codes = {p["plan_code"] for p in r["data"]["plans"]}
    check("① list_plans 至少含 single_book/yearly", {"single_book", "yearly"} <= codes)

    # ---------- ② §9.1 零写死：改表 → 报价跟着变 ----------
    q1 = P.api_quote(db, user_id="u_laoli", plan_code="single_book")
    check("② quote 读到 29.9（来自表）", q1["ok"] and q1["data"]["amount"] == 29.9)
    P.api_admin_set_plan(db, plan_code="single_book", price=39.9)
    q2 = P.api_quote(db, user_id="u_laoli", plan_code="single_book")
    check("② 改表价 → 报价变 39.9（零硬编码）", q2["ok"] and q2["data"]["amount"] == 39.9)

    # ---------- ③ §9.2 三模式预留 ----------
    P.api_admin_set_plan(db, plan_code="free", price=0.0, active=True)
    rf = P.api_quote(db, user_id="u_laoli", plan_code="free")
    ry = P.api_quote(db, user_id="u_laoli", plan_code="yearly")
    check("③ free/single_book/yearly 三模式均可报价", rf["ok"] and ry["ok"])

    # ---------- ④ free 模式 ----------
    check("④ free → payable=False", rf["data"]["payable"] is False)
    of = P.api_create_order(db, user_id="u_laoli", plan_code="free")
    check("④ free 下单即 paid amount=0（不走支付）",
          of["ok"] and of["data"]["status"] == "paid" and of["data"]["amount"] == 0.0)

    # ---------- ⑤ §9.3 免费↔收费 = 开关 ----------
    P.api_admin_set_plan(db, plan_code="single_book", active=False)
    qoff = P.api_quote(db, user_id="u_laoli", plan_code="single_book")
    check("⑤ 关掉开关 → quote 拒 plan_inactive",
          (not qoff["ok"]) and qoff["code"] == "plan_inactive")
    P.api_admin_set_plan(db, plan_code="single_book", active=True)  # 复原

    # ---------- ⑥ §9.4 未配凭证 → not_configured（不假成功） ----------
    o1 = P.api_create_order(db, user_id="u_laoli", plan_code="single_book")
    check("⑥ 未配凭证：单落 pending", o1["ok"] and o1["data"]["status"] == "pending")
    check("⑥ 未配凭证：code=not_configured 且 pay_params 为 None（不假成功）",
          o1.get("code") == "not_configured" and o1["data"]["pay_params"] is None)

    # ---------- ⑦ 配了凭证 ----------
    os.environ["WECHAT_PAY_MCHID"] = "1230000109"
    os.environ["WECHAT_PAY_APIKEY"] = "dummy_key_for_selftest"
    cfg = P.load_pay_config()
    check("⑦ 配凭证 → enabled=True", cfg["enabled"] is True)
    o2 = P.api_create_order(db, user_id="u_laoli", plan_code="single_book")
    check("⑦ 凭证就绪：code=pay_not_implemented（不臆造 prepay）",
          o2.get("code") == "pay_not_implemented" and o2["data"]["pay_params"] is None)

    # ---------- ⑨ 回调幂等 + 防伪造 ----------
    cb1 = P.api_pay_callback(db, order_id=o2["data"]["order_id"], transaction_id="wx_tx_001")
    check("⑨ 回调置 paid", cb1["ok"] and cb1["data"]["status"] == "paid")
    cb2 = P.api_pay_callback(db, order_id=o2["data"]["order_id"], transaction_id="wx_tx_001")
    check("⑨ 重复回调幂等（不报错、不重复置）", cb2["ok"] and cb2["data"]["idempotent"] is True)
    # 未配凭证时回调被拒
    os.environ.pop("WECHAT_PAY_MCHID", None)
    os.environ.pop("WECHAT_PAY_APIKEY", None)
    cb3 = P.api_pay_callback(db, order_id=o1["data"]["order_id"])
    check("⑨ 未配凭证：回调被拒 not_configured（防伪造白嫖）",
          (not cb3["ok"]) and cb3["code"] == "not_configured")

    # ---------- ⑩ 查单越权 ----------
    g_ok = P.api_get_order(db, order_id=o2["data"]["order_id"], user_id="u_laoli")
    check("⑩ 本人查单可见", g_ok["ok"] and g_ok["data"]["order_id"] == o2["data"]["order_id"])
    g_no = P.api_get_order(db, order_id=o2["data"]["order_id"], user_id="u_stranger")
    check("⑩ 非本人查单 → forbidden", (not g_no["ok"]) and g_no["code"] == "forbidden")

    # ---------- 我的订单 ----------
    mine = P.api_my_orders(db, user_id="u_laoli")
    check("⑩ 我的订单列表非空且含两单", mine["ok"] and mine["data"]["count"] >= 2)

    # ---------- ⑪ 信封形状 ----------
    bad = P.api_admin_set_plan(db, plan_code="not_a_plan", price=1)
    check("⑪ 未知 plan → ok=False + code + data={}",
          (bad["ok"] is False) and "code" in bad and bad["data"] == {})
    check("⑪ 缺 plan_code → code=missing_plan",
          P.api_quote(db, user_id="u_laoli", plan_code="")["code"] == "missing_plan")

    db.close()
    total = PASS + FAIL
    print(f"\n{'='*50}\npayment_api 自测：{PASS}/{total} 通过，{FAIL} 失败\n{'='*50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
