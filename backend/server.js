const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');

const app = express();
const PORT = 3000;

// ---------- 数据文件路径 ----------
const DATA_DIR = path.join(__dirname, 'data');
const STORIES_FILE = path.join(DATA_DIR, 'stories.json');

// ---------- 确保 data 目录和 stories.json 存在 ----------
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}
if (!fs.existsSync(STORIES_FILE)) {
  fs.writeFileSync(STORIES_FILE, JSON.stringify([], null, 2), 'utf-8');
}

// ---------- 内存存储 ----------
let stories = [];

// 启动时从 JSON 文件加载到内存
function loadStories() {
  try {
    const raw = fs.readFileSync(STORIES_FILE, 'utf-8');
    stories = JSON.parse(raw);
  } catch (err) {
    console.error('读取 stories.json 失败，使用空数组:', err.message);
    stories = [];
  }
}

// 将内存数据持久化到 JSON 文件
function saveStories() {
  fs.writeFileSync(STORIES_FILE, JSON.stringify(stories, null, 2), 'utf-8');
}

// 初始加载
loadStories();

// ---------- 中间件 ----------
app.use(cors());
app.use(express.json());

// 提供前端静态文件
const frontendPath = path.resolve(__dirname, '..', 'web', 'frontend');
app.use(express.static(frontendPath));

// ---------- API 路由：故事管理 ----------

// GET /api/stories - 获取所有故事
app.get('/api/stories', (req, res) => {
  res.json(stories);
});

// POST /api/stories - 新增故事
app.post('/api/stories', (req, res) => {
  const { title, content, author, tags } = req.body;

  if (!title || !content) {
    return res.status(400).json({ error: 'title 和 content 为必填项' });
  }

  const newStory = {
    id: uuidv4(),
    title,
    content,
    author: author || '匿名',
    tags: tags || [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };

  stories.push(newStory);
  saveStories();

  res.status(201).json(newStory);
});

// PUT /api/stories/:id - 更新故事
app.put('/api/stories/:id', (req, res) => {
  const { id } = req.params;
  const { title, content, author, tags } = req.body;

  const index = stories.findIndex(s => s.id === id);
  if (index === -1) {
    return res.status(404).json({ error: '故事未找到' });
  }

  const existing = stories[index];
  const updatedStory = {
    ...existing,
    title: title !== undefined ? title : existing.title,
    content: content !== undefined ? content : existing.content,
    author: author !== undefined ? author : existing.author,
    tags: tags !== undefined ? tags : existing.tags,
    updatedAt: new Date().toISOString()
  };

  stories[index] = updatedStory;
  saveStories();

  res.json(updatedStory);
});

// DELETE /api/stories/:id - 删除故事
app.delete('/api/stories/:id', (req, res) => {
  const { id } = req.params;

  const index = stories.findIndex(s => s.id === id);
  if (index === -1) {
    return res.status(404).json({ error: '故事未找到' });
  }

  const deleted = stories.splice(index, 1)[0];
  saveStories();

  res.json({ message: '删除成功', story: deleted });
});

// ---------- API 路由：AI 采访 ----------

// POST /api/ai/interview - AI 采访对话（模拟回复）
app.post('/api/ai/interview', (req, res) => {
  const { message, history } = req.body;

  if (!message) {
    return res.status(400).json({ error: 'message 为必填项' });
  }

  // 模拟 AI 回复
  const sampleReplies = [
    '那真是一段难忘的时光，能跟我多聊聊那天的细节吗？',
    '听起来对你影响很大。当时你有什么样的感受？',
    '回忆总是带着特殊的温度。还有别的故事想和我分享吗？',
    '很有意思！这件事让你现在想起还觉得温暖吗？',
    '我理解。有些记忆虽然过去了，但永远留在心里。',
    '能说说那之后发生了什么吗？我很想继续听下去。'
  ];

  const reply = sampleReplies[Math.floor(Math.random() * sampleReplies.length)];

  // 模拟延迟（100~500ms）
  setTimeout(() => {
    res.json({
      reply,
      timestamp: new Date().toISOString()
    });
  }, Math.floor(Math.random() * 400) + 100);
});

// ---------- API 路由：微信登录 ----------

// POST /api/auth/wechat - 微信登录（模拟）
app.post('/api/auth/wechat', (req, res) => {
  const { code } = req.body;

  if (!code) {
    return res.status(400).json({ error: 'code 为必填项' });
  }

  // 模拟微信登录验证
  console.log(`收到微信登录请求，code: ${code}`);

  const mockUser = {
    openid: 'o_' + uuidv4().replace(/-/g, '').substring(0, 16),
    nickname: '往事追忆者',
    avatar: 'https://img.icons8.com/fluency/96/user-male-circle.png',
    token: 'mock_token_' + uuidv4()
  };

  res.json({
    success: true,
    user: mockUser
  });
});

// ---------- 根路径：返回前端 index.html ----------
app.get('/', (req, res) => {
  res.sendFile(path.join(frontendPath, 'index.html'));
});

// ---------- 启动服务器 ----------
app.listen(PORT, () => {
  console.log(`🎉 Echoes（往事可追忆）后端服务器已启动`);
  console.log(`📡 监听端口: http://localhost:${PORT}`);
  console.log(`📁 前端静态文件: ${frontendPath}`);
  console.log(`💾 数据持久化目录: ${DATA_DIR}`);
});
