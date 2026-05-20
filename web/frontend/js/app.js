/* ========================================
   Echoes · 往事可追忆
   核心应用逻辑
   ======================================== */

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
  Storage.init();
  renderRecentStories();
  renderTimeline();
  initElderMode();
});

// ========== 页面导航 ==========
function navigateTo(pageName) {
  // 隐藏所有页面
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  
  // 显示目标页面
  const target = document.getElementById(`page-${pageName}`);
  if (target) target.classList.add('active');

  // 更新底部导航高亮
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle('active', item.dataset.page === pageName);
  });

  // 切换页面时刷新内容
  if (pageName === 'timeline') renderTimeline();
  if (pageName === 'album') renderAlbum();
  if (pageName === 'interview') scrollToBottom();
  if (pageName === 'home') renderRecentStories();
}

// ========== 录音功能 ==========
let mediaRecorder = null;
let audioChunks = [];
let recordingTimer = null;
let recordingSeconds = 0;
let currentMode = 'self'; // self | interview | type

function switchMode(mode, btn) {
  currentMode = mode;
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  
  if (mode === 'interview') {
    navigateTo('interview');
  }
}

function startRecording() {
  // 先检查是否是 interview 模式，如果是则转到 AI采访页
  if (currentMode === 'interview') {
    navigateTo('interview');
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert('您的浏览器不支持录音功能，请使用最新版 Chrome 或 Safari。');
    return;
  }

  document.getElementById('recordBtn').classList.add('recording');
  document.getElementById('recordBtn').querySelector('.btn-label').textContent = '松开停止';
  document.getElementById('recordingIndicator').style.display = 'block';
  recordingSeconds = 0;
  updateRecordingTimer();

  recordingTimer = setInterval(() => {
    recordingSeconds++;
    updateRecordingTimer();
  }, 1000);

  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        processRecording(audioBlob);
        stream.getTracks().forEach(t => t.stop());
      };
      mediaRecorder.start();
    })
    .catch(err => {
      console.error('录音失败:', err);
      stopRecording();
      alert('无法访问麦克风，请在浏览器设置中允许麦克风权限。');
    });
}

function stopRecording() {
  document.getElementById('recordBtn').classList.remove('recording');
  document.getElementById('recordBtn').querySelector('.btn-label').textContent = '按住说话';
  document.getElementById('recordingIndicator').style.display = 'none';
  
  if (recordingTimer) {
    clearInterval(recordingTimer);
    recordingTimer = null;
  }

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
}

function updateRecordingTimer() {
  const min = Math.floor(recordingSeconds / 60);
  const sec = recordingSeconds % 60;
  document.getElementById('recordingTimer').textContent = `${min}:${sec.toString().padStart(2, '0')}`;
}

function processRecording(audioBlob) {
  // 保存录音到本地（作为演示，实际会调用语音识别API）
  const audioUrl = URL.createObjectURL(audioBlob);
  
  // 这里模拟语音识别结果
  const mockTranscriptions = [
    '我记得小时候，门口有一棵很大的槐花树，每到春天满院子都是香味...',
    '那年我去当兵，走的时候我妈哭了一路，我坐在车上不敢回头...',
    '说起我老伴儿，我们是在厂里认识的，她是车间里最漂亮的姑娘...'
  ];
  const randomText = mockTranscriptions[Math.floor(Math.random() * mockTranscriptions.length)];

  // 弹出编辑框让用户确认/修改
  showTranscriptionDialog(randomText, audioUrl);
}

function showTranscriptionDialog(text, audioUrl) {
  // 用模态框展示识别结果
  const modal = document.getElementById('storyModal');
  document.getElementById('storyDate').value = new Date().toISOString().split('T')[0];
  document.getElementById('storyContent').value = text;
  document.getElementById('storyEra').value = '';
  document.querySelector('#storyModal h3').textContent = '🎤 录音转文字 - 确认内容';
  modal.classList.add('active');

  // 存储临时音频
  modal.dataset.audioUrl = audioUrl;
}

// ========== AI 采访 ==========
let interviewHistory = [
  {
    role: 'ai',
    content: '你好呀！我是你的回忆小助手 🎙️ 今天想聊聊哪段时光呢？比如小时候、工作、或者某个难忘的人？'
  }
];

const interviewPrompts = {
  '童年': ['您小时候住在什么样的地方？', '您还记得童年最好的朋友吗？', '小时候有什么特别喜欢的游戏吗？'],
  '求学': ['您上学时候印象最深的一件事是什么？', '有没有特别喜欢的老师？', '那时候同学们都玩什么？'],
  '工作': ['您第一份工作是什么？', '工作中遇到过什么难忘的人吗？', '有没有特别有成就感的时候？'],
  '恋爱': ['您和伴侣是怎么认识的？', '还记得第一次约会吗？', '那时候谈恋爱跟现在有什么不同？'],
  '成家': ['结婚那天有什么印象深刻的事？', '刚成家的时候日子过得怎么样？', '您觉得婚姻中最重要的是什么？'],
  '养育': ['孩子出生那天您是什么心情？', '养孩子过程中最辛苦的是什么？', '孩子做过最让您感动的事是什么？'],
  '退休': ['退休后的生活跟想象中一样吗？', '现在每天主要做些什么？', '有什么一直想做但没时间做的事吗？'],
  'default': ['能再详细说说吗？', '那时候您是什么感觉？', '后来呢？发生了什么？', '这件事对您影响大吗？', '真有意思，还有其他的吗？']
};

let currentInterviewTopic = '';
let lastAiMessage = '';

function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;

  // 添加用户消息
  appendChatMessage('user', text);
  interviewHistory.push({ role: 'user', content: text });

  // 检测话题
  detectTopic(text);

  // AI 生成回复（模拟对话，实际会调用后端 API）
  setTimeout(() => {
    const aiReply = generateInterviewReply(text);
    appendChatMessage('ai', aiReply);
    interviewHistory.push({ role: 'ai', content: aiReply });
    lastAiMessage = aiReply;

    // 自动保存为回忆片段
    autoSaveMemory(text, aiReply);
  }, 800 + Math.random() * 1200);

  input.value = '';
}

function appendChatMessage(role, content) {
  const chatBox = document.getElementById('chatBox');
  const msgDiv = document.createElement('div');
  msgDiv.className = `message ${role}`;
  msgDiv.innerHTML = `<div class="bubble">${content}</div>`;
  chatBox.appendChild(msgDiv);
  scrollToBottom();
}

function scrollToBottom() {
  const chatBox = document.getElementById('chatBox');
  chatBox.scrollTop = chatBox.scrollHeight;
}

function detectTopic(text) {
  const topics = ['童年', '小学', '小时候', '父母', '妈妈', '爸爸', '家', '求学', '上学', '老师', '同学', '读书',
    '工作', '上班', '同事', '老板', '创业', '恋爱', '结婚', '老伴', '爱人', '对象',
    '孩子', '儿子', '女儿', '孙子', '孙女', '退休', '养老', '老年'];
  
  for (const topic of topics) {
    if (text.includes(topic)) {
      currentInterviewTopic = topic;
      break;
    }
  }
}

function generateInterviewReply(userText) {
  // 检测用户是否说了有意义的内容
  const hasContent = userText.length > 5;
  
  if (hasContent) {
    // 顺着话题深入引导
    const followUps = interviewPrompts[currentInterviewTopic] || interviewPrompts['default'];
    const prompt = followUps[Math.floor(Math.random() * followUps.length)];
    
    // 根据用户回答内容给出回应
    if (userText.includes('开心') || userText.includes('快乐') || userText.includes('幸福')) {
      return '听您这么说真温暖 😊 那段时光一定很美好。' + prompt;
    } else if (userText.includes('难过') || userText.includes('遗憾') || userText.includes('哭')) {
      return '听到这些，我都能感受到您的心情 🤗 不过能说出来也是一种释然。' + prompt;
    } else if (userText.includes('记得') || userText.includes('想起')) {
      return '记忆真是神奇的东西，越聊越清晰呢 ✨ ' + prompt;
    } else {
      return '嗯，我在认真听 👂 ' + prompt;
    }
  } else {
    return '没关系，慢慢想，想到什么说什么都行 🌸 您刚才说到的，能再聊聊吗？';
  }
}

function autoSaveMemory(userText, aiReply) {
  // 当用户说了有意义的回忆时，自动保存
  if (userText.length > 10) {
    const dateMatch = userText.match(/(\d{4})年/);
    const year = dateMatch ? dateMatch[1] : String(new Date().getFullYear());
    
    Storage.addStory({
      date: `${year}-01-01`,
      era: currentInterviewTopic || '其他',
      content: userText,
      type: 'interview'
    });

    // 刷新时间轴
    renderTimeline();
    renderRecentStories();
  }
}

function startVoiceChat() {
  // 切换到自述模式进行语音输入
  navigateTo('home');
  const selfBtn = document.querySelector('.mode-btn');
  if (selfBtn) switchMode('self', selfBtn);
  setTimeout(() => startRecording(), 300);
}

// ========== 时间轴渲染 ==========
function renderTimeline() {
  const container = document.getElementById('timeline-container');
  const stories = Storage.getAllStories();
  
  if (stories.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:60px 20px;color:var(--text-light);">
        <div style="font-size:3rem;margin-bottom:16px;">📖</div>
        <p>还没有回忆记录</p>
        <p style="font-size:0.9rem;">快去首页说说你的故事吧</p>
      </div>
    `;
    return;
  }

  // 按日期排序（最新的在下面，符合时间轴从早到晚）
  const sorted = [...stories].sort((a, b) => a.date.localeCompare(b.date));

  container.innerHTML = sorted.map(story => {
    const dateObj = new Date(story.date);
    const dateStr = `${dateObj.getFullYear()}年${dateObj.getMonth() + 1}月`;
    
    const dotClass = story.photos.length > 0 ? 'photo' : story.audioUrl ? 'audio' : '';
    const eraTag = story.era ? `<span class="era">${story.era}</span>` : '';
    const photoPreview = story.photos.length > 0 
      ? `<div class="media-preview">${story.photos.map(p => `<img src="${p}" alt="照片" onclick="viewPhoto('${p}')">`).join('')}</div>`
      : '';

    return `
      <div class="timeline-item" onclick="editStory('${story.id}')">
        <div class="dot ${dotClass}"></div>
        <div class="card">
          <div class="date">${dateStr}</div>
          ${eraTag}
          <div class="content">${story.content}</div>
          ${photoPreview}
        </div>
      </div>
    `;
  }).join('');
}

function renderRecentStories() {
  const container = document.getElementById('recent-stories');
  const stories = Storage.getAllStories().slice(0, 5);

  if (stories.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:30px;color:var(--text-light);background:var(--bg-card);border-radius:var(--radius-md);">
        <p>还没有回忆，开始说说你的故事吧 🎤</p>
      </div>
    `;
    return;
  }

  container.innerHTML = stories.map(story => `
    <div class="timeline-item" style="margin-bottom:8px;" onclick="editStory('${story.id}')">
      <div class="card" style="padding:12px;">
        <div class="date">${story.date}</div>
        <div class="content" style="font-size:0.9rem;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">
          ${story.content}
        </div>
      </div>
    </div>
  `).join('');
}

// ========== 故事编辑 ==========
function showNewStoryModal() {
  const modal = document.getElementById('storyModal');
  document.getElementById('storyDate').value = new Date().toISOString().split('T')[0];
  document.getElementById('storyContent').value = '';
  document.getElementById('storyEra').value = '';
  document.getElementById('photoPreview').innerHTML = '';
  document.querySelector('#storyModal h3').textContent = '📝 新回忆';
  modal.dataset.editId = '';
  modal.classList.add('active');
}

function editStory(id) {
  const story = Storage.getStory(id);
  if (!story) return;

  const modal = document.getElementById('storyModal');
  document.getElementById('storyDate').value = story.date;
  document.getElementById('storyContent').value = story.content;
  document.getElementById('storyEra').value = story.era;
  document.querySelector('#storyModal h3').textContent = '✏️ 编辑回忆';

  // 显示已有照片
  const preview = document.getElementById('photoPreview');
  preview.innerHTML = story.photos.map((p, i) => `
    <div style="position:relative;">
      <img src="${p}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;">
      <button onclick="removePhoto(${i})" style="position:absolute;top:-6px;right:-6px;width:20px;height:20px;border-radius:50%;border:none;background:var(--danger);color:white;font-size:12px;cursor:pointer;">×</button>
    </div>
  `).join('');

  modal.dataset.editId = id;
  modal.classList.add('active');
}

function saveStory() {
  const date = document.getElementById('storyDate').value;
  const content = document.getElementById('storyContent').value.trim();
  const era = document.getElementById('storyEra').value;
  const editId = document.getElementById('storyModal').dataset.editId;

  if (!content) {
    alert('请写下你的回忆内容');
    return;
  }

  if (editId) {
    Storage.updateStory(editId, { date, content, era, type: 'text' });
  } else {
    Storage.addStory({ date, content, era, type: currentMode || 'text' });
  }

  closeModal('storyModal');
  renderTimeline();
  renderRecentStories();
}

function deleteCurrentStory() {
  const editId = document.getElementById('storyModal').dataset.editId;
  if (editId && confirm('确定要删除这段回忆吗？')) {
    Storage.deleteStory(editId);
    closeModal('storyModal');
    renderTimeline();
    renderRecentStories();
  }
}

function handlePhotoUpload(event) {
  const files = event.target.files;
  const preview = document.getElementById('photoPreview');
  
  Array.from(files).forEach(file => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = document.createElement('div');
      img.style.position = 'relative';
      img.innerHTML = `
        <img src="${e.target.result}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;">
      `;
      preview.appendChild(img);
    };
    reader.readAsDataURL(file);
  });
}

function removePhoto(index) {
  // 在实际应用中会从数据中移除
}

// ========== 画册功能 ==========
let currentAlbum = null;
let albumPageIndex = 0;

function renderAlbum() {
  const stories = Storage.getAllStories();
  if (stories.length === 0) return;

  // 从故事生成画册
  if (!currentAlbum) {
    currentAlbum = Storage.generateAlbumFromStories(stories.map(s => s.id));
  }
  albumPageIndex = 0;
  showAlbumPage(0);
}

function showAlbumPage(index) {
  if (!currentAlbum || currentAlbum.pages.length === 0) return;

  const page = currentAlbum.pages[index];
  if (!page) return;

  const frontImg = document.querySelector('#albumPhoto img');
  const frontText = document.getElementById('albumText');
  const backImg = document.querySelector('#albumPhotoBack img');
  const backText = document.getElementById('albumTextBack');

  // 当前页
  if (page.photo) {
    frontImg.src = page.photo;
    frontImg.style.display = 'block';
  } else {
    frontImg.style.display = 'none';
  }

  frontText.innerHTML = `
    <h3 style="font-family:var(--font-main);color:var(--primary-dark);margin-bottom:8px;">
      ${page.era || '回忆'}
    </h3>
    <p style="font-size:0.9rem;color:var(--text-secondary);margin-bottom:12px;">${page.date}</p>
    <p>${page.text}</p>
  `;

  // 下一页（如果有）
  const nextPage = currentAlbum.pages[index + 1];
  if (nextPage) {
    if (nextPage.photo) {
      backImg.src = nextPage.photo;
      backImg.style.display = 'block';
    } else {
      backImg.style.display = 'none';
    }
    backText.innerHTML = `
      <p style="font-size:0.9rem;color:var(--text-secondary);margin-bottom:8px;">${nextPage.date}</p>
      <p>${nextPage.text}</p>
    `;
  } else {
    backImg.style.display = 'none';
    backText.innerHTML = `
      <h3 style="font-family:var(--font-main);color:var(--primary-dark);">🌟</h3>
      <p style="color:var(--text-light);">回忆，未完待续...</p>
    `;
  }

  document.getElementById('albumPageNum').textContent = `第 ${index + 1} / ${currentAlbum.pages.length} 页`;
}

function nextAlbumPage() {
  if (!currentAlbum) return;
  const page = document.getElementById('albumPage');
  page.classList.add('flipped');
  
  setTimeout(() => {
    if (albumPageIndex < currentAlbum.pages.length - 1) {
      albumPageIndex++;
      showAlbumPage(albumPageIndex);
    }
    page.classList.remove('flipped');
  }, 600);
}

function prevAlbumPage() {
  if (!currentAlbum) return;
  if (albumPageIndex > 0) {
    albumPageIndex--;
    showAlbumPage(albumPageIndex);
  }
}

// ========== 导出功能 ==========
function exportPDF() {
  alert('📄 PDF 导出功能即将上线！\n\n后续版本将支持一键生成可打印的回忆画册 PDF。');
}

function exportVideo() {
  alert('🎬 短视频生成功能即将上线！\n\n后续版本将支持将回忆制作成有声短视频，分享到抖音/小红书。');
}

// ========== 付费打印 ==========
function showPayModal() {
  document.getElementById('payModal').classList.add('active');
}

function startPayment() {
  alert('💳 支付功能即将上线！\n\n后续将支持微信/支付宝扫码支付，打印实体画册邮寄到家。\n\n预计价格：¥69/本（精装包邮）');
  closeModal('payModal');
}

// ========== 老照片修复 ==========
function restorePhoto(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById('restoreBefore').src = e.target.result;
    document.getElementById('restorePreview').style.display = 'block';
    
    // 模拟修复效果（实际会调用AI修复API）
    setTimeout(() => {
      document.getElementById('restoreAfter').src = e.target.result; // 这里会替换为修复后的图片
      document.getElementById('restoreModal').classList.add('active');
    }, 500);
  };
  reader.readAsDataURL(file);

  // 提示用户
  alert('✨ AI 老照片修复功能即将上线！\n\n后续版本将支持一键修复模糊老照片、上色、去划痕等。');
}

function useRestoredPhoto() {
  // 将修复后的照片用于当前编辑的故事
  const restoredSrc = document.getElementById('restoreAfter').src;
  const preview = document.getElementById('photoPreview');
  const img = document.createElement('div');
  img.style.position = 'relative';
  img.innerHTML = `<img src="${restoredSrc}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;">`;
  preview.appendChild(img);
  closeModal('restoreModal');
}

// ========== 模态框管理 ==========
function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

function showLogin() {
  document.getElementById('loginModal').classList.add('active');
}

function wechatLogin() {
  alert('💬 微信登录即将上线！\n\n后续版本将支持微信一键登录，回忆数据云端同步。');
  closeModal('loginModal');
}

function phoneLogin() {
  alert('📱 手机号登录即将上线！\n\n后续版本将支持短信验证码登录。');
  closeModal('loginModal');
}

// ========== 老人版模式切换 ==========
function initElderMode() {
  const isElder = Storage.getSetting('elderMode');
  if (isElder) {
    document.body.classList.add('elder-mode');
  }
}

function toggleElderMode() {
  document.body.classList.toggle('elder-mode');
  const isElder = document.body.classList.contains('elder-mode');
  Storage.setSetting('elderMode', isElder);
  alert(isElder ? '👓 已切换到老人版' : '👓 已切换到普通版');
}

// ========== 照片查看 ==========
function viewPhoto(src) {
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.9);
    z-index:500;display:flex;align-items:center;justify-content:center;
    cursor:pointer;
  `;
  overlay.innerHTML = `<img src="${src}" style="max-width:90%;max-height:90%;border-radius:8px;">`;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

// ========== 键盘快捷键 ==========
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
  }
});
