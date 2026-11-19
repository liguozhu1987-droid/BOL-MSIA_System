# AD 联邦接入处置清单

> 起点：IT 已交付 LDAPS 地址、只读服务账号、CA 证书、锁定阈值。
> 环境：Keycloak `C:\keycloak`，脚本 `C:\sso\scripts`，realm `inalfa`，服务名 `Keycloak`。
> 执行窗口：工作日 19:00–22:00。

## 1. 备份与导出

**位置**：Keycloak 主机 + SQL Server 主机。

```powershell
C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export\pre-federation --realm inalfa --users per_file
```

```sql
BACKUP DATABASE CN_AME TO DISK='D:\backup\CN_AME_pre_adfederation.bak' WITH INIT, COMPRESSION;
RESTORE VERIFYONLY FROM DISK='D:\backup\CN_AME_pre_adfederation.bak';
```

**成功**：导出目录有 `inalfa-realm.json`，`RESTORE VERIFYONLY` 返回成功，bak 复制一份到异地。

**失败先查**：导出报锁等待就先停 `Keycloak` 服务再导；SQL 备份空间不足先清旧 bak。

## 2. 验证 LDAPS 连通与证书链

**位置**：Keycloak 主机，证书放 `C:\sso\conf\ad-ca\`。

```powershell
$dc = 'dc01.ap.inalfa.local'   # 每台 DC 都跑一遍
Test-NetConnection $dc -Port 636
```

```powershell
$dc    = 'dc01.ap.inalfa.local'
$caDir = 'C:\sso\conf\ad-ca'

$tcp = New-Object Net.Sockets.TcpClient($dc,636)
$ssl = New-Object Net.Security.SslStream($tcp.GetStream(),$false,({$true}))
$ssl.AuthenticateAsClient($dc)
$leaf = New-Object Security.Cryptography.X509Certificates.X509Certificate2 $ssl.RemoteCertificate

$chain = New-Object Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.TrustMode = [Security.Cryptography.X509Certificates.X509ChainTrustMode]::CustomRootTrust
Get-ChildItem "$caDir\*.cer" | ForEach-Object {
    $c = New-Object Security.Cryptography.X509Certificates.X509Certificate2 $_.FullName
    $chain.ChainPolicy.ExtraStore.Add($c) | Out-Null
    if ($c.Subject -eq $c.Issuer) { $chain.ChainPolicy.CustomTrustStore.Add($c) | Out-Null }
}
"Chain OK: " + $chain.Build($leaf)
$chain.ChainElements | ForEach-Object { "  " + $_.Certificate.Subject }
$chain.ChainStatus  | ForEach-Object { "  " + $_.Status }
$ssl.Dispose(); $tcp.Close()
```

**成功**：`TcpTestSucceeded=True`；`Chain OK: True`；链为叶→中间→根，`ChainStatus` 为空。

**失败先查**：`TcpTestSucceeded=False` → 防火墙没放行，找 IT；`UntrustedRoot` / `PartialChain` → 证书文件不全或根证书拿错；`RemoteCertificateNameMismatch` → 连接用的 FQDN 与证书 SAN 不一致，改用证书里的名字。

## 3. CA 证书进 Keycloak 自己的信任库

**位置**：Keycloak 主机。Keycloak 用 Java 自己的信任库，Windows 系统证书区不生效。

```cmd
mkdir C:\keycloak\conf\truststores
cd /d C:\keycloak\conf\truststores
%JAVA_HOME%\bin\keytool -importcert -noprompt -alias inalfa-root -file C:\sso\conf\ad-ca\INALFA-IRSPKIROOT01-CA.cer -keystore ad-ca.p12 -storetype PKCS12 -storepass <口令>
%JAVA_HOME%\bin\keytool -importcert -noprompt -alias apsh-pki01-ca -file C:\sso\conf\ad-ca\ap-SRV-APSH-PKI-01-CA-1.cer -keystore ad-ca.p12 -storetype PKCS12 -storepass <口令>
%JAVA_HOME%\bin\keytool -list -v -keystore ad-ca.p12 -storetype PKCS12 -storepass <口令>
```

```cmd
C:\keycloak\bin\kc.bat build --spi-truststore-file-file=conf/truststores/ad-ca.p12 --spi-truststore-file-password=<口令> --spi-truststore-file-type=PKCS12
```

```powershell
Restart-Service Keycloak
Start-Sleep 20
Get-Service Keycloak
Invoke-RestMethod http://127.0.0.1:9000/health/ready
C:\keycloak\bin\kc.bat show-config | Select-String truststore
```

**成功**：`keytool -list` 显示两个条目；`build` 无报错；服务 `Running`；健康检查返回 `UP`；`show-config` 里能看到 `ad-ca.p12`。

**失败先查**：`build` 报 `Unrecognized option` → 参数名拼错，照上面原样；`show-config` 没有 truststore → 只改了 p12 没重新 build，或者路径没写成相对 `C:\keycloak` 的 `conf/truststores/...`；服务起不来 → `C:\keycloak\logs\keycloak.log` 里搜 `truststore`。

## 4. 新建 LDAP Federation

**位置**：浏览器打开 `https://iame.ap.inalfa.local:8443/admin` → realm `inalfa` → User federation → Add LDAP provider。

| 字段 | 值 |
|---|---|
| Vendor | `Active Directory` |
| Connection URL | `ldaps://dc01.ap.inalfa.local:636`（多个 DC 空格分隔） |
| Enable StartTLS | 关 |
| Trust email | 开 |
| Bind type | `simple` |
| Bind DN | IT 给的只读账号 DN |
| Bind Credential | 只填这里 |
| Edit mode | `READ_ONLY` |
| Users DN | IT 给的用户 OU，例如 `OU=Users,DC=ap,DC=inalfa,DC=local` |
| Username LDAP attribute | `sAMAccountName` |
| RDN LDAP attribute | `cn` |
| UUID LDAP attribute | `objectGUID` |
| User object classes | `person, organizationalPerson, user` |
| Import users | 开 |
| Sync registrations | 关 |
| Validate password policy | 关 |
| Use Truststore SPI | `ldapsOnly` |
| Pagination | 开 |
| Batch size for sync | `1000` |
| Full sync period | `-1` |
| Changed users sync period | `86400` |
| Connection pooling | 开 |

**成功**：Save 后点 `Test connection` 与 `Test authentication` 均为绿；`Test authentication` 用一个真实测试账号和域密码。

**失败先查**：`Test connection` 失败 → 回第 2、3 步；`Test authentication` 失败 → Bind DN 或口令错、测试账号不在 Users DN 下、或账号已被锁。此时不要点 `Sync all users`，同步放在第 8 步。

## 5. 抽样核对 username

**位置**：管理台 Users → Search，或用 CLI。

```powershell
$K = 'C:\keycloak\bin\kcadm.bat'
& $K config credentials --server https://iame.ap.inalfa.local:8443 --realm master --user admin
& $K get users -r inalfa -q username=<域短名> -q exact=true --fields username,email,federationLink
```

取三个账号：一个普通、一个带数字、一个平时用邮箱登录的。

**成功**：`username` 与域登录名逐字一致，`email` 有值，`federationLink` 非空。

**失败先查**：完全搜不到 → `Users DN` 或搜索过滤器不对，Import 没生效；搜到但 `username` 带 `@` 或大小写不同 → 先处理差异再往下走，否则应用侧匹配和后续脚本都会错位。

## 6. 拆掉两处脚本问题

**位置**：`C:\sso\scripts`，第 6.1 步改计划任务，第 6.2 步改应急脚本。

### 6.1 断开 06:00 建号串联

`sync_ad_to_sso.ps1` 默认会串联 `sync_sso_to_keycloak.ps1` 建号。联邦之后新建的是本地账号，会挡住同名的 AD 用户，导致本人永远登不上。

```powershell
$t   = Get-ScheduledTask -TaskName 'SSO_AD_Import'
$act = $t.Actions[0]
$act.Arguments = "$($act.Arguments) -SkipKeycloakSync"
Set-ScheduledTask -TaskName 'SSO_AD_Import' -Action $act
(Get-ScheduledTask -TaskName 'SSO_AD_Import').Actions[0].Arguments
```

**成功**：参数末尾有 `-SkipKeycloakSync`。

**失败先查**：`Set-ScheduledTask` 拒绝访问 → 用管理员 PowerShell；任务名不是这个 → `Get-ScheduledTask | Where-Object TaskName -like '*SSO*'`。

### 6.2 应急停号脚本

`disable_user_now.ps1` 第 380 行附近会把整个用户对象 PUT 回去置 `enabled=false`。只读联邦用户不接受这个写操作。

改法：在 `if ([bool](Get-Prop $kcUser 'enabled' $false))` 外层先判断 `federationLink`，非空就跳过 PUT，只保留后面的 `POST /users/{id}/logout`，日志写一句「联邦用户，请在 AD 侧禁用」。

改前备份，改后先校验语法再落盘：

```powershell
$src = Get-Content -Raw C:\sso\scripts\disable_user_now.ps1
[void][scriptblock]::Create($src)
```

**成功**：对一个测试账号执行后，日志出现「联邦用户，跳过 PUT」，Keycloak 侧用户仍是 `enabled`（预期），会话被踢掉。

**失败先查**：仍然报 400 / `ReadOnlyException` → 判断没有命中，检查 `federationLink` 字段名和取值。

## 7. 停 06:00 定时任务

**位置**：Keycloak 主机，管理员 PowerShell。

```powershell
Disable-ScheduledTask -TaskName 'SSO_AD_Import'
Get-ScheduledTask -TaskName 'SSO_AD_Import' | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName 'SSO_AD_Import' | Select-Object LastRunTime,LastTaskResult
```

**成功**：`State = Disabled`，且当前没有正在运行的实例。

**失败先查**：拒绝访问 → 管理员；任务名对不上 → `Get-ScheduledTask | Where-Object TaskName -like '*SSO*'`；`LastTaskResult` 非 0 → 先看 `C:\sso\logs` 里上一轮日志，别在异常状态下继续。

## 8. 清空本地用户与会话

**位置**：Keycloak 主机。删除范围按 `ad-federation-assessment.md` §4.3 第 3–4 步执行，条件是 `federationLink` 为空且不在 `C:\sso\conf\keep_usernames.txt`。

```powershell
& $K get users/count -r inalfa
# 删除后复查
& $K get users/count -r inalfa
```

```powershell
& $K create realms/inalfa/logout-all -r inalfa -s realm=inalfa
& $K get realms/inalfa/sessions -r inalfa -q max=5
& $K get realms/inalfa/offline-sessions -r inalfa -q max=5
```

**成功**：用户数等于保留名单条数（40）；两个会话查询都返回空数组。

**失败先查**：数量多于 40 → 白名单没读全或路径不对，停止删除；数量少于 40 → 误删，立即停手，从第 1 步的 bak 与 realm 导出恢复，不要继续往下做。

## 9. 全量同步

**位置**：Keycloak 主机。

```powershell
$id = (& $K get components -r inalfa -q type=org.keycloak.storage.UserStorageProvider --fields id,name | ConvertFrom-Json).id
& $K create user-storage/$id/sync?action=triggerFullSync -r inalfa
& $K get users/count -r inalfa
```

**成功**：用户数接近 AD 在职人数；抽查 `& $K get users -r inalfa -q username=<域短名> -q exact=true --fields username,federationLink` 的 `federationLink` 非空。

**失败先查**：导入 0 人 → Users DN 或过滤器；只导入一部分 → 只读账号对目标 OU 没有读权限，或分页被关闭；`C:\keycloak\logs\keycloak.log` 搜 `LDAP`。

## 10. 重置中央表并回写 kc_user_id

**位置**：SQL Server + Keycloak 主机。

```sql
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = NULL, pwd_set = 0
WHERE source <> 'MANUAL' AND employee_no <> 'admin';
```

```powershell
C:\sso\scripts\sync_sso_to_keycloak.ps1 -SkipInvite
```

**成功**：

```sql
SELECT COUNT(*) AS backfilled FROM dbo.CN_AME_SSO_User WHERE status = 1 AND kc_user_id IS NOT NULL;
SELECT TOP 5 * FROM dbo.CN_AME_SSO_SyncLog WHERE phase = 'KC' ORDER BY id DESC;
```

回写数接近联邦用户数，`SyncLog` 有新的 `KC` 记录。

**失败先查**：大量 404 → 第 10 步没执行或用户还没同步进来；大量 400 → 脚本仍在写用户资料，回第 6.2 步确认改动是否生效；日志里看具体端点。

## 11. 重挂准入组

**位置**：Keycloak 主机。

```powershell
C:\sso\scripts\assign_groups_from_ledger.ps1 -DryRun
C:\sso\scripts\assign_groups_from_ledger.ps1
```

**成功**：`-DryRun` 显示「查无此人 0」；正式执行后 `app-msia`、`app-bol`、`app-ics` 的人数与台账一致。

**失败先查**：查无此人非 0 → 第 9 步同步没完成，或 username 与台账不一致；组不存在 → 不要自动建，先核对组路径是否为顶层精确路径。

## 12. 从登录页真实登录

**位置**：一台普通客户端，浏览器无痕窗口。用三个**没有参与第 4 步测试**的真实账号，分别登三个系统。

- MSIA：`https://iame.ap.inalfa.local:8078`
- BOL：`https://iame.ap.inalfa.local:8090`
- Capacity：`https://iame.ap.inalfa.local:8000`（以 IIS 实际绑定端口为准）

每登一个，再做两件事：打开 `https://iame.ap.inalfa.local:8443/realms/inalfa/account` 看 username 是否为域短名；在应用里打开一个需要身份的页面，确认右上角姓名正确。

**成功**：三个系统都能进；`username` 与域短名一致；没有 403；应用显示的身份和本人对得上。

**失败先查**：登录页报用户名或密码错 → AD 侧账号是否被锁、`Username LDAP attribute` 是否为 `sAMAccountName`；登录成功但应用 403 → 组没挂上，回第 11 步；应用报用户不存在或落到空数据 → `preferred_username` 与 `login_name` 不一致，查第 5 步的差异清单；回调报 redirect_uri 错 → 三个 client 的地址配置。

`Test authentication` 只验证一次 bind，不经过浏览器和 token 流程，不能代替这一步。

## 13. 恢复任务并观察一轮

**位置**：Keycloak 主机。

```powershell
Enable-ScheduledTask -TaskName 'SSO_AD_Import'
Get-ScheduledTask -TaskName 'SSO_AD_Import' | Select-Object TaskName,State
```

**成功**：次日 06:00 自动跑完，`LastTaskResult = 0`；`SyncLog` 没有新增建号记录；Keycloak 里 `federationLink` 为空的用户数没有增加。

**失败先查**：出现新的本地用户 → `-SkipKeycloakSync` 没生效，回第 6.1 步；任务报错 → `C:\sso\logs` 当日日志。
