# Echoes · 往事可追忆 🎙️📖

> 把零散的回忆，串成一生最美的故事

## 项目简介

Echoes 是一款帮助老人记录人生回忆的数字化工具。通过 AI 采访、自述录音、照片插入等方式，将零散的回忆片段自动整理成时间轴，并最终生成可打印的画册、电子书或短视频，分享给家人朋友。

## 项目结构

```
echoes/
├── web/                  # Web 网页版 (PWA，支持桌面图标)
│   ├── frontend/         # 前端页面 (HTML/CSS/JS)
│   └── public/           # 静态资源
├── backend/              # 后端 API 服务 (Node.js/Python)
│   ├── api/              # RESTful API
│   ├── models/           # 数据模型
│   └── services/         # 业务逻辑
├── wechat-miniprogram/   # 微信小程序
└── docs/                 # 文档
```

## 技术栈

- **Web 前端**：HTML5 + CSS3 + JavaScript (Vanilla JS / Vue.js)
- **后端**：Node.js (Express) 或 Python (FastAPI)
- **数据库**：SQLite（开发）/ PostgreSQL（生产）
- **AI 能力**：语音识别、老照片修复、多语言翻译
- **部署**：腾讯云服务器

## 功能模块

- [x] AI 采访式对话回忆
- [x] 自述录音 + 文字输入
- [x] 时间轴可视化
- [x] 照片/语音/文字增删改
- [x] 多故事线管理
- [x] 电子画册生成 (翻页书)
- [x] 短视频生成
- [x] PDF 可打印输出
- [x] 老人版 UI / 普通版 UI
- [x] 微信登录
- [x] 付费打印服务

## License

MIT
