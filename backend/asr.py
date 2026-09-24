#!/usr/bin/env python3
"""
Echoes ASR (语音转文字) 服务

引擎顺序（v2.0，2026-09-25 起）：
  1. 讯飞语音听写（XF_APP_ID / XF_API_KEY / XF_APISECRET）→ 优先
  2. 百度短语音识别（BAIDU_ASR_APP_ID / BAIDU_API_KEY / BAIDU_SECRET_KEY）→ 次选
  3. 本地 faster-whisper（离线、免费）→ 兜底
  4. 全部失败 → 返回明确错误 JSON，绝不让 node 进程崩溃

讯飞接口说明：
  - 听写 API：wss://iat-api.xfyun.cn/v2/iat （WebSocket）
  - 认证：HMAC-SHA256 对 (host, date, request-line) 签名，拼成 URL 查询串
  - 音频要求：16k 采样率、16bit、单声道 PCM
  - 返回：分片 JSON，需把 ws[].cw[].w 拼起来

本地 whisper 模型通过 hf-mirror.com 加速下载（HF_HUB_DISABLE_XET 关闭 xet 协议，避免 401）。
"""

import sys
import os
import json
import base64
import hashlib
import hmac
import time
import traceback
from datetime import datetime
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time
from time import mktime

# ================= 环境配置 =================
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '180')

# 本地 whisper 模型大小（tiny / base / small；本机内存有限勿用 large）
_WHISPER_MODEL = os.environ.get('ASR_WHISPER_MODEL', 'base')

# 讯飞（优先）
XF_APP_ID = os.environ.get('XF_APP_ID', '')
XF_API_KEY = os.environ.get('XF_API_KEY', '')
XF_APISECRET = os.environ.get('XF_APISECRET', '')

# 百度（次选）
BAIDU_APP_ID = os.environ.get('BAIDU_ASR_APP_ID', '')
BAIDU_API_KEY = os.environ.get('BAIDU_API_KEY', '')
BAIDU_SECRET_KEY = os.environ.get('BAIDU_SECRET_KEY', '')

# 讯飞 WebSocket 端点
XF_HOST = 'iat-api.xfyun.cn'
XF_PATH = '/v2/iat'

_whisper_model = None
_opencc_converter = None


# ================= 通用工具 =================

def _read_audio(audio_path):
    """读音频文件，返回 (bytes, 格式扩展名小写)"""
    with open(audio_path, 'rb') as f:
        data = f.read()
    ext = os.path.splitext(audio_path)[1].lower().lstrip('.')
    return data, ext


def _pcm_16k(audio_path):
    """
    把音频转成讯飞要求的 16k/16bit/单声道 PCM。
    优先用 ffmpeg；没有就用原文件（若本身已是 pcm/wav 16k）。
    返回 bytes 或 None。
    """
    import subprocess
    import shutil
    out = '/tmp/_asr_16k.pcm'
    if shutil.which('ffmpeg'):
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', audio_path, '-ar', '16000', '-ac', '1',
                 '-f', 's16le', '-acodec', 'pcm_s16le', out],
                capture_output=True, timeout=60, check=True
            )
            with open(out, 'rb') as f:
                return f.read()
        except Exception as e:
            sys.stderr.write(f'[asr] ffmpeg 转换失败: {e}\n')
    # 无 ffmpeg：若本就是 wav/pcm 则直接返回裸数据（wav 需跳 44 字节头）
    data, ext = _read_audio(audio_path)
    if ext == 'pcm':
        return data
    if ext == 'wav' and len(data) > 44:
        return data[44:]
    return None


# ================= 一、讯飞语音听写 =================

def _xf_auth_url():
    """生成讯飞 WebSocket 鉴权 URL（HMAC-SHA256 签名）"""
    date = format_date_time(mktime(datetime.now().timetuple()))
    signature_origin = f"host: {XF_HOST}\ndate: {date}\nGET {XF_PATH} HTTP/1.1"
    signature_sha = hmac.new(
        XF_APISECRET.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    signature = base64.b64encode(signature_sha).decode('utf-8')
    authorization_origin = (
        f'api_key="{XF_API_KEY}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')
    params = {'authorization': authorization, 'date': date, 'host': XF_HOST}
    return f"wss://{XF_HOST}{XF_PATH}?{urlencode(params)}"


def _xf_recognize(audio_path):
    """
    用讯飞语音听写识别。返回 text 或 None。
    分片发送：首帧 common+business+data，中间 data，末帧 status=2。
    """
    try:
        import websocket  # websocket-client
    except ImportError:
        sys.stderr.write('[asr] 未安装 websocket-client，跳过讯飞\n')
        return None

    pcm = _pcm_16k(audio_path)
    if not pcm:
        sys.stderr.write('[asr] 讯飞：音频无法转 16k PCM，跳过\n')
        return None

    ws_url = _xf_auth_url()
    result_parts = []
    try:
        ws = websocket.create_connection(ws_url, timeout=30)

        # 首帧
        first = {
            "common": {"app_id": XF_APP_ID},
            "business": {
                "language": "zh_cn",
                "domain": "iat",
                "accent": "mandarin",
                "vad_eos": 10000,
                "dwa": "wpgs",  # 动态修正
            },
            "data": {
                "status": 0,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
                "audio": base64.b64encode(pcm[:1280 * 40]).decode('utf-8'),
            },
        }
        ws.send(json.dumps(first))

        # 中间帧
        chunk_size = 1280 * 40
        offset = chunk_size
        while offset < len(pcm):
            chunk = pcm[offset:offset + chunk_size]
            ws.send(json.dumps({
                "data": {
                    "status": 1,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(chunk).decode('utf-8'),
                }
            }))
            offset += chunk_size

        # 末帧
        ws.send(json.dumps({
            "data": {
                "status": 2,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
                "audio": "",
            }
        }))

        # 收结果
        while True:
            msg = ws.recv()
            if not msg:
                break
            r = json.loads(msg)
            code = r.get('code')
            if code != 0:
                sys.stderr.write(f"[asr] 讯飞返回错误: code={code} msg={r.get('message')}\n")
                break
            data = r.get('data', {})
            if data.get('result'):
                ws_list = data['result'].get('ws', [])
                for w in ws_list:
                    for cw in w.get('cw', []):
                        result_parts.append(cw.get('w', ''))
            if data.get('status') == 2:
                break
        ws.close()
    except Exception as e:
        sys.stderr.write(f'[asr] 讯飞识别异常: {e}\n')
        traceback.print_exc(file=sys.stderr)
        return None

    text = ''.join(result_parts).strip()
    return text if text else None


# ================= 二、百度短语音识别 =================

_token_cache = {'token': None, 'expires_at': 0}


def get_access_token():
    """获取百度 access token"""
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
        'client_secret': BAIDU_SECRET_KEY,
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
            'token': token,
        }
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get('err_no') == 0:
            text = result.get('result', [''])[0]
            return text if text else None
        sys.stderr.write(f"[asr] 百度识别失败: {result.get('err_msg','unknown')}\n")
        return None
    except Exception as e:
        sys.stderr.write(f'[asr] 百度API调用异常: {e}\n')
        return None


# ================= 三、本地 whisper =================

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(_WHISPER_MODEL, device='cpu', compute_type='int8')
    return _whisper_model


def _to_simplified(text):
    """繁体转简体（whisper 默认输出繁体）。opencc 缺失时用手写映射兜底。"""
    global _opencc_converter
    try:
        if _opencc_converter is None:
            from opencc import OpenCC
            _opencc_converter = OpenCC('t2s')
        return _opencc_converter.convert(text)
    except Exception:
        # 无 opencc：走手写高频映射（够用，不追求全覆盖）
        _MAP = str.maketrans(
            '這裡個們來時說話對開關門問題沒學會發現實點還當經聽見過長後東車書寫'
            '認識讓給帶動語讀寫買賣錢週歲號愛親藥醫院護師體氣風濕熱頭腦心臟灣',
            '这里个们来时说话对开关门问题没学会发现实点还当经听见过长后东车书写'
            '认识让给带动语读写买卖钱周岁号爱亲药医院护师体气风湿热头脑心脏湾'
        )
        return text.translate(_MAP)


def _whisper_recognize(audio_path) -> str:
    """用本地 faster-whisper 转写。返回简体中文文本。"""
    try:
        model = _get_whisper_model()
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


# ================= 主入口 =================

def recognize(audio_path: str) -> str:
    """识别语音文件为文字。返回 JSON 字符串。"""
    if not os.path.exists(audio_path):
        return json.dumps({"error": "文件不存在"})

    audio_data, ext = _read_audio(audio_path)
    if not audio_data:
        return json.dumps({"error": "音频文件为空"})

    format_map = {
        '.mp3': 'mp3', '.wav': 'wav', '.pcm': 'pcm',
        '.amr': 'amr', '.m4a': 'm4a', '.ogg': 'ogg',
        '.silk': 'silk', '.webm': 'webm',
    }
    audio_format = format_map.get('.' + ext, 'pcm')

    # ① 讯飞优先
    if XF_APP_ID and XF_API_KEY and XF_APISECRET:
        text = _xf_recognize(audio_path)
        if text:
            return json.dumps({"text": text, "source": "xfyun"}, ensure_ascii=False)
        sys.stderr.write('[asr] 讯飞未识别成功，回退下一引擎。\n')
    else:
        sys.stderr.write('[asr] 未配置讯飞 Key，跳过讯飞。\n')

    # ② 百度次选
    if BAIDU_API_KEY and BAIDU_SECRET_KEY:
        text = _baidu_recognize(audio_path, audio_data, audio_format)
        if text:
            return json.dumps({"text": text, "source": "baidu"}, ensure_ascii=False)
        sys.stderr.write('[asr] 百度未识别成功，回退本地 whisper。\n')
    else:
        sys.stderr.write('[asr] 未配置百度 Key，跳过百度。\n')

    # ③ 本地 whisper 兜底
    text = _whisper_recognize(audio_path)
    if text:
        return json.dumps({"text": text, "source": "whisper"}, ensure_ascii=False)

    # ④ 全失败
    return json.dumps({
        "error": "语音识别未能返回文字（讯飞/百度/whisper 均未成功）",
        "mock": True,
        "text": ""
    }, ensure_ascii=False)


def main():
    """CLI 入口"""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供音频文件路径"}, ensure_ascii=False))
        sys.exit(1)
    print(recognize(sys.argv[1]))


if __name__ == '__main__':
    main()
