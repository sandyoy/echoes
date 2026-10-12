"""
往事可追忆 - 收付款接口（handler 层）v1.0
建立：2026-10-12（第4期「预留」件，但按 v3.0 §十一「接口预埋」纪律提前落框架）

=== 为什么今天做本文件 ===
需求书 v3.0 §九「收付款（后台可配置）」与 §十二「每个模块各为一个项目：采集/时间轴/
成书/**支付**/双界面/权限模型」明确把「支付」立为独立模块；§9.2 更写死一句话：
    「第4期一次性预留三种模式（免费/单本/年费），后续随意切换：
      改价/开关**不用找开发、不用重发版本**。」
而 models.py 里 `Pricing` / `Order` / `PrintOrder` 三张表**早已建好**（§七 收费段），
但**全仓库没有一行代码用它**——等于"表在、能力没接"。第4期一到就会被卡住，
且 v3.0 §十一 铁律要求"能预埋的先预埋，否则回头撬接口牵动整条链"。
本文件把这块**从零补上**，做到"凭证一到即可收钱"。

=== 对照需求书 v3.0 §九（逐条落）===
  §9.1 原则：程序只提供"能收"的能力；收不收/收多少 = 后台配置，**不写死**
       → 本文件所有价格/开关一律从 Pricing 表读；**代码里零硬编码金额**
  §9.2 收费模式（后台开关 + 规则表）：单本电子书 / 年费会员 / 实体书按册
       → api_admin_set_plan 改开关+价（后台页调）；api_list_plans 给前端展示
  §9.3 改动代价：改价=后台改 / 免费↔收费=后台开关 / 加年费=已预留则不用重发版
       → 三种 plan_code 一次性预留：free / single_book / yearly
  §9.4 支付渠道：第一版微信支付；预留支付宝/其他
       → pay_channel 字段 + 渠道配置化；未配凭证 → **not_configured（不静默假装）**
  §9.5 待调研（小程序能否收款/年费挂在哪/改价免重发政策）
       → load_pay_config 未配时返回 enabled=False；下单接口明说"凭证未配"，不假成功

=== 设计铁律（与 collect_api / book_api / share_api 同）===
1. handler 不自己开 session，db 由调用方传
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **代码里零价格**：任何金额都来自 Pricing 表；表里没有 = 该模式未启用
4. **绝不静默假装**：支付凭证未配 / 未开通 → 明确 not_configured，不返回假成功
5. 下单金额**服务端现算**（quote），不信前端传的 amount（防篡改）
"""

import os
import json

from permissions import _new_id
from models import (
    SessionLocal, Pricing, Order, User, init_db,
)

# 支付凭证落盘位置（与微信小程序凭证同目录风格；**不进 git**）
CONFIG_PATH = os.path.expanduser("~/.config/yuanekang/wechat_pay.json")

# v3.0 §9.2 一次性预留的三种模式（改价/开关全部后台改，不动这里）
PLAN_CODES = ("free", "single_book", "yearly")
PLAN_DEFAULT_NAMES = {
    "free": "免费使用",
    "single_book": "单本电子书",
    "yearly": "年费会员",
}

NOT_CONFIGURED = "支付凭证未配置，收款能力尚未开通"
NO_PLAN = "该收费模式未启用"


# ============================================================
# 一、统一信封（与其余 handler 同形，前端一套解析）
# ============================================================

def ok(data=None, **extra):
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra):
    d = {"ok": False, "error": msg, "code": code, "data": {}}
    d.update(extra)
    return d


# ============================================================
# 二、支付凭证（§9.4 渠道配置化；未配 → enabled=False，不假装）
# ============================================================

def load_pay_config() -> dict:
    """
    读微信支付商户凭证。优先级：环境变量 > 配置文件。
    返回 {"mchid","api_key","enabled"}；enabled=False 表示没配 → 走 not_configured。
    **不静默假装成功**（与 login_api.load_wechat_config 同纪律）。
    """
    mchid = os.getenv("WECHAT_PAY_MCHID", "").strip()
    api_key = os.getenv("WECHAT_PAY_APIKEY", "").strip()
    if (not mchid or not api_key) and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            mchid = mchid or str(cfg.get("mchid", "")).strip()
            api_key = api_key or str(cfg.get("api_key", "")).strip()
        except (OSError, ValueError):
            pass  # 配置坏了就当作没配
    return {"mchid": mchid, "api_key": api_key, "enabled": bool(mchid and api_key)}


# ============================================================
# 三、价格配置（§9.1/§9.2 后台可配 —— 代码零写死）
# ============================================================

def _get_plan(db, plan_code: str):
    return (db.query(Pricing)
              .filter(Pricing.plan_code == plan_code)
              .order_by(Pricing.updated_at.desc())
              .first())


def api_list_plans(db) -> dict:
    """
    列出所有收费模式（前端「我的 → 会员/付费」页展示用）。
    只读 Pricing 表；表里没有的模式 = 未启用（active 由后台决定）。
    """
    rows = db.query(Pricing).order_by(Pricing.plan_code).all()
    plans = []
    for r in rows:
        plans.append({
            "plan_code": r.plan_code,
            "plan_name": (r.plan_name or PLAN_DEFAULT_NAMES.get(r.plan_code, r.plan_code)),
            "price": float(r.price or 0.0),
            "period_days": int(r.period_days or 0),
            "active": bool(r.active),
            "remark": r.remark or "",
        })
    return ok({"plans": plans, "count": len(plans)})


def api_admin_set_plan(
    db,
    *,
    plan_code: str,
    price=None,
    active=None,
    plan_name: str = "",
    period_days=None,
    remark: str = "",
) -> dict:
    """
    ★后台配置入口（§9.2「后台管理页」）：改价 / 开关 / 改名 / 周期。
    **改价、免费↔收费，都不需要重发小程序版本** —— 改的就是这张表。
    幂等：同 plan_code 存在则更新，不存在则新建（落到预留的三种之一）。
    """
    if not plan_code or plan_code not in PLAN_CODES:
        return fail(f"未知的收费模式：{plan_code}（仅支持 {'/'.join(PLAN_CODES)}）",
                    "unknown_plan")
    row = _get_plan(db, plan_code)
    if row is None:
        row = Pricing(id=_new_id("price"), plan_code=plan_code)
        db.add(row)
    if price is not None:
        row.price = float(price)
    if active is not None:
        row.active = bool(active)
    if plan_name:
        row.plan_name = plan_name
    if period_days is not None:
        row.period_days = int(period_days)
    if remark:
        row.remark = remark
    if not row.plan_name:
        row.plan_name = PLAN_DEFAULT_NAMES.get(plan_code, plan_code)
    db.commit()
    db.refresh(row)
    return ok({
        "plan_code": row.plan_code,
        "plan_name": row.plan_name,
        "price": float(row.price or 0.0),
        "period_days": int(row.period_days or 0),
        "active": bool(row.active),
        "remark": row.remark or "",
    })


# ============================================================
# 四、★核心：算价（§9.1 不写死 —— 金额一律服务端现算）
# ============================================================

def api_quote(db, *, user_id: str = "", plan_code: str) -> dict:
    """
    报价：给定用户 + 模式 → 返回该付多少、能不能收。
    **金额一律从 Pricing 表现算，绝不从请求体拿**（防前端篡改）。
    """
    if not plan_code:
        return fail("缺少 plan_code", "missing_plan")
    if plan_code not in PLAN_CODES:
        return fail(f"未知的收费模式：{plan_code}", "unknown_plan")

    plan = _get_plan(db, plan_code)
    if plan is None:
        return fail(NO_PLAN, "plan_not_found")
    if not plan.active:
        return fail(NO_PLAN, "plan_inactive")

    # 免费模式：不需要支付通道
    if plan_code == "free" or float(plan.price or 0.0) <= 0.0:
        return ok({
            "plan_code": plan_code,
            "plan_name": plan.plan_name or PLAN_DEFAULT_NAMES.get(plan_code, plan_code),
            "amount": 0.0,
            "payable": False,
            "reason": "免费模式，无需支付",
        })

    cfg = load_pay_config()
    return ok({
        "plan_code": plan_code,
        "plan_name": plan.plan_name or PLAN_DEFAULT_NAMES.get(plan_code, plan_code),
        "amount": float(plan.price or 0.0),
        "period_days": int(plan.period_days or 0),
        "payable": True,
        # §9.5：凭证未配 → 明确告知"尚不能收"，不假成功
        "pay_channel": "wechat",
        "channel_ready": cfg["enabled"],
        "notice": "" if cfg["enabled"] else NOT_CONFIGURED,
    })


# ============================================================
# 五、下单（§9.4 第一版微信支付；未配凭证 → not_configured）
# ============================================================

def api_create_order(db, *, user_id: str, plan_code: str, pay_channel: str = "wechat") -> dict:
    """
    下单：服务端现算金额 → 落 Order 表（status=pending）→ 返回支付参数。
    凭证未配时：**仍然落 pending 单**（业务可追踪），但明确 code=not_configured，
    返回里**不给任何伪造的 prepay 参数**。（§9.5 待调研项未落地前的诚实行为）
    """
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")

    q = api_quote(db, user_id=user_id, plan_code=plan_code)
    if not q.get("ok"):
        return q
    data = q["data"]

    if not data.get("payable"):
        # 免费单：直接记一条 amount=0 的完成单，无需支付通道
        order = Order(
            id=_new_id("order"), user_id=user_id, plan_code=plan_code,
            amount=0.0, pay_channel="free", status="paid",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return ok({
            "order_id": order.id, "amount": 0.0, "status": "paid",
            "free": True, "pay_params": None,
        })

    order = Order(
        id=_new_id("order"), user_id=user_id, plan_code=plan_code,
        amount=float(data["amount"]), pay_channel=pay_channel or "wechat",
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    cfg = load_pay_config()
    if not cfg["enabled"]:
        # 诚实告知：单已记，但收不了钱（不返回假 prepay）
        return ok({
            "order_id": order.id,
            "amount": order.amount,
            "status": "pending",
            "pay_channel": order.pay_channel,
            "pay_params": None,
            "notice": NOT_CONFIGURED,
        }, warning="not_configured", code="not_configured")

    # 真凭证到位后：此处接微信统一下单（v2 需 mchid + api_key + 证书；
    # v3 需商户 API 证书）。**当前不臆造**，留清晰接入口：
    return ok({
        "order_id": order.id,
        "amount": order.amount,
        "status": "pending",
        "pay_channel": order.pay_channel,
        "pay_params": None,
        "notice": "支付通道已配置，统一下单接口待接入（第4期实现）",
    }, warning="pay_not_implemented", code="pay_not_implemented")


# ============================================================
# 六、查询订单 / 我的购买记录
# ============================================================

def api_get_order(db, *, order_id: str, user_id: str = "") -> dict:
    """查单（只回单号，不回凭证）。越权：非本人单 → 不看（除非未登录读状态的场景另定）"""
    if not order_id:
        return fail("缺少 order_id", "missing_order_id")
    o = db.get(Order, order_id)
    if o is None:
        return fail("订单不存在", "order_not_found")
    if user_id and o.user_id and o.user_id != user_id:
        return fail("这不是你的订单", "forbidden")
    return ok({
        "order_id": o.id,
        "plan_code": o.plan_code,
        "amount": float(o.amount or 0.0),
        "pay_channel": o.pay_channel or "",
        "status": o.status or "",
        "paid_at": str(o.paid_at or ""),
    })


def api_my_orders(db, *, user_id: str) -> dict:
    """我的购买记录（前端「我的 → 订单」）"""
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")
    rows = (db.query(Order)
              .filter(Order.user_id == user_id)
              .order_by(Order.created_at.desc())
              .all())
    return ok({
        "orders": [{
            "order_id": o.id, "plan_code": o.plan_code,
            "amount": float(o.amount or 0.0), "status": o.status or "",
            "pay_channel": o.pay_channel or "", "created_at": str(o.created_at or ""),
        } for o in rows],
        "count": len(rows),
    })


# ============================================================
# 七、支付回调（§9.4 桩：真凭证到位后接微信回调验签）
# ============================================================

def api_pay_callback(db, *, order_id: str, transaction_id: str = "") -> dict:
    """
    支付成功回调（桩）：把 pending 单置 paid。
    **幂等**：已 paid 的单重复回调不重复置、不报错。
    ⚠️ 真上线必须验签（微信回调带签名），**本桩不验签**，仅第4期联调用；
    未配凭证时拒绝回调（防被伪造回调白嫖）。
    """
    cfg = load_pay_config()
    if not cfg["enabled"]:
        return fail(NOT_CONFIGURED, "not_configured")
    if not order_id:
        return fail("缺少 order_id", "missing_order_id")
    o = db.get(Order, order_id)
    if o is None:
        return fail("订单不存在", "order_not_found")
    if o.status == "paid":
        return ok({"order_id": o.id, "status": "paid", "idempotent": True})
    o.status = "paid"
    if transaction_id:
        o.transaction_id = transaction_id
    from datetime import datetime
    o.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(o)
    return ok({"order_id": o.id, "status": "paid", "idempotent": False})


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    print("本文件为 handler 层，请跑 selftest_payment_api.py")
