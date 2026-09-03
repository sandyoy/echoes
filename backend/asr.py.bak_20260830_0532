#!/usr/bin/env python3
"""
Echoes ASR (语音转文字) 服务
使用百度语音识别API（免费版，有新用户免费额度）
"""

import sys
import os
import json
import base64
import hashlib
import requests
import time

# 百度语音识别 API 配置
# 从这里获取免费额度：https://console.bce.baidu.com/ai/#/ai/speech/overview/resource/getFree
BAIDU_APP_ID = os.environ.get('BAIDU_ASR_APP_ID', '')
BAIDU_API_KEY = os.environ.get('BAIDU_ASR_API_KEY', '')
BAIDU_SECRET_KEY = os.environ.get('BAIDU_ASR_SECRET_KEY', '')

# Token 缓存
_token_cache = {'token': None, 'expires_at': 0}

def get_access_token():
    """获取百度 access token"""
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at'] - 60:
        return _token_cache['token']
    
    if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
        return None
    
    url = 'https://aip.baidubce.com/oauth/2.0/token'
    params = {
        'grant_type': 'client_credentials',
        'client_id': BAIDU_API_KEY,
        'client_secret': BAIDU_SECRET_KEY
    }
    resp = requests.post(url, params=params)
    result = resp.json()
    
    if 'access_token' in result:
        _token_cache['token'] = result['access_token']
        _token_cache['expires_at'] = now + result.get('expires_in', 2592000)
        return result['access_token']
    return None


def recognize(audio_path: str) -> str:
    """识别语音文件为文字"""
    # 检查文件
    if not os.path.exists(audio_path):
        return json.dumps({"error": "文件不存在"})
    
    # 读取音频文件
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    
    # 获取文件格式
    ext = os.path.splitext(audio_path)[1].lower()
    format_map = {
        '.mp3': 'mp3', '.wav': 'wav', '.pcm': 'pcm',
        '.amr': 'amr', '.m4a': 'm4a', '.ogg': 'ogg',
        '.silk': 'silk', '.webm': 'webm'
    }
    audio_format = format_map.get(ext, 'pcm')
    
    # 尝试百度 API
    token = get_access_token()
    if token:
        try:
            # 百度语音识别 API
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
                return json.dumps({"text": text, "source": "baidu"})
            else:
                return json.dumps({"error": f"百度识别失败: {result.get('err_msg', 'unknown')}"})
        except Exception as e:
            return json.dumps({"error": f"百度API调用异常: {str(e)}"})
    
    # 无API Key - 返回模拟结果（用于开发测试）
    return json.dumps({"error": "未配置百度语音识别 API Key", "mock": True, "text": "（语音识别服务未配置）"})


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
