# Entra ID 联合认证评估（路线 B）

> 定位：本文是**路线 B —— 以 Entra ID（微软云）为认证源**；[ad-federation-assessment.md](ad-federation-assessment.md) 是**路线 A —— 本地 Keycloak 直连 AD**。两者互斥，不要同时上：同一个 `username` 不能既由 LDAP 联邦产生、又由 Entra 联邦产生，同时开会互相抢用户、组也挂不到确定的那个账号上。
> 现状口径：MSIA（`msia-prod`）、BOL（`bol-prod`）、Capacity（`ics-prod`）三套已走 OIDC 接 Keycloak `inalfa` realm；Keycloak 有 `kcadmin`（管理）与 `sync-client`（同步脚本）两个客户端；准入组是顶层 `app-msia` / `app-bol` / `app-ics`。
> 示意图：[three-paths.svg](entra-id-federation-assessment/three-paths.svg)（单文件，双击可开）。

## 0. 结论

**推荐 B1：保留 Keycloak 作 broker，把认证上移到 Entra。** 应用一行代码不改、组不用重挂、回滚只需停用一个 Identity Provider，同时拿到 MFA 与条件访问。

**什么时候翻转：**

| 翻转方向 | 触发条件 |
|---|---|
| 改为 B2（应用直连 Entra） | IT 明确要求"所有应用必须直接注册在 Entra、不得经过自建 IdP"，或 Keycloak 确定不再维护。代价见 1.3，工期约为 B1 的 3 倍 |
| 退回 A（本地 Keycloak 直连 AD） | Entra Connect 没有在跑（云上是一套独立的纯云账号）；或办公网无法访问 `login.microsoftonline.com`；或租户只有 Free 档、给不了 MFA 策略粒度——这三种情况下 B 换来的只是"又一层密码" |

## 1. 三种接法

### 1.1 对比

| 维度 | A. Keycloak 直连 AD | B1. Keycloak 作 broker | B2. 应用直连 Entra |
|---|---|---|---|
| 应用改动 | 0 | **0** | **改配置 + 改代码 + 重新打包发版** |
| Keycloak 角色 | 唯一 IdP | IdP + Entra 的下游客户端 | **退场** |
| 组判断 | Keycloak 发组名 `app-msia` | 同 A（组仍在 Keycloak） | 只能拿到组 **GUID**，或改成 App Roles |
| 拿到的能力 | 一套域密码 | 一套域密码 + MFA + 条件访问 + 登录审计 | 同 B1，去掉一层中间件 |
| 新增故障点 | DC / 636 | DC + Entra + `login.microsoftonline.com` 可达性 + 凭据到期 | 同上，且**三套应用各自**承担一份 |
| 回滚成本 | 高（要重建本地账号，见 A 文档 4.6） | **低**（停用 IdP） | 高（要回到"Keycloak 还没被拆"的状态） |
| 账号生命周期 | `CN_AME` 五张表 + 三个脚本 | 同 A | **全部作废**，要在 Entra 侧重做组与分配 |

### 1.2 为什么 B1 的应用改动是 0

应用只做三件事：拿 `id_token` 验签（`aud` = 自己的 client_id）、看 `groups` claim 里有没有准入组、用 `preferred_username` 找本地账号。broker 模式下这三件事的输出**完全不变**——`aud` 仍是 `msia-prod`，`groups` 仍由 Keycloak 按本地组成员关系生成，`preferred_username` 仍是 Keycloak 的 username（即 `login_name`）。Entra 的令牌只到 Keycloak 为止，不下发给应用。

代价是 Keycloak 必须活着，且它成了"Entra 的客户端"——多一个要维护的凭据（见 4.3）。

### 1.3 B2 的真实改动量（不是改几行配置）

1. **配置**：三个系统各自的 issuer / client_id / client_secret / redirect_uri（字段位置见 3.2）。
2. **代码**：MSIA `app/core/oidc.py` 的 `validate_config()` 与 BOL `apps/users/oidc.py` 的 `validate_config()` 都会在启动时检查 **issuer 主机 == redirect_uri 主机**，不一致直接返回 503。直连时 issuer 是 `login.microsoftonline.com`、回调是 `172.26.2.203`，检查必然不过——必须改代码放行，然后**用 PyInstaller 重新打包、发版、重启服务**。这不是配置项。
3. **HTTPS**：Entra 的 Web 平台重定向 URI 必须是 `https://`（只有 `localhost` 例外）。我们三套现在是 `http://`，直连前必须先把对外地址改成带企业证书的 HTTPS。
4. **组判断**：Entra 只发组对象 GUID，`settings.OIDC_REQUIRED_GROUP not in groups` 直接全部 403。要么把 `required_group` 填成 `app-msia` 对应的 GUID（<200 组时可行），要么改成 App Roles 判 `roles` claim（又一次改代码）。
5. **失去的东西**：`sync_sso_to_keycloak.ps1`、`assign_groups_from_ledger.ps1`、`CN_AME_SSO_UserMap`、`SyncLog`、健康检查任务全部作废，账号生命周期要在 Entra 侧用组 + 企业应用分配重建，并重新做一遍权限台账的迁移。

## 2. 前置条件（卡住就做不了）

| # | 条件 | 不满足会怎样 |
|---|---|---|
| 1 | **Entra Connect 已在跑**，且模式是 PHS（密码哈希同步）或 PTA（直通认证）或 ADFS 联邦 | 云上账号与本地 AD 没有对应关系，"电脑密码改了各系统跟着变"不成立；只剩一套独立的云密码，等于又一套口令 |
| 1a | 若为 **PHS**：AD 口令散列同步到云，改密在 AD 侧生效后几分钟跟到云 | 这是三条里最省事的一条，无本地常驻组件；代价是口令散列（PBKDF2 of MD4）存在云上 |
| 1b | 若为 **PTA**：密码不落云，Entra 把校验代理回本地 agent | 本地 agent 全挂 = 云上没人能登。至少要 3 台 agent 且分散在不同主机 |
| 1c | 若为 **ADFS 联邦**：Entra 把登录重定向回本地 ADFS | 要维护 ADFS 场 + 外网 WAP，等于又多一套 IdP；不建议在此之上再叠 Keycloak broker |
| 2 | **用户浏览器能访问 `login.microsoftonline.com`**（不是服务器能出网就行） | 授权跳转在浏览器里发生，走代理/白名单拦掉就是"点了登录没反应/页面打不开"，应用侧只看到回调永远不回来 |
| 3 | **许可证档位**：Free 只有基础 SSO；**P1** 才有条件访问（按人/组、按位置、强制 MFA）；P2 才有 Identity Protection / 风险登录 | 只有 Free 时，能拿到的是"统一登录页 + 安全默认值的 MFA"，拿不到按应用/按网段分级的策略。B1 的收益从"MFA + 条件访问"缩水为"统一登录页" |
| 4 | **应用注册权限**：Application Administrator / Cloud Application Administrator，或 Global Admin | 拿不到 client id；给应用配组声明、授予 Graph 权限需要**管理员同意**，普通账号点不动——会卡在 3.1 第 4 步 |

## 3. 配置步骤

### 3.1 Entra 侧应用注册（B1 只注册一个）

| 项 | 值 | 说明 |
|---|---|---|
| 账户类型 | 仅此组织目录中的账户（单租户） | 多租户会让任意租户的用户撞进来 |
| 平台 | Web | |
| 重定向 URI | `https://iame.ap.inalfa.local:8443/realms/inalfa/broker/entra/endpoint` | Keycloak broker 的回调固定是这个形状，`entra` 是下面 IdP 的 alias，两边必须逐字一致 |
| 客户端凭据 | **上传证书（.cer 公钥），不用 client secret** | 见下方"为什么用证书" |
| 令牌配置 | `groupMembershipClaims=SecurityGroup`、`accessTokenAcceptedVersion=2` | 只影响排查，不影响 B1 的组判断（组仍由 Keycloak 发） |
| 组声明 | 可选，加了也只能得到 GUID | **B1 不要依赖它**，否则和 A 文档 4.4 的"组真相在 Keycloak"冲突 |

**为什么用证书而不是 client secret：**

- secret 是明文存在 Entra 与 Keycloak 两边的，最长 24 个月，会出现在配置、导出、日志里；
- 证书私钥可以只落在 Keycloak 的 keystore 里，Entra 侧只有公钥，泄露面小一半；
- secret 到期当天 token 交换返回 `invalid_client`，**全员登不上，且只有人登录时才暴露**（`/health` 看不出来）；证书同样会到期，但证书可以在到期前并存新旧两份、平滑换签，secret 虽然也能并存，运维上没人会去轮换一个明文串。

### 3.2 Keycloak 侧 Identity Provider

| 配置项 | 值 |
|---|---|
| Provider | OpenID Connect v1.0，alias **`entra`**（改了要同步改 3.1 的回调地址） |
| Discovery URL | `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration` |
| Client ID / 认证方式 | 3.1 的 Application (client) ID；Client Authentication = **Client JWT signed with private key**，上传私钥 |
| Scopes | `openid profile email` |
| Sync mode | `IMPORT` |
| First login flow | `first broker login`，**必须启用 `Automatically link broker user`**（按 username 匹配已有用户），否则会给每个人**新建一个本地账号** |
| Username mapper | Mappers 里加 **Username Template Importer**，claim 取 `preferred_username`，**去掉 `@` 及域名后缀**，得到 `sAMAccountName` |
| Trust Email | 开 |
| PKCE | 开（`pkceEnabled`） |
| Validate signatures | 开 |
| Store tokens | 关（不回写、不存 Entra 的 refresh token） |
| Hide on login page | 切换前保持开启，用直链先测；正式切换时关闭 |

关键点：**username mapper 的截断规则是这条路线唯一的硬约束**。Entra 的 `preferred_username` 是 `ligu@ap.inalfa.local`，Keycloak 的 username 是 `ligu`；不截断就等于给每人在 realm 里多建一个带 `@` 的账号，组全挂不上、数据全空。

### 3.3 B2 才需要改的应用侧参数（按实际字段名）

MSIA：`C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini` 的 `[oidc]` 段

```ini
[oidc]
enabled = true
issuer = https://login.microsoftonline.com/<tenant-id>/v2.0
client_id = <Entra 应用注册的 client id>
client_secret =            ; 建议留空，用环境变量 OIDC_CLIENT_SECRET
redirect_uri = https://<对外地址>/api/auth/oidc/callback
front_callback = /oidc/callback
required_group = app-msia   ; 直连时这里得填 GUID，否则恒 403
auto_create_user = true
scopes = openid profile email
```

BOL：`BOLServer.exe` 同目录的 `db_config.ini` 的 `[oidc]` 段（环境变量 `BOL_DB_CONFIG` 指定的路径优先），键名与 MSIA 相同：`enabled` / `issuer` / `client_id` / `client_secret` / `redirect_uri` / `front_callback` / `required_group` / `auto_create_user` / `scopes`。同名环境变量（`OIDC_ISSUER` 等）**优先级高于 ini**，服务器上若已注入，只改 ini 不生效。

Capacity：`C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env`

```ini
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_CLIENT_ID=<Entra 应用注册的 client id>
OIDC_CLIENT_SECRET=<证书私钥方式不支持时用 secret>
OIDC_REDIRECT_URI=https://<对外地址>/api/v1/auth/oidc/callback
OIDC_FRONTEND_URL=https://<对外地址>
OIDC_POST_LOGOUT_REDIRECT_URI=https://<对外地址>/login
OIDC_REQUIRE_GROUP=true
OIDC_REQUIRED_GROUP=<组 GUID，直连时必须换掉 app-ics>
```

## 4. 必须点明的坑

**4.1 `preferred_username` 是 UPN，`login_name` 是 sAMAccountName。**
现网两者不保证相等（历史上有带后缀、大小写、改名残留）。对不上的后果不是"登录失败"，而是**能登录、但落到错误身份**：准入组过了，身份解析回落 `preferred_username` 找不到本地用户，`auto_create_user=true` 会静默建一个新号——MSIA 是最低权限 `reviewee`，BOL 是 `VIEWER`。用户看到的是"登录成功但数据全空"，还多了一个重复账号，事后很难查。
B1 用 3.2 的截断 mapper 消除这个问题；B2 必须先跑一次 UPN ↔ `login_name` 全量比对。注意 Entra 的 `onPremisesSamAccountName` 只在 PHS/PTA 同步的账号上有值，纯云账号为空——不能盲取。

**4.2 Entra 默认不下发组名称，只下发对象 GUID；组多时直接 overage。**
`groups` claim 里是 GUID；一个用户的组超过 200 个（或 claim 超过令牌体积上限）时，令牌里**干脆没有 `groups`**，只剩 `_claim_names` / `_claim_sources`，必须再拿 Graph 查。应用现在的判断是 `"app-msia" not in groups` → 恒真 → **全员 403**（不是登录失败，是"未开通本系统访问权限"）。B2 要么把 `required_group` 改成 GUID（<200 组才安全），要么改成 App Roles 判 `roles` claim，要么每次登录调 Graph（要额外权限、多一次网络依赖）。B1 不受影响。

**4.3 客户端凭据到期。**
secret 最长 24 个月、证书 1–3 年，到期当天 token 交换失败 = 全员登不上。`/health` 不检查这件事，只能靠自建到期提醒（读凭据 `exp` 与当前时间比，剩 60 天告警）。轮换必须双份并存：Entra 侧先加新凭据、Keycloak 侧先换新、确认登录正常后再删旧的。反过来操作就是一次自制的全员故障。

**4.4 时钟偏差。**
`verify_id_token` 的 `leeway` 是 60 秒；主机时钟漂移超过它就抛 `ImmatureSignatureError` / `ExpiredSignatureError`，表现是回调 500。Keycloak 主机与 AD 同源（域内 NTP）是既有前提；B2 直连时**三台应用主机**都要与同一个时间源同步，否则是三处独立的随机故障。

**4.5 断网 / 云端不可用。**
Entra 不可用时新登录全部失败，已登录的靠本地 JWT 撑到过期。现有兜底只有 `admin` 与 39 个共享信箱账号（本地账号，见 A 文档 4.2），它们能救管理员，救不了普通用户。另外 MSIA 的 `[security] local_login_enabled` 与 BOL 的 `db_config.ini [auth] local_auth_enabled` 是**应用自己的本地账号**，与 Keycloak 无关——保留它们只兜住应用管理员，不能当成"域挂了还能用"的方案。Capacity 没有本地登录通道，云端不可用时它没有退路。

## 5. 切换与回滚

### 5.1 B1 切换顺序（不停机）

| # | 动作 | 判据 |
|---|---|---|
| 1 | 备份 `CN_AME` 五张 SSO 表；导出 realm | 备份可读 |
| 2 | Entra 应用注册（3.1）+ 上传证书 | 能取到 discovery 文档 |
| 3 | Keycloak 建 IdP `entra`，`Hide on login page` = 开 | 用直链 `https://iame.ap.inalfa.local:8443/realms/inalfa/broker/entra/login?client_id=msia-prod&...` 走通 |
| 4 | 用 1 个测试账号（`ligu`）验证 5.2 全部项 | 全部通过 |
| 5 | 关闭 `Hide on login page`，三个应用各登一次 | 登录页出现"Entra ID"按钮 |
| 6 | 观察 3 个工作日 | 无 403、无重复账号（按 `@` 搜 username 应为 0） |

### 5.2 验证项（要验到"统一登录真的可用"，不是拿到 token）

- 跳转落在 `login.microsoftonline.com`，且**没有二次输入密码**（域内已登录的设备应直接过）；
- 回调后 Keycloak 会话建立，`preferred_username` 是 `ligu` **而不是** `ligu@ap.inalfa.local`；
- Keycloak 里 `/realms/inalfa/account` 能看到 `app-msia` 组；
- 三个应用各进**业务页面**：MSIA 打开一个评审项、BOL 打开一条业务记录、Capacity 打开一个计划页。组校验通过 ≠ 数据可见，4.1 的问题只在业务页面才暴露；
- 退出登录回到应用登录页，不报 `Invalid redirect uri`；
- 手动把 IdP 设回 `Hide on login page`，确认回落"Keycloak 表单 + AD 校验"仍能登——这就是回滚演练。

### 5.3 回滚要回到哪个状态

- **B1 回滚 = 停用 IdP**（关掉 `Enabled`，或打开 `Hide on login page`）。登录回落到 Keycloak 的用户名密码表单，凭据仍由 AD 校验（或保留的本地密码），**组与用户一条不动**。10 分钟内可完成，不碰应用、不碰数据库。这是 B1 唯一的、也是最大的优势。
- **B2 回滚 = 改回三处配置 + 重启三个服务**，前提是 **Keycloak 侧的 client、组、`CN_AME` 五张表都还在**。所以 B2 切换期**绝对不要删 Keycloak 的 client 与组**——一旦按"退场"真删了，回滚就是重建一遍（组重挂 + 账号映射 + 重新发版），与正向切换同量级。代码层面放宽过 `validate_config` 的版本不必回滚（改回 Keycloak 配置后主机一致，检查照样通过），但**上一个可用版本的安装包必须留着**。

## 6. 决策点与工期

需要拍板：

1. **走 B1 还是 B2**（默认 B1；B2 只在 IT 强制或 Keycloak 要下线时选）。
2. **Entra 租户的许可证档位**：有没有 P1。没有 P1，B1 的收益只剩统一登录页，投入产出要重算。
3. **是否接受"用户浏览器必须能访问 `login.microsoftonline.com`"**（含生产网段、车间终端、代理白名单）。
4. **登录名以哪个为准**：建议以 `sAMAccountName` 为准（截断 UPN 后缀），而不是把 UPN 当 username。
5. **组真相放哪**：B1 留在 Keycloak（推荐）；B2 必须迁到 Entra 组或 App Roles。
6. **应用本地登录通道是否保留**（MSIA `local_login_enabled`、BOL `[auth] local_auth_enabled`）——保留是运维兜底，也意味着两个登录入口并存。
7. **B2 是否接受"改代码 + 重新打包发版"**，以及谁来发版、回滚包谁保管。

粗略工期（不含 IT 审批等待）：

| 路线 | 阶段 | 工作量 |
|---|---|---|
| B1 | Entra 应用注册 + 证书 + 管理员同意 | 0.5 天 |
| B1 | Keycloak IdP + username mapper + first broker login 调通 | 0.5–1 天 |
| B1 | UPN ↔ `login_name` 全量比对与差异处理 | 0.5–1 天 |
| B1 | 测试 + 切换窗口（不停机） | 2 小时 |
| B1 | 观察期 | 3 个工作日（不占人力） |
| B2 | 上述 B1 全部 | ≈ 2–3 天 |
| B2 | 两处 `validate_config` 改造 + 重新打包发版 | 2–3 天 |
| B2 | 三套系统上 HTTPS（证书 + IIS ARR/域名） | 1–2 天 |
| B2 | 组判断改造（GUID / App Roles）+ 权限台账迁移 | 1–2 天 |
| B2 | 回滚包与演练 | 0.5 天 |

B1 合计 **2–3 人日**，主要变量在 IT 侧（应用注册审批、P1 许可证、租户 ID）；B2 合计 **6–9 人日**，且其中 3–5 天是纯发版与联调，与认证是否稳定无关。
