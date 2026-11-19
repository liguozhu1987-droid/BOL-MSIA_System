# AD 联合认证评估：从"同步密码"改为"认证委托"

> 评估对象：Keycloak `inalfa` realm（25.0.6，`https://iame.ap.inalfa.local:8443`）接入 `ap.inalfa.local` 域。
> 相关资产：`CN_AME`（`IRSCNYTFINEREPORT.ap.inalfa.local`）、脚本 `C:\sso\scripts\`、客户端 `msia-prod` / `bol-prod` / `ics-prod`。
> 本文所有结论按当前实现写，不写理想态。
> 另一条互斥路线（以 Entra ID 为认证源）见 [entra-id-federation-assessment.md](entra-id-federation-assessment.md)，两者不要同时上。

## 0. 结论

1. **"把密码同步到 Keycloak"做不到**。AD 不对外提供口令散列，也没有任何 API 能读出域账号密码。能落地的只有一条：**Keycloak 不再校验本地密码，把校验动作交给 AD**（LDAP 直验），或进一步让浏览器直接出示域票证（Kerberos/SPNEGO）。效果就是用户要的："电脑密码改了，各系统跟着变，不需要第二套密码。"
2. **三个应用一行代码都不用改**。MSIA（`msia-prod`）、BOL（`bol-prod`）、Capacity（`ics-prod`）已经是标准 OIDC 客户端，认证方式换在哪一侧它们看不见。FineReport 例外——它自己直连 AD，与 Keycloak 无关，本次不动。
3. **本地用户退场方式已定：清空重建**。现有 2798 个本地用户是批量建的、基本没人用过（只有 `ligu` 设过密码），直接按 AD 账号重建，不做保留、不做改名共存。
4. **现在做最便宜**：本地密码体系几乎零沉没成本；等全员完成首登设密再迁移，就是"几千人重设密码 + 重挂权限"，代价翻几倍。

## 1. 前提纠正（先说清楚，否则方案会跑偏）

| 常见误解 | 事实 |
|---|---|
| 定时把 AD 密码同步到 Keycloak | AD 不提供口令散列。`NTDS.dit` 受启动密钥保护，域内也没有"读密码"接口。任何声称同步密码的方案，实际都是**代理认证**或**改密码**，不是同步 |
| 让 Keycloak 回写 AD 密码 | 技术上可以（LDAP `WRITABLE` 模式 + 有写权限的绑定账号），但那意味着 Keycloak 成了密码修改入口，AD 侧密码策略、审计、口令历史全部绕过一半，且绑定账号拿到的是域内写权限 |
| AD 改了密码，Keycloak 要"收到通知" | 不需要。认证委托之后，Keycloak 每次登录都拿用户输入的密码去 AD 校验，AD 里是什么就是什么，不存在"同步延迟" |

一句话：**认证归 AD，授权留各应用**。这正是 FineReport 现在的模式。

## 2. 机制对比

| 维度 | A. 现状：Keycloak 本地密码 | B. LDAP 直验（simple bind + LDAPS） | C. Kerberos/SPNEGO |
|---|---|---|---|
| 用户操作 | 首登设一套新密码，之后两套密码并存 | 输入**域账号密码**，与开机同一个 | 域内已登录的电脑上**完全不输密码**，点进即入 |
| 域密码改了 | 不会跟 | 立即跟（下次登录就是新密码） | 立即跟 |
| Keycloak 改动 | — | 加一个 User Federation 组件 | 在 B 之上再开 Kerberos，并给 Keycloak 主机签发 keytab |
| 应用改动 | — | **无** | **无** |
| 网络依赖 | 无（只依赖 Keycloak 自身） | 每次登录都要能到 DC 的 636 | 登录时到 DC，之后靠票据 |
| 域不可用时 | 照常登录 | **全员登不上**（`admin` 本地账号除外） | 已登录的还能用票据撑一段，新登录失败 |
| 主要代价 | 两套密码、离职要等 06:00 同步 | 引入 DC 单点；Keycloak 侧失去"改资料/停用"的写能力（见 4.5） | 需要 IT 出 keytab、DNS/时间同步严格、浏览器要配 SPNEGO 白名单、共享电脑"自动登录成上一个人"的风险被放大 |
| 实施量 | 0 | 小（纯配置 + 用户清空重建） | 中（含 IT 侧 AD 委派与浏览器策略） |

**推荐 B 作为本期目标**，理由：达成用户要的效果（一套密码），不动应用，不依赖浏览器策略，失败模式简单可解释。
**C 留作第二阶段**，触发条件是：B 稳定运行、用户抱怨"还要输一次密码"、且 IT 愿意签发 keytab 并提供 `HTTP/iame.ap.inalfa.local@AP.INALFA.LOCAL` 的 SPN。C 不改变 B 的任何配置，只是多开一个开关。

### 2.1 为什么 LDAPS 是硬要求

`simple bind` 的密码是**明文**放在 LDAP 报文里的。389 端口上的 bind 等于把每个用户的域密码明文送过网络——抓到包就是全域口令。所以：

- 连接串必须是 `ldaps://<dc>:636`，不允许 `ldap://...:389`；
- 如果要走 389，只能开 StartTLS（`useStartTls=true`），且同样需要信任 AD 的 CA；
- Keycloak 的 JVM 必须信任 AD 的根 CA（`INALFA-IRSPKIROOT01-CA`）与中间 CA（`ap-SRV-APSH-PKI-01-CA-1`），否则握手直接失败，表现为 `LDAP connection failed` / `PKIX path building failed`。

## 3. 对应用的影响（逐个判断）

| 应用 | 现在怎么接 | 要不要改 | 说明 |
|---|---|---|---|
| MSIA | OIDC 授权码 + PKCE，client `msia-prod`，准入组 `app-msia` | **不需要** | 只认 Keycloak 发的 token。用户在哪里验的密码，它不知道也不关心 |
| BOL | OIDC 授权码 + PKCE，client `bol-prod`，准入组 `app-bol` | **不需要** | 同上 |
| Capacity | OIDC，client `ics-prod`，`OIDC_REQUIRE_GROUP=true` / `OIDC_REQUIRED_GROUP=app-ics` | **不需要** | 同上。唯一要注意的是组：迁移时组没了就是 403，不是登录失败 |
| FineReport（帆软） | 自己直连 AD，不经过 Keycloak | **不需要，也不应该动** | 它就是用户说的"已经实现"的样板：自己的 AD 认证 + 自己的权限体系。它是**独立路径**，本次改造与它互不影响；反过来，它的存在也不构成"Keycloak 也必须这么干"的理由 |

FineReport 只有一种情况需要改：将来要把它也纳入统一身份（用 `sso` 单点而不是各自的登录页），那是一次独立改造，需要帆软侧支持 OIDC 并做用户映射，本期不做、也未验证。

## 4. 本地用户退场：确定执行清空重建

### 4.1 为什么必须清空

Keycloak 解析用户名时的顺序是：**本地用户 → 联邦 Provider**。只要本地已存在 `username=ligu`，登录就永远走本地密码校验，LDAP 那边连查都不会查。

不做清空的唯一替代是"保留本地用户另行改名、让 AD 账号占住原名"，那等于**永久维护两套身份的对齐关系**：每次 AD 改名、每次入职离职、每次报警，都要人工确认两边的映射没歪，而收益只是保住一批本来也没人用过的本地密码。不选。

另一个反直觉的点：**联邦用户是首次登录才 lazily 导入的**。不触发全量同步，Keycloak 里就没有这个人，授组脚本会全员报"查无此人"，组也就挂不上。

### 4.2 必须保留的账号（40 个，必须点名，不能靠人工核对）

`admin` 和 39 个共享信箱/服务类账号不是可登录的 AD 真人，联邦过去没有人能校验它们的密码，必须留在本地：

| 账号 | 为什么留本地 |
|---|---|
| `admin`（`source='MANUAL'`，`display_name='系统管理员'`） | AD 里没有这个可登录的真人。它承担应急入口：DC 挂了、Federation 配错、绑定账号被锁时，只剩它能进管理台 |
| 39 个共享信箱/服务类账号 | 一个邮箱多个人用、或根本无人对应，不是可登录的 AD 身份。联邦过去要么查无此人，要么落到某个真实员工头上，变成"多人共用一个实名账号"，审计上不可接受 |

白名单用 SQL 筛出来，不靠人眼：

```sql
-- 保留名单：admin + MANUAL + 共享信箱（同一邮箱对应多个工号）→ 必须正好 40 行
SELECT employee_no, login_name, display_name, email, source, status
FROM dbo.CN_AME_SSO_User
WHERE employee_no = 'admin'
   OR source = 'MANUAL'
   OR email IN (
        SELECT email FROM dbo.CN_AME_SSO_User
        WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> ''
        GROUP BY email
        HAVING COUNT(*) > 1)
ORDER BY employee_no;
```

两道闸门，缺一不可：

1. **行数必须正好 40**。多出来通常是"两个真实员工共用一个公共邮箱"，要单独排除；少于 40 说明筛选条件漏了某一类账号，改条件而不是手工补。
2. 把结果导出成 `C:\sso\tmp\keep_usernames.txt`（`login_name` 列，一行一个）。配好 Federation 后再逐个反查一次，确认它们在 AD 里**没有**对应的可登录账号：

```cmd
C:\keycloak\bin\kcadm.bat get users -r inalfa -q username=<其中的一个> -q exact=true --fields username,federationLink
```

若某个白名单账号带出了 `federationLink`，说明 AD 里确实有同名真人——那就是真人员工，不该留在白名单里，先解决同名冲突再继续。

### 4.3 清空步骤（可照着执行）

**第 1 步：导出。** 注意这份导出**不是还原点**：

```cmd
mkdir C:\sso\kc-export\pre-federation
C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export\pre-federation --realm inalfa --users per_file
```

- 导出的是**账号与属性**，不含可用的密码：即使带出口令字段也是不可逆散列，联邦用户的凭据本来就在 AD、根本不在这份文件里；
- 所以回滚不能靠"导入这份备份把密码找回来"，只能把账号壳重建出来（见 4.6）；
- 导出目录拷一份到另一台机器，别只留在 Keycloak 本机。

**第 2 步：停掉每日同步。** 否则 06:00 一到，删掉的人又被建回来：

```powershell
Disable-ScheduledTask -TaskName 'SSO_AD_Import'
```

**第 3 步：筛出要删的人。** 条件是"**没有 `federationLink`**（即本地用户）**且不在白名单里**"。先只打印、不删：

```powershell
$base='https://iame.ap.inalfa.local:8443'; $realm='inalfa'
$tok=(Invoke-RestMethod -Method Post -Uri "$base/realms/$realm/protocol/openid-connect/token" -Body @{
        grant_type='password'; client_id='admin-cli'; username='admin'; password='<管理员口令>' }).access_token
$h=@{ Authorization = "Bearer $tok" }
$keep = @(Get-Content 'C:\sso\tmp\keep_usernames.txt' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })

$all=@(); $first=0
do {
    $page=@(Invoke-RestMethod -Uri "$base/admin/realms/$realm/users?briefRepresentation=false&first=$first&max=100" -Headers $h)
    $all += $page; $first += 100
} while ($page.Count -eq 100)

# 只删"本地用户"（federationLink 为空）且不在白名单
$del = @($all | Where-Object { -not $_.federationLink -and ($keep -notcontains $_.username) })
"总数 $($all.Count)，将删除 $($del.Count)，保留 $($all.Count - $del.Count)"
$del | Select-Object username -First 20 | Format-Table
```

**第 4 步：确认数字后执行删除。** 保留数应等于 40（白名单）+ 已联邦用户数：

```powershell
$del | ForEach-Object { Invoke-RestMethod -Method Delete -Uri "$base/admin/realms/$realm/users/$($_.id)" -Headers $h }
```

**第 5 步：确认没有残留会话。** 用户删了，会话/离线会话可能还挂在内存里：

```powershell
Invoke-RestMethod -Method Post -Uri "$base/admin/realms/$realm/logout-all" -Headers $h
# 应返回空数组；有输出说明还有会话存活
Invoke-RestMethod -Uri "$base/admin/realms/$realm/sessions?max=100" -Headers $h
Invoke-RestMethod -Uri "$base/admin/realms/$realm/offline-sessions?max=100" -Headers $h
```

**第 6 步：全量同步。** 顺序不能提前（见 4.4）：

```cmd
C:\keycloak\bin\kcadm.bat create user-storage/<组件id>/sync?action=triggerFullSync -r inalfa
```

`<组件id>` 用 `kcadm get components -r inalfa -q type=org.keycloak.storage.UserStorageProvider --fields id,name` 取。

### 4.4 组关系重挂：顺序不能反

- Keycloak 的组成员关系存在**本地**（`USER_GROUP_MEMBERSHIP`），不来自 AD。删用户 = 组关系一起没。
- 顺序：**先配 Federation → 先全量同步把用户导入 Keycloak → 再加组**。反过来跑，授组脚本按 username 查不到人，全部落到"查无此人"，且不会自动补。
- 12 人台账用原用法重跑即可，不需要任何新参数：

```powershell
C:\sso\scripts\assign_groups_from_ledger.ps1
# 先加 -DryRun 确认"将添加 N / 已存在 M / 查无此人 0"
```

- 不要用 `-AllUsers` 重挂准入组——那等于取消访问控制。
- AD 侧如果已有安全组（如 `GG-MSIA-Users`），更省事的做法是在 Federation 的 Mapper 里把 AD 组成员映射成 Keycloak 组。前提是 AD 组划分与 `app-msia` / `app-bol` / `app-ics` 成员完全一致；不一致时不要映射，会制造第二套真相。

### 4.5 中央表侧必须一起重置

`kc_user_id` 指向的是刚被删掉的那批用户 id，`pwd_set` 记录的是"这个人本地设过密"。两个都必须清：

```sql
-- 只清非本地保留账号；admin 与 39 个共享账号不动
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = NULL,
    pwd_set    = 0
WHERE source <> 'MANUAL'
  AND employee_no <> 'admin';
```

为什么必须重置：

- `sync_sso_to_keycloak.ps1` 第一步是**按 `kc_user_id` 查人**。不清的话它拿着一个已删除的 id 去 `GET /users/{id}`，得到 404，只能靠后面的"按 username 再查一次"兜回来——能恢复，但每人都要多吃一次 404，日志里全是噪声，且一旦某个 username 也查不到就直接记为失败。
- `pwd_set=1` 会让"复职"分支认为这个人已经有密码，从而不补发设密邀请；联邦之后这条本来就该归 AD，留着旧值只会误导判断。

重置完跑一次同步，让脚本按 username 重新找回联邦用户并回写 id：

```powershell
C:\sso\scripts\sync_sso_to_keycloak.ps1 -SkipInvite
```

### 4.6 回滚：关掉 Federation 不是回滚

删掉本地用户之后，"关掉/删掉 Federation"**不能把系统恢复原状**——人已经不在 Keycloak 里了，关掉联邦只会让除 `admin` 与 39 个共享账号之外的所有人都登不上。删掉组件更彻底：联邦用户的映射记录一并丢弃。

真正的回滚只有一条路径：**从空的用户状态重新批量建号**，而这正是 `sync_sso_to_keycloak.ps1` 的本职：

```powershell
# 1) 停用/删除 Federation 组件，回到纯本地认证
# 2) 恢复每日同步任务
Enable-ScheduledTask -TaskName 'SSO_AD_Import'
# 3) 全量建号（keeps 白名单不动，其余按中央表重建本地账号并发设密邀请）
C:\sso\scripts\sync_sso_to_keycloak.ps1
# 4) 重挂组
C:\sso\scripts\assign_groups_from_ledger.ps1
```

所以回滚是**可行但昂贵**的：2798 人重新建号、重新设密（或等邀请邮件）、重挂组，耗时与正向切换同量级，不是"一键退回"。真正的底账是 `CN_AME_SSO_User` 与 `CN_AME_SSO_PermLedger` 两张表——它们不在 Keycloak 里，只要这两张表完好，账号和权限就都能重建；这也是为什么 4.3 第 1 步的导出只是留痕，而**数据库备份**才是真正的兜底。

## 5. 落地步骤

### 5.1 顺序总览

| # | 动作 | 判据 |
|---|---|---|
| 1 | 备份 `CN_AME`（含五张 SSO 表）+ 导出 realm | 备份可读、导出目录异地留一份 |
| 2 | 建 Federation，Test connection / Test authentication | 两者都通过 |
| 3 | 抽样验证 username 映射 | `username` 与域登录名逐字一致 |
| 4 | 停 `SSO_AD_Import` | 任务状态 Disabled |
| 5 | 删本地用户（排除白名单 40 个） | 保留数 = 40 |
| 6 | 清会话 | 无残留会话/离线会话 |
| 7 | 全量同步 | 用户数 ≈ AD 在职人数，`federationLink` 非空 |
| 8 | 重置 `kc_user_id` / `pwd_set`，跑同步脚本 | 回写数 ≈ 联邦用户数 |
| 9 | 重挂组 | `assign_groups_from_ledger.ps1` 显示"查无此人 0" |
| 10 | 三个应用各登一次 + 恢复任务 | 登录成功、组内 403 消失 |

### 5.2 Federation 参数（逐个定死）

| 参数 | 值 | 为什么 |
|---|---|---|
| Vendor | `ad` | 决定属性映射与 `userAccountControl` 解析 |
| Connection URL | `ldaps://dc01.ap.inalfa.local:636`（多个 DC 用空格分隔写在同一串里，做故障切换） | 必须是 636；DC 名以 IT 提供为准 |
| Enable StartTLS | 关 | 已用 LDAPS |
| Trust email | 开 | 邮箱来自 AD，不再要求验证 |
| Bind type | `simple` | 配合 LDAPS |
| Bind DN | `CN=svc-keycloak-ldap,OU=Service Accounts,DC=ap,DC=inalfa,DC=local` | 专用只读账号，不复用个人域账号 |
| Bind credential | 只填在 Keycloak 组件配置里 | 不写进任何文档、不写进脚本 |
| Edit mode | **`READ_ONLY`** | AD 为准，Keycloak 不回写；见 4.5 的连带影响 |
| Users DN | `OU=Users,DC=ap,DC=inalfa,DC=local` | 范围越小同步越快；以 IT 给的为准 |
| Username LDAP attribute | **`sAMAccountName`** | 这是用户真正用来登录的域账号名。**不能用 `cn`/`displayName`/`mail`**，否则 username 与域登录名对不上，用户拿工号登不进 |
| RDN LDAP attribute | `cn` | — |
| UUID LDAP attribute | `objectGUID` | AD 的稳定唯一 id；用错会导致每次同步重复建号 |
| User object classes | `person, organizationalPerson, user` | AD 标准三类 |
| Import users | **开** | 必须开，否则无法预分配组（见 4.4） |
| Sync registrations | 关 | 不允许自助注册写回 AD |
| Edit mode 下的密码策略校验 | 关（`validatePasswordPolicy=false`） | 密码由 AD 校验，Keycloak 的策略只管本地用户 |
| Cache policy | `DEFAULT` | 默认缓存能挡住大部分重复查询 |
| Connection pooling | 开 | 减少每次登录的 bind 开销 |
| Batch size for sync | `1000` | 2798 人一次全量同步约 1–3 分钟 |
| Full sync period | `-1`（仅手动/脚本触发） | 不做定时全量，避免和 06:00 任务打架 |
| Changed users sync period | `86400` | 每天增量一次；或直接关掉，靠登录时实时查 |
| Truststore SPI | `ldapsOnly` | 只让 LDAPS 用自定义信任库，不影响 Keycloak 自身对外 HTTPS |

信任库（AD 的 CA 链）用 Keycloak 自带的文件信任库，升级 JDK 不会丢：

```cmd
C:\keycloak\bin\kc.bat build --spi-truststore-file-file=conf/truststores/ad-ca.p12 --spi-truststore-file-password=<口令> --spi-truststore-file-type=PKCS12
```

把 `INALFA-IRSPKIROOT01-CA` 与 `ap-SRV-APSH-PKI-01-CA-1` 两张证书导入 `C:\keycloak\conf\truststores\ad-ca.p12` 后再 `build`，然后重启 Keycloak 服务。

组件也可以用 CLI 建，便于留痕：

```cmd
C:\keycloak\bin\kcadm.bat config credentials --server https://iame.ap.inalfa.local:8443 --realm master --user admin
C:\keycloak\bin\kcadm.bat create components -r inalfa ^
  -s name=ad-ap -s providerId=ldap -s providerType=org.keycloak.storage.UserStorageProvider -s parentId=inalfa ^
  -s config.enabled=true -s config.vendor=ad -s config.editMode=READ_ONLY ^
  -s config.connectionUrl="ldaps://dc01.ap.inalfa.local:636" ^
  -s config.usersDn="OU=Users,DC=ap,DC=inalfa,DC=local" ^
  -s config.authType=simple ^
  -s config.bindDn="CN=svc-keycloak-ldap,OU=Service Accounts,DC=ap,DC=inalfa,DC=local" ^
  -s config.bindCredential="<绑定账号口令>" ^
  -s config.usernameLDAPAttribute=sAMAccountName ^
  -s config.rdnLDAPAttribute=cn ^
  -s config.uuidLDAPAttribute=objectGUID ^
  -s config.userObjectClasses="person, organizationalPerson, user" ^
  -s config.importEnabled=true -s config.syncRegistrations=false ^
  -s config.validatePasswordPolicy=false -s config.useTruststoreSpi=ldapsOnly ^
  -s config.pagination=true -s config.batchSizeForSync=1000
```

### 5.3 验证（迁移前，此时不动任何用户）

管理台 → User federation → `ad-ap`：

1. **Test connection** 通过（证明网络、证书、绑定账号三者都对）；
2. **Test authentication** 用 1 个测试域账号通过（证明 `sAMAccountName` 映射对）；
3. 搜一个用户，检查 `federationLink` 非空、`username` 与域登录名逐字一致：

```cmd
C:\keycloak\bin\kcadm.bat get users -r inalfa -q username=ligu -q exact=true --fields id,username,email,federationLink
```

4. 数量对得上：`GET /admin/realms/inalfa/users/count` 应接近 AD 在职人数，且与 `SELECT COUNT(*) FROM CN_AME.dbo.CN_AME_SSO_User WHERE status = 1` 的差值 ≤ 共享账号数。

### 5.4 切换后对同步脚本的影响（必须一起改）

`READ_ONLY` 之后，用户的姓名、邮箱、启用状态都由 AD 说了算，Keycloak 本地写不进去。`sync_sso_to_keycloak.ps1` 的写分支会这样：

| 分支 | 联邦后的结果 |
|---|---|
| 建号 `POST /users` | 不会触发（全量同步已经把人导进来了） |
| 改资料 `PUT /users/{id}` | 有差异时被拒（read-only），H18 记 WARN 继续，但每天刷一批 WARN |
| 停用 `PUT enabled=false` | 被拒；离职改由 AD 禁用账号实现（联邦会读到 `userAccountControl`） |
| 复职 | 同上，自动跟随 AD |
| 回写 `kc_user_id` / `pwd_set` | 仍可写（这两列在中央表，不在 Keycloak） |

切换后脚本降级为**只读校验模式**：只做"补 `kc_user_id`"和"写 `SyncLog`"，不再发属性写请求。不做这件事不会坏，但每天几百条 WARN 会把真正的异常淹掉。`editMode` 不要改用 `UNSYNCED`——那样本地可改但 AD 改名/改邮箱不跟随，与"一套身份"的目标相悖。

## 6. 与 IT/AD 沟通需要确认的清单

| # | 要什么 | 为什么要 | 卡住什么 |
|---|---|---|---|
| 1 | LDAPS 端点：各 DC 的 636（`ldaps://dc01...`、`ldaps://dc02...`），或 389 + StartTLS | simple bind 明文送密码，不能走裸 389 | 不确认就没法建 Federation |
| 2 | AD 根 CA `INALFA-IRSPKIROOT01-CA` 与中间 CA `ap-SRV-APSH-PKI-01-CA-1` 的证书文件（`.cer`/PEM） | Keycloak 的 JVM 要信任这条链，否则 LDAPS 握手失败 | 同上 |
| 3 | 专用只读绑定账号 `svc-keycloak-ldap`（口令 + 有效期 + 谁负责轮换）与它所在的 OU 授权路径 | 不复用个人账号；只读即可，不给写权限 | 绑定失败 = 全员登不上 |
| 4 | 登录名到底是哪个属性：`sAMAccountName` / `userPrincipalName` / 员工号 | 决定 `usernameLDAPAttribute`；选错用户拿工号登不进，且会出现同名二次建号 | 直接决定迁移能否成功 |
| 5 | 现网 `CN_AME_SSO_User.login_name` 与 AD `sAMAccountName` 对不上的清单（大小写、带域后缀、离职遗留） | 联邦后 Keycloak 按 username 找 AD，对不上的那批人会全部登录失败 | 必须在切换前跑一次比对，不能等切完再发现 |
| 6 | 域密码策略与锁账号阈值（错误次数、锁定分钟、观察窗口） | 用户输错密码时由 AD 计数。Keycloak 侧没有额外防线，需要知道阈值来评估"用户被锁"的概率与话术 | 决定是否需要保留本地应急账号与解锁流程 |
| 7 | 防火墙方向：Keycloak 主机 → DC 的 636（TCP，双向放行返回） | LDAPS 是长连接 + 登录时实时校验 | 不放开就是 `LDAP connection failed` |
| 8 | 是否授权 Keycloak 回写 AD 密码（即是否给 `WRITABLE` + 写权限） | 决定 Keycloak 的"忘记密码"还能不能用。不给写权限就必须关掉该入口，引导用户走 AD 自助重置 | 决定用户侧支持流程 |
| 9 | 后续是否允许上 Kerberos：能否为 `HTTP/iame.ap.inalfa.local@AP.INALFA.LOCAL` 签发 keytab、是否已有对应 SPN | 第二阶段静默登录的前提，缺 keytab 就做不了 | 只影响阶段二 |
| 10 | 域控与 Keycloak 主机的时间同步源（同一 NTP） | Kerberos 要求时钟偏差 ≤5 分钟；即使只做 LDAPS，时间漂移也会让证书校验与日志时间线失真 | 阶段二硬要求 |
| 11 | 是否同意新建 `OU=Keycloak` 之类的服务账号容器、以及 AD 侧变更的审批周期 | 影响排期；服务账号通常要走安全审批 | 影响工期 |

## 7. 风险与工期

| 风险 | 影响 | 判断点 |
|---|---|---|
| DC / 网络不可用 | 全员无法登录三个应用（`admin` 除外）。**这是引入的新的单点** | 接受还是接受不了，要用户拍板。缓解手段只有"多 DC 写在连接串里 + 保留 `admin` 本地应急"，无法消除 |
| AD 账号被锁 | 用户登录三个系统全失败，且 Keycloak 侧无法解锁 | 依赖锁定策略阈值（清单第 6 条） |
| 清空时误删白名单 | `admin` 或共享信箱账号消失，应急入口没了 | 4.2 的两道闸门（正好 40 行 + 反查 `federationLink`）+ 4.3 先打印后删除 |
| `login_name` 与 `sAMAccountName` 不一致 | 一批人切完即登不上 | 切换前必须先跑比对（清单第 5 条），这步不能省 |
| 组没重挂 | 登录成功但 403（`app-ics` 最常见） | 按 4.4 的顺序，同步完再跑授组脚本 |
| 回滚成本被低估 | 误以为"关掉 Federation 就回来了"，实际要全员重建 | 4.6 已写明；切换前确认 `CN_AME` 备份可用 |

粗略工期（不含 IT 审批等待）：

| 阶段 | 工作量 |
|---|---|
| Federation 配置 + 证书信任库 + 联调（测试账号） | 0.5–1 天 |
| `login_name` ↔ `sAMAccountName` 全量比对与差异处理 | 0.5–1 天 |
| 白名单筛选与核对（40 行闸门 + 反查） | 0.5 天 |
| 清空重建脚本化（导出、批量删、会话清理、SQL 重置、验证） | 0.5–1 天 |
| 同步脚本降级为只读模式（5.4） | 0.5 天 |
| 切换窗口（备份、删用户、全量同步、回写、重挂组、验证） | 3–4 小时 |
| 观察期（每天看 SyncLog 与登录失败日志） | 1 周（不占人力，占窗口） |

相比"保留本地用户"的做法，清空重建多出约 **1.5–2 天**（白名单核对 + 删号脚本 + 重建验证），换来的是不留双轨、不需要长期维护两套身份对齐。

IT 侧的前置（LDAPS、证书、只读账号、防火墙）通常 2–5 个工作日，是实际排期的主要变量。

## 8. 需要拍板的决策点

1. **是否接受"DC 不可用 = 全员登不上"这个单点**（唯一兜底是本地 `admin`）。
2. **白名单的最终名单**：4.2 的 SQL 筛出正好 40 行后，需要有人签字确认这 40 个 `employee_no`。
3. **`editMode` 就按 `READ_ONLY`**：确认接受"同步脚本降级为只读、离职由 AD 禁用驱动"这个连带改动（如不接受，则要另行设计，成本更高）。
4. **"忘记密码"入口的去留**：关掉并引导 AD 自助重置，还是给 Keycloak 写权限（安全面变大）。
5. **本期是否同时上 Kerberos 静默登录**（需要 IT 出 keytab，工期 +2–3 天）。
6. **切换窗口的时点**：3–4 小时内三个应用不可登录，需避开月末/排产高峰。
7. **是否现在就做**：现在是沉没成本最低的时点（只有 `ligu` 一个本地密码），越晚迁移代价越高。

---


## 9. 复评（2026-11-14）：Entra broker 卡在 50146 时的取舍

> 本节回答：**放弃 Entra 代理，改为 Keycloak 直接用 AD 账号 + AD 密码认证**，要改什么、存量怎么办、是不是最优、怎么进退。
> 只写与 §2–§5 不同或需要补强的部分；Federation 参数见 §5.2，清空重建见 §4，不重复。

### 9.1 已核实 vs 待核实

| 结论 | 依据 | 性质 |
|---|---|---|
| 现有 realm 没有 LDAP / User Federation | `docs/方案A落地清单.md` M01 判据为 `components` 返回 `[]` | 待现场复核（C1） |
| 应用只消费 4 个 claim：`preferred_username` / `groups` / `email` / `name` | `MSIA Report/backend/app/services/sso_identity.py`、`BOL管理系统/backend/apps/users/oidc_views.py` | 已核实 |
| 应用用 `preferred_username` 匹配中央表 `login_name`，再关联 UserMap | 两处 `_USERMAP_SQL` | 已核实 |
| 本地用户优先于联邦用户，同名不走 AD | §4.1 | 已核实（Keycloak 查找顺序） |
| `sync_ad_to_sso.ps1` 每天 06:00 串联 `sync_sso_to_keycloak.ps1` 建号 | `sync_ad_to_sso.ps1` 第 591 行 | 已核实 |
| 仓库内 `keycloak/keycloak.conf` 已过期（`hostname=sso.…`、PEM 双文件） | 与现场 `iame…` + PKCS12 不一致 | 已核实；**配置以服务器为准** |

待现场确认：DC 的 LDAPS、AD CA、只读服务账号、Keycloak 用户总数、`kc_user_id` / `pwd_set` 分布、AD 锁定阈值。命令见 9.7。

### 9.2 要改什么

#### Keycloak 侧

| 项 | 动作 |
|---|---|
| User Federation | 新建 LDAP（`providerId=ldap`），参数逐项按 §5.2；**`Import users=ON`、`Edit mode=READ_ONLY`、`usernameLDAPAttribute=sAMAccountName`** |
| 认证流程 | **不改 browser flow**。默认 `Username Password Form` 就会把密码交给 AD bind；Kerberos/SPNEGO 不是本期必需 |
| 属性映射 | 内置 `email` / `firstName` / `lastName` mapper 走 LDAP 属性；`uuidLDAPAttribute=objectGUID` |
| 组映射 | **不映射 AD 组**。`app-msia` / `app-bol` / `app-ics` 继续是 Keycloak 本地组，真相仍在 Keycloak（§4.4） |
| 令牌 claim | `preferred_username` 自动等于 Keycloak username（= `sAMAccountName`）；`groups` 仍由 client scope 的 Group Membership mapper 产生。**三个 client 一行不改** |
| 自助能力 | 关 `Forgot password`、关 `Update Profile` required action、`Sync registrations=OFF`；READ_ONLY 下这些写操作本来就会报错，留着只会给用户报错页 |
| 防爆破 | Keycloak 侧失败阈值要**低于** AD 锁定阈值（建议 3 次），否则用户在应用里试错会把域账号锁死，连电脑都登不上（9.5 R2） |
| 信任库 | AD 根 CA + 中间 CA 导入 `conf/truststores/ad-ca.p12`，`useTruststoreSpi=ldapsOnly`（§5.2） |

#### 应用侧

**0 改动。** 三个系统只验 Keycloak 的 `iss` / `aud`，只读 `preferred_username` / `groups` / `email` / `name`。认证发生在 Keycloak 之前，应用看不到；Capacity 的 `OIDC_REQUIRE_GROUP=app-ics` 也不变。

> 唯一的"应用侧"动作是**比对**：跑一次 `login_name` ↔ `sAMAccountName` 差异（C9）。差异不处理就会落到"能登录但落到错误身份 / 自动建档"（§6 第 5 条）。

#### 数据侧

| 对象 | 动作 |
|---|---|
| `CN_AME_SSO_User.kc_user_id` | 删用户后按 §4.5 置 NULL，再跑 `sync_sso_to_keycloak.ps1` 回写联邦用户 id |
| `CN_AME_SSO_User.pwd_set` | 语义作废（密码在 AD）。置 0，脚本不再用它判断"是否已设密" |
| `CN_AME_SSO_User.login_name` | **不动**。这是本路线相对 Entra 的最大优势：`preferred_username` 仍是 `login_name` |
| `CN_AME_SSO_UserMap` | 不动（2 条历史映射继续生效） |
| `CN_AME_SSO_PermLedger` | 不动；组重挂仍按台账 |
| `sync_ad_to_sso.ps1` | 保留（名单→中央表），**但必须断开对 KC 的建号串联**（9.2.1） |
| `sync_sso_to_keycloak.ps1` | 降级为只读校验（§5.4）：只补 `kc_user_id`、写 SyncLog，不发建号/改资料/停用请求 |
| `disable_user_now.ps1` | **必须改**：READ_ONLY 下 `PUT enabled=false` 会被拒，应急停号改为"AD 禁用 + Keycloak 按用户登出" |

##### 9.2.1 新入职会生成"影子本地账号"（必须处理的坑）

`sync_ad_to_sso.ps1` 末尾会串联 `sync_sso_to_keycloak.ps1` 建号。联邦之后：

1. 新人在 AD 已存在，但还没被全量/增量同步导入 Keycloak；
2. 06:00 脚本按中央表 `POST /users` 建了一个**本地** Keycloak 账号；
3. 本地用户优先于联邦用户 → 这个人以后永远走本地密码，AD 改密不跟随，且 `pwd_set=0` 没人给他设过密码 → **直接登不上**。

处置：二选一，切换前定死。
- 给 `sync_ad_to_sso.ps1` 加开关跳过 KC 串联，或在计划任务里把 `-KeycloakSyncScript` 指向只补 id 的包装脚本；
- 或让 `sync_sso_to_keycloak.ps1` 检测到"该 username 在 AD 存在"时只查询、不建号。

不要依赖 `-SkipInvite`：它只关邮件，照样建号。

#### AD 侧

| 项 | 要求 |
|---|---|
| 端口 | **636 LDAPS**（或 389 + StartTLS）；禁止裸 389（§2.1） |
| 服务账号 | 专用只读账号，只需 `Users DN` 的读/搜索权限；**不需要** `Replicating Directory Changes`（Keycloak 用分页搜索，不用 DirSync） |
| 证书 | AD 根 CA + 中间 CA 的 `.cer` / PEM，导入 Keycloak 信任库 |
| Kerberos | **不需要**。用户名 + 密码走 simple bind；keytab / SPN 只有做静默 SSO 才要（§2 的 C） |
| 防火墙 | Keycloak 主机 → 各 DC 636 |
| 搜索范围 | `Users DN` 尽量收窄；过滤器排除计算机与服务账号，避免 `sAMAccountName` 撞进 40 个保留账号 |
| 锁定策略 | 错误次数 / 观察窗口 / 锁定时长必须拿到；这是 9.5 R2 的输入 |

### 9.3 对存量账号的影响

| 对象 | 现状（文档口径） | 切换后 |
|---|---|---|
| Keycloak 本地用户 | ≈2822（在职）/ 2798（旧统计），`pwd_set=1` 仅 `ligu` | 除 40 个白名单外**全部删除**；组关系一并消失，按台账重挂 |
| `kc_user_id` | 全空 | 先置 NULL，全量同步后由脚本回写为联邦用户 id |
| `pwd_set` | 绝大多数 0 | 置 0 并作废；不再有"设密邀请"这件事 |
| `login_name` 匹配链 | 应用按它匹配 | **不变**（关键优势） |
| MSIA 本地账号 | 4290，4289 有 `HrSyncedAt` | **不动**。历史 Issue / 责任人归属保留（9 名历史责任人 + UserMap 也不用改） |
| BOL `Employee` | 本地账号 | **不动** |
| Keycloak 会话 | 现存会话 | 删用户前 `logout-all`；切换窗口内用户需重新登录 |
| `ligu` 的本地密码 | 已设 | 失效；改用域密码 |
| 审计口径 | Keycloak 事件 | Keycloak 仍记 `LOGIN`，但"密码是否正确"由 AD 判定；AD 侧 4768/4771 才是权威 |

### 9.4 与另两条路线对比：是不是最优

| 维度 | A. AD 直连（本方案） | B1. Entra broker（当前在推） | C. 本地建号（现状） |
|---|---|---|---|
| 用户输入 | 域账号短名 + 域密码 | Entra 页面（域内设备可能免密） | Keycloak 密码（第二套） |
| Keycloak `preferred_username` | `ligu`（= `login_name`） | UPN，需靠 email 绑定回 `ligu` | `ligu` |
| 应用改动 | 0 | 0 | 0 |
| 数据迁移 | 只清 Keycloak 本地用户 | 需建立 Entra ↔ 账号绑定（R3 主方案） | 无 |
| 网络依赖 | DC 636 | `login.microsoftonline.com` + Entra | 无 |
| MFA / 条件访问 | 只能加 Keycloak OTP，无 CA | **有**（需 P1） | 无 |
| 新增单点 | DC | Entra + 云可达性 + 凭据到期 | 无 |
| 回滚 | **贵**（重建 2822 账号） | **便宜**（停 IdP） | — |
| 当前状态 | 未配置，IT 前置 2–5 天 | 卡 `AADSTS50146` | 可用 |
| 许可成本 | 0 | P1（若要 CA） | 0 |

**结论（分两种目标回答）：**

1. **如果目标就是"用户拿现有域账号 + 域密码登三个系统"**：A 是当前最优。它是唯一不依赖云、不改应用、不改 `login_name` 口径、不动业务历史数据的路径；B1 即使修好 50146，仍要先解决 UPN ↔ 账号绑定，且多一层云依赖。**A 可以立刻做，做完之后 50146 与本次目标无关。**
2. **如果目标包含 MFA / 条件访问 / 云侧登录审计**：A 不是最优。它给不了 CA，只能叠加 Keycloak OTP；B1 才是。`AADSTS50146` 是 Entra 侧签名密钥策略问题（`preferredTokenSigningKeyThumbprint` 或应用专属签名密钥），属于**可修的配置**，不是路线级否决。

**因此不建议把 A 与 B1 当"二选一"长期对立**，但也不要在同一窗口同时开两个入口：

- 近期：A 作为唯一默认入口，B1 的 IdP 保持禁用/隐藏；
- 将来确需 CA：再把 B1 灰度打开，先验证 broker 首登能否**链接到已联邦的 `ligu`**（而不是新建账号）。这一步未现场验证，属**待验证**；不通过就不要开。

**不选 C 的理由**：C 要求全员再设一套密码，与用户诉求相反；且沉没成本会随首登人数上升。

### 9.5 风险与不可逆点

| # | 风险 | 说明 / 缓解 |
|---|---|---|
| R1 | **DC 单点** | DC / 网络不可用 = 全员登不上（`admin` 除外）。连接串写多 DC、保留 `admin` 本地账号；无法消除 |
| R2 | **域账号被锁** | 用户在应用里试错会累计 AD 失败次数，可能锁死域账号，进而**连电脑都登不上**。Keycloak 失败阈值要低于 AD 阈值，并准备解锁流程 |
| R3 | **清空本地用户不可逆** | realm 导出不含可用口令；回滚 = 重建 2822 账号 + 邀请/设密 + 重挂组 |
| R4 | **删除 Federation 组件会带走导入用户** | Keycloak 删除组件时会移除该 provider 导入的用户。**只停用，不删除** |
| R5 | **新入职影子账号** | 9.2.1，不处理就是"新人永远登不上" |
| R6 | **忘记密码入口失效** | READ_ONLY 不能改 AD 密码；关掉入口，引导 AD 自助重置 |
| R7 | **服务账号 / CA 到期** | 绑定账号口令过期或 CA 轮换未更新信任库 = 全员 `LDAP connection failed`；纳入到期提醒 |
| R8 | **登录名口径** | 必须输短名；`AP\ligu`、`ligu@ap.inalfa.local` 都可能 bind 失败。登录页与用户通知要写清 |
| R9 | **同步脚本 WARN 噪声** | READ_ONLY 下改资料/停用被拒；不降级会淹没真异常（§5.4） |

**不可逆点（签字前必须确认）：**

1. 删本地用户 —— 口令与 OTP 凭据不可恢复；
2. 删 Federation 组件 —— 导入用户连带删除；
3. 用户已开始用域密码后，退回本地密码 = 全员重设；
4. AD 侧改锁定策略 / 禁用账号，会同时影响 Windows 登录与三个系统。

### 9.6 实施步骤（在 §5.1 上加两处）

沿用 §5.1 的 10 步，只列**新增 / 修改**：

| 位置 | 动作 |
|---|---|
| §5.1 第 1 步前 | 跑完 9.7 的 C1–C9，全部有结果才进窗口 |
| §5.1 第 2 步后 | 用测试账号从**登录页**走一次表单登录，确认 `preferred_username=ligu` 且能进业务页（不是只看 Test authentication 通过） |
| §5.1 第 4 步前 | 断开 `sync_ad_to_sso.ps1` → KC 的建号串联（9.2.1） |
| §5.1 第 10 步前 | 改 `disable_user_now.ps1`（9.2 数据侧） |
| 第 10 步后 | 连观察 3 天：`LOGIN_ERROR` 是否集中在"账号不存在 / 密码错"，`SyncLog` 是否只有 WARN、不再刷建号 |

### 9.7 现场核查命令（只读）

前置（口令用 `Read-Host` 或凭据文件，不要写进脚本）：

```powershell
$K = 'C:\keycloak\bin\kcadm.bat'
& $K config credentials --server https://iame.ap.inalfa.local:8443 --realm master --user admin
```

| # | 查什么 | 命令 | 判据 |
|---|---|---|---|
| C1 | 是否已有 Federation | `& $K get components -r inalfa -q type=org.keycloak.storage.UserStorageProvider --fields id,name,providerId` | 返回 `[]` 才符合"全新接入" |
| C2 | 现有 IdP（Entra）状态 | `& $K get identity-provider/instances -r inalfa --fields alias,enabled` | 记录 alias 与 enabled；切换期应保持禁用/隐藏 |
| C3 | Keycloak 用户总数 | `& $K get users/count -r inalfa` | 与中央表在职数比对 |
| C4 | 保留名单行数 | §4.2 的 SQL | **必须正好 40** |
| C5 | `kc_user_id` / `pwd_set` 分布 | 下方 SQL | 记录基线，用于切换后对账 |
| C6 | DC 636 可达 | `Test-NetConnection <dc> -Port 636` | `TcpTestSucceeded=True` |
| C7 | 服务账号 bind | 下方 PowerShell | 能 `Refresh()` 出 DN |
| C8 | AD CA 是否已在信任库 | `& 'C:\keycloak\bin\kc.bat' show-config \| Select-String 'truststore'` | 有 `spi-truststore-file-file` 且指向 `ad-ca.p12` |
| C9 | `login_name` ↔ `sAMAccountName` 差异 | `Get-ADUser -Filter * -Properties sAMAccountName` 导出短名，与 `SELECT login_name FROM CN_AME_SSO_User WHERE status=1` 做 `Compare-Object` | 差异为 0，或有逐条处置 |

C5：

```sql
SELECT COUNT(*) AS total,
       SUM(CASE WHEN kc_user_id IS NULL OR LTRIM(RTRIM(kc_user_id))='' THEN 1 ELSE 0 END) AS kc_empty,
       SUM(CASE WHEN pwd_set=1 THEN 1 ELSE 0 END) AS pwd_set_1,
       SUM(CASE WHEN status=1 THEN 1 ELSE 0 END) AS active
FROM dbo.CN_AME_SSO_User;
```

C7：

```powershell
$dn = 'CN=svc-keycloak-ldap,OU=Service Accounts,DC=ap,DC=inalfa,DC=local'
$pw = Read-Host '绑定账号口令' -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
           [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
$e = New-Object System.DirectoryServices.DirectoryEntry(
        "LDAP://<dc>:636/$dn", 'AP\svc-keycloak-ldap', $plain,
        [System.DirectoryServices.AuthenticationTypes]::SecureSocketsLayer)
$e.Refresh(); $e.Name   # 能返回 DN 即 bind 成功
```

> C7 会把口令放进进程参数，只在本机执行、执行完立即关闭会话；不要写进脚本或工单。

### 9.8 回滚

与 §4.6 完全一致：**停用组件不是回滚**。

| 场景 | 动作 | 代价 |
|---|---|---|
| 切换前失败 | 删除/停用 Federation，本地用户还在 | 零 |
| 删用户后、全量同步前失败 | 停 Federation → 按 §4.6 用 `sync_sso_to_keycloak.ps1` 重建 | 2822 账号 + 邀请 |
| 上线后要退回本地密码 | 停 Federation + 重建 + 重挂组 + 恢复 `SSO_AD_Import` | 全员重设密码 |
| 只是 DC 故障（临时） | 不动配置，等 DC 恢复；`admin` 可进管理台 | 无数据变更 |

**切换前必须留的四样**：`CN_AME` 全库备份、realm 导出（异地一份）、保留名单 `keep_usernames.txt`、AD 侧服务账号与 CA 的有效期记录。

---

## 附录 A：给 IT 的沟通稿

已独立成文，直接发送：[ad-federation-it-email.md](ad-federation-it-email.md)