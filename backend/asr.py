#!/usr/bin/env python3
"""
Echoes ASR (语音转文字) 服务
引擎顺序：
  1. 若配置了百度语音识别 API Key → 优先用百度（普通话识别好、速度快、免费额度）
  2. 否则回退到本地 faster-whisper（零第三方账号、免费、离线），输出简体中文
  3. 兜底返回明确错误信息，绝不让 node 进程崩溃

本地 whisper 模型通过 hf-mirror.com 加速下载（HF_HUB_DISABLE_XET 关闭 xet 协议，
避免 401）。
"""

import sys
import os
import json
import base64
import hashlib
import traceback

# ================= faster-whisper / 简体转换 配置 =================
# 让 huggingface_hub 走国内镜像 + 关闭有问题的 xet 协议
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '180')

# 本地 whisper 使用的模型大小（越小越省内存/越快；base 对普通话够用，2G内存机器可跑）
# 可选: tiny / base / small  （本机仅 ~2G 内存 + swap，切勿用 large）
import os as _os
_WHISPER_MODEL = _os.environ.get('ASR_WHISPER_MODEL', 'base')

# 百度语音识别 API 配置（可选；配了优先用百度，不配则走本地 whisper）
BAIDU_APP_ID = os.environ.get('BAIDU_ASR_APP_ID', '')
BAIDU_API_KEY = os.environ.get('BAIDU_API_KEY', '')
BAIDU_SECRET_KEY = os.environ.get('BAIDU_SECRET_KEY', '')

# Token 缓存
_token_cache = {'token': None, 'expires_at': 0}

# 全局模型引用（懒加载，避免每次请求都重新加载）
_whisper_model = None
_opencc_converter = None


def get_access_token():
    """获取百度 access token"""
    import time
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at'] - 60:
        return _token_cache['token']

    if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
        return None

    import requests
    url = 'https://aip.baidubce.com/oauth/2.0/token'
    params = {
        'grant_type': 'client_credentials',
        'client_id': BAIDU_API_KEY,
        'client_secret': BAIDU_SECRET_KEY
    }
    try:
        resp = requests.post(url, params=params, timeout=10)
        result = resp.json()
        if 'access_token' in result:
            _token_cache['token'] = result['access_token']
            _token_cache['expires_at'] = now + result.get('expires_in', 2592000)
            return result['access_token']
    except Exception as e:
        sys.stderr.write(f'[asr] 百度 token 获取失败: {e}\n')
    return None


def _baidu_recognize(audio_path, audio_data, audio_format):
    """用百度短语音识别。返回 text 或 None。"""
    import requests
    token = get_access_token()
    if not token:
        return None
    try:
        url = 'https://vop.baidu.com/server_api'
        speech_data = base64.b64encode(audio_data).decode('utf-8')
        payload = {
            'format': audio_format,
            'rate': 16000,
            'dev_pid': 1537,  # 普通话(中文)
            'speech': speech_data,
            'len': len(audio_data),
            'channel': 1,
            'cuid': 'echoes_asr_001',
            'token': token
        }
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get('err_no') == 0:
            text = result.get('result', [''])[0]
            return text if text else None
        else:
            sys.stderr.write(f"[asr] 百度识别失败: {result.get('err_msg','unknown')}\n")
            return None
    except Exception as e:
        sys.stderr.write(f'[asr] 百度API调用异常: {e}\n')
        return None


def _get_whisper_model():
    """懒加载 faster-whisper 模型。"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(_WHISPER_MODEL, device='cpu', compute_type='int8')
    return _whisper_model


def _to_simplified(text):
    """繁体转简体（whisper 默认输出繁体中文）。"""
    global _opencc_converter
    try:
        if _opencc_converter is None:
            from opencc import OpenCC
            _opencc_converter = OpenCC('t2s')
        return _opencc_converter.convert(text)
    except Exception as e:
        sys.stderr.write(f'[asr] OpenCC 转换失败(返回原文): {e}\n')
        return text


def _whisper_recognize(audio_path) -> str:
    """用本地 faster-whisper 转写。返回简体中文文本。"""
    try:
        model = _get_whisper_model()
        # 用简体提示词引导 tokenizer 偏向简体输出
        segments, _info = model.transcribe(
            audio_path,
            language='zh',
            initial_prompt='以下是普通话的句子，请使用简体中文字幕。'
        )
        text = ''.join(s.text for s in segments).strip()
        if not text:
            return ''
        return _to_simplified(text)
    except Exception as e:
        sys.stderr.write(f'[asr] whisper 识别失败: {e}\n')
        traceback.print_exc(file=sys.stderr)
        return ''


def recognize(audio_path: str) -> str:
    """识别语音文件为文字。返回 JSON 字符串。"""
    # 检查文件
    if not os.path.exists(audio_path):
        return json.dumps({"error": "文件不存在"})

    # 读取音频文件
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    if not audio_data:
        return json.dumps({"error": "音频文件为空"})

    # 获取文件格式
    ext = os.path.splitext(audio_path)[1].lower()
    format_map = {
        '.mp3': 'mp3', '.wav': 'wav', '.pcm': 'pcm',
        '.amr': 'amr', '.m4a': 'm4a', '.ogg': 'ogg',
        '.silk': 'silk', '.webm': 'webm'
    }
    audio_format = format_map.get(ext, 'pcm')

    # 优先百度
    if BAIDU_API_KEY and BAIDU_SECRET_KEY:
        text = _baidu_recognize(audio_path, audio_data, audio_format)
        if text:
            return json.dumps({"text": text, "source": "baidu"})
        sys.stderr.write('[asr] 百度未识别成功，回退本地 whisper。\n')
    else:
        sys.stderr.write('[asr] 未配置百度 Key，使用本地 whisper。\n')

    # 回退本地 faster-whisper
    text = _whisper_recognize(audio_path)
    if text:
        return json.dumps({"text": text, "source": "whisper"})

    # 兜底
    return json.dumps({
        "error": "语音识别未能返回文字（百度未配且本地whisper失败）",
        "mock": True,
        "text": ""
    })


def main():
    """CLI 入口"""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供音频文件路径"}))
        sys.exit(1)

    audio_path = sys.argv[1]
    result = recognize(audio_path)
    print(result)


if __name__ == '__main__':
    main()
