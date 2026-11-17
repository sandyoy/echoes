#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小桥小老师 · 答疑后端
- 孩子提问 → DeepSeek 回答（圆圆老师人设）
- 每日花钱上限保护，超了自动拒答
- 对话记录落本地文件，妈妈随时可查
"""
import json, os, time, datetime, urllib.request, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

KEY = os.environ.get('DS_KEY', '')
API = 'https://api.deepseek.com/v1/chat/completions'
MODEL = 'deepseek-chat'

BASE = os.path.expanduser('~/小桥小老师')
LOG_DIR = os.path.join(BASE, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
USAGE_FILE = os.path.join(LOG_DIR, 'usage.json')
_usage_lock = threading.Lock()

# 每天最多允许多少次问答（防孩子乱刷）
DAILY_LIMIT = 60
MAX_INPUT = 300

SYSTEM = """你是"圆圆老师"，小桥的专属小老师。小桥是小学五年级的男孩，学习基础薄弱。

他的情况（不要主动提，但回答时要照顾）：
- 拼音严重掉队，字不太会写，但口头表达很好
- 除法没学好、乘法口诀不熟
- 数学代入法、代换不会
- 英语最弱

回答要求（严格遵守）：
1. 说话像一个温和、耐心、说话简短的小学老师。用"你"，不用"您"。
2. 每次回答不超过 120 个字。宁可少说，不要长篇大论。
3. 先肯定他愿意问，再回答。不要说"你真棒"这种空话，要具体。
4. 讲知识点必须拆成很小的步骤，一次只讲一步。
5. 绝对不许说"这么简单都不会"、"上课没听吗"这类话。
6. 如果他问"不想学了""好难"，先接住情绪，然后把任务缩到最小（比如"那今天只做三道"）。
7. 如果他问跟学习无关的问题（游戏、动画、好奇的事），也可以正常回答，简短、真诚，然后顺带引回学习一点点。不要生硬拒绝。
8. 他问的题目，不要直接给答案，先给方法，让他自己算。他明确说"你就告诉我答案"时可以给。
9. 用中文回答。不要用markdown符号、不要用星号、不要用井号。就是正常说话。"""


def load_usage():
    today = datetime.date.today().isoformat()
    try:
        u = json.load(open(USAGE_FILE))
    except Exception:
        u = {}
    if u.get('date') != today:
        u = {'date': today, 'count': 0, 'tokens': 0}
    return u


def save_usage(u):
    json.dump(u, open(USAGE_FILE, 'w'), ensure_ascii=False)


def log_chat(question, answer):
    f = os.path.join(LOG_DIR, 'chat_%s.log' % datetime.date.today().isoformat())
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    with open(f, 'a', encoding='utf-8') as fh:
        fh.write('[%s] 小桥：%s\n[%s] 圆圆老师：%s\n\n' % (ts, question, ts, answer))


def ask_deepseek(question, history):
    msgs = [{'role': 'system', 'content': SYSTEM}]
    for h in history[-6:]:
        msgs.append({'role': h['role'], 'content': h['content']})
    msgs.append({'role': 'user', 'content': question})
    body = json.dumps({
        'model': MODEL, 'messages': msgs,
        'max_tokens': 400, 'temperature': 0.7
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + KEY})
    r = urllib.request.urlopen(req, timeout=90)
    d = json.loads(r.read())
    return d['choices'][0]['message']['content'].strip(), d.get('usage', {})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, *a):
        pass

    # 长连接要显式声明，否则学习机浏览器会一直挂着等
    protocol_version = 'HTTP/1.1'

    def end_headers(self):
        self.send_header('Connection', 'close')
        super().end_headers()

    def do_POST(self):
        if self.path != '/api/ask':
            self.send_error(404)
            return
        try:
            n = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            self._json({'error': 'bad request'}, 400)
            return

        q = (payload.get('q') or '').strip()[:MAX_INPUT]
        history = payload.get('history') or []
        if not q:
            self._json({'error': 'empty'}, 400)
            return

        with _usage_lock:
            u = load_usage()
            over = u['count'] >= DAILY_LIMIT
            if not over:
                u['count'] += 1
                save_usage(u)
        if over:
            self._json({'answer': '今天咱们问得够多啦，老师也有点累。明天接着问，好不好？'}, 200)
            return

        try:
            answer, usage = ask_deepseek(q, history)
        except Exception as e:
            answer = '老师这边网络有点慢，你等一下再问一次好不好？'
            usage = {}
            print('API ERROR:', e, flush=True)

        with _usage_lock:
            u = load_usage()
            u['tokens'] += usage.get('total_tokens', 0)
            save_usage(u)
        log_chat(q, answer)
        self._json({'answer': answer,
                    'used': u['count'],
                    'limit': DAILY_LIMIT})

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)


if __name__ == '__main__':
    if not KEY:
        raise SystemExit('缺少 DS_KEY 环境变量')
    srv = ThreadingHTTPServer(('0.0.0.0', 8899), Handler)
    srv.daemon_threads = True
    print('小桥小老师服务启动 :8899  每日上限 %d 次（多线程）' % DAILY_LIMIT, flush=True)
    srv.serve_forever()
