#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯云语音识别（ASR）本地调用封装 —— 往事可追忆
================================================
为什么用它：服务器就在腾讯云，内网直连，不用配 IP 白名单、不受公网限速影响。

⚠️ 零依赖实现：本机 venv 无 pip、装不了腾讯云官方 SDK，
   所以这里用 requests 手写 TC3-HMAC-SHA256 签名直调 API。
   只依赖 requests（系统 python3 自带）。

用到的接口：
  SentenceRecognition —— 一句话/短语音（≤60s）一次性识别，传 base64 音频
  （长音频异步 CreateRecTask 暂未接，老人单段回忆基本 ≤60s）

凭证读取顺序（第一个找到的为准）：
  1. 环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
  2. ~/.config/yuanekang/tencent_asr.json
  3. ~/echoes/config/secrets/tencent_asr.json

⚠️ 凭证严禁进 Git 仓库（.gitignore 已拦 *_secret*.json / config/secrets/）

用法：
  python3 tencent_asr.py <音频文件>            # 自动转码后识别
"""

import os
import sys
import json
import time
import base64
import hmac
import hashlib
import subprocess
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:  # 兜底：走 venv 里可能有的 requests
    requests = None

# ================= 凭证 =================

def load_credentials():
    sid = os.environ.get("TENCENT_SECRET_ID", "").strip()
    skey = os.environ.get("TENCENT_SECRET_KEY", "").strip()
    if sid and skey:
        return sid, skey

    candidates = [
        Path.home() / ".config" / "yuanekang" / "tencent_asr.json",
        Path.home() / "echoes" / "config" / "secrets" / "tencent_asr.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            sid = str(d.get("secret_id", "")).strip()
            skey = str(d.get("secret_key", "")).strip()
            if sid and skey:
                return sid, skey
    raise RuntimeError(
        "未找到腾讯云凭证。请设置环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY，"
        "或写入 ~/.config/yuanekang/tencent_asr.json"
    )


def has_credentials() -> bool:
    """不抛异常地探测凭证是否可用（供 asr.py 决定是否把腾讯云排第一）"""
    try:
        load_credentials()
        return True
    except Exception:
        return False


# ================= 音频转码 =================

def to_wav16k(src: str) -> str:
    """任意音频 → 16k / 16bit / 单声道 WAV（腾讯云推荐格式）"""
    out = tempfile.mktemp(suffix=".wav")
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败: {r.stderr[-500:]}")
    return out


def probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ================= TC3-HMAC-SHA256 签名 =================
# 参考腾讯云官方签名算法 v3（https://cloud.tencent.com/document/api/1093/35640）

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_authorization(secret_id: str, secret_key: str, host: str,
                         service: str, action: str, version: str,
                         payload: str, region: str = "ap-guangzhou") -> dict:
    """构造腾讯云 API 3.0 请求头（含签名）"""
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))

    # 1. 拼接规范请求串
    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        http_request_method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, hashed_request_payload,
    ])

    # 2. 拼接待签名字符串
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join([
        algorithm, str(timestamp), credential_scope, hashed_canonical_request,
    ])

    # 3. 计算签名
    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    # 4. 拼接 Authorization
    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }


def _call_api(action: str, params: dict, *, service: str = "asr",
              host: str = "asr.tencentcloudapi.com", version: str = "2019-06-14",
              region: str = "ap-guangzhou", timeout: int = 30) -> dict:
    """调用腾讯云 API，返回 Response 字典"""
    if requests is None:
        raise RuntimeError("缺少 requests 库，无法调用腾讯云 API")

    sid, skey = load_credentials()
    payload = json.dumps(params, ensure_ascii=False)
    headers = _build_authorization(sid, skey, host, service, action,
                                   version, payload, region)

    r = requests.post(f"https://{host}/", headers=headers,
                      data=payload.encode("utf-8"), timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

    d = r.json()
    resp = d.get("Response", {})
    err = resp.get("Error")
    if err:
        raise RuntimeError(f"腾讯云返回错误: {err.get('Code')} - {err.get('Message')}")
    return resp


# ================= 识别 =================

def recognize_short(audio_path: str, eng_service_type: str = "16k_zh",
                    timeout: int = 30) -> str:
    """
    短语音识别（≤60 秒），一次调用出结果，返回识别文字。
    eng_service_type: 16k_zh=中文普通话, 16k_yue=粤语, 16k_zh_en=中英混合,
                      16k_zh_dialect=方言（含四川话/长沙话等）
    """
    wav = to_wav16k(audio_path)
    try:
        data = Path(wav).read_bytes()
        b64 = base64.b64encode(data).decode()
        resp = _call_api("SentenceRecognition", {
            "ProjectId": 0,
            "SubServiceType": 2,          # 2 = 一句话识别
            "EngSerViceType": eng_service_type,
            "SourceType": 1,              # 1 = 音频数据（base64）
            "VoiceFormat": "wav",
            "Data": b64,
            "DataLen": len(data),
            "FilterDirty": 0,
            "FilterModal": 0,
            "FilterPunc": 0,
            "ConvertNumMode": 1,          # 数字转阿拉伯：便于抓年份锚点
            "WordInfo": 0,
        }, timeout=timeout)
        return resp.get("Result", "")
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def recognize_long(audio_path: str, eng_service_type: str = "16k_zh",
                   poll_interval: int = 3, max_wait: int = 300) -> str:
    """
    录音文件识别（长音频，异步）：上传→轮询→取结果。
    需要音频先传到 COS 或给公网 URL；本机直传可用 Data 方式（≤5MB 走 CreateRecTask 不支持，
    此接口仅作占位，当前主链路走 recognize_short）。
    """
    raise NotImplementedError("长音频异步识别暂未启用，当前标注：老人单段回忆 ≤60s")


class ASRError(Exception):
    pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    audio = sys.argv[1]
    if not os.path.exists(audio):
        print(f"文件不存在: {audio}")
        sys.exit(1)

    dur = probe_duration(audio)
    print(f"音频: {audio}  时长: {dur:.2f}s")
    try:
        t0 = time.time()
        text = recognize_short(audio)
        print(f"耗时: {time.time()-t0:.2f}s")
        print(f"识别结果: {text}")
    except Exception as e:
        print(f"失败: {type(e).__name__}: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
