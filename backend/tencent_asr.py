#!/usr/bin/env python3
"""
腾讯云语音识别（ASR）本地调用封装 —— 往事可追忆
================================================
为什么用它：服务器就在腾讯云，内网直连，不用配 IP 白名单、不受公网限速影响。

用到的接口（都是一句话/短语音，适合"老人说一段回忆"的场景）：
  1. SentenceRecognition   —— 短语音（≤60s）一次性识别，最省事，传 base64 音频
  2. CreateRecTask         —— 录音文件识别（长音频，异步，轮询取结果）

凭证读取顺序（第一个找到的为准）：
  1. 环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
  2. ~/.config/yuanekang/tencent_asr.json
  3. ~/echoes/config/secrets/tencent_asr.json

⚠️ 凭证严禁进 Git 仓库（.gitignore 已拦 *_secret*.json / config/secrets/）

用法：
  python3 tencent_asr.py <音频文件>            # 自动转码后识别
  python3 tencent_asr.py <音频文件> --long     # 走长音频异步接口
"""

import os
import sys
import json
import base64
import subprocess
import tempfile
import time
from pathlib import Path

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
            d = json.loads(p.read_text())
            sid = d.get("secret_id", "").strip()
            skey = d.get("secret_key", "").strip()
            if sid and skey:
                return sid, skey
    raise RuntimeError(
        "未找到腾讯云凭证。请设置环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY，"
        "或写入 ~/.config/yuanekang/tencent_asr.json"
    )


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


# ================= 识别 =================

def recognize_short(audio_path: str, eng_service_type: str = "16k_zh") -> str:
    """
    短语音识别（≤60 秒），一次调用出结果。
    eng_service_type: 16k_zh=中文普通话, 16k_yue=粤语, 16k_zh_en=中英混合,
                      16k_zh_dialect=方言（含四川话/长沙话等）
    """
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.asr.v20190614 import asr_client, models

    sid, skey = load_credentials()

    wav = to_wav16k(audio_path)
    data = Path(wav).read_bytes()
    b64 = base64.b64encode(data).decode()

    cred = credential.Credential(sid, skey)
    hp = HttpProfile(endpoint="asr.tencentcloudapi.com")
    cp = ClientProfile(httpProfile=hp)
    client = asr_client.AsrClient(cred, "ap-guangzhou", cp)

    req = models.SentenceRecognitionRequest()
    req.from_json_string(json.dumps({
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
    }))
    resp = client.SentenceRecognition(req)
    d = json.loads(resp.to_json_string())
    return d.get("Result", "")


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
        print(f"❌ 失败: {type(e).__name__}: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
