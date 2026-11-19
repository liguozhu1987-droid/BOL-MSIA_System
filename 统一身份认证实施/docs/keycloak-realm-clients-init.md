# Keycloak 25.0.6：收尾封口（清单 A）与 realm/client 初始化（清单 B）

> 前置：`docs/keycloak-deploy-runbook.md` 第 10 节 V1–V6 已过，服务由 NSSM 正常运行。
> 👉 **不熟 Keycloak 界面、想照着屏幕一步步点？请看 [keycloak-console-setup-for-beginners.md](./keycloak-console-setup-for-beginners.md)**（零基础控制台操作手册，与本文命令做的是同一件事）。
> 版本口径：**Keycloak 25.0.6**（`kc.bat` / `kcadm.bat`），JDK 21。
> 依据：25.0.6 官方《Server Administration Guide → Admin CLI》（`kcadm create/update` 语义、`config truststore`）、`realm-setup.md`、`clients.md`，以及两套系统**实际代码**（取值以代码为准，见第 4 节差异表）。
> 本文只产出清单，不代替现场执行；所有 `<>` 占位必须替换为现场确认值。
>
> **修订记录（2026-11-09，第二轮）**：按《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 / §9.5 对齐——会话 `ssoSessionIdleTimeout=86400`、`ssoSessionMaxLifespan=604800`（1 天 / 7 天，覆盖原 28800/43200 秒，原值作废）；SMTP `from=ap_sso@inalfa.com`、`fromDisplayName=Inalfa AME系统统一身份认证`，`auth/starttls/ssl=false`。暴力破解维持 5 次 / 900 秒（本轮无变更）。

---

## 0. 会话变量块（每个新窗口重跑）

```powershell
$KC       = 'C:\keycloak'
$SvcName  = 'Keycloak'
$JdkHome  = 'C:\Program Files\Java\jdk-21.0.10'   # 现场确认（10.1-T3）
$KCADM    = "$KC\bin\kcadm.bat"
$OPS_IP   = '<运维机内网IP>'                        # 需现场确认
$env:JAVA_HOME     = $JdkHome
$env:KEYCLOAK_HOME = $KC
```

---

# 清单 A：② 收尾封口

## A1 服务侧确认

```powershell
Get-Service $SvcName | Select-Object Name, Status, StartType
(Get-CimInstance Win32_Service -Filter "Name='$SvcName'").StartMode
Get-CimInstance Win32_Process -Filter "Name='java.exe'" |
    Where-Object { $_.CommandLine -like '*keycloak*' } |
    Select-Object ProcessId, ExecutablePath
Get-Content "$KC\logs\keycloak.log" -Tail 50 | Select-String -Pattern 'ERROR|FATAL|Exception'
```

| 判据 | 通过条件 | 不通过 |
|---|---|---|
| 服务状态 | `Status = Running`、`StartType = Automatic`（NSSM 里是 `SERVICE_AUTO_START`） | 停服看 `service-stderr.log`；启动失败按 runbook 10.11 |
| JDK | `ExecutablePath` 含 `jdk-21`（不是 `C:\Program Files (x86)\...\java8`） | 说明 NSSM `AppEnvironmentExtra` 丢了 `JAVA_HOME`，回 10.8 |
| 日志 | 最近 50 行无 `ERROR`/`FATAL`；`WARN` 可接受（如 `Deprecated`） | 出现 `Login failed` / `Cannot open database` 按 10.11 |

## A2 健康与端点验证（本机无 curl，用 .NET）

**管理口 9000：IPv6 `::` 与 IPv4 两种写法都要试**（该机 9000 监听在 `::`，`::` 上的双栈是否接受 v4 映射取决于系统配置，必须实测而不是假定）。

```powershell
$urls = 'http://127.0.0.1:9000/health/ready','http://[::1]:9000/health/ready'
foreach ($u in $urls) {
  try {
    $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 10
    "[OK]   $u -> $($r.StatusCode) $($r.Content)"
  } catch {
    "[FAIL] $u -> $($_.Exception.Message)"
  }
}
```

| 结果组合 | 判读 |
|---|---|
| 两条都 200 + `{"status":"UP"}` | 管理口 v4/v6 都通 → 正常 |
| 仅 `[::1]` 通、`127.0.0.1` 失败 | 只监听了 IPv6。属预期（10.9 netstat 已见 `::`）；**`health_check.ps1` 若写死 127.0.0.1 要改成 `[::1]` 或两条都试**，否则误报 DOWN |
| 都 503 | 仍在启动/建表，等 60–120 秒；持续 503 看日志 |
| 都失败 | 9000 未起（`http-management-port` 是否被 10.4 误删）→ 查 conf 与启动参数 |

**8443 JWKS（自签，.NET WebClient 跳过证书校验）**：

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$wc = New-Object Net.WebClient
$wc.Headers.Add('Accept','application/json')
($wc.DownloadString('https://127.0.0.1:8443/realms/master/protocol/openid-connect/certs') | ConvertFrom-Json).keys.Count
# 判据：>= 1
```

**discovery 记录（B0 的输入，必须留证）**：

```powershell
($wc.DownloadString('https://127.0.0.1:8443/realms/master/.well-known/openid-configuration') |
    ConvertFrom-Json) | Select-Object issuer, authorization_endpoint, token_endpoint
```

> 把 `issuer` 的实际值抄进记录。**若带 `:8443` 或与 `https://sso.ap.inalfa.local/realms/inalfa` 不一致，先做 B0，不要往下建 client。**
> 校验完成后清掉回调，避免污染后续脚本：
> ```powershell
> [Net.ServicePointManager]::ServerCertificateValidationCallback = $null
> ```

## A3 端口封口（8443 / 9000 只允许本机与指定运维机）

**先审计现有规则**（避免已有宽泛允许规则让封锁失效）：

```powershell
Get-NetFirewallRule -Direction Inbound -Enabled True | ForEach-Object {
  $p = $_ | Get-NetFirewallPortFilter
  if ($p.LocalPort -in 8443,9000) {
    [pscustomobject]@{ Name=$_.DisplayName; Action=$_.Action; Port=$p.LocalPort; Remote=$_.RemoteAddress; Profile=$_.Profile }
  }
}
```

**再按目标选方案**：

方案 1（推荐：外部完全不需要访问，只本机回环）

```powershell
New-NetFirewallRule -DisplayName 'Block-Keycloak-8443-Inbound' -Direction Inbound -Action Block -Protocol TCP -LocalPort 8443
New-NetFirewallRule -DisplayName 'Block-Keycloak-9000-Inbound' -Direction Inbound -Action Block -Protocol TCP -LocalPort 9000
```

方案 2（需指定运维机访问 9000 做巡检）

```powershell
Remove-NetFirewallRule -DisplayName 'Block-Keycloak-9000-Inbound' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'Allow-Keycloak-9000-Ops' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9000 -RemoteAddress 127.0.0.1,$OPS_IP
```

> ⚠️ Windows 防火墙**显式 Block 规则优先于 Allow 规则**，两者混用会让白名单彻底失效。要白名单就只能用"仅 Allow + 精确 RemoteAddress"，并确保没有其它宽泛 Allow 规则（上面的审计就是为此）。

**本机验证（回环不受防火墙约束，应仍通）**：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 8443 -InformationLevel Quiet   # True
Test-NetConnection -ComputerName 127.0.0.1 -Port 9000 -InformationLevel Quiet   # True
```

**另一台内网机验证（预期 False）**：

```powershell
Test-NetConnection -ComputerName IRSCnKettle01.ap.inalfa.local -Port 8443 -InformationLevel Quiet   # False
Test-NetConnection -ComputerName IRSCnKettle01.ap.inalfa.local -Port 9000 -InformationLevel Quiet   # False
Test-NetConnection -ComputerName IRSCnKettle01.ap.inalfa.local -Port 8443 -InformationLevel Detailed # TcpTestSucceeded : False
```

| 现象 | 判读 |
|---|---|
| 本机 True、另一台 False | 封口成功 |
| 另一台 True | 规则未生效：确认端口/协议（TCP）、`Profile` 是否覆盖 Domain 网卡、是否有 GPO 规则覆盖 |
| 本机 8443 False | 8443 未监听或证书启动失败，回 A1 |
| 另一台能连但本机 IIS ARR 正常 | 说明 ARR 走 127.0.0.1，属预期；外部仍应不可达 |

## A4 备份与敏感信息处置

**（1）26 备份目录：先抹口令，再删目录**

```powershell
# 1) 全目录扫一遍，确认没有口令残留
Get-ChildItem 'C:\keycloak_26_backup' -Recurse -File -Include *.conf,*.properties,*.log,*.bat,*.ps1 -ErrorAction SilentlyContinue |
    Select-String -Pattern 'db-password=','KEYCLOAK_ADMIN_PASSWORD','client_secret' -SimpleMatch
# 2) 需留证先把 logs 归档到受限目录，然后整目录删除
New-Item -ItemType Directory -Force 'C:\sso\archive\keycloak26-logs' | Out-Null
Copy-Item 'C:\keycloak_26_backup\logs\*.log' 'C:\sso\archive\keycloak26-logs\' -ErrorAction SilentlyContinue
Remove-Item 'C:\keycloak_26_backup' -Recurse -Force
Test-Path 'C:\keycloak_26_backup'          # 预期 False
```

**（2）PowerShell 历史里的明文口令（最容易漏）**

```powershell
(Get-PSReadLineOption).HistorySavePath
Select-String -Path (Get-PSReadLineOption).HistorySavePath -Pattern 'KC_DB_PASSWORD','KEYCLOAK_ADMIN_PASSWORD','client_secret','kcadmin'
```

命中则**按行剔除**（不要整文件删掉运维记录）：

```powershell
$h = (Get-PSReadLineOption).HistorySavePath
(Get-Content $h) |
    Where-Object { $_ -notmatch 'KC_DB_PASSWORD|KEYCLOAK_ADMIN_PASSWORD|client_secret|kcadmin' } |
    Set-Content $h -Encoding UTF8
```

历史文件位置（两处都可能存在）：

| PowerShell | 路径 |
|---|---|
| 5.1 | `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt` |
| 7.x | `%APPDATA%\Microsoft\PowerShell\PSReadLine\ConsoleHost_history.txt` |

预防：敏感命令前先 `Set-PSReadLineOption -HistorySaveStyle SaveNothing`（PSReadLine 2.x），做完关窗口。

**（3）服务注册表里不得有临时变量**

```powershell
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Keycloak\Parameters' |
    Select-Object AppEnvironmentExtra, AppDirectory, Application
```

预期 `AppEnvironmentExtra` **只有** `JAVA_HOME=` 与 `KC_DB_PASSWORD=`；出现 `KEYCLOAK_ADMIN*` / `KC_BOOTSTRAP_ADMIN_*` 立即按 runbook 10.8 覆盖回两项并重启。

**（4）截图 / 导出 / 日志**

| 物件 | 处置 |
|---|---|
| 控制台截图 | 不得含 client secret、`Credentials` 页面、用户初始口令；已截的删除或裁切 |
| realm 导出 JSON | **导出文件内含 client secret**，按密件管理：放 `C:\sso\kc-export`（仅运维账号可读），不得进 git/邮件 |
| `keycloak.log` | 不含 secret，但含用户名/登录事件；按日志留存策略归档 |
| `build.log` / `service-stderr.log` | 无 secret；可留在 `C:\keycloak\logs` |

**（5）`keycloak_svc` 口令轮换（窗口与步骤）**

- **时机**：realm/client 初始化完成、交付前做一次；之后每半年或人员变动时再做。
- **窗口**：轮换需要重启 Keycloak，**30–60 秒服务中断**，安排在业务低峰；期间应用本地登录不受影响（OIDC 开关此时仍未开）。
- **步骤（顺序不可颠倒，否则服务连不上库）**：

```powershell
# 1) 生成新口令（不打印到屏幕）
$new = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 28 | ForEach-Object {[char]$_})
$new | Set-Clipboard

# 2) SSMS（IRSCNYTFINEREPORT）执行：ALTER LOGIN keycloak_svc WITH PASSWORD = N'<粘贴新口令>';
#    口令不要含单引号

# 3) 更新服务环境变量（两项必须一条命令给全）
& $NSSM set $SvcName AppEnvironmentExtra "JAVA_HOME=$JdkHome" "KC_DB_PASSWORD=$new"

# 4) 重启 + 验证
& $NSSM restart $SvcName
Start-Sleep -Seconds 60
Get-Service $SvcName | Select-Object Status
Get-Content "$KC\logs\keycloak.log" -Tail 20 | Select-String 'Login failed|Started Keycloak|ERROR'
```

- **判据**：服务 Running、日志无 `Login failed for user 'keycloak_svc'`、A2 的 `health/ready` 为 UP。
- 轮换后**旧口令立即失效**；`C:\keycloak_26_backup` 若还没删，此步之后已无利用价值，但目录仍要删。
- 记录：轮换时间、执行人、新口令封存编号（**只记编号，不记口令**）。

## A5 台账更新（勾选口径）

| 位置 | 写什么 |
|---|---|
| `keycloak-deploy-runbook.md` §0 P1–P7 | P1 ✅（回填 JDK 目录）；P2/P3/P4 ✅（由 10.5-D2/D3/D4 达成，附 D6 截图路径）；P5 ➖（复用 26 备份 PEM，记 SHA256）；P6 ✅（包路径 + SHA256）；P7 ✅（口令已轮换，封存编号） |
| 同文档 10.9 V1–V6 | 六行全部 ✅，每行附"验证时间 + 证据文件名"（日志片段、SQL 输出、截图） |
| 同文档 10.10 台账 | 登记：Keycloak 25.0.6 / IRSCnKettle01 / 8443（回环+防火墙）/ 9000 / `sso.ap.inalfa.local` / 服务名 `Keycloak` / NSSM / JDK21 路径 |
| 同文档 10.12 | 结论落 **PASS**，并注明"已进入 realm/client 初始化" |
| 《统一身份认证技术交底书》2.1 | "进行中：Keycloak 部署" → "已完成（25.0.6 服务化）"；"待办"增加 realm/client 初始化状态 |

---

# 清单 B：③ realm / client 初始化

## B0 前置配置门：issuer 必须与两系统配置完全一致

两系统读的是**同一个值**：

| 系统 | 文件 | 键 | 现值（代码） |
|---|---|---|---|
| MSIA | `backend/config.ini` | `[oidc] issuer` | `https://sso.ap.inalfa.local/realms/inalfa` |
| BOL | `backend/db_config.ini` | `[oidc] issuer` | `https://sso.ap.inalfa.local/realms/inalfa` |

要求：**scheme https、host `sso.ap.inalfa.local`、无端口、无结尾斜杠**。Keycloak 侧 issuer 由 `hostname=sso.ap.inalfa.local` 决定，但**端口依赖访问路径**：

| 访问方式 | issuer 可能形态 |
|---|---|
| 经 IIS ARR（自带 `X-Forwarded-Host/Port=443`） | `https://sso.ap.inalfa.local/realms/inalfa` ✅ |
| 直连 `https://127.0.0.1:8443`（无转发头） | 可能带 `:8443` ❌ |

**动作**：A2 记下实际值。若直连带 `:8443`，在 `keycloak.conf` 增加：

```properties
hostname-port=443
```

然后 **`kc.bat build` 重新构建 + 重启服务**（hostname 相关属 build-time 选项，改完不 rebuild 不生效；不确定时先 `.\kc.bat build --help` 查该选项是否在列），再复查 discovery。

> 不改 issuer 的理由：issuer 一变，两系统配置、已签发令牌的 `iss` 校验、未来网关都要跟着改。**issuer 一次定死，G4 定稿只动 redirect_uri。**

## B1 建立 realm `inalfa`

### B1-0 kcadm 信任本机自签证书（25.0.6 的官方路径是 truststore）

25.0.6 官方 Admin CLI 文档只给 `kcadm config truststore` 这一条信任自签证书的做法；`--tls-ignore-hostname-verification` **不是 kcadm 的参数**（kcadm 没有同名开关，照抄会报 `Unknown option`）。

```powershell
# 1) 自签证书 CN=localhost → 必须用 localhost 访问，用 127.0.0.1 会域名不匹配
& "$JdkHome\bin\keytool.exe" -importcert -noprompt -alias keycloak-local `
    -file "$KC\conf\server.crt.pem" `
    -keystore "$KC\conf\kcadm-truststore.jks" -storepass changeit -storetype JKS

# 2) 让 kcadm 使用该 truststore
& $KCADM config truststore -trustpass changeit "$KC\conf\kcadm-truststore.jks"

# 3) 可选：自证本机 kcadm 是否支持 --insecure（有则后续命令可加，无则继续用 truststore）
& $KCADM config credentials --help | Select-String 'insecure|truststore|tls'
```

### B1-1 登录 master

```powershell
Set-Location "$KC\bin"
& $KCADM config credentials --server https://localhost:8443 --realm master --user kcadmin --password '<kcadmin 口令>'
# 预期：Logging into https://localhost:8443 as user kcadmin of realm master
```

### B1-2 建 realm + 全部策略（字段逐个给值）

```powershell
& $KCADM create realms -s realm=inalfa -s enabled=true -s displayName=inalfa

& $KCADM update realms/inalfa -r inalfa `
  -s displayNameHtml='<b>统一身份认证</b>（MSIA / BOL）' `
  -s registrationAllowed=false `
  -s resetPasswordAllowed=true `
  -s loginWithEmailAllowed=false `
  -s duplicateEmailsAllowed=false `
  -s verifyEmail=false `
  -s editUsernameAllowed=false `
  -s rememberMe=false `
  -s bruteForceProtected=true `
  -s failureFactor=5 `
  -s waitIncrementSeconds=900 `
  -s maxFailureWaitSeconds=900 `
  -s quickLoginCheckMilliSeconds=1000 `
  -s minimumQuickLoginWaitSeconds=60 `
  -s accessTokenLifespan=900 `
  -s ssoSessionIdleTimeout=86400 `
  -s ssoSessionMaxLifespan=604800 `
  -s actionTokenGeneratedByUserLifespan=259200 `
  -s "passwordPolicy=length(10) and notUsername and notEmail and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1)" `
  -s eventsEnabled=true `
  -s eventsExpiration=7776000 `
  -s adminEventsEnabled=true `
  -s adminEventsDetailsEnabled=true
```

| 字段 | 值 | 依据 / 说明 |
|---|---|---|
| realm | `inalfa` | 两系统 issuer 路径 `/realms/inalfa` |
| enabled | true | — |
| Login theme | 默认 `keycloak`（不填即默认） | 定制主题本期不做；`loginTheme` 留空 |
| User registration | OFF | R6：只能来自同步 |
| Forgot password | ON | `resetPasswordAllowed=true` |
| Login with email | OFF | 统一 username 登录（与两系统 `login_name` 口径一致） |
| Duplicate emails | OFF | 邮箱暂不管控（允许空/重复由 `duplicateEmailsAllowed=false` + 不强制验证实现） |
| Verify email | OFF | 降低设密摩擦 |
| Brute force | ON，5 次失败，递增 900 秒，最大等待 900 秒，快速登录检查 1 秒 | realm-setup.md §4 |
| Access token | 900 秒（15 分钟） | §5 |
| SSO idle / max | **86400 / 604800 秒（1 天 / 7 天）** | 交底书 §9.3（2026-11-09 现场决定，覆盖原 8h / 12h，原值作废）；方向是加长，不会踢掉已登录用户 |
| Action token lifespan | 259200 秒（3 天） | 设密邮件 3 天有效（默认 5 分钟会失效） |
| Password policy | 长度 10、非用户名、非邮箱、大写/小写/数字/特殊各 1；不过期 | §3 |
| Events | 用户事件 ON，保留 7776000 秒（90 天）；管理员事件 ON + 详情 ON | §6 |
| SMTP | 见下条命令 | 25 端口无认证无 TLS |
| sslRequired | 保留默认 `external` | 对外经 ARR HTTPS；本机回环视为安全 |

SMTP（`starttls=false` / `ssl=false` / `auth=false` 已显式写入，不要依赖"不填即关闭"）：

> 当前是**内网明文中继**。若后续邮件网关启用 STARTTLS，把 `starttls` 改为 `"true"`（必要时同步调整端口），保存后**重新实测发信**。判据是「确实收到信」，Test Connection 成功不算。

```powershell
& $KCADM update realms/inalfa -r inalfa `
  -s 'smtpServer={"host":"172.19.253.10","port":"25","from":"ap_sso@inalfa.com","fromDisplayName":"Inalfa AME系统统一身份认证","auth":"false","starttls":"false","ssl":"false"}'
```

> 管理员事件保留期：25.0.6 的 RealmRepresentation 没有独立的 admin 事件过期字段，控制台里也没有单独项；以 `eventsExpiration` 为准即可，**不要臆造参数**。用 `& $KCADM get realms/inalfa --fields eventsExpiration` 核对。

### B1-3 准入组

```powershell
& $KCADM create groups -r inalfa -s name=app-msia
& $KCADM create groups -r inalfa -s name=app-bol
& $KCADM get groups -r inalfa --fields id,name,path
# 预期：/app-msia、/app-bol（顶层组，path 与 name 同名）
```

> 组必须是**顶层**，且 mapper 里 `full.path=false`，令牌里才是 `"groups":["app-msia"]`；写成 `/dept/app-msia` 或开 full path，后端 `in groups` 比对会失败。

### B1-4 建 realm 后的即时校验

```powershell
& $KCADM get realms/inalfa --fields realm,enabled,accessTokenLifespan,ssoSessionIdleTimeout,bruteForceProtected,passwordPolicy,eventsExpiration
```

## B2 四个 client：字段表 + 建库命令

> 认证方式约定：`publicClient=false` ⇔ 控制台"Client authentication = ON"（confidential）。授权码流 + PKCE(S256)。

### B2-1 `msia-prod`（MSIA Report 登录回调链路）

| 字段 | 值 | 说明 |
|---|---|---|
| Client ID | `msia-prod` | 与 `config.ini [oidc] client_id` 一致 |
| Name | `MSIA Report` | — |
| Enabled | true | — |
| Client authentication | ON（`publicClient=false`） | 后端持 secret |
| Authorization | OFF（`authorizationServicesEnabled=false`） | 不用 Keycloak 授权服务 |
| Standard flow | true | 授权码 |
| Implicit flow | false | 禁用 |
| Direct access grants | false | 禁用密码模式（代码不用） |
| Service accounts | false | 代码不用 |
| Valid redirect URIs | `http://172.26.2.203:8078/api/auth/oidc/callback` | **精确匹配**，来源 `MSIA Report/backend/config.ini:117` |
| Valid post logout redirect URIs | 留空（可沿用 `clients.md` 原值 `http://172.26.2.203:8078/`） | 应用只做本地登出、不调 `end_session`，该项填了也不生效；留空可少一个开放跳转面 |
| Web origins | `http://172.26.2.203:8078` | CORS，精确 origin |
| Root URL / Home URL | `http://172.26.2.203:8078` | 控制台展示用 |
| Access token lifespan | 0（继承 realm 900 秒） | — |
| PKCE | `pkce.code.challenge.method=S256` | 25.0.6 不强制，显式设上 |
| Mappers / scopes | `groups` 专用 mapper + 默认 `profile`/`email` | 后端读 `groups` 与 `preferred_username`/`name`/`email` |
| Frontchannel logout | OFF | 代码无 frontchannel 端点 |

```powershell
& $KCADM create clients -r inalfa `
  -s clientId=msia-prod -s 'name=MSIA Report' -s enabled=true `
  -s publicClient=false -s standardFlowEnabled=true -s implicitFlowEnabled=false `
  -s directAccessGrantsEnabled=false -s serviceAccountsEnabled=false `
  -s authorizationServicesEnabled=false `
  -s 'redirectUris=["http://172.26.2.203:8078/api/auth/oidc/callback"]' `
  -s 'webOrigins=["http://172.26.2.203:8078"]' `
  -s rootUrl=http://172.26.2.203:8078 -s baseUrl=http://172.26.2.203:8078 `
  -s 'attributes={"pkce.code.challenge.method":"S256"}' -i
```

### B2-2 `bol-prod`（BOL 登录回调链路，redirect 待 G4）

| 字段 | 值 | 说明 |
|---|---|---|
| Client ID | `bol-prod` | 与 `db_config.ini [oidc] client_id` 一致 |
| Client authentication | ON | Django 后端持 secret |
| Standard flow / Implicit / Direct / Service accounts | true / false / false / false | 同 MSIA |
| Valid redirect URIs | `http://127.0.0.1:8090/api/auth/oidc/callback`、`http://127.0.0.1:8090/api/auth/oidc/callback/` | 占位值；**两条都要**，原因见 §3 尾斜杠 |
| Valid post logout redirect URIs | 留空 | 同 MSIA |
| Web origins | `http://127.0.0.1:8090` | 占位；定为正式地址后追加 |
| Root URL / Home URL | `http://127.0.0.1:8090` | 占位 |
| PKCE | S256 | — |
| Mappers | `groups` + 默认 profile/email | 准入值 `app-bol` |
| Frontchannel logout | OFF | 代码无端点 |

```powershell
& $KCADM create clients -r inalfa `
  -s clientId=bol-prod -s 'name=BOL 管理系统' -s enabled=true `
  -s publicClient=false -s standardFlowEnabled=true -s implicitFlowEnabled=false `
  -s directAccessGrantsEnabled=false -s serviceAccountsEnabled=false `
  -s authorizationServicesEnabled=false `
  -s 'redirectUris=["http://127.0.0.1:8090/api/auth/oidc/callback","http://127.0.0.1:8090/api/auth/oidc/callback/"]' `
  -s 'webOrigins=["http://127.0.0.1:8090"]' `
  -s rootUrl=http://127.0.0.1:8090 -s baseUrl=http://127.0.0.1:8090 `
  -s 'attributes={"pkce.code.challenge.method":"S256"}' -i
```

### B2-3 `sync-client`（同步脚本调 Admin REST，非浏览器链路）

| 字段 | 值 |
|---|---|
| Client ID | `sync-client` |
| Client authentication | ON |
| Standard flow | **false** |
| Implicit / Direct access grants | false / false |
| Service accounts | **true** |
| Valid redirect URIs / Web origins / Root URL | 留空 |
| Service account roles | `realm-management` 的 `manage-users`、`view-users`、`query-users`（不给 `realm-admin`） |

```powershell
& $KCADM create clients -r inalfa `
  -s clientId=sync-client -s 'name=SSO Sync' -s enabled=true `
  -s publicClient=false -s standardFlowEnabled=false -s implicitFlowEnabled=false `
  -s directAccessGrantsEnabled=false -s serviceAccountsEnabled=true -s authorizationServicesEnabled=false -i

& $KCADM add-roles -r inalfa --uusername service-account-sync-client `
  --cclientid realm-management `
  --rolename manage-users --rolename view-users --rolename query-users
```

> 服务账号用户名约定是 `service-account-<clientId>`。先 `& $KCADM get users -r inalfa -q username=service-account-sync-client` 确认存在再加角色；查不到就先 `get clients -q clientId=sync-client --fields id` 核对 clientId 大小写。

### B2-4 `account`（内置）

保持启用，不改配置。邀请设密邮件的落地页由它承载（`UPDATE_PASSWORD` 在此完成）。只需确认它仍在：

```powershell
& $KCADM get clients -r inalfa -q clientId=account --fields clientId,enabled,publicClient
```

### B2-5 `groups` mapper（两个业务 client 都要加）

```powershell
$cid = ((& $KCADM get clients -r inalfa -q clientId=msia-prod --fields id) | ConvertFrom-Json)[0].id
& $KCADM create "clients/$cid/protocol-mappers/models" -r inalfa `
  -s name=groups -s protocol=openid-connect `
  -s protocolMapper=oidc-group-membership-mapper `
  -s 'config={"claim.name":"groups","full.path":"false","id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}'
```

`bol-prod` 用同一条命令，只把 `clientId=msia-prod` 换成 `bol-prod`。

**默认 scope 核对**（新建 client 应自动继承 realm 的 default client scopes）：

```powershell
& $KCADM get "clients/$cid/client-scopes" -r inalfa --fields name
# 预期含 profile、email、roles、web-origins、acr、basic
```

缺 `profile`/`email` 时（少见，通常发生在用 `-f` 覆盖创建时）补挂：

```powershell
$sid = ((& $KCADM get client-scopes -r inalfa -q name=email --fields id) | ConvertFrom-Json)[0].id
& $KCADM update "clients/$cid/default-client-scopes/$sid" -r inalfa
```

> 不需要额外 `audience` mapper：两系统验的是 **id_token 的 `aud`**，Keycloak 的 id_token `aud` 天然等于 client_id（代码 `verify_id_token(..., audience=settings.OIDC_CLIENT_ID)`）。

## B3 secret 生成、保管与注入

**生成/读取（不 echo 到屏幕）**：

```powershell
$cid  = ((& $KCADM get clients -r inalfa -q clientId=msia-prod --fields id) | ConvertFrom-Json)[0].id
$sec  = ((& $KCADM get "clients/$cid/client-secret" -r inalfa) | ConvertFrom-Json).value
# 需要重新生成时（旧 secret 立即失效，必须同步改应用）：
# & $KCADM create "clients/$cid/client-secret" -r inalfa

# 立即转 DPAPI 加密落盘（SecureString 才会被 CliXml 加密）
$sec | ConvertTo-SecureString -AsPlainText -Force |
    Export-Clixml -Path 'C:\sso\conf\msia-prod.secret.xml'
$sec = $null
```

取回（同一台机、同一运行账号）：

```powershell
$s = (Import-Clixml 'C:\sso\conf\msia-prod.secret.xml')
[Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
```

| 项 | 规则 |
|---|---|
| 存放位置 | `C:\sso\conf\` 下每 client 一个 `*.secret.xml`（DPAPI，绑定本机 + 当前账号）。若已有 `credentials.xml` 统一台账，按其既有结构追加，**不要另建一套**（结构待现场确认） |
| 目录权限 | `icacls C:\sso\conf /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"` |
| 禁止 | 写进 git、写进 `docs/`、贴进聊天/工单、留在截图、留在 PS 历史 |
| 轮换 | 每次 `create client-secret` 后，**先改应用再重启**，旧 secret 立即失效；期间登录会失败，需窗口 |

**注入两系统（代码事实，不可两者混用）**：

| 系统 | 注入位置 | 代码依据 |
|---|---|---|
| MSIA | 服务器上的 `config.ini` → `[oidc] client_secret = <secret>`；或进程环境变量 `OIDC_CLIENT_SECRET`（**env 优先**，`config.py` 只在 env 未设时才写入） | `MSIA Report/backend/app/core/config.py:162,176-179` |
| BOL | **只能** `db_config.ini` → `[oidc] client_secret = <secret>`；代码没有 per-key 的环境变量覆盖，只有 `BOL_DB_CONFIG` 可改配置文件路径 | `BOL管理系统/backend/bol_platform/settings.py:363-388` |

```powershell
# BOL：把密文解出来写进服务器上的 db_config.ini（文件权限收紧）
icacls '<BOL部署目录>\db_config.ini' /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

> 仓库里的 `db_config.ini` / `config.ini` 模板保持 `client_secret =` 空值；只在服务器副本填。

## B4 初始化后的验证

```powershell
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$wc = New-Object Net.WebClient

# 1) realm 存在
& $KCADM get realms/inalfa --fields realm,enabled

# 2) client 存在且开关正确
& $KCADM get clients -r inalfa --fields clientId,enabled,publicClient,standardFlowEnabled,serviceAccountsEnabled,redirectUris

# 3) discovery 三要素
($wc.DownloadString('https://127.0.0.1:8443/realms/inalfa/.well-known/openid-configuration') |
    ConvertFrom-Json) | Select-Object issuer, authorization_endpoint, token_endpoint, jwks_uri
```

| 校验 | 通过条件 |
|---|---|
| issuer | 与两系统配置**逐字符相同**：`https://sso.ap.inalfa.local/realms/inalfa` |
| authorization_endpoint | `https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/auth` |
| token_endpoint | `https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/token` |
| jwks_uri | `.../protocol/openid-connect/certs` |

**最小 token 链路（sync-client 的 client_credentials，不依赖任何用户）**：

```powershell
$syncSec = '<sync-client secret>'   # 从 DPAPI 取，不打印
$form = @{ grant_type='client_credentials'; client_id='sync-client'; client_secret=$syncSec }
$tok = Invoke-RestMethod -Uri 'https://127.0.0.1:8443/realms/inalfa/protocol/openid-connect/token' `
        -Method Post -Body $form -ContentType 'application/x-www-form-urlencoded'
$tok.token_type; ($tok.access_token -split '.')[1]   # Base64URL 段，可 base64 解码看 iss/aud/exp
```

判据：`token_type=Bearer`、返回 `access_token`。失败 `invalid_client` → secret 或 `serviceAccountsEnabled` 不对；`unauthorized_client` → 该 client 没开 service accounts。

**授权端点冒烟（验证 redirect_uri 已登记）**：

```powershell
$u = 'https://127.0.0.1:8443/realms/inalfa/protocol/openid-connect/auth' +
     '?client_id=msia-prod&response_type=code&scope=openid' +
     '&redirect_uri=' + [uri]::EscapeDataString('http://172.26.2.203:8078/api/auth/oidc/callback')
(Invoke-WebRequest -Uri $u -UseBasicParsing).StatusCode
```

| 结果 | 含义 |
|---|---|
| 200 + 登录页 HTML | redirect_uri 已正确登记、client 可用 |
| 400 `Invalid parameter: redirect_uri` | URI 字符串与登记值不一致（常见：尾斜杠、http/https、端口） |
| `Invalid client` | clientId 拼错或 client 被禁用 |

**完整授权码链路**：需要真实用户 + 组 + 应用开关，属下一步（灌用户后）。此时才把两系统 `[oidc] enabled` 打开，先在测试账号上走一遍。

---

## 3. redirect_uri 待定项（G4）怎么处理

### 3.1 "先建后补"的具体做法

1. **现在**用占位值建 client（`msia-prod` 用代码现值；`bol-prod` 用 `127.0.0.1:8090` 两条），不做任何猜测；
2. 地址定稿后，**读旧值 → 拼新值 → 整体提交**（`kcadm update` 默认做 get+merge，但**数组属性是整体替换**，只提交新值会把旧值冲掉）：
3. 验证通过一个观察期后，再删旧值。

```powershell
# 追加（保留旧值；webOrigins 同理，一次一起提交）
$c   = ((& $KCADM get clients -r inalfa -q clientId=bol-prod --fields id,redirectUris,webOrigins) | ConvertFrom-Json)[0]
$newR = @($c.redirectUris) + '<新回调URI>'
$newW = @($c.webOrigins)  + '<新 origin>'
$jr = '["' + ($newR -join '","') + '"]'
$jw = '["' + ($newW -join '","') + '"]'
& $KCADM update "clients/$($c.id)" -r inalfa -s "redirectUris=$jr" -s "webOrigins=$jw"

# 改完立刻核对（不要靠控制台肉眼）
& $KCADM get "clients/$($c.id)" -r inalfa --fields redirectUris,webOrigins
```

**为什么用这种拼法**：PS 5.1 的 `ConvertTo-Json` 遇到单元素数组会退化成字符串，导致提交的不是 JSON 数组；手工拼 `["a","b"]` 最稳。

### 3.2 哪些值现在就能填、哪些必须等定稿

| 类别 | 示例 | 现在能否填 | 限制 |
|---|---|---|---|
| 本机联调 | `http://127.0.0.1:8090/api/auth/oidc/callback` | ✅ 可填（BOL 已是占位） | 只有服务器本机浏览器能完成；不是生产值 |
| 内网 IP:端口 | `http://172.26.2.203:8078/...`（MSIA 现网） | ✅ 可直接作为**过渡生产值** | 无 DNS 依赖；但用户看到的是 IP，证书只对域名有效 |
| 正式域名 | `https://msia.ap.inalfa.local/...`、`https://bol.ap.inalfa.local/...` | ❌ 等 DNS + ARR + CA 定稿 | 三条一起到位才能用 |
| 通配 | `*`、`http://*/*`、`.../callback*` | ❌ **禁止** | 任意站点可接收授权码 → 令牌窃取/开放重定向 |

DNS/证书未到位时用 IP 的连带限制：

- **issuer 仍是 `sso.ap.inalfa.local`**：浏览器会被跳到该域名，DNS 不解析就登不了（所以 IP 只适合作回调地址，不适合作 issuer）；
- **Cookie 域绑定 hostname**：用 IP 访问 Keycloak 与用域名访问不共享 SSO 会话；
- **8443 自签**：外部机器必须手动信任，不能作为生产入口（生产入口是 ARR 的 443 + 企业证书）。

### 3.3 占位 → 正式 对照表模板

| Client | URI 用途 | 现在填（占位） | 定稿后填（正式） | 风险/备注 |
|---|---|---|---|---|
| `msia-prod` | 登录回调 | `http://172.26.2.203:8078/api/auth/oidc/callback` | `https://msia.ap.inalfa.local/api/auth/oidc/callback`（U1） | 追加，不替换；两条并存直到切换完成 |
| `msia-prod` | CORS origin | `http://172.26.2.203:8078` | `https://msia.ap.inalfa.local` | 必须是 scheme+host+port，不带路径 |
| `bol-prod` | 登录回调 | `http://127.0.0.1:8090/api/auth/oidc/callback`、`.../callback/` | `http://bol.ap.inalfa.local/api/auth/oidc/callback`（U2/G4） | 定稿前不可对外 |
| `bol-prod` | CORS origin | `http://127.0.0.1:8090` | `http://bol.ap.inalfa.local` | — |
| 两个业务 client | 登出后跳转 | 留空 | 留空（应用只做本地登出） | 若将来接 Keycloak `end_session`，再按精确 URI 填 |

### 3.4 定稿后的切换顺序（两侧必须同步）

1. **Keycloak 先加新值**（保留旧值）→ 核对 `redirectUris`；
2. 改应用配置：`redirect_uri` 改为新值；**`issuer` 不动**；
3. 重启应用（BOL 改 `db_config.ini`、MSIA 改 `config.ini` 都要重启进程）；
4. 用新地址完整登录一次（discovery → 授权页 → 回调 → OTK 换登录态）；
5. 观察 1–2 个工作日；
6. **再删旧值**（同样用读-改-写，提交只含保留项的数组）。

> 颠倒顺序（先删旧值）会让旧地址登录**立即**失败，双轨期不可接受。
> 顺序中不进 `issuer` 的理由见 B0：issuer 一变，两系统 + Keycloak hostname（build-time）+ 已发令牌全部要重来。

### 3.5 代码与文档的差异（以代码为准，已按下表处理）

| # | 差异 | 事实（代码） | 处理 |
|---|---|---|---|
| D1 | BOL 回调路由带尾斜杠（`path('oidc/callback/')`），配置值不带 | `auth_urls.py:35`；Django `APPEND_SLASH` 会对无斜杠请求 301 到带斜杠（查询串保留，功能可用但多一跳） | Keycloak 里**两条都登记**；后续统一定稿时把 `db_config.ini` 也改成带斜杠，再删旧值 |
| D2 | MSIA 回调 `.../api/auth/oidc/callback`（无斜杠） | FastAPI `@router.get("/oidc/callback")` | 与登记值一致，无需改 |
| D3 | MSIA `[server] port=8000`，但 redirect/`system_url` 都是 `:8078` | `config.ini:117,137,144` | 待确认：8078 是否为 IIS/反代的对外端口；确认前 **redirect 按 8078 登记**（这是代码实际发送的值） |
| D4 | `realm-setup.md` 标题写 26.x | 实际 25.0.6 | 已改为"25.0.6 口径" |
| D5 | `clients.md` 称"26 默认强制 PKCE" | 25.0.6 不强制 | 已改为"显式设 S256" |
| D6 | `clients.md` Frontchannel logout = ON | 两系统代码均无 frontchannel 登出端点（仅本地登出） | 已改为 OFF，避免 Keycloak 渲染指向不存在 URL 的 iframe |
| D7 | 两系统均声明 `scopes = openid profile email` | 一致 | client 默认 scope 必须含 `profile`/`email`，B4 已校验 |

---

## 4. 需要现场确认的项

| # | 事项 | 确认方法 | 影响 |
|---|---|---|---|
| Q1 | MSIA 实际对外端口（8000 还是 8078） | 看 IIS 站点绑定/反代配置；或 `netstat -ano \| findstr 8078` | 决定 `msia-prod` 的 redirectUri |
| Q2 | BOL 正式内网地址（U2/G4） | 找业务方定稿；部署包默认 `--port 8090` | `bol-prod` redirect/webOrigins |
| Q3 | 本机 kcadm 是否支持 `--insecure` | `& $KCADM config credentials --help \| Select-String 'insecure'` | 有则可用，无则走 truststore（B1-0） |
| Q4 | discovery 的 `issuer` 实际值 | A2 的 discovery 命令 | 是否要加 `hostname-port=443`（B0） |
| Q5 | `C:\sso\conf\credentials.xml` 既有结构 | `Get-Content C:\sso\conf\credentials.xml -TotalCount 5`（若有） | secret 统一台账的追加方式 |
| Q6 | MSIA 进程启动方式（服务/计划任务/手动） | `Get-CimInstance Win32_Service \| ? { $_.PathName -like '*msia*' }` | 若用 env 注入 `OIDC_CLIENT_SECRET`，必须能改该进程环境 |
| Q7 | BOL 部署目录与运行账号 | `Get-CimInstance Win32_Process \| ? { $_.Name -like 'BOLServer*' }` | `db_config.ini` 权限与 secret 注入 |
| Q8 | 服务账号 `service-account-sync-client` 是否存在 | `& $KCADM get users -r inalfa -q username=service-account-sync-client` | 决定 B2-3 加角色前是否要先核对 clientId |
| Q9 | 管理员事件保留期是否有独立字段 | `& $KCADM get realms/inalfa \| Select-String 'adminEvents'` | 只影响审计留存，不影响功能 |
| Q10 | 是否有第四个用途的 client | 与两系统负责人确认；当前代码只用 `msia-prod`/`bol-prod`/`sync-client`/`account` | 防止多建 client 扩大攻击面 |

---

## 5. 执行顺序（一把梭版）

```text
A1 服务确认 → A2 健康/端点(记 issuer) → B0 issuer 门(需要则 rebuild+重启)
  → A3 端口封口 → A4 敏感信息处置(先抹后删; 轮换安排窗口)
  → B1 登录 kcadm → realm → 策略 → SMTP → 组
  → B2 四个 client → groups mapper → 默认 scope 核对
  → B3 secret 生成/DPAPI/注入 → B4 三项验证 + client_credentials + 授权端点冒烟
  → A5 台账勾选 → 应用侧才可开 OIDC_ENABLED → 灌用户（另一份清单）
```

> 反例：先把 `enabled=true` 再建 client，会立刻把登录页打出"统一登录"入口并 302 到未配置的 client，用户侧直接报错。**永远先 Keycloak 后应用开关。**
