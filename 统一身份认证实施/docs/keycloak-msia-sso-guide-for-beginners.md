# Keycloak 25.0.6 + MSIA 统一身份认证：从零走到登录成功（零基础操作手册）

> **这份文档与其他两份的关系**
> - 本文是**端到端一条龙**：从"服务在不在"一路做到"浏览器登录成功"，面向第一次上手的人，每一步都有命令、判据和"不对时最可能是哪里"。
> - `docs/keycloak-console-setup-for-beginners.md` 是**纯控制台版**，只讲 Keycloak 里那些对象怎么点（realm、client、group、mapper），不含 MSIA 侧。
> - `docs/keycloak-realm-clients-init.md` 是**命令行版**（`kcadm` 可粘贴命令）+ 字段取值依据表，适合已经会了、要批量复现的人。
> 三者内容有重叠是故意的：本文给的是"照着做能通"，另两份给的是"为什么这么填"。
>
> **本文对应的现场状态（2026-11）**
> | 项 | 值 |
> |---|---|
> | Keycloak | 25.0.6，安装目录 `C:\keycloak`，NSSM 服务名 `Keycloak` |
> | 端口 | 8443 HTTPS、9000 管理口（`/health/ready`） |
> | 证书 | 自签，PEM 方式；SAN = `IP:172.26.2.203` + `DNS:localhost` + `DNS:sso.ap.inalfa.local`；私钥无口令 |
> | MSIA | 构建 `20261105-1600`，部署目录 `C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server`，监听 8000，对外经 8078 |
> | 口径 | issuer 用 IP（`https://172.26.2.203:8443/realms/inalfa`）、client `msia-prod`、组 `app-msia`、redirect `http://172.26.2.203:8078/api/auth/oidc/callback` |
> | 双轨 | `local_login_enabled=true`、`sso_user_sync_enabled=false` |
>
> **本文不编造的三类值**：JDK 安装路径、服务运行账号、kcadmin 口令 / client secret、8078 反代细节。凡是这几类，文中写 **需现场确认**，请用现场值替换。

---

## 0. 这份文档怎么用 + 术语表

### 0.1 三条主线，别混着做

1. **Keycloak 侧**（第 1–7 章）：确认服务能用 → 建组 → 建 client → 建 mapper → 建一个测试用户。
2. **MSIA 侧**（第 8–9 章）：改 `config.ini` → 带证书信任启动 exe → 三条自检。
3. **联合调试**（第 10 章）：浏览器走一遍，看黑窗口日志。

**顺序不能反**。先启动 MSIA 再配 Keycloak，你会看到一堆 503/403，分不清是配置没写对还是 Keycloak 没有对象。

### 0.2 术语表（每个都配大白话 + 比喻）

| 术语 | 大白话 | 比喻 |
|---|---|---|
| **realm** | Keycloak 里的一个独立"认证空间"，用户、应用、策略都归它管 | 一栋独立的办公楼，门禁和员工名册都归这栋楼 |
| **client** | 一个接入这个认证空间的应用（这里是 MSIA） | 这栋楼里的一家公司，有自己的工牌通道 |
| **client secret** | 应用和 Keycloak 之间共享的一串密码，证明"我确实是 MSIA 后端" | 公司和门禁系统之间的对暗号 |
| **mapper** | 决定"令牌里带哪些信息"的规则，比如把用户所在的组写进 `groups` | 门禁卡上要印哪些字段（部门、楼层） |
| **PKCE** | 授权码流里额外加的一对"一次性校验值"，防止授权码被半路截走 | 取快递时的取件码：只认这次、只认你 |
| **issuer** | Keycloak 自称的"我是谁"，形如 `https://主机/realms/inalfa`；应用会校验它 | 门禁系统对外报的正式名称，对不上就不认 |
| **redirect URI** | 登录成功后把用户送回应用的哪个地址 | 快递的收货地址，差一个字符就送不到 |
| **groups claim** | 令牌里的一个数组，列出用户属于哪些组；MSIA 用它判断"有没有开通" | 工牌背面印的准入楼层列表 |
| **realm-management 角色** | Keycloak 内置的一组管理权限，同步脚本要用到其中三个 | 物业给运维发的"只能管住户、不能改大楼结构"的门禁权限 |

### 0.3 你会见到两种界面

- **Keycloak 管理控制台**（浏览器，`https://172.26.2.203:8443`）：配 realm / client / group / user。
- **MSIA 黑窗口**（exe 启动后的控制台窗口）：看启动日志和登录日志。**出问题第一眼看这里**，不要先猜证书。

---

## 1. 开工前的 5 项确认（任何一项不过就停下）

### 1.1 服务状态

你要做什么：确认 NSSM 服务真的在跑，而不是"进程列表里有个 java"。

```powershell
$Svc = Get-CimInstance Win32_Service -Filter "Name='Keycloak'"
$Svc | Select-Object Name, State, StartMode, ProcessId, PathName
```

✅ 做到这里你应该看到：`State = Running`、`StartMode = Automatic`、`ProcessId` 非 0。

如果不对，最可能是：服务根本没注册（`Get-CimInstance` 返回空）或启动即退出。看 `C:\keycloak\logs\service-stderr.log`，**不要**先去怀疑证书。

> **新手陷阱（真实踩过）**：服务停了，却去猜"证书是不是又不对了"。先看 `State`。`State=Stopped` 时浏览器报的任何 TLS 错误都没有意义——端口上根本没有服务。

### 1.2 两个端口

你要做什么：确认 8443（业务）和 9000（管理）都在监听。

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8443,9000 |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

✅ 做到这里你应该看到：两行，`LocalPort` 分别是 8443、9000，`OwningProcess` 是同一个 java 进程 PID。

如果不对，最可能是：8443 没监听 → `keycloak.conf` 里 `http-enabled=false` 但证书加载失败；9000 没监听 → `health-enabled=true` 没生效或端口被占。

### 1.3 证书指纹与有效期

你要做什么：确认 8443 上现在这张证书就是重签后的那张，且 SAN 里带 IP。

```powershell
$KC = 'C:\keycloak'
Get-ChildItem "$KC\conf\server.crt.pem","$KC\conf\server.key.pem" |
  Select-Object Name, Length, LastWriteTime
```

```powershell
# 若 keytool 不在 PATH，先按现场 JDK 路径调用（<JDK路径> 需现场确认）
& '<JDK路径>\bin\keytool.exe' -printcert -file "$KC\conf\server.crt.pem"
```

✅ 做到这里你应该看到：两个文件都在；`keytool` 输出里有一行

```
SubjectAlternativeName: [ IP:172.26.2.203, DNS:localhost, DNS:sso.ap.inalfa.local ]
```

并且有效期不是 1970 也不是已过期。

如果不对，最可能是：证书还是旧的（缺 `IP:` 那一项）→ 后面 MSIA 一定报 `IP address mismatch`。**就此停下，先按证书重签流程处理**，不要继续往下配。

> **新手陷阱（真实踩过）**：证书只写了 `DNS:localhost`，MSIA 用 `https://172.26.2.203:8443` 连，Python 只认 SAN 不认 CN，直接 `IP address mismatch`。修证书，不要在代码里关校验。

### 1.4 issuer 回显（这一条最容易被"照抄文档"害死）

你要做什么：让 Keycloak 自己告诉你它认为的 issuer 是什么，**以回显为准**。

```powershell
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$d = Invoke-RestMethod 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration'
[pscustomobject]@{ issuer = $d.issuer; authorization_endpoint = $d.authorization_endpoint; token_endpoint = $d.token_endpoint }
[Net.ServicePointManager]::ServerCertificateValidationCallback = $null
```

✅ 做到这里你应该看到：`issuer` 是一个 https 地址，形如 `https://<某主机>/realms/inalfa`。**把这个字符串原样记下来**，第 8 章要一字不差地填进 `config.ini`。

如果不对，最可能是：
- 报证书错误 → 你没先设上面的 `ServerCertificateValidationCallback`；
- 报 404 → realm 名不是 `inalfa`；
- `issuer` 主机是 `sso.ap.inalfa.local`（而 MSIA 的 redirect 主机是 `172.26.2.203`）→ **停下**。MSIA 启动时会做配置体检，`issuer` 主机与 `redirect_uri` 主机不一致会被判为错误并返回 503（见 `app/core/oidc.py` 的 `validate_config`）。这时要么让 Keycloak 的回显变成 IP 口径，要么把 MSIA 的对外访问地址统一成同一主机——**这是现场决策，需现场确认**，不要硬填。

### 1.5 kcadm 能登录

你要做什么：确认命令行管理通道可用（后面查 client / group / user 都用它）。

```powershell
$KCADM = "$KC\bin\kcadm.bat"
& $KCADM config credentials --server 'https://172.26.2.203:8443' --realm master `
  --user kcadmin --password '<kcadmin 口令>'
& $KCADM get realms/inalfa --fields realm,enabled
```

✅ 做到这里你应该看到：`Logging into https://172.26.2.203:8443 as user kcadmin of realm master`，以及 `"realm" : "inalfa", "enabled" : true`。

如果不对，最可能是：`kcadm` 不信任本机自签证书 → 需要 `kcadm-truststore.jks`（`C:\keycloak\conf\kcadm-truststore.jks`，别名 `keycloak-local`，storepass `changeit`）。`<kcadmin 口令>` 是 **需现场确认** 的值，物理封存，不在任何文档里。

> **新手陷阱（真实踩过）**：`kcadm config credentials` 成功后改了证书却没重新登录，后面所有命令都拿着旧会话，报的错看起来像"权限问题"。换证书后必须重跑这一条。

---

## 2. 登录 Keycloak 管理控制台

### 2.1 进控制台

你要做什么：用浏览器打开管理台，用 `kcadmin` 登录 master 域。

- 地址：`https://172.26.2.203:8443`（自签证书，浏览器会拦）
- 点 **Advanced / 高级** → **Proceed to 172.26.2.203 (unsafe)**（Chrome/Edge 文案略有差异，认"仍然继续"这个动作）
- 用户名 `kcadmin`，口令 `<kcadmin 口令>`（需现场确认）

✅ 做到这里你应该看到：左上角显示 `master`，左侧一竖排菜单（`Realm Settings`、`Clients`、`Groups`、`Users`…），右上角是你登录的用户名。

如果不对，最可能是：`Invalid username or password` → 你用的是 realm 用户而不是 master 管理员；`kcadmin` 只在 `master` 域。

### 2.2 "认字段名，不认位置"

Keycloak **25 是经典控制台**：左侧菜单 + 一页表单 + 页签（`Settings` / `Credentials` / `Mappers` / `Client scopes`）。
Keycloak 26 起改成三页向导（General / Capability config / Login settings），同样的字段被拆到不同页。

所以本文所有界面描述都**先给字段名**：你看到的排版可能不同，但字段名不会变。找不到时用页面搜索（`Ctrl+F`）搜字段名。

✅ 做到这里你应该看到：你能在 `master` 里自由切换左侧菜单，且顶部 realm 下拉能列出 `inalfa`。

如果不对，最可能是：你其实还在 26.x（界面是三页向导）→ 字段名仍适用，按名字找即可，但**不要照抄本文的页签名**。

---

## 3. realm `inalfa` 的核对与必要设置

### 3.1 切到 realm

你要做什么：从 master 切到 `inalfa`。

左上角 realm 下拉 → 选 `inalfa`（若列表里没有，说明 realm 没建，需现场确认）。

✅ 做到这里你应该看到：左上角变成 `inalfa`，左侧菜单不变。

如果不对，最可能是：realm 名拼错（大小写敏感）；或在 master 里改了东西——那不会影响业务 realm。

### 3.2 General

| 字段（按名字找） | 应设 | 为什么 / 填错会怎样 |
|---|---|---|
| `Enabled` | ON | 关掉整个 realm 不可用，登录页直接报错 |
| `Display name` | `统一身份认证`（可选） | 只影响登录页标题 |
| `User Registration`（自助注册） | **OFF** | 开了等于任何人都能自己注册进统一身份；人员只能从中央表来 |
| `Forgot Password` | ON | 用户自助改密要用 |
| `Email as Username` | OFF | 我们用 `login_name` 当用户名 |
| `Edit Username` | OFF | 用户名是唯一键，禁止用户自己改 |
| `Login with email` | OFF（建议） | 开了以后用户可能拿邮箱登录，和"必须用 login_name"冲突 |

✅ 做到这里你应该看到：`Enabled` 是 ON，`User Registration` 是 OFF，`Edit Username` 是 OFF。

如果不对，最可能是：改完没点 `Save`（经典控制台每次都要显式保存）。

> **新手陷阱（真实踩过）**：用户名必须用中央表的 `login_name`（小写）。开了 `Login with email` 或让用户拿邮箱登录，登录能成功但身份解析命中不了本地账号，最后变成一个最低权限的新账号。第 7 章会再说一遍。

### 3.3 Login

| 字段 | 应设 |
|---|---|
| `Require SSL`（有的版本叫 `SSL required`） | `external`（默认，保持） |
| `Verify Email` | OFF（本环境邮箱暂不管控） |
| `Remember Me` | 按现场习惯，默认 OFF 即可 |

✅ 做到这里你应该看到：没有任何一项被改成 `none` 或把 SSL 关掉。

如果不对，最可能是：为了让自签证书"好过"把 `Require SSL` 关了——没必要，8443 本来就是 HTTPS。

### 3.4 Email（SMTP）

> **参数口径**：以下为正式参数（以交底书 §9.5 为准）。当前是内网明文中继；若后续邮件网关启用 STARTTLS，把 `Enable StartTLS` 改 ON（必要时同时调整端口），保存后重新做发信验证。

| 字段 | 值 |
|---|---|
| `Host` | `172.19.253.10` |
| `Port` | `25` |
| `From` | `ap_sso@inalfa.com` |
| `From Display Name` | `Inalfa AME系统统一身份认证` |
| `Enable StartTLS` | OFF |
| `Enable SSL` | OFF |
| `Authentication` | OFF（本环境无认证中继） |

点 **Test Connection**。

✅ 做到这里你应该看到：绿色提示"Test connection successful"。

> **注意：Test Connection 只证明「连得上、能握手」，不证明「信能到」**。真正的判据是**实际收到一封验证信**：用测试账号触发一封设密/改密邮件（或让邮件管理员代发测试），确认收件箱确实收到。判据写「确实收到邮件」，不要写「保存成功」。

如果不对，最可能是：SMTP 25 被防火墙拦，或发件人域名被判垃圾（后者 Test Connection 也会成功，但邀请邮件进垃圾箱）。**需现场确认**邮件服务器策略。

### 3.5 Tokens

> **数值口径**：本表以《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 为准。本文早期版本写的 `SSO Session Idle = 30 分钟` **已作废**；随后又由现场决定改为 **1 天 / 最长 7 天**（2026-11-09 第二轮决策），同样覆盖本文早前记录的 8 小时 / 12 小时。

| 字段 | 值 | 原因 |
|---|---|---|
| `Access Token Lifespan` | 900 秒（默认） | 太长则被踢下线后仍可用 |
| `Action Token Generated By User Lifespan` | `4320` + `Minutes`（=3 天） | 设密邀请邮件默认 5 分钟就失效 |
| `SSO Session Idle` | **1 天** | 现场决定（2026-11-09 第二轮），覆盖原 8 小时；加长不会踢掉已登录用户 |
| `SSO Session Max` | **7 天** | 超过此时长强制重新认证；加长对在用用户无感 |

✅ 做到这里你应该看到：这四项保存后刷新页面仍然是新值。

如果不对，最可能是：单位选错（秒 / 分钟 / 小时），显示值看起来对但实际差 60 倍。

### 3.6 Security Defenses

> **数值口径**：本表以《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 为准。本文早期版本写的 `Max Login Failures = 30`、`Wait Increment = 60 秒` **已作废**（2026-11-09 决策）。

| 字段 | 值 |
|---|---|
| `Brute Force Detection` | ON |
| `Max Login Failures` | **5**（连续失败 5 次开始锁定） |
| `Wait Increment` | **900 秒**（首次锁定 15 分钟） |

✅ 做到这里你应该看到：`Brute Force Detection` 为 ON。

如果不对，最可能是：把它关了图省事——等于允许无限撞密码。

### 3.7 Events

| 字段 | 值 |
|---|---|
| `Save Events` | ON |
| `Expiration` | `90` + `Days` |
| `Admin events` | ON（`Include Representation` 可选） |

✅ 做到这里你应该看到：`Save Events` ON、Expiration 90 Days。

如果不对，最可能是：开了 Save Events 但没开 Expiration → 数据库无限增长。

---

## 4. 组 `app-msia`

### 4.1 建组

你要做什么：建一个**顶层**组，名字精确为 `app-msia`。

左侧 `Groups` → `Create group` → `Name` 填 `app-msia` → `Create`。

✅ 做到这里你应该看到：Groups 列表里出现 `/app-msia`（前面的 `/` 表示它是顶层）。

```powershell
& $KCADM get groups -r inalfa --fields id,name,path
```

应看到 `"name" : "app-msia", "path" : "/app-msia"`。

如果不对，最可能是：你把它建成了某个组的子组，`path` 变成 `/xxx/app-msia`。

### 4.2 为什么必须顶层（这条必须懂）

MSIA 校验的是令牌里 `groups` 数组是否**包含字符串** `app-msia`。

- 顶层组 + mapper 的 `Full group path = OFF` → 令牌里是 `"groups": ["app-msia"]` → 通过。
- 子组，或 `Full group path = ON` → 令牌里是 `"groups": ["/dept/app-msia"]` 或 `"/app-msia"` → 字符串不相等 → **403 未开通本系统访问权限**。

> **新手陷阱（真实踩过）**：`full.path=true` 是 403 的高发原因。看到 403 先去查 mapper 的这个开关，而不是先去查用户有没有加组。

---

## 5. client `msia-prod`

### 5.1 新建或核对

左侧 `Clients` → `Create client`（26 是三页向导；25 是一页表单）。
若 `Clients` 列表里已经有 `msia-prod`，点进去核对，不要重复建。

> **新手陷阱（真实踩过）**：复制粘贴 client 名时带了**尾部空格**（`msia-prod `），令牌请求报 `Client not found`，但列表里看起来名字一模一样。点开 client，把 `Client ID` 全选复制，用 `Trim()` 比对：
> ```powershell
> & $KCADM get clients -r inalfa -q clientId=msia-prod --fields clientId,id
> ```
> 返回空数组就说明名字里有不可见字符。**宁可删了重建**，别手动改。

### 5.2 逐字段表

| 字段（按名字找） | 值 | 填错会怎样 |
|---|---|---|
| `Client ID` | `msia-prod` | 与 `config.ini` 的 `client_id` 不一致 → Keycloak 报 `Client not found` |
| `Name` | `MSIA Report`（展示用） | 无影响 |
| `Enabled` | ON | 关掉 → `invalid_client` |
| `Client authentication`（25 里等价于 `publicClient=false`） | **ON** | 关掉 → 后端拿 secret 换 token 被拒（`invalid_client`） |
| `Authorization` | OFF | 开了不必要 |
| `Standard flow` | **ON** | 关掉 → 授权码流不可用，登录页报 `Invalid parameter: response_type` |
| `Implicit flow` | OFF | 开了不安全 |
| `Direct access grants` | **OFF** | 开了等于允许账号密码直取令牌，绕过 SSO |
| `Service accounts roles` | OFF | 业务 client 不需要 |
| `Valid redirect URIs` | 见 5.3 | 差一个字符 → `Invalid parameter: redirect_uri` |
| `Web origins` | `http://172.26.2.203:8078` | 漏填 → 前端跨域取 token 失败（页面空白/控制台 CORS 报错） |
| `Root URL` / `Home URL` | `http://172.26.2.203:8078` | 只影响控制台展示 |
| `PKCE`（Advanced） | 见 5.5 | 缺 `code_challenge_method` → 授权请求被拒或换 token 失败 |

### 5.3 `Valid redirect URIs` 是多行框，怎么写

这个框是**一行一个完整 URL**，不是逗号分隔。必须精确等于 MSIA 的 `redirect_uri`：

```
http://172.26.2.203:8078/api/auth/oidc/callback
```

> **新手陷阱（真实踩过）**：写成 `http://172.26.2.203:8078/api/auth/oidc/callback/`（多一个尾斜杠），或写成 `http://172.26.2.203:8078/*`，前者会 `Invalid parameter: redirect_uri`，后者把开放跳转面放大。
> 若要同时容纳"带尾斜杠"的变体（某些框架会补 `/`），就**另起一行**再加一条带 `/` 的，不要用通配符。
>
> 另外：**不要**把 `127.0.0.1` / `localhost` 的地址混进生产 client。MSIA 启动体检会把 `redirect_uri` 含 `127.0.0.1`/`localhost` 判为占位错误并 503。

### 5.4 `Web origins`

填 `http://172.26.2.203:8078`（只填 scheme+host+port，不带路径、不带尾斜杠）。

✅ 做到这里你应该看到：保存后重新打开，`Valid redirect URIs` 仍是那一行完整 URL，`Client authentication` 是 ON，`Standard flow` 是 ON。

如果不对，最可能是：经典控制台点 `Save` 后页面顶部没有绿色提示——那说明校验没过（常见是 `Web origins` 带了路径）。

### 5.5 Advanced 里的 PKCE

在 `Advanced Settings`（26 在 `Capability config` 页）里：

| 字段 | 值 |
|---|---|
| `Proof Key for Code Exchange Code Challenge Method`（25 里显示为 `PKCE Code Challenge Method`） | `S256` |

MSIA 的授权请求固定带 `code_challenge` + `code_challenge_method=S256`（`app/core/oidc.py` 的 `create_pkce_pair`）。

✅ 做到这里你应该看到：该字段是 `S256`，不是空、不是 `plain`。

如果不对，最可能是：你以为"不填就是默认 S256"。25.0.6 不会强制，空着可能被拒——**显式设上**。

> **新手陷阱（真实踩过）**：漏配 `code_challenge_method` 时，现象往往不是清晰的报错，而是浏览器停在登录页后回跳失败，黑窗口里只有 `OIDC 回调失败: ...`。先查这一项。

### 5.6 取 client secret

你要做什么：拿到 `msia-prod` 的 secret，填进 MSIA（或注入环境变量）。

左侧 `Clients` → `msia-prod` → `Credentials` 页签 → `Client Secret` 一栏 → 复制。

```powershell
$Cid = (& $KCADM get clients -r inalfa -q clientId=msia-prod --fields id).id
& $KCADM get "clients/$Cid/client-secret" -r inalfa --fields value
```

✅ 做到这里你应该看到：一串随机字符串（`"value" : "..."`）。

如果不对，最可能是：`Client authentication` 是 OFF → 这个 client 根本没有 secret 页签。

> **安全**：secret 等同于 MSIA 后端的身份证。**不要贴到聊天、文档、工单里**；只在本机 PowerShell 会话里用，或写进 DPAPI 凭据文件。

---

## 6. Mapper `groups`（两个入口，都要会）

MSIA 读的是**令牌里的 `groups` 数组**。默认 client 不会带这个 claim，必须加 mapper。

### 6.1 入口一：客户端 Mappers 页签

`Clients` → `msia-prod` → `Mappers` 页签 → `Add mapper`（有的版本是 `Create` / `Add`）→ `By protocol` → 选 `group membership`。

| 字段 | 值 |
|---|---|
| `Name` | `groups` |
| `Mapper type` | `Group membership` |
| `Token Claim Name` | `groups` |
| `Full group path` | **OFF** |
| `Add to ID token` | ON |
| `Add to access token` | ON（建议） |
| `Add to userinfo` | ON（可选） |

> MSIA 验的是 **id_token**（`verify_id_token`），所以 `Add to ID token` 必须 ON。

### 6.2 入口二：Client scopes → Dedicated scope and mappers

如果 `Mappers` 页签里找不到（25 的部分小版本会把它挪走）：

`Clients` → `msia-prod` → `Client scopes` 页签 → 找到 `msia-prod-dedicated` → 点进去 → `Mappers` 子页签 → `Add mapper` → `By protocol` → `Group membership`，字段同上。

> 两个入口写的是**同一份** mapper 列表，从哪进都一样；只要别在两处各建一个（会出现重复 claim）。

### 6.3 `Full group path` 必须 OFF

| 设置 | 令牌里的值 | MSIA 结果 |
|---|---|---|
| OFF（正确） | `"groups": ["app-msia"]` | 通过 |
| ON | `"groups": ["/app-msia"]` | **403 未开通本系统访问权限** |

✅ 做到这里你应该看到：Mappers 列表里有一条 `groups`，类型 `Group membership`，`Full group path` 为 OFF，`Add to ID token` 为 ON。

如果不对，最可能是：在 Client scope 里加了一次、又在 Mappers 里加了一次，令牌出现两个 `groups` 键。

### 6.4 怎么验证 claim 真的带出来了

不要靠猜。用控制台的 `Clients` → `msia-prod` → `Client scopes` 里的 `Evaluate`（或 `Evaluate` 页签）：

- `User` 选第 7 章那个测试用户
- 点 `Generated token`（或 `Evaluate`）
- 找 `groups`

✅ 做到这里你应该看到：`groups` 字段是 `["app-msia"]`（**不带斜杠**）。

如果不对，最可能是：用户还没加组（第 7.3 步），或 `Full group path` 是 ON。

---

## 7. 建一个能登录的测试用户

### 7.1 选谁

推荐用中央表里**确定存在、且 MSIA 本地未停用**的账号。已核实可用的：

| 用户名 | 说明 |
|---|---|
| `ligu` | MSIA 本地 admin，安全 |
| `yangli1` | MSIA 本地 admin，安全 |
| `zhangya4` | MSIA 本地 lead_reviewer（BOL 侧需要 UserMap，MSIA 侧不需要） |

**不要**用 `yaole` 做第一次测试：它在 MSIA 本地是 `status=0`，键完密码也只会得到 403「账号已禁用」。这是已知业务项，不是配置错。

### 7.2 建用户

`Users` → `Add user`（26 是 `Create new user`）：

| 字段 | 必填 | 值 |
|---|---|---|
| `Username` | **是** | `ligu`（**必须是中央表 `login_name` 的小写形式**，不能用邮箱） |
| `Email` | 否 | `Guozhu.Li@inalfa.com`（与中央表一致；空也能建） |
| `Email verified` | 否 | 有邮箱时建议 ON |
| `First name` / `Last name` | 否 | 只影响展示名 |
| `Enabled` | 是 | ON |

`Create` 之后：`Credentials` 页签 → `Set password`。

| 字段 | 建议 |
|---|---|
| `Password` / `Password confirmation` | 现场自定强口令 |
| `Temporary` | **本手册建议 ON**（首登强制改密，更接近真实用户路径）；只是自己反复调试可 OFF |

✅ 做到这里你应该看到：用户列表里出现 `ligu`，`Enabled` 列是 ON；`Credentials` 里显示 `Temporary` 状态符合你的选择。

如果不对，最可能是：用户名用了邮箱或大写 `LIGU`。Keycloak 用户名虽不区分大小写地查找，但**中央表回落匹配是按 `login_name` 精确值走的**，保持小写最稳。

> **新手陷阱（真实踩过）**：用户名必须等于中央表 `login_name` 小写。写成 `Guozhu.Li@inalfa.com` 或 `Ligu`，MSIA 会认为"这个人本地不存在"，然后按 `auto_create_user=true` **自动建一个新账号**（最低权限 `reviewee`），你原来 admin 的角色就没了。

### 7.3 加组（这一步漏了必然是 403）

`Users` → `ligu` → `Groups` 页签 → `Join Group`（26 是 `Join groups`）→ 勾选 `app-msia` → `Join`。

```powershell
$Uid = (& $KCADM get users -r inalfa -q username=ligu --fields id).id
& $KCADM get "users/$Uid/groups" -r inalfa --fields id,name,path
```

✅ 做到这里你应该看到：返回里有 `"name" : "app-msia"`。

如果不对，最可能是：组名不是 `app-msia`（拼错/多空格），或加到了子组。

---

## 8. MSIA 的 `config.ini` 逐键填写

### 8.1 文件在哪

```
C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini
```

**必须在 exe 同级目录**。发布包里已经剔除了构建机带出来的 `config.ini`（`_internal\config.ini` 已被删除），所以现场这份是"服务器自己的配置"，改它才生效。改 `dist\` 或源码目录里的那份对线上没有任何作用。

> **新手陷阱（真实踩过）**：改了源码仓库里的 `config.ini`，然后重启 exe 发现没变化。要确认你改的是 exe 同目录那份：
> ```powershell
> Get-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' |
>   Select-Object FullName, LastWriteTime
> ```
> `LastWriteTime` 必须是你刚保存的时间。

### 8.2 完整的 `[oidc]` 块（照这块替换）

```ini
[oidc]
# 统一身份登录总开关
enabled = true

# Keycloak issuer：把第 1.4 步 discovery 回显的 issuer 原样贴过来
issuer = https://172.26.2.203:8443/realms/inalfa

# 客户端 ID
client_id = msia-prod

# 客户端密钥（建议留空，改用环境变量 OIDC_CLIENT_SECRET 注入）
client_secret =

# 回调地址（必须与 Keycloak 的 Valid redirect URIs 逐字符一致）
redirect_uri = http://172.26.2.203:8078/api/auth/oidc/callback

# 前端回调页（后端 302 到这里并带 ?otk=）
front_callback = /oidc/callback

# 准入组
required_group = app-msia

# 本地用户表未命中时是否自动建档（true = 按最低权限 reviewee 新建）
auto_create_user = true

# 授权范围
scopes = openid profile email
```

### 8.3 逐键说明（填什么 / 为什么 / 填错会怎样）

| 键 | 填什么 | 为什么 | 填错会怎样 |
|---|---|---|---|
| `enabled` | `true` | 打开统一登录入口 | `false` 时 `/api/auth/oidc/login` 与回调返回 **503「统一登录未启用」**，登录页看不到统一登录按钮 |
| `issuer` | **第 1.4 步回显的原字符串** | 应用拿它校验 `id_token` 的 `iss`，也是拼授权地址的基址 | 与回显不一致 → `OIDC 回调失败`/`id_token iss 不匹配`；若与 `redirect_uri` 主机不同 → 启动体检直接报错并 503 |
| `client_id` | `msia-prod` | 与 Keycloak client 对应 | 尾部空格或大小写不符 → `Client not found` |
| `client_secret` | 留空，用 `OIDC_CLIENT_SECRET` 环境变量 | 不落盘明文 | 空且未注入环境变量 → 体检报 `client_secret 为空` → **503「OIDC 配置不完整」** |
| `redirect_uri` | `http://172.26.2.203:8078/api/auth/oidc/callback` | 授权后回跳地址，必须与白名单完全一致 | 差尾斜杠/端口/协议 → Keycloak 报 `Invalid parameter: redirect_uri`；写成 `127.0.0.1` → 体检判为占位并 503 |
| `front_callback` | `/oidc/callback` | 后端 302 到前端承接一次性码的页面 | 写错 → 浏览器 404，登录"看起来成功但进不去" |
| `required_group` | `app-msia` | 准入校验 | 与 Keycloak 组名不一致 → **403 未开通** |
| `auto_create_user` | `true`（双轨期可先保持） | 本地没命中时自动建档 | 调试期建议临时改 `false`，否则拼错用户名会静默生成低权限账号 |
| `scopes` | `openid profile email` | 拿 `preferred_username` 等字段 | 少了 `openid` → 拿不到 `id_token` |

### 8.4 顺带确认两个 `[security]` 键（不是 `[oidc]`）

```ini
[security]
local_login_enabled = true
hr_sync_enabled = true
sso_user_sync_enabled = false
```

| 键 | 双轨期应为 | 说明 |
|---|---|---|
| `local_login_enabled` | `true` | 本地账密登录仍可用；改 `false` 后 `/api/auth/login` 返回 403 |
| `sso_user_sync_enabled` | `false` | 每日 06:30 从中央表派生同步；双轨期先关，P4 单轨再开 |

> `/api/auth/config` 只回 `oidc_enabled` 与 `local_login_enabled` 两个字段（已核实 `app/api/auth.py`），**不包含** `sso_user_sync_enabled`。别拿这个接口去验证同步开关。

✅ 做到这里你应该看到：`[oidc]` 里 `enabled=true`、`issuer` 与回显一致、`redirect_uri` 与白名单一致；保存后文件 `LastWriteTime` 是当前时间。

如果不对，最可能是：INI 里用了中文引号、行首多了空格、`[oidc]` 段被写到了别的段里面（`Get-Content` 看一遍段落边界）。

> **新手陷阱（真实踩过）**：`enabled` 从 `false` 改成 `true` 但**没重启 exe**。进程内的配置是启动时读的，改文件不会热加载。看到"还是 503"先看进程启动时间。

### 8.5 改完必须重启 exe

没有热加载。第 9 章就是重启流程，别跳过。

---

## 9. 启动 MSIA

### 9.1 停旧进程

你要做什么：先停干净，别出现"两个 exe 抢 8000 端口"。

```powershell
Get-Process -Name 'msia_server' -ErrorAction SilentlyContinue |
  Select-Object Id, StartTime, Path
Stop-Process -Name 'msia_server' -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-Process -Name 'msia_server' -ErrorAction SilentlyContinue
```

✅ 做到这里你应该看到：第二条没有输出（进程已停）。

如果不对，最可能是：它是 Windows 服务（不是先起进程）→ 先 `nssm stop <服务名>`（**需现场确认** MSIA 是否注册为服务）。

### 9.2 设 `SSL_CERT_FILE`（必须，且是"替换"不是"追加"）

你要做什么：让 exe 信任 8443 的自签证书。

```powershell
# 证书包路径按现场实际（<PEM包路径> 需现场确认，下文按 C:\sso\conf\ca-bundle.pem 写）
$env:SSL_CERT_FILE = 'C:\sso\conf\ca-bundle.pem'
Test-Path $env:SSL_CERT_FILE
```

✅ 做到这里你应该看到：`True`，且包里第一行是 `-----BEGIN CERTIFICATE-----`。

如果不对，最可能是：包不存在，或包里是旧的（旧证书没 SAN IP）→ 后面报 `self-signed certificate` / `IP address mismatch`。

> **新手陷阱（真实踩过）**：`SSL_CERT_FILE` 在 Python 里是**替换**整个默认根证书集合，不是追加。如果这个包只放了自签证书，而 MSIA 还要访问别家 HTTPS（比如外部 API），就会报 `unable to find valid certification path`。正确做法是把"自签证书 + 其它需要的 CA"都拼进同一个 PEM 包里。
>
> 另外：`$env:SSL_CERT_FILE` 只对**当前 PowerShell 会话**有效。用服务方式启动时，必须写进服务的环境变量（`nssm set <服务名> AppEnvironmentExtra "SSL_CERT_FILE=..."`），否则"我设了但没生效"。

### 9.3 启动

```powershell
$env:OIDC_CLIENT_SECRET = '<msia-prod 的 secret>'   # 需现场确认；不想用环境变量就写进 config.ini 的 client_secret
Set-Location 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server'
& '.\msia_server.exe'
```

✅ 做到这里你应该看到黑窗口里依次出现（`app/main.py` 的启动日志）：

```
MSIA 审核管理系统启动中...
应用就绪, 监听 0.0.0.0:8000
```

以及 OIDC 体检的一条 `INFO`（关闭态是"OIDC 未启用…"；开启且配置正常时不报 ERROR）。

如果不对，最可能是：`ERROR OIDC 配置体检失败: ...`（键名和当前值都在日志里，照它改）；或端口被占（`WinError 10048`）。

### 9.4 三条自检（缺一条都别去浏览器试登录）

**自检 1：路由在不在**

```powershell
$o = Invoke-RestMethod 'http://127.0.0.1:8000/openapi.json'
$o.paths.PSObject.Properties.Name | Select-String '/api/auth/'
```

✅ 应看到三条：`/api/auth/config`、`/api/auth/oidc/login`、`/api/auth/oidc/callback`。
若缺 → 你跑的不是 `20261105-1600` 那个包（旧包里可能没有这些路由）。

**自检 2：开关对不对**

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/auth/config' | ConvertTo-Json
```

✅ 应看到 `{"oidc_enabled": true, "local_login_enabled": true}`。
若 `oidc_enabled=false` → 你改的不是 exe 同级那份 `config.ini`，或者没重启。

**自检 3：入口可达（不要真登录）**

```powershell
$r = Invoke-WebRequest 'http://127.0.0.1:8000/api/auth/oidc/callback?code=x&state=y' -MaximumRedirection 0 -ErrorAction SilentlyContinue
"status=$($r.StatusCode)"
try { $r.Content | ConvertFrom-Json | ConvertTo-Json } catch { $r.Content }
```

✅ 应看到 **400** 且 detail 为 `登录状态无效，请重试`（`app/api/auth.py` 的 state 校验分支）。
- 看到 **503「统一登录未启用」** → `enabled` 还是 false 或没重启；
- 注意：**回调端点不会返回「OIDC 配置不完整」**（它只判断总开关）。想验证体检结果，直接打登录入口，不开浏览器也行：

```powershell
$r2 = Invoke-WebRequest 'http://127.0.0.1:8000/api/auth/oidc/login' -MaximumRedirection 0 -ErrorAction SilentlyContinue
"login status=$($r2.StatusCode)"   # 302 = 体检通过；503 = 体检没过（detail 里列键名）
```

> 说明：这里的 400 是**期望值**，它证明"回调路由活着且 OIDC 已启用"，不代表登录失败。

> **新手陷阱（真实踩过）**：`enabled=true` 之后直接去浏览器点登录，结果 503。原因是 `issuer` 主机与 `redirect_uri` 主机不一致（`app/core/oidc.py` 的 `validate_config` 会拦），或 `client_secret` 为空。第 1.4 步和第 8.3 步就是为这个准备的。

---

## 10. 端到端登录测试

### 10.1 走一遍（用**客户端**浏览器，不要用服务器上的浏览器）

1. 打开 `http://172.26.2.203:8078/login`
2. 页面上应出现"统一身份登录"按钮（来自 `/api/auth/config` 的 `oidc_enabled=true`）
3. 点它 → 浏览器跳到 `https://172.26.2.203:8443/realms/inalfa/protocol/openid-connect/auth?...`
4. Keycloak 登录页出现 → 输入 `ligu` + 密码
5. 首次登录若设了 `Temporary`，会要求改密 → 改完继续
6. 回跳 `http://172.26.2.203:8078/api/auth/oidc/callback?code=...&state=...`
7. 后端 302 到 `/oidc/callback?otk=...`
8. 前端用一次性码换本地 JWT → 进入系统

✅ 做到这里你应该看到：最终落在 MSIA 业务首页，左上角/用户区显示 `ligu` 或 `李国柱`，且不弹错。

如果不对，最可能是：看第 11 章对照表——每一步的失败现象不一样，别凭感觉改。

### 10.2 黑窗口里应该出现哪两行（已核实 `app/api/auth.py`）

成功链路必然有这两行，顺序出现：

```
OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)
OIDC 登录成功: ligu (local user id=<数字>)
```

- 只有第一行、没有第二行 → 卡在 Keycloak 侧或回调（看 11 章 400/403/invalid 类）；
- 第一行都没有 → 点的是本地登录，或者 `oidc_enabled` 还是 false；
- 第二行的 `<数字>` 是本地 `User.Id`——如果这个账号你"没印象"，很可能触发了自动建档（见 7.2 的陷阱）。

失败时还会出现（用于定位）：

```
OIDC 回调失败: <中文原因>
OIDC token 交换/验签失败
OIDC 身份解析异常
```

---

## 11. 失败对照表

| 现象 | 出现在哪一步 | 怎么查 | 改哪里 |
|---|---|---|---|
| **503「统一登录未启用」** | 点统一登录按钮，或回调 | 黑窗口启动日志；`/api/auth/config` 的 `oidc_enabled` | `config.ini` 的 `[oidc] enabled`；改完**重启 exe**；确认改的是 exe 同级那份 |
| **503「OIDC 配置不完整: …」** | 点统一登录按钮 | 黑窗口 `OIDC 配置体检失败:` 那一行会列出键名和当前值 | 按提示改：`client_secret` 为空 / `redirect_uri` 含 `127.0.0.1` / `issuer` 与 redirect 主机不一致 / `issuer` 不是 https |
| **400「登录状态无效，请重试」** | 回调 | 是否重启过 exe（内存态 state 会丢）；是否多开浏览器标签重复回调；是否超过 10 分钟 | 重新点一次登录；确认只有**单进程单 worker**（state 存内存，多 worker 会互相看不到） |
| **「未开通本系统访问权限，请联系管理员」**（表现为回跳前端后的红字提示，HTTP 上是 302，不是 403） | 回调后 | 黑窗口 `OIDC 回调失败: 未开通本系统访问权限…`；`Evaluate` 看 `groups` claim | 用户没加 `app-msia`；或 mapper `Full group path=ON`（值是 `/app-msia`）；或 `required_group` 与组名不一致 |
| **「账号已禁用, 请联系管理员」** | 回调后 | 同上，看黑窗口；再查 MSIA 本地 `User` 表的启用状态 | 停用状态在**本地表**里，不是 Keycloak 的 `Enabled`；`yaole` 就是这种情况 |
| **`invalid_user_credentials`** | Keycloak 登录页提交后 | Keycloak 控制台 `Users → 该用户 → Credentials` | 密码错；或用户 `Enabled=OFF`；或 `Temporary` 密码过期；`ligu` 是否被误建在别的 realm |
| **`Invalid parameter: redirect_uri`** | Keycloak 登录页，还没输入账号 | 比对 `config.ini` 的 `redirect_uri` 与 client 的 `Valid redirect URIs`（逐字符，含尾斜杠、端口、http/https） | 让两边完全一致；需要多个就多起一行，不要用 `*` |
| **`Client not found`** | 换 token 时（黑窗口 `token 交换失败`） | `& $KCADM get clients -r inalfa -q clientId=msia-prod --fields clientId,id` | client 名的尾部空格/大小写；`config.ini` 的 `client_id` 拼错；secret 属于另一个 client |
| **`IP address mismatch`** | MSIA 连 8443 时（discovery/换 token） | 第 1.3 步 `keytool -printcert` 看 SAN | 证书缺 `IP:172.26.2.203`；换证书后未重启 Keycloak；`SSL_CERT_FILE` 指向旧包 |
| **`self-signed certificate` / `certificate verify failed`** | 同上 | `$env:SSL_CERT_FILE` 是否设置、包内容是否为新证书 | 指对 PEM 包；服务方式启动要写进服务环境变量；包里要含新证书 |
| **页面空白 / 500** | 回跳后前端 | 浏览器 F12 看 `/api/auth/oidc/token` 的响应；黑窗口看 traceback | `front_callback` 写错；`cors_origins` 没含 `http://172.26.2.203:8078`；一次性码 60 秒过期（重新登录） |
| **登录页没有"统一身份登录"按钮** | 第 2 步 | `/api/auth/config` 返回值 | `oidc_enabled=false`（没改配置/没重启）；或前端缓存（强刷） |

---

## 12. 回滚

### 12.1 软回滚（30 秒，推荐先做这个）

```ini
[oidc]
enabled = false
```

改完**重启 exe**。效果：统一登录入口消失，`/api/auth/oidc/*` 返回 503，本地账密登录照常（`local_login_enabled=true`）。Keycloak 侧一个对象都不用动。

✅ 应看到 `/api/auth/config` 变成 `{"oidc_enabled": false, "local_login_enabled": true}`。

### 12.2 硬回滚（换目录）

```powershell
# 停进程 → 把 exe 目录整个换回旧构建（<旧目录> 需现场确认）
Stop-Process -Name 'msia_server' -Force -ErrorAction SilentlyContinue
Rename-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server' 'msia_server.bak-<日期>'
Copy-Item '<旧构建目录>' 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server' -Recurse
# 保留现场 config.ini（不要把构建机的配置带回来）
```

✅ 应看到旧 exe 的 `LastWriteTime` 与旧构建一致，且启动日志里没有 OIDC 相关路由。

### 12.3 三条必须知道的边界

1. **删 Keycloak 用户不算回滚。** 中央表里这个人还是 `status=1`，次日 06:00 的同步会按 `login_name` 把他**重新建回来**（脚本对失效的 `kc_user_id` 会回落按用户名查找，找不到就新建）。要真正停掉一个人，改中央表 + `disable_user_now.ps1`。
2. **Keycloak 用户与 MSIA 本地 `User` 表没有外键关系。** 删 KC 用户不会连带删本地账号；反过来删本地账号也不会删 KC 用户。所以"删错人"不会造成业务数据级联删除，但会留下两边不一致。
3. **自动建档的账号不会被自动清理。** 因拼错用户名触发的 `reviewee` 新账号会一直留在 `User` 表里，需要人工按名单核对后停用。

---

## 13. 附录 A：一次性变量块 + 常用只读查询

### 13.1 变量块（每次开新会话先跑）

```powershell
$KC     = 'C:\keycloak'
$KCADM  = "$KC\bin\kcadm.bat"
$Jdk    = '<JDK路径>'                 # 需现场确认
$IP     = '172.26.2.203'
$AppDir = 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server'
$AppUrl = 'http://172.26.2.203:8078'
```

### 13.2 只读查询（全部不改数据）

```powershell
# realm 概况
& $KCADM get realms/inalfa --fields realm,enabled,accessTokenLifespan,sslRequired

# client 概况（含 redirectUris / webOrigins / attributes=PKCE）
& $KCADM get clients -r inalfa -q clientId=msia-prod `
  --fields id,clientId,enabled,publicClient,standardFlowEnabled,directAccessGrantsEnabled,redirectUris,webOrigins,attributes

# 组（看 path 是不是 /app-msia）
& $KCADM get groups -r inalfa --fields id,name,path

# 用户
& $KCADM get users -r inalfa -q username=ligu --fields id,username,enabled,email

# 用户属于哪些组
$Uid = (& $KCADM get users -r inalfa -q username=ligu --fields id).id
& $KCADM get "users/$Uid/groups" -r inalfa --fields id,name,path

# 某个组的成员
$Gid = (& $KCADM get groups -r inalfa --fields id,name | Out-String)  # 先看 id
& $KCADM get "groups/<组id>/members" -r inalfa --fields id,username

# mapper 列表（若 kcadm 报 404，改用控制台 Clients → msia-prod → Mappers 查看）
$Cid = (& $KCADM get clients -r inalfa -q clientId=msia-prod --fields id).id
& $KCADM get "clients/$Cid/protocol-mappers/models" -r inalfa --fields name,protocol,protocolMapper,config

# 取 client secret —— 别贴到聊天/工单/文档里
& $KCADM get "clients/$Cid/client-secret" -r inalfa --fields value
```

> `kcadm get "..."` 这类子路径是"透传给 Admin REST"，不同小版本可能返回 404；返回 404 时以控制台为准，不要以为是权限问题。

### 13.3 MSIA 侧只读自检

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/auth/config' | ConvertTo-Json
(Invoke-RestMethod 'http://127.0.0.1:8000/openapi.json').paths.PSObject.Properties.Name |
  Select-String '/api/auth/'
Get-Item "$AppDir\config.ini" | Select-Object LastWriteTime
(Get-Process msia_server).StartTime
```

---

## 14. 附录 B：与本项目其他文档的索引

| 文档 | 用来干什么 |
|---|---|
| `docs/keycloak-deploy-runbook.md` | Keycloak 安装 / JDK / NSSM / 数据库 / 首次启动（本文默认这些已完成） |
| `docs/keycloak-realm-clients-init.md` | 本文第 3–6 章的**命令行等价写法**与字段取值依据（`kcadm` 批量复现用） |
| `docs/keycloak-console-setup-for-beginners.md` | 第 3–6 章的**纯界面版**（不含 MSIA 侧） |
| `keycloak/clients.md` | `msia-prod` / `bol-prod` / `sync-client` 的字段台账与来源 |
| `keycloak/realm-setup.md` | realm 各策略的语义说明（SMTP、密码策略、事件） |
| `docs/msia-redeploy-checklist.md` | MSIA 打包、部署、`SSL_CERT_FILE`、issuer 口径、回调分状态判据 |
| `docs/app-certificate-trust.md` | `SSL_CERT_FILE` 的原理（替换而非追加）、NSSM 注入方式 |
| `docs/cert-request-guide.md` | 企业证书申请（8443 自签可继续用，443 走 ARR） |
| `scripts/sql/03_seed_users.sql` | 中央表 13 人种子（本文第 7 章选人的依据） |
| `scripts/powershell/sync_sso_to_keycloak.ps1` | 批量灌 Keycloak 用户（注意：**不分配组**） |

---

## 附录 C：时间预估与最短路径清单

### C.1 分段计时（第一次做）

| 段 | 内容 | 预估 |
|---|---|---|
| 第 1 章 | 5 项确认（含证书核对） | 10–15 分钟 |
| 第 2–3 章 | 登录控制台 + realm 六屏核对 | 15–20 分钟 |
| 第 4 章 | 建组 | 2 分钟 |
| 第 5 章 | client + secret | 10 分钟 |
| 第 6 章 | mapper + Evaluate 验证 | 5–10 分钟 |
| 第 7 章 | 测试用户 + 加组 + 设密 | 5 分钟 |
| 第 8 章 | 改 `config.ini` | 5–10 分钟 |
| 第 9 章 | 启动 + 三条自检 | 5–10 分钟 |
| 第 10 章 | 端到端登录 | 5–10 分钟 |
| **合计** | | **约 60–90 分钟**（顺利）/ **2 小时**（遇 403 或证书问题） |

熟手复现（对象已存在、只改配置与重启）：**20–30 分钟**。

### C.2 最短路径清单（逐项打勾）

- [ ] `Get-CimInstance Win32_Service -Filter "Name='Keycloak'"` → Running
- [ ] 8443、9000 都在 Listen
- [ ] `keytool -printcert` 里 SAN 有 `IP:172.26.2.203`
- [ ] discovery 的 `issuer` 已记下（与 redirect 同主机）
- [ ] `kcadm` 能登录 master
- [ ] realm `inalfa` 启用、`User Registration=OFF`
- [ ] 组 `app-msia` 是顶层（`path=/app-msia`）
- [ ] client `msia-prod`：`Client authentication=ON`、`Standard flow=ON`、`Direct grants=OFF`
- [ ] `Valid redirect URIs` 精确等于 `http://172.26.2.203:8078/api/auth/oidc/callback`
- [ ] `Web origins` = `http://172.26.2.203:8078`
- [ ] PKCE = `S256`
- [ ] mapper `groups` 存在、`Full group path=OFF`、`Add to ID token=ON`
- [ ] 测试用户 `ligu`（小写）Enabled、密码已设、已加入 `app-msia`
- [ ] `config.ini`：`enabled=true`、`issuer` 抄回显、`client_id=msia-prod`、`redirect_uri` 一致、`required_group=app-msia`
- [ ] `client_secret` 已填或 `OIDC_CLIENT_SECRET` 已注入
- [ ] exe 已重启（`StartTime` 晚于 `config.ini` 的 `LastWriteTime`）
- [ ] `SSL_CERT_FILE` 指向含新证书的 PEM 包
- [ ] `/api/auth/config` → `{"oidc_enabled": true, ...}`
- [ ] 回调探测返回 400「登录状态无效」
- [ ] 浏览器登录成功，黑窗口出现 `OIDC 登录成功: ligu (local user id=…)`
