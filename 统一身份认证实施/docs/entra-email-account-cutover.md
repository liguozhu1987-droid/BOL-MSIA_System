# 零改动切换 Microsoft Entra 邮箱账号（执行手册）

> 适用版本：Keycloak 25.0.6 / realm `inalfa` / `https://iame.ap.inalfa.local:8443` / SQL Server `CN_AME`
>
> 配套脚本：[entra_email_cutover.ps1](file:///C:/WorkFile/D/OPEX/04-Digital_development/2026/AI%20Agent%20Development%20Application/统一身份认证实施/scripts/powershell/entra_email_cutover.ps1)
>
> 前置条件：Entra Identity Provider `oidc` 已按 [entra-broker-setup-runbook.md](entra-broker-setup-runbook.md) 配好，并已完成一次测试登录
>
> 本手册中的个人身份信息已脱敏；未核实的现场值标「需现场确认」并附核查命令。

---

## 0. 一页看懂

### 0.1 目标与原理

清空 Keycloak 本地用户，让用户首次通过 Entra 登录时由联邦自动建档。账号名取 Entra 的 `preferred_username`（完整 UPN），因此账号名就是邮箱。

应用（MSIA、BOL）在映射表 `CN_AME.dbo.CN_AME_SSO_UserMap` 查不到人时，会回落到 `preferred_username`，因此原则上不写映射行，应用侧不需要改一行代码。

唯一例外是 MSIA 的 9 名历史责任人：为保住 232 条历史 Issue 的归属，需要为这 9 人写 9 行映射，并把这 9 行中央表的 `login_name` 改成邮箱（第 5.1 节）。这是数据配置，不涉及代码。

### 0.2 固定值

| 项 | 值 |
|---|---|
| Keycloak 地址 | `https://iame.ap.inalfa.local:8443` |
| realm | `inalfa` |
| 管理员 realm / 账号 | `master` / `kcadmin`（若现场把管理员建在 `inalfa`，脚本传 `-AdminRealm inalfa`） |
| IdP alias | `oidc` |
| 准入组 | `app-msia`、`app-bol`（必须是顶层组） |
| 应用 clientId | `msia-prod`、`bol-prod` |
| 中央表 | `CN_AME.dbo.CN_AME_SSO_User` |
| 映射表 | `CN_AME.dbo.CN_AME_SSO_UserMap` |
| 保留名单规则 | `employee_no='admin'` + `source='MANUAL'` + 邮箱重复的行；另加 Keycloak 服务账号 |
| 保留名单现场口径 | 40（admin + 39 个共享信箱/服务类账号），以脚本 `DbCount` 为准 |
| 账号长度上限 | BOL 本地 `username` 50；MSIA 本地 `Username` varchar(100) |
| 中央表字段 | `kc_user_id`、`pwd_set` 保留原值，不再参与身份，不影响登录 |

### 0.3 三个硬门槛

以下三项任一不满足，不进入第 4 步清空：

1. **用户名模板**必须是 `${CLAIM.preferred_username}`，不能带 `|localpart`；同时核实 realm 的 `Email as username` 开关（第 1.2 节）。
2. **长度预检**：按 Entra UPN 计，超过 50 字符的账号必须为 0；超过 100 的必须为 0（第 1.1 节）。
3. **四组撞车邮箱**已定案，保留名单为 40（第 2 节）。

### 0.4 本方案不改什么，代价是什么

- 不改应用代码；中央表 `status`、`email` 不动，`kc_user_id`、`pwd_set` 默认不重置。写库动作只有两处：第 5.1 节为 9 名历史责任人写 9 行映射 + 改 9 行 `login_name`；第 5.3 节字段重置（可选）。
- 应用会按最低权限给 UPN 账号自动建档：MSIA 为 `reviewee`，BOL 为 `VIEWER`。**这不等于账号完整可用**：BOL 能看到全部跟踪数据但只读；MSIA 的 reviewee 工作台为空（应用按 `login_name` 过滤，邮箱账号匹配不上）。具体见 3.3。
- 原有短名账号及其角色不会迁移。`app-msia`、`app-bol` 只管准入，权限级别由应用内的 `Role` / `role` 字段决定，提权在应用侧操作（3.3）。
- 中央表状态回写、应急停号、BOL 离职同步会失效，替代流程见第 8 节；这是本方案的已知边界，不是故障。

### 0.5 执行顺序

| 步骤 | 动作 | 脚本命令 | 通过后才做 |
|---|---|---|---|
| 1 | 前置检查、备份 | `-Action Precheck` | 第 2 步 |
| 2 | 处理重复邮箱、确认保留名单 | 看 Precheck 输出的 CSV | 第 3 步 |
| 3 | 配置 Default Groups | `-Action SetDefaultGroups -Execute` | 第 4 步 |
| 4 | 清空本地用户 | `-Action Purge -Execute -ExpectedKeepCount 40` | 第 5 步 |
| 5 | 9 人历史归属（建议做）+ 中央表字段（可选） | `Add-SsoUserMapForLegacyOwners.ps1 -Action Apply -AlignLoginName`；见第 5 节 | 第 6 步 |
| 6 | 单账号首登验证 MSIA/BOL | 浏览器 + SQL 核对 | 全体放行 |
| 7 | 回滚（仅在需要时） | 见第 7 节 | — |

---

## 1. 前置检查与备份

### 1.1 跑只读核查

**操作位置**：在能访问 Keycloak 和 SQL Server 的 Windows 机器上，以管理员身份打开 PowerShell。

首次使用先把脚本放到现场固定目录 `C:\sso\scripts\entra_email_cutover.ps1`（后续命令都用这个路径；交付包里对应 `统一身份认证实施\scripts\powershell\entra_email_cutover.ps1`）。

**命令**：

```powershell
cd C:\sso\scripts
.\entra_email_cutover.ps1 -Action Precheck
```

如果本机不信任 Keycloak 的内网证书，先安装企业 CA；临时排查可加 `-SkipCertCheck`，不要把它写进固定作业：

```powershell
.\entra_email_cutover.ps1 -Action Precheck -SkipCertCheck
```

**输出文件**（默认在 `C:\sso\tmp`）：

| 文件 | 用途 |
|---|---|
| `keep_users_<时间戳>.csv` | 保留名单明细，含 `keep_reason` |
| `keep_usernames_<时间戳>.txt` | 保留名单 username，一行一个，供人工复核/`-KeepFile` 使用 |
| `email_duplicates_<时间戳>.csv` | 重复邮箱的每一行 |
| `email_collision_groups_<时间戳>.csv` | 按邮箱汇总的撞车组及人数 |
| `overlong_usernames_<时间戳>.csv` | 邮箱/UPN 长度 > 50 的清单 |

**成功判据**：

- 屏幕最后一行是 `结论: GO`，且 `阻断 0`。
- Precheck 输出第 7 节（中央表）的 `数据库保留名单` 为 40。
- Precheck 输出第 7 节的 `邮箱/UPN 长度不超过 BOL 上限 50` 为 `[通过]`。

**失败排查**：

| 现象 | 原因 | 处理 |
|---|---|---|
| `取 token 失败 (HTTP 401)` | 管理员 realm 或密码不对；`admin-cli` 未开 Direct Access Grants | 确认 `kcadmin` 在 `master`；若在 `inalfa`，加 `-AdminRealm inalfa` |
| TLS/证书握手失败 | 本机不信任内网 CA | 安装企业 CA；临时用 `-SkipCertCheck` 只做核查 |
| `凭据文件不存在` / 数据库登录失败 | `C:\sso\conf\credentials.xml` 或条目名不对 | 核对 `-CredentialFile` 和 `-SqlCredentialName`；不要改脚本硬编码口令 |
| `IdP 'oidc' 存在` 阻断 | IdP 未配置或 alias 不是 `oidc` | 先按 `entra-broker-setup-runbook.md` 完成 IdP |
| `client ... groups mapper` 阻断 | `full.path=true` 或 `id.token.claim=false` | 在 client 的 Mappers 里把 Group Membership 改为 `full.path=false`、`id.token.claim=true` |
| `SSO_AD_Import 已停止串联 Keycloak` 告警 | 现场存在该任务且未加 `-SkipKeycloakSync` | 按 1.3 处理 |

### 1.2 核查用户名模板与 Email as username

**操作位置**：

- 用户名模板：管理控制台 → 选择 realm `inalfa` → 身份提供程序 → `oidc` → Mappers → `Username Template Importer`。
- Email as username：管理控制台 → 领域设置 → 登录 → `Email as username`。

**命令**（`kcadm.bat` 路径以现场 Keycloak 安装目录为准）：

```cmd
C:\keycloak\bin\kcadm.bat config credentials --server https://iame.ap.inalfa.local:8443 --realm master --user kcadmin
C:\keycloak\bin\kcadm.bat get identity-provider/instances/oidc/mappers -r inalfa --fields name,identityProviderMapper,config
C:\keycloak\bin\kcadm.bat get realms/inalfa --fields registrationEmailAsUsername,duplicateEmailsAllowed
```

**判定标准**：

| 现场情况 | 判定 | 动作 |
|---|---|---|
| 模板为 `${CLAIM.preferred_username}`，Target 为 `LOCAL`（或 `BROKER_USERNAME`） | 通过 | 无 |
| 模板含 `|localpart` 或 `${ALIAS}` 前缀 | **NO-GO** | 改为 `${CLAIM.preferred_username}`，Target 改为 `LOCAL` |
| Target 为 `BROKER_ID` | **NO-GO** | 改为 `LOCAL` |
| 没有 `Username Template Importer` | 等效通过（Keycloak 默认取 `preferred_username`） | 建议补一个显式模板，便于审计；Precheck 会告警 |
| `Email as username=OFF` | 通过 | 无 |
| `Email as username=ON`，且 Entra 的 `mail` 与 `userPrincipalName` 完全一致 | 等效通过 | 记录该状态 |
| `Email as username=ON`，但 `mail` 与 UPN 不一致 | **NO-GO** | 关闭该开关；或让 IT 统一 `mail=UPN` |

**成功判据**：Precheck 的第 1 节 `Email as username` 为 `[通过]`，第 3 节 `用户名模板` 为 `[通过]`。

**失败排查**：

- 改完模板后，如果之前已经用错误的模板登录过测试账号，Keycloak 里会留下短名账号。先删掉该测试账号，再重新首登；否则会一直复用短名。
- `Email as username` 在 Keycloak 25 的菜单位置是「领域设置 → 登录」，不是「用户注册」页。

### 1.3 确认没有会自动重建账号的作业

**现场结论**：`sync_sso_to_keycloak.ps1` 从未正式部署为定期任务，现场没有会调用它的计划任务。因此这一步不是"停作业"，而是"确认现状 + 依靠脚本内置保护"。

**操作位置**：任意管理员 PowerShell。

**命令**：

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like '*SSO*' -or $_.TaskName -like '*Import*' } |
  Select-Object TaskName, State
```

**成功判据**：列表为空，或列出的任务不调用 `sync_sso_to_keycloak.ps1`。

**如果现场确实存在这样的任务**（与结论不符），按下面任一种处理：

```powershell
# 方式一：保留 AD 刷新，只去掉 Keycloak 段
$a = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\sso\scripts\sync_ad_to_sso.ps1 -SkipKeycloakSync'
Set-ScheduledTask -TaskName 'SSO_AD_Import' -Action $a
(Get-ScheduledTask -TaskName 'SSO_AD_Import').Actions.Arguments

# 方式二：整任务禁用
Disable-ScheduledTask -TaskName 'SSO_AD_Import'
```

**保护（已在脚本里内置，现场不需要改代码）**：`sync_sso_to_keycloak.ps1` 启动后先读 Keycloak 用户结构；当用户名多数为邮箱格式（含 `@`，且不少于 20 个）时直接拒绝执行——退出码 2，不建号、不改中央表，并发告警邮件。

**验证时机**：只能在第 4 节清空完成后验证。切换前短名账号占多数，保护按设计不会触发，此时执行会真的建号，不要用它来"试一下"。

```powershell
C:\sso\scripts\sync_sso_to_keycloak.ps1 -SkipInvite
"exit=$LASTEXITCODE"
```

清空后应得到 `exit=2`，日志首行为「拒绝执行：Keycloak 里多数用户已是邮箱格式」。

**失败排查**：

- 应当拒绝却继续建号：说明 Keycloak 里短名账号仍占多数（清空没做完）。先回第 4 节，再验证。
- 报认证失败而不是拒绝执行：保护需要读用户列表，凭据问题按 1.1 排查。

### 1.4 备份

#### 1.4.1 导出 realm

**操作位置**：Keycloak 安装目录的 `bin`。

**命令**：

```cmd
mkdir C:\sso\kc-export\pre-entra-email
C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export\pre-entra-email --realm inalfa --users per_file
```

**成功判据**：目录下有 `inalfa-realm.json` 和 `inalfa-users-0.json`；用户文件里的账号数与 Precheck 的用户总数一致。

**注意**：这个导出不含可用密码，只能用于重建账号壳，**不是还原点**。真正的还原点是下面的数据库备份。

#### 1.4.2 备份中央表

**操作位置**：SQL Server Management Studio，用有建表权限的账号（如 `ytview`）执行。

**命令**（把日期后缀换成实际日期）：

```sql
USE CN_AME;
SELECT * INTO dbo.CN_AME_SSO_User_bak_20261113      FROM dbo.CN_AME_SSO_User;
SELECT * INTO dbo.CN_AME_SSO_UserMap_bak_20261113   FROM dbo.CN_AME_SSO_UserMap;
SELECT * INTO dbo.CN_AME_SSO_PermLedger_bak_20261113 FROM dbo.CN_AME_SSO_PermLedger;
```

**成功判据**：三张备份表的行数与原表一致。

**失败排查**：`CREATE TABLE` 权限不足时找 DBA 做一次 `CN_AME` 全库备份；不要用 `SELECT INTO` 以外的写操作绕过权限。

### 1.5 Go/No-Go 签核

以下 6 项全部为「通过」才进入第 2 步：

| # | 检查项 | 来源 |
|---|---|---|
| 1 | IdP `oidc` 已启用，登录页显示按钮，首次登录流程不是默认 `first broker login` | Precheck 第 2 节 |
| 2 | 用户名模板 = `${CLAIM.preferred_username}`，无 `localpart`；`Email as username` 状态已核实 | 1.2 + Precheck 第 1/3 节 |
| 3 | `msia-prod`、`bol-prod` 的 groups mapper 为 `full.path=false`、`id.token.claim=true` | Precheck 第 5 节 |
| 4 | 保留名单 `DbCount=40`，且能解释每一行 | Precheck 第 7 节 + 第 2 节 |
| 5 | 邮箱/UPN 长度 > 50 的账号为 0；> 100 的为 0 | Precheck 第 7 节 |
| 6 | 现场没有会调用 `sync_sso_to_keycloak.ps1` 的定期任务（若存在，已加 `-SkipKeycloakSync` 或已禁用） | 1.3 + Precheck 第 8 节 |

---

## 2. 处理重复邮箱

### 2.1 先看现状

**操作位置**：SSMS，`CN_AME` 库。

**命令**：

```sql
SELECT COUNT(*) AS total_rows,
       SUM(CASE WHEN email IS NOT NULL AND LTRIM(RTRIM(email)) <> '' THEN 1 ELSE 0 END) AS email_filled,
       COUNT(DISTINCT LTRIM(RTRIM(LOWER(email)))) AS distinct_email
FROM dbo.CN_AME_SSO_User;
```

**核定值**：2944 行、邮箱有值 2944 行、distinct 2911。重复行数 = 2944 - 2911 = 33。

注意：33 是「重复出来的行数」，不是 33 个邮箱。实际涉及多少个邮箱、每个邮箱几个人，以 `email_collision_groups_<时间戳>.csv` 为准。

**成功判据**：查询结果与 Precheck 第 7 节打印的数字一致；不一致时以现场查询为准，并在变更记录里注明。

### 2.2 风险只有一句话

在 Entra 里，同一个 UPN 就是同一个登录身份。两个人如果共用同一个 UPN，进入 Keycloak 和应用后就是同一个账号，系统无法区分是谁。中央表邮箱重复不等于 Entra UPN 重复，必须到 Entra 核实这四组人的 `userPrincipalName`。

### 2.3 四组撞车邮箱的处理

| 邮箱（脱敏） | 人数 | 已核实的性质 | 处理 |
|---|---|---|---|
| `fa.cncq` | 5 | 多人共用 | 在 Entra 查这 5 人的 UPN。若共用同一 UPN，IT 必须拆分；未拆分前这 5 行保留本地，不切 |
| `nb.cncq` | 4 | 多人共用 | 同上 |
| `jas***` | 2（在职 + 离职各一） | 一人多号/历史重复 | 保留在职号，离职号在中央表置 `status=0`；切换后只用在职 UPN，不删除历史行 |
| `cngz.gz121` | 2 | 两人共用 | 同 `fa.cncq`：先查 Entra UPN，共用则拆分，未拆分前保留本地 |

除这四组外，其余重复项是共享服务信箱或一人多号；本次一律保留本地，不参与清空。

**操作步骤**（对每一组执行）：

1. 打开 `C:\sso\tmp\email_collision_groups_<时间戳>.csv`，找到该组，记录 `email_key`、`user_count`、`login_names`。
2. 在 Entra 管理中心 → 用户 → 搜索这些 `login_name` 或邮箱，查看每个人的 `userPrincipalName`；也可以让 IT 导出这四组的 UPN 清单。`jas***` 的完整邮箱以 CSV 为准，本文不写全。
3. 按下面的判定处理：

| 核实结果 | 判定 | 动作 |
|---|---|---|
| 多个人共用同一个 UPN | 身份撞车 | 该组暂不切；让 IT 先分配唯一 UPN。这组账号由保留规则自动留在本地 |
| 每个人 UPN 各不相同 | 只是中央表邮箱重复 | 可以正常切；这组旧本地账号仍保留，等本人用 UPN 首登成功后再停用旧号 |
| 同一人的在职号 + 离职号 | 历史重复 | 保留在职号；离职号在中央表置 `status=0`，不要删除历史行 |

4. 把判定结果写进变更记录，附上 `email_collision_groups_<时间戳>.csv`。保留名单不需要手工编辑：脚本已按邮箱重复规则自动保留这些行。
5. 切换后，等本人用 UPN 首登成功、确认新账号可用，再停用对应的旧本地账号。

**用于定位四组的 SQL**（`jas%` 只用于粗筛，完整值以 CSV 为准）：

```sql
;WITH d AS (
    SELECT LTRIM(RTRIM(LOWER(email))) AS email_key, COUNT(*) AS user_count
    FROM dbo.CN_AME_SSO_User
    WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> ''
    GROUP BY LTRIM(RTRIM(LOWER(email)))
    HAVING COUNT(*) > 1
)
SELECT d.email_key, d.user_count
FROM d
WHERE d.email_key LIKE 'fa.cncq@%'
   OR d.email_key LIKE 'nb.cncq@%'
   OR d.email_key LIKE 'cngz.gz121@%'
   OR d.email_key LIKE 'jas%@%'
ORDER BY d.user_count DESC;
```

**成功判据**：四组都在 CSV 中定位到；每组都有「共用 UPN / 各自 UPN / 一人多号」的明确结论；保留名单仍为 40。

**失败排查**：

- 某组人数与上表不一致：先不要继续，按 CSV 的实际人数重新核对；人数变化说明数据在此期间被同步过。
- 无法从 Entra 确认 UPN：该组按「暂不切」处理，保留本地，不影响其他 2782 人切换。
- 不要为了让邮箱唯一而改中央表 `email` 或 `login_name`。夜间的 AD 同步会覆盖，且应用身份取的是 UPN，不是这两个字段。

---

## 3. 配置 Default Groups

### 3.1 管理台方式

**操作位置**：管理控制台 → realm `inalfa` → 领域设置 → 组 → 默认组 → 添加组。

依次添加 `app-msia`、`app-bol`，保存。

### 3.2 脚本方式（推荐，幂等）

**命令**：

```powershell
cd C:\sso\scripts
.\entra_email_cutover.ps1 -Action SetDefaultGroups -Execute
```

不带 `-Execute` 只预演，不写入。

**成功判据**：脚本最后打印的默认组列表同时包含 `app-msia`、`app-bol`；Precheck 第 4 节变为 `[通过]`。

**失败排查**：

- 报「只允许顶层组」或「存在非顶层/大小写不一致的同名组」：先在控制台改正组结构，不要临时建空组，也不要使用嵌套组。
- 报 403：`kcadmin` 缺少 `manage-realm`；换有权限的管理员。
- 添加成功但 Precheck 仍失败：检查是否加到了别的 realm，或同名组有多个。

### 3.3 这条配置意味着什么

**权限边界**：`app-msia`、`app-bol` 只决定"能不能进"（准入），不决定"能做什么"（权限级别）。权限级别由应用内的角色字段决定——MSIA 是 `CN_AME_MISA_User.Role`，BOL 是 `CN_IE_BOL_Employee.role`。提权在应用侧操作，改 Keycloak 组不会提升任何人的权限。

**预期最终效果**：清空本地用户后，每个首次通过 Entra 登录的人都会自动带上这两个组，因此所有能登录 Entra 的人都能进 MSIA 和 BOL，进来后是最低权限角色；需要更高权限的人由业务管理员在应用里单独授权。

**三个实际行为**（切换前要让业务部门知道，否则会被当成故障）：

| 行为 | 现场表现 | 说明 |
|---|---|---|
| BOL 最低权限是"全量只读" | `VIEWER` 能看到全部跟踪数据，但没有编辑、审批入口 | 不是"只看自己的数据"。要按人收敛数据范围只能改应用，本方案不做 |
| MSIA 的 reviewee 工作台为空 | 能登录、能进主界面，但待办/工作台没有数据 | 工作台按 `login_name` 过滤，邮箱账号匹配不上；需要看自己数据的人要在 MSIA 里绑工号或提权 |
| 默认组不追溯，手工建号不带组 | 已存在的用户不会被补上组；在控制台手工新建的用户也不会自动带组 | 手工建号后要手动把 `app-msia`、`app-bol` 加进 Groups。本方案是清空后由首登建档，因此不受影响 |

**两条仍需现场确认**：

- Capacity 如果也在本次切换范围，必须同时把 `app-ics` 设为默认组，否则 Capacity 会因 `OIDC_REQUIRE_GROUP=app-ics` 返回 403。
- 如果应用读取的是 `access_token` 而不是 `id_token`，groups mapper 还需要打开 `access.token.claim`；现有 MSIA/BOL 读的是 id_token，Precheck 只校验 id_token。


---

## 4. 清空本地用户

### 4.1 复核保留名单

**操作位置**：PowerShell。

**命令**：

```powershell
Get-Content C:\sso\tmp\keep_usernames_<时间戳>.txt
```

**成功判据**：40 行；每行都能在 `keep_users_<时间戳>.csv` 的 `keep_reason` 里找到 `ADMIN`、`MANUAL` 或 `SHARED_EMAIL`。

**失败排查**：少于 40 行，先回第 2 节看四组是否被漏掉；多于 40 行，按 CSV 逐行解释，解释不了就不要执行删除。

另外，如果 `inalfa` realm 里除 `admin` 之外还有运维用的管理员账号（例如按人名建的 realm 管理账号），这些账号不在中央表保留规则里，会被当成普通本地用户删除。执行前先在控制台 → 用户 里按 `admin`、`manage-realm` 角色筛一遍，把不在 40 人名单里的管理员账号补进保留名单：

```powershell
.\entra_email_cutover.ps1 -Action Purge -KeepUsernames '<管理员账号1>,<管理员账号2>'
```

补人后 `-ExpectedKeepCount` 仍填中央表保留人数（40），追加账号不计入这个数字，脚本会单独打印「人工追加保留: N 个」。第 5.3 节的字段重置是可选项，若决定执行重置，必须用同一组 `-KeepFile` / `-KeepUsernames`，否则这些管理员行也会被重置。

### 4.2 预演

**命令**：

```powershell
cd C:\sso\scripts
.\entra_email_cutover.ps1 -Action Purge
```

**成功判据**：输出里的数字满足以下关系：

| 项 | 预期 |
|---|---|
| Keycloak 用户总数 | 约 2944 |
| 保留名单命中 | 约 40 |
| 服务账号 | 按现场实际，脚本恒定保留 |
| 已由 Entra 建档（含 `@`） | 0（首次切换时） |
| 本轮将删除 | 总数 - 保留 - 服务账号 - `@` 账号 |

**失败排查**：

- `@` 账号不为 0：说明之前已经有人通过 Entra 登录过。脚本会跳过这些账号，不会误删；先确认来源，再决定是否继续。
- 将删除数明显偏小：检查 `keep_users` 是否把不该保留的人算进了重复邮箱组。

### 4.3 执行删除

**命令**：

```powershell
.\entra_email_cutover.ps1 -Action Purge -Execute -ExpectedKeepCount 40
```

脚本会在删除前比对 `-ExpectedKeepCount` 和数据库实际保留人数；不一致直接拒绝执行。这是第二道闸门，不要为了「先跑起来」随便改数字。

删除完成后脚本会自动执行全量登出，并核对在线会话和离线会话。

**成功判据**：

- 删除后剩余用户 = 40 个保留账号 + 服务账号（以脚本输出为准）。
- 在线会话 0，离线会话 0。
- 用 `admin` 能正常登录管理控制台。

**失败排查**：

| 现象 | 原因 | 处理 |
|---|---|---|
| `拒绝执行：-ExpectedKeepCount=...` | 输入数字与实际保留人数不一致 | 重跑 Precheck，按 `DbCount` 重新核对；不要强行执行 |
| 401/403 | 管理员 realm/权限不对 | 核对 `-AdminRealm`、`kcadmin` 的 `manage-users` 权限 |
| 个别用户删除失败（409/500） | Keycloak 瞬时错误/关联数据 | 直接重跑同一条命令；404 视为已删除，不会重复报错 |
| 残留会话不为 0 | 刚删完还有缓存/离线令牌 | 等 1 分钟重跑 `-Action Verify`；仍在则管理台 → Sessions → Logout all，并删除离线会话 |
| 剩余用户比预期多 | `@` 账号被跳过，或服务账号未识别 | 用 `find_at_username_users.ps1` 盘点 `@` 账号；确认后再决定是否清理 |

> 执行时间：2900 个账号逐个删除，通常需要数分钟。中途不要按 Ctrl+C；中断后重跑是安全的，已删除的账号会返回 404 并被跳过。

---

## 5. 映射与中央表字段

### 5.1 MSIA 9 名历史责任人：保住 232 条历史数据（建议做）

**决议：做。** 依据与口径：

- MSIA `Issue` 表共 234 行，其中 **232 行**通过 `OwnerUserId` 挂在 9 个短名账号下。切换后这 9 人用 UPN 登录，应用查不到映射就会新建空账号，232 条数据全部失去归属。
- 恢复成本只有 9 行数据，且脚本自带回滚，因此纳入本次切换，放在第 5 步执行。
- 机制：应用用 `preferred_username` 匹配 `CN_AME_SSO_User.login_name`，命中后再按 `employee_no + system_code='msia'` 取 `CN_AME_SSO_UserMap.local_username`。所以两步缺一不可：**这 9 行的 `login_name` 必须等于本人 UPN**，**同时写入 9 行映射指向原短名**。只写映射不会命中；只改 `login_name` 会新建空账号。

**执行位置**：第 4 步清空本地用户之后、第 6 步首登验证之前。9 人清单与各人问题条数已内置在脚本的 `$MapData` 中（按 2026-11-13 只读统计：未删除问题合计 158 条，其中未关闭 20 条；以现场 `-Action Preview` 输出为准）。

**命令**（`C:\sso\scripts` 下，管理员 PowerShell）：

```powershell
.\Add-SsoUserMapForLegacyOwners.ps1                                       # 预览，只读
.\Add-SsoUserMapForLegacyOwners.ps1 -Action Apply -AlignLoginName -WhatIf  # 看将写入的行
.\Add-SsoUserMapForLegacyOwners.ps1 -Action Apply -AlignLoginName          # 正式写入（单事务）
.\Add-SsoUserMapForLegacyOwners.ps1 -Action Verify                         # 只读校验
```

**成功判据**：

- 预览与执行输出中 9 人全部按 `employee_no` 命中，没有「`login_name` 仍为短名」的告警；
- `CN_AME_SSO_UserMap` 中 `system_code='msia'` 由 0 行变为 9 行，原有行不受影响；
- 9 人的 `CN_AME_SSO_User.login_name` 均等于本人 UPN，唯一索引 `UQ_CN_AME_SSO_User_Login` 无冲突；
- 这 9 人首登后 MSIA 工作台能看到原有条数，`CN_AME_MISA_User` 不新增 UPN 账号。

**失败排查**：

- 提示「`login_name` 仍为短名，中止」：漏了 `-AlignLoginName`，脚本未写入任何数据；
- 提示 UPN 已被中央表另一行占用：回到第 2 节核对重复邮箱，不要强行改；
- 退出码 2：前置一致性检查未通过，按输出逐条修正后重跑，不会留下半成品。

**回滚**：`.\Add-SsoUserMapForLegacyOwners.ps1 -Action Rollback -RollbackLoginName`，删除 9 行映射并把 `login_name` 改回短名。必须在恢复本地账号（第 7.2 节第 5 步）之前执行，否则重建出来的会是邮箱名账号。

**范围边界**：仅 MSIA。BOL 的目标账号在 `CMC.dbo.CN_IE_BOL_Employee`，当前环境没有 CMC 只读权限，BOL 侧历史数据的损失量尚未统计，不在本步范围（附录 A #10）。

### 5.2 为什么不再需要重置 kc_user_id / pwd_set

中央表 `CN_AME_SSO_User` 继续保留，除 5.1 的 9 行 `login_name` 外，`employee_no`、`status`、`email` 全部不动。切换后身份来自 Entra：

- Keycloak 的用户名是 `preferred_username`（UPN），与中央表的 `kc_user_id` 已无对应关系。
- `pwd_set` 只对本地密码账号有意义，UPN 账号的密码在微软侧。
- 应用解析身份时先查 `CN_AME_SSO_UserMap`，查不到就用 `preferred_username`；两者都不读 `kc_user_id`、`pwd_set`。

所以这两列是否为空、是否为 1，都不影响登录，也不影响第 6 节的验证。**默认跳过 5.3**，保留原值即可；只有当 DBA 希望中央表恢复成"无绑定"状态时才执行 5.3。

### 5.3 需要时如何重置

**命令**（先预演，确认数字后再执行）：

```powershell
cd C:\sso\scripts
.\entra_email_cutover.ps1 -Action ResetDb
.\entra_email_cutover.ps1 -Action ResetDb -Execute
```

对应的 SQL 逻辑：

```sql
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = NULL,
    pwd_set    = 0
WHERE login_name NOT IN (/* 保留名单，脚本自动生成 */);
```

**成功判据**：复核结果为 `kc_user_id 有值 0`、`pwd_set=1 0`；保留名单的 40 行未被改动。

**失败排查**：

- 复核不为 0：检查是否有在 4.1 追加过的管理员账号——重置命令必须带上与删除时相同的 `-KeepFile` / `-KeepUsernames`，否则这些行也会被重置。

### 5.4 不要改的字段

`employee_no`、`status`、`email` 都不改；除 5.1 的 9 行 `login_name` 与 9 行映射外，不再新增或修改任何映射行。

切换后其余人员的 `login_name`（短名）不再等于 Keycloak 用户名（UPN），这是预期状态，也是第 8 节那些脚本失效的原因。

---

## 6. 首登验证

先用一个真人账号走通 Keycloak → MSIA → BOL，再全体放行。

### 6.1 选测试账号

条件：Entra 里可正常登录；不在第 2 节四组撞车邮箱里；不是 `admin` 或共享信箱；账号名不含特殊字符。

记下这个账号的 UPN，例如 `test.user@ap.inalfa.local`（示例，不是现场值）。

### 6.2 Keycloak 账号控制台

**操作位置**：无痕窗口打开 `https://iame.ap.inalfa.local:8443/realms/inalfa/account`，点 Entra ID 登录。

**命令**（核对建档结果）：

```cmd
C:\keycloak\bin\kcadm.bat get users -r inalfa -q username="<测试 UPN>" -q exact=true --fields id,username,email,enabled
C:\keycloak\bin\kcadm.bat get users/<上一步返回的 id>/groups -r inalfa --fields name,path
```

**成功判据**：

- 用户名 = 完整 UPN，不是短名。
- 邮箱 = UPN（或 Entra 下发的 mail，且与 UPN 一致）。
- 组里有 `app-msia`、`app-bol`。
- 用短名再查一次，返回 0 条，说明没有重复建档。

**失败排查**：

| 现象 | 原因 | 处理 |
|---|---|---|
| 登录页没有 Entra 按钮 | IdP 被隐藏/禁用 | 回 1.1 检查 `hideOnLoginPage`、`enabled` |
| 首登要求补资料/验证邮箱 | 还在用默认 `first broker login` 流程 | 回 1.1 检查 `firstBrokerLoginFlowAlias` |
| 用户名是短名 | 模板带了 `|localpart` | 回 1.2 改模板；删掉测试账号后重试 |
| 组里没有 app-msia/app-bol | 默认组未生效/未配置 | 回第 3 节；确认是新用户，不是旧用户 |
| `email already exists` | 该邮箱已被其他账号占用，或 realm 关闭了 Duplicate emails | 回第 2 节核实；必要时在领域设置 → 登录打开 `Duplicate emails` |

### 6.3 MSIA 链路

**操作位置**：MSIA 登录入口（IIS 切换后为 `https://iame.ap.inalfa.local:8078`；若现场仍是 HTTP，以实际入口为准，需现场确认）。用测试 UPN 通过 Entra 登录。

**命令**（核对本地自动建档）：

```sql
SELECT Username, DisplayName, Email, Role, Status
FROM dbo.CN_AME_MISA_User
WHERE UPPER(Username) = UPPER('<测试 UPN>');
```

**成功判据**：

- `Username` = 完整 UPN。
- 只有 1 条记录。
- 新账号 `Role=reviewee`、`Status=1`。
- 页面能进入主界面，不出现 403。**工作台为空是预期**：reviewee 数据按 `login_name` 过滤，邮箱账号匹配不上（见 3.3）。

**失败排查**：

- 403：先看 Keycloak 组和 groups mapper（第 3 节、1.1），再看 MSIA 日志里的 `OIDC` 输出。
- 500：如果 UPN 超过 50 字符，先怀疑 BOL；MSIA 上限 100，超过 100 才会失败。
- 新建了两条：检查大小写差异；应用侧已做忽略大小写查重，若仍重复，保留一条并删除另一条。

### 6.4 BOL 链路

**操作位置**：BOL 登录入口（IIS 切换后为 `https://iame.ap.inalfa.local:8090`，需现场确认）。用同一个测试 UPN 登录。

**命令**：

```sql
SELECT username, name, email, role, status
FROM dbo.CN_IE_BOL_Employee
WHERE UPPER(username) = UPPER('<测试 UPN>');
```

**成功判据**：

- `username` = 完整 UPN，且只有 1 条。
- `role=VIEWER`、`status=ACTIVE`。
- 页面能进入，不出现 403/500。`VIEWER` 能看到全部跟踪数据但没有编辑入口，这是预期（见 3.3），不要当成越权漏洞。

**失败排查**：

- **500**：优先查 UPN 长度是否超过 50。这是未捕获异常，日志里通常能看到 `String or binary data would be truncated` 或数据库列长度错误。处理见 1.1 的长度预检。
- 403：检查 groups mapper 和默认组；BOL 还要求 `trusted_proxy` 配置正确，但本次不改应用配置，若切换前正常，切换后一般不受影响。

### 6.5 交叉核对

**命令**：

```sql
SELECT system_code, COUNT(*) AS rows_count
FROM dbo.CN_AME_SSO_UserMap
GROUP BY system_code;
```

**成功判据**：

- `CN_AME_SSO_UserMap` 行数 = 切换前基线 + 9（第 5.1 节）。现有基线为 2 行（均为 admin 映射），做完 5.1 后应为 11 行；若现场基线不同，以 Precheck 记录为准，且不应为测试账号新增行。
- 退出后重新登录，Keycloak 用户数不增加，应用本地账号不增加。

### 6.6 全体放行

测试账号连续登录两次都稳定后，通知全员使用 UPN 登录。放行后重点观察：

- Keycloak 事件里的登录失败原因（重点看 `email already exists`、`invalid redirect`）。
- MSIA/BOL 的 403/500 日志。
- 第 2 节四组撞车账号的登录情况；这些账号本轮仍走本地，不要催促。

放行后收到的权限诉求一律在应用内处理：MSIA 调 `CN_AME_MISA_User.Role`，BOL 调 `CN_IE_BOL_Employee.role`。Keycloak 组只决定准入，改组不改变权限级别。

---

## 7. 回滚

### 7.1 先判断回滚规模

- 只登录了几个测试账号：关闭 Entra 登录入口，删掉测试 UPN 账号即可，不需要重建 2822 人。
- 已经全体放行：按下文的完整回滚执行。

### 7.2 完整回滚步骤

1. 停止新的 UPN 建档：
   - Entra 管理中心 → 企业应用 → 对应应用 → 属性 → 「需要分配」设为「是」；或
   - Keycloak 管理控制台 → 身份提供程序 → `oidc` → 关闭 `Enabled`。
2. 删除已经由 Entra 建档的 UPN 账号：

```powershell
cd C:\sso\scripts
.\entra_email_cutover.ps1 -Action Purge -Scope Federated -Execute -ExpectedKeepCount 40
```

3. 撤销 9 人映射与 `login_name`（若执行过 5.1 节）：

```powershell
C:\sso\scripts\Add-SsoUserMapForLegacyOwners.ps1 -Action Rollback -RollbackLoginName
```

4. 恢复 AD 刷新作业（如果现场原本有）：把计划任务的参数或启用状态改回 1.3 之前的样子。
5. 重建本地账号：

```powershell
C:\sso\scripts\sync_sso_to_keycloak.ps1
```

按需加 `-SkipInvite` 跳过邀请邮件。中央表里残留的 `kc_user_id` 不影响重建：脚本按该 ID 查不到人时会自动回落到 `login_name` 新建账号，并回写新的 ID。所以第 5 节的重置在回滚时也不需要补做。

6. 核对 `admin` 和一个普通账号能登录；默认组仍在，新建的本地账号会自动带上 `app-msia`、`app-bol`。
7. 应用侧的 UPN 本地账号（MSIA/BOL）不会自动消失，需要手工停用；旧短名账号及其角色仍然在，恢复后继续使用。

### 7.3 回滚代价与边界

- 关闭 IdP 不等于回滚。本地用户已经清空，必须重新建号，代价与正向切换同量级。
- 2822 个账号重建 + 邀请邮件，不是即时完成；回滚窗口要按批量建号的时长预留。
- realm 导出不含可用密码，不能作为还原点；真正的还原点是 1.4.2 的数据库备份。
- 回滚后，`app-msia`、`app-bol` 仍是默认组，等于全员准入；如果需要收回，按人从组里移除。

### 7.4 应急入口

- `admin` 在保留名单里，切换后仍可用本地密码登录管理控制台；执行第 4 步后先验证这一点。
- Entra 故障时，2822 名普通用户无法登录，只有 40 个保留账号可走本地。这是本方案的可用性代价，必须提前让业务知晓。
- 登录页必须保留用户名/密码表单；不要把整个登录页替换成只显示 Entra 按钮。

---

## 8. 切换后失效的脚本与作业

这些不是「可能有问题」，而是切换后必然失效。按「处理」一栏执行，不要手工跑这些脚本。

| 对象 | 切换后的行为 | 处理 |
|---|---|---|
| `sync_sso_to_keycloak.ps1` | 中央表 `login_name` 仍是短名，Keycloak 用户名已是 UPN，按短名查不到人；一旦手工执行，会把在职者重新建成本地密码账号，形成第二套身份 | 现场没有定期任务，风险仅是手工误执行。脚本已内置拒绝保护：Keycloak 多数用户为邮箱格式时退出 2，不建号、不改表。不要绕过，也不要给它加计划任务 |
| `sync_ad_to_sso.ps1` | 默认串联 `sync_sso_to_keycloak.ps1`；AD 刷新部分正常，Keycloak 段被保护拒绝后整轮以 `exit=2` 结束 | 仍需要每日刷新中央表就加 `-SkipKeycloakSync`；不加也不会建号，但日志会记一条 ERROR |
| `disable_user_now.ps1` | Keycloak 段按 `login_name` 查不到人，只更新中央表；账号仍能登录，直到会话过期 | 不做改造。停号只走微软侧禁用，必要时按 8.1 手工登出 Keycloak 会话。中央表不再作为停号依据 |
| BOL `sync_sso_status` | 按 `login_name` 匹配本地 `username`，UPN 账号匹配不到；状态不传导，本地令牌不清除 | 离职停用改走 Entra 阻止登录 + Keycloak 会话撤销；BOL 账号手工禁用 |
| `assign_groups_from_ledger.ps1` | 按短名查用户，切换后查不到；默认组已覆盖准入 | 停用；不要再跑 |
| `compare_upn_login.ps1` | 比较 UPN 与 `login_name`，切换后两者本就不一致 | 仅切换前用于数据核对；切换后不再作为健康检查 |
| `find_at_username_users.ps1` | 只读盘点，不受影响 | 保留，回滚清理和排查 `@` 账号时使用 |

补充：`CN_AME_SSO_SyncLog` 不会再有 `phase='KC'` 记录（该同步现场未部署，通常早已没有）。若有监控把它当信号，确认不会因无记录误报。

### 8.1 切换后的应急停号流程

已定口径：**只靠微软侧禁用**，不改 `disable_user_now.ps1`。

1. Entra 管理中心 → 用户 → 目标用户 → 阻止登录（Block sign-in）。此后该用户无法再通过 Entra 登录，也拿不到新令牌。
2. 已经签发的 Keycloak 会话在过期前仍然有效，微软侧禁用不会立刻断开它。需要立即断开时：Keycloak 管理控制台 → 用户 → 按邮箱（UPN）搜索 → Sessions → Logout all；必要时把该用户 `Enabled` 关掉。
3. MSIA/BOL 的本地账号不会被联动禁用；要立即停用就在各自后台按 UPN 搜索后手工禁用。
4. 中央表 `status` 不会自动更新；需要留痕时手工置 0，但它不再驱动任何登录判断。

不要用 `disable_user_now.ps1` 代替上述流程：它只会改中央表，账号实际仍可登录，容易造成"已停用"的误判。

---

## 9. 命令速查

| 目的 | 命令 |
|---|---|
| 只读核查 | `.\entra_email_cutover.ps1 -Action Precheck` |
| 配置默认组（预演/执行） | `.\entra_email_cutover.ps1 -Action SetDefaultGroups` / `... -Execute` |
| 清空本地用户（预演/执行） | `.\entra_email_cutover.ps1 -Action Purge` / `... -Execute -ExpectedKeepCount 40` |
| 9 人历史归属（预览/执行/校验/回滚） | `.\Add-SsoUserMapForLegacyOwners.ps1` / `... -Action Apply -AlignLoginName` / `... -Action Verify` / `... -Action Rollback -RollbackLoginName` |
| 重置中央表（可选，预演/执行） | `.\entra_email_cutover.ps1 -Action ResetDb` / `... -Execute` |
| 切换后校验 | `.\entra_email_cutover.ps1 -Action Verify` |
| 确认同步保护生效（清空后） | `C:\sso\scripts\sync_sso_to_keycloak.ps1 -SkipInvite; "exit=$LASTEXITCODE"`，应得 `exit=2` |
| 回滚清理 UPN 账号 | `.\entra_email_cutover.ps1 -Action Purge -Scope Federated -Execute -ExpectedKeepCount 40` |
| 查看默认组 | `C:\keycloak\bin\kcadm.bat get default-groups -r inalfa` |
| 查看 IdP mapper | `C:\keycloak\bin\kcadm.bat get identity-provider/instances/oidc/mappers -r inalfa --fields name,identityProviderMapper,config` |
| 查看 realm 开关 | `C:\keycloak\bin\kcadm.bat get realms/inalfa --fields registrationEmailAsUsername,duplicateEmailsAllowed` |
| 查看用户与组 | `C:\keycloak\bin\kcadm.bat get users -r inalfa -q username="<UPN>" -q exact=true --fields id,username,email,enabled`；再 `get users/<id>/groups -r inalfa --fields name,path` |

---

## 附录 A：现场核实清单（开工前必须全部回填）

**用法**：逐行执行「核查命令」，把实测值写进「回填」栏。**任一「阻断项」未回填或判据不成立，不得进入第 4 步清空用户。**

| # | 事项 | 核查命令 / 位置 | 判据 | 阻断 | 回填 |
|---|---|---|---|---|---|
| 1 | 是否存在调用 `sync_sso_to_keycloak.ps1` 的定期任务 | `Get-ScheduledTask \| Where-Object { $_.TaskName -like '*SSO*' -or $_.TaskName -like '*Import*' } \| Select TaskName,State` | 查出的任务动作里不含该脚本；若含，先按 1.3 停用 | 是 | |
| 2 | `kcadmin` 在哪个 realm | 分别用 `master`、`inalfa` 取一次 token：`kcadm.bat config credentials --server https://iame.ap.inalfa.local:8443 --realm <r> --user kcadmin` | 返回成功的那个 realm 就是 `-AdminRealm` 的值 | 是 | |
| 3 | MSIA/BOL 正式入口（scheme + host + port + 路径） | `Get-WebBinding -Name 'MSIA*'`；`Get-WebBinding -Name 'BOL*'`（IIS 站点名以现场为准） | 与 Keycloak 对应 client 的 `Valid Redirect URIs` 逐字符一致（含尾斜杠） | 是 | |
| 4 | `Email as username` 当前状态 | `kcadm.bat get realms/inalfa --fields registrationEmailAsUsername` | 记录 true/false。为 true 时新建用户取 email、忽略用户名模板，需在 1.2 的口径下确认 | 是 | |
| 5 | 四组撞车人员的 Entra UPN 是否共用 | Entra 管理中心按人查 `userPrincipalName`，或让 IT 导出清单 | 每组只保留一个在职 UPN；共用同一邮箱的用户视为同一身份，须书面确认 | 是 | |
| 6 | Capacity 是否在本次范围 | 与业务确认；若在，查 `app-ics` 组是否存在 | 在范围内则必须把 `app-ics` 设为默认组，否则登录后 403 | 否 | |
| 7 | BOL `username` 列实际长度 | `SELECT CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='CN_IE_BOL_Employee' AND COLUMN_NAME='username'` | ≥ 最长 UPN 长度；小于则需先扩列 | 是 | |
| 8 | Entra UPN 长度分布 | 见下方统计命令 | `>50` 人数为 0、`>100` 人数为 0 | 是 | |
| 9 | `CN_AME_SSO_UserMap` 基线 | `SELECT system_code, COUNT(*) FROM dbo.CN_AME_SSO_UserMap GROUP BY system_code;` | 记录基线（现有基线：2 行 admin 映射）。执行 5.1 后应为基线 + 9 | 是 | |
| 10 | BOL 历史数据归属量 | 需 `CMC` 库只读权限：`SELECT COUNT(*) FROM CMC.dbo.CN_IE_BOL_Employee WHERE username NOT LIKE '%@%'` 及引用该用户名的业务表 | 统计挂在旧短名下的业务记录数；无权限时记录「未统计」并书面告知业务该风险 | 否 | |

Entra UPN 长度统计命令（列名按实际导出调整）：

```powershell
Import-Csv .\entra_users.csv |
  Where-Object { $_.userPrincipalName.Length -gt 50 } |
  Select-Object userPrincipalName, @{N='Length';E={$_.userPrincipalName.Length}} |
  Sort-Object Length -Descending

# 同时确认 >100 也为 0（MSIA varchar(100)）
(Import-Csv .\entra_users.csv | Where-Object { $_.userPrincipalName.Length -gt 100 }).Count
```

---

## 附录 B：变更记录建议字段

| 字段 | 内容 |
|---|---|
| 切换窗口 | 年-月-日 时:分 至 时:分 |
| Precheck 结论 | 通过/告警/阻断数，操作人 |
| 保留名单 | `DbCount`，四组撞车结论 |
| 长度预检 | >50 人数、>100 人数，处理方式 |
| 已停用作业 | 确认无定期任务；清空后 `sync_sso_to_keycloak.ps1` 保护实测 `exit=2` |
| 9 人历史归属 | `system_code='msia'` 行数（0→9）、9 人 `login_name` 是否等于 UPN、`-Action Verify` 结论 |
| 首登验证 | 测试 UPN（脱敏）、MSIA 角色、BOL 角色、UserMap 行数 |
| 回滚点 | 数据库备份表名、realm 导出目录 |
