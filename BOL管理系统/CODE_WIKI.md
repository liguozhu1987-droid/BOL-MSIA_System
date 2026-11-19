# BOL 管理分析平台 - Code Wiki

> 版本:v1.0  · 生成日期:2026-08-18
> 仓库根目录:`c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统`

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 项目结构总览](#2-项目结构总览)
- [3. 技术栈](#3-技术栈)
- [4. 系统整体架构](#4-系统整体架构)
- [5. 后端模块详解](#5-后端模块详解)
- [6. 前端模块详解](#6-前端模块详解)
- [7. 关键类与函数说明](#7-关键类与函数说明)
- [8. 数据库设计与路由策略](#8-数据库设计与路由策略)
- [9. 依赖关系](#9-依赖关系)
- [10. 项目运行方式](#10-项目运行方式)
- [11. 部署与配置](#11-部署与配置)
- [12. 关键业务约束与设计约定](#12-关键业务约束与设计约定)

---

## 1. 项目概述

**BOL 管理分析平台**(Bill of Labor,工时清单管理分析平台)是企业 IE(工业工程)领域的数字化管理系统,围绕汽车外饰(天窗系统)生产线的 **BOL(工时清单)** 全生命周期数据展开,涵盖:

- **BOL 审批记录**(动态 BOL):来源于既有 HRDB 系统,记录每次 BOL 变更审批履历
- **年度预算 BOL**(三种类型:Budget / Achievable / Target):通过标准化 Excel 模板导入
- **实测 CT**(Cycle Time,来自传感器采集系统):工位级 / 瓶颈 / 日级粒度
- **高 BOL 跟踪**:超标项目的改善闭环管理(OPEN → IN_PROGRESS → ACHIEVED → VERIFIED → CLOSED)
- **跨库分析中心**:综合 Budget / 实测 / 动态 / 跟踪多维度对比与改善机会挖掘
- **人员与认证管理**:员工账号、自定义 Token 认证、RBAC 权限

系统采用 **Django + DRF 后端 + Vue 3 + Element Plus 前端** 的双库架构,通过 `BolDbRouter` 实现 **CMC 读写库** 与 **HRDB 只读库** 的隔离;支持开发态分离部署(Vite 5173 + Django 8000)与生产态合并部署(waitress + Django 直接托管前端 SPA)两种模式,生产环境可通过 PyInstaller 打包为单 exe。

---

## 2. 项目结构总览

```
BOL管理系统/
├── backend/                       # Django 后端
│   ├── apps/                      # 业务应用(7 个)
│   │   ├── projects/              # 项目主数据(HRDB 只读)
│   │   ├── dynamic_bol/           # BOL 审批记录(HRDB 只读)
│   │   ├── actual_ct/             # 实测 CT(HRDB 只读 + OPE 远程视图)
│   │   ├── budget_bol/            # 年度预算 BOL(CMC 读写)
│   │   ├── tracking/              # 高 BOL 闭环跟踪(CMC 读写)
│   │   ├── analytics/             # 跨库分析中心 + 定时报告
│   │   └── users/                 # 员工与认证(CMC 读写)
│   ├── bol_platform/              # 项目级配置
│   │   ├── settings.py            # 基础配置(开发/通用)
│   │   ├── settings_prod.py       # 生产配置(继承 + SPA + PyInstaller)
│   │   ├── urls.py                # 主路由 + SPA 回退
│   │   ├── wsgi.py / asgi.py      # WSGI/ASGI 入口
│   │   ├── db_router.py           # 双库路由器
│   │   ├── bol_calc.py            # BOL 计算工具与常量
│   │   ├── plant_utils.py         # 工厂名标准化工具
│   │   ├── pagination.py          # 自定义分页
│   │   └── exceptions.py          # 统一异常处理
│   ├── staticfiles/               # collectstatic 输出(含前端构建产物)
│   ├── build/bol_server/          # PyInstaller 打包中间产物
│   ├── db_config.ini(.example)    # 数据库/邮件外部配置(可覆盖默认值)
│   ├── manage.py                  # Django 管理入口
│   ├── run_server.py              # 生产启动脚本(waitress)
│   ├── bol_server.spec            # PyInstaller 打包规格
│   ├── requirements.txt           # Python 依赖
│   └── BOLServer_v2.2.zip / BOLServer-Deploy-Package.zip  # 部署包
│
├── frontend/                      # Vue 3 前端
│   ├── public/                    # 静态资源(favicon / logo / skyline)
│   ├── src/
│   │   ├── api/index.js           # axios 实例 + 全部 API 模块
│   │   ├── composables/           # 认证状态与组合函数
│   │   ├── components/            # 通用组件(ChartCard / PageHeader)
│   │   ├── router/index.js        # Vue Router(history 模式 + 路由守卫)
│   │   ├── styles/main.css        # 全局样式 + 设计令牌(CSS 变量)
│   │   ├── utils/                  # echarts 主题 + 格式化工具
│   │   ├── views/                 # 页面级组件
│   │   ├── App.vue                # 根组件(仅路由出口)
│   │   └── main.js                # 应用入口
│   ├── index.html
│   ├── vite.config.js             # Vite 配置(host 0.0.0.0 + /api 代理)
│   └── package.json
│
├── *.xlsx                         # 业务 Excel 样本(预算 BOL 模板示例)
├── BOL管理系统.pptx                # 系统使用说明
├── BOL_Analysis_Report_Standalone.html  # 分析报告样板
└── CODE_WIKI.md                   # 本文档
```

---

## 3. 技术栈

### 后端
| 类别 | 选型 | 说明 |
|---|---|---|
| Web 框架 | Django 4.2.30 | LTS 版本,适配 mssql-django |
| REST API | djangorestframework 3.17.1 | 自定义认证/权限/分页/异常处理 |
| 数据库 | Microsoft SQL Server | 双库:CMC(读写)+ HRDB(只读) |
| SQL Server 驱动 | mssql-django 1.7.3 + pyodbc 5.3.0 | 默认 ODBC Driver 18 |
| 跨域 | django-cors-headers 4.9.0 | 内网全开 |
| 过滤 | django-filter 25.1 | DRF 集成 |
| WSGI 服务器 | waitress 3.0.2 | Windows 兼容的生产 WSGI |
| Excel | openpyxl 3.1.5 | 模板生成与导入解析 |
| 图像处理 | Pillow 12.2.0 | Django 依赖项 |
| 定时任务 | APScheduler | 改善周报调度(可选,缺失时降级) |

### 前端
| 类别 | 选型 | 说明 |
|---|---|---|
| 框架 | Vue 3.5.40 | Composition API |
| UI 库 | Element Plus 2.14.3 + @element-plus/icons-vue | 全图标全局注册 |
| 路由 | vue-router 4.6.4 | createWebHistory(history 模式) |
| HTTP | axios 1.18.1 | 统一拦截器返回 `response.data` |
| 图表 | echarts 6.1.0 | 自定义浅蓝科技主题 |
| 构建 | Vite 8.1.1 + @vitejs/plugin-vue 6.0.8 | 开发代理 + 生产构建 |

---

## 4. 系统整体架构

### 4.1 部署拓扑

```
┌─────────────────────────────────────────────────────────────────┐
│                       浏览器(用户)                              │
│        http://<host>:5173 (开发) / :8090 (生产)                │
└─────────────────────────────────────────────────────────────────┘
                              │
              开发态:Vite 5173 ───proxy /api───┐
              生产态:waitress 8090(同源)        │
                              ▼                  │
┌─────────────────────────────────────────────────────────────────┐
│                    Django + DRF 后端                            │
│  /api/*        → REST API(EmployeeTokenAuthentication)         │
│  /admin/       → Django Admin                                   │
│  /static/ /assets/ → 静态资源(生产)                            │
│  其他非 API 路径 → serve_spa(返回 frontend/dist/index.html)    │
└─────────────────────────────────────────────────────────────────┘
                │ BolDbRouter 路由
                ▼                              ▼
   ┌──────────────────────┐        ┌─────────────────────────┐
   │ default 库 = CMC      │        │ hrdb 库 = HRDB(只读)    │
   │ - CN_IE_BOL_*        │        │ - CN_IE_BOLOverView     │
   │   Employee/AuthToken │        │ - CN_IE_BOLOverView_byP │
   │   BudgetBol/AchTgtBol │        │ - CN_IE_BOL_*History    │
   │   HighBolTracking    │        │ - CN_IE_CT_realCT_*     │
   │   ImprovementLog    │        │ - CN_IE_BOL_program*     │
   │   cbco_records(只读) │        │ - fine_user             │
   └──────────────────────┘        └─────────────────────────┘
                                            ▲
                                            │ pyodbc raw SQL
                                            │ (actual_ct 部分 API)
                          ┌─────────────────────────────────┐
                          │ OPE 远程数据仓库                 │
                          │ 172.26.2.212 InalfaCNDM          │
                          │ OPE.V_fact_cn_realTimeCT_overView│
                          └─────────────────────────────────┘
                                            ▲
                                            │ SMTP
                                            │ (周报邮件)
                          ┌─────────────────────────────────┐
                          │ 公司内部邮件服务器                │
                          │ 172.19.253.10:25 (SSL 无密码)    │
                          └─────────────────────────────────┘
```

### 4.2 请求处理流水线

1. **前端发起**:组件调用 `api/index.js` 的封装方法 → axios 实例 baseURL `/api` → 请求拦截器附加 `Authorization: Token <key>`
2. **Vite 代理(开发)**:`/api` → `http://127.0.0.1:8000`
3. **Django 中间件链**:`CorsMiddleware` → `SecurityMiddleware` → `SessionMiddleware` → `CommonMiddleware` → `CsrfViewMiddleware` → `AuthenticationMiddleware` → `MessageMiddleware` → `XFrameOptionsMiddleware`
4. **DRF 认证**:`EmployeeTokenAuthentication` 解析 `Token` 头 → 校验 `AuthToken` 未过期 + `Employee.status=ACTIVE`
5. **DRF 权限**:`IsAuthenticatedEmployee`(全局默认)/ `IsAdmin`(敏感操作如 `clear-all`)/ `CanManageEmployees`(员工 CRUD)
6. **路由分发**:`/api/<app>/` → 各应用 `urls.py` → ViewSet / APIView
7. **跨库数据访问**:`BolDbRouter.db_for_read` 按 `app_label` 路由到 `default` 或 `hrdb`;跨库合并在 Python 层(不允许跨库 JOIN)
8. **统一响应**:DRF 默认分页 `CustomPageNumberPagination`(page_size=50);异常经 `custom_exception_handler`
9. **响应拦截器(前端)**:成功返回 `response.data`(组件中直接用 `res`);401/403+无 token → 清状态并整页跳转 `/login?redirect=...`

### 4.3 双库路由核心规则

参见 [db_router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/db_router.py):

| app_label | 读库 | 写库 | 是否迁移建表 |
|---|---|---|---|
| `projects` / `dynamic_bol` / `actual_ct` | `hrdb` | `None`(禁止写) | `False`(表已存在) |
| `users` / `budget_bol` / `tracking` / `analytics` 等 | `default`(CMC) | `default` | `True`(Django 管理) |

**例外**:`apps/budget_bol/cbco_models.py` 中 `CbcoRecord` 虽为 `managed=False`(只读),但 `app_label='budget_bol'` 不在 `hrdb_apps`,故读取自 **CMC 库的 `cbco_records` 表**(项目主数据:客户 / SOP / EOP / Roof Type / Topline 状态 / 年产量)。

---

## 5. 后端模块详解

后端在 [backend/apps/](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps) 下划分为 7 个 Django App,职责严格遵循单一数据来源原则。

### 5.1 apps/users — 人员与认证(CMC 读写)

**职责**:员工账号 CRUD、自定义 Token 认证、完整认证流程(注册/登录/登出/游客/忘记密码/重置密码/修改密码/获取当前用户)。

> 不使用 Django 内置 `auth` 系统,而是基于 `Employee` 模型自实现密码哈希与令牌。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/models.py))
| 模型 | 表名 | 作用 |
|---|---|---|
| `Employee` | `CN_IE_BOL_Employee` | 员工主表,字段:username(唯一)、password(哈希)、role(ADMIN/IE/MGR/ENGINEER/VIEWER/GUEST)、status(ACTIVE/INACTIVE);实现 `is_authenticated`/`set_password`/`check_password` |
| `AuthToken` | `CN_IE_BOL_AuthToken` | 登录令牌,`create_for_employee` 支持**多端共存策略**(复用未过期令牌,清理过期令牌) |
| `PasswordResetToken` | `CN_IE_BOL_PasswordResetToken` | 密码重置令牌(1 小时有效,使用后标记 `used=True`) |

#### 视图([auth_views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/auth_views.py) / [views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/views.py))
| 视图类 | URL | 方法 | 权限 | 说明 |
|---|---|---|---|---|
| `RegisterView` | `/api/auth/register/` | POST | AllowAny | 注册为 VIEWER,168h 令牌 |
| `LoginView` | `/api/auth/login/` | POST | AllowAny | 支持 `remember=true` → 720h,否则 168h |
| `GuestLoginView` | `/api/auth/guest-login/` | POST | AllowAny | 复用/新建 `guest` 虚拟账号,24h 短令牌 |
| `LogoutView` | `/api/auth/logout/` | POST | 需认证 | 删除当前令牌 |
| `MeView` | `/api/auth/me/` | GET/PATCH | 需认证 | PATCH 仅允许改 name/email/phone/department/title |
| `ChangePasswordView` | `/api/auth/change-password/` | POST | 需认证 | 改密后删除该用户其他令牌(保留当前) |
| `ForgotPasswordView` | `/api/auth/forgot-password/` | POST | AllowAny | username+email 双重匹配,生成 1h 重置令牌;DEBUG 返回 reset_url |
| `ResetPasswordView` | `/api/auth/reset-password/` | POST | AllowAny | 改密后标记 used + 删除该用户全部 AuthToken |
| `EmployeeViewSet` | `/api/users/employees/` | CRUD | `IsAuthenticatedEmployee` + `CanManageEmployees`(仅 ADMIN) | 含 `active`/`activate`/`deactivate` action |

#### 认证与权限([authentication.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/authentication.py) / [permissions.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/permissions.py))
- `EmployeeTokenAuthentication`:`keyword='Token'`,解析 `Authorization: Token <key>` → `AuthToken` 校验过期/状态
- 权限类:`IsAuthenticatedEmployee`、`HasRole`(基类)、`IsAdmin`、`IsAdminOrIE`、`CanManageEmployees`

#### 管理命令
- `python manage.py create_admin`:初始化管理员账号

---

### 5.2 apps/budget_bol — 年度预算 BOL(CMC 读写)

**职责**:通过标准化 Excel 模板导入三种 BOL 类型,支持模板下载、一键清空(管理员)、列表查询(自动补全 cbco_records 项目基本信息)。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/budget_bol/models.py))
| 模型 | 表名 | 列数 | 适用 BOL 类型 |
|---|---|---|---|
| `BudgetBol` | `CN_IE_BOL_BudgetBol` | 7 列 | BUDGET(直接给定 AME Target/Achievable/Budget BOL) |
| `AchievableTargetBol` | `CN_IE_BOL_AchievableTargetBol` | 23 列 | ACHIEVABLE / TARGET(通过 `bol_type` 字段区分) |
| `CbcoRecord` | `cbco_records` | — | 只读(`managed=False`),CMC 库项目主数据,供列表补全客户/SOP/EOP/Roof Type/Volume |

> Achievable 与 Target 的 23 列中前 19 列完全一致(基本信息 + 5 组子工艺 CT/HC/Comment),**最后 4 列顺序不同**:
> - Achievable:`OEE(20) / BOL Base(21) / Uplift(22) / BOL(23)`
> - Target:`BOL Base(20) / Uplift(21) / OEE(22) / BOL(23)`

#### Excel 导入器([excel_importer.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/budget_bol/excel_importer.py))
- `BudgetBolImporter(fiscal_year, bol_type, created_by)`:主入口类
- `import_from_file(file_path)`:返回 `{total_rows, imported, skipped, deleted, errors, ...}`
- **核心流程**:`load_workbook(data_only=True)` → `_pick_sheet()`(精确+模糊匹配 sheet 名)→ **`transaction.atomic()` 内先 `_clear_old_records()`(按财年+类型清空)再逐行导入** → 任一行异常 raise 触发回滚
- 三种分派:`_import_budget_row`(7 列)/ `_import_achievable_row`(23 列,OEE 在第 20 列)/ `_import_target_row`(23 列,OEE 在第 22 列)
- Plant 原值直接存储(不做映射),字符串字段做长度截断

#### 模板生成([excel_template.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/budget_bol/excel_template.py))
- 4 种模板:`budget`(7 列,蓝底)/ `achievable`(23 列,青底)/ `target`(23 列,紫底)/ `original`(25 列旧版兼容)
- `generate_template_bytes(template_type)`:返回 .xlsx 字节流用于下载

#### 视图集([views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/budget_bol/views.py))
`BudgetBolViewSet`(注意是 `ViewSet` 而非 `ModelViewSet`,无内置 CRUD):

| action | URL | 方法 | 说明 |
|---|---|---|---|
| `list` | `/api/budget-bol/budget-bol/` | GET | 合并查询 BudgetBol + AchievableTargetBol;plant 筛选展开为所有变体;批量查 CbcoRecord 补全;按 `_should_display`(STATUS 在 MUST/WON + EOP 年份过滤)业务过滤 |
| `filter_options` | `.../filter-options/` | GET | 返回 `{fiscal_years, bol_types, plants, process_types}` |
| `import_template` | `.../import-template/?type=` | GET | 按 type 返回 .xlsx 模板下载 |
| `import_excel` | `.../import-excel/` | POST | MultiPart 上传,必传 file + fiscal_year,bol_type 默认 ACHIEVABLE;调 `BudgetBolImporter` |
| `clear_all` | `.../clear-all/` | POST | **`permission_classes=[IsAdmin]`**,需 `confirm='CONFIRM_CLEAR'`,可选 fiscal_year/bol_type |

---

### 5.3 apps/tracking — 高 BOL 闭环跟踪(CMC 读写)

**职责**:BOL 超标项目的完整改善闭环管理,基于状态机驱动。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/tracking/models.py))
- `HighBolTracking`(`CN_IE_BOL_HighBolTracking`):主表,含基本信息 / 问题与目标 / 优先级与原因分析 / 改善方案 / 责任人 / 状态流转 / 流转时间节点 / 审计字段
  - `save()` 自动计算:`bol_gap = current_bol - target_bol`、`cost_gap = calc_labor_cost_gap(bol_gap, annual_volume, labor_rate)`；BOL差异为分钟/件、年产量为件/年、工时单价为元/小时，成本差异按 `bol_gap × annual_volume × labor_rate / 60` 计算，正值为年化成本损失、负值为年化节省
  - 状态:`OPEN → IN_PROGRESS → ACHIEVED → VERIFIED → CLOSED`(可 `REOPENED`)
- `ImprovementLog`(`CN_IE_BOL_ImprovementLog`):改善进展日志,ForeignKey 到 HighBolTracking(`related_name='logs'`),`log_type` 区分节点(CREATE/ASSIGN/START/PROGRESS/ACHIEVE/VERIFY/CLOSE/REOPEN)

#### 视图([views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/tracking/views.py))
`HighBolTrackingViewSet(ModelViewSet)` 状态流转规则:

```
STATE_TRANSITIONS = {
    'OPEN': ['IN_PROGRESS'],  'REOPENED': ['IN_PROGRESS'],
    'IN_PROGRESS': ['ACHIEVED'],
    'ACHIEVED': ['VERIFIED', 'IN_PROGRESS'],
    'VERIFIED': ['CLOSED', 'IN_PROGRESS'],
    'CLOSED': ['REOPENED'],
}
```

自定义 action(均 `@action(detail=True, methods=['post'])`):`assign` / `start` / `achieve` / `verify` / `close` / `reopen` / `add-log`(进度日志,不变状态)/ `timeline`(GET,闭环时间线)/ `search-programs`(detail=False,从 cbco_records 检索项目编号,默认取当前年份的下一年)

---

### 5.4 apps/analytics — 跨库分析中心 + 定时报告

**职责**:跨 `hrdb` + `default` 两库合并数据,提供 6 大分析 API 与每周二 12:00 自动邮件推送改善机会报告。

#### 视图([views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/analytics/views.py) ~1550 行)
| 视图类 | URL | 跨库来源 | 说明 |
|---|---|---|---|
| `BolComparisonView` | `/api/analytics/comparison/` | BolOverView(hrdb)+BudgetBol(default)+BottleNeckCt(hrdb) | 单项目 BOL 全链路对比,用 `calc_bol` 反推佐证 |
| `DashboardView` | `/api/analytics/dashboard/` | 多源跨库 | 综合 7 大模块汇总 KPI / BOL 全链路 / SCT vs ACT / 改善机会预警 |
| `BudgetBolComparisonView` | `/api/analytics/budget-bol-comparison/` | BudgetBol/AchievableTargetBol + CbcoRecord(default) | 财年对比,计算节省工时 `volume × bol_reduction / 60` |
| `BolLifecycleAllView` | `/api/analytics/bol-lifecycle-all/` | 跨 4 表 | 全量 BOL 生命周期数据(图表点击弹窗用) |
| `MultiDimBolAnalysisView` | `/api/analytics/multi-dim-analysis/` | BudgetBol/AchTgtBol + CbcoRecord | 工艺 × RoofType × 工厂 × 财年多维度统计 |
| `MultiDimBolTrendView` | `/api/analytics/multi-dim-trend/` | 同上多 BOL 类型 | 时间维度趋势 |

> **跨库查询统一原则**(写在文件顶部注释,全项目强制):Django 不支持跨库 JOIN → 所有合并均在 Python 层通过归一化键(`_line_key` / `_pp_key` / `normalize_plant`)用 dict 完成;**禁止 fallback 兜底**,要求精确匹配 `(project_code, line_nr, process_type, location)`。

#### 定时报告
- [scheduler.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/analytics/scheduler.py):APScheduler `CronTrigger(day_of_week='tue', hour=12, minute=0)`,仅 `settings.SCHEDULER_ENABLED=True` 时启动;APScheduler 缺失时降级 logger.warning
- [report_generator.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/analytics/report_generator.py):生成 HTML 报告,**内联 CSS(Outlook 兼容)**,浅蓝科技风,包含 Top10 低 LB 项目、审批动态、异常 CT、改善建议
- [send_improvement_report.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/analytics/management/commands/send_improvement_report.py):`python manage.py send_improvement_report [--email x@y] [--dry-run]`

---

### 5.5 apps/dynamic_bol — BOL 审批记录(HRDB 只读)

**职责**:访问既有 HRDB 系统的 BOL 审批更新记录,提供总览、按工艺明细、变更审批履历(级联筛选 + 时间序列)、低线平衡率分析。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/dynamic_bol/models.py) 全部 `managed=False`)
| 模型 | 表名 | 作用 |
|---|---|---|
| `BolOverView` | `CN_IE_BOLOverView` | BOL 主表(92 字段),含 BOL_Overall/CT/HC/LB/QWS_BOL/审批状态等 |
| `BolOverViewByProcess` | `CN_IE_BOLOverView_byProcess` | 按工艺分段(BOL_Nr 主键,无 id 列) |
| `BolApprovalHistory` | `CN_IE_BOL_approval_historyList` | 审批历史 |
| `BolUpdateHistory` | `CN_IE_BOL_UpdateHistoryList` | 更新历史 |
| `FineUser` | `fine_user` | 用户名→真实姓名映射 |

#### 关键业务规则([views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/dynamic_bol/views.py))
- **项目编号同一项目识别**(模块级函数):正则 `^[A-Z](\d{4})([a-zA-Z]?)$`
  - `_extract_project_code(code)`:提取后 4 位数字 + 后缀字母(若有)
  - 前缀字母(O/S/T)不同视为同一项目不同阶段 → 合并;后缀字母(a/E)不同视为不同项目 → 不合并
  - 例:`O6848 + T6848` 合并、`S6763 + T6763` 合并;但 `T6846 ≠ T6846a`、`T6968 ≠ T6968E`
  - `_pick_canonical_code`:同一项目优先选 T 开头作为代表编码
- `ApprovalTrendFilterOptionsView`:`GET /api/dynamic-bol/approval-trend-filter-options/`,级联筛选器,仅统计 `final_approve_status='Approved'`,默认 BJ+FA+BJFA1+T6763 防止空数据
- `ApprovalTrendView`:`GET /api/dynamic-bol/approval-trend/`,识别同项目所有编码 → 查审批通过记录 → `BolOverViewByProcess` 按 `bol_nr` 聚合(CT/HC 取 sum,LB 取 avg)
- `LowLbAnalysisView`:`GET /api/dynamic-bol/low-lb-analysis/`,改善机会计算(详见 §12 圆整规则)

---

### 5.6 apps/actual_ct — 实测 CT(HRDB 只读 + OPE 远程视图)

**职责**:工位级 / 瓶颈 / 日级实测 Cycle Time 多维度分析,基于 Shewhart 控制图与 Tukey IQR 异常剔除。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/actual_ct/models.py) 全部 `managed=False`)
| 模型 | 表名 | 用途 |
|---|---|---|
| `RealCtExtract` | `CN_IE_CT_realCT_extract` | 工位级 CT(77000+ 条) |
| `RealCtExtractPerDay` | `CN_IE_CT_realCT_extract_perDay` | 按天 CT |
| `BottleNeckCt` | `CN_IE_CT_bottleNeck_list` | 瓶颈工位 CT |
| `CtRealtimeStatus` | `CN_IE_CT_Realtime_status` | 产线实时状态 |
| `ProjectAcquisition` | `CN_IE_realTime_projects_acquisition` | 项目采集配置(级联筛选用,替代 OPE 远程视图) |

#### 分析核心([analysis.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/actual_ct/analysis.py) 1032 行)
- **数据清洗**:`normalize_ct_value` / `normalize_date`
- **异常剔除**:`filter_outliers_iqr`(Tukey IQR 1.5×IQR)/ `filter_outliers_percentile`(P1-P99)/ `compute_represent_ct`(P1-P99 + IQR 双重剔除后中位数)
- **直方图**:`build_histogram(values, bin_count/bin_size)`
- **控制图**:`build_xbar_r_chart(daily_series)` 休哈特 Xbar-R 控制图(使用 `_SHEWHART_COEFFICIENTS` 表 A2/D3/D4 系数,n=2..12),判异规则:单点越界 / 连续 7 点同侧 / 连续 7 点趋势
- **工位级分析主入口**:`build_station_ct_analysis(records, months, bin_size)` → 直方图 + 均值/极差 + 异常点 + `_build_diagnosis` 自动生成诊断结论与改善建议

#### OPE 远程数据仓库访问(关键跨库)
`actual_ct` 应用同时存在两种数据源:
1. **HRDB 本地表**(`CN_IE_CT_realCT_extract` 等)通过 Django ORM 自动路由只读访问
2. **OPE 远程数据仓库**(`OPE.V_fact_cn_realTimeCT_overView` @ `172.26.2.212 InalfaCNDM`)通过 `pyodbc` 直连 raw SQL 访问
   - `get_ope_connection()` / `execute_ope_query(sql, params)` / `fetch_ct_analysis_from_db()`
   - OPE 连接失败时回退到 `connections['hrdb']` 执行同一段 SQL

#### 视图([views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/actual_ct/views.py))
| 视图 | URL | 数据源 | 说明 |
|---|---|---|---|
| `CascadeFilterView` | `/api/actual-ct/cascade-filters/` | HRDB(ProjectAcquisition + RealCtExtract) | 5 层级联:companies → lines → project_codes → project_names → station_nrs |
| `SctVsActView` | `/api/actual-ct/sct-vs-act/` | BottleNeckCt + BolOverView(均在 hrdb) | SCT vs ACT 跨表合并(按 project_code + line_nr + process) |
| `LineBalanceView` | `/api/actual-ct/line-balance/` | RealCtExtract | 调 `compute_represent_ct` 计算线平衡率 |
| `BoxPlotView` | `/api/actual-ct/box-plot/` | RealCtExtract | 各工位 min/Q1/median/Q3/max/avg |
| `StationCtDetailView` | `/api/actual-ct/station-detail/` | **OPE raw SQL** | 调 `build_station_ct_analysis` 生成直方图 + Xbar-R 控制图 |
| `ActualCtSearchView` | `/api/actual-ct/search/` | **OPE raw SQL** | `OFFSET ... FETCH NEXT` 分页,直方图剔除异常 |
| 5 个 ReadOnlyModelViewSet | `/api/actual-ct/{real-ct,real-ct-per-day,bottleneck-ct,realtime-status,analysis}/` | ORM | 支持 `?months=N` 限制近 N 月 |

---

### 5.7 apps/projects — 项目主数据(HRDB 只读)

**职责**:HRDB 既有项目主数据映射。

#### 模型([models.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/projects/models.py) 全部 `managed=False`)
| 模型 | 表名 | 主键 |
|---|---|---|
| `ProgramInfo` | `CN_IE_BOL_programCodeInfor` | program_code |
| `BolUser` | `CN_IE_BOL_Userdatabase` | user_name |
| `StationInfo` | `CN_IE_BOL_StationInfor` | — |

#### 视图
3 个 `ReadOnlyModelViewSet`:注册路由 `programs` / `users` / `stations`,支持 `DjangoFilterBackend` + `SearchFilter` + `OrderingFilter`。

---

### 5.8 bol_platform — 项目级配置与工具

| 文件 | 作用 |
|---|---|
| [settings.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings.py) | 基础配置:双库 DATABASES + db_config.ini 加载器 + REST_FRAMEWORK 全局认证/权限/分页 + 邮件配置 + 传感器 API + BOL 计算常量 |
| [settings_prod.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings_prod.py) | 生产配置(继承基础):`DEBUG=False` + SPA 路由回退(`FRONTEND_INDEX`)+ PyInstaller 路径自适应 |
| [urls.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/urls.py) | 主路由:8 个 `path('api/...')` + 生产环境 `/assets/` `/static/` 静态服务 + `serve_spa()` SPA 回退 |
| [db_router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/db_router.py) | `BolDbRouter`:按 `app_label` 路由读写与迁移 |
| [bol_calc.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/bol_calc.py) | `calc_bol` / `calc_bol_gap` / `calc_labor_cost_gap` + BOL 类型常量 |
| [plant_utils.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/plant_utils.py) | `normalize_plant` / `normalize_project_code` / `get_plant_raw_values` / `build_plant_q` |
| [pagination.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/pagination.py) | `CustomPageNumberPagination`(默认 page_size=50) |
| [exceptions.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/exceptions.py) | `custom_exception_handler` 统一异常响应 |
| [wsgi.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/wsgi.py) / [asgi.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/asgi.py) | WSGI/ASGI 入口 |

---

## 6. 前端模块详解

前端位于 [frontend/src/](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src),Vue 3 + Element Plus 单页应用。

### 6.1 入口与布局
- [App.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/App.vue):根组件,仅 `<router-view>` + 淡入淡出过渡;无导航栏,各页通过 `PageHeader` 渲染头部;`isHome` 判断主页不渲染 PageHeader
- [main.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/main.js):创建应用、注册 Element Plus + 全部图标为全局组件、引入 router 与全局样式、挂载 `#app`
- [vite.config.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/vite.config.js):`host: '0.0.0.0'`(硬约束)、port 5173、`/api` 代理到 `http://127.0.0.1:8000`、`@` 别名指向 `./src`

### 6.2 状态管理与组合函数
- [composables/authState.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/composables/authState.js):`reactive` 全局认证状态,持久化到 localStorage(`bol_auth` token/expiresAt/user + `bol_remembered_user`);导出 `authState` / `isAuthExpired` / `setAuthPayload` / `clearAuthState` / `rememberUsername`
- [composables/useAuth.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/composables/useAuth.js):暴露 `isAuthenticated` / `isAdmin` / `isGuest` / `roleLabel` / `userInitials` 计算属性 + `login` / `guestLogin` / `register` / `logout` / `fetchMe` / `changePassword` / `updateProfile` / `hasRole` 方法;**`fetchMe` 仅在 401 时清状态**,避免网络抖动误清"保持登录"

### 6.3 API 客户端([api/index.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/api/index.js))
axios 实例 `baseURL='/api'` + 请求拦截器附加 `Authorization: Token <token>` + 响应拦截器返回 `response.data`(组件中直接用 `res` 而非 `res.data`);401/403+无 token 时清状态并整页跳转 `/login?redirect=...`

导出 8 个 API 模块:`authApi` / `programApi` / `dynamicBolApi` / `budgetBolApi` / `actualCtApi` / `trackingApi` / `improvementLogApi` / `userApi` / `analyticsApi`,与后端 7 个 App 一一对应。

### 6.4 路由([router/index.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/router/index.js))
`createWebHistory()` history 模式;三层路由守卫:`requiresAuth` / `guestAllowed`(游客)/ `roles`(角色);`meVerifiedInSession` 标志避免每次跳转都请求后端;`afterEach` 设置浏览器标题。

| 路由 | 模块 | 权限 |
|---|---|---|
| `/login` `/register` `/forgot-password` `/reset-password` | 认证 | guest(已登录访问会重定向 `/`) |
| `/` `/dashboard` `/dynamic-bol` `/actual-ct` `/analytics/comparison` | 数据管理/分析中心 | requiresAuth + guestAllowed |
| `/budget-bol` `/tracking` `/account` | 数据管理/系统管理 | requiresAuth(游客禁入) |
| `/users` | 系统管理 | requiresAuth + roles=['ADMIN'] |

### 6.5 设计令牌与样式([styles/main.css](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/styles/main.css))
**Light Tech Minimalism**(浅蓝简约科技)主题:
- 主色:`--color-primary: #0ea5e9`(天蓝)、`--color-primary-dim: #0284c7`、`--color-primary-light: #38bdf8`
- 语义色:success #10b981 / warning #f59e0b / danger #ef4444 / info #0ea5e9
- BOL 值编码:`--color-bol-high` #dc2626 / `--color-bol-mid` #d97706 / `--color-bol-low` #059669
- 字体:`--font-display: Sora` / `--font-body: DM Sans` / `--font-mono: JetBrains Mono`
- Element Plus 组件覆写(`el-card` / `el-table` 表头浅蓝渐变 / `el-button` 渐变 + 悬停上抬等)
- 全局背景:`--gradient-mesh` + 浅蓝蒙版 + `/skyline.jpg`(88% 不透明蒙版)
- **硬约束**:源码中无硬编码颜色,全部使用 CSS 变量

### 6.6 工具函数
- [utils/echartsTheme.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/echartsTheme.js):`PALETTE`(10 色,以浅蓝为主)+ `BOL_COLORS` + `AXIS` + `baseOption` 通用配置 + 渐变函数 `mintGradient`/`amberGradient`/`dangerGradient` + `aggregate`/`topN`/`histogram` 聚合工具
- [utils/format.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/format.js):`formatBol`/`formatCurrency`/`formatPercent`/`formatDate`/`formatDateTime`/`bolColorClass`/`normalizePlant`(与后端 `plant_utils.normalize_plant` 同构,统一短码 CJ/BJ/SH/CQ/GZ/WH/CMC/YT)

### 6.7 图表视觉规范（全站 ECharts 统一标准）

> 这是本项目对图表可读性和一致性的“视觉定稿”，所有新增图表必须按此标准执行，避免再次出现“有些图表有标签、有些没有标签”的问题。

#### 6.7.1 设计目标

1. 保持图表“可读性”优先，不让读者必须 hover 才能知道数值。
2. 保持图表“整洁度”优先，不让标签在密集数据下挤爆图面。
3. 保持“全站一致性”优先，所有 图表都遵循同一套颜色、字号、间距和显示规则。
4. 允许例外，但例外必须是“业务语义需要”，不能靠散写 magic number 成为默认规则。

#### 6.7.2 统一规则源头

全站图表禁止在各页面手写重复的 `label.show = true/false`、`fontSize`、`color`、`distance` 等魔法数，统一从下面 three sources 读取：

- [frontend/src/utils/echartsTheme.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/echartsTheme.js): 中的 `CHART_SPEC`、`AXIS`、`CHART_LABEL_POLICY`
- `buildValueLabelConfig(chartType, itemCount, extra)`：生成标准 label 配置
- `shouldShowInlineValueLabel(itemCount, denseThreshold, moderateThreshold)`：决定是否展示 inline label

#### 6.7.3 图表类型分档规则

图表的 label 策略必须按图表类型分开配置，而不是统一用一套 `bar` 阈值覆盖所有图。

- `bar`：标准柱状图，少量类别可直接展示标签；密集时自动收敛。
  - `denseThreshold = 8`
  - `moderateThreshold = 11`
  - 适用：年度趋势、KPI 对比、更新率/降低率等普通柱图

- `barCompact`：紧凑柱状图，通常更窄、更拥挤。
  - `denseThreshold = 6`
  - `moderateThreshold = 9`
  - 适用：多工位、长类别名、条形图、压缩空间场景

- `line`：折线图，类别较多时不宜全量标签，适合少量关键点标记。
  - `denseThreshold = 10`
  - `moderateThreshold = 14`
  - 适用：时间序列、趋势线、审批履历趋势

- `scatter`：散点图，通常不宜全量展示，适合少量高价值点。
  - `denseThreshold = 12`
  - `moderateThreshold = 16`
  - 适用：分布图、均值点图、数据点场景

- `heatmap`：热力图，通常只标记值在可读范围内的格子。
  - `denseThreshold = 20`
  - `moderateThreshold = 28`
  - 适用：矩阵型热力、工艺 × RoofType 分布图

- `boxplot`：箱线图，不适合全量 inline label；仅在密度低/重要点上保留。
  - `denseThreshold = 8`
  - `moderateThreshold = 11`
  - 适用：平均值/箱线图、工厂分布图

- `custom`：自定义渲染图表，需单独判断，默认不强制 inline label。
  - 适用：哑铃图、复杂 custom series、连线/区间图

#### 6.7.4 统一可读规范

1. 字体标准
   - 坐标轴和图例：11px
   - 数值标签：10px（普通柱图） / 9px（紧凑图）
   - 文字颜色：`AXIS.text`（深蓝灰）/ `AXIS.textDim`（中灰蓝）
   - 字重：600 正常展示，除特殊强调值可单独 override

2. 颜色标准
   - 全站图表统一走 `PALETTE`、`AXIS`、`BOL_COLORS`，不要在页面里散写 `#374151`、`#6b7280` 等硬编码色值
   - 需要强调的语义色仍按 `PALETTE[0]`、`PALETTE[1]`、`PALETTE[2]`、`PALETTE[4]` 等统一使用

3. 间距标准
   - 柱图最大宽度统一收口到 `CHART_SPEC.barMaxWidth = 22`
   - 类别间距统一通过 `barCategoryGap`、`grid`、`containLabel` 等控制，不在单图里散写魔法值

4. label 显示条件
   - 显示 inline label 的判定必须使用 `buildValueLabelConfig(...)`，不能直接写 `show: itemCount <= 8`
   - 对于条形图/折线图等密度高的图，默认使用 `show: false` 策略，保留 tooltip 作为主阅读入口
   - 只有在“可读性不受影响”的前提下才允许强制 `show: true`

#### 6.7.5 新增图表必须遵守的操作流程

新增任意 ECharts 图表时，必须按以下顺序：

1. 先判断图表类型：bar / barCompact / line / scatter / heatmap / boxplot / custom
2. 选择对应的 `chartType`，不要直接套用 `bar`
3. 用 `buildValueLabelConfig(chartType, itemCount, extra)` 生成 label
4. 若图表是 `pie`、`donut`、`custom` 或 `boxplot` 等特殊图表，确认是否真的需要 inline label；若不需要，则保留默认 tooltip / legend 逻辑，不强行加 tag
5. 只在必要时通过 `extra` 覆盖 `position`、`formatter`、`color`，不能重新定义一套 label 规范

#### 6.7.6 禁止项

以下行为一律禁止：

- 页面中散写 `label: { show: true, ... }` 而不走 helper
- 在不同页面重复写 `show: itemCount <= 8` 这种 ad hoc 判断
- 在同一图表中混用多套字体大小/颜色规范
- 直接写死 `#374151`、`#4b5563` 等颜色，绕过 `AXIS` / `PALETTE`
- 对 `pie` / `boxplot` / `custom` 等天然不适合标签的类型强制加全量 label

#### 6.7.7 实际落地位置

当前全站标准已落地在：

- [frontend/src/utils/echartsTheme.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/echartsTheme.js)
- [frontend/src/views/DashboardView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/DashboardView.vue)
- [frontend/src/views/DynamicBolView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/DynamicBolView.vue)
- [frontend/src/views/ActualCtView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/ActualCtView.vue)

凡是新增图表时，优先复用这里的规则，不得绕回“散写 label 规则”。

### 6.8 通用组件
- [components/ChartCard.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/components/ChartCard.vue):可复用 ECharts 容器,封装 init/resize/dispose 生命周期;props:`title` / `subtitle` / `option`(必填)/ `height`(默认 280)/ `autoResize` / `onChartClick`;`mergeDeep` 深合并 `baseOption`;ResizeObserver + window.resize 双监听
- [components/PageHeader.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/components/PageHeader.vue):标准化页面头部(sticky + 毛玻璃 + 顶部 2px 渐变条);props:`title` / `subtitle` / `icon` / `breadcrumbs`;通过 `useAuth` 获取 `roleLabel`/`userInitials`/`logout`;品牌 B 标 + 日期时间 + 用户 chip + 退出登录(带 ElMessageBox 确认)

### 6.8 视图层
| 视图 | 文件 | 职责 | 主要 API |
|---|---|---|---|
| 登录 | [LoginView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/LoginView.vue) | 用户名密码登录 + 游客入口 | `authApi.login` / `guestLogin` |
| 注册 | [RegisterView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/RegisterView.vue) | 注册(校验密码≥8 位+两次一致) | `authApi.register` |
| 找回/重置密码 | [ForgotPasswordView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/ForgotPasswordView.vue) / [ResetPasswordView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/ResetPasswordView.vue) | 邮件重置流程 | `authApi.forgotPassword` / `resetPassword` |
| 主页 | [HomeView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/HomeView.vue) | 模块导航(核心模块大卡 + 工具模块小卡),游客锁标 | — |
| 综合看板 | [DashboardView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/DashboardView.vue) | 跨源汇总 + BOL 分布 + 跟踪状态 | `analyticsApi.dashboard` / `trackingApi.list` |
| 账号设置 | [AccountView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/AccountView.vue) | 资料编辑 + 改密 | `useAuth.updateProfile` / `changePassword` |
| 人员管理 | [UserView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/UserView.vue) | 员工 CRUD(仅 ADMIN) | `userApi.*` |
| BOL 审批记录 | [DynamicBolView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/DynamicBolView.vue) | 多 Tab(总览/趋势/低 LB) | `dynamicBolApi.*` |
| 预算 BOL | [BudgetBolView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/BudgetBolView.vue) | 三类型管理 + 财年对比 Tab | `budgetBolApi.*` + 内嵌 `BudgetBolComparisonView` |
| 导入帮助 | [BudgetBolHelpView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/BudgetBolHelpView.vue) | 静态文档(el-steps 四步流程) | — |
| 实测 CT | [ActualCtView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/ActualCtView.vue) | 多 Tab(SCT vs ACT / LB / BoxPlot / Search) | `actualCtApi.*` |
| 高 BOL 跟踪 | [TrackingView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/TrackingView.vue) | CRUD + 状态机 + 时间线 | `trackingApi.*` + `userApi` |
| 综合多维分析 | [analytics/ComparisonView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/analytics/ComparisonView.vue) | 工艺 × RoofType × 工厂 × 财年 | `analyticsApi.multiDimAnalysis` / `multiDimTrend` |
| 财年对比(子组件) | [analytics/BudgetBolComparisonView.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/views/analytics/BudgetBolComparisonView.vue) | 内嵌于 BudgetBolView 的 COMPARISON Tab | `analyticsApi.budgetBolComparison` |

---

## 7. 关键类与函数说明

### 7.1 后端核心类与函数

#### BOL 计算([bol_calc.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/bol_calc.py))
```python
def calc_bol(ct: float, hc: float, oee: float) -> float
    # BOL = CT × HC × (1 + 1/15) / OEE / 60  (CT秒→BOL分钟)
def calc_bol_gap(bol_a: float, bol_b: float) -> float   # A - B
def calc_labor_cost_gap(bol_gap, annual_volume, labor_rate) -> float
  # 年化成本差异(元) = BOL差异(分钟/件) × 年产量(件/年) × 工时单价(元/小时) / 60
```

#### 工厂标准化([plant_utils.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/plant_utils.py))
```python
def normalize_plant(raw) -> str               # 各种变体→短代码 CJ/BJ/SH/CQ/GZ/WH/CMC/YT
def normalize_project_code(raw) -> str       # 去除 Ext1-/Ext2- 前缀
def get_plant_raw_values(standard_code) -> list  # 标准码→所有变体(含大写)
def build_plant_q(field_name, standard_code, qs_class) -> Q  # 构建 Q 对象
```

#### 数据库路由([db_router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/db_router.py))
```python
class BolDbRouter:
    hrdb_apps = {'projects', 'dynamic_bol', 'actual_ct'}
    def db_for_read(self, model, **hints)   # hrdb_apps → 'hrdb',否则 'default'
    def db_for_write(self, model, **hints)  # hrdb_apps → None(禁写),否则 'default'
    def allow_migrate(self, db, app_label, ...)  # hrdb_apps → False,否则 db=='default'
```

#### 认证([authentication.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/users/authentication.py))
```python
class EmployeeTokenAuthentication(authentication.BaseAuthentication):
    keyword = 'Token'
    def authenticate(self, request)            # 解析 Authorization 头
    def authenticate_credentials(self, key)     # 校验 AuthToken 过期+Employee 状态
```

#### Excel 导入([excel_importer.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/budget_bol/excel_importer.py))
```python
class BudgetBolImporter:
    def __init__(self, fiscal_year, bol_type=TYPE_ACHIEVABLE, created_by='')
    def import_from_file(self, file_path) -> dict  # 主入口,事务内清空+全量导入
    def _pick_sheet(self)                          # 按 bol_type 选 sheet
    def _clear_old_records(self) -> int           # 清空同财年同类型旧记录
    def _import_budget_row(...) / _import_achievable_row(...) / _import_target_row(...)
```

#### 跟踪状态机([tracking/views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/tracking/views.py))
```python
STATE_TRANSITIONS = {  # 状态流转规则
    'OPEN': ['IN_PROGRESS'], 'REOPENED': ['IN_PROGRESS'],
    'IN_PROGRESS': ['ACHIEVED'],
    'ACHIEVED': ['VERIFIED', 'IN_PROGRESS'],
    'VERIFIED': ['CLOSED', 'IN_PROGRESS'],
    'CLOSED': ['REOPENED'],
}
class HighBolTrackingViewSet(viewsets.ModelViewSet):
    def _change_state(self, request, pk, target_status, log_type, log_text_fn, extra_field_fn=None)
        # 状态流转通用方法:校验 STATE_TRANSITIONS → 维护时间戳 → 写日志
```

#### CT 分析([actual_ct/analysis.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/actual_ct/analysis.py))
```python
def filter_outliers_iqr(values)                  # Tukey IQR 1.5×IQR 剔除
def compute_represent_ct(values)                 # P1-P99 + IQR 双重剔除后中位数
def build_histogram(values, bin_count=10, bin_size=None)
def build_xbar_r_chart(daily_series)             # 休哈特 Xbar-R 控制图
def build_station_ct_analysis(records, months=3, bin_size=None)  # 工位级分析主入口
def get_ope_connection()                          # 直连 OPE 数据仓库
def execute_ope_query(sql, params=None)          # 执行 raw SQL 返回 dict 列表
```

#### 项目编号识别([dynamic_bol/views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/dynamic_bol/views.py))
```python
_PROJECT_CODE_RE = re.compile(r'^[A-Z](\d{4})([a-zA-Z]?)$')
def _extract_project_key(program_code)   # O6848/T6848 → '6848'
def _pick_canonical_code(codes)          # 同项目优先选 T 开头
def _find_matching_codes(program_code)   # 查找所有同项目编码
```

### 7.2 前端核心函数与组合式

#### 认证状态([composables/authState.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/composables/authState.js))
```javascript
const authState = reactive({ token, expiresAt, user, loading, rememberedUsername })
function isAuthExpired()                // 检查过期
function setAuthPayload(payload)        // 写入并持久化 + 记住用户名
function clearAuthState()               // 清 token,保留 rememberedUsername
function rememberUsername(name) / clearRememberedUsername()
```

#### 认证组合([composables/useAuth.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/composables/useAuth.js))
```javascript
export function useAuth() {
  return {
    state: readonly(authState),
    isAuthenticated, isAdmin, isGuest, roleLabel, userInitials,  // computed
    login, guestLogin, register, logout, fetchMe,                // 方法
    changePassword, updateProfile, hasRole, getToken, clearAuth
  }
}
```

#### ECharts 工具([utils/echartsTheme.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/echartsTheme.js))
```javascript
export const PALETTE = ['#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', ...]
export const BOL_COLORS = { high, mid, low }
export const AXIS = { text, textDim, line, lineBright }
export const baseOption = { /* ECharts 通用配置 */ }
export function mintGradient(vertical) / amberGradient(vertical) / dangerGradient(vertical)
export function withAlpha(hex, alpha)             // hex → rgba
export function aggregate(items, groupBy, valueField, op)  // sum/count/avg/max
export function topN(items, n)
export function histogram(values, binCount)
```

---

## 8. 数据库设计与路由策略

### 8.1 双库配置

| 配置项 | default 库 | hrdb 库 |
|---|---|---|
| ENGINE | mssql | mssql |
| NAME | CMC | HRDB |
| 用途 | 新平台读写 | 既有系统只读 |
| HOST/USER/PASSWORD | 同一台 SQL Server(`db_config.ini` 可覆盖) | 同上 |
| ODBC Driver | 默认 `ODBC Driver 18 for SQL Server` | 同上 |
| 迁移 | Django 管理(`allow_migrate=True` 当 db=='default') | 禁止(`allow_migrate=False`) |

### 8.2 数据表分布

#### CMC 库(default,Django 管理建表)
| 表名 | 应用 | 模型 | 类型 |
|---|---|---|---|
| `CN_IE_BOL_Employee` | users | Employee | 读写 |
| `CN_IE_BOL_AuthToken` | users | AuthToken | 读写 |
| `CN_IE_BOL_PasswordResetToken` | users | PasswordResetToken | 读写 |
| `CN_IE_BOL_BudgetBol` | budget_bol | BudgetBol | 读写 |
| `CN_IE_BOL_AchievableTargetBol` | budget_bol | AchievableTargetBol | 读写 |
| `cbco_records` | budget_bol | CbcoRecord | **只读**(managed=False) |
| `CN_IE_BOL_HighBolTracking` | tracking | HighBolTracking | 读写 |
| `CN_IE_BOL_ImprovementLog` | tracking | ImprovementLog | 读写 |

#### HRDB 库(hrdb,只读,表已存在不迁移)
| 表名 | 应用 | 模型 |
|---|---|---|
| `CN_IE_BOL_programCodeInfor` | projects | ProgramInfo |
| `CN_IE_BOL_Userdatabase` | projects | BolUser |
| `CN_IE_BOL_StationInfor` | projects | StationInfo |
| `CN_IE_BOLOverView` | dynamic_bol | BolOverView(92 字段) |
| `CN_IE_BOLOverView_byProcess` | dynamic_bol | BolOverViewByProcess |
| `CN_IE_BOL_approval_historyList` | dynamic_bol | BolApprovalHistory |
| `CN_IE_BOL_UpdateHistoryList` | dynamic_bol | BolUpdateHistory |
| `fine_user` | dynamic_bol | FineUser |
| `CN_IE_CT_realCT_extract` | actual_ct | RealCtExtract |
| `CN_IE_CT_realCT_extract_perDay` | actual_ct | RealCtExtractPerDay |
| `CN_IE_CT_bottleNeck_list` | actual_ct | BottleNeckCt |
| `CN_IE_CT_Realtime_status` | actual_ct | CtRealtimeStatus |
| `CN_IE_realTime_projects_acquisition` | actual_ct | ProjectAcquisition |

#### OPE 远程数据仓库(独立 InalfaCNDM @ 172.26.2.212)
| 视图名 | 访问方式 | 用于 |
|---|---|---|
| `OPE.V_fact_cn_realTimeCT_overView` | pyodbc raw SQL | actual_ct 的 station-detail / search / 部分级联筛选;失败回退到 hrdb 连接 |

### 8.3 跨库查询约束(强制)

> 写在 [analytics/views.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/apps/analytics/views.py) 顶部注释,全项目遵循:

1. Django 不支持跨库 JOIN → 所有跨库合并在 **Python 层**用 dict 完成
2. **禁止** `select_related` / `prefetch_related` 跨库关联
3. 所有 HRDB 模型 `Meta.managed = False`,仅作读取映射
4. 合并键使用归一化函数:`_line_key(program_code, process, line_nr)` / `_pp_key(program_code, process)` / `normalize_plant`
5. **禁止 fallback 兜底**,要求精确匹配关键维度 `(project_code, line_nr, process_type, location)`

---

## 9. 依赖关系

### 9.1 后端 Python 依赖([requirements.txt](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/requirements.txt))
```
Django==4.2.30
djangorestframework==3.17.1
django-cors-headers==4.9.0
django-filter==25.1
mssql-django==1.7.3
pyodbc==5.3.0
waitress==3.0.2
openpyxl==3.1.5
Pillow==12.2.0
# 可选(定时任务,缺失时降级)
# apscheduler
```

### 9.2 前端 npm 依赖([package.json](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/package.json))
```
dependencies:
  vue ^3.5.40
  vue-router ^4.6.4
  element-plus ^2.14.3
  @element-plus/icons-vue ^2.3.2
  axios ^1.18.1
  echarts ^6.1.0
devDependencies:
  vite ^8.1.1
  @vitejs/plugin-vue ^6.0.8
```

### 9.3 模块依赖图

```
                    ┌────────────────────────┐
                    │  bol_platform(项目级)  │
                    │  settings/db_router/   │
                    │  bol_calc/plant_utils  │
                    └─────┬──────────────┬───┘
                          │              │
        ┌─────────────────┴──┐  ┌────────┴──────────────┐
        │   hrdb_apps(只读)   │  │  default_apps(读写)    │
        ├──────────────────┐ │  ├─────────────────────┐ │
        │ projects         │ │  │ users(认证/权限基座) │ │
        │ dynamic_bol      │ │  │ budget_bol           │ │
        │ actual_ct        │ │  │ tracking             │ │
        │ (含 OPE 远程)    │ │  │ analytics(跨库)      │ │
        └──────────────────┘ │  └─────────────────────┘ │
                             │                          │
                             └────────────┬─────────────┘
                                          │
                                  analytics 跨库聚合
                                  (依赖 projects/dynamic_bol/actual_ct/budget_bol/tracking)
                                          │
                                          ▼
                                ┌──────────────────┐
                                │   前端 views     │
                                │ DashboardView    │
                                │ ComparisonView   │
                                │ ... (调用对应 API)│
                                └──────────────────┘
```

### 9.4 关键依赖说明
- `tracking` 依赖 `bol_platform.bol_calc`(自动计算 `bol_gap` / `cost_gap`)
- `analytics` 是唯一跨 5 个 App 数据的"聚合层",依赖 `projects` / `dynamic_bol` / `actual_ct`(hrdb)+ `budget_bol` / `tracking`(default)
- `actual_ct` 是唯一同时使用 ORM + raw SQL(pyodbc 直连 OPE)的 App
- `budget_bol.views.list` 内部调 `bol_platform.plant_utils` 标准化 plant 字段,且查 `CbcoRecord` 补全项目信息
- 前端 `TrackingView` 依赖 `userApi` 拉取责任人下拉;`BudgetBolView` 内嵌 `BudgetBolComparisonView` 作为 COMPARISON Tab

---

## 10. 项目运行方式

### 10.1 开发模式(前后端分离)

#### 后端开发服务器
```powershell
cd backend
pip install -r requirements.txt           # 安装依赖
python manage.py migrate                  # 建表(仅 default 库)
python manage.py create_admin             # 创建管理员账号(交互式)
python manage.py runserver 0.0.0.0:8000   # 启动开发服务器(DEBUG=True,使用 settings.py)
```

#### 前端开发服务器
```powershell
cd frontend
npm install                               # 安装依赖
npm run dev                               # 启动 Vite(host 0.0.0.0:5173,/api 代理到 8000)
```

访问 `http://127.0.0.1:5173`。Vite 自动把 `/api/*` 代理到 `http://127.0.0.1:8000`。

### 10.2 生产模式(合并部署)

生产模式由 [run_server.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/run_server.py) 启动,使用 `settings_prod`(`DEBUG=False`),前端构建产物由 Django 直接托管。

```powershell
# 1. 构建前端
cd frontend
npm install
npm run build                             # 输出到 frontend/dist

# 2. 收集静态文件(把 frontend/dist 复制到 backend/staticfiles)
cd ../backend
python manage.py collectstatic --noinput

# 3. 迁移数据库
python manage.py migrate

# 4. 启动生产服务器(waitress)
python run_server.py                      # 默认 0.0.0.0:8090
# 或自定义:python run_server.py --host 0.0.0.0 --port 8090 --threads 8
```

访问 `http://<host>:8090`,Django 同时提供:
- `/api/*` REST API
- `/admin/` Django Admin
- `/static/` `/assets/` 静态资源
- 其他路径 → `serve_spa()` 返回 `frontend/dist/index.html`(Vue Router history 模式回退)

### 10.3 启动流程([run_server.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/run_server.py) `main()`)
1. 设置 stdout/stderr 为 UTF-8(Windows PyInstaller 中文兼容)
2. 检测 `_is_frozen()`(PyInstaller 环境)→ 设置 `sys.path` 与资源路径
3. 设置 `DJANGO_SETTINGS_MODULE=bol_platform.settings_prod`
4. `check_prerequisites()`:检查前端 dist / staticfiles / waitress 安装
5. `django.setup()`
6. **`check_database_connection()`**:预检 default + hrdb 双库连接,失败时给出 ODBC 驱动修复指引(IM002 错误特别提示)
7. `get_wsgi_application()` → `waitress.serve(application, host, port, threads=8, channel_timeout=120, recv_bytes=65536)`

### 10.4 PyInstaller 打包(单 exe 部署)

使用 [bol_server.spec](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_server.spec) 规格打包为单可执行文件 `BOLServer.exe`,运行时通过 `_is_frozen()` 自动检测环境,优先从外部目录加载 `db_config.ini` / `frontend/dist` / `staticfiles`,便于部署时单独更新前端或修改数据库连接。

```powershell
cd backend
pyinstaller bol_server.spec
# 立即打包为部署包(防止 SentinelOne 杀软删除 exe)
```

> **注意**:企业杀毒软件 SentinelOne 可能拦截并删除 PyInstaller 生成的 exe,必须在同一命令中立即打包为部署包 zip(参见 §12 工程约定)。

打包后运行:
```powershell
BOLServer.exe --host 0.0.0.0 --port 8090
```

### 10.5 定时任务

- 改善周报自动发送:每周二 12:00(Asia/Shanghai),由 APScheduler 触发 `send_improvement_report` 命令
- 手动触发:`python manage.py send_improvement_report --dry-run`(打印到 stdout 不发邮件)
- 指定收件人:`python manage.py send_improvement_report --email a@b.com,c@d.com`

---

## 11. 部署与配置

### 11.1 数据库与邮件配置([db_config.ini](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/db_config.ini.example))

复制 `db_config.ini.example` 为 `db_config.ini`,放置位置(按优先级):
1. 环境变量 `BOL_DB_CONFIG` 指定的路径(最高优先级)
2. PyInstaller 环境:`BOLServer.exe` 同目录
3. 普通环境:`backend` 目录

```ini
[database]
host = IRSCNYTFINEREPORT.ap.inalfa.local,1433
user = sparePartRead
password = Inalfa@2026
driver = ODBC Driver 18 for SQL Server  ; 可改 17 / SQL Server Native Client 11.0
extra_params = TrustServerCertificate=yes;Encrypt=no;

[email]
host = 172.19.253.10                    ; 公司内部邮件服务器
port = 25
use_ssl = True
use_tls = False
user =                                  ; 内部邮件无密码
password =
from_email = BOL管理系统 <bol-system@inalfa.local>
admin_email =                           ; 接收周报的管理员邮箱(逗号分隔)
```

> 如不创建 `db_config.ini`,系统使用 [settings.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings.py) 中的默认值。

### 11.2 关键环境变量
| 变量 | 作用 | 默认值 |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Django 配置模块 | `bol_platform.settings`(开发)/ `bol_platform.settings_prod`(生产,由 run_server.py 设置) |
| `BOL_DB_CONFIG` | db_config.ini 路径覆盖 | — |
| `BOL_FRONTEND_URL` | 前端基础 URL(邮件链接用) | 空 |

### 11.3 ODBC 驱动
- 默认 `ODBC Driver 18 for SQL Server`(部署服务器已安装)
- 可通过 `db_config.ini` 覆盖为 `ODBC Driver 17 for SQL Server` / `SQL Server Native Client 11.0` / `SQL Server`
- 已安装驱动可通过 `odbcad32.exe`(ODBC 数据源管理器)查看
- 启动预检 [check_database_connection()](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/run_server.py#L131) 针对常见 IM002 错误给出明确指引

### 11.4 全局 DRF 配置([settings.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings.py#L215))
```python
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'bol_platform.pagination.CustomPageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [DjangoFilterBackend, SearchFilter, OrderingFilter],
    'DEFAULT_AUTHENTICATION_CLASSES': ['apps.users.authentication.EmployeeTokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['apps.users.permissions.IsAuthenticatedEmployee'],
    'EXCEPTION_HANDLER': 'bol_platform.exceptions.custom_exception_handler',
}
```

### 11.5 SPA 路由回退([urls.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/urls.py))
生产环境(`DEBUG=False`)在主路由末尾添加:
- `re_path(r'^assets/(?P<path>.*)$', serve, {document_root: frontend_root/'assets'})`
- `re_path(r'^static/(?P<path>.*)$', serve, {document_root: static_root})`
- `re_path(r'^(favicon\.svg|logo\.png|icons\.svg|skyline\.jpg)$', serve, ...)`
- `re_path(r'^(?!api/|admin/|assets/|static/|favicon\.svg|logo\.png|icons\.svg|skyline\.jpg).*$', serve_spa)` — 负向先行断言确保不捕获 API/admin/static 路径

---

## 12. 关键业务约束与设计约定

> 这些约束来源于项目 [memory/project_memory.md](file:///c:/Users/ligu/.trae-cn/memory/projects/-c-WorkFile-D-OPEX-04-Digital-development-2026-IE-------BOL------p2-2dc229f5d89548c483ca/project_memory.md) 与代码注释,**修改时务必同步更新**。

### 12.1 数据约束
- **BOL 对比**必须按相同 Roof Type + 相同 Process Type 进行;工厂级平均 BOL 无对比意义
- **Process Type** 系统中只能取三个值:`FA` / `IHR` / `IHE`
- **最大可达线平衡率(LB)上限为 91%**(人机配合工位上限),高于 91% 视为不可行
- **CT 计算**采用国际 IE 最佳实践:`Shewhart 控制图(Xbar-R)` + `Tukey IQR` 组合方法
- **数据匹配**必须使用精确匹配关键维度 `(project_code, line_nr, process_type, location)`,**禁止 fallback 兜底**;缺失数据显示为空,不设任意兜底值
- **工厂地点**统一标准化为短代码:`CJ` / `BJ` / `SH` / `CQ` / `GZ` / `WH` / `CMC` / `YT`(不使用全称或别名)
- **项目号同一项目识别**:前缀字母(O/S/T)不同视为同一项目不同阶段需合并;后缀字母(a/E 等)不同视为不同项目不合并;识别键 = 后 4 位数字 + 后缀字母(若有);筛选器仅保留 T 开头代表编码

### 12.2 改善机会圆整规则
- **潜在减人头数**圆整:小数部分 ≥ 0.8 才向上圆整(如 0.3→0、0.8→1、1.5→1、1.8→2)
- 仅圆整值 ≥ 1 的项目才计入统计
- 保守方案:`减 floor(潜在减人)`,需 `LB ≤ 91%` 才可行
- 激进方案:`减 = HC - ceil(有效工作量/0.91)`

### 12.3 数据导入与清除
- **Budget BOL 导入**:同财年 + 同 BOL 类型(Budget/Achievable/Target)必须**先清空已有记录再全量替换**(事务内执行,任一行异常触发回滚)
- **一键数据清除**仅 `ADMIN` 角色可执行,需输入确认码 `CONFIRM_CLEAR`
- **Excel 导入**不需要查询已有表内容,直接清空再写入
- **Budget BOL 表结构**必须与 Excel 文件格式完全一致(7 列 Budget / 23 列 Achievable & Target)
- **Achievable BOL 与 Target BOL** 共享同一张表结构,通过 `bol_type` 字段区分;最后 4 列顺序不同(OEE 在 Achievable 第 20 列,在 Target 第 22 列)

### 12.4 认证与权限
- **Guest 用户**权限受限,仅可访问 `meta.guestAllowed` 标记的模块;其他路由显示锁标识并限制访问
- **Guest 登录**使用固定虚拟账号 `guest`,24 小时短令牌
- **非 guestAllowed 路由**对 Guest 显示锁标识并限制访问
- **登录令牌**:默认 168 小时(7 天),`remember=true` 时 720 小时(30 天);支持多端共存(复用未过期令牌)
- **密码重置令牌** 1 小时有效,使用后标记 `used=True` 并删除该用户全部 AuthToken
- **改密**后删除该用户其他令牌(保留当前)

### 12.5 前端 UI 约束
- **ECharts 主题**:白底深字 + 浅蓝调色板(`#0ea5e9` 主 / `#0284c7` 深 / `#38bdf8` 浅),**不使用薄荷绿**
- **源码中无硬编码颜色**,必须使用主题变量(`--color-primary` 等)或调色板引用
- **图表容器**禁止使用 `flex:1` 或 `min-height:0`(防止覆盖行内高度设置)
- **Y 轴标签**使用 `grid.left=70` / `nameLocation` / `nameGap` 防遮挡
- **动态颜色逻辑**必须拆分为固定颜色的多个系列,确保图例-颜色一致
- **BOL 审批履历筛选器**默认 `BJ+FA+BJFA1+T6763`,防止页面加载时空数据可视化

### 12.6 工程约定
- **Vite** 必须配置 `host: '0.0.0.0'`(绑定所有网卡 IPv4+IPv6,避免 localhost 访问问题)
- **OPE 查询**的数据库连接在 `CascadeFilterView` 中应通过 `_query_ope_distinct_batch` 复用以降低开销
- **改善机会分析明细表**必须包含项目名与客户名列,横向自适应宽度使用 `min-width`
- **Django settings** 必须包含 `STATICFILES_DIRS` 指向 `frontend/dist`,确保 `collectstatic` 收集前端构建产物
- **ODBC 驱动**默认 `ODBC Driver 18 for SQL Server`(匹配部署服务器),可通过 `db_config.ini` 覆盖
- **Django 启动**包含数据库连接预检([check_database_connection()](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/run_server.py#L131)),对常见问题(如缺失 ODBC 驱动)给出清晰错误信息

### 12.7 邮件与定时任务
- **系统邮件通知**使用公司内部邮件服务器 `172.19.253.10:25`,SSL 加密,无密码
- **定时改善分析报告**每周二 12:00 自动发送,HTML 格式,内联 CSS(Outlook 兼容)

### 12.8 经验教训(踩坑记录)
- 工厂别名匹配在 [plant_utils.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/plant_utils.py) 必须包含大写变体(如 `CC`),以匹配大小写敏感的 OPE 数据库 collation
- axios 响应拦截器已返回 `response.data`,组件代码中用 `res` 直接,**不要** `res.data`(会变成 undefined)
- Django 开发服务器重启(如代码变更)后,浏览器 console 可能残留过期 403 错误;调试前应通过 Django 服务器日志或 `console.clear()` 验证
- **BOL 变更审批履历功能**:通过相同 `program_code` + 相同 `process` + `final_approve_status='Approved'` 识别同一项目不同版本,`BOL_Overall` 来自 `CN_IE_BOLOverView`,CT/HC/LB 来自 `CN_IE_BOLOverView_byProcess`(多段聚合:CT/HC 取 sum,LB 取 avg)
- koa-connect 包装器导致 ctx 泄漏;原生 Koa 中间件重写而非包装 Express 中间件(本项目历史经验)
- **SentinelOne 企业杀毒软件**可能拦截并删除 PyInstaller 生成的 exe;必须在 PyInstaller 执行的同一命令中立即创建部署包,防止文件被删除

---

## 附录:快速链接

### 后端关键文件
- [backend/manage.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/manage.py)
- [backend/run_server.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/run_server.py)
- [backend/requirements.txt](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/requirements.txt)
- [backend/bol_platform/settings.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings.py)
- [backend/bol_platform/settings_prod.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/settings_prod.py)
- [backend/bol_platform/urls.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/urls.py)
- [backend/bol_platform/db_router.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/db_router.py)
- [backend/bol_platform/bol_calc.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/bol_calc.py)
- [backend/bol_platform/plant_utils.py](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/backend/bol_platform/plant_utils.py)

### 前端关键文件
- [frontend/package.json](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/package.json)
- [frontend/vite.config.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/vite.config.js)
- [frontend/src/main.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/main.js)
- [frontend/src/App.vue](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/App.vue)
- [frontend/src/api/index.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/api/index.js)
- [frontend/src/router/index.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/router/index.js)
- [frontend/src/styles/main.css](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/styles/main.css)
- [frontend/src/utils/echartsTheme.js](file:///c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/frontend/src/utils/echartsTheme.js)

---

*本文档基于代码静态分析生成,如代码变更请同步更新。*
