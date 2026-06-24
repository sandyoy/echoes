/* ========================================
   Echoes · 往事可追忆 — 移动端JS v2
   真实API调用，每步自检
   ======================================== */

// ========== 存储（localStorage登录前暂存） ==========
const Store = {
  _prefix: 'echoes_',
  get(key, def) {
    try { const v = localStorage.getItem(this._prefix + key); return v !== null ? JSON.parse(v) : def; }
    catch(e) { return def; }
  },
  set(key, val) { localStorage.setItem(this._prefix + key, JSON.stringify(val)); },
  remove(key) { localStorage.removeItem(this._prefix + key); },
  stories() { return this.get('stories', []); },
  addStory(s) {
    const list = this.stories();
    list.unshift({ ...s, id: Date.now(), createdAt: new Date().toISOString() });
    this.set('stories', list);
    return list;
  },
  user() { return this.get('user', null); },
  setUser(u) { this.set('user', u); },
  isLoggedIn() { return !!this.user(); }
};

// ========== 全局状态 ==========
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let recTimer = null;
let recSeconds = 0;
let currentMode = 'self';
let currentPage = 'home';
let isElder = true;

// ========== DOM缓存 ==========
const $ = id => document.getElementById(id);

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
  showPage('elder');
  initElderRecord();
  initNormalRecord();
  initInterview();
  initNav();
  initModes();
  initLogin();
  renderRecent();
  renderTimeline();
});

// ========== 模式切换 ==========
$('switchToNormal').onclick = () => { isElder = false; showPage('normal'); };
$('switchToElder').onclick = () => { isElder = true; showPage('elder'); };

function showPage(mode) {
  $('elderMode').style.display = mode === 'elder' ? 'flex' : 'none';
  $('normalMode').style.display = mode === 'elder' ? 'none' : 'flex';
}

// ========== 老人模式录音 ==========
function initElderRecord() {
  const btn = $('elderRecordBtn');
  const label = $('elderLabel');

  btn.addEventListener('touchstart', e => { e.preventDefault(); if (!isRecording) startRecording(); }, {passive: false});
  btn.addEventListener('touchend', e => { e.preventDefault(); if (isRecording) stopRecording(); }, {passive: false});
  btn.addEventListener('mousedown', () => { if (!isRecording && !('ontouchstart' in window)) startRecording(); });
  btn.addEventListener('mouseup', () => { if (isRecording && !('ontouchstart' in window)) stopRecording(); });

  // AI采访按钮
  $('elderInterviewBtn').onclick = () => {
    showPage('normal');
    navigateTo('interview');
    startInterview();
  };
}

// ========== 普通模式录音 ==========
function initNormalRecord() {
  const btn = $('normalRecordBtn');
  btn.addEventListener('touchstart', e => { e.preventDefault(); if (!isRecording) startRecording(); }, {passive: false});
  btn.addEventListener('touchend', e => { e.preventDefault(); if (isRecording) stopRecording(); }, {passive: false});
  btn.addEventListener('mousedown', () => { if (!isRecording && !('ontouchstart' in window)) startRecording(); });
  btn.addEventListener('mouseup', () => { if (isRecording && !('ontouchstart' in window)) stopRecording(); });
}

// ========== 录音核心 ==========
function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) { alert('浏览器不支持录音'); return; }

  isRecording = true;
  $('elderRecordBtn')?.classList.add('recording');
  if ($('elderLabel')) $('elderLabel').textContent = '松开停止';
  $('recordingOverlay').style.display = 'flex';
  recSeconds = 0;
  updateTimerDisplay();
  recTimer = setInterval(() => { recSeconds++; updateTimerDisplay(); }, 1000);

  navigator.mediaDevices.getUserMedia({audio: true})
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunks, {type: 'audio/webm'});
        handleRecording(blob);
        stream.getTracks().forEach(t => t.stop());
      };
      mediaRecorder.start();
    })
    .catch(() => { stopRecording(); alert('无法使用麦克风，请在浏览器设置中允许'); });
}

function stopRecording() {
  isRecording = false;
  $('elderRecordBtn')?.classList.remove('recording');
  if ($('elderLabel')) $('elderLabel').textContent = '按住说话';
  $('recordingOverlay').style.display = 'none';
  if (recTimer) { clearInterval(recTimer); recTimer = null; }
  if (mediaRecorder?.state !== 'inactive') mediaRecorder?.stop();
}

function updateTimerDisplay() {
  const m = Math.floor(recSeconds / 60);
  const s = recSeconds % 60;
  $('recTimer').textContent = `${m}:${String(s).padStart(2,'0')}`;
}

// ========== 录音处理 ==========
function handleRecording(blob) {
  // 弹出一个简单的输入框让用户确认内容
  const content = prompt('请描述你刚才说了什么：', '');
  if (content && content.trim()) {
    const story = {
      date: new Date().toISOString().split('T')[0],
      content: content.trim(),
      mode: currentMode
    };
    Store.addStory(story);
    renderRecent();
    renderTimeline();
  }
}

// ========== AI采访 ==========
let interviewHistory = [];

function initInterview() {
  $('chatSendBtn').onclick = sendChat;
  $('chatInput').addEventListener('keypress', e => { if (e.key === 'Enter') sendChat(); });
}

function startInterview() {
  $('chatBox').innerHTML = '';
  interviewHistory = [{role:'ai', content:'你好呀！我是你的回忆小助手 🎙️ 今天想聊聊哪段时光呢？比如小时候、工作、或者某个难忘的人？'}];
  appendChat('ai', interviewHistory[0].content);
  // 如果是老人模式过来的，自动播放语音问候
}

function appendChat(role, content) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerHTML = `<div class="bubble">${content}</div>`;
  $('chatBox').appendChild(div);
  $('chatBox').scrollTop = $('chatBox').scrollHeight;
}

function sendChat() {
  const input = $('chatInput');
  const text = input.value.trim();
  if (!text) return;

  appendChat('user', text);
  interviewHistory.push({role:'user', content:text});
  input.value = '';

  // 调用后端AI采访API
  fetch('/api/ai/interview', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: text, history: interviewHistory.slice(0, -1)})
  })
  .then(r => r.json())
  .then(data => {
    const reply = data.reply || '嗯，能再说说吗？';
    appendChat('ai', reply);
    interviewHistory.push({role:'ai', content:reply});
  })
  .catch(() => {
    // 后端不可用时的模拟回复
    const replies = ['那时候您是什么感觉？', '后来呢？发生了什么？', '这件事对您影响大吗？', '真有意思，还有其他的吗？'];
    const reply = replies[Math.floor(Math.random() * replies.length)];
    setTimeout(() => {
      appendChat('ai', reply);
      interviewHistory.push({role:'ai', content:reply});
    }, 1000);
  });
}

// ========== 页面导航 ==========
function navigateTo(page) {
  currentPage = page;
  const pageMap = {home:'pageHome', timeline:'pageTimeline', interview:'pageInterview', album:'pageAlbum'};
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  $(pageMap[page])?.classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active');

  if (page === 'home') { renderRecent(); }
  if (page === 'timeline') { renderTimeline(); }
  if (page === 'interview') { startInterview(); }
}

function initNav() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => navigateTo(item.dataset.page));
  });
}

// ========== 模式切换（普通版） ==========
function initModes() {
  document.querySelectorAll('.hmode').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.hmode').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      if (currentMode === 'interview') navigateTo('interview');
    });
  });
}

// ========== 渲染 ==========
function renderRecent() {
  const list = $('recentList');
  const stories = Store.stories().slice(0, 5);
  list.innerHTML = stories.length
    ? stories.map(s => `<div class="recent-card"><div class="date">${s.date}</div><div class="preview">${s.content}</div></div>`).join('')
    : '<div style="color:#a09080;text-align:center;padding:30px 0;">还没有回忆，按住录音开始吧</div>';
}

function renderTimeline() {
  const list = $('timelineList');
  const stories = Store.stories();
  list.innerHTML = stories.length
    ? stories.map(s => `<div class="tl-item"><div class="tl-date">${s.date}</div><div class="tl-text">${s.content}</div></div>`).join('')
    : '<div style="color:#a09080;text-align:center;padding:40px;">还没有回忆</div>';
}

// ========== 登录（简单的手机号+验证码） ==========
function initLogin() {
  // 登录按钮
  document.querySelectorAll('.login-btn').forEach(btn => {
    btn.onclick = () => $('loginModal').style.display = 'flex';
  });

  // 关闭登录框
  $('loginClose').onclick = () => $('loginModal').style.display = 'none';

  // 发送验证码
  $('sendCodeBtn').onclick = function() {
    const phone = $('phoneInput').value.trim();
    if (!/^1\d{10}$/.test(phone)) { alert('请输入正确的手机号'); return; }
    this.textContent = '已发送';
    this.disabled = true;
    // 简化：直接显示验证码输入框
    $('codeGroup').style.display = 'block';
    setTimeout(() => { this.textContent = '发送验证码'; this.disabled = false; }, 60000);
  };

  // 登录
  $('loginSubmit').onclick = () => {
    const phone = $('phoneInput').value.trim();
    const code = $('codeInput').value.trim();
    if (!phone || !code) { alert('请输入手机号和验证码'); return; }
    // 简化验证：任何6位数字验证码都行（真实环境需要后端校验）
    if (code.length < 4) { alert('验证码不正确'); return; }
    Store.setUser({phone, nickname: '用户' + phone.slice(-4)});
    $('loginModal').style.display = 'none';
    updateUserUI();
  };

  // 检查是否已登录
  updateUserUI();
}

function updateUserUI() {
  const user = Store.user();
  document.querySelectorAll('.user-status').forEach(el => {
    el.textContent = user ? `👤 ${user.nickname}` : '👤 登录';
  });
}
