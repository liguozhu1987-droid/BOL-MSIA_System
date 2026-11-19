# Keycloak 25.0.6 + BOL 统一身份认证：现场部署操作手册（零基础版）

> **这份文档怎么定位**
> - 与 `docs/keycloak-msia-sso-guide-for-beginners.md` **并列使用**，章节编号一一对应，方便两边对照着做。
> - 本文只讲 **BOL 侧**（Keycloak 侧的 realm / 组 / mapper 概念在 MSIA 手册里已解释过，这里只给"点哪里、填什么"）。
> - 用户体系走**方案 A**：保留现有 `Employee` 表结构，只做 SSO 适配（自动建档时 `role=VIEWER`）。本文**不涉及**重建用户体系。
>
> **本文对应的现场状态（写稿时已核对代码）**
> | 项 | 值 | 依据 |
> |---|---|---|
> | Keycloak | 25.0.6，`172.26.2.203:8443`，realm `inalfa` | 现场既定 |
> | BOL 登录入口页 | `http://172.26.2.203:8090/actual-ct` | 现场既定（前端路由） |
> | BOL 后端 | Django + waitress，默认 `0.0.0.0:8090` | `run_server.py:12` |
> | 生产 settings | `bol_platform.settings_prod`（继承 `settings.py`，`DEBUG=False`） | `run_server.py:68`、`settings_prod.py:19,24` |
> | client | `bol-prod` | `db_config.ini:57`、`settings.py:318` |
> | 准入组 | `app-bol` | `db_config.ini:72` |
> | 回调路由 | `/api/auth/oidc/callback/`（**带尾斜杠**） | `apps/users/auth_urls.py` |
> | 现有 redirect_uri 占位 | `http://127.0.0.1:8090/api/auth/oidc/callback`（**无尾斜杠，且是回环地址**） | `db_config.ini:66`、`settings.py:322` |
> | OIDC 总开关 | 当前 `enabled=False` | `db_config.ini:51` |
> | 双轨开关 | `local_auth_enabled=True` | `db_config.ini:29` |
>
> **本文不编造**：secret 值、`kcadmin` 口令、BOL 部署目录、服务名、JDK 路径、8078/8090 反代细节。凡此一律 "**需现场确认**"。

---

## 0. 怎么用这份手册 + 和 MSIA 的差异

### 0.1 操作顺序（不能反）

1. **确认现状**（第 1 章）：服务在跑、端口通、证书有 IP SAN、入口页能开。
2. **Keycloak 侧**（第 2 章）：`bol-prod` → `app-bol` → mapper → 测试用户。
3. **BOL 配置**（第 3 章）：改 `redirect_uri`（这一步最容易出错，见 2.2）→ 开 `enabled` → 重启。
4. **启动自检**（第 4 章）：四条自检全过，再进浏览器。
5. **端到端**（第 5 章）。

先改 BOL 再去 Keycloak 建 client，你会在浏览器里看到 `Client not found` / `Invalid parameter: redirect_uri`，分不清是谁的问题。

### 0.2 BOL 与 MSIA 的三处关键差异（别互相照抄）

| 项 | MSIA | BOL |
|---|---|---|
| 回调地址 | `.../api/auth/oidc/callback`（**无**尾斜杠） | `.../api/auth/oidc/callback/`（**有**尾斜杠，见 2.2） |
| 入口 | `http://172.26.2.203:8078/login` | `http://172.26.2.203:8090/actual-ct` |
| 配置体检时机 | 启动时打一条 INFO + 登录时校验 | **只在点"统一登录"时校验**（`oidc_views.py:201-202`），启动日志里没有 OIDC 体检行 |
| 403 类错误呈现 | 302 到前端带 `?error=` | 同样 302 带 `?error=`（`_redirect_error`） |

> 因 BOL 没有启动期体检，**不要**用"启动日志里没有 OIDC 行"判断配置坏了。要判断就点一次登录按钮（第 4.5 节）。

### 0.3 术语

不熟的话先翻 `keycloak-msia-sso-guide-for-beginners.md` 的 0.2 术语表（realm / client / secret / mapper / PKCE / issuer / redirect URI）。这里只强调一个：**redirect_uri 不是登录入口页**，见 2.2。

---

## 1. 开工前 7 项确认（任一项不过就停）

### 1.1 BOL 进程在不在

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'BOLServer|python' } |
  Select-Object ProcessId, Name, CreationDate, ExecutablePath
```

✅ 应看到至少一条（打包版是 `BOLServer.exe`，源码版是 `python.exe`），且 `ExecutablePath` 指向 BOL 部署目录。

如果不对，最可能是：服务根本没起。**先起服务，再谈 OIDC**——服务停了去猜证书，会浪费半天。

### 1.2 8090 在监听

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8090 |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

✅ 应看到 `LocalPort=8090`，`OwningProcess` 与 1.1 的 PID 相同。

如果不对：端口被占（同一台机上起了两个实例）或进程崩了（看控制台窗口最后 20 行）。

### 1.3 入口页能打开（这是**入口页**，不是回调）

```powershell
$r = Invoke-WebRequest 'http://172.26.2.203:8090/actual-ct' -UseBasicParsing
"status=$($r.StatusCode) length=$($r.RawContentLength)"
```

✅ 应看到 `status=200`，返回的是前端 `index.html`（`<div id="app">` 之类）。

如果不对：`404` → `settings_prod.FRONTEND_INDEX` 没找到 `index.html`（`frontend/dist` 或 `staticfiles` 缺失）；`502/连不上` → 反代问题（**需现场确认** 8090 是否直连）。

### 1.4 证书 SAN 里有 IP

```powershell
$KC = 'C:\keycloak'
& '<JDK路径>\bin\keytool.exe' -printcert -file "$KC\conf\server.crt.pem"
```

✅ 必须看到 `SubjectAlternativeName: [ IP:172.26.2.203, DNS:localhost, DNS:sso.ap.inalfa.local ]`。

如果不对：缺 `IP:` → BOL 一定报 `IP address mismatch`，**停下，先修证书**。

### 1.5 issuer 回显（决定第 3 章填什么）

```powershell
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$d = Invoke-RestMethod 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration'
$d.issuer
[Net.ServicePointManager]::ServerCertificateValidationCallback = $null
```

✅ 应输出一个 `https://.../realms/inalfa` 的字符串。**原样记下**。

> **关键判断**：BOL 的配置体检要求 `issuer` 主机与 `redirect_uri` 主机**一致**（`apps/users/oidc.py` 的 `validate_config`）。BOL 的 redirect 主机是 `172.26.2.203`，所以 issuer 必须是 IP 口径。如果回显是 `sso.ap.inalfa.local`，**停下**：要么让 Keycloak 的回显变成 IP，要么改 BOL 的访问地址——**现场决策，需现场确认**。

### 1.6 数据库迁移已应用

```powershell
cd '<BOL后端目录>'      # 需现场确认（打包版没有源码时跳过本节，见 4.1）
python manage.py showmigrations users
```

✅ 应看到 `0005_authtoken_source`、`0006_alter_employee_options_alter_employee_role` 前面都是 `[X]`。

如果不对：有 `[ ]` → 先 `python manage.py migrate users`，并确认连的是 **CMC 生产库**，不是测试库。

### 1.7 基线：本地登录还能用（改之前先证明）

用浏览器打开 `http://172.26.2.203:8090/actual-ct`，用现有本地账号（如 `ligu` / `chenca`）登录一次。

✅ 应能正常进系统，拿到登录态。

这条是**基线**：改完后如果统一登录失败，你可以立刻用本地登录证明"业务没被弄坏"——`local_auth_enabled=True` 就是为这个留的退路。

---

## 2. Keycloak 控制台侧

> 登录控制台的步骤（含自签证书警告怎么点）见 MSIA 手册第 2 章，这里不重复。

### 2.1 `bol-prod` 的创建或订正

左侧 `Clients` → 列表里若有 `bol-prod` 就点进去核对，没有就 `Create client`。

| 字段（按名字找） | 值 | 填错的后果 |
|---|---|---|
| `Client ID` | `bol-prod` | 与 `db_config.ini` 的 `client_id` 不一致 → `Client not found` |
| `Name` | `BOL 管理分析平台` | 仅展示 |
| `Enabled` | ON | 关掉 → `invalid_client` |
| `Client authentication` | **ON** | 关掉拿不到 secret，换 token 报 `invalid_client` |
| `Standard flow` | **ON** | 关掉 → 授权码流不可用 |
| `Implicit flow` | OFF | 不安全 |
| `Direct access grants` | **OFF** | 开了等于允许账密直取令牌，绕过 SSO |
| `Service accounts roles` | OFF | 业务 client 不需要 |
| `Root URL` | `http://172.26.2.203:8090` | 只影响控制台展示，但建议填对 |
| `Valid redirect URIs` | **见 2.2**，必须逐字符一致 | 差一个字符 → `Invalid parameter: redirect_uri` |
| `Web Origins` | `http://172.26.2.203:8090` | 漏填可能触发跨域报错（前端页面空白） |
| `PKCE Code Challenge Method`（Advanced） | `S256` | 缺失 → `Missing parameter: code_challenge_method` |

> **新手陷阱（真实踩过）**：`Client ID` 粘贴时带了尾部空格，列表里看着一模一样，但报 `Client not found`。用下面这条确认：

```powershell
$KCADM = 'C:\keycloak\bin\kcadm.bat'
& $KCADM get clients -r inalfa -q clientId=bol-prod --fields clientId,id
```

✅ 应返回一条 `"clientId" : "bol-prod"`。返回空数组 → 名字里有不可见字符，删了重建。

### 2.2 【重点】`redirect_uri` 到底是哪个地址

**先把三个概念分开，不要混：**

| 名字 | 实际值 | 干什么用的 |
|---|---|---|
| **登录入口页** | `http://172.26.2.203:8090/actual-ct` | 用户在浏览器里打开、点"统一登录"按钮的那个页面 |
| **OIDC 回调地址（redirect_uri）** | `http://172.26.2.203:8090/api/auth/oidc/callback/` | 用户在 Keycloak 登录成功后，Keycloak 把浏览器**送回后端**的地址 |
| **前端回调页（front_callback）** | `/oidc/callback` | 后端换到一次性码后，再 302 到前端的承接页 |

**为什么不能混用**：`redirect_uri` 是 OAuth 协议里"授权码送到哪里"的严格登记项，Keycloak 会**逐字符**比对；入口页 `/actual-ct` 是前端路由，它不处理 `?code=`，Keycloak 也从未把它登记为合法回调。把入口页填进 `redirect_uri`，结果是登录成功后浏览器落到一个没有后端处理逻辑的页面，或者直接被 Keycloak 拒绝。

**代码核实结果（写稿时读过，不是推测）：**

- 授权请求里的 `redirect_uri` 取的是 `settings.OIDC_REDIRECT_URI` **原值**，不做任何拼接：
  `apps/users/oidc.py:147` → `"redirect_uri": settings.OIDC_REDIRECT_URI`
- 换 token 时用的也是同一个原值：`apps/users/oidc.py:162`
- 回调路由声明为带尾斜杠：`apps/users/auth_urls.py` → `path('oidc/callback/', ...)`，挂在 `api/auth/` 下，所以完整路径是 `/api/auth/oidc/callback/`
- **Django 不会替你补尾斜杠到 `redirect_uri` 参数上**：`APPEND_SLASH` 只对"浏览器发进来的请求路径"生效，不会改写你发给 Keycloak 的字符串。
- 默认/占位值是回环地址且无尾斜杠：`db_config.ini:66` = `http://127.0.0.1:8090/api/auth/oidc/callback`

**结论（这两个字符串必须完全一样）：**

```
http://172.26.2.203:8090/api/auth/oidc/callback/
```

- Keycloak → `Clients → bol-prod → Valid redirect URIs`，这一行就是这个字符串（**末尾的 `/` 不能省**）。
- BOL → `db_config.ini` 的 `[oidc] redirect_uri`，也必须改成这个字符串（第 3 章会给完整块）。

> 如果确实还有别的前端地址要兼容（例如以后上域名），**另起一行加一条**，不要在一条里写 `*` 或 `...;...`。

**现场自查（改完必做一次，别靠肉眼比对）：**

1. 浏览器打开入口页，点"统一登录"。
2. 页面跳到 `https://172.26.2.203:8443/realms/inalfa/protocol/openid-connect/auth?...` 后，**在地址栏里找 `redirect_uri=`**。
3. 复制它，用下面这条解码比对（`%3A`=`:`、`%2F`=`/`）：

```powershell
$url = '<把地址栏整条粘进来>'
$q = [System.Web.HttpUtility]::ParseQueryString(([Uri]$url).Query)
$q['redirect_uri']
```

✅ 输出的字符串必须与 Keycloak 里那行**一模一样**（含尾斜杠）。不一致就是后面 `Invalid parameter: redirect_uri` 的根因。

> 若输出的是 `http://127.0.0.1:8090/api/auth/oidc/callback`，说明**配置还没改或没重启**（占位值原样带出来了）——回第 3 章。

**填错的报错与排查顺序**：见第 6 章第一行（`Invalid parameter: redirect_uri`）。顺序固定：① 解码出实际值 → ② 比对 Keycloak 白名单 → ③ 比对 `db_config.ini` → ④ 确认进程重启过。

### 2.3 组 `app-bol`

左侧 `Groups` → `Create group` → `Name` = `app-bol` → `Create`。

```powershell
& $KCADM get groups -r inalfa --fields id,name,path
```

✅ 应看到 `"name" : "app-bol", "path" : "/app-bol"`（前面的 `/` 说明是顶层）。

如果不对：建成了子组 → `path` 变成 `/xxx/app-bol` → 令牌里是 `/app-bol`，BOL 的 `settings.OIDC_REQUIRED_GROUP not in groups` 判断失败 → `?error=未开通本系统访问权限，请联系管理员`（`oidc_views.py:105-110`）。

### 2.4 groups mapper

`Clients → bol-prod → Mappers → Add mapper → By protocol → Group membership`：

| 字段 | 值 |
|---|---|
| `Name` | `groups` |
| `Token Claim Name` | `groups` |
| `Full group path` | **OFF** |
| `Add to ID token` | **ON**（BOL 验的是 id_token） |
| `Add to access token` | ON（建议） |

找不到 `Mappers` 页签时：`Clients → bol-prod → Client scopes → bol-prod-dedicated → Mappers → Add mapper → By protocol`。

✅ 列表里有一条 `groups`，`Full group path` 为 OFF。用 `Evaluate`（2.6）验证实际值是 `["app-bol"]`（不带斜杠）。

### 2.5 测试用户（选人很关键）

BOL 本地用户名与中央 `login_name` **不完全一致**，选错人会走到"自动建档"，你就测不出真实角色。

| 用户 | BOL 本地用户名 | 是否适合首测 | 说明 |
|---|---|---|---|
| `ligu` | `ligu` | ✅ 最合适 | BOL 本地 admin，名字一致 |
| `chenca` | `chenca` | ✅ 可用 | BOL 独有账号 |
| `libi2` | `libi2` | ✅ 可用 | BOL 独有账号 |
| `yaole` | `Yaolei` | ❌ 不要首测 | 需要 UserMap 映射；没有映射会新建 `VIEWER` |
| `zhangya4` | `ZhangY4` | ❌ 不要首测 | 同上 |

建用户（`Users → Add user`）：

| 字段 | 值 |
|---|---|
| `Username` | `ligu`（**必须等于中央表 `login_name` 的小写**，不是邮箱、不是 `Ligu`） |
| `Email` | `Guozhu.Li@inalfa.com`（可空） |
| `Enabled` | ON |

然后 `Credentials → Set password`，`Temporary` 建议 **ON**（首登强制改密）。

再加组：`Users → ligu → Groups → Join Group → app-bol`。

```powershell
$Uid = (& $KCADM get users -r inalfa -q username=ligu --fields id).id
& $KCADM get "users/$Uid/groups" -r inalfa --fields id,name,path
```

✅ 返回里有 `app-bol`。

> **新手陷阱（真实踩过）**：用户名写成 `Yaolei` 或邮箱，BOL 解析不到本地账号 → `auto_create_user=True` 静默建档 `VIEWER`（`oidc_views.py:150-159`），你原来 admin 的角色就"没了"，还多出一条脏数据。

### 2.6 用 Evaluate 验证 claim

`Clients → bol-prod → Client scopes → Evaluate`（或 `Client scopes` 页的 `Evaluate`）：

- `User` 选 `ligu`
- 生成 token
- 找 `groups`

✅ 必须是 `["app-bol"]`。

如果不对：用户没加组，或 `Full group path` 是 ON。

---

## 3. BOL 配置侧

### 3.1 配置文件在哪（三个候选，先定位再改）

| 运行方式 | 读取的 `db_config.ini` 位置 | 依据 |
|---|---|---|
| 打包版（`BOLServer.exe`） | **exe 同目录** | `settings.py:396-397` |
| 源码版（`python run_server.py`） | `backend\db_config.ini` | `settings.py:399` |
| 任意 | 环境变量 `BOL_DB_CONFIG` 指定的路径（优先级最高） | `settings.py:400-402` |

```powershell
# 打包版：把 <BOL部署目录> 换成实际目录（需现场确认）
Get-Item '<BOL部署目录>\db_config.ini' | Select-Object FullName, LastWriteTime
```

✅ `FullName` 就是进程实际会读的那份。改别的副本（比如源码仓库里的）对线上没有任何作用。

> **新手陷阱（真实踩过）**：改了仓库里的 `backend\db_config.ini`，重启 exe 毫无变化。先确认 3.1 这条路径。

### 3.2 键名映射与优先级（改之前先看懂它怎么生效）

**优先级：环境变量 > `db_config.ini` > 代码默认值**（`settings.py:303-304, 385`）。

| `db_config.ini` 的键（`[oidc]` 段） | 落到的 settings 常量 | 环境变量名 |
|---|---|---|
| `enabled` | `OIDC_ENABLED` | `OIDC_ENABLED` |
| `issuer` | `OIDC_ISSUER` | `OIDC_ISSUER` |
| `client_id` | `OIDC_CLIENT_ID` | `OIDC_CLIENT_ID` |
| `client_secret` | `OIDC_CLIENT_SECRET` | `OIDC_CLIENT_SECRET` |
| `redirect_uri` | `OIDC_REDIRECT_URI` | `OIDC_REDIRECT_URI` |
| `front_callback` | `OIDC_FRONT_CALLBACK` | `OIDC_FRONT_CALLBACK` |
| `required_group` | `OIDC_REQUIRED_GROUP` | `OIDC_REQUIRED_GROUP` |
| `auto_create_user` | `OIDC_AUTO_CREATE_USER` | `OIDC_AUTO_CREATE_USER` |
| `scopes` | `OIDC_SCOPES` | `OIDC_SCOPES` |
| `[auth] cors_allowed_origins` | `CORS_ALLOWED_ORIGINS` | `CORS_ALLOWED_ORIGINS` |

映射关系在 `settings.py:331-341`（`_OIDC_KEY_MAP`）与 `settings.py:346-356`（`_AUTH_ENV_MAP`）。

> **环境变量的三个"不生效"规则**（`settings.py:363-374`）：值为空 → 忽略；`oidc_enabled` / `oidc_auto_create_user` 只认 `true/1/yes/on/false/0/no/off`，写 `True `（带空格）会被 trim 后接受，但写 `enabled=是` 会被忽略并打印一条 `[settings][警告]`。

### 3.3 完整的 `[oidc]` 块（照这块替换）

```ini
[oidc]
; 是否启用统一身份登录
enabled = True

; 第 1.5 步回显的 issuer（必须是 IP 口径，与 redirect_uri 主机一致）
issuer = https://172.26.2.203:8443/realms/inalfa

; 与 Keycloak client 对应
client_id = bol-prod

; 留空，改用环境变量 OIDC_CLIENT_SECRET 注入（不落盘）
client_secret =

; 【重点】回调地址：必须带尾斜杠，必须与 Keycloak Valid redirect URIs 一致
redirect_uri = http://172.26.2.203:8090/api/auth/oidc/callback/

; 前端承接一次性码的页面
front_callback = /oidc/callback

; 准入组
required_group = app-bol

; 本地未命中时是否自动建档（True = 建 VIEWER）
auto_create_user = True

; 授权范围
scopes = openid profile email
```

逐项说明：

| 键 | 填什么 | 为什么 | 填错会怎样 |
|---|---|---|---|
| `enabled` | `True` | 打开统一登录 | 保持 `False` → 点按钮 503「统一登录未启用」（`oidc_views.py:203-204`） |
| `issuer` | IP 口径 | 校验 id_token 的 `iss`，也是拼授权地址的基址 | 与回显不一致 → 验签失败；与 redirect 主机不一致 → 503「OIDC 配置不完整」 |
| `client_id` | `bol-prod` | 对应 Keycloak client | 尾部空格/大小写 → `Client not found` |
| `client_secret` | 空 + 环境变量 | 不落盘 | 空且未注入 → 503 配置不完整（secret 为空是体检项之一） |
| `redirect_uri` | `.../callback/`（**带 `/`**） | 与白名单逐字符比对 | 无尾斜杠/仍是 `127.0.0.1` → 503 或 `Invalid parameter: redirect_uri` |
| `front_callback` | `/oidc/callback` | 后端 302 到前端承接页 | 写错 → 回跳后 404 |
| `required_group` | `app-bol` | 与令牌 `groups` 比对 | 不一致 → 未开通 |
| `auto_create_user` | `True`（联调可临时 `False`） | 未命中即建档 VIEWER | 调试期建议 `False`，避免拼错用户名产生脏账号 |
| `scopes` | `openid profile email` | 拿 `id_token` 与 `preferred_username` | 少 `openid` → 没有 `id_token` |

### 3.4 `[auth]` 段（双轨期必须确认的三个键）

```ini
[auth]
self_registration_enabled = False
local_auth_enabled = True
password_self_service_enabled = True
sso_status_sync_enabled = True
```

| 键 | 双轨期 | 说明 |
|---|---|---|
| `local_auth_enabled` | `True` | **回滚退路**。改 `False` 后本地账密登录 403 |
| `self_registration_enabled` | `False` | 统一身份期间不开放自助注册 |
| `sso_status_sync_enabled` | `True` | 每小时从中央表回写 `Employee.status`（只同步状态，不动用户主数据） |

CORS（可选）：`[auth]` 里 `cors_allowed_origins` 留空 = 允许全部；正式环境建议写 `http://172.26.2.203:8090`。

### 3.5 为什么必须重启进程（不能热加载）

`settings.py` 的 `_AUTH_DEFAULTS`、`_load_auth_config()`、`_apply_env_overrides()` 都是**模块级**执行的，Django 进程一旦起来，这些常量就定格了；`OIDC_ENABLED` / `OIDC_REDIRECT_URI` 是 import 时读进内存的。

所以：**改完 `db_config.ini` 或改环境变量，必须重启 BOL 进程**。判断是否真的重启过：

```powershell
(Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'BOLServer|python' }).CreationDate
Get-Item '<BOL部署目录>\db_config.ini' | Select-Object LastWriteTime
```

✅ 进程 `CreationDate` **晚于** 配置文件的 `LastWriteTime`。

> **新手陷阱（真实踩过）**：改完 `enabled=True` 没重启，点登录一直 503，然后开始怀疑证书。先看进程启动时间。

---

## 4. 迁移、启动与自检

### 4.1 数据库迁移

打包版通常已带迁移文件但**不会自动执行**（取决于部署方式，**需现场确认**）。源码版执行：

```powershell
cd '<BOL后端目录>'
python manage.py migrate users
python manage.py showmigrations users
```

✅ 能看到 `0005_authtoken_source`、`0006_alter_employee_options_alter_employee_role` 都是 `[X]`。

`0005` 给 `AuthToken` 加了 `source` 字段（OIDC 登录写 `source='oidc'`）；`0006` 只调整 `Employee` 的 `role` 选项（新增 `VIEWER`/`GUEST`）与排序。**没应用**的话 OIDC 登录写 token 会报列不存在。

### 4.2 停旧进程

```powershell
Get-Process -Name 'BOLServer','python' -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like '*BOL*' } |
  Select-Object Id, StartTime, Path
Stop-Process -Name 'BOLServer' -Force -ErrorAction SilentlyContinue
# 源码版：确认没有残留 python 进程占用 8090
Start-Sleep -Seconds 2
Get-NetTCPConnection -State Listen -LocalPort 8090 -ErrorAction SilentlyContinue
```

✅ 第二条没有输出（8090 已释放）。若 BOL 注册成了 Windows 服务，用 `nssm stop <服务名>`（**需现场确认**服务名）。

### 4.3 设 `SSL_CERT_FILE`

```powershell
$env:SSL_CERT_FILE = 'C:\sso\conf\ca-bundle.pem'   # 路径需现场确认
Test-Path $env:SSL_CERT_FILE
Get-Content $env:SSL_CERT_FILE -TotalCount 1
```

✅ `True`，且第一行是 `-----BEGIN CERTIFICATE-----`。

BOL 的 HTTP 走 `urllib.request.urlopen`（`oidc.py:86,103`），不传自定义 context，因此用的是默认 SSL context——**会读 `SSL_CERT_FILE`**。所以这个变量对 BOL 有效。

> **陷阱**：`SSL_CERT_FILE` 是**替换**默认根集合，不是追加。包里的内容必须覆盖 BOL 还需要访问的其它 HTTPS 目标；只放自签证书时，别的 HTTPS 调用会 `unable to find valid certification path`。
> 用服务方式启动时必须写进服务环境变量（`nssm set <服务名> AppEnvironmentExtra "SSL_CERT_FILE=..."`），PowerShell 里 `$env:` 只对当前会话有效。

### 4.4 启动

```powershell
$env:OIDC_CLIENT_SECRET = '<bol-prod 的 secret>'   # 需现场确认；只在本机会话里用，别贴聊天
cd '<BOL部署目录>'
# 源码版：
python run_server.py
# 打包版：
.\BOLServer.exe
```

✅ 控制台出现 waitress 监听信息（`Serving on http://0.0.0.0:8090`）。

如果不对：`WinError 10048` → 8090 还被占；`ImproperlyConfigured` → `DB_CONFIG` 路径不对（exe 同目录没有 `db_config.ini`）。

### 4.5 四条自检（判断"防御代码真的生效"）

**自检 1：开关状态**

```powershell
Invoke-RestMethod 'http://127.0.0.1:8090/api/auth/config/' | ConvertTo-Json
```

✅ 应返回四个布尔字段：`oidc_enabled`、`local_auth_enabled`、`self_registration_enabled`、`password_self_service_enabled`（`oidc_views.py` 的 `AuthConfigView`，只读这四个，不含其他信息）。其中 `oidc_enabled` 必须是 `true`。

若 `oidc_enabled=false` → 改的不是进程读的那份配置，或没重启。

**自检 2：回调路由存在且关闭态拦截**

```powershell
$r = Invoke-WebRequest 'http://127.0.0.1:8090/api/auth/oidc/callback/' -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
"status=$($r.StatusCode) body=$($r.Content)"
```

✅ `enabled=True` 时应是 **400**，body 含「登录状态无效」；`enabled=False` 时是 **503**，body `统一登录未启用`。

- 404 → 路由没挂（不是 `20261105` 之后的防御版代码，或 url 前缀不对）；
- 503 且你已设 `enabled=True` → 没重启。

**自检 3：配置体检真的会拦（不点浏览器）**

```powershell
$r3 = Invoke-WebRequest 'http://127.0.0.1:8090/api/auth/oidc/login/' -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
"status=$($r3.StatusCode)"
if ($r3.StatusCode -eq 503) { $r3.Content }
```

✅ 配置正确时是 **302**（Location 指向 `https://172.26.2.203:8443/realms/inalfa/...`）；配置有问题时是 **503**，body 形如：

```
OIDC 配置不完整: <问题1>；<问题2>
```

（`oidc_views.py:206-209`；问题文本来自 `oidc.py` 的 `validate_config`。）

若 503 且提到 `redirect_uri 仍含 127.0.0.1/localhost` → 你还没改 2.2 那个值。

**自检 4：解码实际 redirect_uri（与白名单比对）**

直接看自检 3 的 `Location`，或浏览器地址栏，按 2.2 的命令解出 `redirect_uri`：

✅ 必须是 `http://172.26.2.203:8090/api/auth/oidc/callback/`（带尾斜杠、非回环地址）。

---

## 5. 端到端登录测试

1. 客户端浏览器打开 `http://172.26.2.203:8090/actual-ct`
2. 点"统一登录"按钮
3. 跳到 `https://172.26.2.203:8443/realms/inalfa/protocol/openid-connect/auth?...`
   - 自签证书会拦一次 → `Advanced` → `Proceed`
4. 输入 `ligu` + 密码；`Temporary` 开启时会要求改密
5. 回跳 `http://172.26.2.203:8090/api/auth/oidc/callback/?code=...&state=...`
6. 后端 302 到 `/oidc/callback?otk=...`
7. 前端用 otk 换本地登录态 → 进入 `/actual-ct`

✅ 最终落在业务页，用户区显示 `ligu`/李国柱；控制台（黑窗口）出现：

```
OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)
OIDC 身份解析: ligu 无 UserMap 映射, 回落 preferred_username
OIDC 登录成功: ligu (employee id=<数字>)
```

（第二行是 `oidc_views.py:123` 的常规日志；有映射时是"命中 UserMap 映射 -> 本地用户名 xxx"。）

- 只有第一行，没有第三行 → 卡在 token 交换/验签/身份解析，看第 6 章；
- 出现 `OIDC 自动建档: xxx (role=VIEWER, source=oidc)` → 你的用户名与本地账号没对上（见 2.5 陷阱），去 `Employee` 表核对是否多了一条。

---

## 6. 失败对照表

| 现象 | 出现在哪一步 | 怎么查 | 改哪里 |
|---|---|---|---|
| `Invalid parameter: redirect_uri` | Keycloak 登录页，还没输账号 | 按 2.2 解码地址栏的 `redirect_uri`；比对 Keycloak 白名单 | 三处对齐：`db_config.ini redirect_uri`、Keycloak `Valid redirect URIs`、**进程重启**。常见是漏尾斜杠或仍是 `127.0.0.1` |
| `Client not found` | 换 token（黑窗口 `OIDC token 交换/验签失败`） | `kcadm get clients -q clientId=bol-prod` | client 名尾部空格；`client_id` 拼错；secret 属于别的 client |
| `Missing parameter: code_challenge_method` | Keycloak 登录页/回调 | client `Advanced` 里的 PKCE 字段 | 设为 `S256`（BOL 固定发 `S256`，`oidc.py:151`） |
| `IP address mismatch` | 调 discovery / 换 token | `keytool -printcert` 看 SAN | 证书缺 `IP:172.26.2.203`；换证书后未重启 Keycloak |
| `self-signed certificate` / `certificate verify failed` | 同上 | `$env:SSL_CERT_FILE` 是否设置、是否指向新包 | 指对 PEM；服务方式启动要写服务环境变量 |
| 503 `统一登录未启用` | 点登录 / 回调 | `/api/auth/config/` 的 `oidc_enabled` | `enabled=True` 并**重启**；确认改的是 exe 同级那份 |
| 503 `OIDC 配置不完整: ...` | 点登录 | 看冒号后的具体问题（`validate_config` 输出） | 按问题改：secret 空 / redirect 含 `127.0.0.1` / issuer 与 redirect 主机不一致 / issuer 非 https |
| 400「登录状态无效」 | 回调 | 是否重启过（state 存内存）；是否重复回调；是否超 10 分钟 | 重新点登录；确认单进程（waitress 多线程单进程没问题，多进程会丢 state） |
| `?error=未开通本系统访问权限，请联系管理员` | 回跳前端 | `Evaluate` 看 `groups` | 用户没加 `app-bol`；或 `full.path=ON`（值是 `/app-bol`）；或 `required_group` 不一致 |
| `?error=账号已禁用, 请联系管理员` | 回跳前端 | 查 `Employee.status` | 本地被停用（每小时状态回写会同步中央表状态）；不是 Keycloak 的 `Enabled` |
| `invalid_user_credentials` | Keycloak 登录页提交 | `Users → ligu → Credentials` | 密码错 / 用户 `Enabled=OFF` / 临时密码过期 |
| 页面空白 / 500 | 回跳后 | F12 看 `/api/auth/oidc/token/` 响应；黑窗口 traceback | `front_callback` 写错；CORS；otk 60 秒过期（重新登录） |

---

## 7. 回滚

### 7.1 软回滚（30 秒，先做这个）

```ini
[oidc]
enabled = False
```

重启进程。效果：统一登录入口消失，`/api/auth/oidc/*` 503，本地登录照常（`local_auth_enabled=True`）。Keycloak 侧不动。

✅ `/api/auth/config/` 里 `oidc_enabled` 变 false。

### 7.2 硬回滚

停进程 → `db_config.ini` 换回备份 → 重启。备份建议改配置前做：

```powershell
Copy-Item '<BOL部署目录>\db_config.ini' "<BOL部署目录>\db_config.ini.bak-$(Get-Date -f yyyyMMdd-HHmmss)"
```

### 7.3 三条边界

1. **删 Keycloak 用户不算回滚**：中央表里该人仍 `status=1`，次日 06:00 同步会按 `login_name` 重建。
2. **KC 用户与 `Employee` 表无外键**：删 KC 用户不会级联删业务数据；反之亦然，但两边会不一致。
3. **自动建档的 `VIEWER` 不会自动清理**：拼错用户名产生的账号要人工核对后停用。

---

## 8. 需现场确认（代码 / 仓库里拿不到的）

1. BOL 部署目录与配置文件名（打包版是 exe 同目录，实际路径未知）。
2. BOL 是否注册为 Windows 服务、服务名（影响"怎么重启"）。
3. `bol-prod` 的 client secret 实际值。
4. `kcadmin` 用户名/口令。
5. `C:\sso\conf\ca-bundle.pem` 是否存在于 BOL 服务器、是否已含新证书。
6. 8090 是直连还是有反代；`Web Origins` 是否需带反代域名。
7. 生产库 `CMC` 的迁移是否已执行（`showmigrations` 为准）。
8. `keycloak.conf` 的 `hostname` 是否仍为 `sso.ap.inalfa.local`（决定 issuer 回显是 IP 还是域名；与 BOL 体检强相关）。
9. `front_callback` 前端路由 `/oidc/callback` 是否已在前端路由表里（前端版本需 ≥ 本构建）。

---

## 附录 A：变量块与只读查询

```powershell
$KCADM  = 'C:\keycloak\bin\kcadm.bat'
$IP     = '172.26.2.203'
$AppUrl = 'http://172.26.2.203:8090'
$KeyUrl = 'https://172.26.2.203:8443'
```

```powershell
# realm
& $KCADM get realms/inalfa --fields realm,enabled,accessTokenLifespan,sslRequired

# client（含 redirectUris / attributes=PKCE）
& $KCADM get clients -r inalfa -q clientId=bol-prod `
  --fields id,clientId,enabled,publicClient,standardFlowEnabled,directAccessGrantsEnabled,redirectUris,webOrigins,attributes

# 组
& $KCADM get groups -r inalfa --fields id,name,path

# 用户与所属组
$Uid = (& $KCADM get users -r inalfa -q username=ligu --fields id).id
& $KCADM get "users/$Uid/groups" -r inalfa --fields id,name,path

# mapper（404 时以控制台为准）
$Cid = (& $KCADM get clients -r inalfa -q clientId=bol-prod --fields id).id
& $KCADM get "clients/$Cid/protocol-mappers/models" -r inalfa --fields name,protocolMapper,config

# client secret —— 别贴到聊天/工单/文档
& $KCADM get "clients/$Cid/client-secret" -r inalfa --fields value
```

---

## 附录 B：最短路径清单与计时

### B.1 计时（第一次做）

| 段 | 内容 | 预估 |
|---|---|---|
| 第 1 章 | 7 项确认 | 15 分钟 |
| 第 2 章 | client + 组 + mapper + 用户 + Evaluate | 20 分钟 |
| 第 3 章 | 改配置（含 redirect 专项） | 10 分钟 |
| 第 4 章 | 迁移 + 启动 + 四条自检 | 15 分钟 |
| 第 5 章 | 端到端 | 10 分钟 |
| **合计** | | **约 60 分钟**（顺利）/ **1.5–2 小时**（遇 redirect 或证书） |

### B.2 打勾清单

- [ ] BOL 进程在跑，8090 在 Listen
- [ ] 入口页 `http://172.26.2.203:8090/actual-ct` 返回 200
- [ ] 证书 SAN 含 `IP:172.26.2.203`
- [ ] discovery issuer 已记下，且与 redirect 同主机（IP）
- [ ] 迁移 `0005`、`0006` 已应用
- [ ] 本地登录基线可用
- [ ] `bol-prod`：`Client authentication=ON`、`Standard flow=ON`、`Direct grants=OFF`
- [ ] `Valid redirect URIs` = `http://172.26.2.203:8090/api/auth/oidc/callback/`（**带尾斜杠**）
- [ ] `Web Origins` = `http://172.26.2.203:8090`
- [ ] PKCE = `S256`
- [ ] 组 `app-bol` 顶层
- [ ] mapper `groups`：`full.path=OFF`、`Add to ID token=ON`
- [ ] 测试用户 `ligu` 已加 `app-bol`、密码已设
- [ ] `db_config.ini`：`enabled=True`、`issuer` 抄回显、`redirect_uri` 带尾斜杠
- [ ] `OIDC_CLIENT_SECRET` 已注入
- [ ] 进程启动时间晚于配置文件修改时间
- [ ] `SSL_CERT_FILE` 指向含新证书的 PEM
- [ ] 自检 3 返回 302（不是 503）
- [ ] 自检 4 解码值与白名单逐字符一致
- [ ] 浏览器登录成功，日志有 `OIDC 登录成功: ligu (employee id=…)`
