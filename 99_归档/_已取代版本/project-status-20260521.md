# Echoes（往事可追忆）项目状态报告
> 生成日期：2026-05-21
> 作者：小鲸鱼 🐳（腾讯云 Hermes）

---

## 一、总体状态

**✅ 服务正在腾讯云运行中**
- 端口：3000
- DeepSeek API：✅ 已连接
- 已有数据：1 条测试故事

---

## 二、代码结构

```
echoes/
├── backend/                  # 后端 API（Node.js + Express）
│   ├── server.js             # 411 行 - 核心 API
│   ├── package.json
│   ├── data/stories.json     # 故事数据（JSON 文件存储）
│   └── node_modules/
├── web/
│   └── frontend/             # 前端（HTML/CSS/JS，无框架）
│       ├── index.html        # 278 行 - 主页
│       ├── jiajiajian.html   # 434 行 - 家家健页面
│       ├── css/style.css     # 792 行 - 样式（含老人版）
│       ├── js/app.js         # 620 行 - 核心交互逻辑
│       ├── js/storage.js     # 207 行 - 本地存储
│       └── manifest.json     # PWA 离线支持
├── docs/                     # 文档目录
├── deploy.sh                 # 一键部署脚本（125 行）
├── start.sh                  # 启动脚本（73 行）
├── echoes-nginx.conf         # Nginx 部署配置（138 行）
├── package.json
└── README.md                 # 项目简介
```

**总代码量：约 3,100 行**

---

## 三、已实现的功能

| 功能 | 状态 | 说明 |
|------|------|------|
| AI 采访式对话 | ✅ | 对接 DeepSeek，有自动降级（无 API Key 时模拟回复） |
| 录音自述 | ✅ | 浏览器录音，支持按住说话 |
| 打字输入 | ✅ | 手动输入回忆 |
| 时间轴可视化 | ✅ | 按时间排序展示 |
| 照片插入 | ✅ | 支持多照片 |
| 多故事线 | ✅ | 支持子故事关联 |
| 翻页电子画册 | ✅ | 生成翻页书 |
| 老人版 UI | ✅ | 大字体大按钮高对比度模式切换 |
| 微信登录 | ✅ | 当前为 mock 实现 |
| PWA 离线支持 | ✅ | manifest.json 配置 |
| HTTPS / Nginx | ⚠️ | 配置已写好，尚未绑定域名和申请证书 |
| 一键部署 | ✅ | deploy.sh / start.sh |

---

## 四、Git 提交历史

```
c843a97   ✨ 接入真实AI采访 - 后端对接DeepSeek
9635a01   Add .gitignore
84937ce   🎉 初版：Echoes 往事可追忆 - Web版完整前端
```

远程仓库：`https://github.com/sandyoy/echoes.git`

---

## 五、待办事项

- [ ] 微信小程序 `wechat-miniprogram/` 目录为空，尚未开发
- [ ] `docs/` 目录尚未充实
- [ ] 绑定域名并配置 HTTPS 证书
- [ ] 外网可访问配置

---

## 六、运行说明

```bash
# 启动（腾讯云上）
cd ~/echoes
bash start.sh

# 或直接
cd backend && node server.js

# 访问
http://localhost:3000
```
