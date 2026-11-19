# Keycloak 25.0.6 控制台配置手册（零基础 · 照着屏幕点）

> **怎么用这份手册**：从第 1 节开始，按顺序照着屏幕点；每节最后都有一句"✅ 做到这里你应该看到……"，看到了再往下走，没看到就停在原地处理。
> 前置：`IRSCnKettle01` 上的 Keycloak 25.0.6 已经作为服务跑起来，`kcadmin` 账号已建好（见 `docs/keycloak-deploy-runbook.md` 10.7）。
> 命令行的等价做法（`kcadm`）在 [keycloak-realm-clients-init.md](./keycloak-realm-clients-init.md)，本文只用界面，不要求你敲命令。
> 本文不包含任何真实口令；需要填口令的地方一律写 `<你的 kcadmin 口令>`。
>
> **修订记录（2026-11-09，第二轮）**：按《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 / §9.5 对齐——§4.3 发件人改为 `ap_sso@inalfa.com`、显示名 `Inalfa AME系统统一身份认证`；§4.6 会话改为 `SSO Session Idle = 1 天`、`SSO Session Max = 7 天`（原 8 小时 / 12 小时作废）。暴力破解维持 5 次 / 900 秒（本轮无变更）。

**关于界面长相的说明（很重要，先看这段）**

Keycloak 25.0.6 默认是"经典控制台"：左侧竖排菜单（`Realm Settings`、`Clients`、`Groups`…），点 `Clients → Create` 是**一页表单**，保存后在同一页出现 `Settings / Credentials / Mappers` 等页签。

Keycloak 26 换成了新版控制台：`Clients → Create client` 变成**三页向导**（`General settings → Capability config → Login settings`，每页点 `Next`）。

如果你打开时看到的是三页向导，说明界面是新版风格——**字段名完全一样**，按下面每张表里的"字段名"去找即可，对应关系是：

| 新版向导页（26 风格） | 25.0.6 经典界面里在哪 |
|---|---|
| General settings（第一页） | `Clients → Create` 那一页表单的 `General` 区 |
| Capability config（第二页） | 保存后 `Settings` 里的 `Capability config` 区 |
| Login settings（第三页） | 保存后 `Settings` 里的 `Access settings` 区 |

本文按 25.0.6 经典界面写；凡是两个版本叫法不同的按钮，会写成"`X`（新版叫 `Y`）"。**认字段名，不认位置。**

---

## 1. 打开控制台并确认"我在 master 域里"

### 1.1 访问地址

在服务器 `IRSCnKettle01` 上用浏览器打开：

```text
https://localhost:8443
```

> 为什么用 `localhost` 而不是 IP：8443 用的是自签证书，证书上的名字是 `localhost`。用 `127.0.0.1` 或服务器 IP 打开，浏览器会因为"名字对不上"报更严重的错误；用 `localhost` 只会提示"证书不受信任"，点过去就行。

### 1.2 过掉证书警告（自签证书，正常现象）

| 浏览器 | 点哪里 |
|---|---|
| Chrome / Edge | 页面出现"您的连接不是私密连接" → 点 **高级** → 点 **继续前往 localhost（不安全）** |
| Firefox | 点 **高级** → 点 **接受风险并继续** |

看到地址栏出现红色/灰色的"不安全"标记是**预期的**，不要为此去找证书。

### 1.3 登录

首页会出现 `Welcome to Keycloak` 页面，点 **Administration Console**（管理控制台），进入登录页：

- `Username or email`：`kcadmin`
- `Password`：`<你的 kcadmin 口令>`
- 点 **Sign In**

### 1.4 确认"我现在在 master 域"

登录后看**左上角**：有一个显示当前域的按钮/下拉框，文字是 **`master`**。

- 是 `master` → 对，继续。
- 是别的名字（比如 `inalfa`）→ 说明你之前切过域，点左上角下拉，选回 `master`。

> 为什么要确认：后面所有"建 realm"的动作都必须站在 `master` 上做。站在别的域里做，页面会长得一样，但你会把东西建错地方。

✅ **做到这里，你应该看到**：左上角写着 `master`，左侧一竖排菜单（`Realm Settings`、`Clients`、`Groups`、`Users`…），右上角是你的用户名 `kcadmin`。

---

## 2. 动手前先自查：issuer 是不是对的

这一步只看不改。issuer 是"Keycloak 对外宣称自己是谁"的地址，两个业务系统就是靠它认人的；它错了，后面全白做。

### 2.1 走到哪里看

1. 左侧菜单点 **Realm Settings**（领域设置）
2. 上方页签点 **General**（常规）
3. 页面往下滚，找到 **Endpoints**（端点）区域
4. 点其中的 **OpenID Endpoint Configuration**（OpenID 端点配置）

会新开一个标签页，显示一大段 JSON。找第一行的 `"issuer"`。

### 2.2 看到什么算对

期望值（master 域）：

```text
https://sso.ap.inalfa.local/realms/master
```

逐项对照：

| 检查点 | 对 | 不对 |
|---|---|---|
| 域名 | `sso.ap.inalfa.local` | `localhost`、`127.0.0.1`、服务器 IP |
| 端口 | **没有端口**（就是 `https://域名/...`） | 带 `:8443` |
| 结尾 | `/realms/master`，最后没有 `/` | 多一个斜杠、或域名叫错 |

### 2.3 看到什么算"先停下来找我"

只要出现下面任一情况，**不要继续往下建 realm**，把 JSON 截图发出来：

- `issuer` 里是 `localhost` 或 IP；
- `issuer` 里带 `:8443`；
- 打不开（404 / 报错页）。

原因：这说明 `hostname` / `hostname-port` 的配置和两系统代码里的 issuer 不一致，属于服务器配置问题，不是界面操作能修的。

✅ **做到这里，你应该看到**：JSON 里 `"issuer": "https://sso.ap.inalfa.local/realms/master"`，没有端口、没有 localhost。看完把新标签页关掉，回到控制台。

---

## 3. 创建 realm `inalfa`

### 3.1 点哪里

1. 左上角点当前域的下拉（那个写着 `master` 的按钮）
2. 下拉里点 **Add realm**（新版叫 **Create Realm / Create realm**）
3. 进入 `Add Realm` 页面，只有一个必填框 **Name**：
   - 填 `inalfa`
   - 其余（`Enabled`、`Display Name`）先不动

> `inalfa` 必须一模一样、全小写。这个名字会进 URL（`/realms/inalfa`），两系统代码里写死了，打错后面全对不上。**建完不能改名，只能删了重建。**

4. 点 **Create**

### 3.2 成功后是什么样

- 左上角下拉从 `master` 变成 **`inalfa`**
- 左侧菜单还是那一排（`Realm Settings`、`Clients`、`Groups`…），但页面内容变成新 realm 的
- 会看到 "You are now viewing the inalfa realm" 之类的提示条

### 3.3 马上补一个显示名（可选但建议）

1. 左侧 **Realm Settings → General**
2. **Display Name** 填 `统一身份认证`
3. **Display Name HTML** **留空**（这里能吃 HTML，留空最安全）
4. 右上角 **Save**

✅ **做到这里，你应该看到**：左上角是 `inalfa`，Realm Settings → General 里的 Display Name 显示"统一身份认证"。

---

## 4. 逐个配置 realm 设置

> 原则：**只改本文列出的项；没列的一律保持默认，不要顺手改。** 每改完一个页签，点右上角 **Save**，再切下一个页签。

### 4.1 General（常规）

| 字段（界面英文） | 设成 | 为什么 / 设错的后果 |
|---|---|---|
| `Enabled` | ON（默认） | 关掉后整个 realm 的登录页直接 404 |
| `Display Name` | `统一身份认证` | 只影响显示 |
| `Display Name HTML` | 留空 | 填 HTML 会被渲染，等于给了改页面的口子 |
| `Require SSL` | **保持 `External requests`（默认）** | 改成 `None` 会让明文 HTTP 也能登录，凭据可被嗅探；改成 `All requests` 会让本机排查也报 HTTPS 错误 |
| `Endpoints` 区 | 不动 | — |

### 4.2 Login（登录）

页签 **Login**，以下开关全部按表：

| 字段 | 设成 | 为什么 / 设错的后果 |
|---|---|---|
| `User Registration`（用户自助注册） | **OFF** | 人员只能从中央表同步来；开了等于任何人都能自己注册进统一身份 |
| `Forgot Password`（忘记密码） | **ON** | 用户自助设密/改密要靠它 |
| `Remember Me` | OFF | 减少长期凭据面 |
| `Email as Username` | OFF | 我们用 `login_name` 当用户名 |
| `Login with Email` | OFF | 同上，避免一个邮箱对应多个账号时歧义 |
| `Duplicate Emails` | OFF | 邮箱允许为空/重复，但登录不用邮箱，所以这里只为规范 |
| `Verify Email` | OFF | 前期没有可用的验证邮件闭环，开了会卡住设密流程 |
| `Edit Username` | OFF | 用户名是人员唯一键，禁止用户自己改 |

> 这几个开关在有些小版本放在 `General` 页签里，名字不变：看到 `User Registration` 就按表设。

### 4.3 Email（邮件）

页签 **Email**，填 SMTP（用于设密邀请、忘记密码邮件）：

| 字段 | 填什么 |
|---|---|
| `From` | `ap_sso@inalfa.com` |
| `From Display Name` | `Inalfa AME系统统一身份认证` |
| `Host` | `172.19.253.10` |
| `Port` | `25` |
| `Authentication`（需要账号密码） | **OFF**（本环境不需要认证） |
| `Username` / `Password` | 因为上一项 OFF，这两个框是灰的/不用填 |
| `Enable SSL` | **OFF** |
| `Enable StartTLS` | **OFF** |
| `Reply To` / `Envelope From` | 留空 |

点 **Save**，然后可选：滚到底部 **Test Connection**，`To Email` 填你自己的邮箱 → **Test**，弹出绿色成功提示即可。

> **Test Connection 只证明「连得上、能握手」，不证明「信能到」**。真正的判据是**实际收到一封验证信**（用测试账号触发一封设密/改密邮件，确认收件箱确实收到）。

> 当前是**内网明文中继**；若后续邮件网关启用 STARTTLS，把 `Enable StartTLS` 改为 ON（必要时同步调整端口），保存后**重新实测发信**。

> 设错的后果：SSL/StartTLS 误开，邮件会一直发不出去，而界面只报"Failed to send email"，很难看出根因。

### 4.4 Tokens（令牌）

页签 **Tokens**（有的版本这些项在 `Sessions` 里，认字段名）：

| 字段 | 设成 | 为什么 / 设错的后果 |
|---|---|---|
| `Access Token Lifespan` | `15` + 单位 `Minutes` | 两系统校验过期用这个；设太短会频繁重登，设太长泄令牌风险大 |
| `Access Token Lifespan For Implicit Flow` | 保持默认 | 我们禁用 Implicit，用不到 |
| `Revoke Refresh Token` | 保持默认（OFF） | 改了会影响刷新行为，无必要 |
| `Refresh Token Max Reuse` | 保持默认 | 同上 |
| `Action Token Generated By User Lifespan` | `4320` + 单位 `Minutes`（= 3 天） | 设密邀请邮件的有效期；默认 5 分钟，用户还没点开就失效了 |
| 其余（各类 Timeout / Signature 算法） | **保持默认** | — |

### 4.5 Security Defenses（安全防护）

页签 **Security Defenses**：

| 字段 | 设成 |
|---|---|
| `Brute Force Detection`（暴力破解检测） | **ON** |
| `Max Login Failures` | `5` |
| `Wait Increment` | `900` + `Seconds` |
| `Max Wait` | `900` + `Seconds` |
| `Quick Login Check Milli Seconds` | 保持默认 `1000` |
| `Minimum Quick Login Wait` | 保持默认 `60` + `Seconds` |
| `Failure Reset Time` | 保持默认 |
| `Headers` 区（X-Frame-Options 等） | **保持默认，不要动** |

> 设错的后果：`Max Login Failures` 设成 0 或关掉检测，等于允许无限次撞密码；`Max Wait` 设得很大，用户被锁后几小时进不来。

### 4.6 Sessions（会话）

页签 **Sessions**：

| 字段 | 设成 |
|---|---|
| `SSO Session Idle` | `1` + `Days`（= 86400 秒） |
| `SSO Session Max` | `7` + `Days`（= 604800 秒） |
| `Client Session Idle` / `Client Session Max` | 保持默认 `0`（跟随 SSO 会话） |
| `Offline Session Idle` / `Offline Session Max` | 保持默认 |

> 设错的后果：Idle 设得很小（如 5 分钟），用户填表时就被踢下线；设成 0 以外的超大值，离职人员会话长期不失效。

### 4.7 Events（事件）

页签 **Events**：

| 区域 | 字段 | 设成 |
|---|---|---|
| User events settings | `Save Events` | **ON** |
| User events settings | `Expiration` | `90` + `Days` |
| Admin events settings | `Save Events` | **ON** |
| Admin events settings | `Include Representation` | **ON**（记录"改前/改后"内容，审计才有意义） |
| Admin events settings | `Expiration`（如果这个版本有这一栏） | `90` + `Days`；没有就留默认 |
| `Event Listeners` | 不动 | — |

> 设错的后果：`Save Events` 关掉后，登录失败、被锁、管理员改配置全都查不到，出事无法追溯。

### 4.8 User Profile（用户档案）

页签 **User Profile**（有的版本在左侧菜单单独一项）：

| 字段 | 设成 |
|---|---|
| `Enabled`（启用声明式用户档案） | **保持 ON（默认）** |
| 属性列表（`username`、`email`、`firstName`、`lastName`） | **不要删、不要改必填** |

> 设错的后果：关掉它或删掉 `username`，注册/设密流程会报 "Account is not fully set up"，用户永远进不去。

### 4.9 其余页签一律不动

`Themes`（保持默认 `keycloak` 主题）、`Keys`（密钥自动生成，别动）、`Localization`（不需要）。

✅ **做到这里，你应该看到**：`Realm Settings` 里 General/Login/Email/Tokens/Security Defenses/Sessions/Events/User Profile 八个页签都按上表设好并已 Save；Email 页签的 Test Connection 成功（绿条）。

---

## 5. 建两个准入组

组的名字会作为 `groups` 声明出现在登录令牌里，两系统用它判断"这个人能不能进"。

### 5.1 点哪里

1. 左侧 **Groups**
2. 右上角点 **New**（新版叫 **Create group**）
3. `Name` 填 `app-msia`
4. 点 **Save**

重复一次，建 `app-bol`。

### 5.2 注意事项

- 必须是**顶层组**（不要在别的组下面建"子组"），建完列表里 `Path` 显示 `/app-msia` 才是对的。
- 名字**全小写、带连字符**，和代码里的 `required_group` 一模一样，不能写成 `APP-MSIA` 或 `app_msia`。

✅ **做到这里，你应该看到**：Groups 列表里两行：`/app-msia`、`/app-bol`。

---

## 6. 建 client（最细的一节）

### 6.0 先理解三个词

- **client** = "允许来我们这里登录的应用"。一个应用一个 client。
- **Client Authentication 开/关**：开 = 应用有密码（confidential），后端能保存 secret；关 = 公开应用（public），谁都能冒充。
  - **一开一关多出什么**：打开 `Client Authentication` 之后，下面才会出现（或才变成可勾选）`Service Accounts Roles` 和 `Authorization` 两个开关。这两个只在"应用有密码"时才允许使用。
- 我们四个 client 的定位：

| Client ID | 是谁 | 认证方式 | 要开的流 |
|---|---|---|---|
| `msia-prod` | MSIA Report 后端 | 有密码（confidential） | 仅授权码（Standard Flow） |
| `bol-prod` | BOL 管理系统后端 | 有密码 | 仅授权码 |
| `sync-client` | 同步脚本（机器对机器） | 有密码 + 服务账号 | **Service Accounts Roles**（不开授权码） |
| `account` | Keycloak 自带 | 公开 | 不用建，确认存在即可 |

### 6.1 建 client 的通用流程（25.0.6 经典界面）

1. 左侧 **Clients** → 右上角 **Create**（新版叫 `Create client`）
2. 进入 `Add Client` 页面，中间有个 **General** 表单：
   - `Client ID`（必填）
   - `Name`
   - `Client Protocol`：下拉选 **`openid-connect`**
   - `Root URL`（可以先填应用根地址，也可以留空）
   - 上面的"Import"区域**不要用**（那是导入 JSON 的）
3. 点 **Save**
4. 保存后停在这个 client 的 **Settings** 页，往下依次改三块：
   - `Access settings`（回调地址、跨域）
   - `Capability config`（认证方式、各种流）
   - `Login settings` / `Advanced settings`（PKCE、令牌时长）
   - 每改完一块，点该块下方的 **Save**（不要等全部改完再点一次）

> 新版三页向导的话：第 1 页填 `Client ID / Name / Client type(OpenID Connect) / Root URL` → `Next`；第 2 页就是 `Capability config` → `Next`；第 3 页就是 `Access settings`（含 redirect）→ `Save`。**字段和下面表格一一对应。**

### 6.2 `msia-prod` 逐字段填写表

**第 1 步：Add Client 表单**

| 界面字段 | 填什么 |
|---|---|
| `Client ID` | `msia-prod` |
| `Name` | `MSIA Report` |
| `Client Protocol` | `openid-connect` |
| `Root URL` | `http://172.26.2.203:8078` |

→ **Save**

**第 2 步：Settings → Access settings**

| 界面字段 | 填什么 | 说明 |
|---|---|---|
| `Root URL` | `http://172.26.2.203:8078` | 应与上一步一致 |
| `Home URL` | `http://172.26.2.203:8078` | 控制台跳转用，可留空 |
| `Valid Redirect URIs` | 一行：`http://172.26.2.203:8078/api/auth/oidc/callback` | 见第 7 节 |
| `Base URL` | 留空 | — |
| `Admin URL` | 留空 | — |
| `Web Origins` | `http://172.26.2.203:8078` | 只填 scheme+域名+端口，不带路径；不要填 `*` |

→ **Save**

**第 3 步：Settings → Capability config**

| 界面字段 | 设成 |
|---|---|
| `Client Authentication` | **ON** |
| `Authorization` | OFF（默认） |
| `Standard Flow` | **ON** |
| `Implicit Flow` | OFF |
| `Direct Access Grants` | **OFF** |
| `Service Accounts Roles` | OFF（开了 `Client Authentication` 后这个框才出现/可点） |

→ **Save**

**第 4 步：Settings → Advanced settings（新版在 Login settings；若在本页找不到，去另一块找，字段名不变）**

| 界面字段 | 设成 |
|---|---|
| `Proof Key for Code Exchange Code Challenge Method` | **`S256`** |
| `Access Token Lifespan` | 留空（继承 realm 的 15 分钟） |
| `Consent Required` | OFF |
| `Frontchannel Logout` | **OFF**（新版默认就是 OFF；不要开） |

→ **Save**

### 6.3 `bol-prod` 逐字段填写表

**第 1 步：Add Client 表单**

| 界面字段 | 填什么 |
|---|---|
| `Client ID` | `bol-prod` |
| `Name` | `BOL 管理系统` |
| `Client Protocol` | `openid-connect` |
| `Root URL` | `http://127.0.0.1:8090`（**这是占位地址，等业务方定稿再补**） |

→ **Save**

**第 2 步：Access settings**

| 界面字段 | 填什么 |
|---|---|
| `Root URL` | `http://127.0.0.1:8090` |
| `Home URL` | `http://127.0.0.1:8090` |
| `Valid Redirect URIs` | **两行**（见第 7 节）：<br>`http://127.0.0.1:8090/api/auth/oidc/callback`<br>`http://127.0.0.1:8090/api/auth/oidc/callback/` |
| `Web Origins` | `http://127.0.0.1:8090` |

→ **Save**

**第 3、4 步**：与 `msia-prod` 完全一致（Client Authentication ON、Standard Flow ON、其余 OFF、PKCE = S256、Frontchannel Logout OFF）。

### 6.4 `sync-client` 逐字段填写表

**第 1 步：Add Client 表单**

| 界面字段 | 填什么 |
|---|---|
| `Client ID` | `sync-client` |
| `Name` | `SSO Sync` |
| `Client Protocol` | `openid-connect` |
| `Root URL` | **留空**（它不发起浏览器登录） |

→ **Save**

**第 2 步：Capability config**

| 界面字段 | 设成 |
|---|---|
| `Client Authentication` | **ON** |
| `Authorization` | OFF |
| `Standard Flow` | **OFF** |
| `Implicit Flow` | OFF |
| `Direct Access Grants` | OFF |
| `Service Accounts Roles` | **ON** |

→ **Save**

**第 3 步：Access settings**：`Valid Redirect URIs`、`Web Origins` **全部留空**。

### 6.5 `account`（不要新建）

在 **Clients** 列表里搜 `account`，确认它是 `Enabled` 即可。它是 Keycloak 自带的，用来承载"邀请设密"邮件的落地页。**不要改它、不要删它。**

✅ **做到这里，你应该看到**：Clients 列表里 4 行：`account`、`bol-prod`、`msia-prod`、`sync-client`；点开 `msia-prod`，`Capability config` 里 `Client Authentication` 是 ON、`Standard Flow` 是 ON、`Direct Access Grants` 是 OFF。

---

## 7. `Valid Redirect URIs` 这一栏讲透（最容易填错）

### 7.1 它在哪

`Clients` → 选中 client → `Settings` → **`Access settings`** 区（新版向导里是第 3 页 `Login settings`）。是一个**多行文本框**，不是单行输入框。

### 7.2 怎么填

- **一行一个完整地址**，必须写全：`http://` + 域名/IP + 端口 + 路径。
- 不要写引号、不要写逗号、不要写空格。
- 填错一个字（少个斜杠、http 写成 https、端口差一位），登录就会报 `Invalid parameter: redirect_uri`。

### 7.3 尾斜杠到底影响什么

Keycloak 是**逐字符严格比对**：应用发过来的回调地址，必须和这里某一行**一字不差**。

本项目一个真实的坑：BOL 的框架（Django）把回调路由定义成带尾斜杠的 `/api/auth/oidc/callback/`，但配置文件里写的是不带斜杠的 `.../callback`。不带斜杠的请求会被 301 跳到带斜杠的地址，多一跳；虽然通常还能走通，但排查时很容易以为 Keycloak 配错了。

所以 `bol-prod` **两行都填**（带斜杠 + 不带斜杠），两边都能对上，切换期不用纠结。

### 7.4 以后加正式域名：**直接在框里另起一行**

这是界面上最安全的地方：

- 你在文本框里**保留旧行、新增一行**，点 Save —— **天然就是"追加"，不会覆盖**。
- 这和命令行 `kcadm update -s redirectUris=[...]` 完全不同：命令行是**整体替换数组**，只提交新值会把旧值冲掉。

所以：**改 redirect 请用界面。** 流程是：

1. 在框里旧的 `http://...` 那一行下面，另起一行写新的 `https://bol.ap.inalfa.local/api/auth/oidc/callback`
2. Save
3. 改应用配置、重启应用
4. 用新地址完整登录一次，确认没问题
5. 观察 1–2 个工作日
6. 再回到这个框，**删掉旧行**，Save

### 7.5 现在能填 vs 必须等定稿

| 类型 | 例子 | 现在能填吗 |
|---|---|---|
| 本机联调 | `http://127.0.0.1:8090/...` | ✅ 能（BOL 现在就是它） |
| 内网 IP:端口 | `http://172.26.2.203:8078/...` | ✅ 能（MSIA 现网就是这个，可直接生产用） |
| 正式域名 | `https://msia.ap.inalfa.local/...` | ❌ 等 DNS + IIS ARR + 证书到位，定稿后再加一行 |
| 通配符 | `*`、`http://*/*`、`.../callback*` | ❌ **绝对禁止** |

> 为什么禁止 `*`：那等于"任何网站都能当我这个 client 的回调地址"，攻击者可以自己搭个站把授权码骗走，再换到你的令牌。**只填精确地址。**

✅ **做到这里，你应该看到**：`bol-prod` 的 `Valid Redirect URIs` 框里有**两行**（带斜杠、不带斜杠）；`msia-prod` 里**一行**；两个 client 的 `Web Origins` 只有 scheme+域+端口。

---

## 8. 拿 client secret（应用的"密码"）

### 8.1 点哪里

1. `Clients` → 点 `msia-prod`
2. 上方页签 **Credentials**（凭据）
3. 页面里 `Client Authenticator` 显示 `Client ID and Secret`
4. `Client Secret` 输入框里就是当前 secret（有的版本默认隐藏，点旁边的 **Show**/眼睛图标显示）
5. 点输入框右侧的 **Copy**（或选中文字复制）

`bol-prod`、`sync-client` 同样操作。

### 8.2 复制后存哪

存到**服务器上的受限目录**，例如 `C:\sso\conf\` 下每个 client 一个文件；只让运维账号和 SYSTEM 能读。

- **不要**贴到聊天工具、邮件、工单、文档、git。
- **不要**放进截图。
- 交给开发同事时，用线下方式（当面/加密盘），并在交付记录里写"已交付"而不写值。

> 为什么这么严：secret 等于"这个应用的身份证"。谁拿到它，谁就能冒充 MSIA/BOL 后端去换令牌、读用户信息。

### 8.3 `Regenerate` 按钮的风险

- **不要随手点**。点了以后旧 secret **立刻作废**，正在跑的应用下一次登录就会失败（报 `Invalid client or Invalid client credentials`）。
- 真的需要轮换时，顺序是：点 `Regenerate` → **马上**把新值更新到应用配置 → 重启应用 → 验证登录。这期间会有短暂登录失败，要放在窗口里做。

✅ **做到这里，你应该看到**：三个 client 的 Credentials 页签都能看到/复制到一长串 secret，并且已经存到了服务器上的受限文件里（不是桌面、不是微信）。

---

## 9. 加 Groups mapper（让令牌里带出组名）

两个业务 client（`msia-prod`、`bol-prod`）各加一次；`sync-client` 不需要。

### 9.1 点哪里（25.0.6 经典界面）

1. `Clients` → 点 `msia-prod`
2. 上方页签 **Mappers**（映射器）
3. 点 **Create**（新版在 `Client scopes` → `Dedicated scope and mappers` → `Add mapper` → `By protocol`）
4. `Mapper Type` 下拉里选 **`Group Membership`**（字段名是 `oidc-group-membership-mapper`）
5. 按下表填：

| 界面字段 | 填什么 | 为什么 |
|---|---|---|
| `Name` | `groups` | 只是显示名，随便叫；但统一叫 `groups` 方便核对 |
| `Token Claim Name` | `groups` | **必须是 `groups`**，两系统代码读的就是这个名字 |
| `Full group path` | **OFF** | 关掉后令牌里是 `"app-msia"`；开着会变成 `"/app-msia"`，代码比对会失败 |
| `Add to ID token` | **ON** | 后端校验的是 id_token |
| `Add to access token` | ON | 方便排查 |
| `Add to userinfo` | ON | 可选，建议开 |

6. 点 **Save**

### 9.2 怎么确认生效

- Mappers 列表里出现一行 `groups`（类型显示 `Group Membership`）。
- 真正的生效要看令牌：给某个用户加上 `app-msia` 组后，登录拿到的 id_token 里应出现 `"groups": ["app-msia"]`。这一步在灌入用户之后才能验证。

✅ **做到这里，你应该看到**：`msia-prod` 和 `bol-prod` 的 Mappers 列表里都有一行 `groups`。

---

## 10. 给 `sync-client` 授权（Service Account Roles）

同步脚本要能建用户、改用户，就必须给它的"服务账号"发权限。

### 10.1 点哪里

1. `Clients` → 点 `sync-client`
2. 上方页签 **Service Account Roles**（服务账号角色）
   - 如果看不到这个页签：回到 `Capability config` 确认 `Client Authentication` 和 `Service Accounts Roles` 都是 **ON**，Save 后再看
3. 点 **Assign role**（分配角色）
4. 对话框里有个筛选下拉，默认 `Filter by roles`，改成 **`Filter by clients`**
5. 搜索框输入 `realm-management`
6. 在结果里**勾选这三个**：
   - `manage-users`（建号/改号/禁用/发设密邮件/强制下线）
   - `view-users`（查用户）
   - `query-users`（按用户名查）
7. 点 **Assign**

### 10.2 少勾会怎样

| 少了哪个 | 同步脚本的表现 |
|---|---|
| `manage-users` | 建用户/改用户时报 `403 Forbidden`（日志里常见 `unknown_error` / `HTTP 403`），同步直接失败 |
| `view-users` / `query-users` | 查不到用户，脚本会把"已存在"的人当成新人重复建，或报 403 |

> 不要给它 `realm-admin` 这类超级角色：同步脚本只需要管用户，权限越小越安全。

✅ **做到这里，你应该看到**：`sync-client` 的 Service Account Roles 页签下，`realm-management` 分组里勾着 `manage-users`、`view-users`、`query-users` 三个。

---

## 11. 收尾验证（逐项打勾）

### 11.1 界面清单

逐项去到对应位置，全部打勾才算完：

| # | 检查项 | 去哪看 | 合格标准 |
|---|---|---|---|
| 1 | realm 在 | 左上角域下拉 | 有 `inalfa`，且当前就是它 |
| 2 | realm 设置 | Realm Settings → 各页签 | Login: Registration OFF / Forgot Password ON；Tokens: Access Token 15 Minutes；Security Defenses: Brute Force ON |
| 3 | 两个组 | Groups | `/app-msia`、`/app-bol` |
| 4 | 四个 client | Clients | `account`、`bol-prod`、`msia-prod`、`sync-client` 都在，且 `Enabled` |
| 5 | MSIA 回调 | `msia-prod` → Access settings | 一行，`http://172.26.2.203:8078/api/auth/oidc/callback` |
| 6 | BOL 回调 | `bol-prod` → Access settings | 两行（带斜杠 + 不带斜杠），都是 `127.0.0.1:8090` |
| 7 | 认证方式 | 两个业务 client → Capability config | `Client Authentication` ON、`Standard Flow` ON、`Direct Access Grants` OFF |
| 8 | PKCE | 两个业务 client → Advanced/Login settings | `S256` |
| 9 | mapper | 两个业务 client → Mappers | 一行 `groups`，`Full group path` = OFF |
| 10 | 服务账号 | `sync-client` → Service Account Roles | 三个角色都在 |
| 11 | secret 已保存 | 服务器受限目录 | 三个 secret 文件存在，没进聊天/邮件/git |

### 11.2 用浏览器走一遍（不需要真的登录成功）

在**同一台服务器**的浏览器里打开（把地址整段复制到地址栏）：

```text
https://localhost:8443/realms/inalfa/protocol/openid-connect/auth?client_id=msia-prod&response_type=code&scope=openid&redirect_uri=http%3A%2F%2F172.26.2.203%3A8078%2Fapi%2Fauth%2Foidc%2Fcallback
```

| 看到什么 | 说明 |
|---|---|
| `inalfa` 的登录页（用户名/密码输入框，页面上有"统一身份认证"之类字样） | ✅ client、redirect URI、realm 全部配对成功 |
| 页面报 `Invalid parameter: redirect_uri` | ❌ 回调地址和登记值不一致 → 回第 7 节逐字符核对 |
| 页面报 `Invalid client` | ❌ clientId 拼错或 client 被 Disabled → 回 Clients 列表核对 |

> 真正完整登录（输账号密码 → 跳回系统）需要先有一个用户，并且把这个用户加进 `app-msia` 组。那属于"灌用户"的下一步，不在本手册范围。

✅ **做到这里，你应该看到**：浏览器里出现 `inalfa` 域的中文/英文登录页，而不是任何红字报错。

---

## 12. 术语小词典（一句话 + 一个比喻）

| 术语 | 一句话 | 比喻 |
|---|---|---|
| realm | 一个独立的"认证空间"，里面有自己的用户、应用、策略 | 一栋独立的办公楼，门禁、员工、访客都归这栋楼管 |
| client | 允许接入这个 realm 的一个应用 | 办公楼里登记过的"合作公司"，有工牌才能进 |
| client secret | client 的密码，后端用来证明"我是这个应用" | 合作公司的公章，盖了才算数，丢了别人就能冒充 |
| PKCE | 登录时临时生成一个一次性校验码，防止授权码被半路截走 | 寄快递时给收件人一个一次性取件码 |
| mapper | 往令牌里"多塞一条信息"的规则 | 门禁卡上多印一行"所属部门" |
| scope | 应用申请要哪些信息（如 `openid profile email`） | 点菜时说"我要主食+饮料"，厨房只给这两样 |
| service account | 没有真人、由程序使用的账号 | 公司的"系统对接专用门禁卡"，不是某个员工的 |
| issuer | Keycloak 对外宣称"我是谁"的地址，令牌上带这个签名 | 发票上的公司抬头，对不上就不认 |
| redirect URI | 登录成功后把用户送回哪个地址 | 快递填的收货地址，差一个字就送不到 |

---

## 13. 常见报错对照表

| 你在界面上/登录时看到 | 最可能的原因 | 去哪一栏改 |
|---|---|---|
| `Invalid parameter: redirect_uri` | 应用发来的回调地址与登记值不是一字不差（尾斜杠、http/https、端口、路径） | `Clients → 该 client → Access settings → Valid Redirect URIs`（必要时补一行，不要覆盖旧行） |
| `Invalid client or Invalid client credentials` | clientId 拼错 / client 被 Disabled / secret 与应用配置不一致（常见是复制时多了空格或换行） | `Clients` 列表核对 ID 与 `Enabled`；`Credentials` 页签重新复制 secret，同步改应用配置 |
| `Unauthorized client` | 该 client 的 `Standard Flow` 关着；或用了 client_credentials 但 `Service Accounts Roles` 没开 | `Clients → Capability config` 把对应开关打开，Save |
| `Account is not fully set up` | 用户还有待办的 Required Action（如 Update Password / Verify Email）；或 User Profile 缺少必填字段 | `Users → 该用户 → Required Actions` 页签；`Realm Settings → User Profile` 不要禁用 |
| 登录后跳回应用是 404 | 应用的**路由**与登记的回调地址不一致（BOL 的路由带尾斜杠） | 回第 7 节：`Valid Redirect URIs` 补上带斜杠那一行；同时核对应用配置文件里的 redirect |
| 点"统一登录"后跳回空白页 | 应用侧回调处理失败（state 校验失败 / OTK 兑换失败），Keycloak 侧通常没有报错 | Keycloak 侧只核对 `Valid Redirect URIs` 与 secret；主要看应用日志 |
| 控制台打不开 / 证书错误更严重 | 用了 IP 或 127.0.0.1 打开，而证书名字是 `localhost` | 地址栏改 `https://localhost:8443`，按第 1 节过警告 |
| 登录页提示 `Invalid username or password` | 用户名不存在或密码错（注意是 `login_name`，不是邮箱） | `Users` 搜索该用户名；确认不是用邮箱登录 |
| 页面 500 / `We are sorry...` | 服务端异常 | 看服务器 `C:\keycloak\logs\keycloak.log` 最后 50 行 |
| 邮件收不到 | SMTP 的 `Enable SSL` / `Enable StartTLS` 误开，或 Host/Port 填错 | `Realm Settings → Email`，先点 `Test Connection` |

---

## 附录：如果你更想用脚本

命令行做法与本文界面操作**是同一件事**（建 realm、建 client、加 mapper、配策略，最终写进同一个数据库），只是入口不同：命令版本见 [keycloak-realm-clients-init.md](./keycloak-realm-clients-init.md) 的"清单 B"。

两条经验：

1. **第一次配置建议走界面**（本文），你能看见每一项落在哪个页签，出错时知道去哪改。
2. **改 redirect URI 一定走界面**：界面是多行文本框，天然追加；命令行是整体替换数组，容易把旧地址冲掉。

---

## 附：禁止动作清单（给不熟界面的人）

- 不要点任何 **Delete**（删 realm / 删 client / 删组）——没有回收站。
- 不要点 `Credentials` 页签的 **Regenerate**，除非你准备立刻改应用配置并重启。
- 不要把 `Client Secret` 贴到聊天、邮件、工单、文档、截图。
- 不要在 `Valid Redirect URIs` / `Web Origins` 里写 `*`。
- `Realm Settings` 里本文没提到的页签（Themes / Keys / Localization / Headers），一律不要动。
