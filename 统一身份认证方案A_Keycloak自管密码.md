# 多业务系统统一身份认证方案 A：Keycloak 自管密码 + 中央人员表

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.1（评审稿补丁：对照表 / 紧急停号 / 反代 / 接入矩阵 / Admin REST PUT 修正） |
| 适用环境 | Windows Server + SQL Server（IRSCNYTFINEREPORT.ap.inalfa.local）+ Keycloak 26.x |
| 目标用户规模 | < 50 人 |
| 阅读对象 | 项目负责人（懂业务、非 IT 专业）、实施工程师、企业 IT 配合人员 |
| 密文约定 | 文档中所有口令一律用占位符，如 `<DB_PWD>`、`<SMTP_PWD>`，实施时替换为真实值并妥善保管 |
| 核对声明 | 标注"※请核对"的配置项，实施前必须按所用版本的官方文档核对，本文不保证与最新版本逐字一致 |
| v1.1 变更 | 增加跨系统账号对照表；紧急停号并立刻踢会话；Keycloak 不再直占 443（前置反代）；各系统接入矩阵（OIDC/SAML/网关/本地）；同步脚本改为 GET→改→PUT；登录名禁止 MERGE 改写；Keycloak 粗粒度准入组 |

> **修订记录（2026-11-09，第二轮）**：按《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 / §9.5 对齐——§9.3 会话改为 **SSO Session Idle 1 天（86400 秒）/ Max 7 天（604800 秒）**（原 8 小时 / 12 小时作废）；§9.5 SMTP 改为已确定的正式服务：Host `172.19.253.10`、Port `25`、From `ap_sso@inalfa.com`、From Display Name `Inalfa AME系统统一身份认证`、Authentication/SSL/StartTLS 全 OFF。暴力破解维持 5 次 / 900 秒。

## 目录

1. [摘要与目标](#1-摘要与目标)
2. [现状与约束](#2-现状与约束)
3. [总体架构](#3-总体架构)
4. [关键设计决策记录（ADR）](#4-关键设计决策记录adr)
5. [人员主数据表设计（sso 库）](#5-人员主数据表设计sso-库)（含 5.6 对照表）
6. [AD → sso_user 同步](#6-ad--sso_user-同步)
7. [sso_user → Keycloak 同步](#7-sso_user--keycloak-同步)（含 7.6 紧急停号）
8. [Keycloak 部署（Windows 原生）](#8-keycloak-部署windows-原生)（含 8.7 前置反代）
9. [Keycloak 配置](#9-keycloak-配置)
10. [各系统接入模板](#10-各系统接入模板)（含 10.0 接入矩阵）
11. [LDAP-only 系统兼容（本方案最难的题）](#11-ldap-only-系统兼容本方案最难的题)
12. [权限与台账](#12-权限与台账)
13. [安全设计](#13-安全设计)
14. [运维](#14-运维)
15. [实施计划](#15-实施计划)
16. [风险清单与应对](#16-风险清单与应对)
17. [附录](#17-附录)

---

## 1. 摘要与目标

**这一章解决什么问题：** 让项目负责人和评审者在一页内看懂"做什么、为什么、做完之后有什么变化"。

### 1.1 一句话方案

> 建一个中央人员表（`sso_user`），每天从 AD 导出的名单自动同步进这张表；再由 Keycloak 作为统一的"登录大门"（统一认证中心），各业务系统都改用 Keycloak 验证身份。密码由 Keycloak 自己管理（首次登录通过邮件设密），权限仍留在各业务系统内部配置，另用一张极简台账记录"谁在哪个系统有什么角色"。

### 1.2 做完之后的体验

| 角色 | 现状 | 做完之后 |
|---|---|---|
| 普通用户 | 每个系统一套账号密码，忘了就找管理员重置 | 一个用户名、一个密码登录所有已接入系统；忘记密码可在登录页自助重置（邮件） |
| 新员工入职 | 逐个系统开账号，权限靠口口相传 | 名单自动同步 → 各系统管理员按台账开权限 → 用户收邮件设一次密码即可 |
| 员工离职 | 逐个系统找管理员停号，容易漏 | 名单中状态变为"停用"→ 当日自动在 Keycloak 禁用 → 该员工所有已接入系统次日（或会话到期后）全部无法登录 |
| 系统管理员 | 每个系统维护一份用户表 | 用户身份不再自己管，只管"这个人能不能用我的系统、用什么角色"（授权） |
| 项目负责人 | 账号管理无据可查 | 一张台账 + 一份同步日志，离职收权有据可查 |

### 1.3 范围内 / 范围外

| 范围内 | 范围外（明确不做） |
|---|---|
| 统一身份、统一登录（SSO）、自助改密、离职自动禁用 | 集中授权（权限仍由各系统自行配置） |
| 中央人员表与每日同步 | 修改 AD 本身、要求 IT 开放 LDAP |
| Keycloak 在 Windows Server 上原生部署 | 引入 Docker、引入新的操作系统 |
| LDAP-only 系统的兼容方案（网关注入为主，门面为变体） | 把所有系统瞬间切换（采用逐系统灰度） |

---

## 2. 现状与约束

**这一章解决什么问题：** 把"为什么做成这样"说清楚，特别是"为什么不能直接共享 AD 密码"，避免评审时反复纠缠。

### 2.1 现状盘点

| 项目 | 现状 |
|---|---|
| 业务系统 | 自研 Web 系统、帆软 FineReport 11、若干开源/商业系统，技术栈不一，多数部署在 Windows Server（同一台或同一域名） |
| 数据库 | 已有 SQL Server 实例 `IRSCNYTFINEREPORT.ap.inalfa.local`；`finedb_11` 库含帆软用户表 `fine_user`（已从 AD 同步，可作人员数据参考，但**不**作为本方案核心表所在库） |
| AD 域控 | 存在且权威；但 IT 只肯提供**人员名单导出（CSV/表）**，不提供 LDAP 连接 |
| 账号管理 | 各系统独立建账号、独立密码、独立权限；离职收权靠人工逐系统操作 |

### 2.2 硬约束（评审通过后不可再议）

1. **Windows Server 原生部署**，不引入 Docker；常驻组件一律注册为 Windows 服务（NSSM 或 WinSW）。
2. **不修改 IT 对 AD 的管理边界**：AD 仅作为人员主数据来源（导名单），不作为认证来源。
3. **核心表不建在 `finedb_11`**：`finedb_11` 归帆软升级/重装管辖，可能被帆软工具重建；自建独立 `sso` 库隔离风险。
4. **不集中授权**：各系统权限内部配置；仅保留极简台账。
5. **方案 A：Keycloak 自管密码**——不联邦 AD 密码，用户密码唯一存在 Keycloak 中。

### 2.3 为什么不能直接共享 AD 密码（Kerberos/LDAP 认证）

| 原因 | 说明 |
|---|---|
| 技术上被堵死 | AD 密码验证需要 LDAP/Kerberos 通道，而 IT 明确不开放 LDAP 连接，此路不通 |
| 责任边界 | 共享 AD 密码意味着业务系统的登录失败、锁定、密码策略都要 IT 域控背锅；IT 已明确只做"名单提供方" |
| 停用影响面 | 若业务系统直接验 AD，误锁/停用会波及域账号本身（影响电脑登录、邮箱），事故半径过大 |
| 改造成本 | 直接共享 AD 密码同样要求每个系统具备 AD/LDAP 认证能力，对 LDAP-only 系统并没有更省事 |

> 结论：认证与 AD 解耦，AD 只管"人"（名单），不管"密码"。这正是方案 A 的立足点。

### 2.4 角色分工约定

| 标记 | 含义 |
|---|---|
| 【客户自做】 | 项目负责人/实施方可独立完成（建库、跑脚本、配置 Keycloak 等） |
| 【需 IT 配合】 | 需要企业 IT 提供名单、开通防火墙、签发证书、放置计划任务等 |
| 【需厂商支持】 | 需要商业系统厂商（如帆软、各开源/商业系统供应商）配合改造 |

---

## 3. 总体架构

**这一章解决什么问题：** 用一张图 + 一张组件清单，说清"数据怎么流、认证怎么走"。

### 3.1 架构图

```
                ┌─────────────────────────────┐
 AD 域控(IT管) ─►│ 每日人员名单导出 CSV/表      │   ① IT 提供（或放共享目录）
 不给LDAP连接    └──────────────┬──────────────┘
                               │
                               ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Windows Server  IRSCNYTFINEREPORT.ap.inalfa.local           │
 │  ┌────────────────── SQL Server ──────────────────────┐     │
 │  │ finedb_11 (帆软, 只读参考)                           │     │
 │  │ sso (stg_ad_user / sso_user / sso_user_map / …)     │     │
 │  │ keycloak  (Keycloak 26.x 专用库，独立账号)            │     │
 │  └────────────────────────────────────────────────────┘     │
 │                                                             │
 │  浏览器 ──HTTPS:443──► IIS ARR 或 nginx（唯一 TLS 入口）      │
 │                         ├ sso.ap.inalfa.local  → KC:8443    │
 │                         └ 各业务站点 Host/路径 → 原应用     │
 └───────┬──────────────────────────────────▲──────────────────┘
         │ ② PowerShell 同步脚本             │ ⑤ Admin REST API
         │   （每日 + 紧急停号可手工）        │   新增/更新/停用+踢会话/邀请邮件
         ▼                                  │
 ┌──────────────────────────────────────────┴────────────┐
 │  Keycloak 26.x（本机 8443，不直占 443；NSSM + JDK 21）  │
 │  realm: inalfa —— 自管密码 + 企业邮箱 SMTP              │◄─── 浏览器: 统一登录页
 └──────▲───────────────────────────▲────────────────────┘
        │ ③ OIDC / OAuth2 / SAML    │ ④ LDAP-only 或难改系统：
        │  （按第 10 章接入矩阵）     │    nginx + oauth2-proxy 注入用户头
 ┌──────┴──────┐          ┌─────────┴─────────────────┐
 │ 自研 Web     │          │ LDAP-only / 开源商业系统    │
 │ Django/Node │          │ （只信请求头或只支持LDAP）   │
 │ .NET/PHP …  │          └───────────────────────────┘
 └─────────────┘   （若 LDAP-only ≥3 个 → 变体 A'：AD LDS 门面，见第 11 章）
```

### 3.2 两条数据流

**数据流 1：人员数据流（每日，单向，AD → sso_user → Keycloak）**

```
AD 导出名单(CSV) → 暂存表 stg_ad_user → MERGE 合并进 sso_user
   （停用不删；source 标记来源；变更比例异常则中止）
→ 脚本调 Keycloak Admin REST API：新增用户 / 更新资料 / 停用用户 / 首次登录邀请邮件
```

**数据流 2：认证流（实时，浏览器 → 业务系统 → Keycloak）**

```
用户访问业务系统 → 未登录则跳转 Keycloak 登录页 → 输入用户名密码（Keycloak 验证）
→ 签发 OIDC 令牌 → 回到业务系统 → 业务系统凭令牌识别身份 → 按本系统权限展示
（LDAP-only 系统：由网关先到 Keycloak 认证，再把"已认证用户名"通过请求头传给后端系统）
```

### 3.3 组件清单

| 组件 | 用途 | 部署形态 | 责任方 |
|---|---|---|---|
| 前置反代（IIS ARR 或 nginx） | 唯一 443 入口：按 Host 把 `sso.*` 转到 Keycloak:8443，业务站点仍走原应用 | Windows 原生 + 现有 IIS 优先 | 【客户自做】；证书仍【需 IT 配合】 |
| Keycloak 26.x | 统一认证中心（登录页、密码、OIDC/SAML 签发） | Windows 原生 + JDK 21 + NSSM；**监听 8443，不直占 443** | 【客户自做】 |
| SQL Server `sso` 库 | 中央人员表 + 暂存表 + 对照表 + 同步日志 | 现有实例上新建库 | 【客户自做】 |
| SQL Server `keycloak` 库 | Keycloak 自身存储 | 现有实例上新建库（备选 PostgreSQL） | 【客户自做】 |
| 同步脚本（PowerShell ×2） | AD 名单入库；sso_user → Keycloak | Windows 计划任务 | 【客户自做】 |
| 企业邮箱 SMTP | 首次设密 / 忘记密码邮件 | 现有邮箱，建专用发信账号 | 【需 IT 配合】 |
| 网关（nginx 或 IIS ARR + oauth2-proxy） | LDAP-only/难改系统的前置认证 | Windows 原生 + NSSM 服务 | 【客户自做】 |
| AD LDS 门面（仅变体 A' 才需要） | 给只支持 LDAP 的系统提供目录 | Windows 角色原生安装 | 【需 IT 配合】 |
| 权限台账（Excel 或 sso 库一张表） | 谁-哪个系统-什么角色-谁授的 | 见第 12 章 | 【客户自做】 |

---

## 4. 关键设计决策记录（ADR）

**这一章解决什么问题：** 把"选了什么、为什么、放弃了什么、代价是什么"固化下来，防止日后反复。

### ADR-1 认证方案选 Keycloak 自管密码（方案 A），不做 AD 密码联邦

| 项 | 内容 |
|---|---|
| 选了什么 | Keycloak 独立持有用户密码，AD 只提供人员名单 |
| 为什么 | IT 不开放 LDAP，AD 密码联邦技术上不可行（见 2.3）；自管密码也让业务登录与域账号完全解耦，事故互不波及 |
| 放弃了什么 | "域账号密码 = 业务系统密码"的体验；用户需记忆一套新密码 |
| 代价 | 需要邮件通道做首次设密/找回密码；用户教育成本（第一周答疑）；密码策略需在 Keycloak 单独配置 |

### ADR-2 数据库复用现有 SQL Server，不新装 PostgreSQL

| 项 | 内容 |
|---|---|
| 选了什么 | Keycloak 自身库与 `sso` 库都建在现有 SQL Server 实例上 |
| 为什么 | 少一套数据库就少一份备份、监控、账号管理负担；<50 人规模的写入压力对 SQL Server 而言可忽略 |
| 放弃了什么 | PostgreSQL 是 Keycloak 社区使用最广、文档最多的库 |
| 代价 | Keycloak 官方对 SQL Server 的支持需安装 JDBC 驱动且社区案例较少，**升级 Keycloak 前必须在测试环境验证兼容性（※请核对当前版本的数据库支持列表）**；若验证受阻，启用备选方案：单机安装 PostgreSQL 并纳入备份 |
| 风险控制 | `sso` 库与 `keycloak` 库分库、分账号；帆软库 `finedb_11` 完全只读，不写不放自建表 |

### ADR-3 LDAP-only 系统优先走"网关前置认证 + 注入用户头"，不先建 LDAP 门面

| 项 | 内容 |
|---|---|
| 选了什么 | 对 ≤2 个只支持 LDAP（或无法改造）的系统，用网关（oauth2-proxy + nginx/IIS ARR）先到 Keycloak 认证，再把用户名以请求头传给后端 |
| 为什么 | Keycloak 不是 LDAP 服务器，"配个 LDAP 门面"不是零成本——它引入密码权威归属问题（详见第 11 章）；<50 人规模下 LDAP-only 系统大概率 ≤2 个，网关方案组件更少 |
| 放弃了什么 | 一次性给所有老旧系统提供"原生 LDAP 登录"的能力 |
| 代价 | 后端系统必须做到"仅接受来自网关的请求 + 清除客户端同名请求头"，否则存在身份伪造风险；系统直连访问需用防火墙封死 |
| 升级路径 | LDAP-only 系统数量 ≥3 或网关方案被厂商否决时，启用变体 A'（AD LDS 门面），见 11.3 |

### ADR-4 权限不集中，只做台账

| 项 | 内容 |
|---|---|
| 选了什么 | 各系统权限仍在系统内配置；另建一张极简台账记录工号/系统/角色/授予人/日期 |
| 为什么 | 集中授权（把各系统角色映射进 Keycloak 组/角色再下发）需要每个系统支持并被打通，工作量和厂商配合度远超本阶段预算；<50 人规模下台账 + 人工流程已够用 |
| 放弃了什么 | "入职即自动有全部门权限"的全自动体验 |
| 代价 | 入职/调岗仍需各系统管理员手工授权（有台账可查）；台账依赖人维护，存在滞后风险（见风险 R6） |

### ADR-5 同步链路严格单向：AD → sso_user → Keycloak，任何环节不回写

| 项 | 内容 |
|---|---|
| 选了什么 | Keycloak 中的用户资料以 `sso_user` 为准，脚本每次全量比对后修正；`sso_user` 只被 AD 名单修改 |
| 为什么 | 双向同步（如在 Keycloak 改名字回写 AD）既没有权限（IT 不开放），也极易产生数据打架；单向 + 全量比对 = 可随时重跑、可自愈 |
| 放弃了什么 | 在 Keycloak 管理后台手工维护用户资料的灵活性（改了也会被下一次同步覆盖） |
| 代价 | 资料更正（改名、换部门）必须先改 AD 名单，次日凌晨生效；紧急情况可手工触发脚本立即生效 |

### ADR-6 Keycloak 不直占 443，前面必须有反代

| 项 | 内容 |
|---|---|
| 选了什么 | 本机 443 只给 IIS ARR（或 nginx）做 TLS 终结；Keycloak 监听 `127.0.0.1:8443`；`sso.ap.inalfa.local` 反代到 8443 |
| 为什么 | 同一台 `IRSCNYTFINEREPORT` 上帆软/IIS 几乎必然已占用 443；Keycloak 再绑 443 会直接冲突，P1 部署就会失败 |
| 放弃了什么 | Keycloak 自己对外终结 HTTPS（配置更短，但与现网不兼容） |
| 代价 | 多一层反代；Keycloak 必须开 `proxy-headers`（hostname v2）并信任反代传来的 `X-Forwarded-*`；健康检查仍走本机管理端口，不经公网 443 |

### ADR-7 准入组在 Keycloak，细权仍在各系统

| 项 | 内容 |
|---|---|
| 选了什么 | Keycloak 只建粗粒度组（如 `app-finereport`、`app-erp`），表示“允许登录该系统”；菜单/数据权限仍在各系统内配置 |
| 为什么 | 若系统“首次登录自动建档”，全员只要能登 Keycloak 就会在每个系统留下空账号；用组做准入，改造量远小于集中授权 |
| 放弃了什么 | 无。这不是推翻 ADR-4，只补一层“能不能进门” |
| 代价 | 入职时除系统内授权外，还要在 Keycloak 把人加进对应组（可与台账同一流程，&lt;50 人可手工） |

### ADR-8 跨系统用户名用对照表，不假设已经统一

| 项 | 内容 |
|---|---|
| 选了什么 | 表 `sso_user_map`：同一 `employee_no` 在各系统的本地用户名可以不同 |
| 为什么 | 存量系统用户名常不等于 AD 登录名（中文名、邮箱、工号混用）；上线时对不上号是第一大迁移坑 |
| 放弃了什么 | “全公司用户名早已一致”的假设 |
| 代价 | 试点接入前要盘点并填对照表；新员工默认 `local_username = login_name`，只处理历史差异 |

---

## 5. 人员主数据表设计（sso 库）

**这一章解决什么问题：** 定义整个方案的"唯一人员事实来源"——表结构、约束、索引和数据质量规则，使后续所有同步都有据可依。

### 5.1 建库与账号

【客户自做】在 `IRSCNYTFINEREPORT.ap.inalfa.local` 上新建数据库 `sso`；为脚本创建专用 SQL 登录（如 `sso_sync_svc`），仅授予 `sso` 库的读写权限，**不授予 sysadmin**，也**不授予访问 `finedb_11` 之外其他库的权限**（读 `fine_user` 仅用于比对参考时，可建只读账号）。

### 5.2 核心表 DDL

```sql
USE sso;
GO

-- 中央人员表（唯一事实来源）
CREATE TABLE dbo.sso_user (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sso_user PRIMARY KEY,
    employee_no    NVARCHAR(32)  NOT NULL,                -- 工号：跨系统稳定主键
    login_name     NVARCHAR(64)  NOT NULL,                -- 登录名（建议与 AD 账号一致，全小写）
    display_name   NVARCHAR(128) NULL,                    -- 中文姓名
    email          NVARCHAR(128) NULL,                    -- 企业邮箱（首登设密/找回密码依赖此列）
    mobile         NVARCHAR(32)  NULL,
    dept_code      NVARCHAR(64)  NULL,                    -- 部门编码
    dept_name      NVARCHAR(128) NULL,
    title          NVARCHAR(128) NULL,                    -- 岗位/职务
    status         TINYINT       NOT NULL DEFAULT 1,      -- 1=在职 0=停用（停用不删行）
    ad_object_guid UNIQUEIDENTIFIER NULL,                 -- AD 对象 GUID（防工号复用造成误合并）
    source         NVARCHAR(16)  NOT NULL DEFAULT N'AD',  -- 数据来源标记
    pwd_set        BIT           NOT NULL DEFAULT 0,      -- 是否已在 Keycloak 完成首次设密
    synced_at      DATETIME2(0)  NULL,                    -- 最近一次从 AD 合并的时间
    created_at     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_sso_user_status CHECK (status IN (0,1)),
    CONSTRAINT CK_sso_user_source CHECK (source IN (N'AD', N'MANUAL'))
);
GO

-- 唯一约束
ALTER TABLE dbo.sso_user ADD CONSTRAINT UQ_sso_user_employee_no UNIQUE (employee_no);
ALTER TABLE dbo.sso_user ADD CONSTRAINT UQ_sso_user_login_name   UNIQUE (login_name);
-- ad_object_guid 可空列上的唯一性：用过滤索引（仅对非空值生效）
CREATE UNIQUE INDEX UX_sso_user_guid
    ON dbo.sso_user (ad_object_guid) WHERE ad_object_guid IS NOT NULL;
-- 邮箱唯一（Keycloak 默认也要求 email 唯一；空邮箱允许多行）
CREATE UNIQUE INDEX UX_sso_user_email
    ON dbo.sso_user (email) WHERE email IS NOT NULL;
-- 常用查询索引
CREATE INDEX IX_sso_user_status    ON dbo.sso_user (status);
CREATE INDEX IX_sso_user_dept_code ON dbo.sso_user (dept_code);
CREATE INDEX IX_sso_user_synced_at ON dbo.sso_user (synced_at);
GO

-- 跨系统账号对照表（存量用户名 ≠ AD 登录名 时用）
CREATE TABLE dbo.sso_user_map (
    id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sso_user_map PRIMARY KEY,
    employee_no     NVARCHAR(32)  NOT NULL,   -- 关联 sso_user.employee_no
    system_code     NVARCHAR(32)  NOT NULL,   -- 与 perm_ledger.system_code 同一套编码
    local_username  NVARCHAR(128) NOT NULL,   -- 该系统里已经存在的登录名
    match_key       NVARCHAR(16)  NOT NULL DEFAULT N'USERNAME', -- USERNAME / EMAIL / EMPNO
    remark          NVARCHAR(200) NULL,
    created_at      DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_sso_user_map_key CHECK (match_key IN (N'USERNAME', N'EMAIL', N'EMPNO')),
    CONSTRAINT UQ_sso_user_map_sys_local UNIQUE (system_code, local_username)
);
CREATE INDEX IX_sso_user_map_emp ON dbo.sso_user_map (employee_no, system_code);
GO
```

> 时间列统一用 UTC（`SYSUTCDATETIME()`）避免夏令时/多机时区混乱；展示时由报表/脚本转换为本地时间。

### 5.3 字段语义与设计要点

| 字段 | 语义与规则 |
|---|---|
| `employee_no` | 跨系统的**业务主键**；要求 IT 导出名单必须含此列且终身不复用（若 IT 无法保证，改以 `ad_object_guid` 为合并键，见 6.4） |
| `login_name` | 登录名，建议 = AD 域账号小写；与 Keycloak 的 username 一一对应；一旦确定**不改**（改名走"新增新账号 + 停用旧账号"，避免系统间引用断裂）。**MERGE 禁止改写本列**（见 6.5） |
| `email` | 企业邮箱；非空值全局唯一。共用邮箱/非法格式会阻断 Keycloak 同步，入库前按 5.5 处理 |
| `status` | 只做停用标记，**永不物理删除**：历史工单、审批记录仍可追溯该人 |
| `ad_object_guid` | AD 对象唯一标识，用于防"工号被复用给新员工"导致把新人数据合并进老人行 |
| `source` | `AD`（同步产生）或 `MANUAL`（例外手工插入，如外部顾问）；同步脚本**不覆盖** `MANUAL` 行 |
| `pwd_set` | 0=尚未完成首次设密；由 Keycloak 同步脚本检测到用户完成设密后置 1；用于追踪"邀请邮件未完成"的滞留用户 |

### 5.4 暂存表与同步日志 DDL

```sql
-- AD 名单暂存表（每日清空重灌，与 sso_user 结构对齐）
CREATE TABLE dbo.stg_ad_user (
    employee_no    NVARCHAR(32)  NOT NULL,
    login_name     NVARCHAR(64)  NULL,
    display_name   NVARCHAR(128) NULL,
    email          NVARCHAR(128) NULL,
    mobile         NVARCHAR(32)  NULL,
    dept_code      NVARCHAR(64)  NULL,
    dept_name      NVARCHAR(128) NULL,
    title          NVARCHAR(128) NULL,
    status         TINYINT       NOT NULL DEFAULT 1,   -- 名单中标记离职的置 0
    ad_object_guid UNIQUEIDENTIFIER NULL,
    loaded_at      DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_stg_ad_user_employee_no ON dbo.stg_ad_user (employee_no);
GO

-- 同步日志（两类同步共用，phase 区分阶段）
CREATE TABLE dbo.sync_log (
    id          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_sync_log PRIMARY KEY,
    phase       NVARCHAR(16)  NOT NULL,   -- LOAD=读名单入库 / MERGE=合并 / KC=Keycloak 同步
    run_at      DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    src_rows    INT           NULL,       -- 本次名单行数
    added       INT           NULL,
    updated     INT           NULL,
    disabled    INT           NULL,
    reactivated INT           NULL,
    status      NVARCHAR(16)  NOT NULL,   -- OK / ABORTED / ERROR
    message     NVARCHAR(2000) NULL
);
GO
```

### 5.5 数据质量规则（脚本入库前校验）

| 规则 | 处理 |
|---|---|
| `employee_no` 为空或重复 | 该行拒入暂存表，写入 `sync_log.message` |
| `login_name` 重复（跨行） | 全部拒入，人工裁决（不允许脚本自动改名） |
| `email` 为空但 status=1 | 允许入库，但 Keycloak 同步阶段跳过邀请邮件并告警（首登设密依赖邮箱） |
| `email` 格式不合法 | 置空 + 告警，不同步到 Keycloak |
| 手机号/部门码 | 去空格、全角转半角；部门名以 IT 名单为准，不做映射表（<50 人无需） |
| 名单编码 | 要求 UTF-8（或带 BOM 的 UTF-8/GBK，脚本内显式声明编码解析） |
| 同一邮箱出现在两名在职人员 | 整体中止（Keycloak 无法接受重复 email） |

### 5.6 对照表怎么用

接入某个系统前，导出该系统用户表，与 `sso_user.login_name` 做一次对账：

| 对账结果 | 处理 |
|---|---|
| 本地用户名 = `login_name` | 不必插入对照表，系统按 Keycloak `preferred_username` 直接匹配 |
| 本地用户名不同但能确认是同一人 | 插入 `sso_user_map` 一行；接入代码：先查对照表，没有再回落到 `login_name` |
| 对不上、疑似重复账号 | 人工裁决后再接入，禁止脚本猜测 |
| 新员工（对照表无记录） | 默认本地用户名 = `login_name`，不再加行 |

查询模板：

```sql
SELECT u.login_name, u.employee_no, u.email,
       COALESCE(m.local_username, u.login_name) AS app_username,
       COALESCE(m.match_key, N'USERNAME')       AS match_key
FROM dbo.sso_user AS u
LEFT JOIN dbo.sso_user_map AS m
       ON m.employee_no = u.employee_no
      AND m.system_code = N'finereport'   -- 换成目标系统
WHERE u.status = 1;
```

---

## 6. AD → sso_user 同步

**这一章解决什么问题：** 在"IT 只给名单、不给 LDAP"的前提下，把名单稳定、防错地变成 `sso_user` 的每日更新。

### 6.1 三种取数方式（按优先级）

| 方式 | 流程 | 适用 | 责任方 |
|---|---|---|---|
| ① 共享目录（推荐） | IT 每日定时（或下班前手工）把名单导出为 CSV 放入共享目录 `\\<文件服务器>\sso_import\`，脚本计划任务每日 06:00 拉取 | IT 愿意固定一次导出动作 | 导出【需 IT 配合】，取数【客户自做】 |
| ② 邮件附件 | IT 把 CSV 发到专用邮箱，脚本通过 IMAP/POP 拉取附件 | IT 不愿维护共享目录、愿意发邮件 | 导出【需 IT 配合】，收件【客户自做】 |
| ③ 手工上传兜底 | IT 在工作日任意时间导出，项目负责人用网页小工具（或 SQL 导入向导）上传入库 | 过渡期/应急 | 【客户自做】 |

> 建议先以方式③跑通全流程，再推动 IT 固化为方式①。无论哪种方式，**文件命名带日期**（如 `ad_users_20261102.csv`），脚本按文件名日期判断当日名单是否已到。

### 6.2 名单格式约定（与 IT 确认）

```
employee_no,login_name,display_name,email,mobile,dept_code,dept_name,title,status,ad_object_guid
A0001,zhangsan,张三,zhangsan@<公司域名>,13800000000,D01,生产部,主管,1,3F2A8C90-....
```

- `status`：1 在职 / 0 离职停用（IT 名单若用"在职/离职"字样，脚本做字典映射）。
- `ad_object_guid`：若 IT 导不出该列，流程仍可跑，但**必须**额外约定"工号不复用"，并在 `fine_user` 中比对参考。
- 名单**不含分组/权限信息**——这正是"权限留各系统"的原因之一，不要向 IT 追加此要求。
- **必须约定全量名单**（当日在职 + 明确标记的离职，或“只含在职、未出现即视为离职”）。第 6.5 节 `WHEN NOT MATCHED BY SOURCE` 会把当天没出现的在职人员全部停用；若 IT 给的是增量/变更摘录，会误杀全员。把“全量/增量”写进双方签署的名单约定。

### 6.3 同步脚本流程（PowerShell，每日计划任务）

```
1. 找到当日名单文件 → 不存在：写 sync_log(LOAD, ABORTED,'当日名单未到')，发告警邮件，退出
2. 校验/清洗 → 合法行灌入 stg_ad_user（先 TRUNCATE 暂存表）
3. 防错检查（见 6.4）→ 任一命中：写 ABORTED 日志 + 告警邮件 + 退出（当日不合并）
4. MERGE 合并（见 6.5）→ 统计 added/updated/disabled/reactivated
5. 写 sync_log(LOAD+MERGE, OK) → 触发第 7 章的 Keycloak 同步脚本
```

### 6.4 防错规则（异常中止机制）

| 检查 | 阈值（可在脚本参数中调整） | 动作 |
|---|---|---|
| 名单行数 = 0 | — | 中止 + 告警（防止空文件清空合并源） |
| 名单行数比上一日骤降 | 降幅 > 30% | 中止 + 告警（疑似导出残缺） |
| 单日停用人数占比 | > 10% | 中止 + 告警（疑似 IT 导出口径错误；如确有批量离职，人工确认后以 `-Force` 参数放行） |
| 单日新增人数占比 | > 20% | 中止 + 告警 |
| `employee_no` 重复/为空、`login_name` 重复 | 任意 1 条 | 拒入该行；若拒入 > 3 行则整体中止 |
| `ad_object_guid` 与既有行冲突（同 GUID 不同工号） | 任意 1 条 | 中止 + 告警（疑似工号复用） |
| 同一工号的 `login_name` 与库中既有值不同 | 任意 1 条 | 中止 + 告警（禁止 MERGE 改登录名；人工走停旧建新） |

### 6.5 MERGE 合并 SQL（可整段复制）

```sql
-- 供脚本调用；也可在 SSMS 中手工执行（先确保 stg_ad_user 已灌入且防错检查通过）
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
BEGIN TRAN;

MERGE dbo.sso_user AS t
USING dbo.stg_ad_user AS s
   ON t.employee_no = s.employee_no
WHEN MATCHED AND (
        ISNULL(t.display_name,'') <> ISNULL(s.display_name,'')
     OR ISNULL(t.email,'')        <> ISNULL(s.email,'')
     OR ISNULL(t.mobile,'')       <> ISNULL(s.mobile,'')
     OR ISNULL(t.dept_code,'')    <> ISNULL(s.dept_code,'')
     OR ISNULL(t.dept_name,'')    <> ISNULL(s.dept_name,'')
     OR ISNULL(t.title,'')        <> ISNULL(s.title,'')
     OR t.status                  <> s.status
     OR ISNULL(t.ad_object_guid,'00000000-0000-0000-0000-000000000000')
        <> ISNULL(s.ad_object_guid,'00000000-0000-0000-0000-000000000000')
     )
   AND t.source <> N'MANUAL'
THEN UPDATE SET
        -- 故意不更新 login_name：登录名变更走“停旧建新”，避免 Keycloak 再造一个用户
        t.display_name   = s.display_name,
        t.email          = s.email,
        t.mobile         = s.mobile,
        t.dept_code      = s.dept_code,
        t.dept_name      = s.dept_name,
        t.title          = s.title,
        t.status         = s.status,
        t.ad_object_guid = s.ad_object_guid,
        t.source         = N'AD',
        t.synced_at      = SYSUTCDATETIME(),
        t.updated_at     = SYSUTCDATETIME()

WHEN NOT MATCHED BY TARGET THEN
    INSERT (employee_no, login_name, display_name, email, mobile,
            dept_code, dept_name, title, status, ad_object_guid, source, synced_at)
    VALUES (s.employee_no, s.login_name, s.display_name, s.email, s.mobile,
            s.dept_code, s.dept_name, s.title, s.status, s.ad_object_guid, N'AD', SYSUTCDATETIME())

WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> N'MANUAL' THEN
    UPDATE SET t.status = 0, t.synced_at = SYSUTCDATETIME(), t.updated_at = SYSUTCDATETIME();

-- 复职：名单中重新出现的停用人员已由 WHEN MATCHED 分支处理（status 置回 1）。
-- 统计（脚本用 OUTPUT 子句或下述查询统计后写 sync_log）：
--   added      = 本次 INSERT 数
--   updated    = MATCHED-UPDATE 数
--   disabled   = status 1→0 数
--   reactivated= status 0→1 数（脚本按 updated_at/synced_at 对比前后快照统计）
COMMIT;
```

> 注意：MERGE 语句在并发场景历史上有过已知缺陷，本流程为单线程计划任务 + 事务隔离，风险可控；若实施中遇到 MERGE 报错，等价改写为"UPDATE 匹配行 → INSERT 新行 → UPDATE 消失行"三段式即可（※请核对 SQL Server 版本对 MERGE 的支持情况）。
>
> **登录名纪律：** 6.4 已拦截“同工号改 login_name”。禁止在 UPDATE SET 里写 `t.login_name = s.login_name`，否则 Keycloak 按新 username 查不到人，会再 POST 出一个重复账号。

### 6.6 Windows 计划任务

【客户自做】脚本文件建议放 `C:\sso\scripts\`，日志放 `C:\sso\logs\`。注册每日 06:00 任务：

```powershell
schtasks /Create /TN "SSO_AD_Import" /SC DAILY /ST 06:00 `
  /RU "<服务账号或SYSTEM>" /RL HIGHEST `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1"
# 立即测试一次：
schtasks /Run /TN "SSO_AD_Import"
```

- 脚本内所有异常都 `try/catch` 并写 `sync_log`，**不允许静默退出**。
- 失败告警：脚本末尾用 SMTP 发邮件给项目负责人（复用企业邮箱发信账号，见 9.5）。

---

## 7. sso_user → Keycloak 同步

**这一章解决什么问题：** 让 Keycloak 中的用户与 `sso_user` 完全一致：新人自动建号并收邀请邮件、离职自动禁用、复职/资料变更自动更新；脚本可重复执行（幂等）、失败可重试、失败会告警。

### 7.1 前置：Keycloak 管理凭据（最小权限）

【客户自做】不要在脚本里用 `master` 域的超管账号。做法：

1. 在 `inalfa` 域创建机密(confidential)客户端 `sync-client`，关闭"标准流"，仅启用 Service Account（服务账号）。
2. 在该 Service Account 的 Service Account Roles 中授予 realm-management 的：`manage-users`、`view-users`、`query-users`（※请核对当前版本角色名）。
3. 脚本用 client_credentials 方式取 token：

```http
POST https://<KC_HOST>/realms/inalfa/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=sync-client&client_secret=<KC_CLIENT_SECRET>
```

- `<KC_CLIENT_SECRET>` 保管方式见 13.4。

### 7.2 同步流程（每日在 MERGE 之后执行）

> **硬规则：Admin REST 的 `PUT /users/{id}` 是整对象替换。** 只 PUT `{"enabled":false}` 会把姓名、邮箱、属性清空。任何更新都必须：GET 完整 representation → 改字段 → 把完整 JSON PUT 回去。

```
对 sso_user 中每一行：
1. GET /admin/realms/inalfa/users?username=<login_name>&exact=true&max=1
   （按 username 幂等查找，避免重复建号）
2. 不存在 且 status=1：
   POST /admin/realms/inalfa/users
   { username, enabled=true, email,
     lastName=<display_name 全文>, firstName=""   （中文名不要拆姓/名）,
     attributes: { employee_no, dept_code, title } }
   → 响应是 201 + Location 头，body 常为空：从 Location 解析新用户 id
     （例：.../users/a1b2c3d4-...）
   → PUT /admin/realms/inalfa/users/<id>/execute-actions-email
     body: ["UPDATE_PASSWORD"]，查询参数带 client_id=account（或邀请落地客户端）与 redirect_uri
     → 用户收到"激活账号"邮件，点链接设密
3. 已存在：
   先 GET /admin/realms/inalfa/users/<id> 拿到完整对象，后续所有变更都在这份 JSON 上改再 PUT
   a. 比对资料（email / lastName=display_name / 属性）→ 有差异则改对象后 PUT
   b. sso_user.status=0 而 KC enabled=true → 对象.enabled=false → PUT
      → 立刻 POST /admin/realms/inalfa/users/<id>/logout   （踢掉所有会话，不等 15 分钟）
   c. sso_user.status=1 而 KC enabled=false → 对象.enabled=true → PUT（复职）；
      若 pwd_set=0 或停用超过 180 天，重新发 UPDATE_PASSWORD 邀请
   d. 若用户 requiredActions 中 UPDATE_PASSWORD 已消失 且 sso_user.pwd_set=0
      → UPDATE sso_user SET pwd_set=1（完成设密追踪闭环）
4. status=1 但 email 为空：跳过邀请邮件，记录告警行（该人无法自助设密）
5. 全部完成 → 写 sync_log(phase='KC')，统计 added/updated/disabled/reactivated
```

关键 REST 端点一览（※请核对当前版本 Admin REST API 文档）：

| 操作 | 端点 |
|---|---|
| 查用户 | `GET /admin/realms/inalfa/users?username=<login_name>&exact=true&max=1` |
| 建用户 | `POST /admin/realms/inalfa/users`（201 + `Location`，从该头取 id） |
| 取完整用户 | `GET /admin/realms/inalfa/users/{id}`（更新前必调） |
| 更新用户 | `PUT /admin/realms/inalfa/users/{id}`（**必须提交完整 GET 结果**，禁止只提交 enabled） |
| 踢会话 | `POST /admin/realms/inalfa/users/{id}/logout`（禁用后立刻调用） |
| 发设密邀请 | `PUT /admin/realms/inalfa/users/{id}/execute-actions-email?lifespan=259200&client_id=account`，body `["UPDATE_PASSWORD"]`（链接有效期 3 天；realm 需启用内置 `account` 客户端） |
| 查待办动作 | `GET /admin/realms/inalfa/users/{id}`（看 `requiredActions`） |

### 7.3 特殊场景处理

| 场景 | 处理 |
|---|---|
| 首登设密 | 建号时 `enabled=true` + `requiredActions=["UPDATE_PASSWORD"]` + 邮件链接；用户在 Keycloak 设密页完成设密后自动移除该动作 |
| 忘记密码 | 用户在登录页自助 "Forgot Password"（需按 9.2 开启 reset-password 流），邮件重置——无需管理员介入 |
| 改名/换部门 | 只改 AD 名单 → 次日自动同步；紧急时手工运行脚本 |
| 复职 | 同一工号重新出现在名单 → status 置回 1 → KC enabled=true；停用超 180 天建议强制重设密（防旧密码泄露） |
| 停用后的在线会话 | 禁用后**立刻** `POST .../users/{id}/logout` 撤销 refresh token 与 SSO 会话。若漏调，access token 最长仍可能活过剩余寿命（默认 ≤15 分钟）。高敏感系统可再对每请求做 token introspection（※请核对） |
| 紧急停号（不等次日名单） | 见 7.6：按工号立刻把 `sso_user.status=0`、Keycloak 禁用并踢会话 |
| 工号复用（旧号给新人） | 6.4 的 GUID 冲突检查会中止并告警；人工确认后：停用旧行 + 新建新行（**绝不复用旧行**） |

### 7.4 幂等、重试与告警

- **幂等**：每步先查询后动作；同一批数据重复执行结果一致（建号前必查 username）。
- **重试**：对 KC 的 HTTP 调用失败（网络/5xx）按 10s/30s/60s 退避重试 3 次；整批失败则写 `sync_log(KC, ERROR)` 并告警，次日自动重跑补齐（因全量比对而自愈）。
- **告警**：`sync_log.status <> 'OK'` 时发邮件给项目负责人；告警邮件由脚本直接发送（不依赖监控平台）。
- **静默失效防线**：见风险 R1 与 14.2 的"同步新鲜度监控"——即使脚本不报错，只要 `sso_user.synced_at` 距今 > 26 小时也会触发告警（防止名单没到、脚本照跑的假成功）。

### 7.5 脚本骨架

完整可运行的 PowerShell 骨架见 [17.4 PowerShell 脚本骨架](#174-powershell-脚本骨架)。`Update-KcUser` 必须走 GET→改→PUT；禁用后必须 `.../logout`。

### 7.6 紧急停号（不等次日 06:00 名单）

IT 或部门当天通知“立刻停号”时，不要等夜间同步。

【客户自做】脚本 `C:\sso\scripts\disable_user_now.ps1 -EmployeeNo A0001`：

```
1. 校验工号存在于 sso_user
2. UPDATE sso_user SET status=0, updated_at=SYSUTCDATETIME()
3. GET Keycloak 用户（按 login_name）→ 对象.enabled=false → PUT 完整对象
4. POST /admin/realms/inalfa/users/{id}/logout
5. 写 sync_log(phase='KC_EMERGENCY', disabled=1, status='OK', message=工号+操作人)
6. 发告警邮件：已紧急停号，请各系统管理员按台账回收权限（登录已被挡住）
```

纪律：

- 紧急停号**只停认证**，不改 AD、不删 `sso_user` 行、不删各系统权限记录。
- 次日全量名单若仍把该人标为在职，MERGE 会把 `status` 置回 1 并复职——因此操作后必须**当天通知 IT 从名单去掉此人**，否则次日自动复活。脚本告警邮件里写明这一条。
- 误停恢复：IT 名单恢复在职后手工跑同步，或临时 `UPDATE status=1` 再跑 `sync_sso_to_keycloak.ps1`（停用超过 180 天仍走强制重设密）。

骨架见 [17.4.3 disable_user_now.ps1](#1743-disable_user_nowps1紧急停号)。

---

## 8. Keycloak 部署（Windows 原生）

**这一章解决什么问题：** 在不使用 Docker 的前提下，把 Keycloak 26.x 装成一台随服务器开机自启、连 SQL Server、走 HTTPS 的 Windows 服务，并具备备份/恢复能力。

> 名词解释：Keycloak 用 Java 编写，需要一个 JDK（Java 运行环境）才能跑；"NSSM"是一个把任意程序注册成 Windows 服务的小工具，作用相当于"让 Keycloak 像普通 Windows 服务一样开机自启、崩溃自动拉起"。

### 8.1 安装步骤总览

| 步骤 | 内容 | 责任方 |
|---|---|---|
| 1 | 安装 JDK 21（推荐 Eclipse Temurin 21 LTS）；配置 `JAVA_HOME` | 【客户自做】 |
| 2 | 下载 Keycloak 26.x 的 zip 分发版，解压到 `C:\keycloak` | 【客户自做】 |
| 3 | 【需 IT 配合】DNS 添加 A 记录：`sso.ap.inalfa.local` → 本服务器；防火墙放行 443（打到反代，不是直接打到 Keycloak） | 【需 IT 配合】 |
| 4 | 【需 IT 配合】签发 TLS 证书（通配符 `*.ap.inalfa.local` 或单域名 `sso.ap.inalfa.local`），安装到 IIS（或 nginx） | 【需 IT 配合】 |
| 5 | 创建 `keycloak` 数据库与专用 SQL 账号；放置 MSSQL JDBC 驱动 | 【客户自做】 |
| 6 | 配置 `conf\keycloak.conf`（监听 8443 + proxy-headers），库口令用环境变量，执行 build，配置管理员账号 | 【客户自做】 |
| 7 | 配置 IIS ARR（或 nginx）把 `sso.ap.inalfa.local` 反代到 `https://127.0.0.1:8443`（见 8.7） | 【客户自做】 |
| 8 | NSSM 注册 Windows 服务，设置开机自启与崩溃自动重启 | 【客户自做】 |
| 9 | 验证 `https://sso.ap.inalfa.local` 打开管理台、配置备份 | 【客户自做】 |

> JDK 版本说明：Keycloak 26.x 仍可在 JDK 17 上运行，但官方已将 JDK 17 列为弃用，**推荐直接安装 JDK 21 LTS**（也为将来升级 Keycloak 27+ 留出路，27 起要求 JDK 21）。※请核对所用版本的 Java 要求。

### 8.2 数据库准备（SQL Server）

```sql
-- 用 DBA/管理员账号在 IRSCNYTFINEREPORT.ap.inalfa.local 上执行
CREATE DATABASE keycloak;
GO
-- 专用登录，仅授予 keycloak 库读写；绝不用 sysadmin 或 sa
USE master;
CREATE LOGIN keycloak_svc WITH PASSWORD = '<DB_PWD>', CHECK_POLICY = ON;
ALTER SERVER ROLE sysadmin DROP MEMBER keycloak_svc; -- 确保未误加（新建账号默认无此角色，此句为保险）
GO
USE keycloak;
CREATE USER keycloak_svc FOR LOGIN keycloak_svc;
ALTER ROLE db_datareader ADD MEMBER keycloak_svc;
ALTER ROLE db_datawriter ADD MEMBER keycloak_svc;
ALTER ROLE db_ddladmin ADD MEMBER keycloak_svc;  -- 首次启动需建表
GO
```

JDBC 驱动：Keycloak 分发版**不自带** SQL Server 驱动。下载 Microsoft JDBC Driver for SQL Server（`mssql-jdbc-<版本>.jre11.jar`），放入 `C:\keycloak\providers\`，然后执行 `kc.bat build`（※请核对当前版本安装驱动的方式与支持的驱动版本）。

> 备选方案：若 MSSQL 兼容性验证受阻（如升级时 schema migration 报错），单机安装 PostgreSQL 并将 `db=postgres`，同时把 PostgreSQL 的数据目录纳入每日备份。**切换前先用 `kc.bat export` 导出 realm。**

### 8.3 keycloak.conf 样例

`C:\keycloak\conf\keycloak.conf`（完整样例与逐行说明见 [17.2 keycloak.conf 样例](#172-keycloakconf-样例)）：

```properties
db=mssql
db-url=jdbc:sqlserver://IRSCNYTFINEREPORT.ap.inalfa.local:1433;databaseName=keycloak;encrypt=true;trustServerCertificate=true
db-username=keycloak_svc
# 口令不要写在本文件：用 NSSM 环境变量 KC_DB_PASSWORD=<DB_PWD>

# hostname v2：填对外主机名，不要带 https://（※请按当前版本核对）
hostname=sso.ap.inalfa.local
proxy-headers=xforwarded
http-enabled=false
https-port=8443
https-certificate-file=C:/keycloak/certs/sso.crt
https-certificate-key-file=C:/keycloak/certs/sso.key
# 本机自签或从 IIS 导出的证书即可，浏览器看到的是反代上的企业证书

health-enabled=true
http-management-port=9000
# 管理/健康检查只绑本机（※键名请按版本核对，也可用防火墙只放行 127.0.0.1）
log=file
log-file=C:/keycloak/logs/keycloak.log
```

> `trustServerCertificate=true` 表示跳过校验 SQL Server 的 TLS 证书；若 DBA 能为 SQL Server 签发受信证书，改为 `encrypt=true;trustServerCertificate=false` 更安全。证书路径分隔符在配置中用 `/`。※以上所有配置键名请按当前版本官方文档核对（Keycloak 26 起 hostname 为 v2 模式）。
>
> NSSM 增加环境变量：`nssm set Keycloak AppEnvironmentExtra KC_DB_PASSWORD=<DB_PWD>`（实施时改为 DPAPI/受控方式注入，避免出现在命令历史）。

### 8.4 初始化与首次启动

```bat
cd C:\keycloak\bin
kc.bat build
```

创建初始管理员（Keycloak 26.x 方式，※请核对）：

```bat
set KC_BOOTSTRAP_ADMIN_USERNAME=kcadmin
set KC_BOOTSTRAP_ADMIN_PASSWORD=<KC_ADMIN_PWD>
bin\kc.bat bootstrap-admin user
```

> 该账号仅存在于 `master` 域，**只用于管理**，不参与业务登录（break-glass 见 14.4）。若 `bootstrap-admin` 命令在你的小版本中不存在，则用"首次从本机 localhost 访问控制台创建管理员"的方式（※请核对当前版本的初始管理员创建方式）。

### 8.5 NSSM 注册 Windows 服务

```bat
nssm install Keycloak "C:\keycloak\bin\kc.bat" "start --optimized"
nssm set Keycloak AppDirectory C:\keycloak\bin
nssm set Keycloak DisplayName "Keycloak SSO"
nssm set Keycloak Start SERVICE_AUTO_START
nssm set Keycloak AppStdout C:\keycloak\logs\service-out.log
nssm set Keycloak AppStderr C:\keycloak\logs\service-err.log
nssm set Keycloak AppRotateFiles 1
nssm set Keycloak AppRotateBytes 10485760
nssm set Keycloak AppEnvironmentExtra KC_DB_PASSWORD=<DB_PWD>
nssm start Keycloak
```

- `start --optimized` 表示"直接用 build 好的配置启动"，服务启动更快、不重复构建。
- 若环境的 PowerShell 执行策略/服务账户导致 kc.bat 启动异常，可改用 **WinSW**（把可执行与配置放同一 XML 描述文件），效果等价。
- NSSM 包装 `kc.bat` 若启动失败，改为：`nssm install Keycloak C:\Windows\System32\cmd.exe "/c C:\keycloak\bin\kc.bat start --optimized"`。
- 验证：先 `https://127.0.0.1:8443`（本机忽略证书）能打开；再经反代 `https://sso.ap.inalfa.local` 能打开；重启服务器后服务自动运行。

### 8.6 备份与恢复（部署阶段就要做）

| 对象 | 备份内容 | 方式 | 频率 |
|---|---|---|---|
| Keycloak 配置 | `conf\` 目录 + `providers\` 里的驱动清单 | 文件备份（纳入服务器既有备份） | 每日 |
| Realm 数据（用户/客户端/策略） | `kc.bat export --dir C:\sso\kc-export` | 计划任务导出 JSON | 每周 + 每次大改后 |
| 数据库 | `keycloak` 库与 `sso` 库 | SQL Server 完整备份（沿用企业既有 SQL 备份作业） | 每日 |

恢复演练（至少做一次）：新目录解压同版本 Keycloak → 恢复 conf/providers → `kc.bat import`（或直接恢复数据库）→ 起服务验证登录。※export/import 的具体参数请按当前版本核对。

### 8.7 前置反代（解决与帆软/IIS 的 443 冲突）

**原则：** 本机对外只开放 443，由现有 IIS 统一持证。Keycloak 只监听本机 8443，防火墙不把 8443 对网段开放。

推荐顺序：① 已有 IIS → 装 **ARR + URL Rewrite**；② 没有 IIS 或 ARR 规则调不通 → nginx Windows 版（与第 11 章网关可共用）。

#### 8.7.1 IIS ARR（推荐，因帆软多半已在 IIS）

1. 安装 IIS、ARR、URL Rewrite。开启 ARR 的 `preserveHostHeader`、`reverse rewrite host in response headers`（※按微软文档核对）。
2. 站点绑定：`sso.ap.inalfa.local:443` + 企业证书（可与其它站点共用通配符证书，靠 Host 头分流）。
3. 服务器场指向 `https://127.0.0.1:8443`。若 Keycloak 用自签证书，ARR 需允许忽略后端证书错误（仅限回环地址）。
4. 传入请求头（ARR 会带一部分；缺的用 URL Rewrite 补）：

| 头 | 值 |
|---|---|
| `Host` | `sso.ap.inalfa.local`（保留对外主机名，不要改成 127.0.0.1） |
| `X-Forwarded-For` | 客户端 IP |
| `X-Forwarded-Proto` | `https` |
| `X-Forwarded-Host` | `sso.ap.inalfa.local` |

5. 健康检查仍用本机 `http://127.0.0.1:9000/health`，不要把管理端口映射到 443。

#### 8.7.2 nginx 替代（与 11.2 可同一进程）

```nginx
server {
    listen 443 ssl;
    server_name sso.ap.inalfa.local;
    ssl_certificate     C:/nginx/certs/sso.crt;
    ssl_certificate_key C:/nginx/certs/sso.key;

    location / {
        proxy_pass https://127.0.0.1:8443;
        proxy_ssl_verify off;                 # 仅限回环 + 自签
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host  $host;
        proxy_buffer_size          128k;
        proxy_buffers              4 256k;
        proxy_busy_buffers_size    256k;
    }
}
```

> 若 443 已被 IIS 占用，**不要再让 nginx 听 443**。要么全部走 IIS ARR，要么把帆软也迁到 nginx——二选一，禁止两个进程抢同一端口。

#### 8.7.3 验收

- [ ] `https://sso.ap.inalfa.local` 证书是企业证书，不是 Keycloak 自签
- [ ] 登录跳转的 redirect 主机名是 `sso.ap.inalfa.local` 而不是 `127.0.0.1` 或 `https://https://...` 双写
- [ ] 帆软原站点 `https://<原主机>` 443 仍然可开，互不影响
- [ ] 从其它机器访问 `https://<服务器IP>:8443` 应失败（未对网段开放）

---

## 9. Keycloak 配置

**这一章解决什么问题：** 把 Keycloak 从"装好了"变成"配置得安全又省心"：一个业务 realm、合理的密码策略与会话时长、防暴力破解、可用的邮件、留得下审计记录、统一的 client 命名。

### 9.1 Realm 规划

| Realm | 用途 | 说明 |
|---|---|---|
| `master` | 管理员专用 | 仅 `kcadmin` 等管理账号；不建业务用户 |
| `inalfa` | 业务登录域 | 全部业务用户、业务系统 client、SMTP、密码策略都在这里 |

> 为什么单 realm：<50 人、无独立法人/子公司隔离需求，一个 realm 管理成本最低。将来若有隔离需求再拆分。

### 9.2 认证流（登录策略）

| 配置项 | 建议值 | 位置 |
|---|---|---|
| 密码策略 | 长度≥10；不包含用户名；不强制定期过期（<50 人环境强过期会催生"密码+1"坏习惯，可一年评估一次） | Realm Settings → Authentication → Policies（※请核对） |
| 注册自建账号 | 关闭（用户只能来自同步） | Realm Settings → Login：User registration OFF |
| 忘记密码 | 开启 | Realm Settings → Login：Forgot password ON（配套 reset-credential 认证流默认启用） |
| 记住我 | 按需开启 | Realm Settings → Login |
| 邮箱必须验证 | 建议开启（Verify Email 动作加入首次登录流或作为 required action） | Authentication → Required actions（※请核对） |
| 暴力破解防护 | 开启：5 次失败锁定，等待 15 分钟（对内网系统可先放宽观察） | Realm Settings → Authentication → Brute force detection（※请核对） |

### 9.3 会话与令牌时长（2026-11-09 现场决定）

| 参数 | 建议值 | 效果 |
|---|---|---|
| SSO Session Idle | **1 天（86400 秒）** | 1 天无操作需重新登录（2026-11-09 现场决定，覆盖原 8 小时，原值作废；加长不踢已登录用户） |
| SSO Session Max | **7 天（604800 秒）** | 最长 7 天强制重登（同上，覆盖原 12 小时） |
| Access Token Lifespan | 15 分钟 | 业务系统短期凭证 |
| Refresh Token Max Reuse | 0（默认，刷新轮换） | 安全性优先 |
| Offline Session | 默认关闭 | 内部系统无长离线需求 |

### 9.4 登录与审计日志

| 项 | 建议 |
|---|---|
| User events（登录事件） | 开启，保存 90 天（存 `keycloak` 库）；用于追查"谁登录失败次数异常" |
| Admin events（管理操作） | 开启，保存 180 天 |
| 事件导出 | 每月用脚本从库中导出 CSV 归档（90/180 天后库内自动清理） |
※事件存储参数请按当前版本核对（部分版本需启用事件存储能力）。

### 9.5 SMTP（企业邮箱）

【现场已确定】使用正式发信账号 `ap_sso@inalfa.com`（仅用于发送设密/重置/告警邮件）。在 Realm `inalfa` → Realm Settings → Email 配置（以交底书 §9.5 为准）：

| 参数 | 值 |
|---|---|
| Host | `172.19.253.10` |
| Port | `25` |
| From | `ap_sso@inalfa.com` |
| From Display Name | `Inalfa AME系统统一身份认证` |
| Authentication | **OFF**（内网无认证中继） |
| Enable StartTLS | **OFF**（当前为明文中继；若后续网关启用 STARTTLS 改 ON 后重新实测） |
| Enable SSL | **OFF** |

配置后点 **Test connection**，并**实际发一封验证信**——判据是「确实收到信」，Test connection 成功不算。SMTP 不通 = 首次设密全部卡死，务必在上线前验证（并在 14.2 加监控）。

### 9.6 Client 命名规范与安全基线

| 规范 | 内容 |
|---|---|
| 命名 | `<系统代码>-<环境>`，如 `erp-prod`、`finereport-prod`、`mes-test`；客户端描述里写中文系统全名 |
| 类型 | 机密客户端（confidential）+ Client Secret；禁止 public + implicit flow |
| Redirect URI | 精确白名单（如 `https://erp.ap.inalfa.local/login/oauth2/code/*`），禁止 `*` 整域通配 |
| Web Origins | 按需最小化 |
| 专用客户端 | `sync-client`（仅服务账号，7.1）；`account` 客户端保持启用（邀请设密邮件落地） |
| 准入组 | 每个要自动建档的业务系统一个组：`app-<系统代码>`，如 `app-erp`、`app-finereport`。用户不在组内则该系统拒绝登录/拒绝自动建档。组**不是**细粒度角色。各 OIDC client 增加 Group Membership mapper，把组名放进 token（※token claim 名按版本核对，建议 `groups`） |

> 全局登出（SLO）不做强承诺：用户在一个系统点“退出”只清该系统 Cookie 和（若接入了 end_session）Keycloak SSO 会话；其它系统可能仍有自己的会话，直到空闲超时。内网接受这一边界，不单独立项做 SLO。

---

## 10. 各系统接入模板

**这一章解决什么问题：** 先用接入矩阵判定每个系统走哪条路，再给可改造系统一份能照抄的协议配置。

### 10.0 接入矩阵（实施前逐系统填一行）

不要默认“都能 OIDC”。国内商业软件经常只认 SAML 或 LDAP。Keycloak 对 OIDC 与 SAML 都是一等公民。

| 系统 | 架构/厂商 | 推荐路径 | 匹配键 | 对照表 | 准入组 | 权限落点 | 负责人 | 状态 |
|---|---|---|---|---|---|---|---|---|
| （例）自研 ERP | ASP.NET Core | OIDC 授权码 | `preferred_username` → 本系统 username，没有则查 `sso_user_map` | 按需 | `app-erp` | 本系统角色 | | 待接入 |
| （例）FineReport 11 | 帆软 | P0 书面确认：OAuth / HTTP 头 / LDAP 三选一 | 用户名或对照表 | 极可能需要 | `app-finereport` | FineReport 目录 | 厂商 | **第 1 周确认** |
| （例）只会 LDAP 的老系统 | 商业 | 网关头 → 不行再 A' 或遗留 | `X-Forwarded-User` | 按需 | 网关侧也可按组过滤 | 本系统 | 厂商 | |
| （例）完全不能改 | — | 本地账号 + 台账标注“遗留” | — | — | — | 本系统 | | 不纳入 SSO |

判定顺序（每个系统只走一条）：

```
1. 有源码 / 明确支持 OIDC     → 第 10.1–10.5
2. 只支持 SAML 2.0            → 10.8（Keycloak 建 SAML client）
3. 支持 HTTP 头 / 集成认证    → 第 11 章方向一（网关）
4. 只支持 LDAP bind           → 第 11 章决策表（网关否决后再考虑 A'）
5. 以上皆否                   → 遗留本地账号，写入台账，设切换截止日期
```

通用约定（OIDC）：每个系统一个独立 client；回调地址精确白名单；scope 用 `openid profile email`；业务系统**只验证身份，不把 Keycloak realm 角色当业务权限**。用户匹配顺序：`sso_user_map.local_username` → 否则 `login_name`。登录时校验用户属于 `app-<系统代码>` 组（JWT 的 `groups` claim 或 userinfo），不在组内则拒绝并提示找管理员开通准入。

所有 OIDC 模板共用同一组 Keycloak 端点：

```
Issuer / Discovery:  https://sso.ap.inalfa.local/realms/inalfa/.well-known/openid-configuration
授权端点:            https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/auth
令牌端点:            https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/token
用户信息端点:        https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/userinfo
JWKS:                https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/certs
登出:                https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/logout
```

### 10.1 Spring Boot（自研 Web 常见）

```yaml
# application.yml（spring-security-oauth2-client）
spring:
  security:
    oauth2:
      client:
        registration:
          erp:
            client-id: erp-prod
            client-secret: <CLIENT_SECRET>
            scope: openid,profile,email
            redirect-uri: "https://erp.ap.inalfa.local/login/oauth2/code/{registrationId}"
        provider:
          erp:
            issuer-uri: https://sso.ap.inalfa.local/realms/inalfa
```

要点：以 `issuer-uri` 自动发现端点；登录成功后以 `principal.getName()`（默认 = Keycloak username = login_name）匹配本系统权限表；登出时调用 KC 的 end_session 端点清 SSO 会话。

### 10.2 Django

```python
# pip install mozilla-django-oidc
OIDC_RP_CLIENT_ID = "erp-prod"
OIDC_RP_CLIENT_SECRET = "<CLIENT_SECRET>"
OIDC_OP_AUTHORIZATION_ENDPOINT = "https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/auth"
OIDC_OP_TOKEN_ENDPOINT = "https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/token"
OIDC_OP_USER_ENDPOINT = "https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/userinfo"
OIDC_OP_JWKS_ENDPOINT = "https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/certs"
# 登录用户名映射：Keycloak username → 本系统 user.username
```

要点：首次登录时按 `preferred_username` 自动在本系统建档（只建身份记录，不给权限，权限由管理员按台账配置）。

### 10.3 Node.js（Express）

```js
// npm install openid-client express-session
// 使用 openid-client 的 Issuer.discover(issuerUri) 后生成 client，
// 采用 authorization_code flow；回调中 tokens.claims().preferred_username 即 login_name。
// 会话用 express-session + Cookie(session 模式)，登出时重定向 KC logout 端点。
```

（※具体 API 以所用 openid-client 大版本文档为准，v5 与 v6 的接口有差异。）

### 10.4 .NET（ASP.NET Core）

```csharp
builder.Services.AddAuthentication(options => {
        options.DefaultScheme = CookieAuthenticationDefaults.AuthenticationScheme;
        options.DefaultChallengeScheme = OpenIdConnectDefaults.AuthenticationScheme;
    })
    .AddCookie()
    .AddOpenIdConnect(options => {
        options.Authority = "https://sso.ap.inalfa.local/realms/inalfa";
        options.ClientId = "erp-prod";
        options.ClientSecret = "<CLIENT_SECRET>";
        options.ResponseType = OpenIdConnectResponseType.Code;
        options.SaveTokens = true;
        options.GetClaimsFromUserInfoEndpoint = true;
        options.Scope.Add("openid"); options.Scope.Add("profile"); options.Scope.Add("email");
    });
```

要点：IIS/反代部署时启用 `ForwardedHeaders` 中间件，否则回调地址可能拼成 http。

### 10.5 PHP

用成熟库（如 `openid-connect-php` / league/oauth2-client 的 OIDC 扩展）实现授权码流程，配置同上四个端点；不要手写签名验证——用库提供的 JWKS 验证 id_token。

### 10.6 帆软 FineReport 11（重点）

FineReport 11 的认证对接能力随版本和小版本变化较快。**P0（第 1 周）就必须拿到帆软支持的书面确认**，不要等到 P4。以下按优先级三条路径：

| 优先级 | 路径 | 说明 |
|---|---|---|
| 1 | OAuth2/OIDC 集成认证 | FR11 支持对接 OAuth 认证（官方提供对应认证方式/插件，名称随版本变化）。在 FR 平台配置 Keycloak 的 authorize/token/userinfo 端点与 `finereport-prod` client。用户匹配键 = 用户名。**这是唯一正路，务必先与帆软确认可用性** |
| 2 | 网关注入 + HTTP 集成认证 | 若帆软确认支持"信任 HTTP 头/集成认证"，可复用第 11 章方向一的网关（oauth2-proxy）注入用户头实现自动登录。FR 侧需保留一份用户名单（可沿用现有 `fine_user` 的同步或手工维护） |
| 3 | 变体 A'：LDAP 门面 | 若以上皆不可行且 FR 只认 LDAP，走 11.3 的 AD LDS 门面，FR 从门面同步用户并做 LDAP 认证 |

> 现有 `fine_user` 表已从 AD 同步，人员名单与 `sso_user` 高度一致，这为 FR 侧的"用户名匹配"降低了难度；但 `fine_user` 归帆软管辖，**不要**在其上叠加自建逻辑。

### 10.7 通用兜底：oauth2-proxy 网关（无法改代码的系统）

适用于：任何支持"从 HTTP 头 / REMOTE_USER 取身份"的 CGI/传统 Web 应用，或完全无法改造但部署在 nginx/IIS 之后的系统。配置细节与安全要求统一见第 11 章方向一。

### 10.8 SAML 2.0（商业软件只认 SAML 时）

Keycloak 为该系统建 **SAML** client（不是 OpenID Connect client）：

| 项 | 做法 |
|---|---|
| Client ID | 对方要求的 Entity ID（常为系统自己的 ACS URL 或 URN） |
| 协议 | SAML，关闭 OIDC |
| ACS URL | 对方提供的 Assertion Consumer Service，精确填写 |
| NameID | 用 `username` 或 `email`，与对照表一致 |
| 属性 | 按厂商文档放 `employee_no` / `email`；**不要**把业务角色当 SAML Attribute 下发（仍 ADR-4） |
| 元数据 | Keycloak `https://sso.ap.inalfa.local/realms/inalfa/protocol/saml/descriptor` 交给厂商导入 |

※各厂商对签名算法（RSA-SHA256）、是否要加密断言、时钟偏差要求不同，以对方文档为准。能 OIDC 的不要主动选 SAML。

---

## 11. LDAP-only 系统兼容（本方案最难的题）

**这一章解决什么问题：** 回答"Keycloak 不能直接当 LDAP 服务器用，那只会说 LDAP 的老系统怎么办"。先给结论，再给两条方向的完整做法、决策表和各自的局限。

### 11.1 先说结论

> **Keycloak 是 OIDC 提供方，不是 LDAP 服务器**——它不能接受 LDAP bind（目录绑定认证）请求，这一点没有变通配置能改变。所以"LDAP-only 系统"有三条现实出路：
>
> - **方向一（推荐，LDAP-only ≤2 个）**：不让它说 LDAP，在它前面放一个**网关**，由网关完成 Keycloak 登录，再把"已认证的用户名"通过 HTTP 请求头传给系统。前提：该系统支持从请求头/集成认证取身份（或厂商能小改）。
> - **方向二（LDAP-only ≥3 个时）**：真的搭一个 LDAP 服务器（门面），把 `sso_user` 喂进去。此时必须回答"密码权威在谁手里"——这会派生出**方案 A 的变体 A'**，Keycloak 不再是纯粹的密码持有者（见 11.4）。
> - **兜底**：系统继续用本地账号密码（不改），仅纳入台账管理。这不丢人——改造价值 < 改造风险时就该不动。

### 11.2 方向一：网关前置认证 + 注入用户头（推荐）

**原理**：用户先被网关重定向到 Keycloak 登录；登录成功后，网关把用户名放进 HTTP 头（如 `X-Forwarded-User`）转发给后端系统；系统信任该头即完成"自动登录"。

**组件**：oauth2-proxy（OIDC 反向代理，单文件可执行，Windows 可原生运行）+ nginx（Windows 版）或 IIS ARR。oauth2-proxy 本身也可直接作为反代使用，nginx/ARR 负责分流多个老系统。

#### 11.2.1 安全要求（每一条都不能省）

| # | 要求 | 不做到的后果 |
|---|---|---|
| 1 | **注入前清除同名头**：网关把来自客户端请求中的 `X-Forwarded-User` 等身份头先置空，再写入认证结果 | 攻击者直连网关时伪造 `X-Forwarded-User: boss` 冒充任何人 |
| 2 | **后端仅接受来自网关的请求**：防火墙把后端应用端口封为仅网关可达；或后端校验网关注入的共享密头（如 `X-Auth-Gateway: <随机长串>`） | 绕过网关直连后端端口，注入任意身份头 |
| 3 | **首次自动建号 + 权限默认最低**：网关传入的 login_name 在后端系统中不存在时自动建档（无任何权限），授权由管理员按台账执行 | 自动建号即给高权限 |
| 4 | **身份头仅在内网 HTTPS 链路上传输**；网关到后端也在内网 | 头在传输中被窃听/篡改 |
| 5 | **oauth2-proxy 用机密客户端**，cookie 加密密钥妥善保管 | 会话被伪造 |

#### 11.2.2 nginx + oauth2-proxy 配置样例

oauth2-proxy 侧（节选，`--provider=oidc`，※参数名请按所用版本核对）：

```bat
oauth2-proxy.exe ^
  --provider oidc ^
  --client-id gateway-prod ^
  --client-secret <CLIENT_SECRET> ^
  --oidc-issuer-url https://sso.ap.inalfa.local/realms/inalfa ^
  --cookie-secret <COOKIE_SECRET_16_32字节随机> ^
  --redirect-url https://apps.ap.inalfa.local/oauth2/callback ^
  --email-domain * ^
  --insecure-oidc-skip-issuer-verification=false ^
  --skip-oidc-discovery=false ^
  --oidc-email-claim email ^
  --user-id-claim preferred_username ^
  --pass-authorization-header ^
  --set-xauthrequest
```

nginx 侧（清除头 → 认证 → 注入头）：

```nginx
server {
    listen 443 ssl;
    server_name apps.ap.inalfa.local;
    ssl_certificate     C:/nginx/certs/apps.crt;
    ssl_certificate_key C:/nginx/certs/apps.key;

    # 后端系统的位置：先内部认证，再注入身份
    location /legacy1/ {
        # 要求 1：先清除客户端可能伪造的同名头
        proxy_set_header X-Forwarded-User "";
        proxy_set_header X-Auth-Gateway "";

        auth_request /_oauth2_auth;                     # 到 oauth2-proxy 验证会话
        error_page 401 =302 /oauth2/signin;             # 未登录跳 Keycloak

        auth_request_set $auth_user $upstream_http_x_forwarded_user;
        proxy_set_header X-Forwarded-User $auth_user;   # 注入真实身份
        proxy_set_header X-Auth-Gateway "<随机长串>";     # 共享密头（后端校验）

        proxy_pass http://127.0.0.1:8081/;              # 后端仅监听 127.0.0.1
    }

    location = /_oauth2_auth {
        internal;
        proxy_pass http://127.0.0.1:4180/oauth2/auth;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
    }
    location /oauth2/ { proxy_pass http://127.0.0.1:4180; }
}
```

> oauth2-proxy 默认常按 **email** 当用户标识。名单缺邮箱或邮箱未验证时会直接 403。必须把用户标识改成 `preferred_username`（上表 `--user-id-claim`），并确认不要启用“必须验证邮箱”一类开关（※参数名按版本核对）。
>
> IIS ARR 替代：ARR + URL Rewrite 也能做反向代理与改写请求头，但"auth_request 式认证"没有原生等价物，需要用 ARR 的请求路由规则 + oauth2-proxy 的 forward-auth 模式拼装，复杂度更高。**业务站点若已在 IIS，443 入口用 ARR（8.7）；网关认证这一跳仍优先 nginx/oauth2-proxy 本机端口，避免和 ARR 规则缠在一起。**

#### 11.2.3 方向一的局限（如实说明）

| 局限 | 影响 |
|---|---|
| 要求系统"认请求头" | 纯 LDAP-only（只会 bind 目录）且不认头的系统，此路不通，只能回方向二或兜底 |
| 系统内仍要有一份用户名单 | 头只解决"登录"，系统的用户表/权限还要维护（首次自动建号 + 台账授权缓解） |
| 每个系统多一层代理 | URL 前缀/路径重写可能踩应用的坑，需要逐系统联调 |
| 登出是"网关会话登出" | 网关清了会话，但 Keycloak SSO 会话仍在——下次访问免密直达。可接受（内网），但要知晓 |

### 11.3 方向二：LDAP 门面（变体 A' 的基础）

**原理**：搭一台真正的 LDAP 服务器（"门面"，即给老系统看的假 AD），`sso_user` 每日同步喂入；老系统照常配 LDAP bind。**先做门面，密码权威问题在 11.4 单独说透。**

#### 11.3.1 门面选型对比

| 选型 | Windows 原生可行性 | 安装复杂度 | 运维成本 | 组(Group)支持 | 结论 |
|---|---|---|---|---|---|
| **AD LDS**（轻量目录服务） | ✅ Windows Server 内置角色，微软官方支持 | 中（角色安装 + 实例向导） | 低（服务化，有图形管理工具 ldp.exe/ADSI Edit） | ✅ 支持 group（groupOfNames 类） | **首选** |
| OpenLDAP | ❌ 无官方 Windows 版；第三方移植老旧 | 高（编译/移植） | 高（无支持） | ✅ | 不推荐 |
| LLDAP（Rust 单文件） | ⚠️ 有社区 Windows 构建，但主要面向 Linux/Docker 分发 | 低 | 中（项目新，Windows 构建非一等公民） | ✅ | Docker 被禁用后不推荐；※实施时确认其 Windows 构建可用性 |
| 复用真 AD | — | — | — | — | IT 已拒绝，不可行 |

> 结论：**门面 = AD LDS**。它跑在 Windows Server 上、由服务化管理，符合"不引入 Docker"约束；且与现有 AD 同源，IT 接受度最高。安装需【需 IT 配合】（服务器管理员权限）。

#### 11.3.2 目录结构设计（DN 规划）

```
分区(Naming Context): CN=SsoCatalog（实例向导中创建，例）
用户 OU:  OU=Users,OU=Sso,CN=SsoCatalog
  每个用户: CN=<display_name>,OU=Users,OU=Sso,CN=SsoCatalog
            属性: uid=<login_name>（或 sAMAccountName 兼容类）、mail、displayName、employeeNumber
组 OU:    OU=Groups,OU=Sso,CN=SsoCatalog
  每个系统一个组: CN=fr-users,OU=Groups,OU=Sso,CN=SsoCatalog   （例：帆软的准入组）
绑定账号: CN=svc-ldap-reader,OU=Users,OU=Sso,CN=SsoCatalog   （各系统做 bind 的只读账号）
```

- 用户条目类：`user` + `organizationalPerson` + 系统要求的类（按目标系统要求，※核对各系统 LDAP Schema 要求）。
- 组：仅当某老系统"按组过滤准入"时才建组；`<50 人`规模下能不建就不建（回到"权限留各系统"原则）。
- 停用：同步脚本写 `msDS-UserAccountDisabled=TRUE`（AD LDS 用该属性禁用，※请核对）。

#### 11.3.3 数据同步方式

每日第 3 个脚本（在 Keycloak 同步之后）：读 `sso_user` → 用 PowerShell（`System.DirectoryServices.Protocols` / ADSI）对 AD LDS 做 LDAP add/replace/disable。幂等逻辑与第 7 章相同：先查 uid，存在则改，不存在则建，名单外的人禁用。初始密码的写入方式决定"密码权威"归属 → 见 11.4。

#### 11.3.4 各系统 LDAP 绑定参数模板

| 参数 | 模板值 |
|---|---|
| LDAP URL | `ldaps://<ADLDS主机名>.ap.inalfa.local:636`（强烈要求 LDAPS；明文 389 仅限初始调试） |
| Bind DN | `CN=svc-ldap-reader,OU=Users,OU=Sso,CN=SsoCatalog` |
| Bind Credential | `<LDAP_BIND_PWD>` |
| Users DN | `OU=Users,OU=Sso,CN=SsoCatalog` |
| 用户过滤 | `(&(objectClass=user)(uid=<username>))`（按各系统语法调整） |

#### 11.3.5 Keycloak User Federation 配置（若走 A'）

在 Keycloak 中把 AD LDS 配为 User Federation（※以下每项的准确名称按当前版本管理控制台核对）：

| 配置项 | 值 | 说明 |
|---|---|---|
| Connection URL | `ldaps://<ADLDS主机>:636` | 加密连接 |
| Bind DN | `CN=svc-kc-fed,OU=Users,OU=Sso,CN=SsoCatalog` | Keycloak 专用只读绑定账号（与系统的 reader 分开） |
| Bind Credential | `<LDAP_BIND_PWD>` | |
| Users DN | `OU=Users,OU=Sso,CN=SsoCatalog` | |
| Username LDAP attribute | `uid` | |
| RDN LDAP attribute | `uid` | |
| UUID LDAP attribute | `objectGUID` | AD LDS 的对象唯一标识 |
| User Object Classes | `person, organizationalPerson, user` | 按目录实际类填 |
| Edit Mode | `READ_ONLY` | 见 11.4 的选择分析 |
| Import Users | ON | 首次把门面用户导入 Keycloak 库 |
| Sync Period（定期全量同步） | 86400 秒（每日） | 与脚本节奏互补；也可改为手动触发 |
| 组映射 | 建 Group Mapper：Groups DN=`OU=Groups,OU=Sso,CN=SsoCatalog`，组名属性=`cn`，成员属性=`member` | 仅当使用组时配置 |

### 11.4 密码权威：方案 A 的变体 A'（必须想清楚再动手）

引入门面后必然出现的问题：**用户密码到底存在哪、谁来改？** 两条子路线：

#### A'-1：门面持有密码（Keycloak 联邦 Edit Mode=READ_ONLY）

密码由门面（AD LDS）持有，Keycloak 只读联邦、不自管密码。**这实际上推翻了"Keycloak 自管密码"的原设计，成为变体 A'。** 具体影响必须逐条接受：

| 影响 | 说明 |
|---|---|
| 改密入口在哪 | Keycloak 登录页的"忘记密码/自助改密"**失效**（READ_ONLY 不允许 Keycloak 写目录）。改密要么由管理员在 AD LDS 侧重置（ldp.exe / PowerShell ADSI 写 `userPassword`），要么自建一个受保护的改密小工具 |
| 密码策略在哪配 | 不再是 Keycloak 策略页；AD LDS 自身的密码策略能力**弱于真 AD**（※请核对 AD LDS 密码策略/密码过滤器的支持情况），复杂度与锁定策略可能要靠脚本自检兜底 |
| 是否双写 | 若同时还有别的写入方（如手工在 Keycloak 建用户）就会双写漂移。纪律：**门面是密码唯一写入口，Keycloak 中不建任何本地用户** |
| 首次设密 | 第 7 章的 execute-actions-email **失效**；改为：同步脚本在门面生成初始密码 → 走自建邮件/IM 通知用户（初始密码经安全通道传递，强制首改） |
| 与方案 A 的代价对比 | 多一台 AD LDS 实例要运维；同步脚本多一条链路；"自管密码、自助重置"的体验丧失 |

**结论：只有当 LDAP-only 且"只认 bind"的系统 ≥3 个、且网关方向一被逐一否决时，才接受 A'-1。**

#### A'-2：坚持 Keycloak 自管密码 → 门面只能是只读目录

门面不存有效密码（同步时写入随机值并禁用），Keycloak 仍自管密码。此时：

- Keycloak 联邦 Edit Mode 仍可 READ_ONLY（目录只当通讯录）；
- **但老系统做 LDAP bind 时，用户在 Keycloak 设的密码在门面里不存在 → bind 永远失败**；
- 结论：A'-2 下 LDAP-only 系统依旧无法完成认证，**唯一出路回到方向一（网关注入）**。

> 一句话：**"Keycloak 自管密码"和"老系统直接 LDAP bind"二者不可兼得。** 要兼得，密码必须搬到门面（A'-1，变体 A'）；不搬，就上网关（方向一）。这是本方案最重要的取舍。

（补充说明：Keycloak 的 LDAP Federation 也存在 Edit Mode=WRITABLE 的模式，理论上允许 Keycloak 把密码改动写回 LDAP。但它引入"Keycloak 与门面双向写密码"的复杂度，且对 AD LDS 的密码写入有协议前提（※请核对 AD LDS 是否支持 LDAP 修改密码扩展操作及 Keycloak 对该模式在 MSSQL/AD LDS 组合下的官方支持度）。本文不推荐，列此仅为完整。）

#### 11.4.1 决策表

| 你的情况 | 推荐选择 |
|---|---|
| LDAP-only / 无法改造的系统 ≤2 个 | **方向一**：网关注入（每系统一个 location，成本最低） |
| LDAP-only 系统有 1–2 个，但厂商连"认请求头"都拒绝 | 兜底：本地账号不动 + 台账管理；把厂商改造列入远期 |
| LDAP-only 系统 ≥3 个，且多数只认 LDAP bind | **变体 A'-1**：AD LDS 门面 + Keycloak READ_ONLY 联邦（放弃自管密码） |
| LDAP-only 系统 ≥3 个，但其中可改造的先改 OIDC，剩下 ≤2 个 | 分批：可改的走第 10 章；剩下的走方向一 |
| 系统有源码/自研 | 一律第 10 章 OIDC 直连，不经过网关/门面 |
| 运维能力弱、无人熟悉 LDAP | 避免方向二（AD LDS 也是要养的）；倾向方向一/兜底 |

#### 11.4.2 两条方向的风险对照

| 风险 | 方向一（网关） | 方向二（门面 A'） |
|---|---|---|
| 身份伪造 | 有（头伪造/绕过网关），靠 11.2.1 五条要求压制 | 无（标准 bind） |
| 密码体系分裂 | 无（单点 Keycloak） | 有（密码搬到门面，自管密码失效） |
| 新增运维对象 | 网关（nginx+oauth2-proxy，注册服务） | AD LDS 实例 + 第 3 条同步链路 |
| 系统侧改动 | 要求认头 | 要求配 LDAP（多数本来就会） |
| 覆盖不了的死角 | 只认 bind 且不认头的系统 | ——（凡认 LDAP 的都能接） |

---

## 12. 权限与台账

**这一章解决什么问题：** 在"不集中授权"的前提下，让权限管理仍然可控可查，入职/离职/调岗有固定流程。

### 12.1 台账设计（极简，Excel 或 sso 库一张表均可）

推荐直接放 `sso` 库（可查询、可导出）：

```sql
CREATE TABLE dbo.perm_ledger (
    id           BIGINT IDENTITY(1,1) CONSTRAINT PK_perm_ledger PRIMARY KEY,
    employee_no  NVARCHAR(32)  NOT NULL,     -- 关联 sso_user.employee_no
    system_code  NVARCHAR(32)  NOT NULL,     -- erp / finereport / mes ...
    role_name    NVARCHAR(64)  NOT NULL,     -- 系统内角色（文本即可，不追求结构化）
    granted_by   NVARCHAR(64)  NOT NULL,     -- 授予人（系统管理员）
    granted_at   DATE          NOT NULL,
    revoked_at   DATE          NULL,         -- 回收日期；NULL=仍有效
    remark       NVARCHAR(200) NULL
);
CREATE INDEX IX_perm_ledger_emp   ON dbo.perm_ledger (employee_no);
CREATE INDEX IX_perm_ledger_sys   ON dbo.perm_ledger (system_code, revoked_at);
GO
```

维护方式：系统管理员每次授权/回收后登记（每季度对账一次：导出各系统权限截图与台账比对）。若嫌 SQL 麻烦，用 Excel 放在受控共享目录，字段同上。

### 12.2 三个流程

| 流程 | 步骤 | 责任方 |
|---|---|---|
| **入职** | ① IT 名单出现新人 → 次日自动建号+邀请邮件；② 各系统管理员按台账为新人在系统内配角色并登记；③ 通知用户完成首次设密 | ①自动；②【各系统管理员】；③【客户自做】 |
| **调岗** | ① 名单部门变化 → 同步；② 原系统管理员按台账回收旧角色、新系统管理员授予新角色（系统间不做自动迁移）；③ 登记台账 | ①自动；②③【各系统管理员】 |
| **离职** | ① 名单置 0 → 当日 Keycloak 禁用（所有已接入系统随即失效）；② 各系统管理员按台账回收系统内账号/权限并登记 `revoked_at`；③ 每季度对账清理"离职残留权限" | ①自动；②③【各系统管理员】 |

> 关键认知：Keycloak 禁用挡住了"登录"，但挡不住"系统内残留的历史权限记录"。台账的 `revoked_at` 就是为此存在的——这是方案 A 的已知边界，不美化。

### 12.3 准入组与对照表在三个流程里怎么用

| 步骤 | 入职 | 调岗 | 离职/紧急停号 |
|---|---|---|---|
| 对照表 | 新员工默认不写（用户名=login_name） | 一般不动 | 保留行（历史对账） |
| Keycloak 组 | 按台账加入 `app-*` | 移出旧系统组、加入新系统组 | 可不清组——账号已 disabled；季度对账时再清 |
| 系统内角色 | 管理员配置 + 登记台账 | 回收旧角色、授新角色 | 登记 `revoked_at`；紧急停号只保证当天登不进去 |

---

## 13. 安全设计

**这一章解决什么问题：** 把这套系统本身看护好：传输加密、账号最小权限、密钥保管、MFA、日志留存与攻击面清单。

### 13.1 传输与端口

| 项 | 要求 |
|---|---|
| 对外 443 | 只开在 IIS ARR / nginx；证书装在反代上 |
| Keycloak | 本机 `https://127.0.0.1:8443`，不对网段开放；经反代对外 |
| SQL Server | 1433 仅限应用服务器/管理机访问（防火墙）；启用加密（8.3 的连接串 `encrypt=true`） |
| 网关→后端 | 后端应用端口绑定 `127.0.0.1` 或防火墙仅放行网关来源 |
| AD LDS（若 A'） | 强制 636/LDAPS |
| 管理控制台 | `/admin` 不对全员开放：防火墙限制来源，或 Keycloak 管理界面单独端口（※管理端口隔离按当前版本文档核对） |

### 13.2 数据库与服务账号（最小权限清单）

| 账号 | 用途 | 权限边界 |
|---|---|---|
| `keycloak_svc` | Keycloak 连库 | 仅 `keycloak` 库 read/write/ddladmin |
| `sso_sync_svc` | 同步脚本连库 | 仅 `sso` 库读写 |
| `sso_ro` | 参考 `fine_user`（如需比对） | 仅 `finedb_11` db_datareader |
| `svc-ldap-reader` / `svc-kc-fed` | 系统绑定/Keycloak 联邦（仅 A'） | 仅 AD LDS 目录读 |
| 发信邮箱 `ap_sso@inalfa.com` | 设密/告警邮件 | 仅发送权限，禁收件箱登录（或仅本方案使用；原 `sso-notify@` 命名作废） |

任何账号不进 sysadmin、不用 sa、不复用、离职/下线即禁用。

### 13.3 TLS 证书管理

- 证书台账：名称、到期日、部署位置（Keycloak、nginx、AD LDS）登记到运维文档；到期前 30 天提醒（【需 IT 配合】统一签发与续期）。
- 证书私钥文件 ACL：仅服务运行账号可读。

### 13.4 脚本密钥保管

| 密钥 | 保管方式 |
|---|---|
| SQL 口令、SMTP 口令、KC client secret、cookie secret | 不写在脚本明文里：用 DPAPI 加密（`ConvertTo-SecureString -AsPlainText ... | ConvertFrom-SecureString` 生成密文文件，密钥绑定本机+运行账号）；或环境变量由服务账号配置。运行账号 ACL 锁定 |
| 文件权限 | `C:\sso\` 目录仅管理员与脚本服务账号可读 |

### 13.5 MFA

- 第一阶段：仅对 Keycloak 管理员（master 域 + inalfa 管理角色）启用 OTP（TOTP，手机验证器 App）。
- 第二阶段（全员可选）：给 `inalfa` realm 开 OTP 作为可选认证流。<50 人规模建议先不强推，避免落地阻力；※OTP 配置按当前版本核对。

### 13.6 日志留存

| 日志 | 位置 | 留存 |
|---|---|---|
| Keycloak 登录/管理事件 | `keycloak` 库（9.4） | 库内 90/180 天 + 每月 CSV 归档 ≥1 年 |
| 同步日志 | `sso` 库 `sync_log` | ≥1 年（表很小） |
| NSSM/服务日志、nginx 日志 | 文件（轮转） | ≥90 天 |

### 13.7 常见攻击面与对策

| 攻击面 | 对策 |
|---|---|
| 网关头伪造（11.2.1） | 清头 + 仅网关可达 + 共享密头 |
| redirect_uri 滥用（授权码截获） | client 精确白名单；PKCE（可改系统建议开启，※按版本核对） |
| Keycloak 管理后台被撞库 | master 域管理员 OTP + 暴力破解防护 + 来源限制 |
| 同步客户端密钥泄露 | 最小权限（只 manage-users）；泄露即轮换 secret |
| 邮件通道钓鱼（假"激活账号"邮件） | 邮件模板中写明公司域名与求助方式；用户教育一条："设密链接域名一定是 sso.ap.inalfa.local" |
| 数据库直连拖库 | 账号最小权限 + 1433 防火墙 + 库文件纳入服务器既有防护 |

---

## 14. 运维

**这一章解决什么问题：** 系统上线后怎么盯住它：备份恢复、监控告警、故障排查，以及"SSO 全挂了怎么进去救火"。

### 14.1 备份与恢复（日常化）

| 对象 | 方式 | 频率 | 恢复演练 |
|---|---|---|---|
| `keycloak` / `sso` 库 | SQL Server 完整备份（沿用企业作业） | 每日 | 半年一次：恢复到测试实例并验证登录 |
| Keycloak realm 导出 | `kc.bat export --dir C:\sso\kc-export`（计划任务） | 每周 + 配置大改后 | 升级前必做一次 |
| 配置文件（keycloak.conf、nginx conf、脚本） | 文件备份 | 每日 | — |
| 证书 | 原始 PFX 存 IT 保密区 | 每次续期 | — |

### 14.2 监控指标与告警阈值

| 指标 | 采集方式 | 告警阈值 | 动作 |
|---|---|---|---|
| Keycloak 健康检查 | `GET http://127.0.0.1:9000/health`（`health-enabled=true` 时管理端口暴露，※端口按版本核对） | 非 200 / 服务停止 | 重启服务；5 分钟未恢复人工介入 |
| 同步新鲜度 | 脚本检查 `MAX(sso_user.synced_at)` | 距今 > 26 小时 | 告警邮件（防"名单没到还报成功"的静默失效） |
| sync_log 状态 | 脚本检查当日 `status` | 非 OK | 告警邮件 |
| SMTP 可用性 | 每周一脚本发测试邮件并确认 | 发送失败 | 【需 IT 配合】查邮箱 |
| 服务存活 | `Get-Service Keycloak`（+nginx/oauth2-proxy） | Stopped | NSSM 自动重启失败时人工介入 |
| 磁盘空间 | 服务器既有监控 | < 10% | 清理日志/导出文件 |
| 证书到期 | 日历提醒 + 脚本检查证书 NotAfter | < 30 天 | 【需 IT 配合】续签 |

> <50 人规模不需要专业监控平台：以上全部可以用 1 个每日运行的 PowerShell 检查脚本 + 邮件告警实现（把检查结果写进 `sync_log` 或独立告警表）。

### 14.3 故障排查手册（按症状查）

| 症状 | 可能原因 | 排查顺序 |
|---|---|---|
| 登录页打不开 | Keycloak 服务停 / 证书过期 / DNS / 反代未转到 8443 | `Get-Service Keycloak` → 本机 `https://127.0.0.1:8443` 是否可开 → ARR/nginx 规则 → `C:\keycloak\logs` |
| 跳转地址变成 127.0.0.1 或双写 https | `proxy-headers` 未开 / ARR 未保留 Host | 核 8.3 与 8.7.1 请求头 |
| 登录报"账号未启用" | 该人 `sso_user.status=0`（名单已置离职） | 查 `sso_user`；确认是离职→属正常；误停→改 IT 名单并手工跑脚本 |
| 收不到激活/重置邮件 | SMTP 配置失效 / 用户 email 为空 | Realm Email → Test connection；查 `sso_user.email`；查垃圾箱 |
| 用户登录某系统后无权限 | 身份通了、授权未配（正常逻辑） | 按台账在该系统内配角色 |
| 同步日志 ABORTED | 名单缺失/异常比例（6.4） | 看 `sync_log.message`；与 IT 核对名单；确认后 `-Force` 重跑 |
| Keycloak 中资料与 AD 不一致 | 当日同步失败或名单滞后 | 查 sync_log；手工执行两脚本；核对名单 |
| 某老系统登录循环/401 | 网关头未注入 / 后端不认头 | 抓网关出口请求头；核对 11.2.2 配置；联调厂商 |
| Keycloak 启动报数据库错误 | MSSQL 驱动不匹配 / 凭据错 / 库被动 | 看 `service-err.log` 首个异常；验证 `sqlcmd -U keycloak_svc` 连接；※对照 Keycloak 版本的 MSSQL 支持文档 |

### 14.4 break-glass（紧急通道）

- 保留 `master` 域本地管理员 `kcadmin`（强密码 `<KC_ADMIN_PWD>`，密码封存两份：纸质信封交项目负责人与 IT 各一，**不入 AD、不入任何系统**）。
- 所有可改造业务系统保留 1 个本地管理员账号（同样的封存方式），保证 Keycloak 故障时各系统仍可本地管理。
- Keycloak 完全宕机时的降级预案：各系统临时切换回本地登录（接入端配置的 fallback，或改 nginx 跳过 auth_request）——把该预案的**具体操作命令**写进运维手册并演练一次。
- 当天必须停号：跑 7.6 `disable_user_now.ps1`，不要等计划任务；同时邮件 IT 改名单，防止次日复活。

---

## 15. 实施计划

**这一章解决什么问题：** 把方案变成可排期、可验收、可回滚的动作清单。按"先立地基、先易后难、逐系统灰度"推进。

### 15.1 阶段与里程碑（建议 5–7 周，视厂商配合度浮动）

| 阶段 | 内容 | 工期 | 里程碑 | 责任方 |
|---|---|---|---|---|
| P0 准备 | 名单格式（**全量**）与 IT 约定；证书/DNS/防火墙；建 `sso`/`keycloak` 库；**书面确认 FineReport 认证路径**；盘点各系统填 10.0 接入矩阵与对照表 | 第 1 周 | M1 基础资源就绪 + 帆软路径锁定 | 【客户自做 + 需 IT 配合 + 需厂商支持】 |
| P1 部署 | JDK21+Keycloak(8443)+NSSM+MSSQL；**IIS ARR/nginx 反代 443**；realm/SMTP/策略/准入组 | 第 2 周 | M2 `https://sso.ap.inalfa.local` 可登录且帆软原站点 443 不受影响 | 【客户自做】 |
| P2 数据链路 | 导入首批名单；MERGE；KC 同步脚本；计划任务；告警 | 第 3 周 | M3 全员账号在 Keycloak 就绪、自动同步跑通 | 【客户自做 + 需 IT 配合（名单）】 |
| P3 试点接入 | 选 1 个自研系统（改造最易）接入 OIDC；10 人试点 | 第 4 周 | M4 试点系统 SSO 可用 | 【客户自做/系统开发】 |
| P4 批量接入 | 其余可改造系统逐个接入；FineReport 与帆软确认路径 | 第 5–6 周 | M5 80% 登录走 Keycloak | 【客户自做 + 需厂商支持】 |
| P5 难点收尾 | LDAP-only 系统定方向（11.4.1 决策表）并实施；禁用旧登录入口 | 第 7 周起 | M6 全量切换 + 旧账号通道关闭 | 【客户自做 + 需厂商支持】 |

### 15.2 验收清单

- [ ] 新员工：名单出现 T+1 日，收到邀请邮件，完成设密，可登录试点系统（无人工建号）
- [ ] 离职员工：名单置 0 当日，Keycloak 禁用且会话被踢掉，试点系统无法登录
- [ ] 紧急停号：名单尚未更新时，`disable_user_now.ps1` 后该用户立即无法登录；次日名单未改则告警提示“将被复活”
- [ ] 忘记密码：自助邮件重置全程无管理员介入
- [ ] 两个系统登录一次后，第二个系统免密直达（SSO 生效）
- [ ] 同步脚本连续 5 个工作日 `sync_log.status=OK`；人为制造"名单未到"，次日收到告警
- [ ] 服务器重启后 Keycloak/网关服务自动恢复，登录正常
- [ ] break-glass 演练：停用 Keycloak 服务，各系统本地管理员仍可进入
- [ ] 台账有首批真实数据；离职流程走查一遍
- [ ] 所有配置核对项（※请核对）逐条确认并记录实际版本号
- [ ] 接入矩阵每一行有路径；对照表覆盖“用户名不一致”的存量账号
- [ ] 反代验收 8.7.3 全部勾选

### 15.3 回滚方案

| 场景 | 回滚动作 |
|---|---|
| 单个系统接入后故障 | 该系统切回本地登录（接入端关闭 OIDC/网关跳过），其余不受影响 |
| Keycloak 持续故障 | 全部系统临时回本地登录（14.4 预案）；`sso_user` 数据不丢，恢复后免重建 |
| 同步链路异常 | 中止机制已保证 `sso_user` 不被污染；最坏情况手工执行 MERGE 前恢复暂存表 |
| 整体放弃（概率低） | 各系统账号体系未删除，只是新增了登录方式；关闭 Keycloak 即回到现状 |

> 设计原则：**本方案只做加法**。每个系统的本地账号在验收通过前一律保留，回滚永远成立。

---

## 16. 风险清单与应对

**这一章解决什么问题：** 提前写下最可能翻车的 10 件事和对策，评审时逐条认领责任人。

| # | 风险 | 可能性 | 影响 | 应对 |
|---|---|---|---|---|
| R1 | **同步静默失效**：名单没到/脚本被禁用，但无人发现，用户资料与离职状态悄然过期 | 高 | 高 | 6.4 防错 + 14.2 同步新鲜度监控（26h 阈值）+ 每周人工抽查一条离职记录是否已被禁用 |
| R2 | **双轨制长期并存**：一部分系统一直走旧账号，"统一登录"名存实亡 | 高 | 中 | 15.1 P5 强制设切换截止日；未接入系统在台账中标注"遗留"，每季度复审 |
| R3 | **离职残留权限**：Keycloak 已禁用，但系统内历史权限未回收 | 中 | 中 | 12.2 流程 + 台账 `revoked_at` + 季度对账 |
| R4 | Keycloak 单点故障导致全员无法登录 | 中 | 高 | NSSM 自动拉起 + 每日备份 + 14.4 break-glass/降级预案演练 |
| R5 | MSSQL 与 Keycloak 未来版本不兼容，升级受阻 | 中 | 中 | 升级前测试环境验证；必要时 8.2 备选切换 PostgreSQL（export/import 迁移） |
| R6 | 台账无人维护，3 个月后形同虚设 | 高 | 中 | 把台账登记写进各系统管理员的岗位职责/流程卡；每季度对账会议 |
| R7 | FineReport OIDC 路径被厂商否决，被迫走门面/网关 | 中 | 中 | P4 阶段**第一时间**联系帆软确认路径（10.6），不把它留到最后 |
| R8 | AD LDS（若走 A'）密码策略弱/双写漂移导致密码体系混乱 | 中 | 高 | 11.4 明确唯一写入口纪律；A' 决策前先走 11.4.1 决策表，能不上门面就不上 |
| R9 | IT 名单口径变化（列名调整、导出人更换导致格式漂移） | 中 | 中 | 名单格式写成双方签署的约定（6.2）；脚本对列名缺失直接 ABORTED 告警而非容错 |
| R10 | 首次设密邮件被当钓鱼/大量用户卡在激活 | 中 | 中 | 上线前全员宣讲（含"域名必为 sso.ap.inalfa.local"）；监控 `pwd_set=0` 滞留名单，3 天未激活电话提醒 |
| R11 | 网关头伪造/绕过（方向一特有） | 低 | 高 | 11.2.1 五条硬要求逐条验收，其中"后端仅网关可达"用端口扫描验证 |
| R12 | Keycloak 与帆软抢 443，P1 装不起来 | 高 | 高 | ADR-6 + 8.7：Keycloak 只听 8443，443 给 IIS ARR |
| R13 | 存量系统用户名 ≠ AD 登录名，上线对不上号 | 高 | 中 | ADR-8 + `sso_user_map`；P0 盘点，对不上的不接入 |
| R14 | 紧急停号后次日名单仍在职，账号被同步复活 | 中 | 高 | 7.6 告警强制通知 IT 改名单；可在脚本加“紧急停号保护期 24h 内 MERGE 不复职” |
| R15 | Admin REST 部分 PUT 清空用户资料 | 中 | 高 | 7.2 硬规则：一律 GET→改→PUT；代码评审对照 17.4.2 |
| R16 | 同机单点：SQL + 帆软 + Keycloak 一起挂 | 中 | 高 | 接受（&lt;50 人）；NSSM + 备份 + 14.4 本地管理员；不上集群 |

---

## 17. 附录

**这一章解决什么问题：** 汇总可直接复制的 DDL、配置、脚本骨架与术语，实施时不必在正文里翻找。

### 17.1 完整 DDL（sso 库）

见 5.2、5.4、5.6、12.1（`sso_user`、`sso_user_map`、`stg_ad_user`、`sync_log`、`perm_ledger`）。执行顺序：建库 `sso` → 5.4 暂存/日志表 → 5.2 核心表与对照表 →（可选）12.1 台账。

### 17.2 keycloak.conf 样例

```properties
# C:\keycloak\conf\keycloak.conf —— 占位符实施时替换
# 逐行说明见 8.3；※所有键名按当前版本官方文档核对

# 数据库（SQL Server；驱动 jar 需放入 providers\ 后执行 build）
db=mssql
db-url=jdbc:sqlserver://IRSCNYTFINEREPORT.ap.inalfa.local:1433;databaseName=keycloak;encrypt=true;trustServerCertificate=true
db-username=keycloak_svc
# db-password 不要写在这里：NSSM 环境变量 KC_DB_PASSWORD

# 主机名与 TLS（hostname v2；在反代后面，不直占 443）
hostname=sso.ap.inalfa.local
proxy-headers=xforwarded
https-port=8443
https-certificate-file=C:/keycloak/certs/sso.crt
https-certificate-key-file=C:/keycloak/certs/sso.key

# 健康检查（管理端口，默认 9000，※核对；只本机访问）
health-enabled=true
http-management-port=9000

# 日志
log=file
log-file=C:/keycloak/logs/keycloak.log
log-level=INFO

# Java 内存（也可用服务环境变量 JAVA_OPTS 设置）
# -Xms512m -Xmx1024m 对 <50 人足够
```

### 17.3 NSSM 命令汇总

```bat
:: Keycloak（8.5）
nssm install Keycloak "C:\keycloak\bin\kc.bat" "start --optimized"
nssm set Keycloak AppDirectory C:\keycloak\bin
nssm set Keycloak Start SERVICE_AUTO_START
nssm set Keycloak AppStdout C:\keycloak\logs\service-out.log
nssm set Keycloak AppStderr C:\keycloak\logs\service-err.log
nssm set Keycloak AppRotateFiles 1
nssm set Keycloak AppRotateBytes 10485760
nssm set Keycloak AppEnvironmentExtra KC_DB_PASSWORD=<DB_PWD>
nssm start Keycloak

:: oauth2-proxy（方向一）
nssm install oauth2proxy "C:\sso\bin\oauth2-proxy.exe" "--config C:\sso\conf\oauth2-proxy.cfg"
nssm set oauth2proxy Start SERVICE_AUTO_START

:: nginx（方向一）
nssm install nginx "C:\nginx\nginx.exe" "-p C:\nginx"
nssm set nginx Start SERVICE_AUTO_START

:: 卸载（回滚用）：nssm stop <name> && nssm remove <name> confirm
```

### 17.4 PowerShell 脚本骨架

#### 17.4.1 sync_ad_to_sso.ps1（AD 名单 → sso 库）

```powershell
# C:\sso\scripts\sync_ad_to_sso.ps1 —— 骨架，实施时补齐密钥读取(DPAPI)与告警函数
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$importDir = '\\<文件服务器>\sso_import'
$today = Get-Date -Format 'yyyyMMdd'
$file  = Join-Path $importDir "ad_users_$today.csv"

function Write-Log($phase,$src,$added,$upd,$dis,$rea,$status,$msg){ /* INSERT INTO dbo.sync_log ... */ }
function Send-Alert($msg){ /* 用 ap_sso@inalfa.com 邮箱发告警 */ }

try {
    if (-not (Test-Path $file)) { Write-Log 'LOAD' 0 0 0 0 'ABORTED' "当日名单未到: $file"; Send-Alert "SSO: 当日名单未到"; exit 1 }

    # 1) 解析 CSV（编码按与 IT 的约定）
    $rows = Import-Csv $file -Encoding UTF8
    if ($rows.Count -eq 0) { Write-Log 'LOAD' 0 0 0 0 'ABORTED' '空文件'; Send-Alert 'SSO: 名单为空'; exit 1 }

    # 2) 校验清洗（employee_no 唯一非空 / login_name 唯一 / email 格式）→ 不合格行剔除并记录
    #    （实现略，参照 5.5）

    # 3) 防错检查（SqlBulkCopy 灌 stg_ad_user 后，在 SQL 侧执行 6.4 各项检查）
    #    任一命中且未指定 -Force：ABORTED + 告警 + exit 1

    # 4) 执行 6.5 MERGE（通过 Invoke-Sqlcmd / SqlCommand 执行）
    #    前后各查一次计数统计 added/updated/disabled/reactivated

    # 5) 写 sync_log OK → 调用 Keycloak 同步
    & C:\sso\scripts\sync_sso_to_keycloak.ps1
}
catch {
    Write-Log 'LOAD' 0 0 0 0 'ERROR' $_.Exception.Message
    Send-Alert "SSO 同步异常: $($_.Exception.Message)"
    exit 1
}
```

#### 17.4.2 sync_sso_to_keycloak.ps1（sso 库 → Keycloak REST）

```powershell
# 骨架；※所有端点按当前版本 Admin REST API 核对
# 硬规则：禁止 PUT 部分 JSON。更新一律 GET 完整对象 → 改字段 → PUT 回去。
$kc   = 'https://sso.ap.inalfa.local'
$realm= 'inalfa'
$cid  = 'sync-client'; $csec = '<KC_CLIENT_SECRET>'   # 实施时改为 DPAPI 读取

function Get-KcToken {
    (Invoke-RestMethod -Method Post -Uri "$kc/realms/$realm/protocol/openid-connect/token" -Body @{
        grant_type='client_credentials'; client_id=$cid; client_secret=$csec }).access_token
}

function Get-KcHeaders {
    @{ Authorization = "Bearer $(Get-KcToken)"; 'Content-Type' = 'application/json' }
}

function Get-KcUserByName($login) {
    $H = Get-KcHeaders
    $q = Invoke-RestMethod -Headers $H `
      -Uri "$kc/admin/realms/$realm/users?username=$([uri]::EscapeDataString($login))&exact=true&max=1"
    if ($q -is [array] -and $q.Count -gt 0) { return $q[0] }
    if ($q -and $q.id) { return $q }
    return $null
}

function Get-KcUserById($id) {
    Invoke-RestMethod -Headers (Get-KcHeaders) -Uri "$kc/admin/realms/$realm/users/$id"
}

function Set-KcUser($userObj) {
    # 必须提交完整 representation
    $json = $userObj | ConvertTo-Json -Depth 8 -Compress
    Invoke-RestMethod -Headers (Get-KcHeaders) -Method Put `
      -Uri "$kc/admin/realms/$realm/users/$($userObj.id)" -Body $json
}

function Disable-KcUserAndLogout($id) {
    $u = Get-KcUserById $id
    $u.enabled = $false
    Set-KcUser $u
    Invoke-RestMethod -Headers (Get-KcHeaders) -Method Post `
      -Uri "$kc/admin/realms/$realm/users/$id/logout"
}

# 1) 读 sso_user 全量
$users = Invoke-Sqlcmd -ServerInstance 'IRSCNYTFINEREPORT.ap.inalfa.local' `
    -Database sso -Credential <SQL凭据> -Query "SELECT * FROM dbo.sso_user"

foreach ($row in $users) {
    $found = Get-KcUserByName $row.login_name
    if (-not $found -and $row.status -eq 1) {
        $create = @{
            username  = $row.login_name
            enabled   = $true
            email     = $row.email
            firstName = ''
            lastName  = [string]$row.display_name   # 中文名整放 lastName，不拆
            attributes = @{
                employee_no = @([string]$row.employee_no)
                dept_code   = @([string]$row.dept_code)
                title       = @([string]$row.title)
            }
        } | ConvertTo-Json -Depth 8

        # POST 201：body 常为空，id 在 Location 头
        $resp = Invoke-WebRequest -Headers (Get-KcHeaders) -Method Post `
            -Uri "$kc/admin/realms/$realm/users" -Body $create -ContentType 'application/json'
        $newId = ($resp.Headers['Location'] -split '/')[-1]
        if (-not $newId) { throw "创建用户 $($row.login_name) 未返回 Location" }

        if ($row.email) {
            Invoke-RestMethod -Headers (Get-KcHeaders) -Method Put `
              -Uri "$kc/admin/realms/$realm/users/$newId/execute-actions-email?lifespan=259200&client_id=account" `
              -ContentType 'application/json' -Body '["UPDATE_PASSWORD"]'
        }
        continue
    }

    if (-not $found) { continue }

    $kcUser = Get-KcUserById $found.id   # 再 GET 一次完整对象，搜索结果可能是精简字段
    $dirty = $false
    if ([string]$kcUser.lastName -ne [string]$row.display_name) { $kcUser.lastName = [string]$row.display_name; $dirty = $true }
    if ([string]$kcUser.email     -ne [string]$row.email)        { $kcUser.email     = [string]$row.email;        $dirty = $true }

    if ($row.status -eq 0 -and $kcUser.enabled) {
        Disable-KcUserAndLogout $kcUser.id
        continue
    }
    if ($row.status -eq 1 -and -not $kcUser.enabled) {
        $kcUser.enabled = $true
        $dirty = $true
        # 停用超过 180 天或 pwd_set=0：再发 UPDATE_PASSWORD（实现略）
    }
    if ($dirty) { Set-KcUser $kcUser }

    # requiredActions 不再含 UPDATE_PASSWORD 且 pwd_set=0 → UPDATE sso_user SET pwd_set=1
}
# 写 sync_log(phase='KC')；HTTP 失败退避重试 3 次（10s/30s/60s）
```

> 不要用 `Invoke-RestMethod` 做 POST 建用户——它常丢掉 `Location` 头。用 `Invoke-WebRequest` 读 `Headers['Location']`。

#### 17.4.3 disable_user_now.ps1（紧急停号）

```powershell
# C:\sso\scripts\disable_user_now.ps1
param(
    [Parameter(Mandatory=$true)][string]$EmployeeNo,
    [Parameter(Mandatory=$true)][string]$Operator
)
$ErrorActionPreference = 'Stop'
# 复用 17.4.2 的 Get-KcToken / Get-KcUserByName / Disable-KcUserAndLogout（实施时抽成公共模块）

$row = Invoke-Sqlcmd -ServerInstance 'IRSCNYTFINEREPORT.ap.inalfa.local' -Database sso -Credential <SQL凭据> `
    -Query "SELECT employee_no, login_name, status FROM dbo.sso_user WHERE employee_no = @en" `
    # 实际用 SqlParameter 传 $EmployeeNo，禁止拼接 SQL
if (-not $row) { throw "工号不存在: $EmployeeNo" }

Invoke-Sqlcmd ... -Query "UPDATE dbo.sso_user SET status=0, updated_at=SYSUTCDATETIME() WHERE employee_no=@en"

$found = Get-KcUserByName $row.login_name
if ($found) { Disable-KcUserAndLogout $found.id }

# Write-Log phase='KC_EMERGENCY' disabled=1 OK "operator=$Operator emp=$EmployeeNo login=$($row.login_name)"
# Send-Alert "已紧急停号 $EmployeeNo ($($row.login_name))。请 IT 当天从名单去掉此人，否则次日凌晨 MERGE 会复职。"
```

### 17.5 nginx / IIS 片段

- Keycloak 前置反代（443 → 8443）：见 8.7。
- nginx 完整样例（老系统网关）：见 11.2.2。
- IIS ARR 思路：安装 ARR + URL Rewrite → 建服务器场(serverFarm)指向后端 → 重写规则中先"清除传入的 `X-Forwarded-User`"→ 条件式调用 oauth2-proxy 的 `/oauth2/auth`（forward-auth 模式）→ 按其响应头回填用户头。因 ARR 无 auth_request 原生等价物，规则较繁，实施时需逐条调试（※按微软 IIS 文档核对）。

### 17.6 术语表

| 术语 | 一句话解释 |
|---|---|
| SSO | 单点登录：登录一次，多个系统都认 |
| OIDC / OAuth2 | 行业标准的"登录交接协议"：业务系统把登录这件事委托给 Keycloak |
| Access/Refresh Token | 访问凭证（短命，15 分钟）与续命凭证 |
| Realm | Keycloak 里的"独立租户/域"，本文用 `inalfa` |
| Client | 一个接入系统在 Keycloak 里的登记身份（OIDC 或 SAML） |
| 准入组 | Keycloak 里 `app-<系统>` 组，只表示“能不能进这个系统”，不是业务角色 |
| 对照表 | `sso_user_map`：同一人在各系统的本地用户名映射 |
| LDAP bind | 老式目录协议的"验证用户名密码"动作；Keycloak 不支持对外提供 |
| AD LDS | Windows Server 内置的轻量 LDAP 目录，可当"门面" |
| User Federation | Keycloak 把外部 LDAP 当用户来源读取的机制 |
| 密码权威 | "用户密码到底存哪、谁说了算"——本方案=Keycloak；A'=门面 |
| oauth2-proxy | 开源网关组件：先用 OIDC 认证，再把用户名注入请求头 |
| 网关注入（方向一） | 在老系统前面放网关做认证，把"已登录用户名"通过 HTTP 头传给系统 |
| MERGE | SQL Server 的"有则更新、无则插入"合并语句 |
| DPAPI | Windows 自带的数据加密接口，密钥绑定本机与运行账号 |
| NSSM / WinSW | 把任意程序注册成 Windows 服务的工具 |
| break-glass | 应急后门：SSO 全挂时仍能进入系统的本地管理员通道 |

---

## 文档核对清单（实施前逐条确认）

| 位置 | 待核对项 |
|---|---|
| 8.1 | 所用 Keycloak 版本的 JDK 要求 |
| 8.2/8.3 | MSSQL 驱动安装方式、db 配置键名、hostname v2、`proxy-headers` |
| 8.7 | IIS ARR preserveHostHeader、后端自签证书、管理端口不映射 443 |
| 8.4 | bootstrap-admin 命令/初始管理员创建方式 |
| 9.2–9.4 | 密码策略、暴力破解、事件存储的具体配置名 |
| 7.2 | Admin REST：PUT 整对象、Location 头、logout 端点、execute-actions-email |
| 10.0 | 各系统接入路径（OIDC / SAML / 网关 / 遗留）已填矩阵 |
| 10.6 | 帆软当前版本 OAuth/OIDC/HTTP 头集成的准确方式（**第 1 周**联系帆软支持） |
| 10.8 | SAML 客户端元数据与对方 ACS |
| 11.3.5 | User Federation 各配置项名称与 AD LDS 属性支持 |
| 14.2 | health 端点与管理端口 |
| 17.4 | PowerShell 调用 Admin REST 的响应细节 |

> 本文档不含任何真实口令；所有 `<占位符>` 在实施时替换，密钥按 13.4 保管。




