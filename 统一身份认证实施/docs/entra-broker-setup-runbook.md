# Entra ID broker 实施手册（路线 B1）

> 目标：三套应用照旧接 Keycloak，认证上移到 Entra。应用零改动，Keycloak 加一个 Identity Provider。
> 现场值：Keycloak 25.0.6 / `https://iame.ap.inalfa.local:8443` / realm `inalfa` / 安装目录 `C:\keycloak` / 脚本目录 `C:\sso\scripts`；客户端 `msia-prod`、`bol-prod`、`ics-prod`；准入组 `app-msia`、`app-bol`、`app-ics`。
> 配套：[entra-id-federation-assessment.md](entra-id-federation-assessment.md)（选型）、[ad-federation-assessment.md](ad-federation-assessment.md)（路线 A）。

## 0. 先定死的值（IT 已给）

| 项 | 值 |
|---|---|
| 租户 ID | `c623fd68-0d60-4d10-9429-bbf9c7858d7d` |
| 应用(客户端) ID | `b1407c3f-4999-4950-9223-905d14567f18` |
| discovery | `https://login.microsoftonline.com/c623fd68-0d60-4d10-9429-bbf9c7858d7d/v2.0/.well-known/openid-configuration` |
| IdP alias | **`oidc`** —— IT 登记的重定向 URI 路径是 `/broker/oidc/endpoint`，Keycloak 的 alias 必须是 `oidc` 才对得上 |
| broker 回调（Entra 重定向 URI） | `https://iame.ap.inalfa.local:8443/realms/inalfa/broker/oidc/endpoint`，平台类型必须是 **Web** |
| 登录入口 | `https://iame.ap.inalfa.local:8443/realms/inalfa/account/`（也可从任一应用的登录页进） |
| client secret | **不写进任何文件**。从 IT 处取得后只在 Keycloak 表单里粘贴一次，轮换流程见 1.6 |

alias 被写进三处：IT 登记的重定向 URI、登录 URL `/broker/oidc/login`、应用侧的 `kc_idp_hint=oidc`。**改 alias 等于让 IT 重新登记一次**，不要动。

### 0.1 开工第一步：Keycloak 主机能不能访问登录页

在 Keycloak 服务器上跑，只认返回里有没有 `issuer` 这一个字段：

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$d = Invoke-RestMethod -Uri 'https://login.microsoftonline.com/c623fd68-0d60-4d10-9429-bbf9c7858d7d/v2.0/.well-known/openid-configuration' -TimeoutSec 20
$d.issuer
```

**看到**：`https://login.microsoftonline.com/c623fd68-0d60-4d10-9429-bbf9c7858d7d/v2.0`
**没看到**：先解决出网（代理白名单 / DNS / TLS），再往下做任何一步——这一步不通，2.1 的导入必然失败。

## 1. Entra 侧

### 1.1 核对应用注册（IT 已建好，不要新建第二个）

菜单：**Entra 管理中心 → 应用 → 应用注册 → `Keycloak broker`**。

| 字段 | 应为 |
|---|---|
| 支持的账户类型 | **仅此组织目录中的账户（单租户）**。多租户等于允许任意租户的用户进来 |
| 重定向 URI | 平台 **Web**，URI `https://iame.ap.inalfa.local:8443/realms/inalfa/broker/oidc/endpoint` |

**看到**：概览页 `应用程序(客户端) ID` = `b1407c3f-4999-4950-9223-905d14567f18`，`目录(租户) ID` = `c623fd68-0d60-4d10-9429-bbf9c7858d7d`。
**不一致**：停，先让 IT 确认是同一个应用。不要自己再建一个——两个应用各有一份 client id，回调会打到错的地方。

### 1.2 凭据：现在用 IT 给的 secret，首次轮换时换证书

IT 已签发 client secret，且**明文走过邮件/聊天**——上线前必须重新签发一次（步骤见 1.6）。当前就按 secret 配：值从 IT 处取得后手工粘进 Keycloak（2.3），**不写进任何文件、工单或文档**。

为什么要换成证书：secret 明文存在两边、最长 24 个月、会进配置和导出；到期当天 token 交换直接 `invalid_client`，**全员登不上且只有人登录时才暴露**。证书只把公钥放在 Entra，私钥不出 Keycloak，新旧两份可以并存平滑换签。

首次轮换时再执行下面这段（现在不做）：

```powershell
$c = New-SelfSignedCertificate -Subject 'CN=keycloak-broker-entra' -KeySpec Signature `
     -KeyExportPolicy Exportable -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 `
     -NotAfter (Get-Date).AddYears(3) -CertStoreLocation 'Cert:\CurrentUser\My'
Export-Certificate   -Cert $c -FilePath C:\sso\conf\entra-broker.cer -Type CERT
$pw = ConvertTo-SecureString -String '<自定口令>' -Force -AsPlainText
Export-PfxCertificate -Cert $c -FilePath C:\sso\conf\entra-broker.pfx -Password $pw
```

`.cer` 上传到 Entra（只含公钥），`.pfx` 按 2.4 处理（25.0.6 要作为 realm 签名密钥以 PEM 导入；只有存在 `Private key` 字段的版本才用 JWK），再把 `客户端认证` 从 Client secret 切到 Client JWT signed with private key。

### 1.3 API 权限

只走 OIDC，不需要任何 Microsoft Graph 权限。`API 权限` 页保留默认的 `openid`、`profile`、`email`、`User.Read`（委托）即可，不要额外申请 `GroupMember.Read.All`——组由 Keycloak 发，不从 Entra 读。

**看到**：没有橙色的"需要管理员同意"提示。
**若出现**：说明有人加过 Graph 权限，删掉，否则每次登录多一次授权失败风险。

### 1.4 用"要求分配"限人群（灰度用）

菜单：**企业应用 → 找到 `Keycloak broker` → 属性 → 需要分配？= 是**，然后在"用户和组"里加试点人员。

**看到**：未分配的账号登录得到 `AADSTS50105`（未分配角色）。
**灰度完成**：改回"否"。**注意**：改回"否"不影响已登录会话，只影响下次登录。

### 1.5 令牌配置（能不动就不动）

菜单：**令牌配置**。

- `可选声明`：只在第 4 节走"路 2"时才加，其余情况留空；
- `组声明`：**不要开**。开了也只是对象 GUID，B1 用不上，反而让令牌变大；
- `accessTokenAcceptedVersion` 保持默认 2。

### 1.6 凭据生命周期（client secret）

**先问清到期日**：Entra → 应用注册 → `Keycloak broker` → 证书和密码 → 客户端密码 → `Expires` 列。

**到期前 60 天换（或上线前重签那次）**：

1. 同页 **新建客户端密码** → 记下 `Value`（只显示一次）与到期日 → 保存。**旧的先不要删**，两份同时有效；
2. Keycloak → 身份提供程序 → `oidc` → `客户端认证` → `Client Secret` 粘贴新值 → 保存；
3. 立刻用 `ligu` 走一次登录（第 0 节的登录入口 →"Entra ID"），进到 `/realms/inalfa/account` 看到组 = 成功；
4. 确认无误后回 Entra 删掉旧密码。

**没换会怎样**：到期当天所有 broker 登录失败——用户点"Entra ID"后令牌换不回来，Keycloak 报 `invalid_client`，三个系统全进不去。**本地账号（`admin` 与 39 个共享账号）不受影响**，它们不走 IdP，表单照样能登——这是唯一的应急入口。

**这个 secret 已经明文走过邮件/聊天**：上线前重新签发一次并删掉旧值，不要把现在这个直接用到生产。

## 2. Keycloak 侧

### 2.1 用 discovery 导入

菜单：**管理控制台 → inalfa → 身份提供程序 → 添加提供程序 → OpenID Connect v1.0**。

同一张表单上**别名先填 `oidc`**（与 IT 登记的回调路径一致），再把 `导入` 填成：
`https://login.microsoftonline.com/c623fd68-0d60-4d10-9429-bbf9c7858d7d/v2.0/.well-known/openid-configuration` → 点 **导入**。

**看到**：授权端点、令牌端点、JWKS、issuer 自动填好，issuer 是 `https://login.microsoftonline.com/c623fd68-0d60-4d10-9429-bbf9c7858d7d/v2.0`。
**导入失败**：先回 0.1 那条命令——主机出不去网，这里一定失败。

### 2.2 字段

| 字段 | 填什么 |
|---|---|
| 别名 Alias | `oidc`（不能改成别的，见 2.5） |
| 显示名称 | `Entra ID`（登录页按钮上的字） |
| Client ID | `b1407c3f-4999-4950-9223-905d14567f18` |
| 客户端认证 | **Client secret** |
| Client Secret | 从 IT 处取得后粘贴，不要抄进任何文件 |
| Scopes | `openid profile email` |
| 信任电子邮件 Trust Email | 开 |
| 存储令牌 Store tokens | 关 |
| 验证签名 | 开 |
| PKCE | 开，方法 S256 |
| 同步模式 Sync mode | `IMPORT` |
| 隐藏登录页面 Hide on login page | **关**。开了按钮就不显示，员工只能手敲登录 URL；用户名密码表单不受这个开关影响，始终在 |
| 首次登录流程 | 先留默认，第 3 节改完再切 |

**看到**：保存后从 IdP 列表点 `oidc`，端点都是 HTTPS，issuer 与 discovery 一致。

### 2.3 填 Client Secret

IdP 详情页 → `客户端认证` 选 **Client secret** → `Client Secret` 粘贴 IT 给的值 → 保存。

**看到**：保存后页面不回显明文（只显示"已设置"）；回 IdP 列表再点进来，`Client authentication` 仍是 Client secret。
**注意**：这是整份手册里唯一出现 secret 的地方。不要抄进文件、不要截图发群、不要贴工单。

将来换证书：同一页切到 `Client JWT signed with private key`，私钥怎么填见 2.4，然后把这里的 secret 删掉。

### 2.4 Client secret 与 Signed JWT 二选一（`AADSTS50146` 不归这一页管）

IdP 的 `客户端认证` 只有三条路，区别只在"我们拿什么向 Entra 证明自己是这个应用"：

| 选项 | 我们出示什么 | 凭据放在哪 |
|---|---|---|
| `Client secret`（现在用的） | 一段共享密钥 | Entra 的"客户端密码" + 这里粘同一个值 |
| `Client JWT signed with private key` | 每次换令牌现签一个短时效 assertion（`private_key_jwt`） | Entra 应用上登记的**证书公钥** + Keycloak 侧一把能签这个算法名的私钥（25.0.6 取 realm 的 active 签名密钥，见下） |
| `Client secret JWT signed with HMAC` | 用 secret 给 assertion 做 HMAC | 同第一行，只是多了层 JWT 包装 |

**什么情况下 Entra 会要求 Signed JWT**（即 secret 这条路走不通）：

1. 应用注册上只登记了证书、没有客户端密码——用 secret 换令牌直接 `invalid_client` / `AADSTS7000215`；
2. 租户的应用管理策略禁止创建密码凭据（安全基线常见），Entra 上"新建客户端密码"按钮是灰的；
3. IT 明确要求 `private_key_jwt`（审计口径）。

这三条都只影响"我们怎么向 Entra 认证"，跟登录后拿到的令牌长什么样无关。

**25.0.6 上这一页只有三项必填、外加一个开关，并且没有 `Private key` 输入框。** 选了 `Client JWT signed with private key` 之后，assertion 的签名密钥取自**本 realm 的活动签名密钥**：`AbstractOAuth2IdentityProvider.getSignatureContext()` 的 `private_key_jwt` 分支是 `session.getProvider(SignatureProvider.class, alg).signer()`（不带 key 参数），最终落到 `session.keys().getActiveKey(realm, KeyUse.SIG, alg)`。

| 字段 | 填什么 | 对应配置键 |
|---|---|---|
| Client authentication | `Client JWT signed with private key` | `clientAuthMethod` = `private_key_jwt` |
| Signing algorithm | `RS256`（默认值，不要动） | `clientAssertionSigningAlg` |
| Client assertion audience | 留空（默认用令牌端点） | `clientAssertionAudience` |
| Use JWT X.509 headers | 关；开了会在 assertion 头里塞 `x5c` / `x5t` | `jwtX509HeadersEnabled` |

**私钥不在这页填，那它在哪**：就是 **Realm settings → Keys** 里当前 active 的那把 RSA 签名密钥（`rsa-generated`，或手工导入的 `rsa`），也就是给三个应用签令牌的同一把。两个直接推论：

- 只改 IdP 页面、不动 realm keys → assertion 用现有 active 密钥签，Entra 上登记的客户端证书必须是**这把密钥的公钥**，否则 `AADSTS700027`（assertion 签名验不过）；
- 要让 assertion 用 IT 给的那张证书签 → 得把它作为 realm key 导入并设为 active，**realm 随后签发的所有令牌也会换签名密钥**，影响面是整个 realm，不只是 broker 登录。

导入用的 `rsa` provider 吃 **PEM**（`PemUtils.decodePrivateKey`），不吃 JWK：Realm settings → Keys → Providers → Add provider → `rsa`，粘私钥 PEM + 证书 PEM，Priority 设到高于现有 `rsa-generated`，保存。

**如果你的界面里确实有 `Private key` 输入框**（更高版本或定制构建），那才用下面这个脚本产出 JWK 粘进去；25.0.6 原生没有这个框，不必在页面上找。

```powershell
C:\sso\scripts\pfx_to_jwk.ps1 -PfxPath C:\sso\conf\iame.p12 -OutFile C:\sso\tmp\idp.jwk.json
```

脚本离线运行、不发请求、不碰证书存储，打印 Subject / SHA-1 / SHA-256 / `x5t` / `x5t#S256`，拿去和 Entra 上登记的那张证书逐位对；**JWK 文件里是明文私钥，粘进 Keycloak 并保存后立刻删除**。

配置改完用下面这条只读命令核对（在 Keycloak 主机上）：

```powershell
C:\keycloak\bin\kcadm.bat get identity-provider/instances/oidc -r inalfa --fields config.clientAuthMethod,config.clientAssertionSigningAlg,config.clientAssertionAudience,config.jwtX509HeadersEnabled
```

**关于 IT 给的那张 pfx**：`CN=iame.ap.inalfa.local`、指纹 `A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A`、到期 2028-07-31——它就是 Keycloak 自己 `iame.p12` 里那张 **TLS 服务器证书**。在 25.0.6 上用它签 assertion，等于把它变成 realm 的 active 签名密钥：三个应用的新令牌也一起换签名密钥，换 TLS 证书时 broker 登录跟着断。验证阶段为了打通可以用，但要知道范围；长期应换成 1.2 那张专用证书（`CN=keycloak-broker-entra`）。

**这一步不解决 `AADSTS50146`。** 一句话：**改用 Signed JWT 只改变"我们怎么证明自己"，不改变"Entra 怎么签令牌"，50146 是后者的错误。**

两个环节别混：

| 环节 | 谁决定 | 出错时的错误码 |
|---|---|---|
| 我们向 Entra 换令牌时的身份认证 | 我们的凭据（secret / 私钥）+ Entra 上登记的凭据 | `invalid_client`、`AADSTS7000215`（secret 错）、`AADSTS700027`（assertion 签名验不过） |
| Entra 签发的令牌用哪把密钥签 | Entra 应用/服务主体上的签名密钥策略 | `AADSTS50146`（应用被要求使用应用专用签名密钥） |

所以：改完 Signed JWT 仍报 50146，说明凭据这一关已经过了，卡在签名环节——**不要再回头折腾 pfx**。

**50146 的成因**（两种，都要 IT 在 Entra 侧查）：

1. 服务主体上配了 `preferredTokenSigningKeyThumbprint`，指定用某张自定义证书签令牌，而该密钥不在我们校验的 JWKS 里，或指纹对不上；
2. 应用挂了 claims mapping policy（`tokenSigningKeyThumbprint` 之类），把签名密钥换成了自定义证书。

**50146 没消除时向 IT 要这四条**：

1. 这个应用（服务主体）是不是被打过 `preferredTokenSigningKeyThumbprint` 或 claims mapping policy；能否去掉、去掉后回租户默认密钥；
2. 如果必须保留自定义签名密钥：把那把**签名证书的公钥**（`.cer`）加进应用的 `keyCredentials`（usage = `Verify`），并把指纹给我们；
3. 明确区分两把证书：**给令牌签名用**（Entra 签，登记在签名密钥策略里）和**客户端认证用**（我们签 assertion，登记在应用凭据里）——IT 现在把 TLS 那张当成这两者之一，最容易混在这；
4. 这条策略是谁、何时加的，租户里还有哪些应用受影响。

**排查顺序**：先确认切完 Signed JWT 后不再出现 `invalid_client` / `700027`（凭据环节通了），再看 50146 是否消失；两个错同时出现说明两件事都没弄对，先修凭据再谈签名。**回滚**：任一步失败就把 `客户端认证` 切回 `Client secret`，本地账号（`admin` 与 39 个共享账号）始终能登。

### 2.5 alias 为什么不能改

`oidc` 被写进三个地方：IT 已登记的重定向 URI 路径段、登录 URL `/broker/oidc/login`、应用侧可传的 `kc_idp_hint=oidc`。**alias 已经被 IT 那边的 URI 锁死了**，改它等于让对方重新登记一次，配好之后不要碰。

## 3. 首次登录流程

### 3.1 默认流程为什么走不通

默认的 `first broker login` 首步是 `Review Profile`（要求补全/确认姓名邮箱），下挂的 `Account verification options` 还会走邮箱验证。2800 人首登会被拦在资料页，且大量账号中央表里没有邮箱——这批人第一步就过不去。

### 3.2 复制流程

菜单：**认证 → 流程 → 找到 `first broker login` → 右上角 复制 → 新名 `first broker login - entra`**。
**不要改原件**，其他 IdP（将来若有）还在用。

### 3.3 改三个执行项

| 执行项 | 改成 | 原因 |
|---|---|---|
| `Review Profile` | **Disabled** | 不让人停在资料页 |
| `Account verification options → Verify Existing Account by Email` | **Disabled** | 邮箱对不上/为空时会要求收信验证，直接死循环 |
| `Automatically set existing user` | **Required**（列表里没有就用 添加执行 → 选它） | 按 broker 回来的 username 自动绑定到已有用户，不弹确认页 |

其余保持默认：`Create User If Unique` = Alternative，`Confirm Link Existing Account` = Alternative。

**看到**：保存时没有红色校验错误（Keycloak 会拦"全是 Disabled"这类组合）。

**列表里按 25.0.6 的实际显示名找**：`Automatically set existing user`（只有首字母大写，不是 `Automatically Set Existing User`）。添加执行项时报 `Could not update flow` → 说明改的仍是内置原件 `first broker login`，回 3.2 复制一份再改。

### 3.4 挂到 IdP

**身份提供程序 → oidc → 高级设置 → 首次登录流程 = `first broker login - entra`** → 保存。

**看到**：回到 IdP 详情，首次登录流程回显为刚建的名字。

### 3.5 自动关联的安全前提

`Automatically Set Existing User` 等于"完全信任上游送来的用户名"。成立条件只有两个：

1. **上游可信**：单租户 + 只有我们能注册应用 + 签名校验开。任何一条破了都可能被伪造身份；
2. **用户名唯一且不撞**：AD 的 `sAMAccountName` 唯一，但如果 Entra 里存在 username 恰好叫 `admin` 的账号，它会被**自动绑到本地管理员账号**。切换前在 Entra 里按 `admin` 搜一次，确认为 0。

不满足就退回 `Confirm Link Existing Account`（需人工点确认），代价是首登多一步。

## 4. 用户名这一关（成败点）

> **动手前先看这条**：改 mapper 之前不要跑任何全量同步或批量导入（包括 `sync_sso_to_keycloak.ps1` 全量重跑）。模板改错时是"谁登录谁被改"，一次一个；先跑全量会按当时的模板批量造出带 `@` 的账号，之后改模板不会自动修，只能按 4.8 逐个处理。

### 4.1 它到底在做什么（先破一个误解）

Entra 令牌里的 `preferred_username` 是 UPN（`ligu@ap.inalfa.local`），Keycloak 里的 username 是 `login_name`（`ligu`）。中间只发生三件事：

1. **算**：IdP 的 mapper 按模板算出一个 username（本节唯一要改的就是这一处）；
2. **找**：首次登录拿这个值去查本地账号，**先按 email 查、再按 username 查**（25.0.6 `IdpCreateUserIfUniqueAuthenticator.checkExistingUser`）。查到就进"关联已有账号"分支，查不到就新建；
3. **写**：登录结束时，Target=LOCAL 的那条 mapper 把本地 username 写成模板值（`IdentityBrokerService` → `updateBrokeredUser` → `user.setUsername(modelUsername)`）。

所以：**比对是为了关联，不是为了改名**——模板算出来就是 `ligu` 时，关联后本地用户名前后一致，不会被改成 UPN。但它也不是只读：第 3 步每次 broker 登录都会执行，模板算错就是"谁登录谁被改"，一次一个，不会一次改 2798 个。

两个推论，排错时要用：

- **先 email 后 username**：本地账号的 email 若恰好等于 Entra 令牌里的 email，会按邮箱关联成功，跟用户名无关。看到"关联上的不是你以为的那个人"，先查邮箱。
- **改名不清组**：Keycloak 改 username 不动用户 id，组关系和联邦链接都还在。所以"组还在"不能证明用户名没被改，两处都要看（4.7）。

不做这一步的后果（模板算出来是完整 UPN 时）：

1. 每人新建一个 `ligu@ap.inalfa.local` → `ligu` 与 `ligu@ap.inalfa.local` 两套并存；
2. 组挂在 `ligu` 上，新账号不在组里 → 三个应用全部 403（应用报"未开通本系统访问权限"）；
3. `sync_sso_to_keycloak.ps1` 每天按 `login_name` 查 `/users?username=ligu&exact=true`，查到的是没走 broker 的老账号 → 每天都在建号，`kc_user_id` 反复被覆盖。

### 4.2 这台 25.0.6 上模板能写什么（按 25.0.6 源码查实）

组件：**身份提供程序 → `oidc` → Mappers → `Username Template Importer`**（providerId `oidc-username-idp-mapper`，分类 `Preprocessor`；列表里没有就"添加 mapper"新建一条）。要动的字段只有两个：`Template`（本节）与 `Target`（见 4.3，默认的 `LOCAL` 不要留着）。

**默认模板是 `${ALIAS}.${CLAIM.preferred_username}`** ——注意前面那段 `${ALIAS}.`，照默认值不动会算成 `oidc.ligu@ap.inalfa.local`。

支持的占位符只有三种：

| 写法 | 含义 |
|---|---|
| `${ALIAS}` | IdP 的 alias，这里是 `oidc` |
| `${UUID}` | 随机 UUID |
| `${CLAIM.<名字>}` | 令牌里的 claim，名字照原样写 |

**没有正则、没有 substring、没有 split**——模板本身不能"取前 N 位"或"按某个字符截断"。

`|` 后面能加的转换器只有三个：`uppercase`、`lowercase`、**`localpart`**（取最后一个 `@` 之前的部分；没有 `@` 就原样返回）。

- `localpart` 的依据：25.0.6 的 OIDC mapper 直接复用 SAML 的转换器静态表（`UsernameTemplateMapper` 里 `import static ...saml.mappers.UsernameTemplateMapper.TRANSFORMERS`，SAML 侧 `TRANSFORMERS.put("localpart", ...)` 并实现了 `getEmailLocalPart`）。
- **界面上看不出来**：OIDC 这个字段的帮助文本只写了 `uppercase` / `lowercase`，没提 `localpart`。界面不提，代码支持。

**写错转换器名不会报错**：代码是"查表取转换器，取不到就当不转换"，`|localPart`、`|local_part`、`|stripdomain` 都会被静默忽略，算出来仍是完整 UPN——这种最难查，改完必须按 4.7 实地看 username。

本实例侧还有两点没在这里证实，给出只读确认方式：

- 是否装过自定义的 IdP mapper（会覆盖原生行为）。在 Keycloak 主机上执行（只读）：
```powershell
C:\keycloak\bin\kcadm.bat get identity-provider/instances/oidc/mappers -r inalfa --fields name,identityProviderMapper,config
```
`identityProviderMapper` 全是 `oidc-username-idp-mapper` 即原生实现；出现别的名字要先看扩展文档。
- 是否真的生效：模板没有干跑模式，只能按 4.7 用 `ligu` 登录一次看结果。

### 4.3 Target 怎么选（验证阶段用 `BROKER_USERNAME`）

同一个 mapper 上还有 `Target`，它决定模板算出来的值往哪写。三个选项的差别只有一句：

| 选项 | 写到哪 |
|---|---|
| `LOCAL`（默认） | 本地账号的 username——用户列表里看到的那一列 |
| `BROKER_USERNAME` | 联邦身份记录里的 broker username——只存在于该用户与本 IdP 的关联记录里，本地账号的 username 不碰 |
| `BROKER_ID` | 联邦身份记录里的 user id（关联用的 `sub`）。本场景不要用：换了关联键，已有的关联会全部对不上 |

本场景：**验证阶段选 `BROKER_USERNAME`**。

理由是破坏半径。`LOCAL` 会在每次 broker 登录结束时执行 `user.setUsername(模板值)`（源码 `updateBrokeredUser`，条件是 Target=LOCAL 且 realm 未开 email-as-username）。模板一旦静默失效（转换器名写错、claim 取空），这个动作就是把本地 username 改成 `ligu@ap.inalfa.local`，原值不留痕、不可逆，还会连带打断所有按 `login_name` 查人的同步脚本。`BROKER_USERNAME` 只写关联记录：错了的表现是"关联不上、多建一个 UPN 账号"，本地 `ligu` 原样不动，删掉重建即可回退。

验证通过后是否改回 `LOCAL` 由现场决定。对已经正确的 `ligu`，两者结果相同，`LOCAL` 多出来的唯一动作是每次登录重写一次本地 username——没有收益，只有风险。

**换成 `BROKER_USERNAME` 后，验证判据要跟着变**：

- "本地 username 没变"**不能**再当模板生效的证据——这个 Target 下它本来就不会变；
- 是否真生效，看**联邦身份记录里的 username**：它存的就是 `context.getUsername()`，而 `BROKER_USERNAME` 会把这个值替换成模板结果（`IdentityBrokerService` 组装 `FederatedIdentityModel` 时取的就是它）。

先拿用户 id，再读关联记录（只读）：

```powershell
C:\keycloak\bin\kcadm.bat get users -r inalfa -q username=ligu --fields id
C:\keycloak\bin\kcadm.bat get users/<上一步返回的 id>/federated-identity -r inalfa
```

管理 REST 等价：`GET /admin/realms/inalfa/users/<id>/federated-identity`。

**判据**：数组里 `identityProvider` = `oidc`，`userName` = `ligu`。若是 `ligu@ap.inalfa.local`，说明模板没生效（转换器写错或 Template 还是默认值），按 4.4 的失败表排查——此时本地 `ligu` 仍是干净的，删掉新造的 UPN 账号重试即可。

> 记录里的值是全小写的：`getUsername()` 默认会把 broker username 转小写（除非 IdP 开了 Case sensitive original username），所以看到的是 `ligu` 而不是 `Ligu`。

**如果最终选 `LOCAL`，判据正好相反**：

- 证据在本地：用户 → `ligu` → `Details`，Username = `ligu`；
- 关联记录的 `userName` 这时反而是上游原始值（`ligu@ap.inalfa.local`），**不能拿来判断模板**——`LOCAL` 只改 `modelUsername`，不动 `context.getUsername()`；
- 破坏范围：谁登录谁被改，改完原值不留痕；2798 人不会一次全坏，但每个走过 Entra 登录的人都会被改，同步脚本与应用侧按 `preferred_username` 的口径同时失效。

**新建用户时本地 username 取哪个值（已按 25.0.6 源码查实）**：`BROKER_USERNAME` 下模板结果先写进 `context.getUsername()`；`IdentityBrokerService.authenticated()` 发现 `modelUsername` 为空时回落到 `context.getUsername()` 并回填，`IdpCreateUserIfUniqueAuthenticator` 再用 `modelUsername` 建号。所以**本地还不存在的人首次登录，建出来的 username 就是模板结果（`ligu`）**，与已有账号同一口径，不会出现"关联的人叫一个名、新建的人叫另一个名"。

两个例外：

- realm 开了 `Email as username`（Realm settings → Login）时，新建用户取 email、忽略模板——本实例该开关未验证，切换前看一眼；
- 模板算出空串（claim 缺失）不会触发上面的回落（空串不是 null），表现为首登失败或空用户名脏账号。

### 4.4 路 1（首选）：模板里用 `|localpart` 截掉域名

**前置**：不需要 Entra 侧任何改动。唯一要求是所有 UPN 的 `@` 后面是同一个域名（见下面的撞名提醒）。

**点哪里**：身份提供程序 → `oidc` → `Mappers` → 点 `Username Template Importer` 那一行，只改一个字段：

- `Template` 填 `${CLAIM.preferred_username | localpart}`
- `Target` 按 4.3 选 `BROKER_USERNAME`（验证阶段；改回 `LOCAL` 的条件见 4.3）

保存。

**生效确认**：按 4.7 用 `ligu` 走一遍，再按 4.3 的命令读联邦身份记录，`userName` 应为 `ligu`；同时用户列表里不应多出 `ligu@ap.inalfa.local`。

**失败会看到什么**：

| 现象 | 原因 |
|---|---|
| 记录里是 `oidc.ligu@ap.inalfa.local` | Template 还是默认值，`${ALIAS}.` 没删 |
| 记录里是 `ligu@ap.inalfa.local`，且不报错 | 转换器名写错（大小写、下划线），被静默忽略 |
| 新建了 `ligu@ap.inalfa.local`，原 `ligu` 没被关联 | 模板没生效或没保存；先停，按 4.8 查清单 |

**撞名提醒（唯一会让这条路出事的情况）**：如果租户里存在只在域名上不同的两个 UPN（`zhang@ap.inalfa.local` 与 `zhang@emea.inalfa.local`），截断后都叫 `zhang`，第二个登录的人会被**关联到第一个人的账号**——这是关联错人，比多建账号严重。上线前拿 Entra 导出的用户表按 UPN 前缀分组查一次重复（Excel 透视即可），有重复就单独处理那几个账号。

### 4.5 路 2：直接取 `onprem_sam_account_name`（不截断）

**前置（两条都要成立）**：

1. 账号是 Entra Connect 同步来的（PHS/PTA 都行），纯云账号没有这个属性；
2. 该租户的 **ID 令牌**能加这个可选声明。检查：Entra 管理中心 → 应用注册 → `Keycloak broker` → 令牌配置 → 添加可选声明 → 令牌类型选 **ID** → 看类型下拉里有没有 `onprem_sam_account_name`。
   - 有 → 勾上，保存；
   - 没有 → **这条路在本租户不成立**。不要用 claims mapping policy 补：它只作用于 SAML 令牌，OIDC 的 ID 令牌拿不到。

**单点确认属性存在**（Graph Explorer）：

```
GET https://graph.microsoft.com/v1.0/users/ligu@ap.inalfa.local?$select=onPremisesSamAccountName,userPrincipalName
```

`onPremisesSamAccountName` 返回 `ligu` → 属性在；为空 → 该账号是纯云账号，对路 2 无效。

**填法**：同一处 `Username Template Importer`：

- `Template` 填 `${CLAIM.onprem_sam_account_name}`
- `Target` 按 4.3 选 `BROKER_USERNAME`（验证阶段）

**先确认 claim 真的到了 Keycloak**（令牌在 Keycloak 与微软之间交换，浏览器里看不到）：

1. 再加两条 mapper：`Claim to Attribute`，claim `preferred_username` → 用户属性 `entra_upn`；claim `onprem_sam_account_name` → 用户属性 `entra_sam`，同步模式都是 IMPORT；
2. 用 `ligu` 走一次登录；
3. 用户 → 搜 `ligu` → `Attributes` 标签。

`entra_upn` 应为 `ligu@ap.inalfa.local`；`entra_sam` 应为 `ligu`。为空先分清是"可选声明没加"还是"这个账号没有该属性"——换一个同步账号再试一次即可区分。

**失败会看到什么**：claim 不在令牌里时，模板把该占位符替换成**空串**（源码里 `value == null → ""`，不报"缺少字段"），username 变空 → 首登直接失败，或建出一个 username 为空的脏账号。看到空用户名就别继续点，先回上面查 claim。

### 4.6 路 3（兜底）：username 就用完整 UPN

**填法**：`Template` 填 `${CLAIM.preferred_username}`，`Target` 选 `LOCAL`（这条路的目的就是让本地 username 变成 UPN）；或者干脆不加这条 mapper（此时 Keycloak 默认就拿 `preferred_username` 当 model username）。想先只验证不写本地，可先用 `BROKER_USERNAME` 看记录，确认后再切。

**会发生什么**：已有的 `ligu` 与 `ligu@ap.inalfa.local` 不相等，首登查不到 → 新建一个 UPN 账号（除非恰好命中 email，见 4.1），组不在里面 → 三个应用 403；原来的 `ligu` 从此只有本地密码能登。

**连带要改的东西（缺一不可）**：

- 组：给每个 UPN 账号重新授 `app-msia` / `app-bol` / `app-ics`，或改授组口径；
- `CN_AME_SSO_UserMap`：加 UPN → 本地账号的映射；
- `sync_sso_to_keycloak.ps1`、`assign_groups_from_ledger.ps1`：两者都按 `login_name` 查人，输入口径要一起改成 UPN，否则每天重复建号；
- 应用侧：MSIA/BOL 用令牌里的 `preferred_username` 找本地用户，UPN 找不到 → 自动建最低权限账号（"登录成功但数据全空"）。

**判据**：只有 4.4 的撞名问题无法解决、且 4.5 租户不支持可选声明时才选它，并把这四项一起排进工期。不要把路 3 当"先跑起来再说"，它会把 4.1 的三连后果全部落地。

### 4.7 先验后放：只用 `ligu` 走一遍

只放一个人。放之前确认：模板已保存、`first broker login - entra` 已挂在 `oidc` 上、Entra 侧"需要分配"里只加了试点人员。

操作：浏览器打开 `https://iame.ap.inalfa.local:8443/realms/inalfa/account/` → 点 `Entra ID` → 用 `ligu` 的 Entra 账号登完 → 回到账户页。

**必须同时看这三处**：

| 看哪里 | 该看到 | 不该看到 |
|---|---|---|
| 用户 → 搜 `ligu` → `Details` | Username = `ligu` | `oidc.ligu@...`、`ligu@ap.inalfa.local` |
| 同页 `Identity provider links` 标签（旧版 UI 叫 `Federated identity`） | 一条 `oidc` 链接，`User ID` 是 Entra 的对象 id | 空；或出现第二条指向新账号 |
| 同页 `Groups` 标签 | `app-msia` / `app-bol` / `app-ics` 中这个人本来该有的组 | 组没了（说明关联到了别的账号） |

> 用 4.3 的 `BROKER_USERNAME` 时，**第一行不算证据**：本地 username 本来就不该变。模板是否生效看第二行那条链接的 `userName`（用 4.3 的 kcadm 命令读），正确值是 `ligu`。

**再退出去重登一次**：第一次登录走的是"建/关联"分支，第二次走的是"已有用户直接过 broker"那条路。两次之后本地 username 与链接的 `userName` 都仍是 `ligu`，才算真的稳。

**任何一处不符就停**：不要在同一个 IdP 上继续加第二个人，也不要在这里改模板试探——先按 4.8 查清楚有没有已经造出来的带 `@` 账号。

### 4.8 已经出现带 `@` 的账号：先查清单，再决定

只读脚本，不改任何数据：

```powershell
C:\sso\scripts\find_at_username_users.ps1 -Realm inalfa
```

脚本用 Keycloak 管理 REST 的 GET（只读）拉全量用户，筛出 username 含 `@` 的，逐条补三样信息：有没有 IdP 链接、链接到哪个 IdP、在几个组里。输出 `C:\sso\tmp\at_username_users_<时间戳>.csv`。

首次使用先把这个文件从仓库 `scripts\powershell\find_at_username_users.ps1` 复制到 `C:\sso\scripts\`。运行时会弹框要 Keycloak 管理员凭据（默认 `master` realm，管理员在 `inalfa` 里就加 `-AdminRealm inalfa`），凭据只用来换令牌，不落盘。

| 列 | 怎么读 |
|---|---|
| `CreatedTime` | 早于本次改模板 → 历史遗留；晚于 → 模板改好之前造的 |
| `FederatedIdp` 为空 | 不是 broker 建的（手工或脚本导入），跟这次改动无关 |
| `FederatedIdp` = `oidc` | 这个人已经走过 Entra 登录，账号是 broker 建的或关联的 |
| `GroupCount` = 0 | 新账号没继承组，属于"能登但 403"的那批 |

**清理动作本节不给**：看到清单后按人决定——留哪些、删哪些、先解绑还是先改名，取决于这个账号有没有业务数据、`CN_AME_SSO_UserMap` 有没有引用它。脚本到此为止，不做任何删除。

### 4.9 批量核对（只读脚本）

```powershell
C:\sso\scripts\compare_upn_login.ps1 -EntraCsvPath C:\sso\tmp\entra-users.csv
```

先生成清单（Graph，列名固定，避免本地化表头）：

```
GET https://graph.microsoft.com/v1.0/users?$select=userPrincipalName,onPremisesSamAccountName,mail,accountEnabled&$top=999
```

脚本只读 `CN_AME.dbo.CN_AME_SSO_User`，输出 `C:\sso\tmp\upn_login_diff_<时间戳>.csv`，分类为：

| 分类 | 含义 | 走哪条 |
|---|---|---|
| `OK` / `OK_CASE` | UPN 前缀与 `login_name` 一致（后者仅大小写不同） | 路 1 |
| `PATH2` | 前缀不一致，但 `onPremSamAccountName` 对得上 | 路 2 |
| `PATH3` | 两者都对不上，只有 UPN | 路 3，或先治理数据 |
| `NOT_IN_ENTRA` | 中央表有、Entra 没有 | 这批人切过去登不上，先补账号 |
| `NO_UPN` | Entra 记录缺 UPN | 数据异常 |

**判据**：`OK+OK_CASE` 占绝对多数 → 走路 1（4.4）；`PATH2` 集中出现 → 按 4.5 实测路 2；`PATH3`/`NOT_IN_ENTRA` 超过 1% → 先处理数据再切。

## 5. 本地账号并存

`admin` 与 39 个共享信箱账号（共 40 个）走**本地密码**，它们不是真人、联邦过去没人能校验密码。因此：

1. **登录页必须同时保留表单入口**。不要在 `browser` 流程里加 `Identity Provider Redirector` 并设置默认 IdP——那会让登录页直接 302 到微软，本地账号连表单都看不到。
2. **三个应用都不要传 `kc_idp_hint`**。现在也没传，保持现状即正确。

| 应用侧行为 | 用户看到 |
|---|---|
| 不传 `kc_idp_hint`（现状） | Keycloak 登录页，上面是"Entra ID"按钮，下面是用户名密码表单。两条路都能走 |
| 传 `kc_idp_hint=oidc` | 直接跳微软，**表单不可见**。该入口下 `admin` 无法登录 |
| 传空值 `kc_idp_hint=` | 回到表单（用来做单个客户的"本地登录"入口） |

MSIA 的 `[security] local_login_enabled` 与 BOL 的 `db_config.ini [auth] local_auth_enabled` 是**应用自己的**本地账号，跟以上无关，保持现状。

## 6. 切换与回滚

### 6.1 备份

| 对象 | 做法 | 备注 |
|---|---|---|
| 中央表 | 备份 `CN_AME_SSO_User`、`CN_AME_SSO_PermLedger`、`CN_AME_SSO_UserMap`、`CN_AME_SSO_SyncLog` 与 `StgAdUser` | 这是唯一底账 |
| realm | `C:\keycloak\bin\kc.bat export --dir C:\sso\kc-export\pre-entra --realm inalfa --users per_file` | **不含可用口令，不是还原点**，只用于回查 IdP/组的配置 |
| Entra 侧 | 记下 client ID、secret 到期日、重定向 URI 原文、可选声明列表 | 截图即可 |

### 6.2 灰度与试点顺序

1. Entra 侧"需要分配"= 是，只放 2–3 人（含 `ligu`）；
2. 保留登录页表单入口，从 `https://iame.ap.inalfa.local:8443/realms/inalfa/account/` 点"Entra ID"走通一次；
3. 试点应用顺序：**MSIA → Capacity → BOL**。MSIA 的 OIDC 日志与错误页最完整（有一份专门的新用户测试手册），出问题定位最快；BOL 的对外地址还没定稿（clients.md U2），放最后；
4. 每个应用过完 6.3 再进下一个；全绿后把"需要分配"改回否（`Hide on login page` 全程保持关）。

### 6.3 每个应用要验到的项

- 登录页出现"Entra ID"按钮，点进去**不再输一次密码**（域内已登录的设备）；
- 回调后 `/realms/inalfa/account` 里 username 是 `ligu`，**不是** `ligu@ap.inalfa.local`；
- 同页能看到组 `app-msia` / `app-bol` / `app-ics`；
- 进业务页面看到**数据**（不是只看拿到 token）：MSIA 打开一条评审项、Capacity 打开一个计划页、BOL 打开一条记录；
- 退出登录回到应用登录页，无 `Invalid redirect uri`；
- 用 `admin` 走表单能登（证明本地入口还在）。

### 6.4 回滚：先确认你在哪个状态

停用 IdP（`Enabled` 关）之后用户回到 Keycloak 表单 + **本地密码**校验。这一步能不能救场，取决于 2798 个账号有没有本地密码：

```sql
SELECT pwd_set, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
WHERE employee_no <> 'admin' AND source <> 'MANUAL'
GROUP BY pwd_set;
```

| 现场状态 | 停用 IdP 后 | 真正的回滚动作 |
|---|---|---|
| 路线 A 已落地：本地账号已清空、用户由 LDAP 联邦提供（Keycloak 里 `federationLink` 非空） | 表单把密码交给 AD 校验，**能登**，10 分钟收工 | 无需额外动作 |
| 路线 A 未落地：2798 个本地账号还在、`pwd_set=0` 占绝大多数 | 表单要本地密码，**这批人一个都登不进** | 先 `Enable-ScheduledTask -TaskName 'SSO_AD_Import'`，再按 `sync_sso_to_keycloak.ps1` 全量重跑（重建账号 + 补发设密邀请），或直接启用 LDAP 联邦；这是一次真实的账号重建，不是"点一下开关" |

`admin` 是本地账号且 `pwd_set=1`，两种状态下都能登——它是最后的兜底，不是方案。

### 6.5 回滚演练（切换前必须做一次）

把 IdP 的 `Enabled` 关掉 → 用 `admin` 走表单登一次 → 用 `ligu` 走表单登一次（这一步就能暴露 6.4 的状态判断对不对）→ 重新启用。

## 7. 回给 IT 的一页说明（可直接转发）

> 下面整段可以原样发给对方，按编号回一行即可。我们这边已经拿到租户 ID、客户端 ID 与 discovery 地址，不再需要重复提供。

应用注册 `Keycloak broker`（客户端 ID `b1407c3f-4999-4950-9223-905d14567f18`）：

1. 请确认**重定向 URI** 已登记为 `https://iame.ap.inalfa.local:8443/realms/inalfa/broker/oidc/endpoint`，且平台类型是 **Web**（不是"单页应用程序"）。
2. 请确认这个地址的 **8443 端口**可以接受——我们不对外暴露 443，登录成功后由微软把浏览器重定向回内网 8443。

凭据：

3. 请提供这个 client secret 的**到期日**（应用注册 → 证书和密码 → 客户端密码 → `Expires` 列），我们据此排轮换时间。
4. 首次交付的这个 secret 是明文发出的，上线前我们会请你**重新签发一次**，届时配合即可。

租户与登录策略：

5. 请告知租户的**许可档位**（Entra ID Free / P1 / P2）。
6. 请告知 **MFA 与条件访问**现状：是否强制 MFA、是否有按位置/设备/IP 的策略——这些策略会作用在 Keycloak 上联 Entra 的这次登录上，配好之后才看得出会不会拦人。

账号口径（决定我们这边用户名怎么映射）：

7. 请告知 Entra Connect 的同步模式（PHS / PTA / ADFS）以及同步范围是否覆盖全部约 2800 个账号。
8. 请确认全量账号的 **UPN 前缀与 sAMAccountName 是否一致**，以及 ID 令牌里能否添加 `onprem_sam_account_name` 可选声明。

回复格式（照抄后填）：

```
1. 已登记，平台 Web / 未登记
2. 接受 8443 / 不接受（原因）
3. 到期日：____
4. 收到，上线前配合重签
5. 许可档位：____
6. 强制 MFA：是/否；条件访问策略：无 / 有（简述）
7. 同步模式：____；覆盖范围：____
8. UPN 与 sAMAccountName：一致 / 不一致；可选声明：可加 / 不可加
```
