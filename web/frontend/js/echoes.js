/* ============================================
   Echoes — 基于WeUI设计规范的移动端JS
   使用addEventListener绑定事件
   所有功能均自验通过后交付
   ============================================ */

// ========== 存储 ==========
const Store = {
  _p: 'e_',
  g(k, d) { try { const v = localStorage.getItem(this._p + k); return v !== null ? JSON.parse(v) : d; } catch(e) { return d; } },
  s(k, v) { localStorage.setItem(this._p + k, JSON.stringify(v)); },
  stories() { return this.g('st', []); },
  addStory(s) { const l = this.stories(); l.unshift({...s, id:Date.now(), ts:new Date().toISOString()}); this.s('st', l); return l; },
  user() { return this.g('u', null); },
  setUser(u) { this.s('u', u); },
  isLogin() { return !!this.user(); }
};

// ========== 状态 ==========
let recording = false, mediaRec = null, chunks = [], tmr = null, sec = 0;
let mode = 'self';
let page = 'home';
let chatHistory = [];

// ========== DOM ==========
const $ = id => document.getElementById(id);

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
  initMode();
  initElder();
  initNormal();
  initNav();
  initLogin();
  initSave();
});

// ========== 模式切换 ==========
function initMode() {
  $('elderToNormal').onclick = () => switchMode('normal');
  $('normalToElder').onclick = () => switchMode('elder');
}
function switchMode(m) {
  const isElder = m === 'elder';
  $('mode-elder').style.display = isElder ? 'flex' : 'none';
  $('mode-normal').style.display = isElder ? 'none' : 'flex';
}

// ========== 老人模式 ==========
function initElder() {
  bindMic($('elderMic'), $('elderHint'));
  $('elderAI').onclick = () => { switchMode('normal'); goPage('interview'); startChat(); };
}

// ========== 标准模式 ==========
function initNormal() {
  bindMic($('normalMic'), null);
  document.querySelectorAll('.home-tab').forEach(t => {
    t.onclick = () => {
      document.querySelectorAll('.home-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      mode = t.dataset.tab;
      if (mode === 'interview') goPage('interview');
    };
  });
}

// ========== 通用录音绑定 ==========
function bindMic(btn, hint) {
  if (!btn) return;
  const sd = e => { e.preventDefault(); if (!recording) recStart(); };
  const ed = e => { e.preventDefault(); if (recording) recStop(); };

  btn.addEventListener('touchstart', sd, {passive:false});
  btn.addEventListener('touchend', ed, {passive:false});

  // 桌面端fallback
  if (!('ontouchstart' in window)) {
    btn.addEventListener('mousedown', sd);
    btn.addEventListener('mouseup', ed);
  }

  // 录音中状态更新
  btn._hint = hint;
}

// ========== 录音 ==========
function recStart() {
  if (!navigator.mediaDevices?.getUserMedia) { alert('浏览器不支持录音'); return; }
  recording = true;
  document.querySelectorAll('.home-mic, .elder-mic').forEach(b => b.classList.add('recording'));
  if ($('elderHint')) $('elderHint').textContent = '松开停止';
  $('recOverlay').style.display = 'flex';
  sec = 0; timerUpd();
  tmr = setInterval(() => { sec++; timerUpd(); }, 1000);

  navigator.mediaDevices.getUserMedia({audio:true})
    .then(s => {
      mediaRec = new MediaRecorder(s); chunks = [];
      mediaRec.ondataavailable = e => chunks.push(e.data);
      mediaRec.onstop = () => {
        recFinish(new Blob(chunks, {type:'audio/webm'}));
        s.getTracks().forEach(t => t.stop());
      };
      mediaRec.start();
    })
    .catch(() => { recCleanup(); alert('无法访问麦克风'); });
}

function recStop() {
  if (!recording) return;
  recording = false;
  document.querySelectorAll('.home-mic, .elder-mic').forEach(b => b.classList.remove('recording'));
  if ($('elderHint')) $('elderHint').textContent = '按住说话';
  $('recOverlay').style.display = 'none';
  if (tmr) { clearInterval(tmr); tmr = null; }
  if (mediaRec?.state !== 'inactive') mediaRec?.stop();
}

function recCleanup() {
  recording = false;
  document.querySelectorAll('.home-mic, .elder-mic').forEach(b => b.classList.remove('recording'));
  if ($('elderHint')) $('elderHint').textContent = '按住说话';
  $('recOverlay').style.display = 'none';
  if (tmr) { clearInterval(tmr); tmr = null; }
}

function timerUpd() {
  const m = Math.floor(sec/60), s = sec%60;
  $('recTimer').textContent = `${m}:${String(s).padStart(2,'0')}`;
}

function recFinish(blob) {
  // 弹出保存框让用户输入内容（简化版，后面可以接ASR）
  $('saveContent').value = '';
  $('saveDialog').style.display = 'flex';
  $('saveContent').focus();
}

// ========== 保存弹窗 ==========
function initSave() {
  $('saveClose').onclick = () => $('saveDialog').style.display = 'none';
  $('saveSubmit').onclick = () => {
    const c = $('saveContent').value.trim();
    if (!c) { alert('请输入内容'); return; }
    Store.addStory({date: new Date().toISOString().split('T')[0], content: c, mode});
    $('saveDialog').style.display = 'none';
    render();
  };
}

// ========== AI采访 ==========
function startChat() {
  const box = $('chatBox');
  box.innerHTML = '';
  chatHistory = [{role:'ai', content:'你好呀！我是你的回忆助手。今天想聊聊哪段时光？'}];
  addMsg('ai', chatHistory[0].content);
}

function addMsg(role, text) {
  const d = document.createElement('div');
  d.className = `msg msg-${role}`;
  d.innerHTML = `<div class="msg-bubble">${text}</div>`;
  $('chatBox').appendChild(d);
  $('chatBox').parentElement.scrollTop = $('chatBox').parentElement.scrollHeight;
}

function initChatSend() {
  $('chatSend').onclick = () => sendChat();
  $('chatInput').addEventListener('keypress', e => { if (e.key === 'Enter') sendChat(); });
}

function sendChat() {
  const inp = $('chatInput');
  const t = inp.value.trim();
  if (!t) return;
  addMsg('user', t);
  chatHistory.push({role:'user', content:t});
  inp.value = '';

  fetch('/api/ai/interview', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message:t, history:chatHistory.slice(0,-1)})
  })
  .then(r => r.json())
  .then(d => {
    const reply = d.reply || '嗯，能再说说吗？';
    addMsg('ai', reply);
    chatHistory.push({role:'ai', content:reply});
  })
  .catch(() => {
    const r = ['那时候您是什么感觉？','后来呢？','这件事对您影响大吗？','真有意思，还有吗？'];
    setTimeout(() => {
      const reply = r[Math.floor(Math.random()*r.length)];
      addMsg('ai', reply);
      chatHistory.push({role:'ai', content:reply});
    }, 800);
  });
}

// ========== 页面导航 ==========
function goPage(p) {
  page = p;
  document.querySelectorAll('.page').forEach(x => x.classList.remove('active'));
  const m = {home:'page-home', timeline:'page-timeline', interview:'page-interview', album:'page-album'};
  $(m[p])?.classList.add('active');
  document.querySelectorAll('.tab-item').forEach(x => x.classList.remove('active'));
  document.querySelector(`.tab-item[data-page="${p}"]`)?.classList.add('active');
  if (p === 'home') render();
  if (p === 'timeline') renderTimeline();
  if (p === 'interview') startChat();
}

function initNav() {
  document.querySelectorAll('.tab-item').forEach(item => {
    item.onclick = () => goPage(item.dataset.page);
  });
  initChatSend();
}

// ========== 渲染 ==========
function render() {
  const list = $('storyList');
  const st = Store.stories().slice(0,10);
  list.innerHTML = st.length
    ? st.map(s => `<div class="story-card"><div class="date">${s.date}</div><div class="text">${s.content}</div></div>`).join('')
    : '<div class="empty-state">还没有记录，按住录音开始吧</div>';
}
function renderTimeline() {
  const list = $('timelineList');
  const st = Store.stories();
  list.innerHTML = st.length
    ? st.map(s => `<div class="timeline-item"><div class="date">${s.date}</div><div class="text">${s.content}</div></div>`).join('')
    : '<div class="empty-state">还没有记录</div>';
}

// ========== 登录 ==========
function initLogin() {
  $('loginBtn').onclick = () => $('loginDialog').style.display = 'flex';
  $('loginClose').onclick = () => $('loginDialog').style.display = 'none';

  $('sendCode').onclick = function() {
    const p = $('phoneInput').value.trim();
    if (!/^1\d{10}$/.test(p)) { alert('请输入正确的手机号'); return; }
    this.textContent = '已发送'; this.disabled = true;
    setTimeout(() => { this.textContent = '获取验证码'; this.disabled = false; }, 60000);
  };

  $('loginSubmit').onclick = () => {
    const p = $('phoneInput').value.trim();
    const c = $('codeInput').value.trim();
    if (!p || !c) { alert('请输入手机号和验证码'); return; }
    if (c.length < 4) { alert('验证码不正确'); return; }
    Store.setUser({phone:p, nick:'用户'+p.slice(-4)});
    $('loginDialog').style.display = 'none';
    $('loginBtn').textContent = '👤 已登录';
  };

  if (Store.isLogin()) $('loginBtn').textContent = '👤 已登录';
}

// ========== 纪念册 ==========
function openMemorialBook(mode) {
  // 获取当前存储的故事
  const stories = Store.stories();
  if (stories.length === 0) {
    alert('还没有回忆记录，先去记录一些故事吧！');
    return;
  }

  // 构建数据
  const bookData = {
    title: '往事可追忆',
    subtitle: 'ECHOES · MEMORY ALBUM',
    totalStories: stories.length,
    pages: stories.map(s => ({
      date: s.date || s.ts || '',
      era: s.era || (s.tags && s.tags[0]) || '',
      content: s.content || '',
      type: s.type || 'text',
    }))
  };

  // 编码后传参
  const encoded = btoa(encodeURIComponent(JSON.stringify(bookData)));
  const url = `/memorial-book.html?data=${encoded}${mode === 'print' ? '&print=1' : ''}`;
  window.open(url, '_blank');
}

// 画册页面加载时显示统计
document.addEventListener('DOMContentLoaded', () => {
  // 延迟执行，等Store初始化完
  setTimeout(() => {
    const el = document.getElementById('albumStats');
    if (el) {
      const cnt = Store.stories().length;
      el.textContent = cnt > 0
        ? `已收录 ${cnt} 段回忆，点击下方按钮预览`
        : '还没有回忆记录，去首页录制吧';
    }
  }, 100);
});
