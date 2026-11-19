# MSIA 审核管理系统 - 后端

基于 FastAPI 构建的审核管理后端服务, 对接 SQL Server 数据库与内网邮件服务。

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy 2.0 (声明式) + pyodbc (SQL Server)
- Pydantic v2 + pydantic-settings
- JWT (PyJWT) + passlib[bcrypt] 密码哈希
- APScheduler (后台定时任务: 用户同步 / 逾期扫描)
- reportlab (PDF) + openpyxl (Excel)
- loguru (日志)
- PyInstaller (打包)

## 环境要求

- Python 3.11+
- ODBC Driver 17 for SQL Server (需在运行机器安装)
- SQL Server 可访问 (主库 CN_AME, HR 库 HRDB)

## 安装

```bash
# 进入 backend 目录
cd backend

# 创建虚拟环境 (Windows)
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制并填写环境变量
copy .env.example .env
# 编辑 .env, 填入实际的数据库与邮件配置
```

## 运行

```bash
# 方式一: 直接运行入口
python run.py

# 方式二: uvicorn 热重载 (开发模式)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问:

- API 文档 (Swagger): http://localhost:8000/docs
- ReDoc 文档: http://localhost:8000/redoc

## 打包

```bash
pyinstaller build.spec
```

打包结果位于 `dist/MSIABackend/` 目录, 运行其中的 `MSIABackend.exe` 启动服务。
打包目录中需放置 `.env` 配置文件 (打包脚本会自动包含已存在的 .env)。

## 目录结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口: CORS / 路由 / 静态文件 / 调度器
│   ├── core/                # 配置 / 安全 / 依赖
│   ├── models/              # SQLAlchemy 模型 (CN_AME_MISA_ 前缀)
│   ├── schemas/             # Pydantic 数据模型
│   ├── api/                # 路由层
│   ├── services/            # 业务服务 (同步 / 邮件 / 报告 / 通知)
│   ├── db/                  # 数据库会话
│   ├── scheduler/           # APScheduler 调度器
│   └── utils/               # 工具函数
├── requirements.txt
├── .env.example
├── build.spec               # PyInstaller 打包配置
├── run.py                   # 入口
└── README.md
```

## 主要功能

- 用户认证 (JWT) 与角色权限 (admin / lead_reviewer / reviewer / reviewee)
- 项目 / 阶段 / 检查项管理
- 审核记录与问题跟踪
- 附件上传下载
- 报告导出 (PDF / Excel)
- 站内通知与邮件提醒
- 每周从 HRDB 自动同步用户 (周一 02:00)
- 每日扫描逾期问题并发送提醒 (08:00)

## 配置说明

详见 `.env.example`, 关键配置项:

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 主数据库 SQLAlchemy 连接串 |
| `HRDB_CONNECTION_STRING` | HR 库 pyodbc 连接串 (用户同步) |
| `EMAIL_SMTP_HOST/PORT` | SMTP 服务器 (无认证) |
| `JWT_SECRET_KEY` | JWT 签名密钥 (生产环境务必修改) |
| `CORS_ORIGINS` | CORS 允许来源, 逗号分隔 |
| `STORAGE_PATH` | 附件存储目录 |
