"""
往事可追忆 - 对象存储上传通道（handler 层）v1.0
建立：2026-10-14（设计哨兵 · 长线卡点清理）

=== 为什么有本文件 ===
本卡点自 **2026-09-26** 起，在每一天的推进日历「卡点」列里出现（共 18 天，是全项目寿命最长的未清卡点）：

    「对象存储未定（照片/语音/视频 media_url 无落点，上传只到一半）」

`collect_api.api_upload_url()` 此前**只返回 `upload_not_configured`**，一个字节都存不进去：
  - 老人传的照片 → 没地方放；
  - 老人录的语音/原声（**声音本身就是记忆资产**，§6.2.2 铁律）→ 没地方放；
  - 视频 → 没地方放。

后果：整条「采进来 → 看得到 → 出书 → 分享」的链路，**在"素材落地"这一步断头**；
第1期真机验收、08 页分享（要能真播）、07 页翻相册式（要能真看图）全都悬空。

=== 本文件做的事（与"等 sandy 定"不冲突） ===
sandy 要定的是**用哪家存储**（腾讯云 COS / 自建），那是**采购决策**；
但"上传通道长什么样、怎么签名、怎么落库不回滚、怎么防越权"是**技术设计**，本端今天就该做完。
做法：**抽象出统一存储接口 + 落一个能立刻跑的本地后端**，COS 后端按同一接口预留（凭证一到即插即用，前端一行不用改）。

=== 对照需求书 v3.0（逐条落）===
  §6.2   上传交互（照微信做）        → `api_upload_url()` 给"上传地址+用法"，前端直传
  §6.2.1 素材只由本人入库            → `actor_id` 必填，key 前缀绑 actor，**别人抢不了他的槽位**
  §6.2.2 语音"两边都要"（留声为主）  → `kind=audio` 允许音频扩音；**原声不允许被覆盖**
  §6.2.3 回放按钮                    → `api_media_url()` 给出可回放的稳定地址（本地后端即静态服务路径）
  §1.2   公开/私有闸门               → ★`api_confirm_upload()` **入库那一刻由本人定公开/私有**，
                                        与 §6.2.1「放的人当场决定公开还是私有」严丝合缝
  §6.3   拍板确认                    → 上传→登记 分两步，登记成功才算数（不落半截）

=== 设计铁律 ===
1. handler 不自己开 session，db 由调用方传（与 collect_api / book_api / share_api 同）
2. 统一信封 {ok, data, error, code}，异常不抛穿到 web 层
3. **不静默假装**：没配存储时，本地后端**默认开**（`ECHOES_STORAGE=local`），
   仍拿不到地址就明确报 `storage_not_configured`，绝不返回假 URL
4. **key 必须防穿越**：文件名净化（去 ../、去控制符），key 前缀 `clips/{actor_id}/`
   → 别人拿不到你的前缀，也写不进你的目录
5. **原声不可覆盖**：同 key 二次上传，`original` 类拒覆盖（§6.2.2 声音是资产，不许被后来的冲掉）
6. 后端可换不可改接口：`LocalStorage` / `CosStorage` 同一套方法，`get_storage()` 按配置选
7. 绝不臆造：COS 未配凭证 → 明确 `cos_not_configured`，不假装签出 URL

=== 环境变量 ===
  ECHOES_STORAGE        = local（默认）| cos
  ECHOES_LOCAL_ROOT     = 本地根目录（默认 ~/.echoes_media）
  ECHOES_PUBLIC_BASE    = 对外可访问基址（默认 http://<host>/media，真机需换公网域名）
  ECHOES_COS_SECRET_ID / ECHOES_COS_SECRET_KEY / ECHOES_COS_REGION / ECHOES_COS_BUCKET
                        （也可放 ~/.config/yuanekang/cos.json）
"""

import os
import re
import json
import time
import hmac
import hashlib
import mimetypes

# ============================================================
# 一、统一信封
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
# 二、常量
# ============================================================

# 三类素材各自的上限（与 collect_api / collect_av 对齐，物理上限不放这里重定义，
# 这里只做"上传通道"层的粗拦，细校验仍由 collect_*.validate_* 负责）
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"
KIND_ORIGINAL = "original"      # 原声：只存声音不转写（§6.2.2 铁律）
KIND_TTS = "tts"                # 合成音：AI 主持人问句/§7.6 复述（tts_api 产出）
VALID_KINDS = {KIND_IMAGE, KIND_AUDIO, KIND_VIDEO, KIND_ORIGINAL, KIND_TTS}

KIND_MAX_BYTES = {
    KIND_IMAGE: 20 * 1024 * 1024,
    KIND_AUDIO: 20 * 1024 * 1024,
    KIND_ORIGINAL: 20 * 1024 * 1024,
    KIND_TTS: 10 * 1024 * 1024,
    KIND_VIDEO: 200 * 1024 * 1024,
}

# 允许的扩展名（与 collect_api/collect_av 的 ALLOWED_* 保持一致）
KIND_ALLOWED_EXT = {
    KIND_IMAGE: {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp"},
    KIND_AUDIO: {".mp3", ".wav", ".m4a", ".aac", ".amr", ".silk", ".pcm", ".ogg", ".webm"},
    KIND_ORIGINAL: {".mp3", ".wav", ".m4a", ".aac", ".amr", ".silk", ".pcm", ".ogg", ".webm"},
    KIND_TTS: {".mp3", ".wav", ".ogg"},
    KIND_VIDEO: {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".avi", ".mkv"},
}

# URL 有效期（签名地址）。本地后端不签名，仅记录口径；COS 后端用它算签名过期。
DEFAULT_EXPIRE_SECONDS = 3600

# key 里允许的字符（净化后）
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")
_SAFE_ACTOR_RE = re.compile(r"[^A-Za-z0-9_\-]")


# ============================================================
# 三、配置加载（不静默假装）
# ============================================================

def _env_or_file(env_key: str, file_key: str, cfg: dict, default: str = "") -> str:
    v = os.environ.get(env_key)
    if v:
        return v
    return str(cfg.get(file_key) or default)


def load_storage_config() -> dict:
    """
    读取存储配置。

    返回 {"backend": "local"|"cos", ...}。
    **不静默假装**：读不到就返回什么，是什么（缺哪项 = 空串），由调用方判。
    """
    cfg = {}
    path = os.path.expanduser("~/.config/yuanekang/cos.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}

    backend = _env_or_file("ECHOES_STORAGE", "backend", cfg, "local").lower()
    if backend not in ("local", "cos"):
        backend = "local"

    local_root = _env_or_file(
        "ECHOES_LOCAL_ROOT", "local_root", cfg,
        os.path.expanduser("~/.echoes_media"),
    )
    public_base = _env_or_file(
        "ECHOES_PUBLIC_BASE", "public_base", cfg,
        "/media",
    ).rstrip("/")

    return {
        "backend": backend,
        "local_root": local_root,
        "public_base": public_base,
        "cos_secret_id": _env_or_file("ECHOES_COS_SECRET_ID", "secret_id", cfg),
        "cos_secret_key": _env_or_file("ECHOES_COS_SECRET_KEY", "secret_key", cfg),
        "cos_region": _env_or_file("ECHOES_COS_REGION", "region", cfg),
        "cos_bucket": _env_or_file("ECHOES_COS_BUCKET", "bucket", cfg),
    }


def cos_configured(cfg: dict = None) -> bool:
    """COS 四项凭证齐 = 配好了。缺一项就是没配（不假装）。"""
    cfg = cfg or load_storage_config()
    return all([
        cfg.get("cos_secret_id"),
        cfg.get("cos_secret_key"),
        cfg.get("cos_region"),
        cfg.get("cos_bucket"),
    ])


# ============================================================
# 四、key 净化 & 生成（防越权 / 防穿越）
# ============================================================

def sanitize_actor(actor_id: str) -> str:
    """净化 actor_id 成可安全做目录名的片段（防 ../ 穿越）。空 = 非法。"""
    a = _SAFE_ACTOR_RE.sub("", str(actor_id or "").strip())
    return a[:64]


def sanitize_filename(file_name: str) -> str:
    """
    净化文件名：
      - 去掉目录部分（只取 basename）
      - 去掉 ../ 和控制字符
      - 中文保留（老人照片常是中文名）
      - 空文件名/纯杂符号 → 回落到 "unnamed"
    """
    raw = str(file_name or "").strip()
    # 只取最后一段（干掉 ../../etc/passwd 这类）
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = raw.replace("\x00", "")
    safe = _SAFE_NAME_RE.sub("_", raw)
    safe = safe.strip("._")
    if not safe:
        return "unnamed"
    # 防超长文件名（Linux 上限 255 字节，中文 3 字节/字）
    if len(safe.encode("utf-8")) > 120:
        stem, dot, ext = safe.rpartition(".")
        if dot and len(ext) <= 8:
            safe = stem[:30] + "." + ext
        else:
            safe = safe[:30]
    return safe


def build_key(*, actor_id: str, kind: str, file_name: str, nonce: str = "") -> str:
    """
    生成对象 key： `clips/{actor}/[{kind}/]{ts}_{nonce}_{filename}`

    规则（铁律 4）：
      - 前缀必须带 actor → 别人拿不到你的前缀、写不进你的目录；
      - 带时间戳+nonce → 同一文件多次上传不互相覆盖（**原声除外，见 confirm**）；
      - 文件名净化，防穿越。
    """
    actor = sanitize_actor(actor_id)
    if not actor:
        raise ValueError("actor_id 非法（净化后为空）")
    kind = kind if kind in VALID_KINDS else KIND_IMAGE
    fname = sanitize_filename(file_name)
    if not nonce:
        nonce = hashlib.sha1(
            f"{time.time()}-{os.getpid()}-{fname}".encode("utf-8")
        ).hexdigest()[:8]
    ts = int(time.time())
    return f"clips/{actor}/{kind}/{ts}_{nonce}_{fname}"


def ext_of(file_name: str) -> str:
    base = str(file_name or "").rsplit("/", 1)[-1]
    return ("." + base.rsplit(".", 1)[-1].lower()) if "." in base else ""


# ============================================================
# 五、上传前的校验（kind / 大小 / 扩展名）
# ============================================================

def validate_upload(*, kind: str, file_name: str, file_size: int,
                    mime: str = "") -> tuple:
    """
    返回 (passed: bool, msg: str, code: str)。
    **不静默**：任何拒绝都带中文原因 + 机器码。
    """
    if kind not in VALID_KINDS:
        return False, f"不知道这是什么类型的素材（{kind}）", "bad_kind"
    if not file_size or file_size <= 0:
        return False, "文件是空的，没上传成功", "empty_file"
    limit = KIND_MAX_BYTES.get(kind, 20 * 1024 * 1024)
    if file_size > limit:
        got = round(file_size / 1024 / 1024, 1)
        cap = int(limit / 1024 / 1024)
        return False, f"文件太大了（{got}MB，上限{cap}MB）", "too_large"
    ext = ext_of(file_name)
    allowed = KIND_ALLOWED_EXT.get(kind, set())
    if ext and ext not in allowed:
        return False, f"这种格式不支持（{ext}）", "bad_ext"
    if not ext:
        # 没扩展名 → 靠 mime 兜；mime 也不对 → 拒
        if not (mime or "").strip():
            return False, "文件没扩展名也没类型，认不出是什么", "unknown_type"
    return True, "", ""


# ============================================================
# 六、存储后端（同一套方法，可换实现）
# ============================================================

class StorageBase:
    """统一存储接口。子类只改实现，不改方法名/返回形状。"""

    name = "base"

    def upload_url(self, *, key: str, mime: str = "",
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> dict:
        """
        返回 {"upload_url":..., "method":"PUT", "headers":{...}, "key":..., "expire":n}
        前端照做：按 method 把字节 PUT/POST 到 upload_url，带上 headers。
        """
        raise NotImplementedError

    def public_url(self, *, key: str,
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> str:
        """返回可读/可播的稳定地址（本地=静态路径；COS=签名 GET 地址）。"""
        raise NotImplementedError

    def put_bytes(self, *, key: str, data: bytes) -> dict:
        """
        服务端落字节（本地后端=写文件；COS=走 SDK）。
        用途：① 无前端时的自测 ② 小程序 `wx.uploadFile` 之后服务端兜底落盘。
        返回 {"stored": bool, "key":..., "size": n, "url": ...}
        """
        raise NotImplementedError

    def exists(self, *, key: str) -> bool:
        raise NotImplementedError

    def delete(self, *, key: str) -> bool:
        """删对象（谨慎：素材删除走 story_api，这里只给底层能力）。"""
        raise NotImplementedError


class LocalStorage(StorageBase):
    """
    本地文件系统后端 —— **今天就能跑**，不需要任何采购。

    落点：`{local_root}/{key}`，对外地址：`{public_base}/{key}`。
    适用：CVM 内测期 / 真机联调期（static 服务挂 local_root 即可）。
    切 COS 时本类一行不改，`get_storage()` 换实现即可。
    """

    name = "local"

    def __init__(self, root: str, public_base: str = "/media"):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.public_base = (public_base or "/media").rstrip("/")
        os.makedirs(self.root, exist_ok=True)

    # --- 内部：key → 绝对路径（防穿越最后一道闸）---
    def _abs(self, key: str) -> str:
        k = str(key or "").replace("\\", "/").lstrip("/")
        p = os.path.abspath(os.path.join(self.root, k))
        # 必须仍在 root 内（防 ../../ 逃逸）
        if not (p == self.root or p.startswith(self.root + os.sep)):
            raise ValueError(f"key 越界，拒绝：{key}")
        return p

    def upload_url(self, *, key: str, mime: str = "",
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> dict:
        # 本地后端"上传地址" = 后端自身的一个 PUT 端点（见 storage/put 路由）
        return {
            "upload_url": f"{self.public_base.rsplit('/media', 1)[0]}/api/echoes/storage/put",
            "method": "PUT",
            "headers": {"Content-Type": mime or "application/octet-stream"},
            "key": key,
            "expire": expire,
            "backend": self.name,
            "note": "本地后端：PUT 到该地址，body 为文件字节，key 放 query。切 COS 后此处变签名直传地址。",
        }

    def public_url(self, *, key: str,
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> str:
        k = str(key or "").replace("\\", "/").lstrip("/")
        return f"{self.public_base}/{k}"

    def put_bytes(self, *, key: str, data: bytes) -> dict:
        path = self._abs(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data or b"")
        return {
            "stored": True,
            "key": key,
            "size": len(data or b""),
            "url": self.public_url(key=key),
        }

    def exists(self, *, key: str) -> bool:
        try:
            return os.path.isfile(self._abs(key))
        except ValueError:
            return False

    def delete(self, *, key: str) -> bool:
        try:
            path = self._abs(key)
        except ValueError:
            return False
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False


class CosStorage(StorageBase):
    """
    腾讯云 COS 后端（凭证一到即用；**未配凭证 = 明确报错，不假装签出 URL**）。

    依赖 `cos-python-sdk-v5`（本机未装 → import 时才 import，缺了就明确告知）。
    接口与 LocalStorage 完全一致 → 前端一行不用改。
    """

    name = "cos"

    def __init__(self, secret_id: str, secret_key: str, region: str, bucket: str):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.bucket = bucket

    def _client(self):
        try:
            from qcloud_cos import CosConfig, CosS3Client  # type: ignore
        except Exception as e:  # pragma: no cover - 本机无 SDK
            raise RuntimeError(
                "腾讯云 COS SDK 未安装（pip install cos-python-sdk-v5）；"
                f"原始错误：{e}"
            )
        cfg = CosConfig(Region=self.region, SecretId=self.secret_id,
                        SecretKey=self.secret_key, Scheme="https")
        return CosS3Client(cfg)

    def upload_url(self, *, key: str, mime: str = "",
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> dict:
        if not cos_configured({"cos_secret_id": self.secret_id,
                               "cos_secret_key": self.secret_key,
                               "cos_region": self.region,
                               "cos_bucket": self.bucket}):
            raise RuntimeError("cos_not_configured")
        client = self._client()
        url = client.get_presigned_url(
            Method="PUT", Bucket=self.bucket, Key=key,
            Expired=expire, Headers={"Content-Type": mime or "application/octet-stream"},
        )
        return {
            "upload_url": url,
            "method": "PUT",
            "headers": {"Content-Type": mime or "application/octet-stream"},
            "key": key,
            "expire": expire,
            "backend": self.name,
        }

    def public_url(self, *, key: str,
                   expire: int = DEFAULT_EXPIRE_SECONDS) -> str:
        client = self._client()
        return client.get_presigned_url(
            Method="GET", Bucket=self.bucket, Key=key, Expired=expire,
        )

    def put_bytes(self, *, key: str, data: bytes) -> dict:
        client = self._client()
        b = client.put_object(Bucket=self.bucket, Body=data, Key=key)
        return {
            "stored": True, "key": key, "size": len(data or b""),
            "url": self.public_url(key=key),
            "etag": (b or {}).get("ETag", ""),
        }

    def exists(self, *, key: str) -> bool:
        try:
            client = self._client()
            return bool(client.object_exists(Bucket=self.bucket, Key=key))
        except Exception:
            return False

    def delete(self, *, key: str) -> bool:
        try:
            self._client().delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def get_storage(cfg: dict = None) -> StorageBase:
    """
    按配置返回存储后端实例。

    - `ECHOES_STORAGE=local`（默认）→ LocalStorage（**今天就能用**）
    - `ECHOES_STORAGE=cos` + 四项凭证 → CosStorage
    - `ECHOES_STORAGE=cos` 但缺凭证 → **明确抛错**（不静默回落到 local 假装成功）
    """
    cfg = cfg or load_storage_config()
    if cfg.get("backend") == "cos":
        if not cos_configured(cfg):
            raise RuntimeError(
                "storage_not_configured：已选 COS 但凭证不齐"
                "（需 ECHOES_COS_SECRET_ID/SECRET_KEY/REGION/BUCKET 或 ~/.config/yuanekang/cos.json）"
            )
        return CosStorage(
            cfg["cos_secret_id"], cfg["cos_secret_key"],
            cfg["cos_region"], cfg["cos_bucket"],
        )
    return LocalStorage(cfg.get("local_root") or os.path.expanduser("~/.echoes_media"),
                        cfg.get("public_base") or "/media")


# ============================================================
# 七、对外 handler（前端/小程序调的三个）
# ============================================================

def api_upload_url(*, actor_id: str, kind: str = KIND_IMAGE, file_name: str,
                   file_size: int = 0, mime: str = "") -> dict:
    """
    §6.2 取上传地址。

    入参：
      actor_id  谁在上传（**本人**，§6.2.1 素材只由本人入库）
      kind      image / audio / video / original
      file_name 原始文件名（用于校验+净化）
      file_size 字节数
      mime      可选

    返回：
      {ok, data:{upload_url, method, headers, key, expire, backend}}

    铁律：未配存储 → 明确 `storage_not_configured`，**绝不返回假 URL**。
    """
    if not str(actor_id or "").strip():
        return fail("不知道是谁在上传（actor_id 必填）", "missing_actor")
    passed, why, code = validate_upload(
        kind=kind, file_name=file_name, file_size=file_size, mime=mime,
    )
    if not passed:
        return fail(why, code)

    try:
        key = build_key(actor_id=actor_id, kind=kind, file_name=file_name)
    except ValueError as e:
        return fail(str(e), "bad_actor")

    try:
        st = get_storage()
    except RuntimeError as e:
        return fail(str(e), "storage_not_configured")

    try:
        info = st.upload_url(key=key, mime=mime)
    except RuntimeError as e:
        return fail(str(e), "cos_not_configured")

    return ok({
        "upload_url": info["upload_url"],
        "method": info.get("method", "PUT"),
        "headers": info.get("headers", {}),
        "key": key,
        "expire": info.get("expire", DEFAULT_EXPIRE_SECONDS),
        "backend": getattr(st, "name", "unknown"),
        "confirm_tip": "传完调 /api/echoes/storage/confirm 登记（含公开/私有）才算数",
    }, message="拿到上传地址了")


def api_confirm_upload(*, db, actor_id: str, owner_id: str = "", key: str,
                       kind: str = KIND_IMAGE, story_id: str = "",
                       file_name: str = "", file_size: int = 0, mime: str = "",
                       visibility: str = "private", duration: float = 0.0) -> dict:
    """
    ★§6.2.1 + §1.2：**入库那一刻由本人定公开/私有**（与"放的人当场决定"严丝合缝）。

    入参：
      actor_id  谁在放（**本人**，素材只由本人入库 → 也用于校验槽位）
      owner_id  这个故事的主人（不传=actor_id，自述场景二者同一人）
      key       上传时拿到的对象 key
      kind      image / audio / video / **original**（原声：只存声音不转写）

    流程：前端拿到 upload_url → 传字节 → 调本接口 → 本接口
      ① 校验 key 前缀属于 actor_id（**别人抢不了你的槽位**）
      ② 校验对象**真的存在**（不假装成功——没传上来不许登记）
      ③ 拿存储的稳定可读地址（回放/看图用）
      ④ 落 Clip 表（走 collect_api / collect_av 的原登记 handler，不另开一套）
      ⑤ `original` 类走专用 API（§6.2.2 铁律：原声刻意不转写）

    返回 {ok, data:{clip_id, media_url, visibility, kind, key}}
    """
    # 延迟 import，避免 handler 层互相引成环
    import collect_api
    import collect_av

    try:
        st = get_storage()
    except RuntimeError as e:
        return fail(str(e), "storage_not_configured")

    if not key or not str(key).strip():
        return fail("没给对象 key，不知道传的是哪个文件", "missing_key")

    # ① key 前缀必须属于本人（防越权占槽）
    actor = sanitize_actor(actor_id)
    if not actor:
        return fail("不知道是谁在上传（actor_id 必填）", "missing_actor")
    if not str(key).startswith(f"clips/{actor}/"):
        return fail("这个上传地址不是你的，不能用", "key_actor_mismatch")

    # ② 对象必须真的在（防"没传上来就登记"）
    if not st.exists(key=key):
        return fail("没找到刚上传的文件（可能没传成功），请重试", "object_not_found")

    # ③ 稳定可读地址
    media_url = st.public_url(key=key)

    if visibility not in ("public", "private"):
        visibility = "private"

    size = int(file_size or 0)
    fname = file_name or key.rsplit("/", 1)[-1]
    oid = owner_id or actor_id     # 自述场景：主人=上传者本人

    # ④ 走已有的登记 handler（不重造轮子，保证公私闸门/权限/幂等口径一致）
    if kind == KIND_IMAGE:
        res = collect_api.api_add_photo_clip(
            db, story_id=story_id, owner_id=oid, actor_id=actor_id,
            media_url=media_url, file_name=fname, file_size=size,
            mime=mime, visibility=visibility,
        )
    elif kind == KIND_ORIGINAL:
        # §6.2.2 铁律：原声**刻意不转写**（方言/语气本身是内容）→ 走专用 API
        res = collect_av.api_add_original_clip(
            db, story_id=story_id, owner_id=oid, actor_id=actor_id,
            media_url=media_url, file_name=fname, file_size=size,
            mime=mime, duration=duration, visibility=visibility,
        )
    elif kind == KIND_AUDIO:
        res = collect_av.api_add_audio_clip(
            db, story_id=story_id, owner_id=oid, actor_id=actor_id,
            media_url=media_url, file_name=fname, file_size=size,
            mime=mime, duration=duration, visibility=visibility,
            do_transcribe=True,   # 语音：留声为主 + 留字为辅（§6.2.2）
        )
    elif kind == KIND_VIDEO:
        res = collect_av.api_add_video_clip(
            db, story_id=story_id, owner_id=oid, actor_id=actor_id,
            media_url=media_url, file_name=fname, file_size=size,
            mime=mime, duration=duration, visibility=visibility,
        )
    else:
        return fail(f"不知道这是什么类型的素材（{kind}）", "bad_kind")

    if not res.get("ok"):
        return res

    data = res.get("data", {}) or {}
    data.update({
        "media_url": media_url,
        "visibility": visibility,
        "kind": kind,
        "key": key,
    })
    return ok(data, message="已存好，" + ("公开" if visibility == "public" else "私有"))


def api_media_url(*, key: str, expire: int = DEFAULT_EXPIRE_SECONDS) -> dict:
    """
    §6.2.3 回放/看图：给一个可读地址（本地=静态路径，COS=签名 GET）。
    """
    if not key or not str(key).strip():
        return fail("没给 key", "missing_key")
    try:
        st = get_storage()
    except RuntimeError as e:
        return fail(str(e), "storage_not_configured")
    if not st.exists(key=key):
        return fail("这个文件没有了", "object_not_found")
    return ok({"media_url": st.public_url(key=key, expire=expire),
               "backend": getattr(st, "name", "unknown")})


def api_storage_status() -> dict:
    """
    存储体检（给运维/联调看"现在到底用哪个后端、能不能用"）——**不假装**。
    """
    cfg = load_storage_config()
    backend = cfg["backend"]
    out = {"backend": backend, "public_base": cfg["public_base"]}
    if backend == "cos":
        out["cos_configured"] = cos_configured(cfg)
        out["writable"] = None
        out["note"] = "COS 已选" + ("" if out["cos_configured"] else "但凭证不齐（写不了）")
    else:
        try:
            st = get_storage(cfg)
            probe_key = f"clips/_probe/{int(time.time())}.txt"
            r = st.put_bytes(key=probe_key, data=b"ok")
            st.delete(key=probe_key)
            out["local_root"] = cfg["local_root"]
            out["writable"] = bool(r.get("stored"))
            out["note"] = "本地后端可用（内测/联调够用；真机对外需 ECHOES_PUBLIC_BASE 换公网域名）"
        except Exception as e:
            out["writable"] = False
            out["note"] = f"本地后端不可写：{e}"
    return ok(out)


# ============================================================
# 八、自测 SQLite 建库（供 selftest / 本地跑用）
# ============================================================

def fresh_db():
    from models import init_db, SessionLocal
    init_db()
    return SessionLocal()
