# 财务记账工具 — 部署说明

## 项目结构

```
财务记账工具/
├── frontend/          # 前端页面（HTML+CSS+JS）
│   ├── index.html     # 主页面
│   ├── style.css      # 样式
│   └── app.js         # 交互逻辑
├── backend/           # 后端服务
│   ├── main.py        # FastAPI 服务入口
│   ├── parser.py      # 微信账单解析引擎
│   ├── database.py    # SQLite 数据库操作
│   └── requirements.txt  # Python 依赖
├── deploy/
│   └── nginx.conf     # Nginx 反向代理配置
├── start.sh           # 一键启动脚本
└── README.md          # 本文件
```

## 部署步骤

### 1. 上传到服务器

将整个 `财务记账工具/` 目录上传到你的服务器。

### 2. 安装依赖

```bash
cd 财务记账工具/backend
pip3 install -r requirements.txt
```

### 3. 修改密码（可选）

默认管理员账号：`admin / admin123`

首次登录后建议修改密码。如需修改默认密码，编辑 `main.py` 中的 `lifespan` 函数。

### 4. 启动服务

```bash
cd 财务记账工具
chmod +x start.sh
./start.sh 8008
```

服务默认监听 `0.0.0.0:8008`。

### 5. Nginx 配置（域名访问）

1. 将 `deploy/nginx.conf` 复制到 `/etc/nginx/sites-available/`
2. 修改其中的 `server_name` 和 SSL 证书路径
3. 启用站点并重启 Nginx：

```bash
sudo ln -s /etc/nginx/sites-available/finance.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6. 守护进程（建议用 supervisor 或 systemd）

示例 systemd 服务 `/etc/systemd/system/finance.service`：

```ini
[Unit]
Description=财务记账工具
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/财务记账工具
ExecStart=/usr/bin/python3 /path/to/财务记账工具/backend/main.py
Restart=always
RestartSec=5
Environment=PORT=8008
Environment=HOST=0.0.0.0

[Install]
WantedBy=multi-user.target
```

## 功能说明

- **上传账单**：支持微信支付导出的 `.xlsx` 格式账单
- **自动分类**：按餐饮、交通、购物、教育、医疗、生活等自动归类
- **图表展示**：分类饼图 + 月度趋势图
- **筛选查询**：按分类、月份、收支类型筛选交易明细
- **多用户**：支持注册多个账号，数据隔离
- **数据持久化**：所有数据存储在 SQLite 数据库中

## 扩展计划

- [ ] 支付宝账单解析（.csv 格式）
- [ ] 银行卡账单解析
- [ ] 自定义分类规则
- [ ] 数据导出（Excel / PDF）
- [ ] 标签 / 备注功能
