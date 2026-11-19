# Keycloak Clients 配置表（realm `inalfa`）

> 依据《统一身份认证实施方案_MSIA与BOL系统.md》7.1 节。
> client secret 统一登记在 `C:\sso\conf\credentials.xml`（DPAPI），**不落本文档、不进 git**。
> 客户端 ID 一旦创建**不要改名**（会破坏两系统的 OIDC 配置与同步脚本）。

## 1. 总览

| Client ID | 类型 | 认证流 | Redirect URI | 准入组 | 用途 |
|---|---|---|---|---|---|
| `msia-prod` | confidential | 授权码 + PKCE(S256) | `http://172.26.2.203:8078/api/auth/oidc/callback`（精确） | `app-msia` | MSIA Report OIDC（T02） |
| `bol-prod` | confidential | 授权码 + PKCE(S256) | `http://<BOL地址>/api/auth/oidc/callback`（精确，**待确认 U2**） | `app-bol` | BOL 管理系统 OIDC（T03） |
| `sync-client` | confidential | Service Account（client_credentials） | —（不发起交互登录） | — | 三个同步脚本调 Admin REST |
| `account` | 内置 public | 标准流 | 自动 | — | 邀请设密邮件落地页；保持启用 |

## 2. msia-prod（MSIA Report 生产客户端）

| 配置项 | 值 | 说明 |
|---|---|---|
| Client ID | `msia-prod` | |
| Client authentication | **ON**（confidential） | MSIA 后端持 secret，前端不可见 |
| Authorization | OFF（不用 Keycloak 授权服务） | |
| Authentication flow | Standard flow ON；Direct access grants **OFF**；Service accounts OFF | 只走授权码 |
| Valid redirect URIs | `http://172.26.2.203:8078/api/auth/oidc/callback` | **精确匹配**（不带 `*`）；MSIA 现网 HTTP 地址（TR2），后续若上 HTTPS 域名（U1：`msia.ap.inalfa.local`）**追加**一条而不是替换，双轨期两个地址都要保留 |
| Valid post logout redirect URIs | `http://172.26.2.203:8078/` | |
| Web origins | `http://172.26.2.203:8078` | CORS |
| PKCE | S256（25.0.6 **不强制** PKCE；本系统客户端始终发送 S256，故在此 client 上显式设 `pkce.code.challenge.method=S256`） | |
| Login theme | 默认（或 inalfa 定制） | |
| Consent required | OFF | 内部系统免确认页 |
| Frontchannel logout | **OFF** | 两系统代码只有本地登出、无 frontchannel 登出端点；开 ON 会让 Keycloak 渲染指向不存在 URL 的 iframe |

**Mappers（Client scopes → Dedicated scope）**：

| Mapper 名 | 类型 | 值 | 用途 |
|---|---|---|---|
| `groups` | Group Membership | token claim: `groups`（full path 建议关闭，取组名） | 后端校验 `app-msia` |
| `email` | User Attribute → email（内置） | — | 设密/找回 |
| `full name` | User Attribute（内置） | — | 展示 |

## 3. bol-prod（BOL 管理系统生产客户端）

| 配置项 | 值 | 说明 |
|---|---|---|
| Client ID | `bol-prod` | |
| Client authentication | **ON**（confidential） | Django 后端持 secret |
| Authentication flow | Standard flow ON；Direct access grants **OFF**；Service accounts OFF | |
| Valid redirect URIs | `http://<BOL部署地址>/api/auth/oidc/callback` | **⚠️ U2 待确认**：BOL 对外地址/端口（waitress 托管地址）。按 12.4 结论：内网 IP:端口即可，建议随 IIS ARR 分配 `bol.ap.inalfa.local`；两种形态的 redirect URI 在切换期可同时配置 |
| Valid post logout redirect URIs | `http://<BOL部署地址>/` | |
| Web origins | `http://<BOL部署地址>` | |
| PKCE | S256（显式设 `pkce.code.challenge.method=S256`） | |
| Frontchannel logout | **OFF** | 代码无 frontchannel 登出端点 |

**Mappers**：同 msia-prod（groups claim 名 `groups`，准入值 `app-bol`）。

## 4. sync-client（同步脚本专用）

| 配置项 | 值 | 说明 |
|---|---|---|
| Client ID | `sync-client` | |
| Client authentication | **ON**（confidential） | secret 存 credentials.xml 条目 `keycloak_sync_client` |
| Authentication flow | **Service accounts roles ON**；Standard flow **OFF**；Direct access grants OFF | client_credentials 取令牌 |
| Client secret | 生成后登记 credentials.xml，**轮换时两个位置同步更新** | |
| Root URL / Redirect | 留空 | 不发起浏览器交互 |

**Service Account Roles（Service account roles 标签页 → assign role → filter by clients → realm-management）**：

| 角色 | 用途 |
|---|---|
| `manage-users` | 建号/改号/禁用/execute-actions-email/logout |
| `view-users` | 查询用户 |
| `query-users` | 按 username 查询 |

> 不授予 `realm-admin` 等宽角色——同步脚本只做用户管理，权限面最小化。

## 5. account（内置客户端）

| 配置项 | 值 | 说明 |
|---|---|---|
| 状态 | **保持启用** | 邀请设密邮件中的链接落地到 Account 控制台，用户在此完成 UPDATE_PASSWORD |
| 无需改配置 | — | 26.x 默认即可 |

## 6. 安全基线（所有 confidential client 通用）

1. secret 长度 ≥ 32，仅存 credentials.xml（DPAPI，绑定本机+运行账号）；
2. Access Token Lifespan 15 分钟（realm 级，见 realm-setup.md 第 5 节）；
3. 每季度核对一次 client 清单与本文档，发现多余 client 立即禁用并记录；
4. 紧急停号场景下无需动 client——只影响用户（disable_user_now.ps1）。

## 7. 待确认项（阻塞登记）

| # | 事项 | 影响 | 责任 | 状态 |
|---|---|---|---|---|
| U2 | BOL 固定内网访问 URL/端口（无需公网） | `bol-prod` redirect_uri 无法定稿 | T03 + 用户 | **待确认** |
| U1 | MSIA HTTPS 域名（`msia.ap.inalfa.local`） | `msia-prod` 需追加 redirect URI | IT（IIS ARR） | 推进中 |
| — | msia-prod secret 生成 | T02 config.ini `[oidc].client_secret` | T01/T02 | 待 P1 建 realm 后执行 |
