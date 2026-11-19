# Keycloak 用户 ↔ 中央库表：关系与同步架构

> 说明对象: 现场已部署的实现（不是目标设计）。
> 实例 `IRSCNYTFINEREPORT.ap.inalfa.local` / 库 `CN_AME` / realm `inalfa`（Keycloak 25.0.6）。
> 配套示意图: [`docs/sso-user-sync-architecture/index.html`](sso-user-sync-architecture/index.html)。

## 1. 一句话结论

中央表 `CN_AME_SSO_User` 是人员的唯一事实来源；两段脚本把它单向推到 Keycloak，Keycloak 只被"对账"，不被重建；Keycloak 侧的任何修改（改密码、改姓名）都不回流。

## 2. 落点

| 项 | 实际值 |
|---|---|
| 数据库 | `IRSCNYTFINEREPORT.ap.inalfa.local` → `CN_AME`（表在 `dbo`） |
| AD 名单落地 | `C:\sso\import\ad_users_yyyyMMdd.csv`（UTF-8；列 `userName,realName,email,mobile,enable,employeeNo`） |
| 主链路脚本 | `C:\sso\scripts\sync_ad_to_sso.ps1`（仓库 `scripts\powershell\`） |
| Keycloak 同步脚本 | `C:\sso\scripts\sync_sso_to_keycloak.ps1`（被上一支 `powershell.exe -File` 串联调用） |
| 计划任务 | `SSO_AD_Import` 每日 06:00；`SSO_HealthCheck` 每日 07:30 |
| Keycloak | `https://iame.ap.inalfa.local:8443`，realm `inalfa` |
| 同步专用 client | `sync-client`（service account，仅 `manage-users`/`view-users`/`query-users`） |
| DB 连接账号 / 凭据 | `sso_sync_svc` / `C:\sso\conf\credentials.xml`（DPAPI，明文不落盘） |
| 日志 | `C:\sso\logs\sync_ad_to_sso_yyyyMMdd.log`；KC 段常被重定向到 `C:\sso\logs\bulk_*.out/.err` |

## 3. 五张表：职责与边界

| 表 | 职责 | 谁写 | 边界（明确不做什么） |
|---|---|---|---|
| `CN_AME_SSO_StgAdUser` | 当日名单着陆区。`employee_no` 普通索引，列与 `SSO_User` 基本同构 | 只由 06:00 脚本 `sync_ad_to_sso.ps1`：先 `DELETE` 再 `SqlBulkCopy` 灌入，灌完核对行数 | 不做任何判断、不做历史保留；不是事实来源，随时可清空重灌 |
| `CN_AME_SSO_User` | 人员主数据。`employee_no`、`login_name` 唯一；`kc_user_id` 唯一（filtered）；`source` 只允许 `AD`/`MANUAL` | 06:00 的 MERGE 写 AD 字段；KC 脚本只回写 `kc_user_id`、`pwd_set`、`updated_at` | 永不物理删除（离职只置 `status=0`）；不改写 `login_name`（改名走"停旧建新"）；不从 Keycloak 拉数据 |
| `CN_AME_SSO_UserMap` | 跨系统本地账号对照：`employee_no` + `system_code`（`msia`/`bol`）→ `local_username` | 人工/`90_usermap_backfill.sql` 回填，`(system_code, local_username)` 唯一 | 不参与建号、不被同步脚本写入；只服务应用侧身份解析 |
| `CN_AME_SSO_SyncLog` | 同步台账。`phase`=`LOAD`/`MERGE`/`KC`/`KC_EMERGENCY`，`status`=`OK`/`ABORTED`/`ERROR` | 两支脚本与 `disable_user_now.ps1` 都写 | 只记"这一轮跑了什么结果"，不记逐人明细；逐人明细在日志文件 |
| `CN_AME_SSO_PermLedger` | 授权审计：谁 / 哪个系统 / 什么角色 / 谁授的、何时吊销（`revoked_at IS NULL` = 仍有效） | 人工维护（首批由 `03_seed_users.sql` 灌入）；`assign_groups_from_ledger.ps1` 读它授组 | 不是 Keycloak 的实时权限表；改台账不会自动改组，需跑授组脚本 |

### 键关系

```
CN_AME_SSO_StgAdUser.employee_no  ──1:1──▶  CN_AME_SSO_User.employee_no   (MERGE 唯一匹配键)
CN_AME_SSO_User.employee_no       ──1:N──▶  CN_AME_SSO_UserMap.employee_no
CN_AME_SSO_User.employee_no       ──1:N──▶  CN_AME_SSO_PermLedger.employee_no
CN_AME_SSO_SyncLog                          无外键（按 run_at + phase 读）
CN_AME_SSO_User.kc_user_id                  指向 Keycloak user UUID，唯一（filtered）
```

注意：数据库层面除 `User.employee_no`/`login_name`/`kc_user_id` 的唯一约束外，**没有建外键**。跨表一致性靠脚本与人工，排障时不要假设数据库会拦住孤儿行。

## 4. 链路，逐跳

### 跳 0：AD 名单出文件（AD 侧，非本仓库）

人事/AD 侧导出当日 `ad_users_yyyyMMdd.csv` 到 `C:\sso\import`。脚本只认这个文件名规则，找不到就整轮失败。

### 跳 1：`sync_ad_to_sso.ps1`（每日 06:00，任务 `SSO_AD_Import`）

1. 读 CSV（`-Source table` 时改读库表，属兜底通道）；
2. 清洗：`userName` 全小写、空登录名剔行、邮箱格式非法→置空并告警、邮箱重复→只 WARN；
3. **防错闸门**（任一命中即中止，写 `SyncLog` `phase=LOAD`,`status=ABORTED` 并发告警邮件，MERGE 与 Keycloak 都不跑）：
   - 有效行数为 0；
   - 行数比上次成功 LOAD 骤降 >30%；
   - 停用占比 >10%；
   - 登录名/工号重复；
4. 灌 `StgAdUser`：`DELETE` + `SqlBulkCopy`，灌后行数必须与清洗结果相等；
5. 写 `SyncLog`：`LOAD`/`OK`（`src_rows` = 本次行数）；
6. 执行 MERGE 进 `SSO_User`（一条 SQL，`OUTPUT` 统计增/改/停/复），写 `SyncLog`：`MERGE`/`OK`；
7. 串行调用 `sync_sso_to_keycloak.ps1`（`-SkipKeycloakSync` 可跳过），检查其退出码。

MERGE 的三条硬规则：

- `WHEN MATCHED ... AND t.source <> N'MANUAL'`：`source='MANUAL'` 的行永不被 AD 覆盖；
- `WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> N'MANUAL'`：AD 名单里消失的人在中央表置 `status=0`，但 MANUAL 行不受影响；
- 更新列表里**故意不含** `login_name` 与 `kc_user_id`。

### 跳 2：`sync_sso_to_keycloak.ps1`（紧随跳 1，同一进程树）

取数：`SELECT ... FROM dbo.CN_AME_SSO_User ORDER BY employee_no`（无 `WHERE`，含离职与 MANUAL 行），然后按 `-ExcludeEmployeeNos` 过滤（默认 15 个服务/机器账号）。

**这一跳是对账，不是重建**。每个用户只走一条分支：

| 分支 | 判据 | 动作 |
|---|---|---|
| 定位 | 先按 `kc_user_id` GET；为空或 404 则按 `username=login_name` 查 | 不发写请求 |
| 建号 | 上述都查不到 | `POST /users`（`username`/`email`/`firstName`/`lastName`/`enabled`，空值字段不写）→ 立刻回写 `kc_user_id`（不等邀请结果）→ 按邀请策略发信 |
| 改资料 | 查到了，但 `username`/`email`/`firstName`/`lastName`/`enabled` 任一不同 | `GET` 整对象 → 改字段 → `PUT` 整对象；**全部一致则一个写请求都不发** |
| 补回写 | 查到了但中央表 `kc_user_id` 为空/不一致（上一轮可能在回写前中止） | 只 `UPDATE kc_user_id` |
| 停用 | `status=0` 且 KC 仍 `enabled` | `PUT enabled=false` + `POST /users/{id}/logout` 踢会话（踢不掉只 WARN） |
| 复职 | `status=1` 且 KC 被禁用 | `PUT enabled=true`；`pwd_set=0` 时按邀请策略重发 |
| 设密状态回写 | 每轮末尾 | 读 `/users/{id}/credentials` 计数与 `requiredActions`，决定 `pwd_set=1` 还是保持 0（待首次改密） |

### 跳 3：Keycloak realm `inalfa`

- **client**：`msia-prod`（MSIA，`app-msia`）、`bol-prod`（BOL，`app-bol`）、`ics-prod`（Capacity）、`sync-client`（同步专用，不参与交互登录）、`account`（内置，邀请链接落地页）。
- **准入组**：`app-msia`、`app-bol` **必须是顶层组**（token 的 `groups` claim 取组名，应用后端按组名精确校验）。放进父组会变成 `/xxx/app-msia`，校验直接失败。当前成员按台账：`app-msia` 10 人、`app-bol` 6 人（`admin` 尚未在 KC 建号，未计入）。
- **用户属性里没有工号**：realm user profile 只保留了 `username`/`email`/`firstName`/`lastName`，没有 `employee_no` 自定义属性。所以 Keycloak 侧**无法按工号反查人**——工号只存在于中央表；应用侧能拿到的稳定标识是 `preferred_username`（即 `login_name`），需要工号时必须回 `CN_AME_SSO_User` 查。这也是登录脚本回写 `kc_user_id` 的意义：它把两端主键钉在一起，避免靠 username 猜。

应用侧身份解析顺序（已实现）：`groups` 准入 → `CN_AME_SSO_UserMap(system_code + local_username)` → 回落 `preferred_username` → 本地用户表 → 自动建档。

## 5. 例外与边界

| 事项 | 实际做法 | 注意 |
|---|---|---|
| `source='MANUAL'` | MERGE 的 UPDATE 与"名单消失→停用"两处都排除 MANUAL | `admin` 就是这样保住的：AD 名单里没有它，也永远不会被置 `status=0` |
| 排除名单 | 15 个服务/机器账号（`$duplicate-4f3a`、`t&e`、`svc-*`、`sccm-*` 等），**只在 `sync_sso_to_keycloak.ps1` 一处维护** | `sync_ad_to_sso.ps1` 的 `-KeycloakExcludeEmployeeNos` 默认空值=不传参，夜间任务自动沿用；账面上仍会进中央表，只是不进 Keycloak |
| `-SkipInvite` | 只建号、不回写密码、不发任何邀请邮件；汇总里单列"跳过邀请 N" | 新账号在管理员代设密码前无法登录；批量铺号时用，避免 SMTP 拖慢或误发 |
| `duplicateEmailsAllowed` | 已开启（允许重复邮箱） | 两个后果：① 建号不会因邮箱重复报 409；② "忘记密码"按邮箱定位用户不再唯一，可能把重置链接发给同邮箱的另一个人。登录用 username（`Login with email=OFF`），忘记密码也应引导用户填 username |
| 空邮箱 | 跳过邀请、写入"无邮箱"清单 WARN，改由管理员控制台代设密码 | 邮箱不是受管属性，允许为空 |
| 单人失败（H18） | 建号/改资料/停用/复职中单个用户 4xx/5xx → 记 WARN（工号 + login + HTTP 码 + Keycloak `errorMessage` 原文）、计入"失败 N"、继续下一个；末尾列前 20 条 | 三类仍立即中止：`401/403`、`HTTP 0`（网络/TLS）、非 KC 异常（SQL/凭据/文件）；`-StopOnError` 可恢复"一出错就停"；"0 成功 + 有失败"按致命处理 |
| 姓名脏字符（H19） | `firstName` 走回退分支时剔除 `< > " & $ % ! # ? § ; * ~ / \ | ^ = [ ] { } ( )` 与控制字符，压缩空白 | 只清洗回退值；中文姓名分支不动 |
| 同步方向 | **单向**：`SSO_User` → Keycloak | KC 里改密码、改姓名、改邮箱不会回流中央表；中央表也不从 KC 拉取任何字段，只写 `kc_user_id`/`pwd_set` |

## 6. 失败怎么走

| 现象 | 落在哪 | 处理 |
|---|---|---|
| 名单缺失/为空/防错闸门命中 | `SyncLog` `phase=LOAD`,`status=ABORTED` + 告警邮件 | 修数据后重跑；KC 段不会执行 |
| 灌表行数不符、SQL 连不上、凭据读不到 | `SyncLog` `phase=LOAD`,`status=ERROR`（脚本 `catch` 统一写 LOAD，即使失败发生在 MERGE 阶段）+ 邮件 | 看 `sync_ad_to_sso_yyyyMMdd.log` 尾部异常；退出码 1 |
| 单个用户建号 400（脏数据） | 日志 WARN + 汇总"失败 N"+ 名单 | 先看 Keycloak `errorMessage`：`error-username-invalid-character` / `error-person-name-invalid-character` 对应上面第 5 节 |
| 令牌 401/403、网络不通 | 立即中止，ERROR | 查 `sync-client` 的 service account 角色与时间同步；不要靠重试 |
| 邀请邮件发不出（404/超时） | WARN + "邀请未发出"清单，**不影响建号结果** | 账号已建、`kc_user_id` 已回写；管理员代设密码或下轮 `-ResendInviteForPasswordless` 补发 |
| 停用了但会话还在 | `POST logout` 失败只 WARN | 用户下一次刷新即掉线；必要时 `disable_user_now.ps1` |

常用只读核对：

```sql
-- 最近 10 轮（两支脚本 + 应急停号）
SELECT TOP 10 id, phase, run_at, src_rows, added, updated, disabled, reactivated, status, LEFT(message,120) AS msg
FROM dbo.CN_AME_SSO_SyncLog ORDER BY id DESC;

-- 已建号 / 未建号
SELECT COUNT(*) AS total,
       SUM(CASE WHEN kc_user_id IS NOT NULL THEN 1 ELSE 0 END) AS has_kc_id,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS active
FROM dbo.CN_AME_SSO_User;

-- MANUAL 行（免疫 AD 同步）
SELECT employee_no, login_name, display_name, status, pwd_set, kc_user_id
FROM dbo.CN_AME_SSO_User WHERE source = N'MANUAL';
```

## 7. 两套 MERGE 实现，别同时开

仓库里同时存在：

- 脚本内联 MERGE（`sync_ad_to_sso.ps1` 的 `Invoke-MergeCentralUser`，06:00 主链路，本文按它描述）；
- 库内存储过程 `dbo.usp_SSO_MergeStgToUser` + SQL Agent 作业 `SSO_Merge_StgToUser`（`07_merge_job_setup.sql`，默认每日 02:00）。

两者写同一张 `SSO_User`、同一套 `SyncLog`。若作业被启用，它会在 02:00 再合并一次上一轮 06:00 灌进去的暂存数据（结果幂等，但会多两条台账、且数据新鲜度落后一天）。**只保留 06:00 这条**，作业应保持禁用：

```sql
SELECT j.name, j.enabled FROM msdb.dbo.sysjobs j WHERE j.name = N'SSO_Merge_StgToUser';
```

## 8. 变更纪律

- 正式脚本是唯一事实来源：改逻辑直接改 `sync_sso_to_keycloak.ps1` / `sync_ad_to_sso.ps1`，用时间戳备份兜底；
- 不再新增 `patch_*.ps1`：现场文件与仓库文件 SHA256 一致后，补丁脚本即退场；
- 改完必须过 `PARSE`（`[Parser]::ParseFile` 零错误），再用 `-WhatIf` 类干跑确认影响面。
