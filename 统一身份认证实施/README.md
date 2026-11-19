# 统一身份认证实施工件（T01 交付）

> 配套方案文档：《统一身份认证实施方案_MSIA与BOL系统.md》（v1.0，第 12 章实测结论为准）。
> 本目录为 T01（基础设施与数据库）的全部实施工件：SQL 脚本、PowerShell 同步脚本、Keycloak 配置、操作手册。
> **T01 数据库部分已于 2026-11-02 在 IRSCNYTFINEREPORT.ap.inalfa.local / CN_AME 库实际执行并通过自查**（详见文末"执行记录"）。

## 1. 文件清单

```
统一身份认证实施/
├── README.md                          -- 本文件（总说明 + 执行顺序 + 依赖）
├── scripts/
│   ├── sql/
│   │   ├── 01_create_sso_tables.sql   -- 五表 DDL（幂等，方案文档 4.2）
│   │   ├── 02_grants.sql              -- sso_sync_svc 创建+授权；BOL 跨库只读授权
│   │   ├── 03_seed_users.sql          -- 种子数据（13 用户 + 2 对照 + 18 台账，幂等先查后插）
│   │   └── 90_usermap_backfill.sql    -- 对照表回填模板 + 对账查询（T05 共用）
│   └── powershell/
│       ├── sync_ad_to_sso.ps1         -- 每日 06:00：名单→暂存→防错→MERGE→串联KC同步
│       ├── sync_sso_to_keycloak.ps1   -- sso_user→Keycloak Admin REST（幂等，退避重试）
│       ├── disable_user_now.ps1       -- 紧急停号（手工）
│       └── health_check.ps1           -- 每日 07:30 健康检查 + 告警
├── keycloak/
│   ├── keycloak.conf                  -- Keycloak 26.x 生产配置（7.1 参数）
│   ├── realm-setup.md                 -- realm inalfa 配置清单（SMTP/策略/事件/组）
│   └── clients.md                     -- msia-prod/bol-prod/sync-client/account 配置表
└── docs/
    ├── cutover-runbook.md             -- 双轨→单轨切换操作手册（开关矩阵）
    └── rollback-runbook.md            -- 回滚手册（R-a~R-e + break-glass）
```

## 2. 部署位置映射（服务器 IRSCNYTFINEREPORT）

| 工件 | 部署位置 | 说明 |
|---|---|---|
| `scripts/powershell/*.ps1` | `C:\sso\scripts\` | 计划任务指向此目录 |
| `keycloak/keycloak.conf` | `C:\keycloak\conf\keycloak.conf` | |
| `Microsoft.Data.SqlClient.dll` | `C:\sso\scripts\`（**按需**） | 仅当 SSMS/SqlServer 模块不可用时需要；从 NuGet 获取 |
| `credentials.xml` | `C:\sso\conf\credentials.xml` | 见第 4 节，权限仅运行账号可读 |
| 日志 | `C:\sso\logs\` | 各脚本每日一个日志文件 |

## 3. 执行顺序

### 3.1 数据库（已完成，2026-11-02；重跑/新环境按此序）

```
① 01_create_sso_tables.sql   -- 建五表（幂等）
② 02_grants.sql              -- 账号授权（幂等）
③ 03_seed_users.sql          -- 种子数据（幂等）
④ 90_usermap_backfill.sql    -- 按需：对账/回填（查询为主，模板需改值后执行）
```

执行方式：SSMS 打开执行，或 `sqlcmd -S IRSCNYTFINEREPORT.ap.inalfa.local -d CN_AME -U ytview -P <pwd> -i 01_create_sso_tables.sql`。

### 3.2 计划任务（P2 数据链路上线时注册）

| 任务名 | 时间 | 命令 |
|---|---|---|
| `SSO_AD_Import` | 每日 06:00 | `powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1` |
| `SSO_HealthCheck` | 每日 07:30 | `powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\health_check.ps1` |
| `SSO_KC_Export` | 每周日 02:00 | `C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export --realm inalfa` |

> 计划任务运行账号 = 生成 credentials.xml 的同一账号（DPAPI CurrentUser 绑定，见第 4 节）。

## 4. 凭据文件生成（credentials.xml，DPAPI）

口令**不落任何脚本/文档**。用计划任务的同一运行账号、在同一台服务器上执行：

```powershell
# 1. 生成（在目标服务器的目标账号下执行！）
$entries = @(
    @{ Name = 'sso_sync_svc';          UserName = 'sso_sync_svc';     Password = '<sso_sync_svc 的实际口令>' },
    @{ Name = 'keycloak_sync_client';   UserName = 'sync-client';     Password = '<sync-client 的 secret>' }
)
$xml = New-Object System.Xml.XmlDocument
$root = $xml.CreateElement('Credentials')
$xml.AppendChild($root) | Out-Null
foreach ($e in $entries) {
    $sec = ConvertTo-SecureString $e.Password -AsPlainText -Force
    $enc = $sec | ConvertFrom-SecureString      # DPAPI CurrentUser 作用域
    $node = $xml.CreateElement('Credential')
    $node.SetAttribute('Name', $e.Name) | Out-Null
    $un = $xml.CreateElement('UserName'); $un.InnerText = $e.UserName; $node.AppendChild($un) | Out-Null
    $pw = $xml.CreateElement('Password'); $pw.InnerText = $enc;        $node.AppendChild($pw) | Out-Null
    $root.AppendChild($node) | Out-Null
}
New-Item -ItemType Directory -Path 'C:\sso\conf' -Force | Out-Null
$xml.Save('C:\sso\conf\credentials.xml')
# 2. 收紧权限：仅运行账号 + SYSTEM 可读
icacls C:\sso\conf\credentials.xml /inheritance:r /grant:r "$env:USERNAME:(R)" /grant:r "SYSTEM:(R)"
```

**注意**：
- `ConvertFrom-SecureString` 默认绑定**当前用户 + 本机**——换账号/换机器执行脚本将无法解密（报"密钥句柄无效"类错误）；
- 换口令后必须重新生成此文件，并重跑一次脚本验证；
- kcadmin（master 域 break-glass 账号）口令**不在此文件**，物理封存（见 rollback-runbook.md R-a）。

## 5. 依赖与待确认项

| # | 事项 | 影响 | 责任 | 状态 |
|---|---|---|---|---|
| U3 | IT 每日 AD 名单导出：时间/方式/列名（userName,realName,email,mobile,enable,employeeNo）/编码 UTF8 | sync_ad_to_sso.ps1 `-Source csv` | IT | **已开始同步（2026-11-03 StgAdUser 已有数据）**；正式投递方式（CSV/快照表）待书面约定 |
| — | JDK21 + Keycloak 26.x + NSSM + MSSQL JDBC 部署 | 全部 KC 功能 | T01（P1） | **JDK21 已装于 IRSCnKettle01（2026-11-03）**；待 Keycloak 26.x + MSSQL JDBC + NSSM 部署 |
| — | IIS ARR 反代 sso.ap.inalfa.local + 企业证书（规格单/申请步骤见 docs/cert-request-guide.md；仅 Keycloak 入口需 1 张，MSIA/BOL 维持 HTTP 不需要） | OIDC redirect、SMTP 域名口径 | IT | **CA 工单已提交（2026-11-03），证书待签发**；部署位置定稿 IRSCnKettle01（需 IT 装 IIS+ARR+URL Rewrite）；DNS A 记录待执行 |
| U4/Q6 | SMTP 25 无认证中继确认（发件人 `ap_sso@inalfa.com` 不被判垃圾；原 `sso-notify@inalfa.local` 命名作废） | 设密邮件送达 | IT | 用户确认前期已验证 OK；**2026-11-09 起 From 以交底书 §9.5 为准，仍须实测收到信** |
| U1 | MSIA HTTPS 域名（msia.ap.inalfa.local） | msia-prod 需追加 redirect URI | IT | 推进中 |
| U2 | BOL 固定内网访问 URL/端口（无需公网） | **bol-prod redirect_uri 无法定稿** | 用户 + T03 | **待用户提供地址/端口** |
| — | keycloak 独立库 + keycloak_svc 账号创建（DBA） | Keycloak 启动 | DBA | 待执行 |
| — | yaole 在 MSIA 本地行 status=0（中央表按 BOL 在职口径置 1） | MSIA OIDC 登录姚雷会遇"账号已禁用"403；业务结论：默认不自动恢复，后续按需在 MSIA 后台或中央表处理 | 业务 + T02 | **业务项，后续按需设置** |
| — | BOL admin 与 ligu 两本地账号共用 guozhu.li@inalfa.com | 邮箱暂不用管理：唯一索引已降级，重复允许；BOL 侧映射以 UserMap 为准 | T03 | 已按新策略处置 |
| — | **邮箱策略（2026-11-02 用户确认）** | email 允许空/重复；无邮箱用户走 Keycloak 控制台代设密+首登改密（realm-setup.md 2.1），不走邮件邀请 | 全员 | **已生效** |

## 6. T02/T03/T05 依赖确认（给后续任务）

1. **数据库侧全部就绪**：五表 + 种子 + 授权（含 sparePartRead 跨库只读两表）已落地，T02 读 `CN_AME_SSO_User/UserMap` 用 ytview 直连即可；T03 BOL 跨库读用 sparePartRead（已授权 SELECT）；
2. **匹配约定**（两系统 OIDC 回调统一）：groups 准入校验 → `CN_AME_SSO_UserMap(system_code)` → 回落 `preferred_username` → 本地用户表 → 自动建档（最低权限）；
3. **system_code 取值**：`msia` / `bol` / `keycloak-admin` / `local-admin`；
4. **对照表现状**：仅 2 条 BOL 映射（Yaolei/Zhangy4），MSIA 无需映射（用户名即 login_name）；
5. **OIDC 成功后签发各系统既有本地凭证**，下游鉴权零改动；otk 一次性码 60 秒；
6. **redirect_uri 待定项**：msia-prod 用 `http://172.26.2.203:8078/api/auth/oidc/callback`（现网 HTTP，TR2 已知晓）；bol-prod 待 U2 确认后补登记到 clients.md。

## 7. 执行记录（2026-11-02，ytview 实测）

| 项 | 结果 |
|---|---|
| 五表创建（01） | ✅ StgAdUser/User/UserMap/SyncLog/PermLedger 全部建成 |
| sso_sync_svc（02） | ✅ LOGIN + USER 创建成功（ytview 实测为 sysadmin+securityadmin，非文档记载的 db_owner）；五表 SELECT/INSERT/UPDATE/DELETE 已授；DDL 已 DENY；连接测试 SELECT/INSERT 通、建表被拒（符合预期） |
| BOL 跨库授权（02） | ✅ sparePartRead 在 CN_AME 建 USER 并授 `CN_AME_SSO_User/UserMap` SELECT（TR4 风险解除，T03 无阻塞） |
| 种子数据（03） | ✅ User=13、UserMap=2、PermLedger=18（MSIA 11 + BOL 7）、SyncLog=0；无孤儿数据；邮箱经二次 SELECT 核对与两系统实测一致 |
| 对账（90 查询 A） | ✅ 11 名非测试 MSIA 用户全部被中央表覆盖（回落命中）；3 个测试账号（lead_reviewer01/reviewer01/reviewee01）按用户确认不纳入 |
| PowerShell 脚本 | ✅ 4 个全部通过 PowerShell 语法解析校验（UTF-8 BOM，兼容 5.1） |
| 实测偏差记录 | ① containment=NONE → 改 LOGIN+USER 两段式（脚本已注释留档 contained 语法）；② 脚本灌数用 DELETE 代替 TRUNCATE（sso_sync_svc 无 ALTER 权限，符合权限最小化设计）；③ MSIA 真实用户角色分布与 12.2 表略有出入（reviewer 实际 1 人且为测试账号，reviewee 实际 7 人含 1 测试），种子按实测台账 |
| **2026-11-02 邮箱策略调整**（用户确认"邮箱暂不用管理"） | ✅ `UX_CN_AME_SSO_User_Email` 唯一索引已 DROP，普通索引 `IX_CN_AME_SSO_User_Email`（filtered）已 CREATE；realm-setup.md 已关闭 Duplicate emails 并补无邮箱兜底流程（管理员代设密+首登改密）；sync_ad_to_sso.ps1 取消"邮箱重复整体中止"、改为"格式非法→告警置空放行"；sync_sso_to_keycloak.ps1 空邮箱跳过邀请并写 SyncLog、不覆盖 KC 已有邮箱 |

## 8. 安全基线

- 所有口令/secret 仅存在于 DPAPI 加密的 credentials.xml 与物理封存介质；
- 同步账号 sso_sync_svc 仅五表 DML，无 DDL、无整库权限；
- Keycloak 只听本机 8443，对外经 IIS ARR + 企业证书；
- 日志目录 C:\sso\logs 每日轮换文件，含账号操作审计线索（紧急停号强制邮件留痕）。

## 9. 代码实施与 QA 结论（2026-11-03）

### 9.1 本次已落地代码改造

- **MSIA Report**：新增 OIDC 登录/回调/OTK 兑换、本地登录开关、HR 同步开关、中央表派生同步（`sso_user_sync`）及调度；前端新增统一登录按钮、OIDC 回调页、密码入口按开关显隐。
- **BOL 管理系统**：新增 OIDC 登录/回调/OTK 兑换、登录配置端点、双轨开关矩阵；保留游客登录；`AuthToken.source` 加法迁移（0005）与 users 迁移 drift 消除（0006）；`sync_sso_status` 全量中央表回写 + 中央停用无条件清 Token；前端新增统一登录按钮、OIDC 回调页、注册/忘记密码/改密入口按开关显隐。
- **默认行为**：Keycloak 未部署前 `OIDC_ENABLED=False`，本地登录、HR 同步保持开启；BOL 自助注册默认关闭、游客通道保留、状态回写默认开启。生产行为与改造前一致。

### 9.2 全量验证结果（主理人 + QA 独立复核）

| 验证项 | 结果 |
|---|---|
| BOL `manage.py check`（默认 settings） | ✅ 通过 |
| BOL `manage.py check`（`bol_platform.settings_prod`） | ✅ 通过 |
| BOL `manage.py test apps.users` | ✅ 35 项通过（含 Round2  Token 残留修复回归） |
| BOL `manage.py makemigrations users --check --dry-run` | ✅ No changes detected |
| BOL `compileall` | ✅ 通过 |
| MSIA 应用导入 + `tests/test_sso_oidc.py` | ✅ 16 项通过 |
| MSIA `compileall` | ✅ 通过 |
| BOL 前端 `npm run build` | ✅ 通过 |
| MSIA 前端 `npm run build`（含 `tsc`） | ✅ 通过 |
| 邮件参数静态 AST 校验（Django `send_mail` / `EmailMultiAlternatives`） | ✅ 无无效关键字 |
| QA Round 2 独立结论 | ✅ **IS_PASS: YES**；初轮与 Token minor 修复复核均通过，功能级证据 7/7 |

### 9.3 BOL 打包产物（2026-11-03 重打包）

- 最新打包目录：`BOL管理系统/backend/dist-sso-20261103-r2/BOLServer/`
- 可执行文件：`BOLServer.exe`（约 10.8 MB）
- 冒烟验证：`BOLServer.exe --help` 正常返回启动参数，未触发数据库连接。
- 包内核对：`users` 迁移 0005/0006、`sync_sso_status`（含全量中央表 SQL 与 Token 无条件清理修复）、`staticfiles/index.html`、`db_config.ini.example` 均在包内。
- 旧 `dist/BOLServer` 未删除，避免触发批量删除安全阈值；部署时以 `dist-sso-20261103-r2` 为最新候选包。

### 9.4 既有问题（非本次 SSO 改造引入）

- 全项目 `manage.py makemigrations --check --dry-run` 仍报告 `budget_bol`、`dynamic_bol`、`reports` 存在模型/迁移差异；`users` 单独检查无差异。该 drift 属于既有业务模型未同步迁移，需业务/DBA 单独评估，不阻塞统一身份认证代码交付。
- QA 另记录两个不阻塞 minor：MSIA 测试以 `TestClient` 导入作为依赖不满足的降级哨兵；BOL 静态 OIDC 配置无环境变量覆盖。前者已有清晰失败提示，后者已由外部配置文件覆盖机制承担，建议后续增强。

### 9.5 运维口径与上线前门项（未完成）

**运维口径（QA Round 2 确认）**：中央人员表是人员状态唯一事实来源。BOL 后台或数据库手工把员工置为 `INACTIVE` 后，下一次 `sync_sso_status` 会按中央表状态覆盖；`ACTIVE` Token 复活只在中央表仍为 `status=1` 时发生，属于预期复职，不是绕过禁用。

**上线前门项**：

- Keycloak 26.x + JDK21 + NSSM + MSSQL JDBC 部署；realm/client/secret 配置。
- DNS/IIS ARR/证书：`sso.ap.inalfa.local`、MSIA/BOL 固定内网回调地址。
- SMTP 25 无认证：用户确认前期已验证 OK；上线前仍建议用小范围真实邮件做最终冒烟。
- BOL `bol-prod` redirect_uri 定稿：**待你提供 BOL 固定内网 URL/端口（无需公网）**。
- MSIA 姚雷本地禁用状态：业务项，默认不自动恢复，后续按需设置。
- 切换前按 `docs/cutover-runbook.md` 执行双轨→单轨；回滚演练按用户要求暂缓。

### 9.6 定期更新作业对接（AD 名单 → SSO）

**定期作业只应写“暂存表”，不要直接写中央人员表。** 中央人员表由 `sync_ad_to_sso.ps1` 的防错检查 + MERGE 更新，直接写会绕过校验、告警和 Keycloak 串联。

| 用途 | 表名 | 说明 |
|---|---|---|
| 名单暂存（定期作业目标表） | `CN_AME.dbo.CN_AME_SSO_StgAdUser` | 每日清空重灌；脚本随后 MERGE 到中央表 |
| 中央人员事实表（脚本更新，作业只读） | `CN_AME.dbo.CN_AME_SSO_User` | Keycloak 同步来源；`login_name` 禁止改写 |
| 跨系统用户名例外映射 | `CN_AME.dbo.CN_AME_SSO_UserMap` | 仅本地用户名 ≠ 中央 login_name 时登记 |
| 同步运行日志 | `CN_AME.dbo.CN_AME_SSO_SyncLog` | 监控 `LOAD/MERGE/KC` 阶段 |

**`CN_AME_SSO_StgAdUser` 字段（snake_case，直接写库时用）：**

| 字段 | 类型 | 必填 | 来源/口径 |
|---|---|---|---|
| `employee_no` | NVARCHAR(32) | 是 | 工号；无工号时等于 `login_name` |
| `login_name` | NVARCHAR(64) | 是 | AD 域账号，统一小写；全局唯一 |
| `display_name` | NVARCHAR(128) | 否 | 中文姓名 |
| `email` | NVARCHAR(128) | 否 | 企业邮箱；允许空/重复 |
| `mobile` | NVARCHAR(32) | 否 | 手机号 |
| `dept_code` | NVARCHAR(64) | 否 | 部门编码；当前 CSV 约定未提供 |
| `dept_name` | NVARCHAR(128) | 否 | 部门名称；当前 CSV 约定未提供 |
| `title` | NVARCHAR(128) | 否 | 岗位；当前 CSV 约定未提供 |
| `status` | TINYINT | 是 | `1=在职`，`0=离职停用`；永不物理删除 |
| `ad_object_guid` | UNIQUEIDENTIFIER | 否 | 防工号复用误合并；当前名单无此列可空 |
| `loaded_at` | DATETIME2(0) | 否 | 默认 `SYSUTCDATETIME()`，UTC |

**如果 IT 以 CSV 投递（L2 主通道）**，CSV 列名固定为：`userName,realName,email,mobile,enable,employeeNo`，UTF-8 编码，文件名 `ad_users_yyyyMMdd.csv`，放到 `C:\sso\import`。字段映射：

| CSV 列 | 暂存表字段 | 转换 |
|---|---|---|
| `userName` | `login_name` | `Trim().ToLower()` |
| `employeeNo` | `employee_no` | 为空时用 `userName` |
| `realName` | `display_name` | 去空格 |
| `email` | `email` | 格式非法置空并告警，不中止 |
| `mobile` | `mobile` | 去空格 |
| `enable` | `status` | `1/0`、`true/false`、`yes/no`、`在职/离职` |

**推荐计划任务命令：**

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1 -Source csv -CsvDirectory C:\sso\import
```

**如果 IT 直接落数据库表（L3 兜底）**，可让脚本直读你的快照表，但仍由脚本写暂存表并 MERGE：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1 -Source table -TableSourceQuery "SELECT userName, realName, email, mobile, enable, employeeNo FROM dbo.YourAdSnapshot"
```

**监控口径：**

```sql
SELECT TOP 20 run_at, phase, src_rows, added, updated, disabled, reactivated, status, message
FROM dbo.CN_AME_SSO_SyncLog
ORDER BY run_at DESC;
```

出现 `ABORTED/ERROR` 或当日无 `LOAD/MERGE` 记录时，必须人工介入，不要重复手工改中央表。

