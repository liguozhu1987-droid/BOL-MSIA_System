# MSIA 审核管理系统 - Code Wiki

> 版本: 1.0.0 | 最后更新: 2026-08-17

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [整体架构](#3-整体架构)
4. [目录结构](#4-目录结构)
5. [后端核心模块详解](#5-后端核心模块详解)
   - 5.1 [入口与生命周期](#51-入口与生命周期)
   - 5.2 [配置系统](#52-配置系统)
   - 5.3 [数据库层](#53-数据库层)
   - 5.4 [API 路由层](#54-api-路由层)
   - 5.5 [数据模型层 (Models)](#55-数据模型层-models)
   - 5.6 [业务服务层 (Services)](#56-业务服务层-services)
   - 5.7 [调度器 (Scheduler)](#57-调度器-scheduler)
6. [前端核心模块详解](#6-前端核心模块详解)
   - 6.1 [前端构建配置](#61-前端构建配置)
   - 6.2 [路由系统](#62-路由系统)
   - 6.3 [API 客户端层](#63-api-客户端层)
   - 6.4 [页面组件](#64-页面组件)
   - 6.5 [状态管理](#65-状态管理)
7. [数据库模型关系图](#7-数据库模型关系图)
8. [关键业务流程](#8-关键业务流程)
9. [项目运行方式](#9-项目运行方式)
10. [打包与部署](#10-打包与部署)

---

## 1. 项目概述

**MSIA 审核管理系统** (Manufacturing System Implementation Audit) 是 Inalfa 内部使用的制造业体系审核流程管理平台，用于规范从项目立项到量产各阶段（MSIA1~MSIA5）的审核活动、问题跟踪与闭环整改。

### 核心功能

| 功能模块 | 说明 |
|---------|------|
| 用户与权限 | 从 HRDB 自动同步用户，支持 admin/lead_reviewer/reviewer/reviewee 四级角色 |
| 项目与阶段管理 | 管理整车项目，支持 MSIA1~MSIA5 五阶段审核流程 |
| 检查项管理 | 维护各阶段的审核条款清单（Checklist），支持评分与描述独立编辑 |
| 阶段评审 | 按阶段执行评审，记录每项评分与问题，支持条款联动与自然排序 |
| 问题跟踪 (Issue) | 审核发现的问题登记、分配、整改、验证闭环流程 |
| 工作台 | 责任人视角维护根本原因、纠正措施、计划完成日期 |
| 问题升级机制 | 逾期问题按配置自动触发 Lv1(责任人)→Lv2(部门经理)→Lv3(Director) 升级邮件 |
| 通知系统 | 站内通知 + 邮件双通道，支持测试/生产模式切换 |
| 报告导出 | 支持 PDF / Excel 格式的审核报告导出 |
| 历史评分 | 记录历次审核评分快照，支持趋势分析 |
| 综合看板 | 逾期/在途/关闭问题统计、工厂维度分布图表 |
| 系统设置 | 可配置化管理逾期阈值、升级参数、提醒频率等 |

---

## 2. 技术栈

### 后端 (Backend)

| 分类 | 技术选型 | 版本/说明 |
|-----|---------|----------|
| 语言 | Python | 3.11+ |
| Web 框架 | FastAPI | 异步框架，自动生成 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | 支持热重载的开发服务器 |
| ORM | SQLAlchemy | 2.0 声明式模型 |
| 数据库驱动 | pyodbc | SQL Server ODBC 驱动 |
| 数据验证 | Pydantic | v2 + pydantic-settings |
| 认证授权 | PyJWT + passlib[bcrypt] | JWT Token 认证 + bcrypt 密码哈希 |
| 定时任务 | APScheduler | BackgroundScheduler + CronTrigger |
| 报告生成 | reportlab + openpyxl | PDF + Excel 导出 |
| 日志 | loguru | 结构化日志 |
| 打包 | PyInstaller | onedir 模式打包为 .exe |

### 前端 (Frontend)

| 分类 | 技术选型 | 版本/说明 |
|-----|---------|----------|
| 语言 | TypeScript | 5.3+ |
| UI 框架 | React | 18.2+ |
| 构建工具 | Vite | 5.1+，HMR 热更新 |
| UI 组件库 | Ant Design | 5.14+（浅色工业科技风主题） |
| 图标 | @ant-design/icons | 配套图标库 |
| 路由 | React Router DOM | 6.22+，BrowserRouter 模式 |
| 状态管理 | Zustand | 4.5+，轻量级 store |
| HTTP 客户端 | Axios | 1.6+，统一拦截器 |
| 图表 | ECharts + echarts-for-react | 数据可视化（看板） |
| 日期处理 | dayjs | 轻量日期库 |
| 图片导出 | html-to-image | DOM 转图片 |

### 基础设施

| 组件 | 说明 |
|-----|------|
| 主数据库 | SQL Server (CN_AME 库)，表前缀 `CN_AME_MISA_` |
| HR 数据库 | SQL Server (HRDB 库)，用于用户同步 |
| 邮件服务器 | 内网 SMTP (无需认证) |
| 文件存储 | 本地文件系统 (storage 目录) |

---

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                        用户浏览器                          │
│  ┌──────────────┐     ┌──────────────┐                   │
│  │   Login 页   │────▶│  SPA 前端应用 │ (React + AntD)    │
│  └──────────────┘     └──────┬───────┘                   │
│                              │ /api/* 请求                │
└──────────────────────────────┼───────────────────────────┘
                               │
                       ┌───────▼────────┐
                       │   Vite Dev     │  (开发模式, 端口 5173)
                       │   Proxy /api   │
                       └───────┬────────┘
                               │
┌──────────────────────────────▼───────────────────────────┐
│                  后端 FastAPI 服务 (端口 8000)              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  CORS 中间件 │  │ SPA 静态文件  │  │   API 路由聚合    │ │
│  └─────────────┘  └──────┬───────┘  └────────┬─────────┘ │
│                          │                    │           │
│                          │           ┌────────▼─────────┐ │
│                          │           │   19 个 API 路由  │ │
│                          │           └────────┬─────────┘ │
│                          │                    │           │
│                          │           ┌────────▼─────────┐ │
│                          │           │  Services 业务层  │ │
│                          │           └────────┬─────────┘ │
│                          │                    │           │
│                          │           ┌────────▼─────────┐ │
│                          │           │  SQLAlchemy ORM  │ │
│                          │           └────────┬─────────┘ │
│                          │                    │           │
└──────────────────────────┼────────────────────┼───────────┘
                           │                    │
                  ┌────────▼──────┐   ┌────────▼────────┐
                  │ SQL Server    │   │   本地文件系统    │
                  │ (CN_AME/HRDB) │   │  (storage/)      │
                  └───────────────┘   └─────────────────┘

┌──────────────────────────────────────────────────────────┐
│              APScheduler 后台定时任务 (进程内)              │
│  ┌─────────────────┐  ┌──────────────────┐                │
│  │ 每周一 02:00    │  │ 每日 08:00       │                │
│  │ HR 用户同步     │  │ 逾期问题扫描     │                │
│  └─────────────────┘  └──────────────────┘                │
│  ┌─────────────────┐  ┌──────────────────┐                │
│  │ 每日 08:30      │  │ 每小时 00 分     │                │
│  │ 未维护问题提醒   │  │ 问题升级扫描     │                │
│  └─────────────────┘  └──────────────────┘                │
└──────────────────────────────────────────────────────────┘
```

**架构分层说明**：

1. **表示层**：React SPA 应用，通过 Vite 开发服务器代理或直接请求后端 API
2. **接口层**：FastAPI 路由，负责参数校验、权限验证、返回响应
3. **业务层**：Services 目录中的各类服务，封装核心业务逻辑
4. **数据层**：SQLAlchemy Models + Session，负责持久化
5. **基础设施层**：数据库、文件系统、邮件服务器、HR 数据源
6. **横切层**：APScheduler 调度器，运行在同一进程中

---

## 4. 目录结构

```
MSIA Report/
├── backend/                          # 后端根目录
│   ├── app/
│   │   ├── main.py                   # FastAPI 入口：CORS/路由/静态文件/调度器
│   │   ├── core/                     # 核心：配置、安全、依赖注入
│   │   │   ├── config.py             # ★ 配置中心：config.ini + .env 双重读取
│   │   │   ├── deps.py               # FastAPI 依赖：get_current_user 等
│   │   │   └── security.py           # JWT 生成/验证、密码哈希
│   │   ├── db/
│   │   │   └── session.py            # 数据库引擎、SessionLocal、get_db 依赖
│   │   ├── models/                   # ★ SQLAlchemy 数据模型 (14个表)
│   │   ├── schemas/                  # Pydantic 请求/响应模型
│   │   ├── api/                      # ★ API 路由层 (19个子路由)
│   │   │   └── router.py             # 路由聚合入口
│   │   ├── services/                 # ★ 业务服务层 (10+ 服务)
│   │   ├── scheduler/
│   │   │   └── scheduler.py          # ★ APScheduler 定时任务定义
│   │   ├── scripts/                  # 一次性数据修复脚本
│   │   └── utils/
│   │       └── pagination.py         # 分页工具
│   ├── dist/                         # 前端构建产物 (已构建后拷贝到此处)
│   ├── libs/                         # PyInstaller 打包的依赖库
│   ├── build/                        # PyInstaller 构建临时目录
│   ├── storage/                      # 附件存储目录 (运行时生成)
│   ├── config.ini                    # ★ 生产配置文件 (数据库/邮件/端口等)
│   ├── .env / .env.example           # 开发环境变量模板
│   ├── build.spec                    # PyInstaller 打包配置
│   ├── run.py                        # 可选入口脚本
│   └── README.md                     # 后端说明文档
│
├── frontend/                         # 前端源代码
│   ├── src/
│   │   ├── main.tsx                  # 前端入口：挂载 React App + Router
│   │   ├── App.tsx                   # 根组件
│   │   ├── router/
│   │   │   └── index.tsx             # ★ React Router 路由定义 (14个页面)
│   │   ├── api/                      # ★ Axios API 客户端 (15个模块)
│   │   │   └── client.ts             # Axios 实例：BaseURL/JWT拦截/错误处理
│   │   ├── store/
│   │   │   └── auth.ts               # ★ Zustand 状态：用户/JWT/权限
│   │   ├── layouts/
│   │   │   └── MainLayout.tsx        # 主布局：侧边栏+头部+内容区
│   │   ├── pages/                    # ★ 页面组件 (14个)
│   │   ├── components/               # 通用组件：AuthRoute/Modal 等
│   │   ├── styles/                   # 共享样式 (AntD 主题定制)
│   │   ├── utils/                    # 工具函数
│   │   └── theme.ts                  # AntD 主题配置
│   ├── public/                       # 静态资源 (logo 图片等)
│   ├── dist/                         # Vite 构建输出
│   ├── index.html                    # Vite HTML 模板
│   ├── vite.config.ts                # ★ Vite 配置：代理/别名
│   ├── tsconfig.json                 # TypeScript 配置
│   └── package.json                  # 前端依赖
│
├── 00. MSIA Check list_template.xlsx # 检查项导入模板
├── MSIA_audit_system_*.md            # 历史设计文档
├── MSIA_audit_system_db_schema.sql   # 数据库建表 DDL 参考
└── CODE_WIKI.md                      # ★ 本 Code Wiki 文档
```

---

## 5. 后端核心模块详解

### 5.1 入口与生命周期

**入口文件**: [main.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/main.py#L1-L193)

**关键函数**: `create_app() -> FastAPI`

**应用生命周期 (`lifespan`) 执行顺序**：

```
启动阶段:
  ├─ 1. APScheduler 启动 (注册 4 个定时任务)
  ├─ 2. 可选: 自动建表 (MSIA_AUTO_CREATE_TABLES=1)
  ├─ 3. SystemSetting 表默认配置初始化 (缺失项自动补充)
  └─ 4. 用户表为空时触发首次 HR 用户同步

请求阶段:
  └─ CORS 中间件 → 路由匹配 → 依赖注入 (get_db/get_current_user) → 业务逻辑

关闭阶段:
  └─ APScheduler.shutdown (不等待运行中任务)
```

**SPA 静态文件查找顺序** (优先级从高到低)：
1. PyInstaller `_MEIPASS/dist` (打包内嵌)
2. 可执行程序同目录 `dist/` (部署后)
3. 当前工作目录 `dist/` (开发环境，前端构建产物拷贝到此处)

匹配后挂载 `/assets` 子目录，并注册 catch-all 路由返回 `index.html`，由 React Router 接管前端路由。

---

### 5.2 配置系统

**配置文件**: [config.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/core/config.py#L1-L267)

**配置优先级** (从高到低)：
```
1. 系统环境变量 / .env 文件 (pydantic-settings 自动读取)
2. config.ini 文件 (生产部署用，自动检测 UTF-8/GBK 编码)
3. Settings 类中的硬编码默认值
```

**关键配置项一览**：

| 分组 | 配置项 | 默认值 | 说明 |
|-----|-------|-------|------|
| 数据库 | DATABASE_URL | 由 config.ini 构建 | SQLAlchemy 连接串 |
| 数据库 | HRDB_CONNECTION_STRING | 由 config.ini 构建 | pyodbc 原生 HR 库连接 |
| 邮件 | EMAIL_SMTP_HOST | 172.19.253.10 | 内网 SMTP |
| 邮件 | NOTIFICATION_MODE | production | test=全部发测试邮箱 |
| 安全 | JWT_SECRET_KEY | change-me-in-production | JWT 签名密钥，务必修改 |
| 安全 | JWT_EXPIRE_MINUTES | 43200 (30天) | Token 过期时间 |
| 服务 | APP_HOST / APP_PORT | 0.0.0.0 / 8000 | 监听地址端口 |
| 服务 | SYSTEM_URL | 空 | 邮件正文中的登录链接 |
| 服务 | CORS_ORIGINS | http://localhost:5173 | 跨域白名单，逗号分隔 |
| 服务 | STORAGE_PATH | ./storage | 附件存储路径 |

**数据库连接串自动构建**: 根据 `sql_driver_version` (17/18) 自动适配 `ODBC Driver {N} for SQL Server`，兼容本地开发和 Windows Server 环境差异。

**`Settings` 类属性**：
- `cors_origins_list` → `List[str]`：CORS 拆分后的列表
- `effective_system_url` → `str`：邮件系统访问地址，优先级 SYSTEM_URL > CORS_ORIGINS[0] > 默认
- `is_notification_test_mode` → `bool`：是否测试通知模式

---

### 5.3 数据库层

**文件**: [session.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/db/session.py#L1-L58)

**核心组件**：
- `engine`: SQLAlchemy 引擎，启用 `pool_pre_ping` (连接有效性检查) 和 `fast_executemany` (批量插入优化)
- `SessionLocal`: 会话工厂，`expire_on_commit=False` 避免 commit 后对象属性无法访问
- `get_db()`: FastAPI 依赖注入，`try/finally` 保证会话关闭
- `create_tables()`: 开发模式建表（导入全部 models 后调用 `Base.metadata.create_all`）

**表命名约定** (在 [base.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/models/base.py) 中统一配置)：

| 约束类型 | 命名格式 |
|---------|---------|
| 主键 | PK_MISA_<表名> |
| 唯一约束 | UX_MISA_<表名>_<列名> |
| 索引 | IX_MISA_<表名>_<列名> |
| 外键 | FK_MISA_<表名>_<列名>_<引用表名> |
| 检查约束 | CK_MISA_<表名>_<约束名> |

所有业务表前缀为 `CN_AME_MISA_`，中文字段一律使用 `Unicode/NVARCHAR` 类型避免乱码。

---

### 5.4 API 路由层

**路由聚合**: [router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/router.py#L1-L52)

所有路由统一以 `/api/` 为前缀，共 19 个路由模块：

| 路由文件 | 标签 | 主要端点 | 说明 |
|---------|-----|---------|------|
| [auth.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/auth.py) | 认证 | POST /login, POST /change-password | JWT 登录、修改密码 |
| [users.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/users.py) | 用户 | GET/PUT /api/users/* | 用户CRUD、角色分配、启用/禁用 |
| [projects.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/projects.py) | 项目 | CRUD /api/projects | 项目管理 |
| [phases.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/phases.py) | 阶段 | /api/phases | 阶段（MSIA1-5）管理 |
| [check_items.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/check_items.py) | 检查项 | /api/check-items | 审核条款维护 |
| [phase_review_items.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/phase_review_items.py) | 阶段评审项 | /api/phase-review-items | 阶段检查项实例、评分 |
| [reviews.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/reviews.py) | 评审记录 | /api/reviews | 评审操作记录 |
| [issues.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/issues.py) | 问题 | CRUD /api/issues | 问题登记、分配、整改、关闭 |
| [reports.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/reports.py) | 报告 | GET /api/reports/* | 报告列表、导出 PDF/Excel |
| [phase_reports.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/phase_reports.py) | 阶段报告 | /api/phase-reports | 阶段报告生成 |
| [notifications.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/notifications.py) | 通知 | /api/notifications | 站内通知列表、标为已读 |
| [attachments.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/attachments.py) | 附件 | POST /upload, GET /download | 附件上传下载 |
| [admin.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/admin.py) | 管理 | /api/admin/* | 管理员专用接口 |
| [msia_plan.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/msia_plan.py) | MSIA计划 | /api/msia-plan | 对接 HRDB 的项目计划数据 |
| [workbench.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/workbench.py) | 工作台 | /api/workbench/* | 责任人维护整改信息 |
| [escalation.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/escalation.py) | 升级配置 | CRUD /api/escalation | 升级规则 (工厂+严重等级) |
| [dashboard.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/dashboard.py) | 综合看板 | /api/dashboard/* | 统计图表数据 |
| [historic_scores.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/historic_scores.py) | 历史评分 | /api/historic-scores | 评分快照趋势 |
| [system_settings.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/system_settings.py) | 系统设置 | CRUD /api/system-settings | 动态配置参数 |

---

### 5.5 数据模型层 (Models)

**模型汇总**: [models/__init__.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/models/__init__.py#L1-L44)

共 14 个业务模型 + 2 个日志模型：

| 模型类 | 表名 | 说明 | 关键字段 |
|-------|-----|------|---------|
| **User** | CN_AME_MISA_User | 用户表 | Username, RealName, Email, Role(admin/lead_reviewer/reviewer/reviewee), Status(1启用/0禁用) |
| **UserSyncLog** | CN_AME_MISA_UserSyncLog | 用户同步日志 | SyncBatchId, TotalRead/Inserted/Updated/Failed, Status |
| **Project** | CN_AME_MISA_Project | 项目表 | Name, Code, Status, CmcAme, PlantMe, 里程碑时间 (Kickoff/DesignFreeze/PVP/SOP) |
| **Phase** | CN_AME_MISA_Phase | 阶段表 | ProjectId, Code(MSIA1~MSIA5), LeadReviewerId, Score, Status |
| **CheckItem** | CN_AME_MISA_CheckItem | 审核条款模板 | PhaseCode, ItemNo, Description, ScoringCriteria |
| **PhaseReviewItem** | CN_AME_MISA_PhaseReviewItem | 阶段检查项实例 | PhaseId, CheckItemId, Score, ScoringDescription, Request |
| **PhaseReviewMeta** | CN_AME_MISA_PhaseReviewMeta | 阶段评审元信息 | PhaseId, ReviewerIds, MeetingTime |
| **ReviewRecord** | CN_AME_MISA_ReviewRecord | 评审操作记录 | ActionType, OperatorId, TargetPhase/Item |
| **Issue** | CN_AME_MISA_Issue | 问题表 | IssueNo, Title, OwnerUserId, Severity(H/M/L), Status, PlannedCloseDate, RootCause, CorrectiveAction, ScoreAtClosure, ScoreAfterUpdate |
| **IssueComment** | CN_AME_MISA_IssueComment | 问题评论 | IssueId, UserId, Content |
| **Attachment** | CN_AME_MISA_Attachment | 附件 | FileName, FilePath, FileSize, RefType/RefId |
| **RecordEntry** | CN_AME_MISA_RecordEntry | 操作审计日志 | Action, TargetType/Id, OperatorId |
| **Notification** | CN_AME_MISA_Notification | 站内通知 | UserId, Title, Content, Type, IsRead |
| **EmailLog** | CN_AME_MISA_EmailLog | 邮件发送日志 | ToAddress, Subject, TemplateKey, RefType/RefId, Status, ErrorMsg |
| **EscalationConfig** | CN_AME_MISA_EscalationConfig | 升级配置 | Plant, Severity, Level1/2/3Hours, Level1/2/3Recipients, IsEnabled |
| **EscalationLog** | CN_AME_MISA_EscalationLog | 升级发送日志 | IssueId, ConfigId, Level, RemindCount, SentAt |
| **HistoricScore** | CN_AME_MISA_HistoricScore | 评分快照 | PhaseId, ItemId, Score, CapturedAt, CapturedBy |
| **SystemSetting** | CN_AME_MISA_SystemSetting | 系统动态配置 | Key, Value, Description, Category |

**核心业务关系**：
- `Project 1 ── N Phase` (一个项目 5 个阶段)
- `Phase 1 ── N PhaseReviewItem` (每个阶段有若干检查项实例)
- `PhaseReviewItem 1 ── N Issue` (每个检查项可发现多个问题)
- `User 1 ── N Issue` (通过 OwnerUserId 关联责任人)
- `Issue 1 ── N EscalationLog` (升级记录)
- `EscalationConfig` 通过 (Plant, Severity) 匹配 Issue

---

### 5.6 业务服务层 (Services)

| 服务文件 | 类/函数 | 核心职责 |
|---------|--------|---------|
| [issue_overdue.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/services/issue_overdue.py) | `build_overdue_filter()`<br>`build_overdue_condition()`<br>`is_issue_overdue()`<br>`get_overdue_start()` | ★ 统一逾期判定，供看板/列表/调度三处共用，保证口径一致 |
| email_service.py | `EmailService` | 邮件模板渲染、SMTP 发送、EmailLog 记录、防重去重 |
| notification_service.py | `NotificationService` | 站内通知创建 + 邮件发送联动，支持群发合并 (`create_and_email_group`) |
| user_sync.py | `UserSyncService` | 从 HRDB 拉取用户数据，匹配更新本地 User 表，提取中文名 RealName |
| report_service.py | `ReportService` | PDF/Excel 报告生成、阶段报告打包 |
| phase_report_service.py | - | 阶段评审报告专项生成 |
| system_config_service.py | `get_int()/get_string()/get_bool()`<br>`init_default_settings()` | ★ 动态配置读取，优先级：数据库 > config.ini > 默认值；启动时自动补全缺失项 |
| score_control_service.py | - | 评分管控：问题关闭时快照评分、整改后更新评分 |
| issue_project_service.py | - | 问题与项目/计划关联查询 |
| hrdb_query_service.py | - | HR 数据库通用查询封装 (MSIA 计划等) |

#### ★ 问题逾期判定逻辑 (issue_overdue.py)

**统一判定规则**（按优先级从高到低）：

```
1. Status ∈ {closed, pending_verification} → 不逾期
   (已关闭 / 已申请关闭待审批，即使超期也不算逾期)

2. 若 未维护 PlannedCloseDate 且 CreatedAt < (now - grace_hours)
   → 逾期 (48h 宽限期后必须维护计划完成日期)

3. 若 PlannedCloseDate < now → 逾期
   (未在计划完成日期内申请关闭)

4. 其他 → 不逾期
```

**可配置参数** (从 SystemSetting 读取)：
- `issue_overdue_grace_hours` = 48 (默认)
- `issue_overdue_exempt_statuses` = "closed,pending_verification" (默认)

**对外 API**：
- `build_overdue_filter(now, db) -> tuple`：返回 SQLAlchemy 表达式元组，用于 `query.filter(*filter)`
- `build_overdue_condition(now, db)`：返回组合后的单一布尔表达式，用于 `case()` 等场景
- `is_issue_overdue(issue, now, db) -> bool`：Python 层判定单个 Issue 对象
- `get_overdue_start(issue, now, db) -> datetime | None`：返回逾期起始时间点（升级任务计算逾期时长基准）

---

### 5.7 调度器 (Scheduler)

**文件**: [scheduler.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/scheduler/scheduler.py#L1-L566)

使用 **APScheduler BackgroundScheduler**，内存存储，线程池大小 5，时区 `Asia/Shanghai`。

**4 个定时任务**：

| Job ID | Cron 表达式 | 说明 | 函数 |
|-------|-----------|------|------|
| user_sync_weekly | `mon 02:00` | 每周一 02:00 从 HRDB 同步用户 | `_run_user_sync()` |
| overdue_scan_daily | `daily 08:00` | 每日 08:00 扫描逾期问题，给责任人发邮件 | `_scan_overdue_issues()` |
| unmaintained_scan_daily | `daily 08:30` | 每日 08:30 扫描未维护整改方案的问题，按严重等级频率提醒 | `_scan_unmaintained_issues()` |
| escalation_scan_hourly | `hourly :00` | 每小时整点扫描问题升级，按配置触发 Lv1/Lv2/Lv3 邮件 | `_scan_escalations()` |

#### 任务 1：用户同步
- 新建虚拟服务 → 调用 `UserSyncService.sync_from_hr(db)`
- 首次启动用户表为空时也会调用（跳过定时任务直接执行）

#### 任务 2：逾期问题扫描
- 调用统一 `build_overdue_filter` 查询逾期问题
- 每问题向 OwnerUserId 发送 "问题已逾期" 通知 + 邮件

#### 任务 3：未维护问题提醒（闭环管理）
- **筛选条件**：CreatedAt 超过 N 个工作日前 + RootCause/CorrectiveAction/PlannedCloseDate 至少一项为空
- **提醒频率**（从 SystemSetting 读取）：
  - H (高)：每 1 天提醒
  - M (中)：每 1 工作日提醒
  - L (低)：每 3 工作日提醒
- **幂等性**：通过 EmailLog 查询窗口期内是否已发送

#### 任务 4：问题升级扫描 (★ 复杂逻辑)
```
匹配逻辑:
  对每个未关闭 Issue:
    1. get_overdue_start() 判定是否逾期 → 未逾期则跳过
    2. 按 (OwnerCompany, Severity) 查 EscalationConfig → 无则回退 (Plant="*", Severity)
    3. 计算 overdue_hours = (now - overdue_start)
    4. 对 Lv1/Lv2/Lv3 每一级:
         next_due = (已发送次数 + 1) * LevelNHours
         若 overdue_hours >= next_due → 发送该级别第 N 次邮件
    5. Level1 无收件人配置时使用责任人邮箱
    6. 发送后写入 EscalationLog 更新计数

升级级别:
  Lv1: 责任人 (OwnerEmail 或 Level1Recipients)
  Lv2: 部门经理 (Level2Recipients 配置)
  Lv3: AME Director (Level3Recipients 配置)
```

---

## 6. 前端核心模块详解

### 6.1 前端构建配置

**配置文件**: [vite.config.ts](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/vite.config.ts#L1-L22)

| 配置项 | 值 | 说明 |
|-------|---|------|
| dev 端口 | 5173 | 开发服务器端口 |
| /api 代理 | http://localhost:8000 | 所有 `/api/*` 请求转发到后端 |
| path 别名 | `@` → `./src` | `@/api/client` 等价于 `src/api/client.ts` |

**启动命令** (frontend 目录)：
```bash
npm run dev      # 开发模式 (HMR)
npm run build    # 构建: tsc 检查类型 + vite build → dist/
npm run preview  # 预览构建产物
```

---

### 6.2 路由系统

**文件**: [router/index.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/router/index.tsx#L1-L51)

使用 React Router DOM v6 `createBrowserRouter`，结构如下：

```
/login                         → 登录页 (无鉴权、无布局)
/  ──┐
     │ AuthRoute 组件 (Zustand 中检查 token，无则跳 /login)
     │
     └── MainLayout (侧边栏 + 头部面包屑 + 内容区)
          │
          ├── /dashboard              → 综合看板 Dashboard
          ├── /workbench              → 工作台 Workbench
          ├── /msia-plan              → MSIA 计划 MsiaPlan
          ├── /projects               → 项目列表 Projects
          ├── /projects/:id           → 项目详情 ProjectDetail
          ├── /projects/:id/phases/:phaseId  → 阶段评审 PhaseReview
          ├── /issues                 → 问题列表 Issues
          ├── /checklist              → 检查项维护 Checklist
          ├── /escalation             → 升级配置 Escalation
          ├── /notifications          → 站内通知 Notifications
          ├── /system/users           → 用户管理 SystemUsers
          ├── /historic-score         → 历史评分 HistoricScore
          ├── /system/settings        → 系统设置 SystemSettings
          └── *                       → 404 NotFound
```

---

### 6.3 API 客户端层

**Base 客户端**: `src/api/client.ts`
- 创建 Axios 实例，`baseURL = '/api'`
- **Request 拦截器**：从 Zustand auth store 获取 token，注入 `Authorization: Bearer xxx`
- **Response 拦截器**：
  - 401 Unauthorized → 清空本地 token → 跳转 `/login`
  - 其他 HTTP 错误 → 统一 AntD `message.error` 提示

**15 个 API 模块** (与后端路由对应)：
- auth.ts, projects.ts, phases.ts, checkItems.ts, phaseReviewItems.ts
- reviews.ts, issues.ts, reports.ts, phaseReports.ts, notifications.ts
- escalation.ts, msiaPlan.ts, workbench.ts, system.ts, systemSettings.ts
- historicScores.ts

---

### 6.4 页面组件

共 14 个页面组件，位于 `src/pages/`：

| 页面文件 | 路由 | 核心功能 |
|---------|-----|---------|
| [Login.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Login.tsx) | /login | 用户名密码登录表单，回车提交，成功后写 Zustand + localStorage |
| [Dashboard.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Dashboard.tsx) | /dashboard | 综合看板：ECharts 问题趋势图、工厂分布、严重等级饼图、Top 逾期 |
| [Workbench.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Workbench.tsx) | /workbench | 责任人工作台：维护 RootCause / CorrectiveAction / PlannedCloseDate，申请关闭 |
| [Projects.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Projects.tsx) | /projects | 项目列表 + 新增/编辑弹窗 |
| [ProjectDetail.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/ProjectDetail.tsx) | /projects/:id | 项目详情：5 个阶段卡片，显示状态/评分/负责人，点击跳转评审 |
| [PhaseReview.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/PhaseReview.tsx) | /projects/:id/phases/:phaseId | ★ 阶段评审：检查项列表（自然排序 2.0→2.9→2.10）、评分编辑、问题弹窗、Request 列显示 |
| [Issues.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Issues.tsx) | /issues | 问题列表：多条件筛选、状态流转、详情抽屉 |
| [Checklist.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Checklist.tsx) | /checklist | 检查项模板维护：独立编辑评分描述、条款联动导入 |
| [MsiaPlan.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/MsiaPlan.tsx) | /msia-plan | MSIA 计划列表：对接 HRDB 的实际项目计划 |
| [Escalation.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Escalation.tsx) | /escalation | 升级配置管理：Plant+Severity 唯一、复制功能、启用/禁用 |
| [Notifications.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/Notifications.tsx) | /notifications | 站内通知中心：全部/未读 Tab、批量标为已读 |
| [SystemUsers.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/SystemUsers.tsx) | /system/users | 用户管理：角色分配、禁用/启用、手动同步按钮 |
| [HistoricScore.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/HistoricScore.tsx) | /historic-score | 评分历史趋势：按阶段/条款对比历次评分 |
| [SystemSettings.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/pages/SystemSettings.tsx) | /system/settings | ★ 系统配置：按功能模块分组 (逾期/提醒/升级/邮件等)，修改立即生效 |

---

### 6.5 状态管理

**Store 文件**: `src/store/auth.ts` (Zustand)

```typescript
interface AuthState {
  // 状态
  token: string | null;
  user: CurrentUser | null;  // { id, username, realName, role, email }
  
  // Actions
  setToken(token: string): void;           // 写内存 + localStorage
  setUser(user: CurrentUser): void;
  loginSuccess(token, user): void;         // setToken + setUser 合并
  logout(): void;                          // 清空 + 跳登录页
}

// 持久化: token 存入 localStorage, 启动时从 localStorage 恢复
```

**AuthRoute 组件** (`src/components/AuthRoute.tsx`)：
- Outlet 模式包装受保护路由
- 检查 Zustand.token：
  - 有 → 渲染子路由 (MainLayout)
  - 无 → `<Navigate to="/login" replace />`

---

## 7. 数据库模型关系图

```
┌─────────────────┐        ┌──────────────────┐        ┌─────────────────┐
│      User       │        │     Project      │        │     Phase       │
│─────────────────│        │──────────────────│        │─────────────────│
│ PK Id           │◄───────┤ FK CreatedBy     │        │ PK Id           │
│ Username UK     │        │ PK Id            │──┐     │ FK ProjectId ───┼───┐
│ RealName        │        │ Code UK          │  │     │ Code(MSIA1-5)   │   │
│ Email           │        │ Status           │  └────►│ LeadReviewerId ─┼───┤◄── User
│ Role            │        │ CmcAme/PlantMe   │        │ Score           │   │
│ Status(1/0)     │        │ Kickoff/Freeze...│        │ Status          │   │
└─────────────────┘        └──────────────────┘        └─────────────────┘   │
         ▲                                                           │        │
         │                                                           ▼        │
         │           ┌──────────────────┐        ┌───────────────────────┐    │
         │           │ EscalationConfig │        │ PhaseReviewItem       │    │
         │           │──────────────────│        │───────────────────────│    │
         │           │ PK Id            │        │ PK Id                 │    │
         │           │ Plant+Severity UK│        │ FK PhaseId ───────────┼────┘
         │           │ Level1/2/3Hours  │        │ FK CheckItemId        │
         │           │ Level1/2/3Rcpts  │        │ Score                 │
         │           │ IsEnabled        │        │ ScoringDescription    │
         │           └──────────────────┘        │ Request               │
         │                    ▲                  └──────────┬────────────┘
         │                    │                             │
         │                    │                             ▼
         │           ┌──────────────────┐        ┌───────────────────────┐
         │           │  EscalationLog   │        │        Issue          │
         │           │──────────────────│        │───────────────────────│
         └───────────┤ FK IssueId       │  FK ───┤ PK Id                 │
   OwnerUserId      │ FK ConfigId      │◄────────┤ IssueNo UK            │
                    │ Level(1/2/3)     │         │ Title                 │
                    │ RemindCount      │         │ FK OwnerUserId ───────┘
                    │ SentAt           │         │ OwnerUserName/Name    │
                    └──────────────────┘         │ Severity(H/M/L)       │
                                                 │ Priority               │
                               ┌────────────────►│ Status(open/in_prog..)│
                               │                 │ PlannedCloseDate      │
                               │                 │ RootCause/Corrective..│
                               │                 │ FK PhaseReviewItemId  │
                               │                 │ ScoreAtClosure        │
                               │                 │ ScoreAfterUpdate      │
                               │                 └──────────┬────────────┘
                               │                            │
┌─────────────────┐            │           ┌────────────────▼────────────┐
│  Notification   │            │           │     IssueComment            │
│─────────────────│            │           │─────────────────────────────│
│ FK UserId ──────┼────────────┘           │ FK IssueId                  │
│ Title/Content   │                        │ FK UserId                    │
│ IsRead          │                        │ Content                      │
│ Type/RefType/Id │                        └──────────────────────────────┘
└─────────────────┘

┌─────────────────┐         ┌──────────────────┐        ┌──────────────────┐
│    EmailLog     │         │    CheckItem     │        │ SystemSetting    │
│─────────────────│         │──────────────────│        │──────────────────│
│ ToAddress       │         │ PK Id            │        │ PK Key           │
│ Subject         │         │ PhaseCode        │        │ Value            │
│ TemplateKey     │         │ ItemNo           │        │ Description      │
│ RefType/RefId   │         │ Description      │        │ Category         │
│ Status/ErrorMsg │         │ ScoringCriteria  │        └──────────────────┘
└─────────────────┘         └──────────────────┘

┌─────────────────┐         ┌──────────────────┐        ┌──────────────────┐
│   Attachment    │         │  HistoricScore   │        │  UserSyncLog     │
│─────────────────│         │──────────────────│        │──────────────────│
│ FileName/Path   │         │ FK PhaseId       │        │ SyncBatchId UK   │
│ FileSize        │         │ FK ItemId        │        │ Total Read/I/U/F │
│ RefType/RefId   │         │ Score            │        │ Status           │
│ UploadedBy      │         │ CapturedAt/By    │        └──────────────────┘
└─────────────────┘         └──────────────────┘
```

---

## 8. 关键业务流程

### 8.1 审核主流程

```
1. 创建项目 (admin)
   └─ 自动生成 5 个阶段 (MSIA1~MSIA5)

2. 维护检查项模板 (admin/lead_reviewer)
   └─ 定义每个 PhaseCode 对应的标准条款 (CheckItem)

3. 进入阶段评审 (reviewer + lead_reviewer)
   ├─ 从 CheckItem 克隆生成 PhaseReviewItem 实例
   ├─ 逐条执行评审 → 填写 Score / ScoringDescription / Request
   └─ 发现不符合 → 登记 Issue (关联该检查项)

4. Issue 整改闭环 (责任人 in 工作台)
   ├─ 48h 内维护 PlannedCloseDate + RootCause + CorrectiveAction
   │   (超时触发每日扫描邮件提醒)
   ├─ 整改完成 → 申请关闭 (Status → pending_verification)
   └─ reviewer 验证通过 → 关闭 (Status → closed)
       └─ 验证时重新评分 → 回写 Issue.ScoreAfterUpdate
           └─ 生成 HistoricScore 快照

5. 问题升级 (定时任务每小时扫描)
   ├─ 逾期 → 按 EscalationConfig(工厂+严重等级) 匹配
   ├─ Lv1: 责任人邮箱 (每 Level1Hours 小时重复一次)
   ├─ Lv2: 部门经理 (每 Level2Hours 小时重复一次)
   └─ Lv3: AME Director (每 Level3Hours 小时重复一次)

6. 阶段完成
   └─ 导出阶段评审报告 (PDF / Excel)
```

### 8.2 用户登录流程

```
浏览器 POST /api/auth/login { username, password }
   │
   ▼
后端 security.py: 查 User(Status=1) → bcrypt 校验密码
   │
   ├─ 失败 → 401 { detail: "用户名或密码错误" }
   │
   └─ 成功 → create_access_token(user_id, role, expire=30d)
            └─ 响应 { access_token, token_type, user: {...} }
               │
               ▼
前端 auth.ts store: setToken + setUser
   │
   └─ localStorage 持久化 token → 跳转 /dashboard
```

### 8.3 邮件发送防重与过滤

```
EmailService.send_email(to, subject, body, ...)
   │
   ├─ [过滤1] 禁用账户: 收件人所属 User.Status == 0 → 跳过
   │
   ├─ [过滤2] 测试模式: NOTIFICATION_MODE == test → 替换为测试邮箱
   │
   ├─ [去重] 收件人列表去重 (同一邮件)
   │
   ├─ [防重] 60s 窗口内 (template_key + ref_id + subject + 收件人) 已发送
   │         → 记录 skipped_duplicate 日志，不重复发送
   │         → * 管理员手动 "重发" 可通过 skip_dedup 绕过
   │
   ├─ [发送] smtplib (内网无认证 SMTP)
   │   ├─ 成功 → 写 EmailLog(Status=sent)
   │   └─ 失败 → 撤销登记 (EmailLog 不入库或标记失败)
   │            → 下次调度/手动触发可重试
   │
   └─ [合并群发] create_and_email_group
       → 多人一条站内 Notification 每人一条
       → 邮件合并为一封多收件人 (To: 多个邮箱)
```

---

## 9. 项目运行方式

### 9.1 开发环境启动

**前置条件**：
- Python 3.11+
- Node.js 18+ (含 npm)
- 安装 ODBC Driver 17 for SQL Server
- 能访问 SQL Server (CN_AME + HRDB 库)
- 已配置好 backend/config.ini 中的数据库连接信息

#### 步骤 1：启动后端

```powershell
# 进入 backend 目录
cd "c:\WorkFile\D\OPEX\04-Digital_development\2026\MSIA Report\backend"

# 激活虚拟环境 (若已存在)
.venv\Scripts\Activate.ps1

# 或创建新虚拟环境 + 安装依赖
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 确认 config.ini 中数据库配置正确 (见 backend/config.ini)
#  特别是: db_server, db_user, db_password, sql_driver_version

# 启动后端 (端口 8000)
# 方式一 (推荐):
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 方式二 (如果有 run.py):
python run.py
```

后端启动后访问验证：
- 健康检查: http://localhost:8000/api/health
- Swagger 文档: http://localhost:8000/docs
- ReDoc 文档: http://localhost:8000/redoc

#### 步骤 2：启动前端 (开发模式)

```powershell
# 新开终端，进入 frontend 目录
cd "c:\WorkFile\D\OPEX\04-Digital_development\2026\MSIA Report\frontend"

# 安装依赖 (首次)
npm install

# 启动开发服务器 (端口 5173, 自动代理 /api → 8000)
npm run dev
```

前端启动后访问：http://localhost:5173/

### 9.2 生产模式（使用打包后的 EXE）

```powershell
# 打包产物位于 backend/dist/msia_server/
cd "c:\WorkFile\D\OPEX\04-Digital_development\2026\MSIA Report\backend\dist\msia_server"

# 双击或命令行运行
.\msia_server.exe
```

启动后访问: http://localhost:8000/ (同目录已包含前端 dist，直接打开首页)

如果后端已有构建产物且想快速启动，直接执行：

---

## 10. 打包与部署

### 10.1 前端构建

```bash
cd frontend
npm install
npm run build
# 产物输出到 frontend/dist/
# 将 frontend/dist/* 复制到 backend/dist/ (后端静态文件挂载路径)
```

### 10.2 后端打包 (PyInstaller)

```bash
cd backend

# 确保前端已构建并拷贝到 backend/dist/
# (PyInstaller build.spec 中会包含此目录)

pyinstaller build.spec
# 或使用另一个 spec:
# pyinstaller msia_server.spec

# 产物:
#   backend/build/msia_server/        (临时文件)
#   backend/dist/msia_server/         (最终部署目录)
#     └─ msia_server.exe              (主程序)
```

### 10.3 部署步骤

1. 将整个 `backend/dist/msia_server/` 文件夹复制到目标服务器
2. 确认目标服务器已安装 ODBC Driver 17/18 for SQL Server
3. 修改 `msia_server/_internal/config.ini`（或与 exe 同目录）
   - 数据库连接 (db_server/user/password/sql_driver_version)
   - 监听端口 (server.port)
   - CORS 与 SYSTEM_URL (部署后用户实际访问地址)
   - 邮件服务器配置
   - JWT_SECRET_KEY (修改为随机长字符串)
4. 双击 `msia_server.exe` 启动服务（或注册为 Windows 服务）
5. 浏览器访问 `http://<服务器IP>:<端口>/`

---

## 附录：代码链接索引

| 模块 | 文件路径 |
|-----|---------|
| 后端入口 | [main.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/main.py) |
| 配置中心 | [config.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/core/config.py) |
| 生产配置 | [config.ini](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/config.ini) |
| 路由聚合 | [router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/api/router.py) |
| 调度器 | [scheduler.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/scheduler/scheduler.py) |
| 逾期判定 | [issue_overdue.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/services/issue_overdue.py) |
| 模型汇总 | [models/__init__.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/models/__init__.py) |
| 数据库会话 | [session.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/backend/app/db/session.py) |
| 前端路由 | [router/index.tsx](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/src/router/index.tsx) |
| Vite 配置 | [vite.config.ts](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/vite.config.ts) |
| 前端依赖 | [package.json](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/MSIA%20Report/frontend/package.json) |

---

*文档结束*
