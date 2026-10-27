/**
 * 往事可追忆 · 自测（零依赖版，只用 Node 自带 http + 手写 WebSocket 握手）
 * 目的：让模拟器真跑起来，读小程序 globalData 里的登录态，判断登录到底成没成。
 */
const http = require('http');
const crypto = require('crypto');
const net = require('net');

const PORT = 9420;

function httpGet(path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path }, (res) => {
      let d = '';
      res.on('data', (c) => d += c);
      res.on('end', () => resolve(d));
    });
    req.on('error', reject);
    req.end();
  });
}

/** 极简 WebSocket 客户端（只处理文本帧，够读 CDP 响应） */
function wsConnect(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const key = crypto.randomBytes(16).toString('base64');
    const sock = net.connect({ host: u.hostname, port: u.port || 80 }, () => {
      sock.write(
        `GET ${u.pathname}${u.search} HTTP/1.1\r\n` +
        `Host: ${u.host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n` +
        `Sec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`
      );
    });
    let buf = Buffer.alloc(0);
    let handshook = false;
    const pending = new Map();
    let idSeq = 0;

    function tryParse() {
      while (buf.length >= 2) {
        const len0 = buf[1] & 0x7f;
        let off = 2, len = len0;
        if (len0 === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); off = 4; }
        else if (len0 === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); off = 10; }
        const masked = (buf[1] & 0x80) !== 0;
        let mOff = off;
        if (masked) { if (buf.length < off + 4) return; off += 4; }
        if (buf.length < off + len) return;
        const payload = buf.slice(off, off + len);
        if (masked) {
          const mask = buf.slice(mOff, mOff + 4);
          for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
        }
        buf = buf.slice(off + len);
        const opcode = buf.length >= 0 ? null : null;
        try {
          const msg = JSON.parse(payload.toString('utf8'));
          if (msg.id && pending.has(msg.id)) {
            pending.get(msg.id)(msg);
            pending.delete(msg.id);
          }
        } catch (e) { /* 控制帧/非 JSON 忽略 */ }
      }
    }

    sock.on('data', (chunk) => {
      if (!handshook) {
        buf = Buffer.concat([buf, chunk]);
        const idx = buf.indexOf('\r\n\r\n');
        if (idx === -1) return;
        const head = buf.slice(0, idx).toString();
        if (!/101/.test(head.split('\r\n')[0])) { reject(new Error('握手失败: ' + head.split('\r\n')[0])); return; }
        buf = buf.slice(idx + 4);
        handshook = true;
        resolve({
          send: (method, params) => new Promise((res) => {
            const id = ++idSeq;
            pending.set(id, res);
            const json = Buffer.from(JSON.stringify({ id, method, params: params || {} }));
            const len = json.length;
            let header;
            if (len < 126) header = Buffer.from([0x81, 0x80 | len]);
            else if (len < 65536) { header = Buffer.alloc(4); header[0] = 0x81; header[1] = 0x80 | 126; header.writeUInt16BE(len, 2); }
            else { header = Buffer.alloc(10); header[0] = 0x81; header[1] = 0x80 | 127; header.writeBigUInt64BE(BigInt(len), 2); }
            const mask = crypto.randomBytes(4);
            const masked = Buffer.from(json);
            for (let i = 0; i < masked.length; i++) masked[i] ^= mask[i % 4];
            sock.write(Buffer.concat([header, mask, masked]));
            setTimeout(() => { if (pending.has(id)) { pending.delete(id); res({ timeout: true }); } }, 15000);
          }),
          close: () => sock.destroy()
        });
        tryParse();
        return;
      }
      buf = Buffer.concat([buf, chunk]);
      tryParse();
    });
    sock.on('error', reject);
    setTimeout(() => { if (!handshook) reject(new Error('握手超时')); }, 10000);
  });
}

(async () => {
  // 微信开发者工具的自动化端口只用一个 WebSocket 入口（根路径），不是标准 /json/list
  console.log('=== 连接 127.0.0.1:' + PORT + '/===')
  const ws = await wsConnect('ws://127.0.0.1:' + PORT + '/');
  console.log('WebSocket 已连上');

  // 先探一下这端口支持哪些 CDP 命令
  const v = await ws.send('Runtime.evaluate', { expression: '1+1', returnByValue: true });
  console.log('探针 1+1 =>', JSON.stringify(v).slice(0, 200));

  const expr = `(function(){
    var app = getApp();
    if (!app) return {err:'getApp() 拿不到'};
    var g = app.globalData;
    return {
      apiBase: g.apiBase, userId: g.userId, loginReady: g.loginReady,
      loginPending: g.loginPending, loginError: g.loginError,
      sessionFrom: g.sessionFrom, isDevEnv: app.isDevEnv ? app.isDevEnv() : 'no-fn'
    };
  })()`;

  const r = await ws.send('Runtime.evaluate', { expression: expr, returnByValue: true });
  console.log('=== 登录态 ===');
  if (r.timeout) console.log('!! 执行超时（可能 appservice 没连对）');
  else console.log(JSON.stringify(r.result && r.result.result && r.result.result.value, null, 2));
  ws.close();
})().catch((e) => console.log('ERR', e.message));
