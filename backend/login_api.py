"""
往事可追忆 - 微信登录态（code2session）接口 v1

=== 为什么需要这一层（第1期"能录进来"的最后一块后端拼图）===
前端（小龙虾）所有采集接口都要传 user_id / viewer_id，
而 user_id 的官方来源只有一个：**微信登录 code 换 openid**。
此前 09-26 已在口径单里答过"user_id = 微信 openid"，但**取 openid 的这一步没人做**，
前端只能先写死假 id —— 真机上线必炸。本文件补齐这一步。

=== 与已有模块的关系 ===
- 出口给前端的两个接口：
    POST /api/echoes/login          code → user_id（同时建/更新 User 行）
    GET  /api/echoes/login/profile  user_id → 昵称/头像/ui_mode（进小程序先拉这个，决定标准版/大字版）
- 换到 openid 之后**自动串上"待认领"**：调 claim.claim_everything_for()，
  这样"老李一登录，等他认领的故事自动归位"这条链路一次打通，前端只需调这 1 个接口。
- ui_mode 是 v2.4 的第9条（双界面 标准版/大字版），落点就是 User.ui_mode，本文件读它。

=== 铁律遵守（v2.4 第十四节）===
- 不编造：真实 code2session 要 appid+secret，**本机没有**（~/.config 下无 wechat 凭证）。
  故本文件把"真网络调用"写在 `_code2session_real()` 里并标注【未实测】，
  默认走 `_code2session_stub()`（可离线自测），两条路径**由 config 显式切换**，绝不静默假装成功。
- 静态核验 ≠ 通过：本文件自测 `selftest_login.py` 实跑通过才算数。

=== 安全 ===
appid/secret **不进仓库**：从环境变量或 ~/.config/yuanekang/wechat_mp.json 读（0600）。
"""

from datetime import datetime
import hashlib
import json
import os

from models import get_db, User, UiMode  # noqa: F401  (UiMode 供调用方复用)

# ============================================================
# 配置读取（secret 绝不硬编码、绝不进仓库）
# ============================================================

CONFIG_PATH = os.path.expanduser("~/.config/yuanekang/wechat_mp.json")


def load_wechat_config() -> dict:
    """
    读微信小程序凭证。优先级：环境变量 > 配置文件。
    返回 {"appid": str, "secret": str, "enabled": bool}
    enabled=False 表示没配凭证 → 走桩（自测/联调用），**不假装成功**。
    """
    appid = os.getenv("WECHAT_MP_APPID", "").strip()
    secret = os.getenv("WECHAT_MP_SECRET", "").strip()

    if (not appid or not secret) and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            appid = appid or str(cfg.get("appid", "")).strip()
            secret = secret or str(cfg.get("secret", "")).strip()
        except (OSError, ValueError):
            pass  # 配置坏了就当作没配，走桩

    return {"appid": appid, "secret": secret, "enabled": bool(appid and secret)}


# ============================================================
# 信封（与 collect_api / claim_api 口径一致，前端只用认一种）
# ============================================================

def ok(data=None, **extra) -> dict:
    d = {"ok": True, "data": data if data is not None else {}}
    d.update(extra)
    return d


def fail(msg: str, code: str = "bad_request", **extra) -> dict:
    d = {"ok": False, "code": code, "msg": msg}
    d.update(extra)
    return d


# ============================================================
# 一、stub 换 openid（离线自测用；真机联调前必须切真调用）
# ============================================================

def _code2session_stub(code: str) -> dict:
    """
    桩：code → 稳定伪 openid。
    稳定 = 同一个 code 永远算出同一个 openid（自测可断言、可重复跑）。
    形状与真实 code2session 返回**完全一致**，前端无需感知真假。
    """
    if not code or not str(code).strip():
        return {"errcode": 40029, "errmsg": "code 为空"}
    h = hashlib.sha256(str(code).strip().encode("utf-8")).hexdigest()[:24]
    return {"openid": f"stub_{h}", "session_key": f"sk_{h[:16]}", "errcode": 0}


def _code2session_real(code: str, *, appid: str, secret: str) -> dict:
    """
    真调用微信 code2session。
    【未实测】——本机无 appid/secret，沙箱无法联网到 api.weixin.qq.com 的登录接口。
    形状已按官方文档冻结：{openid, session_key} / {errcode, errmsg}。
    只需有凭证即自动生效（load_wechat_config().enabled=True 时走这里）。
    """
    import urllib.parse
    import urllib.request

    qs = urllib.parse.urlencode({
        "appid": appid, "secret": secret, "js_code": code,
        "grant_type": "authorization_code",
    })
    url = f"https://api.weixin.qq.com/sns/jscode2session?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # 网络异常不能让采集链路崩
        return {"errcode": -1, "errmsg": f"code2session 网络异常：{e}"}


def code2session(code: str, *, force_stub: bool = False) -> dict:
    """
    统一入口：有凭证走真调用，无凭证走桩。返回值形状一致。
    force_stub=True 供自测强制走桩（不依赖本机是否配了凭证）。
    """
    if not code or not str(code).strip():
        return {"errcode": 40029, "errmsg": "code 为空"}
    cfg = load_wechat_config()
    if force_stub or not cfg["enabled"]:
        return _code2session_stub(code)
    return _code2session_real(code, appid=cfg["appid"], secret=cfg["secret"])


# ============================================================
# 二、User 行读写（登录即建档 / 更新）
# ============================================================

def upsert_user(db, *, user_id: str, nick_name: str = "", avatar_url: str = "",
                phone: str = "") -> User:
    """
    登录即建/更新 User 行。**不覆盖已有值**（除非新值非空）——
    防止"老人第二次登录昵称空了把原来的抹掉"。
    phone 若带进来，走同一归一化口径（与认领钥匙一致）。
    """
    u = db.query(User).filter(User.id == user_id).first()
    if u is None:
        u = User(id=user_id, nick_name=nick_name or "", avatar_url=avatar_url or "")
        if phone:
            from permissions import _normalize_phone
            u.phone = _normalize_phone(phone)
        db.add(u)
    else:
        if nick_name:
            u.nick_name = nick_name
        if avatar_url:
            u.avatar_url = avatar_url
        if phone:
            from permissions import _normalize_phone
            u.phone = _normalize_phone(phone)
        u.last_login_at = datetime.utcnow()
    db.commit()
    return u


def get_profile(db, *, user_id: str) -> dict:
    """进小程序先拉这个：决定标准版/大字版 + 显示谁在登录。"""
    u = db.query(User).filter(User.id == user_id).first()
    if u is None:
        return {}
    return {
        "user_id": u.id,
        "nick_name": u.nick_name or "",
        "avatar_url": u.avatar_url or "",
        "ui_mode": u.ui_mode.value if hasattr(u.ui_mode, "value") else str(u.ui_mode),
        "has_phone": bool(u.phone),
        "phone_masked": _mask_phone(u.phone) if u.phone else "",
    }


def _norm_ui_mode(ui_mode: str) -> str:
    """
    界面模式归一化。DB 枚举实际值是 standard / large（models.UiMode），
    但公众号/前端口头叫法有 senior / big / 大字版 等多种 →
    统一收口在这里，避免"前端传 senior 后端不认"这类静默失败。
    返回 DB 值（"standard"/"large"）或 "" 表示非法。
    """
    m = str(ui_mode or "").strip().lower()
    if m in ("standard", "normal", "标准", "standard_ui"):
        return "standard"
    if m in ("large", "senior", "big", "elder", "大字", "大字版", "senior_ui"):
        return "large"
    return ""


def set_ui_mode(db, *, user_id: str, ui_mode: str) -> bool:
    """双界面切换（标准版 standard / 大字版 large）。v2.4 第9条。"""
    norm = _norm_ui_mode(ui_mode)
    if not norm:
        return False
    u = db.query(User).filter(User.id == user_id).first()
    if u is None:
        return False
    u.ui_mode = UiMode.LARGE if norm == "large" else UiMode.STANDARD
    db.commit()
    return True


def _mask_phone(phone: str) -> str:
    p = (phone or "").strip()
    if len(p) < 7:
        return "***"
    return f"{p[:3]}****{p[-4:]}"


# ============================================================
# 三、API handlers（信封 + 中文报错，供 fastapi adapter 调）
# ============================================================

def api_login(db, *, code: str, nick_name: str = "", avatar_url: str = "",
              phone: str = "", force_stub: bool = False) -> dict:
    """
    登录总入口：code → openid → upsert User → **自动串联待认领** → 返回首页所需一切。

    返回值里 owners / mentioned_count 来自 claim 模块（"登录即认领"），
    所以前端**只调这一个接口**就能拿到：我是谁 + 我有哪些书 + 有几篇提到了我。
    """
    if not code or not str(code).strip():
        return fail("缺少登录 code", "missing_code")

    sess = code2session(code, force_stub=force_stub)
    if sess.get("errcode", 0) != 0 or not sess.get("openid"):
        return fail(f"微信登录失败：{sess.get('errmsg', '未知错误')}",
                    "code2session_failed", errcode=sess.get("errcode"))

    user_id = sess["openid"]

    # 判断"新用户"必须**在建档之前**查（不然永远 False）——09-29 自测抓到的真 bug
    is_new_user = db.query(User).filter(User.id == user_id).first() is None

    upsert_user(db, user_id=user_id, nick_name=nick_name,
                avatar_url=avatar_url, phone=phone)

    # 串联待认领：登录即自动认领（老李一登录，等他认领的故事自动归位）
    try:
        from claim import claim_everything_for
        claimed = claim_everything_for(db, user_id=user_id, phone=phone)
    except Exception as e:  # 认领失败不该让登录整体失败
        claimed = {"error": str(e)}

    prof = get_profile(db, user_id=user_id)
    return ok({
        "user_id": user_id,
        "is_new_user": is_new_user,
        "profile": prof,
        "owners": claimed.get("owners", []) if isinstance(claimed, dict) else [],
        "count_stories": claimed.get("count_stories", 0) if isinstance(claimed, dict) else 0,
        "mentioned_count": claimed.get("mentioned_count", 0) if isinstance(claimed, dict) else 0,
        "session_from": "stub" if not load_wechat_config()["enabled"] or force_stub else "wechat",
    })


def api_profile(db, *, user_id: str) -> dict:
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")
    prof = get_profile(db, user_id=user_id)
    if not prof:
        return fail("用户不存在", "user_not_found")
    return ok(prof)


def api_set_ui_mode(db, *, user_id: str, ui_mode: str) -> dict:
    if not user_id:
        return fail("缺少 user_id", "missing_user_id")
    norm = _norm_ui_mode(ui_mode)
    if not norm:
        return fail("界面模式只能是 standard（标准版）或 large/senior（大字版）", "bad_ui_mode")
    if not set_ui_mode(db, user_id=user_id, ui_mode=norm):
        return fail("用户不存在", "user_not_found")
    return ok({"user_id": user_id, "ui_mode": norm})


def fresh_db():
    """自测用：内存库（与其它 selftest 同款）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


if __name__ == "__main__":
    db = fresh_db()
    print(api_login(db, code="demo_code_123", nick_name="老李", force_stub=True))
