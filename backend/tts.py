#!/usr/bin/env python3
"""
Echoes TTS 语音合成服务
使用 edge-tts (微软AI语音) 生成高质量中文语音
支持缓存避免重复生成
"""

import sys
import os
import asyncio
import hashlib
import json
import edge_tts

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'tts_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# 语音配置
VOICE = 'zh-CN-XiaoxiaoNeural'  # 晓晓 - 温柔女声，适合采访场景
RATE = '+0%'      # 语速
VOLUME = '+0%'    # 音量


def get_cache_key(text: str) -> str:
    """生成缓存键"""
    return hashlib.md5(f"{text}|{VOICE}|{RATE}|{VOLUME}".encode()).hexdigest()


def get_cache_path(cache_key: str) -> str:
    return os.path.join(CACHE_DIR, f"{cache_key}.mp3")


async def generate_tts(text: str) -> str:
    """生成语音文件，返回文件路径"""
    cache_key = get_cache_key(text)
    cache_path = get_cache_path(cache_key)

    # 命中缓存
    if os.path.exists(cache_path):
        return cache_path

    # 生成语音
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, volume=VOLUME)
    await communicate.save(cache_path)

    return cache_path


def main():
    """CLI 入口：python3 tts.py "要朗读的文字" """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供要朗读的文字"}))
        sys.exit(1)

    text = sys.argv[1].strip()
    if not text:
        print(json.dumps({"error": "文字不能为空"}))
        sys.exit(1)

    # 限制长度
    if len(text) > 500:
        text = text[:500]
        print("⚠️ 文字过长，已截断至500字", file=sys.stderr)

    filepath = asyncio.run(generate_tts(text))
    print(json.dumps({"filepath": filepath, "cached": os.path.basename(filepath)}))


if __name__ == '__main__':
    main()
