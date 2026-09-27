"""
往事可追忆 - 待认领/认领 接口（handler 层）v1.0
第1期 A 线（2026-09-27）

=== 同 collect_api.py 的设计铁律 ===
本机**没有 fastapi/pydantic**，所以这里只写**纯函数 handler**：
  - 入参出参都是普通 dict，不 import 任何 web 框架
  - 框架适配器见 api_adapter_fastapi.py
  - 好处：现在就能自测（见 selftest_claim.py），不被框架卡住

=== 对照需求书 v2.4 第八之二节 ===
  「有 N 篇故事提到了你」→ GET  /api/echoes/claim/mentioned
  登录后自动认领          → POST /api/echoes/claim/login
  名字搜索认领（候选）    → GET  /api/echoes/claim/search
  登记人确认             → POST /api/echoes/claim/confirm
  登记待认领（写故事时）   → POST /api/echoes/claim/register

=== 铁律 ===
1. handler 不自己开 session —— 由调用方传 db
2. 统一信封 {"ok": bool, "data": {...}, "error": "..."}
3. 绝不把内部 traceback 抛给小程序，一律转成可读中文
"""

from claim import (
    register_claim, claim_everything_for, search_claims_by_name,
    confirm_by_owner, reject_claim, mentioned_stories, list_pending_claims,
    pending_mentioned_count,
)
from collect_api import ok, fail
from models import Story, Member, Claim


# ============================================================
# 一、写故事时登记人（对方可能还没账号）
# ============================================================

def api_register_claim(db, *, owner_id: str, phone: str = "",
                       display_name: str = "", story_id: str = "") -> dict:
    """
    写故事的人把人写进去 → 登记一条待认领。
    手机号 / 名字 至少给一个。
    """
    if not owner_id:
        return fail("缺少 owner_id", "bad_request")
    try:
        c = register_claim(
            db, owner_id=owner_id, phone=phone,
            display_name=display_name, story_id=(story_id or None),
        )
    except ValueError as e:
        return fail(str(e), "bad_request")
    return ok({
        "claim_id": c.id,
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        "match_type": c.match_type,
        "display_name": c.display_name,
        "phone_masked": _mask_phone(c.phone),
    })


# ============================================================
# 二、登录时总入口（前端登录后调这一个）
# ============================================================

def api_claim_on_login(db, *, user_id: str, phone: str = "") -> dict:
    """
    老李登录 → 自动认领所有等他的记录，并带回首页数字。
    返回含 mentioned_count（「有 N 篇故事提到了你」的 N）。
    """
    if not user_id:
        return fail("缺少 user_id（登录态）", "unauthorized")
    try:
        r = claim_everything_for(db, user_id=user_id, phone=phone)
    except ValueError as e:
        return fail(str(e), "bad_request")
    return ok({
        "owners": r["owners"],
        "claimed_claims": r["claimed_claims"],
        "claimed_members": r["claimed_members"],
        "mentioned_count": r["mentioned_count"],
    })


# ============================================================
# 三、「有 N 篇故事提到了你」（首页提示）
# ============================================================

def api_mentioned(db, *, user_id: str) -> dict:
    """首页用：N + 故事列表（标题/时间标签/AI摘要）。"""
    if not user_id:
        return fail("缺少 user_id（登录态）", "unauthorized")
    stories = mentioned_stories(db, user_id=user_id)
    return ok({
        "count": len(stories),
        "stories": [
            {
                "story_id": s.id,
                "title": s.title,
                "summary": s.summary,
                "time_label": s.time_label,
                "owner_id": s.owner_id,
            }
            for s in stories
        ],
    })


# ============================================================
# 四、名字搜索认领（手机号对不上时的备选路）
# ============================================================

def api_search_claim_by_name(db, *, display_name: str) -> dict:
    """按名字搜索候选（**只是候选，还没生效**）。"""
    if not (display_name or "").strip():
        return fail("请填写姓名", "bad_request")
    cands = search_claims_by_name(db, display_name=display_name)
    out = []
    for c in cands:
        s = db.get(Story, c.story_id) if c.story_id else None
        out.append({
            "claim_id": c.id,
            "display_name": c.display_name,
            "owner_id": c.owner_id,
            "story_id": c.story_id,
            "story_title": s.title if s else "",
            "need_owner_confirm": True,
        })
    return ok({"count": len(out), "candidates": out,
               "hint": "须写故事的人确认后才会生效"})


def api_confirm_claim(db, *, claim_id: str, owner_id: str, user_id: str) -> dict:
    """登记人确认「对，这就是他」→ 生效。只有登记人本人能确认。"""
    if not (claim_id and owner_id and user_id):
        return fail("缺少参数", "bad_request")
    try:
        done = confirm_by_owner(db, claim_id=claim_id, owner_id=owner_id,
                                user_id=user_id)
    except PermissionError as e:
        return fail(str(e), "forbidden")
    if not done:
        return fail("认领记录不存在", "not_found")
    return ok({"claim_id": claim_id, "status": "claimed"})


def api_reject_claim(db, *, claim_id: str, owner_id: str) -> dict:
    """登记人否认「这不是他」。"""
    if not (claim_id and owner_id):
        return fail("缺少参数", "bad_request")
    try:
        done = reject_claim(db, claim_id=claim_id, owner_id=owner_id)
    except PermissionError as e:
        return fail(str(e), "forbidden")
    if not done:
        return fail("认领记录不存在", "not_found")
    return ok({"claim_id": claim_id, "status": "rejected"})


# ============================================================
# 五、登记人视角：我还有哪些人没被认领
# ============================================================

def api_pending_claims(db, *, owner_id: str) -> dict:
    """后台/提醒用：列未认领的人。"""
    if not owner_id:
        return fail("缺少 owner_id", "bad_request")
    rows = list_pending_claims(db, owner_id=owner_id)
    return ok({
        "count": len(rows),
        "claims": [
            {
                "claim_id": c.id,
                "display_name": c.display_name,
                "phone_masked": _mask_phone(c.phone),
                "match_type": c.match_type,
                "story_id": c.story_id,
            }
            for c in rows
        ],
    })


# ============================================================
# 六、工具
# ============================================================

def _mask_phone(phone: str) -> str:
    """手机号脱敏（日志/接口回显不应带完整号）。"""
    if not phone:
        return ""
    return phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "***"
