# 统一身份认证技术交底书：MSIA Report 与 BOL 管理系统实施实录

> 用途：向同事交底已落地的统一身份认证方案，并作为其他系统接入的实施参考。
>
> 方案基础：《统一身份认证方案A_Keycloak自管密码.md》
> 实施文档：《统一身份认证实施方案_MSIA与BOL系统.md》｜实施工件：`统一身份认证实施/`
>
> **当前进度（2026-11-03）**：两系统代码改造与全量测试已交付（QA 结论 `IS_PASS: YES`）；五张 SSO 表 + 种子 + 授权已落地；JDK21 已装于 `IRSCnKettle01`；CA 证书工单已提交；AD 名单已同步进暂存表。进行中：Keycloak 部署——26.x 因 SQL Server 2017 不支持 `OPTIMIZE_FOR_SEQUENTIAL_KEY` 已回退，**当前按 25.0.6 重装**，可执行清单见 `docs/keycloak-deploy-runbook.md` 第 10 节（含 T1–T6 现场确认项与 V1–V6 验证门）。OIDC 双轨开关默认关闭，**生产行为与改造前一致**。

> **当前进度（2026-11-05 更新）**：现场已完成 Keycloak 25.0.6 部署与 `msia-prod` client 重建；MSIA 旧版 exe 导致 OIDC 回调 404 已定位，含 OIDC 路由的版本已于 11-05 重新打包（`MSIA Report/dist/MSIA-deploy-20261105.zip`）。同日 21:34，`ligu` 经 Keycloak 登录页成功进入 MSIA，四段式链路（授权跳转 → 回调验签 → OTK 换 JWT → 业务接口鉴权）均有实证，详见第 20 章。踩坑与可复用判据见第 17 章，Ready 矩阵与并行工作清单见第 18 章。CA 证书仍在等签发，两系统 OIDC 开关的正式切换仍待定。

---

## 1. 一句话架构

**Keycloak 作为统一身份提供者，CN_AME 库中的 `CN_AME_SSO_` 系列表作为中央人员事实来源，AD 名单单向同步到中央表再同步到 Keycloak；MSIA/BOL 通过 OIDC 授权码流登录，但认证成功后仍签发各系统原有本地登录凭证，从而做到“登录入口统一、下游鉴权零改动”。**

---

## 2. 当前状态与默认行为

### 2.1 进度一览

- **已完成**：SSO 五表 + 种子 + 授权；两系统 OIDC 代码改造（后端端点、OTK、开关、身份解析、状态回写）+ 前端双轨登录页；全量测试通过；BOL 重打包冒烟通过；JDK21 安装；CA 工单提交；StgAdUser 名单同步启动；MANUAL 种子用户已转 `AD`（`04_flip_manual_source.sql`）；AD 账号已批量导入 Keycloak（**本地用户，含 `username` / `email`，无密码**，首次密码需管理员代设）。
- **进行中**：Keycloak 部署（装包 → 8443 自签 → build → bootstrap-admin → NSSM）；CA 证书签发。
- **待办**：keycloak 库登录名/排序规则确认（勿用 sysadmin 的 ytview）→ 人员 MERGE → realm/client 初始化 → 本地账号与 `CN_AME_SSO_UserMap` 对齐（口径已定：本地账号必须先存在，UserMap 负责把 IdP 身份指向本地账号，见 20.4）→ 证书到手后 DNS + ARR + 双轨联调。

### 2.2 双轨默认行为（改造后生产不受影响）

| 系统 | 开关 | 默认值 |
|---|---|---|
| MSIA | `OIDC_ENABLED` / `LOCAL_LOGIN_ENABLED` / `HR_SYNC_ENABLED` / `SSO_USER_SYNC_ENABLED` | false / true / true / false |
| BOL | `OIDC_ENABLED` / `LOCAL_AUTH_ENABLED` / `SELF_REGISTRATION_ENABLED` / `PASSWORD_SELF_SERVICE_ENABLED` / `SSO_STATUS_SYNC_ENABLED` | false / true / false / true / true |

BOL 游客登录保留。Keycloak 未上线、OIDC 为 false 时，两系统行为与改造前完全一致。

---

## 3. 统一身份认证核心设计

### 3.1 为什么 Keycloak 自管密码，而不是 AD 密码联邦

- **AD 能提供的只有 `username` 和 `email`，没有密码**——AD 从不对外提供密码哈希，也不开放 LDAP 连接，因此「拿 AD 密码来验」在技术上就不成立，不是选型偏好。
- 因此确定走**方案 A：Keycloak 本地密码**。Keycloak 持有唯一业务密码，是密码的唯一权威；AD 只作为人员名单来源。
- **本方案不做 LDAP / User Federation 联邦**。Keycloak 里的业务账号是**本地用户**（本地 `username` + 本地凭证，密码哈希存于 `keycloak` 库 `CREDENTIAL` 表），不是 AD 的影子账号。后续接手者不要按「联邦」思路排查问题。
- 首次设密、忘记密码、离职禁用统一由 Keycloak/中央表管理，避免两套密码体系并存。
- 已有落地事实：AD 账号已**批量导入**为 Keycloak 本地用户，具备 `username` 与 `email`；**没有任何密码**，首次密码必须由管理员代设（详见第 21 章）。

### 3.2 为什么 OIDC 成功后还签发本地凭证

- MSIA 原有本地 JWT、BOL 原有 `AuthToken`；统一登录只替换“身份来源”，不替换“业务鉴权凭证”。
- 下游权限判断、接口鉴权、前端存储逻辑基本不变。

### 3.3 为什么使用 OTK 一次性码

OIDC 回调成功后，后端签发本地凭证 → 生成 60 秒有效、单次消费的 OTK → 前端回调页用 OTK 调 `/oidc/token` 换本地登录态。避免 Token 进入 URL、浏览器历史、反代日志和 Referer。

---

## 4. 中央数据库设计

目标库：`IRSCNYTFINEREPORT.ap.inalfa.local / CN_AME`；统一表前缀 `CN_AME_SSO_`。

### 4.1 表总览

| 表名 | 作用 | 谁写 |
|---|---|---|
| `CN_AME_SSO_StgAdUser` | AD 名单暂存表，每日清空重灌 | 定期作业/同步脚本 |
| `CN_AME_SSO_User` | 中央人员唯一事实来源 | `sync_ad_to_sso.ps1` MERGE |
| `CN_AME_SSO_UserMap` | 跨系统本地用户名映射 | 人工/对账后登记 |
| `CN_AME_SSO_SyncLog` | 同步日志与告警依据 | 同步脚本 |
| `CN_AME_SSO_PermLedger` | 权限台账（谁在哪个系统是什么角色） | 人工维护 |

种子 13 人已建档；2026-11-03 起 source 统一为 `AD`，纳入 AD 同步生命周期。**完整 DDL 见 `scripts/sql/01_create_sso_tables.sql`**，本文只列集成必读字段：

- `User.employee_no`：稳定人员主键（MERGE 匹配键），唯一；
- `User.login_name`：Keycloak username，唯一，**禁止被 MERGE 改写**；
- `User.status`：`1=在职 / 0=停用`，永不物理删除；
- `User.source`：`AD=同步 / MANUAL=手工例外`（MANUAL 行不被同步覆盖或停用）；
- `User.pwd_set` / `kc_user_id`：Keycloak 设密状态与用户 ID 缓存；
- `UserMap(system_code, local_username)`：唯一约束，本地用户名与中央 login_name 不一致时必填。

### 4.2 定期作业对接口径

定期作业只写暂存表，不直接写中央人员表。CSV 投递列名固定：

```text
userName,realName,email,mobile,enable,employeeNo
```

映射：`userName→login_name`、`employeeNo→employee_no`、`realName→display_name`、`email/mobile→同名字段`、`enable→status`。

```bat
:: CSV 通道
powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1 -Source csv -CsvDirectory C:\sso\import

:: 快照表通道（IT 直接落库时）
powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1 -Source table -TableSourceQuery "SELECT userName, realName, email, mobile, enable, employeeNo FROM dbo.YourAdSnapshot"
```

---

## 5. 人员同步链路

### 5.1 数据流

```text
AD 名单 -> CSV / 数据库快照 -> CN_AME_SSO_StgAdUser -> 防错检查
  -> MERGE 到 CN_AME_SSO_User -> Keycloak Admin REST 同步
  -> 首次密码：管理员批量代设统一初始密码（Temporary=ON）+ 首登强制改密
     （SMTP 已按正式服务具备，邀请邮件链路可用；批量开通场景仍以统一初始密码为主，见第 21 章）
```

### 5.2 核心同步规则

- `login_name` 一旦确定，禁止被 MERGE 改写（变更走“停旧建新”）。
- `source='MANUAL'` 的中央人员不被 AD 同步覆盖、不被停用。
- 停用永不物理删除，只置 `status=0`。
- 邮箱允许空/重复；格式非法置空并告警，不整体中止；无邮箱用户由管理员代设密 + 首登改密。
- **AD 名单不含密码**：所有 Keycloak 本地账号的初始密码都由管理员批量代设为**统一初始密码**（`Temporary=ON`）+ `UPDATE_PASSWORD` 必需动作，首登强制改密；SMTP 已按正式服务具备，但批量开通场景不依赖邮件邀请（见第 21 章）。
- Keycloak 侧同步通过 `sync_sso_to_keycloak.ps1`（sync-client 调 Admin REST），与 AD 同步串联执行。

### 5.3 防错中止规则

以下情况写 `CN_AME_SSO_SyncLog` + 告警邮件后 `ABORTED`：行数骤降 >30%、停用占比 >10%、登录名重复、工号重复。

### 5.4 监控 SQL

```sql
SELECT TOP 20 run_at, phase, src_rows, added, updated, disabled, reactivated, status, message
FROM dbo.CN_AME_SSO_SyncLog
ORDER BY run_at DESC;
```

---

## 6. OIDC 接入统一模式

两个系统使用同一套 OIDC 模式，差异只在框架和本地凭证类型。

### 6.1 标准登录流程

```text
前端点“统一身份登录”
  -> GET /api/auth/oidc/login
  -> 后端生成 state/nonce/PKCE verifier
  -> 302 到 Keycloak 授权端点
  -> 用户登录
  -> 302 /api/auth/oidc/callback?code=&state=
  -> 后端校验 state/nonce
  -> 用 code + PKCE verifier 换 id_token
  -> JWKS 验签，校验 aud/iss/exp/nonce
  -> 身份解析 resolve_or_create
  -> 签发本地凭证 -> 生成 OTK
  -> 302 前端 /oidc/callback?otk=...
  -> 前端 POST /api/auth/oidc/token -> 返回本地登录态
```

### 6.2 标准端点

| 端点 | 方法 | 作用 |
|---|---|---|
| `/api/auth/config` | GET | 登录页开关：OIDC、本地登录、自助注册、密码自助 |
| `/api/auth/oidc/login` | GET | 跳转 Keycloak 授权 |
| `/api/auth/oidc/callback` | GET | OIDC 回调 |
| `/api/auth/oidc/token` | POST | OTK 换本地凭证 |

### 6.3 安全参数

授权码流 + PKCE S256；ID Token RS256 + JWKS 验签；aud=本系统 client_id；iss=`https://sso.ap.inalfa.local/realms/inalfa`；nonce 必须匹配；state 一次性消费防 CSRF/重放；discovery 缓存 10 分钟；state/nonce/PKCE 与 OTK 均存内存（10 分钟 / OTK 60 秒单次消费）；时钟容错 60 秒。

### 6.4 身份解析统一顺序

```text
1. groups 准入校验（无准入组 -> 403）
2. CN_AME_SSO_UserMap 按 system_code + login_name 查本地用户名
3. 未命中映射，回落 preferred_username
4. 查本地用户表
5. 本地命中且启用 -> 登录
6. 本地未命中且允许自动建档 -> 按最低权限建档
7. 本地禁用 / 不允许自动建档 -> 403
```

### 6.5 自动建档规则

| 系统 | 本地用户表 | 自动建档角色 | 本地密码 |
|---|---|---|---|
| MSIA | `CN_AME_MISA_User` | `reviewee` | `PasswordHash=None` |
| BOL | `CMC.db_datawriter.CN_IE_BOL_Employee` | `VIEWER` | 空密码，不强制本地改密 |

**灌用户口径（2026-11-05 落定）**：正式期要求**本地账号必须先存在**，`CN_AME_SSO_UserMap` 负责把 IdP 身份指向本地账号。MSIA 实测 `ligu` 为本地已存在账号（`local user id=2414`），**不是自动建档**；无 UserMap 映射时回落 `preferred_username` 的兜底分支已在本次登录中生效，但它解决不了同名/大小写冲突，因此 UserMap 仍需补齐。上表的自动建档代码仍保留，但正式期不作为账号来源。

---

## 7. MSIA Report 实施细节

- **技术栈**：FastAPI + SQLAlchemy / React + TS + Vite；本地凭证 JWT；用户表 `CN_AME_MISA_User`。
- **关键文件**（其余见源码树）：
  - `backend/app/core/oidc.py` — OIDC 客户端（PKCE、discovery、token 交换、JWKS 验签、state/OTK）
  - `backend/app/api/auth.py` — 登录、OIDC 登录/回调/OTK 兑换
  - `backend/app/services/sso_identity.py` — 中央表 + UserMap + 本地解析与自动建档
  - `backend/app/services/sso_user_sync.py` — 中央表派生同步（只更新命中用户）
  - `frontend/src/pages/OidcCallback.tsx` + `src/api/auth.ts` — 回调页与 OTK 兑换
- **配置要点**（`backend/config.ini`）：`[oidc]` issuer/client_id/redirect_uri=`http://172.26.2.203:8078/api/auth/oidc/callback`/required_group=`app-msia`/auto_create_user=true；`[security]` 三个开关见 2.2。
- **用户同步策略**：HRDB 全量同步由 `HR_SYNC_ENABLED` 控制；中央表派生同步由 `SSO_USER_SYNC_ENABLED` 控制（每日 06:30，只遍历中央表命中的本地用户，不新建、不禁用未命中）。双轨期建议 hr=true / sso=false；单轨期反之。

---

## 8. BOL 管理系统实施细节

- **技术栈**：Django + DRF + waitress / Vue 3 + Vite；本地凭证 `AuthToken`；员工表 `CMC.db_datawriter.CN_IE_BOL_Employee`。
- **关键文件**（其余见源码树）：
  - `apps/users/oidc.py` + `oidc_views.py` — Django 版 OIDC 客户端与登录/回调/OTK、身份解析
  - `apps/users/auth_views.py` — 本地登录、游客登录、开关、密码服务
  - `apps/users/management/commands/sync_sso_status.py` + `scheduler.py` — 中央状态回写（每小时）
  - `apps/users/migrations/0005_authtoken_source.py` — `AuthToken.source` 加法迁移
- **配置要点**（`backend/db_config.ini`）：`[auth]` 开关见 2.2；`[oidc]` client_id=`bol-prod`、required_group=`app-bol`；**redirect_uri 当前是 `127.0.0.1:8090` 占位，生产必须改为固定内网地址（G4 门项）**。
- **数据库改动（唯一一处加法）**：`CN_IE_BOL_AuthToken.source`（`local`=原本地登录签发 / `oidc`=统一身份登录签发），用于切换日作废旧令牌。
- **离职状态回写**（每小时，全量中央表）：

```sql
SELECT COALESCE(m.local_username, u.login_name) AS local_username, u.status
FROM CN_AME.dbo.CN_AME_SSO_User u
LEFT JOIN CN_AME.dbo.CN_AME_SSO_UserMap m
  ON m.employee_no = u.employee_no AND m.system_code = 'bol'
```

中央 `status=0` → 本地置 `INACTIVE` 并**无条件清理 AuthToken**（不依赖状态转换分支，防残留 Token 复职后复活）；`status=1` → 恢复 `ACTIVE`。游客不在中央表，天然不受影响。
- **跨库读**：BOL 默认连 CMC 库，经三段名 `CN_AME.dbo.CN_AME_SSO_*` 跨库读，已授 `sparePartRead` SELECT。

---

## 9. Keycloak 配置要点

### 9.1 部署形态

Keycloak **25.0.6** + JDK 21（已装于 `IRSCnKettle01`；原 26.x 因 SQL Server 2017 不支持 `OPTIMIZE_FOR_SEQUENTIAL_KEY` 已回退，见部署手册第 10 节）；独立数据库 `keycloak` + 服务账号 `keycloak_svc`（勿用 sysadmin 的 ytview）；8443 走本机回环自签证书（默认听全网卡，由防火墙规则收敛为仅本机可达，见部署手册 6.3）；对外经同机 IIS ARR + 企业证书访问 `sso.ap.inalfa.local`；健康检查 9000 端口。

### 9.2 `keycloak.conf` 要点

```properties
db=mssql
db-url=jdbc:sqlserver://IRSCNYTFINEREPORT.ap.inalfa.local:1433;databaseName=keycloak;encrypt=true;trustServerCertificate=true
db-username=keycloak_svc
db-password=${KC_DB_PASSWORD}          # NSSM 服务环境变量注入，不落盘
hostname=sso.ap.inalfa.local
proxy-headers=xforwarded               # 反代后 redirect_uri 不变 127.0.0.1 的关键
hostname-strict=true
http-enabled=false
https-port=8443
http-management-port=9000
```

完整配置见 `统一身份认证实施/keycloak/keycloak.conf`。

### 9.3 realm `inalfa` 关键策略

User registration OFF；Forgot password ON；Login with email OFF；Duplicate emails OFF；Verify email OFF；密码最小长度 10、不过期；Brute force ON（5 次失败锁 900 秒）；Access Token 15 分钟；**会话空闲 1 天 / 最长 7 天**（现场决定，覆盖原设计值 8 小时/12 小时，原值作废）；Action Token 4320 分钟。详见 `keycloak/realm-setup.md`。

> **口径说明（以本节为准）**：`keycloak-msia-sso-guide-for-beginners.md` 早期版本记录的 `Max Login Failures=30`、`SSO Session Idle=30 分钟` 两处**已作废**，统一按本节「5 次失败锁 900 秒」「会话空闲 1 天 / 最长 7 天」（2026-11-09 现场决定进一步覆盖了本节的 8 小时/12 小时）。现场实际值仍需用命令复核（见 21.7），但**口径不再并列多个值**。
>
> 会话由 8 小时/12 小时放宽到 1 天/7 天，**方向上是加长，不会踢掉已登录用户**（只有缩短才会）；因此本次变更对在用用户无感。代价是共享机位上的会话存活更久，账号接管风险上升，需按 21.7 的独立事项跟进。
>
> `Verify email OFF` 的理由不是「没有 SMTP」，而是：① 本方案用「统一初始密码 + 首登强制改密」，已能保证账号由本人启用；② AD 导入的 `email` 存在缺失或重复的可能，一旦把 `VERIFY_EMAIL` 设为默认必需动作，这些用户会直接卡在验证页且无法自救；③ 邮箱在本方案中不是受管属性，验证无实际收益。因此**批量开通场景不启用 `VERIFY_EMAIL`**（详见 21.4）。

### 9.4 Clients 与准入组

| Client ID | 类型 | 用途 |
|---|---|---|
| `msia-prod` | confidential | MSIA OIDC（redirect 精确匹配） |
| `bol-prod` | confidential | BOL OIDC（redirect 待 G4 定稿） |
| `sync-client` | confidential | 同步脚本调 Admin REST（service account） |
| `account` | public | 邀请设密邮件落地页 |

准入组：`app-msia` / `app-bol`；新系统按 `app-<system-code>` 建组。详见 `keycloak/clients.md`。

### 9.5 SMTP

**SMTP 是本环境的正式邮箱服务，按正式服务使用。正式参数：**

| 字段 | 值 |
|---|---|
| `host` | `172.19.253.10` |
| `port` | `25` |
| `from` | `ap_sso@inalfa.com` |
| `fromDisplayName` | `Inalfa AME系统统一身份认证` |
| `auth` | `false`（不需要认证） |
| `starttls` | `false` |
| `ssl` | `false` |

> **明文中继说明**：当前为内网明文中继（25 端口、无 TLS、无认证）。若后续邮件网关启用 STARTTLS，需把 `starttls` 改为 `true`（必要时同时调整端口），重启/保存后重新做发信验证；不要在未验证的情况下直接改生产值。

> **事实说明（需现场核对）**：以上是**正式参数口径**，不是候选地址。但「realm `inalfa` 里是否已按这组值完成 Email 配置、是否已实测发信成功」仍需现场核对，**不要当成已完成**。核查方式：
>
> 1. 读配置：`kcadm get realms/inalfa --fields realm,smtpServer,smtpPort,smtpFrom,starttls,ssl`（或控制台 `Realm Settings → Email`）；
> 2. **实测发信（唯一有效判据）**：控制台 `Realm Settings → Email → Test connection` 只验证连通性；真正的判据是**向经办人邮箱实际发一封验证信并确认收到**。可用测试账号触发一封 `execute-actions-email`（会附带一个改密动作），或直接由控制台发送测试邮件。
> 3. 判据写「确实收到邮件」，不写「保存成功 / 连接成功」。

因为 SMTP 可用，以下三条成立：

1. **`execute-actions-email` 可用**：邀请设密、忘记密码等邮件链路成立；`sync_sso_to_keycloak.ps1` 建号分支调用该接口**不再必然失败**，前提是上面第 2 条「实测收到信」已通过（见《方案A落地清单》M09/S07）。
2. **批量开通仍不依赖邮件**：几百人一次性开通采用「统一初始密码（运行时由管理员输入，值不落文档）+ `Temporary=ON` + 首登强制改密」，见第 21 章 21.2。邮件邀请保留给后续零散补开、忘记密码，以及后续新员工自动路径。
3. **批量开通场景不启用 `VERIFY_EMAIL`**：理由见 9.3 与 21.4——不是「发不出邮件」，而是 AD 导入的 `email` 可能缺失/重复，一旦设为默认必需动作会直接卡死用户。

---

## 10. 双轨与单轨切换

完整步骤见 `docs/cutover-runbook.md`，此处只记决策面：

- **双轨期**：OIDC 与本地登录并存，填 secret → `enabled=true` → 保留本地登录 → 重启 → 验证 `/api/auth/config` 与真实登录。观察登录成功率、邮件到达率、权限正确性。
- **单轨切换**（验收后）：MSIA 关 `local_login_enabled` + `hr_sync_enabled`、开 `sso_user_sync_enabled`；BOL 关 `LOCAL_AUTH_ENABLED` + `PASSWORD_SELF_SERVICE_ENABLED`；然后 `DELETE FROM CN_IE_BOL_AuthToken WHERE source='local'`。
- 切换窗口内只改上述加粗项，每项改动前后各做一次冒烟；任一项可随时改回。

---

## 11. 安全与运维要点

- **已实施**：OIDC 授权码 + PKCE S256；state/nonce 一次性消费；JWKS 验签；OTK 60 秒单次消费；本地 Token 不进 URL；BOL 中央停用回写 + 无条件清 Token；8443 防火墙收敛；同步账号 `sso_sync_svc` 仅五表 DML 无 DDL；口令/secret 不落文档（DPAPI `credentials.xml` 或服务环境变量）。
- **应急**：`disable_user_now.ps1` 紧急停号；`health_check.ps1` 健康检查；回退=关闭 OIDC 开关恢复本地登录；kcadmin 为 master 域 break-glass，口令物理封存。
- **运维语义**：中央人员表是人员状态唯一事实来源。BOL 后台/数据库手工置 `INACTIVE` 会被下次同步按中央表覆盖；`ACTIVE` Token 复活仅在中央表仍为 `status=1` 时发生，属预期复职。

---

## 12. 测试与交付验证

- **结论**：QA Round 1 major 全修复、Round 2 最终 `IS_PASS: YES`（功能级证据 7/7）。BOL `manage.py check` 通过、users 35 项测试通过、`makemigrations users --check` 无差异；MSIA 16 项 SSO 测试通过、应用导入成功；两前端构建通过。
- **测试资产**：`MSIA Report/backend/tests/test_sso_oidc.py`、`BOL管理系统/backend/apps/users/tests/test_sso_oidc.py`。
- **既有技术债（非本次引入，交接须知）**：全项目 `makemigrations --check` 仍有 `budget_bol`/`dynamic_bol`/`reports` drift，需业务/DBA 单独立项；BOL 静态 OIDC 配置暂无环境变量覆盖；BOL 生产配置面（DEBUG、SECRET_KEY、CORS）建议后续收严。

---

## 13. 同机多系统部署模式（IIS SNI + ARR）

> 适用场景：多个业务系统经同一台 IIS（`IRSCnKettle01`）按 `<系统名>.ap.inalfa.local` 区分入口。ARR 反代不要求后端同机。

### 13.1 形态

```text
用户浏览器 -> DNS：*.ap.inalfa.local -> IIS 443 SNI 分流（一张通配符证书）
  -> ARR 按 Host 头反代 -> 各系统端口（Keycloak 8443 / MSIA 8078 / BOL / 未来系统）
```

新系统接入 = **新 IIS 站点 + 一条 ARR 规则 + 一个 Keycloak client + 一个准入组**（+ 可选 UserMap）。中央表和同步链路不动。

### 13.2 端口与主机名台账

| 系统 | 对外主机名 | 部署机 | 经 ARR? |
|---|---|---|---|
| IIS ARR（统一入口） | 443 SNI 分流，通配符证书 | IRSCnKettle01 | — |
| Keycloak | `sso.ap.inalfa.local` | IRSCnKettle01 | 同机回环 `https://127.0.0.1:8443` |
| MSIA Report | 现 `172.26.2.203:8078`；未来 `msia.ap.inalfa.local`（U1） | IRSCNYTFINEREPORT | 上域名后跨机反代 8078 |
| BOL 管理系统 | 待定稿（U2/G4） | 待定 | 定稿后反代 |
| 帆软（既有） | `SRV-APSH-FNR-1P`（裸名/FQDN，自有证书） | SRV-APSH-FNR-1P | 不经本 ARR |

登记规则：① 主机名统一 `<系统名>.ap.inalfa.local`；② 端口全环境唯一（避开 8078/8090/8443/9000）；③ 每系统独立 IIS 站点 + 应用池；④ 台账随接入更新。

### 13.3 注意点

- **SNI**：每站点绑定必须勾 SNI + 填主机名。当前 IRSCnKettle01 上 443 净空（帆软在另一台机、不经本 ARR），直接绑定即可；将来收拢外部站点时逐个绑定并回归验证。
- **证书**：一张通配符覆盖所有系统，续期只维护一张；但续期=全系统同时换绑，须低峰窗口 + 先预装验证；通配符私钥是“一把钥匙开所有门”，重点保护。
- **ARR 规则**：精确 Host 在前、通配 Host 兜底放最后；每条规则“停止处理后续规则”；必须转发 `X-Forwarded-Proto/Host/For`（Keycloak `hostname-strict` 依赖）；长报表/大导出调大 proxy timeout 与上传限制；实时场景开 WebSocket。
- **Keycloak 侧**：每系统独立 client + redirect 精确匹配，天然隔离；单 realm 共享用户池是设计目标（SSO 免密跨系统、登出经 frontchannel logout 传播）；realm 级参数全局统一；sync-client 共享，多系统并行同步注意错峰。
- **故障域**：ARR/IIS 故障 = 所有域名入口不可达（后端不受影响）。缓解：各系统保留 IP:端口直连兜底、每系统 ≤2 个 break-glass 本地管理员、整机备份、ARR 故障时本机可经 `https://127.0.0.1:8443` 排障。
- **运维**：每站点独立日志目录；证书到期日/端口/主机名统一登记在 13.2 台账；IIS 补丁重启纳入统一变更窗口。

### 13.4 同机新系统上线检查单

1. 端口登记；2. DNS 加 A 记录（或确认泛解析）；3. IIS 建站点+应用池，绑 443 + 主机名 + SNI + 通配符证书；4. ARR 规则（精确 Host、三件套头、停止处理）；5. Keycloak 建 client + 准入组 + secret（按 14.2）；6. 冒烟四项：直连后端、经域名访问、OIDC 全链路、其他系统不受影响；7. 更新 13.2 台账。

---

## 14. 新系统接入统一身份认证实施清单

### 14.1 接入前确认

本地用户表结构（用户名字段/状态字段/角色字段/唯一约束）；是否有长效本地 Token；访问入口（内网 IP:端口或 ARR 域名）；是否保留本地登录作双轨回退；最低权限自动建档角色。

### 14.2 Keycloak 侧

1. 建 client `<system-code>-prod`（confidential，Standard Flow ON，Direct access grants OFF，PKCE S256）；
2. redirect URI 精确匹配 `<系统入口>/api/auth/oidc/callback`，配 post logout redirect 与 Web origins；
3. 生成 secret 登记 `credentials.xml`；
4. 建准入组 `app-<system-code>`，给首批用户加组。

### 14.3 后端侧

1. 参考 `MSIA Report/backend/app/core/oidc.py` 或 `BOL管理系统/backend/apps/users/oidc.py` 增加 OIDC 核心模块；
2. 增加端点：`/api/auth/config`、`/api/auth/oidc/login`、`/api/auth/oidc/callback`、`/api/auth/oidc/token`；
3. 身份解析按 6.4 顺序（groups → UserMap → preferred_username → 本地表 → 自动建档）；
4. OIDC 成功后签发系统原有本地凭证，OTK 换凭证，Token 不放 URL；
5. 配置开关默认 `oidc_enabled=false`。

### 14.4 前端侧

拉 `/api/auth/config`；加“统一身份登录”按钮；公开回调页 `/oidc/callback`；OTK 调 `/api/auth/oidc/token`；按开关显隐本地登录/注册/密码自助入口。

### 14.5 数据库与同步侧

本地用户名与中央 `login_name` 不一致 → 插 `CN_AME_SSO_UserMap`；有长效 Token → 加来源标记列（如 `source`）；实现中央状态回写（0→禁用+清 Token，1→恢复），建议每小时；**不要直接写 `CN_AME_SSO_User`**。

### 14.6 测试清单

至少覆盖：OIDC 关闭时 login 返回 503；本地开关关闭返回 403；无效 state 400；OTK 假码 400；OTK 单次消费；缺准入组 403；UserMap 命中；无映射回落；自动建档最低权限；本地禁用 403；中央停用传导+清 Token；游客/特殊通道不受开关影响。

### 14.7 上线步骤

1. `oidc_enabled=false` 先发布代码；2. 配 client/组/secret；3. 开 `oidc_enabled=true` 保留本地登录；4. 小范围全链路验证；5. 观察至少一个完整业务周期；6. 按单轨矩阵关本地登录与密码服务；7. 作废旧本地 Token。

---

## 15. 当前上线门项（仅未决项）

| 门项 | 状态 |
|---|---|
| keycloak 库登录名/排序规则 | 待确认：需专用登录 + USER/db_owner + CS 排序规则；勿用 sysadmin 的 ytview |
| Keycloak 部署 | 手册就绪（`docs/keycloak-deploy-runbook.md`），待执行 |
| 人员 MERGE | `04_flip_manual_source.sql` 就绪（预检→转换→MERGE→核对），待执行 |
| realm/client/secret 初始化 | 待 KC 起来后按 `realm-setup.md`/`clients.md` 执行 |
| CA 证书 → DNS/IIS ARR | 工单已提交，证书待签发；IIS+ARR 需 IT 安装于 IRSCnKettle01 |
| BOL 固定内网地址（G4） | 待用户提供，定稿 `bol-prod` redirect_uri |
| MSIA 8078 与 `config.ini [server] port=8000` 核对 | 待核对 |
| 双轨切换与回滚演练 | 步骤已明确（cutover-runbook）；演练按用户要求暂缓 |
| MSIA 姚雷本地禁用 | 业务项，默认不自动恢复，按需设置 |

---

## 16. 交付物索引

| 交付物 | 路径 |
|---|---|
| 主实施方案 | `统一身份认证实施方案_MSIA与BOL系统.md` |
| 实施工件说明 | `统一身份认证实施/README.md` |
| SQL 脚本（建表/授权/种子/转换/对账） | `统一身份认证实施/scripts/sql/` |
| PowerShell 脚本（AD 同步/KC 同步/停号/健康检查） | `统一身份认证实施/scripts/powershell/` |
| 端到端登录证据采集脚本 | `统一身份认证实施/scripts/collect-sso-login-evidence.ps1` |
| 端到端登录证据包（evidence.md + 原始文件） | `统一身份认证实施/evidence/<yyyyMMdd-HHmmss>/` |
| Keycloak 配置工件 | `统一身份认证实施/keycloak/`（keycloak.conf、realm-setup.md、clients.md） |
| 操作手册 | `统一身份认证实施/docs/`（keycloak-deploy-runbook、cutover-runbook、rollback-runbook、cert-request-guide、**msia-redeploy-checklist**、**app-certificate-trust**、**方案A落地清单**） |
| MSIA 部署包 | `MSIA Report/dist/MSIA-deploy-20261105.zip`（仅 `msia_server.exe` + `_internal`，不含 config.ini/storage） |
| MSIA 代码 | `MSIA Report/backend/app/core/oidc.py`、`app/api/auth.py`、`app/services/sso_identity.py`、`app/services/sso_user_sync.py` |
| BOL 代码 | `BOL管理系统/backend/apps/users/`（oidc.py、oidc_views.py、sync_sso_status.py、migrations/0005） |

---

## 17. 现场踩坑实录（2026-11-05）

> 每一条按「现象 → 根因 → 正确做法 → 可复用检查点」写，判据命令可直接粘贴。后续接入系统遇到同类症状，按这里对号入座，不要重新试错。

### 17.1 Keycloak 25.0.6

#### 17.1.1 没有 `bootstrap-admin` / `tools` 命令

- **现象**：按 26.x 文档执行 `kc.bat bootstrap-admin user add ...` 报命令不存在；控制台里也没有 Tools 菜单。
- **根因**：`bootstrap-admin` 与 `tools` 是 26.x 新增，25.0.6 时代没有。
- **正确做法**：初始管理员只能靠环境变量在**空库首次启动**时创建：
  `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` → 启动一次 → 管理员生成后**立即清除这两个变量并重启**；**绝不能**写进 NSSM 的 `AppEnvironmentExtra`。
- **检查点**：

```bat
kc.bat --help | findstr /i "bootstrap"        :: 应无输出
nssm get <服务名> AppEnvironmentExtra          :: 不得出现 KEYCLOAK_ADMIN
```

#### 17.1.2 `hostname-strict-https` 在 25.0 已移除

- **现象**：`kc.bat build` 报 `Unrecognized option: hostname-strict-https`。
- **根因**：该配置项 25.0 已删除，HTTPS 由 `hostname-strict` + `proxy-headers` + 端口配置共同决定。
- **正确做法**：删掉该行，用 `hostname-strict=true` + `proxy-headers=xforwarded` + `hostname=<正式域名>` + `https-port=8443`。
- **检查点**：

```bat
kc.bat build                                  :: 不得再出现 Unrecognized option
kc.bat show-config | findstr /i "hostname"    :: hostname 应为正式域名
```

#### 17.1.3 用 `kcadm` 改 client 会冲掉 `redirectUris` / `webOrigins`

- **现象**：`kcadm update clients/<id> -s redirectUris=[...]` 执行后，原有 URI 消失、`webOrigins` 被清空。
- **根因**：`-s` 对数组字段是**整体替换**，不是追加。
- **正确做法**：这两个字段只在控制台 Clients → 对应 client 的**多行输入框**里增删（界面天然是追加/合并）；确实要用 `kcadm`，先 `get` 导出完整数组，改完整体写回。
- **检查点**：

```bat
kc.bat kcadm get clients -r inalfa -q clientId=msia-prod --fields id,redirectUris,webOrigins
```

判据：改动前后条目数不得减少。

#### 17.1.4 `Client not found` 与 `Invalid parameter: redirect_uri` 的区分

- **现象 A**：授权页直接报 `Client not found`；**现象 B**：报 `Invalid parameter: redirect_uri`。
- **根因**：A = client 不存在，或 `clientId` 与请求不一致（最常见是复制粘贴时带了**尾部空格/换行**）；B = client 存在，但 `redirect_uri` 不在白名单（端口、大小写、尾斜杠任一不同即不匹配）。
- **正确做法**：A 用精确查询 + 长度复核；B 用浏览器地址栏**完整复制**的 URL 与白名单逐字符对照（不要手敲）。
- **检查点**：

```bat
:: 1) 精确查询（模糊查询会把带空格的同名 client 也列出来，容易误判）
kc.bat kcadm get clients -r inalfa -q clientId=msia-prod --fields clientId
:: 2) 列出所有相似项，肉眼查尾部空白
kc.bat kcadm get clients -r inalfa --fields clientId | findstr /i msia
```

判据：`msia-prod` 长度应为 9；返回值长度对不上就是有隐藏字符，**删除重建**，不要试图“改名修好”。

### 17.2 证书与 TLS（本次最耗时的一段）

#### 17.2.1 自签证书 + Python 默认校验

- **现象**：应用日志 `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`；浏览器却能打开（用户点了“继续访问”）。
- **根因**：浏览器有例外机制，Python `ssl.create_default_context` 只认系统/自带根库，自签与企业根都不在其中。
- **正确做法**：给**运行该进程的环境**设 `SSL_CERT_FILE`（PEM 路径）。注意三点：
  1. `$env:SSL_CERT_FILE` 只对当前会话有效，**必须与启动 exe 的那个会话/服务是同一个环境**；
  2. 以 NSSM 服务运行时写进 `AppEnvironmentExtra`（或服务包装脚本），改完重启服务；
  3. **禁止** `verify=False`、全局 `ssl._create_unverified_context`。
- **检查点**：

```powershell
# 控制台方式：同一窗口内设置后再启动
$env:SSL_CERT_FILE='C:\certs\inalfa-ca.pem'
.\msia_server.exe

# 服务方式：确认变量真的进了服务环境
nssm get <服务名> AppEnvironmentExtra
```

判据：日志不再出现 `CERTIFICATE_VERIFY_FAILED`，且 `/api/auth/config` 正常返回。

#### 17.2.2 只签 `CN=localhost`，而 Keycloak `hostname` 是 IP

- **现象**：`certificate verify failed: IP address mismatch, certificate is not valid for '172.26.2.203'`。
- **根因**：证书只有 `CN=localhost`，没有 IP SAN；而 Keycloak 的 `hostname` 配成了服务器 IP，客户端按 IP 校验。
- **正确做法**：证书 SAN 同时包含 `DNS:localhost`、`DNS:<正式域名>`、`IP:<服务器IP>`；Keycloak `hostname` 用域名而不是 IP。
- **检查点**：

```powershell
certutil -dump C:\certs\kc.pem | findstr /i "Subject Alternative Name DNS IP"
```

判据：上述三类（localhost、域名、IP）都在 SAN 列表里。

#### 17.2.3 由此派生的“discovery 通、换 token 不通”

- **现象**：拉 `/.well-known/openid-configuration` 成功，紧接着换 token 失败（证书不匹配或超时）。
- **根因**：服务端用 `https://127.0.0.1:8443` 拉 discovery（主机名匹配证书里的 localhost），但 Keycloak 依据 `hostname` 返回的 `token_endpoint` 是**另一个主机名/IP**，第二次请求换了主机 → 证书不匹配。这是“同一套配置两个结果”的典型分裂症状。
- **正确做法**：证书 SAN 覆盖**所有可能被访问的主机名/IP**；根治办法是 issuer、hostname、redirect_uri、证书四处都用同一个域名。
- **检查点**：

```powershell
(Invoke-RestMethod 'https://127.0.0.1:8443/realms/inalfa/.well-known/openid-configuration').token_endpoint
(Invoke-RestMethod 'https://127.0.0.1:8443/realms/inalfa/.well-known/openid-configuration').issuer
```

判据：返回的 endpoint 主机名必须在证书 SAN 内。

#### 17.2.4 `SSL_CERT_FILE` 是**替换**而不是追加

- **现象**：设置企业根后，访问 Keycloak 正常，但访问其他公共 HTTPS 站点（外部 API、邮件网关）开始报证书错误。
- **根因**：`SSL_CERT_FILE` 取代 openssl 默认根集合，不是合并。
- **正确做法**：做一份“企业根 + 公共根”的合并 PEM，长期指向它。
- **检查点**：

```powershell
Get-Content C:\certs\corp-root.pem, C:\certs\cacert.pem | Set-Content C:\certs\combined-ca.pem -Encoding ascii
$env:SSL_CERT_FILE='C:\certs\combined-ca.pem'
```

判据：既通 Keycloak，也不破坏其他 HTTPS 出站。更细的三种信任方式与打包 exe 适用性见 `docs/app-certificate-trust.md`。

#### 17.2.5 四件套必须同时变更（本次全部故障的共同成因）

`issuer` / `redirect_uri` / Keycloak `hostname` / 证书 SAN（含证书本身）——**只改其中一项，必然在授权或回调环节失败**。
检查点：改动前先写一张四行对照表（现值 / 目标值），四项一次改完，再按 17.3.1 的顺序验证，不要边改边试。

### 17.3 应用侧（MSIA）

#### 17.3.1 exe 比源码旧 → 新路由不存在

- **现象**：Keycloak 正常回跳，MSIA 却返回 FastAPI 的 `{"detail":"Not Found"}`。
- **根因**：PyInstaller 把 Python 模块编进产物，服务器跑的是**改造前**的 exe；源码改了不重新打包等于没发布。代码里路由存在（`/api/auth/oidc/callback`），但 exe 里没有。
- **正确做法**：以**路由清单**为发布判据，不是“进程能起来”“首页能打开”。
- **检查点**：

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/openapi.json).paths.PSObject.Properties.Name |
  Where-Object { $_ -like '*oidc*' }
```

判据：必须出现 `/api/auth/oidc/login` 与 `/api/auth/oidc/callback`；同时 exe 修改时间应晚于源码最后一次改动。

#### 17.3.2 服务器 `config.ini` 才是生效文件，整目录覆盖会带回旧配置

- **现象**：换上新 exe 后 OIDC 仍未生效（`/api/auth/config` 返回 `oidc_enabled=false`），严重时数据库/邮件配置莫名变化。
- **根因**：程序按 **exe 同目录 → `_internal` → 当前目录 → backend** 的顺序找 `config.ini`；整目录部署把构建机（或旧版无 `[oidc]` 段）的配置带回去，且它优先级最高。
- **正确做法**：只替换 `msia_server.exe` + `_internal\`，**保留现场 `config.ini` 与 `storage\`**；`[oidc]` 段手工追加。部署包不要打包 config.ini（本次 `MSIA-deploy-20261105.zip` 已剔除）。完整步骤见 `docs/msia-redeploy-checklist.md`。
- **检查点**：

```powershell
Get-Item D:\MSIA\config.ini | Select-Object LastWriteTime,Length   # 部署后应保持不变
Select-String D:\MSIA\config.ini -Pattern '^\[oidc\]'
```

判据：`[oidc]` 段存在，且 `/api/auth/config` 返回的开关与文件一致。

#### 17.3.3 端口认知混乱：8000 监听 vs 8078 对外

- **现象**：浏览器被重定向到 `:8078` 回调 404，而本机 `:8000` 一切正常。
- **根因**：真正监听端口来自 `[server] port`（现网 8000）；8078 只写在 `redirect_uri` / `system_url` 文本里，是否可达取决于**有没有反向代理**，代码里没有任何地方监听 8078。
- **正确做法**：先判定 8078 是否有监听、是否保留 `/api` 前缀，再决定 `redirect_uri` 用 8078 还是 8000；两种情况下 `redirect_uri` 都必须与 Keycloak 的 Valid redirect URIs **逐字符一致**。
- **检查点**：

```powershell
netstat -ano | findstr LISTENING | findstr :8078
Test-NetConnection 172.26.2.203 -Port 8078 -InformationLevel Quiet
try { Invoke-RestMethod 'http://172.26.2.203:8078/api/auth/config' } catch { $_.Exception.Message }
```

判据：8078 能返回 `/api/auth/config` 的 JSON → 反代正常且保留前缀；返回 404/502 → 改走 8000 或修 ARR 规则。

#### 17.3.4 配置语法错误 → 段静默不加载

- **现象**：明明写了 `[oidc] enabled=true`，接口仍返回 false。
- **根因**：段名大小写/拼写错误（`[OIDC]`）、键名前有空格、值带引号、文件被存成 GBK 且含中文注释导致解析异常——ini 解析失败时整段按默认值（false）处理，**不报错**。
- **正确做法**：段名小写方括号、键值不加引号、文件 UTF-8；改完用接口回读验证，而不是看文件“写了什么”。
- **检查点**：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/auth/config
```

判据：返回的 `oidc_enabled` 与文件一致；不一致先查语法与生效位置（见 17.3.2）。

---

## 18. 当前 Ready 状态与并行工作清单（2026-11-05）

### 18.1 Ready 矩阵

状态口径：**Ready** = 代码或对象已就绪且自测通过；**待配置** = 代码就绪，缺值；**待验证** = 依赖现场证据确认；**阻塞** = 缺外部前置，无法推进到端到端。

| 维度 | MSIA Report | BOL 管理系统 |
|---|---|---|
| 代码 | **Ready**：路由、PKCE、JWKS、OTK、身份解析齐全；11-05 已重打包并校验 `PYZ` 内含 `/oidc/login`、`/oidc/callback` | **Ready**：`apps/users/oidc.py` + `oidc_views.py` + `sync_sso_status`；`users` 54 项测试通过；已有 env 覆盖与 CORS 白名单 |
| 配置 | **待配置**：`client_secret` 空；`redirect_uri` 的 8078/8000 未定稿；`enabled=false` | **待配置**：`client_secret` 空；`redirect_uri` 仍是 `127.0.0.1:8090` 占位；`enabled=False` |
| Keycloak 侧对象 | **待验证**：`msia-prod` 已重建（现场）；`app-msia` 组、`groups` mapper 需现场确认；用户是否入组未知 | **阻塞**：`bol-prod` 仅存在于文档，**无任何创建脚本/记录**；`app-bol` 组与 `groups` mapper 同样只在 `clients.md` 描述 |
| 证书信任 | **阻塞**：等 CA 签发；过渡期用自签须 `SSL_CERT_FILE`，且 SAN 需含域名+IP | **阻塞**：同一张 CA；服务环境同样需注入 `SSL_CERT_FILE` |
| 端到端联调 | **待验证**：exe 已就绪，等配置+证书+8078 结论 | **阻塞**：client/组未建，无法发起授权 |

### 18.2 MSIA 除了等 CA 还差什么

**现在就能做（不依赖外部）**
1. 部署 11-05 新包（只换 `exe + _internal`），按 `msia-redeploy-checklist.md` 合并 `[oidc]`，`enabled` 保持 false。
2. 用 `/openapi.json` 确认两条 oidc 路由存在；`/api/auth/oidc/callback` 不带参数应 400。
3. 若先用自签过渡：设 `SSL_CERT_FILE`（合并 PEM），并确认证书 SAN 含 `localhost`、域名、IP。
4. 核对 `CN_AME_SSO_User` / `_UserMap` 数据与 13 人名单（执行只读校验 `91_usermap_integrity_checks.sql`）。

**需现场确认**
1. 8078 是否有反代、是否保留 `/api` 前缀（决定 `redirect_uri` 终值）。
2. `app-msia` 组是否已建、首批用户是否已入组、client 上 `groups` mapper 是否已加。
3. Keycloak 实际 `hostname` / `issuer` 与 `config.ini` 是否一致。

**必须等外部**
1. CA 证书签发 + 导入信任库。
2. `msia-prod` 的 secret 下发（建议走环境变量 `OIDC_CLIENT_SECRET`，不落盘）。
3. DNS 与 IIS/ARR 规则（若上 `msia.ap.inalfa.local`）。

### 18.3 BOL 除了等 CA 还差什么

**现在就能做（不依赖外部）**
1. 在 Keycloak 建 `bol-prod`（confidential、Standard Flow、PKCE S256、Direct grants OFF），建 `app-bol` 组，加 `groups` mapper（full path 关闭）。
2. 定稿访问地址后填 `redirect_uri`；未定稿前先用服务器真实 IP/端口，**不要**留 `127.0.0.1:8090`。
3. secret 用系统环境变量 `OIDC_CLIENT_SECRET` 注入（优先级 env > `db_config.ini` > 默认）。
4. 取消 `cors_allowed_origins` 注释并填正式来源，替换当前“留空=全放行”。
5. 按 `package.bat` / `deploy.bat` / `build_exe.ps1` 重新打包，把含 OIDC 的版本先以 `enabled=False` 发上去。

**需现场确认**
1. BOL 正式访问地址（U2/G4 未决）与部署机端口。
2. 是否已服务化（NSSM）；若已服务化，`AppEnvironmentExtra` 需同时注入 `OIDC_CLIENT_SECRET` 与 `SSL_CERT_FILE`。
3. `migrations/0005_authtoken_source.py` 是否已在生产执行（`AuthToken.source` 列存在与否）。

**必须等外部**
1. CA 证书与信任库。
2. DNS / ARR（BOL 域名未定稿）。
3. `bol-prod` secret 由 Keycloak 侧生成下发。

### 18.4 BOL 当前口径（以代码/配置实读为准）

| 项 | 实际状态 | 依据 |
|---|---|---|
| `[oidc] enabled` | `False` | `backend/db_config.ini` |
| `client_secret` | 空；推荐 `OIDC_CLIENT_SECRET` 环境变量（env > ini > 默认） | `db_config.ini`；`bol_platform/settings.py` 的 `_apply_env_overrides` |
| `redirect_uri` | `http://127.0.0.1:8090/api/auth/oidc/callback`（占位） | `db_config.ini`；`settings.py` 默认值同款 |
| `bol-prod` client | **只在文档里存在**（`keycloak/clients.md`、runbook、控制台手册、README），无创建脚本/JSON | 全仓检索仅文档命中 |
| `app-bol` 组 | 仅文档描述，未确认已建 | `clients.md` |
| `groups` mapper | 仅文档描述（`full path` 建议关闭） | `clients.md` |
| 回调路由 | `path('oidc/callback/')` → 实际 `/api/auth/oidc/callback/`（**带尾斜杠**） | `apps/users/auth_urls.py`；`bol_platform/urls.py` 的 `api/auth/` 前缀 |
| 准入组 | `app-bol` | `db_config.ini` |
| 开关命名 | `local_auth_enabled`（MSIA 叫 `local_login_enabled`） | `db_config.ini [auth]` |

### 18.5 BOL 与 MSIA 的差异点（接入新系统时容易踩）

1. **回调尾斜杠**：BOL 路由是 `/api/auth/oidc/callback/`，配置里没有尾斜杠 → 依赖 Django `APPEND_SLASH` 301 跳一次。Keycloak 白名单里建议**两种写法都登记**（带斜杠与不带斜杠），避免 301 后的地址不在白名单。
2. **无 refresh**：两系统都只在回调时交换一次 token，不使用 refresh token（本地凭证各自管理生命周期，MSIA JWT 30 天；BOL `AuthToken` 由表管理）。
3. **本地凭证清理**：BOL 有 `AuthToken` 实体表，单轨切换后可直接 `DELETE FROM CN_IE_BOL_AuthToken WHERE source='local'`；MSIA 是无状态 JWT，无法“删表作废”，只能换 `jwt_secret_key`（会影响全部用户，需窗口）。
4. **停用回写**：BOL 每小时全量回写且**无条件清 Token**；MSIA 每次请求查库校验 `Status`，停用即时生效、无需回写任务。
5. **配置读取**：BOL 是 Django 启动时模块级常量（改配置需重启）；MSIA 是 pydantic Settings（同样需重启，但环境变量优先级更高）。
6. **游客通道**：BOL 保留 guest 登录，不受 OIDC 开关影响；MSIA 无此通道。

### 18.6 可与 CA/DNS/ARR 并行推进的清单

| # | 工作项 | 负责人角色 | 前置条件 | 完成判据 |
|---|---|---|---|---|
| 1 | AD→SSO 同步计划任务 `SSO_AD_Import` | IT 运维 | 五表就绪；`sync_ad_to_sso.ps1` + 专用 SQL 账号（仅五表 DML） | 计划任务每日成功；`CN_AME_SSO_SyncLog` 有当日 `SUCCESS` 记录 |
| 2 | UserMap 灌数与完整性校验 | 数据/业务负责人 | 13 人名单定稿；跨库 SELECT 权限 | `91_usermap_integrity_checks.sql` 九组查询全部符合预期；口径见 20.4（本地账号先存在，UserMap 负责指向） |
| 3 | 双轨联调测试账号与用例 | 测试/业务 | `msia-prod`/`bol-prod`、`app-msia`/`app-bol` 组、可登录账号 | 用例覆盖：首次建号、UserMap 命中、无组 403、停用传导、OTK 过期 |
| 4 | BOL 打包与预发布 | 后端负责人 | 依赖版本锁定、Python 版本与生产一致 | `enabled=False` 下冒烟通过；`/api/auth/config` 正常 |
| 5 | 回滚演练（软/硬） | 运维 | 备份就绪、维护窗口 | 软回滚 5 分钟内恢复；硬回滚整目录还原后业务正常 |
| 6 | 台账与封口项 | 项目负责人 | 各系统地址/端口/证书到期日定稿 | 13.2 台账更新；第 15 章门项清零 |

---

## 19. 交底结论

当前统一身份认证方案已经形成可复制 pattern：

1. **中央人员表 + Keycloak** 负责身份和密码；
2. **OIDC 授权码流 + PKCE + OTK** 负责安全登录；
3. **各系统继续签发本地凭证**，下游鉴权零改动；
4. **开关化双轨**保证可回退；
5. **中央状态回写 + 清 Token** 堵住长效本地 Token 的离职缺口；
6. **多系统同机部署**按第 13 章模式（IIS SNI + ARR + 一张通配符证书）扩展，新系统按第 14 章清单接入，不需要改中央表结构，只需增加 client、组、映射和本系统 OIDC 端点。

---

## 20. 端到端登录验证实录（2026-11-05）

> 证据包：`统一身份认证实施/evidence/<yyyyMMdd-HHmmss>/evidence.md`（含原始文件）。
> 复采脚本：`统一身份认证实施/scripts/collect-sso-login-evidence.ps1`（只读、幂等、PS 5.1 兼容）。

### 20.1 已确认事实

| 项 | 实测值 |
|---|---|
| 验证时间 | 2026-11-05 21:33:46 – 21:34:09（精确到秒见 20.2 实证日志） |
| 服务器 | `IRSCnKettle01` / `172.26.2.203` |
| Keycloak | 25.0.6，安装于 `C:\keycloak`，HTTPS 8443，PKCS/PEM 证书模式，证书文件 `C:\keycloak\conf\server.crt.pem` |
| realm / client | `inalfa` / `msia-prod` |
| 登录用户 | `ligu`，`local user id=2414`（本地已存在账号，非自动建档） |
| 身份解析 | `ligu` 无 `UserMap` 映射，回落 `preferred_username` 分支生效 |
| MSIA | `C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe`，监听 8078 |
| 回调地址 | `http://172.26.2.203:8078/api/auth/oidc/callback` |
| 来源 IP | Keycloak Event 页记录 `10.41.0.64`；MSIA 控制台请求记录 `10.41.10.64`（两者口径不一致，需现场核对客户端真实地址与代理链，不影响成功结论） |
| 证书 SAN | `IPAddress:172.26.2.203`、`DNSName:localhost`、`DNSName:sso.ap.inalfa.local` |
| 证书有效期 | 2026-11-05 → 2029-02-07 |
| 证书信任 | 进程环境变量 `SSL_CERT_FILE=C:\keycloak\conf\server.crt.pem` |
| 登录结果 | 通过 Keycloak 登录页认证后成功进入 MSIA |

**判定结论：MSIA 侧 OIDC 链路已验证通过**，覆盖授权跳转、回调验签、OTK 换 JWT、业务接口鉴权四段，**前端到后端这一跳也已验证，不只是后端打通**。

### 20.2 四段式证据链（MSIA 控制台实证）

以下为现场 MSIA 控制台原文摘录（2026-11-05 21:33–21:34，请求来源 IP `10.41.10.64`）。OTK 为一次性码（已消费），按“不打印 secret”约束脱敏。

| 阶段 | 时间 | 实证日志（原文） | 判读 |
|---|---|---|---|
| 1. 授权跳转 | 21:33:46 | `app.api.auth:oidc_login:141 - OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)`；`GET /api/auth/oidc/login 302` | state/nonce/PKCE verifier 已入库，授权跳转已发起 |
| 2. 回调验签 | 21:34:09 | `app.services.sso_identity:resolve_or_create:118 - OIDC 身份解析: ligu 无 UserMap 映射, 回落 preferred_username`；`app.api.auth:oidc_callback:223 - OIDC 登录成功: ligu (local user id=2414)`；`GET /api/auth/oidc/callback?...iss=https%3A%2F%2F172.26.2.203%3A8443%2Frealms%2Finalfa&code=... 302` | issuer 回显校验通过，code 换 token；身份解析命中本地 `ligu`（id=2414） |
| 3. OTK 换 JWT | 21:34:09 | `GET /oidc/callback?otk=<一次性码，已消费，脱敏> 200`；`POST /api/auth/oidc/token 200` | 前端用 OTK 换取后端 JWT 成功 |
| 4. 业务接口鉴权 | 21:34:09 之后 | `/api/dashboard/analytics`、`/api/users`、`/api/system-settings/grouped`、`/api/archive/projects` 等均 `200` | 携带 JWT 访问受保护接口全部通过，证明前端到后端这一跳也已验证 |

Keycloak 侧对应事件为 `LOGIN → CODE_TO_TOKEN → VERIFY_PROFILE → UPDATE_PROFILE`，client 全部为 `msia-prod`，其中 `LOGIN` 与 `CODE_TO_TOKEN` 是本次成功登录的核心证据。`<待补：21:34 用户的 Keycloak userId UUID，取自 evidence.md 第 1b 项>`。

### 20.3 旁证与噪声

- **下午旁证**：2026-11-05 15:11–15:19 另有一批 `LOGIN`，来源 IP `10.41.0.96`，用户 UUID `83cbae96-03fd-4f5e-b4ee-ed8182acdb4c`。该批为链路联调旁证，不是本次 21:34 成功登录的判定依据。
- **20:32 LOGIN_ERROR**：IP 显示 `0.0.0.0:0:0:0:0:0:1`（本机回环），User 显示 `No user details`。**判定为本机回环来源，非用户登录路径，不构成用户登录失败的证据**。该条的具体 `error` 字段以 Keycloak Event 页 error 列或 Keycloak 日志原文为准；本实录不臆测错误码，采集脚本会原样导出该字段与日志上下文（见 `01-login-error-2032.txt`、`02-keycloak-login-error-2032.txt`）。

### 20.4 灌用户口径（已落定）

本次实证中 `local user id=2414` 证明 `ligu` 是**本地已存在账号、不是自动建档**；同时 `无 UserMap 映射, 回落 preferred_username` 证明兜底分支生效。

正式期口径：

1. **本地账号必须先存在**，`CN_AME_SSO_UserMap` 负责把 IdP 身份指向本地账号；
2. **无映射时回落 `preferred_username`** 是已验证的兜底路径，但它解决不了同名/大小写冲突，所以 `CN_AME_SSO_UserMap` 仍需补齐；
3. 自动建档代码保留，但正式期不作为账号来源。

### 20.5 遗留风险 / 待办

| 风险项 | 现状 | 修复方式 | 当前影响 |
|---|---|---|---|
| MSIA `[security] jwt_secret_key` 长度不足 | 当前仅 23 字节，触发 `InsecureKeyLengthWarning`（低于 RFC 7518 SHA256 的 32 字节建议底线） | 生成 ≥32 字节随机密钥替换 `config.ini` / 环境变量后重启；重启后现有登录态失效，需重新登录 | 当前仅一个测试账号，代价为零 |

### 20.6 待现场确认与待补字段

- **user profile 必填字段 → 待现场确认**：Keycloak realm 的 `email` / `firstName` / `lastName` 是否必填，以及首次登录时是否实际出现资料补全页；本项只做只读检测与记录，不修改 realm 配置，**不替用户下结论**。
- 从 evidence.md 粘贴补齐：
  1. 21:34 窗口每条事件的 `time` / `type` / `clientId` / `username` / `userId(UUID)` / `ipAddress`（第 1b 项）；
  2. 20:32 `LOGIN_ERROR` 的 `error` 字段与日志详情（第 1c 项、第 2 项）；
  3. Keycloak 日志命中行与文件 `LastWriteTime`（第 2 项）；
  4. MSIA 进程 `Id` / `Path` / `StartTime`、8078/8443 监听行、exe `LastWriteTime` 与字节数（第 4 项）；
  5. 证书 `Valid from/until` 原文与 SAN 三行（第 5 项）；
  6. `config.ini` 中 `oidc.enabled` / `issuer` / `client_id` / `redirect_uri` / `required_group` / `auto_create_user`（第 6 项，secret 已脱敏）；
  7. 本地用户表 SQL 输出：`CreatedAt`、`PasswordHash`、UserMap 命中情况（第 8 项，作为 `id=2414` 的佐证）；
  8. IP 口径核对结论（`10.41.0.64` 与 `10.41.10.64` 的差异来源）。

---

## 21. 用户开通与密码管理（方案 A）

> 本章解决一个问题：**用户从哪来、第一次密码怎么给、密码归谁管**。
> 完整可执行清单（每项含 kcadm 命令 / 控制台路径 / 判据 / 排查入口）见 **`统一身份认证实施/docs/方案A落地清单.md`**，本章只记口径与结论，避免两份文档说法打架。

### 21.1 账号来源：本地用户，不是 LDAP 联邦

| 问题 | 结论 |
|---|---|
| 用户从哪来 | AD 名单 → 暂存表 → `CN_AME_SSO_User` → `sync_sso_to_keycloak.ps1` 建号；当前 AD 账号**已批量导入** Keycloak |
| 导入带过来什么 | `username`（= 中央表 `login_name` 小写）+ `email`；**没有密码，也没有密码哈希** |
| Keycloak 里是什么用户 | **本地用户**。密码哈希存于 `keycloak` 库 `CREDENTIAL` 表，与 AD 无关 |
| 是否 LDAP / User Federation | **否**。不要按「联邦」思路排查；`Realm Settings → User Federation` 应为空 |
| 密码归谁管 | **Keycloak**。首次密码由管理员代设，之后由用户自助修改；离职禁用由中央表 `status=0` 驱动 |

> 一句话给接手的人：**「AD 只管人，不管密码」**。任何「让用户用域密码登录」「去 AD 重置密码」的说法都与本方案冲突。

### 21.2 首次密码：全员统一初始密码 + 首登强制改密

**决策（2026-11-09）**：不逐一发放随机临时密码。**全员使用同一个初始密码**，`Temporary=ON`，首次登录强制改密。

- **初始密码的值不写入任何文档、脚本、清单或聊天记录**；由管理员在执行时交互输入（`Read-Host -AsSecureString`），单独封存，交接按密件处理。
- 脚本不会把密码写入文件、日志或命令行历史（不落盘、不进 `$args`）。

> **风险与缓解（必须随方案一起评审）**
> 统一初始密码等于**全员共享一个已知秘密**：在「已设密但未首登」的窗口内，任何人只要知道某个用户名 + 这个初始密码，就能冒名登录。**只有在「首登即强制改密」成立时，这个方案才可接受**。缓解措施：
> 1. `Temporary=ON` + `UPDATE_PASSWORD` 必需动作必须同时生效（见 21.3），且逐个核查未漏设；
> 2. 密码策略：最短长度、`notUsername`、`notEmail`，并确保**新密码不得与初始密码相同**（`passwordHistory` 至少 1，或由策略强制）；
> 3. **建议项（不擅自实施）**：给「已设密但超过 14 天未首登」的账号设处置机制——到期前提醒、到期后禁用，由业务与安全负责人决定是否执行。判定条件是 `requiredActions` 仍含 `UPDATE_PASSWORD` 且 `createdTimestamp` 超过 14 天；执行方式与影响面需单独评审。
> 4. 初始密码只用于「一次性批量开通」，**不得作为长期应急口令**；每次批量开通后即视为已消耗，如需再次批量开通必须重新设定并重新封存。
> 5. **命名风格风险（建议项，不擅自实施）**：该初始密码与现有管理员口令的命名风格高度相似，存在被用户「顺推」管理员口令的风险。**建议正式推广前更换为与管理员口令无关的字符串**。
> 6. **字符集约束（建议项，不擅自实施）**：该初始密码不含特殊字符。若后续启用「必须含特殊字符」的密码策略（见 S01），此初始密码将**无法设置**（`reset-password` 会被策略拒绝），必须同步更换初始密码或调整策略。两条都需在策略评审时一并确认。

SMTP 已按正式服务具备（见 9.5），但它**不改变本决策**：批量开通走统一初始密码；邮件邀请用于后续零散补开与忘记密码。

### 21.3 `Temporary` 与 `UPDATE_PASSWORD` 的正确配置

| 项 | 必须 | 设错的后果 |
|---|---|---|
| `Credentials → Set password → Temporary` | **ON** | OFF = 临时密码永久有效，管理员知道的密码长期能登 |
| `Details → Required user actions → Update Password` | **ON** | 未设则首登不强制改密（`--temporary` 通常会自带，仍需核查） |
| `VERIFY_EMAIL` | **OFF** | 见 21.4 |

**实际用户体验**（跟用户提前说明，避免被当成故障）：

```text
输入 用户名（login_name 小写）+ 临时密码
  → 「Update Password」页：输入两遍新密码（须满足密码策略，且不能与近期旧密码相同）
  → 若资料不全：再跳「Update your profile」页补姓/名/邮箱
  → 完成后自动回到 MSIA / BOL
```

核查命令：`kcadm get users/<id> -r inalfa --fields username,enabled,requiredActions`（应含 `UPDATE_PASSWORD`）；`kcadm get users/<id>/credentials`（应为 `temporary: true`）。失败排查入口：`C:\keycloak\logs\keycloak.log` 搜 `UPDATE_PASSWORD`。

### 21.4 批量开通为什么仍不启用 `VERIFY_EMAIL`

**不是「发不出邮件」**（SMTP 已是正式服务），而是三条业务理由：

1. 统一初始密码 + `UPDATE_PASSWORD` 强制改密，已经能保证「首次登录的人必须自己设定密码」，账号由本人启用；
2. AD 导入的 `email` **允许空、允许重复**；一旦 `VERIFY_EMAIL` 成为默认必需动作，邮箱缺失/重复的用户会直接卡在验证页，且没有自助出口（管理员只能逐个关掉该动作再让他登录）；
3. 邮箱在本方案中不是受管属性，验证不带来实际安全收益，只会增加开通摩擦。

> 因此结论是：**批量开通场景关闭 `VERIFY_EMAIL`**（`enabled=false`、`defaultAction=false`）；后续若业务确需邮箱验证，作为独立变更评审，先在测试 realm 验证「缺失/重复邮箱用户」的表现。

核查：

```powershell
& 'C:\keycloak\bin\kcadm.bat' get authentication/required-actions -r inalfa `
  --fields alias,name,enabled,defaultAction,priority
```

判据：`VERIFY_EMAIL` 的 `enabled=false` 且 `defaultAction=false`；`UPDATE_PASSWORD` 的 `enabled=true`。
控制台等价路径：`Realm Settings → Authentication → Required Actions`。

### 21.5 资料缺失导致的「更新资料」页

Keycloak 的用户资料是**声明式必填**：只要 `email` / `firstName` / `lastName` 中有被标为 required 而用户值为空，首次登录就会被强制跳资料补全页。

**已有证据**：2026-11-05 21:34 成功登录的 Keycloak 事件序列为 `LOGIN → CODE_TO_TOKEN → VERIFY_PROFILE → UPDATE_PROFILE`，其中 `VERIFY_PROFILE` 通常出现在资料页被触发时。因此**「是否会出现资料补全页」不能只按「待确认」放着，必须实测确认**。

两种收口方式：

1. **首选（推荐）**：不改 realm 配置，直接按 `CN_AME_SSO_User.display_name` 批量补齐三字段（清单 M05，只填空值不覆盖）；
2. 备选：把 `firstName`/`lastName` 的 `required` 关掉。这是 realm 级改动，影响所有 client，需评审。

核查命令：`kcadm get users/profile -r inalfa`（看 `attributes.*.required`）。
批量排查：导出全部用户，筛 `email`/`firstName`/`lastName` 为空者，再与中央表比对补齐（清单 M02 + M05）。

### 21.6 准入组批量加入

- 设计：`app-msia` / `app-bol` 为**顶层组**，mapper `Full group path=OFF`，令牌里 `groups` 必须是 `["app-msia"]`（不带斜杠）；
- 漏加 = OIDC 回调后 403「未开通本系统访问权限」；
- 批量命令与抽检方法见清单 M08；成员名单以权限台账为准（`realm-setup.md` §7 只记录首批 13 人，后续变更不能凭记忆）。

### 21.7 策略、会话与审计的建议值（现场以复核值为准）

| 类别 | 建议值 | 备注 |
|---|---|---|
| 密码策略 | 长度 12、大小写/数字/特殊各 ≥1、`notUsername`、`notEmail`、`passwordHistory(5)`、**不过期** | 统一初始密码方案下，`passwordHistory` 用于确保新密码不能是初始密码；无自助重置时策略过严会变成重置工单洪水 |
| 暴力破解 | ON、`failureFactor=5`、`waitIncrement=900s`、`maxFailureWait=900s`、**`permanentLockout=false`** | 与交底书 9.3 一致（5 次 / 900 秒），本轮无变更。永久锁定只能管理员解锁，不适合本环境 |
| 会话 | SSO Idle **86400s（1 天）**、SSO Max **604800s（7 天）**、Access Token **900s**、Action Token **4320 分钟** | **2026-11-09 现场决定覆盖原设计值 8 小时/12 小时，原值作废**。方向是加长，**不会踢掉已登录用户**，对在用用户无感；代价是共享机位会话存活更久，需作为独立事项跟进（例如强制本地登出） |
| 事件审计 | 用户事件 ON、`eventsExpiration=7776000`（90 天，单位秒）；管理员事件 ON、`adminEventsDetailsEnabled=false` | `Expiration` 通常只清用户事件；管理员事件在 25.0.6 不自动过期，需定期导出/清理（清单 S04） |

复核命令（**逐项执行，未复核前不得当成既成事实**）：

```powershell
& 'C:\keycloak\bin\kcadm.bat' get realms/inalfa --fields realm,passwordPolicy,bruteForceProtected,failureFactor,ssoSessionIdleTimeout,ssoSessionMaxLifespan,accessTokenLifespan,actionTokenGeneratedByUserLifespan
& 'C:\keycloak\bin\kcadm.bat' get events/config -r inalfa
```

### 21.8 停用、大小写重复与新员工过渡

- **AD 已停用账号**：中央表 `status=0` → 同步脚本禁用 + 踢会话，**永不物理删除**。不要手工逐个人禁用（会被下次同步覆盖且易漏）。核对方法：中央 `status=0` 清单 vs Keycloak `enabled=false` 清单做差集（清单 M09）；SQL 侧交叉核对用 `scripts/sql/91_usermap_integrity_checks.sql` 第 8 节。
- **大小写重复建档**：本地用户名与中央 `login_name` 仅大小写/空白不同且没有 UserMap 行 → 身份解析随机命中，权限/密码/令牌分叉。核查用 `91` 号脚本第 4.2 / 4.3 / 6 节（预期全空），Keycloak 侧再用 `user_entity` 的 `LOWER(username)` 分组复核。**发现后逐条人工裁决，禁止批量自动合并**。
- **新员工路径**：`sync_sso_to_keycloak.ps1` 建号分支会调用 `execute-actions-email`。SMTP 已按正式服务具备，该路径**理论上可用**，但「realm 是否已配置 Email、是否实测发信成功」仍需现场核对（见 9.5 核查命令）；未确认前，建号后仍按 21.2 的批量方式设统一初始密码，避免依赖未验证的邮件链路。

### 21.9 备份：数据库备份 vs realm 导出（哪个能救用户）

| 备份 | 能救什么 | 不能救什么 |
|---|---|---|
| **SQL Server `keycloak` 库完整备份** | 用户、**密码哈希**、组、client、secret、会话、签名密钥 | 跨 Keycloak 版本直接还原 |
| **realm 导出 JSON** | realm/client/组/mapper/策略等**配置结构** | **不含密码/凭据**，导出永远拿不到密码哈希 |

**结论：救「用户能不能登录」只能靠数据库备份；realm 导出只能救「配置改坏了怎么回滚」。两者都要做，不可互相替代。** 数据库备份建议每日全备 + 保留 30 天 + 每季度还原演练；realm 导出建议每周一次（`kc.bat export --dir C:\sso\kc-export --realm inalfa`）。命令与判据见清单 S05。

### 21.10 本章对既有文档的修订说明

| 轮次 | 位置 | 修订内容 |
|---|---|---|
| 2026-11-09（第二轮） | §9.3、§21.7、MSIA 手册 §3.5、清单 S03、`keycloak/realm-setup.md` §5 | **会话改为空闲 1 天 / 最长 7 天**（`ssoSessionIdleTimeout=86400`、`ssoSessionMaxLifespan=604800`）。这是现场决定，**优先于原设计值 8 小时/12 小时，原值作废**。方向是加长，不会踢掉已登录用户，对在用用户无感 |
| 2026-11-09（第二轮） | §9.5、MSIA 手册 §3.4、清单 C04、`keycloak/realm-setup.md` §1 | SMTP 补全正式参数：from 改为 `ap_sso@inalfa.com`、新增 `fromDisplayName`，明确 `auth/starttls/ssl=false` 与明文中继的后续切换方式；发信判据改为「实际收到信」 |
| 2026-11-09（第二轮） | §21.2、清单 M07/S01、`keycloak/realm-setup.md` §3 | 统一初始密码补两条建议项：与管理员口令命名风格相似（建议更换）、不含特殊字符（启用 specialChars 策略前必须更换）。**初始密码值不写入任何文件** |
| 2026-11-09（第二轮） | `scripts/apply-realm-baseline.ps1` | 命令块补全为完整可执行版：备份当前值 → 会话 → 暴力破解 → SMTP → 发信验证 → 资料缺失查询 → 批量加组 → 批量设初始密码 |
| 2026-11-09 | §9.5 | SMTP 恢复为「正式服务」口径；此后参数与发信判据按第二轮修订 |
| 2026-11-09 | §9.3 | 删除并列两个值；暴力破解**以本节为准**（5 次/900 秒，延续不变）。`VERIFY_EMAIL` 关闭理由改为「批量开通 + 邮箱缺失/重复会卡死」，不再表述为「没有 SMTP」 |
| 2026-11-09 | §21.2 | 首次密码改为**全员统一初始密码 + 强制改密**；删除「逐用户随机分发」的分叉讨论；补风险与缓解（含 14 天未首登处置的建议项，未实施） |
| 2026-11-09 | §21.4 | 标题与理由重写为「批量开通为什么仍不启用 `VERIFY_EMAIL`」 |
| 2026-11-09 | §21.7 | 会话值先改为 28800s / 43200s，**后被第二轮 1 天/7 天覆盖**；Action Token 4320 分钟沿用 |
| 2026-11-09 | §21.8 | 新员工路径由「SMTP 缺失会失败」改为「SMTP 可用但需确认已实测」 |
| 2026-11-09 | `docs/keycloak-msia-sso-guide-for-beginners.md` | §3.5 `SSO Session Idle` 30 分钟 → 先改 8 小时，**第二轮再改为 1 天 / 最长 7 天**；§3.6 `Max Login Failures` 30 / `Wait Increment` 60 秒 → 5 次 / 900 秒；均标注「以交底书为准，原值作废」 |
| 2026-11-09 | `docs/方案A落地清单.md` | M03/M07/M09/S07 按本轮决策重写；新增可执行命令块脚本 `scripts/apply-realm-baseline.ps1` |
| 2026-11-09（第三轮：口径回灌） | `docs/keycloak-realm-clients-init.md`、`docs/keycloak-console-setup-for-beginners.md`、`统一身份认证实施方案_MSIA与BOL系统.md`、`统一身份认证方案A_Keycloak自管密码.md`、`docs/sso-session-and-silent-login.md`、`keycloak/realm-setup.md`、`README.md` | 把 §9.3 / §9.5 的最终口径回灌到遗留文档：会话 86400/604800 秒、SMTP `ap_sso@inalfa.com` + 显示名 + `auth/starttls/ssl=false`、暴力破解 5 次/900 秒。各文档均在文首或文内标注了修订记录；历史变更记录保留原值并注明「已作废」，未做抹除 |
| 2026-11-06 | §3.1 | 补明「AD 只提供 `username`/`email`，**没有密码**；**不做 LDAP 联邦**；导入的是本地用户」 |
| 2026-11-06 | §5.1 / §5.2 | 明确首次密码为「管理员代设 + 首登强制改密」 |
| 2026-11-06 | §16 | 交付索引增加《方案A落地清单》 |
| 2026-11-06 | §2.1 | 补「AD 账号已批量导入 Keycloak（本地用户，含 username/email，无密码）」 |

> **文档位置说明**：本章所在的交底书位于**工作区根目录**，不是 `统一身份认证实施/docs/` 目录。
> 根目录：`统一身份认证技术交底书_MSIA与BOL实施实录.md`
> `docs/` 下的三份新手手册经核对**不存在 LDAP 联邦表述**，其「本地用户 + 本地密码 + `Temporary=ON`」口径与本章一致；其中 MSIA 手册的两处数值已按本轮决策修正。
