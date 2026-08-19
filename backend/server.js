const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const https = require('https');

// ---------- 纪念册模块 ----------
const { generateBookData, encodeBookData } = require('./memorial-book');

// ---------- 加载 .env 环境变量 ----------
try {
  const envPath = path.join(__dirname, '.env');
  if (fs.existsSync(envPath)) {
    const envContent = fs.readFileSync(envPath, 'utf-8');
    envContent.split('\n').forEach(line => {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#')) {
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          const val = trimmed.slice(eqIdx + 1).trim();
          if (!process.env[key]) {
            process.env[key] = val;
          }
        }
      }
    });
    console.log('  ✅ 已加载 .env 配置文件');
  }
} catch (e) {
  console.log('  ⚠️  .env 文件读取失败（非致命）:', e.message);
}

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

function loadStories() {
  try {
    const raw = fs.readFileSync(STORIES_FILE, 'utf-8');
    stories = JSON.parse(raw);
  } catch (err) {
    console.error('读取 stories.json 失败，使用空数组:', err.message);
    stories = [];
  }
}

function saveStories() {
  fs.writeFileSync(STORIES_FILE, JSON.stringify(stories, null, 2), 'utf-8');
}

loadStories();

// ---------- 中间件 ----------
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// 提供前端静态文件
const frontendPath = path.resolve(__dirname, '..', 'web', 'frontend');
app.use(express.static(frontendPath));

// ==========================================
// TTS 语音合成（调用边缘 TTS）
// ==========================================

const { execSync } = require('child_process');
const TTS_CACHE_DIR = path.join(DATA_DIR, 'tts_cache');
if (!fs.existsSync(TTS_CACHE_DIR)) {
  fs.mkdirSync(TTS_CACHE_DIR, { recursive: true });
}

const ttsEnabled = (function() {
  try {
    execSync('python3 -c "import edge_tts"', { stdio: 'ignore' });
    return true;
  } catch(e) {
    return false;
  }
})();

if (!ttsEnabled) {
  console.log('  🔊 TTS语音:    ⚠️ edge-tts 未安装，语音功能不可用');
}

// POST /api/ai/tts - 文字转语音
app.post('/api/ai/tts', (req, res) => {
  const { text } = req.body;
  
  if (!text || !text.trim()) {
    return res.status(400).json({ error: 'text 为必填项' });
  }

  if (!ttsEnabled) {
    return res.status(503).json({ error: 'TTS 服务未启用' });
  }

  // 限制长度
  const ttsText = text.trim().substring(0, 500);
  
  try {
    // 调用 Python TTS 脚本
    const result = execSync(`python3 "${__dirname}/tts.py" ${JSON.stringify(ttsText)}`, {
      encoding: 'utf-8',
      timeout: 30000,
      maxBuffer: 1024 * 1024
    });
    
    const parsed = JSON.parse(result.trim());
    const audioPath = parsed.filepath;
    
    if (!fs.existsSync(audioPath)) {
      return res.status(500).json({ error: '语音生成失败' });
    }

    // 返回音频文件（流式响应，不缓存到内存）
    const stat = fs.statSync(audioPath);
    res.writeHead(200, {
      'Content-Type': 'audio/mpeg',
      'Content-Length': stat.size,
      'Cache-Control': 'public, max-age=31536000',
      'X-TTS-Cached': parsed.cached ? 'true' : 'false'
    });
    const readStream = fs.createReadStream(audioPath);
    readStream.pipe(res);
  } catch (err) {
    console.error('TTS 生成失败:', err.message);
    res.status(500).json({ error: '语音生成失败' });
  }
});

// ==========================================
// AI 采访 - 对接 DeepSeek API
// ==========================================

// AI 采访的系统提示词 - 模拟一位温暖、有经验的访谈者
const INTERVIEW_SYSTEM_PROMPT = `你是一位温暖、耐心的回忆采访者，正在帮助一位老人回忆他/她的人生故事。

## 你的角色
- 你像一位经验丰富的纪录片访谈导演，也像一位亲切的老朋友
- 你的目标是引导对方自然地讲述回忆，而不是机械地提问
- 你具备出色的倾听能力和共情能力

## 采访原则
1. **顺着话题深入**：对方提到什么，你就深入追问什么，不要生硬切换话题
2. **有情感回应**：对方说到开心的事，你跟着开心；说到难过的事，你给予温暖安慰
3. **自然引导**：用"后来呢？""那时候您是什么感觉？"这样的方式推进
4. **避免冷冰冰的提问**：不要像问卷调查一样问"请描述您的童年"
5. **记笔记**：记住对方之前说过的人和事，后续可以呼应

## 语气风格
- 温暖、亲切、有耐心
- 用"您"尊称
- 适当使用语气词（"嗯"、"那"、"真好"）
- 回复不要超过100字，保持口语化

## 示例对话
用户说："我小时候住在乡下，门口有棵大槐树。"
你应该回应："嗯，大槐树…一到夏天树荫肯定特别凉快吧？您那时候是不是经常在树底下玩？"

用户说："我老伴走了三年了。"
你应该回应："三年了…您一定很想她吧。能跟我聊聊你们是怎么认识的吗？如果您愿意说的话。"

用户说："今天不太想聊了。"
你应该回应："没关系，咱就不聊了。回忆这事儿什么时候想说再说，您别勉强。要不要去看看您以前保存的照片？"`;

// 调用 DeepSeek API
function callDeepSeek(messages) {
  return new Promise((resolve, reject) => {
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) {
      // 如果没有 API Key，使用模拟回复
      resolve(generateMockReply(messages));
      return;
    }

    const data = JSON.stringify({
      model: 'deepseek-chat',
      messages: messages,
      temperature: 0.8,
      max_tokens: 200
    });

    const options = {
      hostname: 'api.deepseek.com',
      path: '/v1/chat/completions',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      }
    };

    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          const result = JSON.parse(body);
          if (result.choices && result.choices[0]) {
            resolve(result.choices[0].message.content);
          } else {
            console.error('DeepSeek API 返回异常:', body);
            resolve(generateMockReply(messages));
          }
        } catch (e) {
          console.error('解析 DeepSeek 响应失败:', e.message);
          resolve(generateMockReply(messages));
        }
      });
    });

    req.on('error', (e) => {
      console.error('DeepSeek API 请求失败:', e.message);
      resolve(generateMockReply(messages));
    });

    req.write(data);
    req.end();
  });
}

// 备用：模拟回复（当 API 不可用时）
function generateMockReply(messages) {
  const lastUserMsg = messages[messages.length - 1].content;
  
  const replies = {
    '童年': '小时候的事儿总是特别清晰呢。您那时候最喜欢跟谁一起玩呀？',
    '学校': '上学的时候总有一些特别难忘的事。您还记得您的第一位老师吗？',
    '工作': '第一份工作总是让人印象深刻的。当时是怎么找到那份工作的呢？',
    '结婚': '结婚那天一定很特别吧？能跟我聊聊那天最难忘的细节吗？',
    '孩子': '孩子是父母最大的牵挂。孩子小时候有没有什么让您特别开心的事？',
    '父母': '说起父母，总让人心里暖暖的。您觉得您最像他们哪一点？',
    '朋友': '老朋友最珍贵了。您跟这位朋友是怎么认识的？',
    '老家': '老家总是充满了回忆。您现在还会经常想起那里的样子吗？',
    'default': '嗯，我在认真听。您能再多说说那段时光吗？那时候您是什么感觉？'
  };

  for (const [keyword, reply] of Object.entries(replies)) {
    if (lastUserMsg.includes(keyword)) {
      return reply;
    }
  }
  return replies['default'];
}

// POST /api/ai/interview - 真正的 AI 采访对话
app.post('/api/ai/interview', async (req, res) => {
  const { message, history } = req.body;

  if (!message) {
    return res.status(400).json({ error: 'message 为必填项' });
  }

  try {
    // 构建消息历史
    const messages = [
      { role: 'system', content: INTERVIEW_SYSTEM_PROMPT }
    ];

    // 加入对话历史（最多保留最近10轮）
    if (history && Array.isArray(history)) {
      const recentHistory = history.slice(-10);
      recentHistory.forEach(msg => {
        messages.push({
          role: msg.role === 'ai' ? 'assistant' : 'user',
          content: msg.content
        });
      });
    }

    // 加入当前用户消息
    messages.push({ role: 'user', content: message });

    // 调用 AI
    const reply = await callDeepSeek(messages);

    res.json({
      reply,
      timestamp: new Date().toISOString()
    });

    // 自动保存有价值的回忆（超过15个字）
    if (message.length > 15) {
      // 检测是否包含年份信息
      const yearMatch = message.match(/(\d{4})年/);
      const year = yearMatch ? yearMatch[1] : String(new Date().getFullYear());

      // 检测主题
      const topics = ['童年','小学','求学','工作','结婚','恋爱','孩子','父母','老家','朋友','退休'];
      let topic = '';
      for (const t of topics) {
        if (message.includes(t)) { topic = t; break; }
      }

      const newStory = {
        id: uuidv4(),
        date: `${year}-01-01`,
        era: topic || '其他',
        content: message,
        type: 'interview',
        photos: [],
        tags: topic ? [topic] : [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      stories.push(newStory);
      saveStories();
    }
  } catch (err) {
    console.error('AI 采访出错:', err);
    res.status(500).json({ error: 'AI 采访服务暂时不可用' });
  }
});

// ==========================================
// API 路由：故事管理
// ==========================================

// GET /api/stories - 获取所有故事
app.get('/api/stories', (req, res) => {
  res.json(stories);
});

// GET /api/stories/:id - 获取单个故事
app.get('/api/stories/:id', (req, res) => {
  const story = stories.find(s => s.id === req.params.id);
  if (!story) return res.status(404).json({ error: '故事未找到' });
  res.json(story);
});

// POST /api/stories - 新增故事
app.post('/api/stories', (req, res) => {
  const { content, date, era, type, photos, tags, isSubStory, parentStory } = req.body;

  if (!content) {
    return res.status(400).json({ error: 'content 为必填项' });
  }

  const newStory = {
    id: uuidv4(),
    date: date || new Date().toISOString().split('T')[0],
    era: era || '',
    content,
    type: type || 'text',
    photos: photos || [],
    audioUrl: null,
    isSubStory: isSubStory || false,
    parentStory: parentStory || null,
    tags: tags || [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };

  stories.unshift(newStory);
  saveStories();

  res.status(201).json(newStory);
});

// PUT /api/stories/:id - 更新故事
app.put('/api/stories/:id', (req, res) => {
  const { id } = req.params;
  const updates = req.body;

  const index = stories.findIndex(s => s.id === id);
  if (index === -1) {
    return res.status(404).json({ error: '故事未找到' });
  }

  stories[index] = {
    ...stories[index],
    ...updates,
    id: stories[index].id, // 不允许改 ID
    updatedAt: new Date().toISOString()
  };

  saveStories();
  res.json(stories[index]);
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

// GET /api/stories/timeline - 按时间轴获取故事
app.get('/api/stories/timeline', (req, res) => {
  const sorted = [...stories].sort((a, b) => a.date.localeCompare(b.date));
  res.json(sorted);
});

// ==========================================
// API 路由：AI 分析
// ==========================================

// POST /api/ai/analyze - AI 分析回忆内容（提取关键信息、生成标题等）
app.post('/api/ai/analyze', async (req, res) => {
  const { content } = req.body;
  if (!content) {
    return res.status(400).json({ error: 'content 为必填项' });
  }

  try {
    const messages = [
      { role: 'system', content: '你是一个回忆分析助手。请从以下回忆文字中提取关键信息，返回JSON格式：{ "emotion": "喜悦|感动|怀念|平静|感伤", "keyPeople": ["人物1", "人物2"], "keyPlaces": ["地点1"], "decade": "年代(如1980年代)", "suggestion": "一个用于继续引导回忆的问题" }' },
      { role: 'user', content }
    ];

    const reply = await callDeepSeek(messages);
    
    // 尝试解析JSON
    try {
      const jsonMatch = reply.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        const analysis = JSON.parse(jsonMatch[0]);
        res.json(analysis);
      } else {
        res.json({ emotion: '未知', keyPeople: [], keyPlaces: [], decade: '', suggestion: '能再多聊聊吗？' });
      }
    } catch {
      res.json({ emotion: '未知', keyPeople: [], keyPlaces: [], decade: '', suggestion: '能再多聊聊吗？' });
    }
  } catch (err) {
    console.error('AI 分析出错:', err);
    res.status(500).json({ error: '分析服务暂时不可用' });
  }
});

// ==========================================
// API 路由：微信登录
// ==========================================

// POST /api/auth/wechat - 微信登录
app.post('/api/auth/wechat', (req, res) => {
  const { code } = req.body;
  if (!code) {
    return res.status(400).json({ error: 'code 为必填项' });
  }

  console.log(`收到微信登录请求，code: ${code}`);

  const mockUser = {
    openid: 'o_' + uuidv4().replace(/-/g, '').substring(0, 16),
    nickname: '往事追忆者',
    avatar: 'https://img.icons8.com/fluency/96/user-male-circle.png',
    token: 'mock_token_' + uuidv4()
  };

  res.json({ success: true, user: mockUser });
});

// ==========================================
// API 路由：音频上传（微信小程序）
// ==========================================

const multer = require('multer');
const AUDIO_DIR = path.join(DATA_DIR, 'audio');

// 确保音频目录存在
if (!fs.existsSync(AUDIO_DIR)) {
  fs.mkdirSync(AUDIO_DIR, { recursive: true });
}

// Multer 配置 - 音频上传
const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, AUDIO_DIR),
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname) || '.mp3';
    cb(null, `${uuidv4()}${ext}`);
  }
});
const upload = multer({ 
  storage,
  limits: { fileSize: 30 * 1024 * 1024 } // 30MB 限制
});

// POST /api/stories/audio - 上传录音
app.post('/api/stories/audio', upload.single('audio'), (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: '请上传音频文件' });
  }

  const { type, era, duration } = req.body;

  const newStory = {
    id: uuidv4(),
    date: new Date().toISOString().split('T')[0],
    era: era || '',
    content: `[语音回忆 ${duration || '?'}秒]`,
    type: 'audio',
    audioUrl: `/data/audio/${req.file.filename}`,
    duration: parseInt(duration) || 0,
    tags: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };

  stories.unshift(newStory);
  saveStories();

  res.status(201).json(newStory);
});

// POST /api/ai/asr - 语音转文字（用于语音输入）
app.post('/api/ai/asr', upload.single('audio'), (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: '请上传音频文件' });
  }

  const audioPath = req.file.path;
  
  try {
    const result = execSync(`python3 "${__dirname}/asr.py" "${audioPath}"`, {
      encoding: 'utf-8',
      timeout: 30000,
      maxBuffer: 1024 * 1024
    });
    
    const parsed = JSON.parse(result.trim());
    
    if (parsed.error && !parsed.mock) {
      console.error('ASR 识别失败:', parsed.error);
      return res.status(500).json({ error: parsed.error });
    }
    
    res.json({
      text: parsed.text || '(未能识别)',
      source: parsed.source || 'mock'
    });
  } catch (err) {
    console.error('ASR 处理失败:', err.message);
    res.status(500).json({ error: '语音识别失败' });
  } finally {
    // 清理临时音频文件
    try { fs.unlinkSync(audioPath); } catch(e) {}
  }
});

// ==========================================
// 纪念册导出
// ==========================================

// GET /api/memorial-book - 获取纪念册数据（翻页书用）
app.get('/api/memorial-book', (req, res) => {
  const bookData = generateBookData(stories);
  res.json(bookData);
});

// GET /api/memorial-book/encoded - 获取编码后的数据（嵌入翻页书URL）
app.get('/api/memorial-book/encoded', (req, res) => {
  const bookData = generateBookData(stories);
  const encoded = encodeBookData(bookData);
  res.json({ url: `/memorial-book.html?data=${encoded}`, encoded });
});

// ==========================================
// 健康检查
// ==========================================
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    storiesCount: stories.length,
    version: '1.0.0',
    aiPowered: !!process.env.DEEPSEEK_API_KEY
  });
});

// ==========================================
// 根路径：返回前端 index.html
// ==========================================
app.get('/', (req, res) => {
  res.sendFile(path.join(frontendPath, 'index.html'));
});

// ==========================================
// 启动服务器
// ==========================================
app.listen(PORT, () => {
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  🎉 Echoes（往事可追忆）已启动');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log(`  📡 地址:      http://localhost:${PORT}`);
  console.log(`  📁 前端:      ${frontendPath}`);
  console.log(`  💾 数据:      ${DATA_DIR}`);
  console.log(`  🤖 AI采访:    ${process.env.DEEPSEEK_API_KEY ? '✅ 已连接 DeepSeek' : '⚠️ 未配置 API Key（使用模拟回复）'}`);
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
});
