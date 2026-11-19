# MSIA 统一身份认证：免密、免点击与「保持登录」可行性分析

- 日期：2026-11-05
- 适用：Keycloak 25.0.6 / realm `inalfa` / client `msia-prod`；MSIA Report（FastAPI + React）
- 性质：只做分析与建议，**本次未修改任何业务代码**
- 口径：代码事实以仓库文件为准，逐项标注文件与行号；Keycloak 侧以既有文档
  （`统一身份认证实施/docs/keycloak-realm-clients-init.md`、`keycloak-console-setup-for-beginners.md`）
  的设定值为基准，**现场必须用第 6 节命令复核**，未复核项一律按「待确认」处理。
- **修订记录（2026-11-09，第二轮）**：按《统一身份认证技术交底书_MSIA与BOL实施实录.md》§9.3 对齐——Keycloak 会话由 8 小时 / 12 小时改为 **空闲 1 天（86400 秒）/ 最长 7 天（604800 秒）**，原值作废；文中 §0.1、§2.4、§3.1、§4.2、§6 的会话表述已同步。暴力破解 5 次 / 900 秒（本轮无变更）。

---

## 0. 结论先行

### 0.1 三问直接回答

| # | 用户的问题 | 结论 | 条件 |
|---|---|---|---|
| 1 | 使用统一身份认证登录，是否可以不用每次都录入用户名密码？ | **有条件能** | 同一台电脑、同一浏览器、不清站点数据、未点「退出登录（清除缓存）」、距上次 SSO 登录不超过 **30 天**（MSIA 本地 JWT 有效期）。满足时打开系统直接进看板，**既不输密码也不点按钮**。超过 30 天 / 换浏览器 / 清缓存后，需要点一次「统一身份登录」；此时若 Keycloak SSO 会话仍在（当前设定为 **1 天空闲 / 7 天上限**），免密进；否则要输一次密码。 |
| 2 | 本机浏览器能够保持登录或缓存？ | **能，现状已具备** | 前端把 MSIA 自签 JWT 与用户信息持久化在 `localStorage['msia-auth']`，有效期 **30 天**（`jwt_expire_minutes = 43200`）。关浏览器、重启电脑、重启 MSIA 后端都不影响（JWT 无服务端状态）。前提：不主动退出、不清浏览器数据、`jwt_secret_key` 不变、服务器时间正常。缓存的是**登录令牌**，不是账号密码（OIDC 路径不会保存密码）。 |
| 3 | 下次登录时自动填充用户名密码？ | **不能（指统一身份认证）** | OIDC 登录显式清空并禁用本地账号密码记忆（`rememberMe=false`、`savedPassword=null`）。Keycloak 侧 `rememberMe=false`，登录页没有「记住我」复选框；即使打开，也只记住**用户名**并预填，密码仍必须输入。浏览器密码管理器可能自动填充，但**仍需人工点「Sign In」**，且取决于用户浏览器/设备策略，不能当作方案。 |

> 注意：本地账密登录（`local_login_enabled=true`）确实存在「下次自动登录」：它把**明文密码**存进 `localStorage['msia-auth']`，下次打开自动提交（`frontend/src/store/auth.ts:53-54,71-85`）。这是当前「打开就进」观感的来源之一，但它属于旧双轨路径，P4 单轨（`local_login_enabled=false`）后即失效，且存在明文口令落盘的安全问题（见 §2.7）。

### 0.2 一句话建议

- **现状已经能满足「同一浏览器 30 天打开即进」**，这是零改动的能力，先把它讲清楚、把配置核对清楚即可。
- 若业务要求「换浏览器/清缓存/超过 30 天后也尽量无感」，做 **方案 B 静默重认证**（`prompt=none`），并配合把 Keycloak 的 SSO 会话时长调到 1 天 / 7 天这一档；这是性价比最高的组合。
- **方案 C（refresh token）现在不建议上**：收益与改动量不成比例，且当前生产入口是 HTTP，Refresh Token 只能放 Cookie 才安全，而 HTTP 下 Cookie 无法加 `Secure`，等于把长期凭证暴露在明文链路上。先上 HTTPS 再谈。
- **浏览器自动填充不能当成方案**（理由见 §8）。

---

## 1. 现场链路（2026-11-05 实测，作为本文前提）

```
GET  /api/auth/oidc/login           302 → Keycloak 授权页
Keycloak 认证                        302 → /api/auth/oidc/callback?code=&state=
GET  /api/auth/oidc/callback        校验 state/nonce/PKCE → 换 id_token → 解析身份
                                    签本地 JWT + 60s OTK → 302 /oidc/callback?otk=...
GET  /oidc/callback (前端)           POST /api/auth/oidc/token (otk) → 200 本地 JWT
业务接口                             Authorization: Bearer <MSIA JWT> → 200
```

身份解析：`ligu 无 UserMap 映射, 回落 preferred_username`，命中本地用户 `id=2414`
（对应 `MSIA Report/backend/app/services/sso_identity.py:5-8,71-90` 的匹配顺序）。
运行期出现 `InsecureKeyLengthWarning`（HMAC key 23 字节），说明**生产实际生效的密钥不是仓库里的 64 字节值**（见 §2.6）。

---

## 2. 代码事实清单

### 2.1 MSIA 自签 JWT：有效期、算法、刷新、存放位置、401 处理

| 项 | 事实 | 出处 |
|---|---|---|
| 算法 | `HS256`（对称 HMAC） | `MSIA Report/backend/config.ini:79`；`app/core/security.py:57` |
| 有效期 | `jwt_expire_minutes = 43200`（**43200 分钟 = 720 小时 = 30 天**）；代码默认值同为 43200 | `config.ini:82`；`app/core/config.py:220`；`app/core/security.py:48` |
| 载荷 | 仅 `sub`（用户 Id）、`role`、`iat`、`exp`；**无 `iss`/`aud`/`jti`**，没有唯一标识，无法按单枚令牌吊销 | `app/core/security.py:49-54` |
| 刷新机制 | **没有**。无 `/api/auth/refresh` 端点，也没有定时续签；唯二签发点是本地登录和 OIDC 回调 | `app/api/auth.py:106,221`；后端全仓无 refresh 端点 |
| 服务端校验 | 每个请求验签 + 按 `sub` 查库校验 `IsDeleted` / `Status`；`role` claim 实际未被使用 | `app/core/deps.py:36-55`；`app/api/auth.py` 调用 `create_access_token` |
| 前端存放 | `localStorage['msia-auth']`（Zustand `persist` 默认存储即 localStorage），持久化字段：`token`、`user`、`rememberMe`、`lastLoginUsername`、`savedPassword` | `frontend/src/store/auth.ts:6,120-133` |
| 恢复登录 | 刷新页面后从 localStorage 恢复 token；缺 `user` 时自动调 `/api/auth/me` | `frontend/src/components/AuthRoute.tsx:17-29`；`store/auth.ts:110-118` |
| 401 处理 | **硬跳转 + 提示，不静默重试**：清内存 token → 调 `onUnauthorized` 清持久化 token/user → 弹「登录已过期，请重新登录」→ `window.location.replace('/login')` | `frontend/src/api/client.ts:41-58`；`store/auth.ts:141-144` |
| 登录页后续 | 登录页挂载时调用 `autoLogin()`，但它只对「本地账密登录 + 已保存明文密码」有效；OIDC 路径保存的密码为 `null`，因此**不会自动恢复** | `frontend/src/pages/Login.tsx:43-66`；`store/auth.ts:71-85` |

结论：**唯一的「保持登录」载体是 30 天 JWT**；一旦它过期或丢失，系统没有任何自动续期能力，只能回登录页重新发起授权。

### 2.2 OTK 一次性码：有效期、单次消费、来源绑定

| 项 | 事实 | 出处 |
|---|---|---|
| 有效期 | **60 秒** | `app/core/oidc.py:36`；`app/api/auth.py:232` |
| 单次消费 | 是。`consume_otk` 用 `pop` 取出，取出即删除 | `app/core/oidc.py:237-243` |
| 随机性 | 32 字节 `secrets.token_bytes`，base64url 去填充 | `app/core/oidc.py:220` |
| 绑定来源 | **不绑定**。载荷只有 `user_id` + 已签发的 JWT；没有 IP、User-Agent、浏览器指纹或 state 关联 | `app/core/oidc.py:223-227` |
| 存储 | 进程内存字典 + 线程锁；重启即丢 | `app/core/oidc.py:46-48` |
| 换取接口 | `POST /api/auth/oidc/token`，仅校验 otk 与用户状态，不校验来源 | `app/api/auth.py:227-258` |

风险边界：OTK 会出现在前端地址栏（`/oidc/callback?otk=...`），理论上可经浏览器历史、截图、Referer 泄漏；60 秒 + 单次消费把窗口压得很小，但**不绑定来源**意味着「拿到 otk 的人在同一分钟内可换到登录态」。这不是本次问题的关键，但属于既有设计事实。

### 2.3 回调时是否保存 Keycloak 的 refresh_token / id_token；scopes 是否含 offline_access

| 项 | 事实 | 出处 |
|---|---|---|
| 换取 token | `exchange_code` 返回完整 token 响应（含 `access_token` / `id_token` / 很可能含 `refresh_token`） | `app/core/oidc.py:147-160`；`app/api/auth.py:197` |
| id_token | **仅验签后取 claims，用完即弃**，不落库、不存前端 | `app/api/auth.py:198-204`；`app/core/oidc.py:163-184` |
| refresh_token | **不读取、不保存、不使用**（代码里没有 `refresh_token` 这个键） | `app/api/auth.py:196-204` |
| access_token（Keycloak） | 不使用；业务接口只认 MSIA 自签 JWT | `app/core/deps.py:18-45` |
| scopes | `openid profile email`，**不含 `offline_access`** | `MSIA Report/backend/config.ini:129`；`app/core/config.py:246` |
| 授权请求参数 | 仅 `response_type=code`、`scope`、`client_id`、`redirect_uri`、`state`、`nonce`、PKCE `S256`；**没有 `prompt`、`max_age`、`login_hint`** | `app/core/oidc.py:131-144` |
| userinfo | 不调用，身份信息全部取自 id_token claims | `app/api/auth.py:206-213` |

补充事实：Keycloak 授权码流默认会下发 refresh_token（客户端未显式关闭 `Use Refresh Tokens`；文档 `keycloak-console-setup-for-beginners.md:199-204` 记录 `Revoke Refresh Token` / `Refresh Token Max Reuse` 均保持默认，未做改动）。也就是说**凭证大概率已经拿到了，只是被应用丢掉了**；`Use Refresh Tokens` 的实际值需现场确认（见 §6 C2）。若将来走方案 C，通常不需要改 Keycloak 的 scope 就能拿到 refresh_token（但 `offline_access` 才决定「离线会话」语义，见 §4.5）。

### 2.4 登出行为：是否注销 Keycloak SSO 会话

| 项 | 事实 | 出处 |
|---|---|---|
| 后端登出 | 空实现，只返回提示；注释明确「Keycloak 侧 SSO 会话的全局登出传播（front-channel logout）本期不做」 | `app/api/auth.py:261-268` |
| 前端登出 | 调 `/api/auth/logout`（失败也继续）→ 清内存 token / user → 可选清 `localStorage` | `frontend/src/store/auth.ts:87-108` |
| Keycloak 登出 | **从不调用 `end_session_endpoint`**；Keycloak 客户端 `Valid post logout redirect URIs` 也留空 | 代码无该调用；文档 `keycloak-realm-clients-init.md:391,645,668` |
| 实际效果 | 点「退出登录」只清掉 MSIA 的浏览器状态；**Keycloak 的 `KEYCLOAK_IDENTITY` / `KEYCLOAK_SESSION` Cookie 仍在** | 由上述实现推断 |

后果（重要）：

1. **再点一次统一身份登录会直接登回原账号，不再要密码**，直到 SSO 会话（1 天空闲 / 7 天上限）自然过期。
2. **共享电脑上的账号接管风险**：A 用户退出后，B 用户点统一登录，Keycloak 会把 A 的会话直接发给 MSIA → B 以 A 的身份进入。这是当前最现实的越权场景，优先级高于「免密体验」。
3. 跨系统登出不同步：MSIA 退出不影响 BOL，反之亦然（两系统都只做本地登出）。
4. 管理员无法「强制踢线」：只能在 Keycloak 删会话/禁用用户；禁用用户对 MSIA 本地 30 天 JWT **不生效**（本地 JWT 仍能通过 `sub` 查库进系统，除非 MSIA 本地账号也被禁用）。
5. 若将来实现方案 B（静默重认证），**登出后如果不加标记，登录页会自动静默登回**，形成「退出即自动登录」的悖论（§5.3 给出规避方式）。

### 2.5 后端 session 是否依赖进程内存；对「保持登录」意味着什么

| 项 | 事实 | 出处 |
|---|---|---|
| 服务端 session | **没有**。未挂 `SessionMiddleware`，无 Redis，无会话表 | 全仓 grep 无 `SessionMiddleware` / Redis |
| 唯一内存态 | OIDC `state/nonce/PKCE verifier`（TTL 10 分钟，单次消费）、OTK（TTL 60 秒） | `app/core/oidc.py:35-36,42-48,188-243` |
| 部署 | uvicorn `workers=1` | `MSIA Report/backend/run.py:70-77` |
| 重启影响 | **已登录用户完全不受影响**（JWT 无状态，重启后验签照常）；只有「登录进行中」的人会失败：state 丢失 → 回调 400「登录状态无效」；OTK 丢失 → 前端提示「登录凭证无效或已过期」 | `app/api/auth.py:179-190,234-240` |
| 多实例 | **不支持**。state/OTK 在单进程内存，多 worker 或 8078 后面挂多台后端会随机 400 | `app/core/oidc.py:12-13` 注释 |

对「保持登录」的结论：**内存态不影响 30 天保持登录**，它只影响登录那一瞬间。但为了让方案 B 可靠，必须保持单实例（或把 state/OTK 外置到共享存储）。

### 2.6 `InsecureKeyLengthWarning`：23 字节密钥

| 项 | 事实 |
|---|---|
| 告警产生位置 | PyJWT 在签名/验签前检查 HMAC 密钥长度：不足 32 字节时发 `InsecureKeyLengthWarning`（`MSIA Report/.venv/Lib/site-packages/jwt/api_jws.py:201-206`，验签路径 `:414`） |
| 仓库值 | `config.ini` 中 `jwt_secret_key` 实测 **64 字节**（本次用脚本计长，未打印明文）；`config.py:150` 回退值、`config.py:218` 默认值也要求长串 |
| 现场为何是 23 字节 | 配置优先级「环境变量 > config.ini > 默认值」（`config.py:176-179`）：生产 `JWT_SECRET_KEY` 环境变量（或服务器本机 config.ini）是 23 字节，覆盖了仓库值 |
| 影响 | HS256 的安全强度不超过密钥熵；23 字节若为可猜字符串，存在离线暴力破解与伪造令牌风险；30 天有效期放大了影响 |
| 修复 | 换成 ≥32 字节（建议 64 字节）随机值，统一走环境变量；**换密钥会让所有存量 JWT 失效，全员需重登一次**，需安排窗口 |

现场核对命令见 §6 的 C6。

### 2.7 前端「记住密码 / 自动登录」的真实机制（本地登录路径）

| 项 | 事实 | 出处 |
|---|---|---|
| 保存内容 | `savedPassword` **明文**存进 `localStorage['msia-auth']`（仅在本地登录且勾选「下次在这台电脑上自动登录」时） | `store/auth.ts:14,46-56,122-133` |
| 自动登录 | 登录页挂载即调 `autoLogin()`，用保存的用户名 + 明文密码重新 POST `/auth/login` | `store/auth.ts:71-85`；`Login.tsx:58-65` |
| OIDC 路径 | `loginWithOtk` 显式写入 `rememberMe=false`、`lastLoginUsername=null`、`savedPassword=null`，并注释「Keycloak SSO 会话负责下次免密」 | `store/auth.ts:58-69` |
| 退出选项 | 「保留本机自动登录」= `logout(true)`；「清除本机自动登录缓存」= `logout(false)`，后者删除整个 `msia-auth` | `frontend/src/layouts/MainLayout.tsx:211-228`；`store/auth.ts:87-108` |
| 安全评价 | XSS 或本机其他账户可直接读走明文口令；一旦 P4 关本地登录，该机制失效（且 `autoLogin` 会拿到 403 后清理缓存） | — |

---

## 3. Keycloak 侧（25.0.6 口径）

> 以下「文档设定」来自仓库既有文档，**不是现场实测值**。第 6 节给出只读核对命令；未核对前按「待确认」使用。
> 25.0.6 不存在 26.x 的 `bootstrap-admin`、`hostname-strict-https` 等选项，本文不引用这些。

### 3.1 realm 会话参数（当前设定，以交底书 §9.3 为准）

| 参数 | 当前设定 | 含义 | 出处 |
|---|---|---|---|
| `accessTokenLifespan` | `900` 秒（15 分钟） | Keycloak 自己的 access token 寿命。**MSIA 不使用它**，只在方案 C 有意义 | `keycloak-realm-clients-init.md:319,342` |
| `ssoSessionIdleTimeout` | `86400` 秒（1 天） | 滑动空闲窗口：连续 1 天无活动则 SSO 会话失效（2026-11-09 现场决定，原 28800 秒 / 8 小时作废） | `keycloak-realm-clients-init.md:320,342`；`keycloak-console-setup-for-beginners.md:235` |
| `ssoSessionMaxLifespan` | `604800` 秒（7 天） | 绝对上限：从登录起满 7 天必失效，无论是否活跃（原 43200 秒 / 12 小时作废） | `keycloak-realm-clients-init.md:321,342`；`keycloak-console-setup-for-beginners.md:236` |
| `Client Session Idle` / `Max` | `0`（跟随 SSO） | 客户端级覆盖，0 = 继承 realm | `keycloak-console-setup-for-beginners.md:231` |
| `Offline Session Idle` / `Max` | 保持默认（值待确认） | 只有 `offline_access` 才用得上；方案 C 才涉及 | `keycloak-console-setup-for-beginners.md:232` |
| `rememberMe` | `false` | 登录页不显示「记住我」 | `keycloak-realm-clients-init.md:310` |
| 客户端 post logout URI | 留空 | 应用不调 `end_session`，填了也不生效 | `keycloak-realm-clients-init.md:391,645` |

> 口径修正：`keycloak-console-setup-for-beginners.md:199` 写「Access Token Lifespan 两系统校验过期用这个」，**对 MSIA 不成立**——MSIA 只在回调时验一次 id_token，随后完全使用自签 JWT（§2.1）。该值对 MSIA 的登录保持没有影响。

**关键推论**：当前 Keycloak 的免密窗口是「1 天空闲 / 7 天绝对」，而 MSIA 的登录态是 30 天。两者不在一个量级——**用户日常感受到的「保持登录」几乎全部来自 MSIA 的 30 天 JWT，而不是 Keycloak 会话**。这也是为什么现状下「重新点登录」通常发生在 30 天后，而不是每天。

控制台路径（25.0.6）：

- `Realm Settings` → `Sessions`：`SSO Session Idle`、`SSO Session Max`、`Client Session Idle/Max`、`Offline Session Idle/Max`（部分构建把会话字段放在 `Tokens` 页签，以命令输出为准）。
- `Realm Settings` → `Tokens`：`Access Token Lifespan`、Refresh Token 相关策略。
- `Realm Settings` → `Login`：`Remember Me`、`Email as username` 等。
- `Clients` → `msia-prod` → `Settings`：`Valid Redirect URIs`；`Advanced`：PKCE、`Use Refresh Tokens` 等。
- 会话观察：`Users` → 目标用户 → `Sessions` 页签。

### 3.2 Remember Me 的实际作用边界

事实边界（不要把它当成「保持登录」）：

1. **开关位置**：`Realm Settings → Login → Remember Me`。当前文档设定为 `false`，所以登录页**根本没有复选框**。
2. **开启后**：登录页出现「Remember me」复选框；勾选后 Keycloak 写一枚 `KEYCLOAK_REMEMBER_ME` Cookie，内容主要是**用户名 + 认证方式**，用于下次打开登录页时**预填用户名**并跳过用户名输入步骤。
3. **不做什么**：**不放宽 `SSO Session Idle` / `SSO Session Max`**，也不跳过密码；不会改变「SSO 会话过期后必须重新认证」的事实。
4. **Cookie 有效期**：由 Keycloak 内置常量决定（长期，量级约一年）；**精确 Max-Age 需现场确认**——开启后勾选一次，在浏览器开发者工具 `Application → Cookies → sso 域名` 里看 `KEYCLOAK_REMEMBER_ME` 的 `Expires/Max-Age`。
5. **与 MSIA 的关系**：MSIA 登录态只认自己的 JWT；Keycloak 的 Remember Me 最多让用户在**必须重新输密码时少打一次用户名**。

结论：**Remember Me 是「用户名记忆」，不是「免密 / 保持登录」**；在本项目里属于可选微优化，不能作为三问之 3 的答案。

### 3.3 静默重认证参数：`prompt=none`、`login_hint` 与会话失效返回

授权请求新增参数（OpenID Connect 标准，Keycloak 25.0.6 支持）：

```
&prompt=none                 # 禁止任何交互：有会话就发码，没有就带 error 回跳
&login_hint=<用户名>          # 预选/提示账号（多账号同浏览器时有用；不改变认证要求）
&max_age=<秒>                # 可选：强制「认证新鲜度」，超过则需重新认证
```

行为预期：

| 场景 | Keycloak 行为 | 前端应如何兜底 |
|---|---|---|
| 有有效 SSO 会话 | 302 到 `redirect_uri?code=...&state=...` | 正常走现有回调 → otk → JWT，无感 |
| 无 SSO 会话 / 已过期 | 302 到 `redirect_uri?error=login_required&state=...`（**不弹登录页**） | **不能**当错误页展示；应回登录页并给出「会话已失效，请重新登录」提示 |
| 需要重新同意授权（如 `offline_access` 首次授权） | 302 带 `error=consent_required`（用 `offline_access` 时才可能出现） | 同上，回交互式登录 |
| 需要用户补动作（改密/完善资料等） | 可能返回 `interaction_required` | 同上，回交互式登录 |
| 用户/客户端被禁用、准入组缺失 | `access_denied` 或 MSIA 自有 403 文案 | 展示明确原因，不自动重试 |

> 具体错误码以现场探测为准（命令 C4/C5 见 §6）。**兜底原则统一**：静默请求只要不是成功回调，就落到交互式登录页，绝不循环重试。

当前代码的实际行为：`/api/auth/oidc/callback` 遇到 `error` 参数时会 302 到
`/oidc/callback?error=<中文提示>`，前端 `OidcCallback.tsx` 把它渲染成「统一登录失败」的告警页
（`app/api/auth.py:175-176`；`frontend/src/pages/OidcCallback.tsx:25-27,48-72`）。
**因此方案 B 若不改这两处，静默失败会变成一个吓人的错误页，而不是优雅回落到登录页。**

探测方法（浏览器直接打开，不改任何配置）：

```
https://sso.ap.inalfa.local/realms/inalfa/protocol/openid-connect/auth
  ?client_id=msia-prod
  &response_type=code
  &scope=openid%20profile%20email
  &redirect_uri=http%3A%2F%2F172.26.2.203%3A8078%2Fapi%2Fauth%2Foidc%2Fcallback
  &state=probe
  &prompt=none
```

预期：已登录 → 回跳带 `code`（MSIA 因 `state=probe` 无效会 400，属预期）；未登录 → 回跳带 `?error=login_required`。

---

## 4. 方案对比

### 4.1 总表

| 维度 | A 现状 | B 静默重认证（`prompt=none`） | C1 延长 JWT | C2 引入 refresh token |
|---|---|---|---|---|
| 用户体验 | 同浏览器 30 天**打开即进**（免点击免密码）；30 天后 → 点一次，SSO 会话在则免密，否则输密码 | 打开即进；JWT 失效后**自动**去 Keycloak 换新，会话在则完全无感；会话不在才回登录页（点一次 + 密码） | 同 A，只是窗口拉长（如 90 天 / 180 天） | 同 A，但失效后可后台静默续期（无浏览器跳转）；会话被废止后自动回登录页 |
| 免密窗口 | 30 天（JWT）+ 8h/12h（Keycloak） | 30 天（JWT）；每次 JWT 失效时再看 Keycloak 会话（取决于 Idle/Max 设定） | 由 `jwt_expire_minutes` 决定 | 由 Keycloak 会话/离线会话策略决定 |
| 安全性代价 | 30 天 Bearer 放 localStorage：XSS 即盗用；**无吊销**；Keycloak 侧禁用不生效；共享电脑登出后仍可被下一位「接管」 | 不新增长期凭证；但需处理「登出后自动静默登回」「401 循环」「多实例 state 丢失」；登录页会多一次跳转 | A 的风险等比放大（90 天不可吊销令牌） | 最高：refresh token 是长期高价值凭证，必须 HttpOnly + Secure + 轮换 + 重放检测；引入服务端状态 |
| 改动量 | 0 代码；可选调 Keycloak 会话时长（配置） | 后端 **2 个文件**（`oidc.py` 加参数、`auth.py` 加 `silent` 标记与失败分支）；前端 **4 个文件**（`api/auth.ts`、`store/auth.ts`、`pages/Login.tsx`、`pages/OidcCallback.tsx`，`api/client.ts` 的 401 分支）；**无需新增接口** | 0 代码；改 `config.ini` 的 `jwt_expire_minutes`，重启进程 | 后端新增 refresh 端点 + 安全存储 + 轮换；前端 401 改为刷新；Keycloak 需配 scope/策略；**HTTP 下不建议** |
| Keycloak 配置 | 需现场核对；建议 Idle/Max 调档 | 无需改客户端（`prompt` 是标准参数）；建议配合 Idle/Max 调档 | 无 | `offline_access`（可选 scope，会引入同意页）、`Use Refresh Tokens`、`Revoke Refresh Token`、Offline Session Idle/Max |
| 失败兜底 | 401 → 登录页 → 点按钮 | 静默失败 → **回交互式登录页**（一次），禁止循环 | 同 A | 刷新失败 → 清本地态 → 登录页 |
| 结论 | 先保留 | **推荐** | 仅作为 B 的补充/替代窗口，不推荐单独用 | 暂缓 |

### 4.2 A 现状（不改）

- **用户感知**：同一浏览器 30 天内打开即进，这一点已被代码实现（`store/auth.ts:120-133`、`AuthRoute.tsx:17-29`、`Login.tsx:43-66`）。超期后 401 拦截器硬跳登录页（`client.ts:41-58`），用户点「统一身份登录」。
- **为什么「30 天后」通常要输密码**：Keycloak 会话上限 7 天，仍远小于 30 天；30 天后 SSO 会话几乎必然已失效。
- **安全**：30 天令牌无法吊销；共享电脑登出后 Keycloak 会话仍在（§2.4）。
- **改动**：0。
- **适用**：不追求「永远无感」，只要能「每天打开就进」。

### 4.3 B 静默重认证（推荐）

**做法**：

1. 后端授权入口支持静默模式：
   - `GET /api/auth/oidc/login?silent=1&login_hint=<username>`
   - `build_authorize_url` 增加 `prompt=none`（静默时）与 `login_hint`；现有 `state/nonce/PKCE` 逻辑不变（`app/core/oidc.py:131-144`）。
   - 在 `store_oidc_session` 里多存一个 `silent` 标记（`app/core/oidc.py:188-196`）。
2. 回调区分静默失败：
   - `error` 且 `silent=1` → 302 到 `OIDC_FRONT_CALLBACK + "?error=login_required&silent=1"`（或专用 `?silent_failed=1`）。
   - 成功路径完全复用现有「签 JWT + OTK」（`app/api/auth.py:220-224`）。
3. 前端：
   - `Login.tsx` 挂载时若无 token 且未处于「刚退出」状态，自动跳静默授权一次。
   - `api/client.ts` 的 401 分支：改「硬跳 `/login`」为「若启用 OIDC 且本次页面尚未尝试过静默，则先跳静默授权；失败再跳 `/login`」。
   - `OidcCallback.tsx` 识别 `silent=1`：静默失败**不进错误页**，而是 `navigate('/login?silent_failed=1')` 并提示「登录会话已失效，请重新登录」。
4. 防死循环 / 防「退出后自动登回」：
   - `sessionStorage` 标记（示例）：`msia-sso-silent-try`（每次页面生命周期只尝试一次，或 60 秒节流）、`msia-just-logged-out`（`logout()` 时写入，登录页看到就**不**做静默尝试，用户点按钮后才清除）。
   - 401 只对「业务请求」触发静默，不对 `/auth/login`、`/auth/config` 触发。
5. 单实例前提：保持 `workers=1`（`run.py:74`）；否则 state/OTK 会丢（§2.5）。

**用户体验**：JWT 有效 → 打开即进；JWT 失效但 Keycloak 会话在 → 页面自动闪一下 Keycloak 再回来，用户无感；两者都没 → 登录页点一次 + 密码。

**改动量**：后端 2 文件（约 20–30 行），前端 4–5 文件（约 60–100 行），无新接口、无 DB 变更、无 Keycloak 客户端变更。

**失败兜底**：静默失败一律落到交互式登录页；Keycloak 不可达时浏览器会显示连接错误，用户返回后仍可点按钮（不建议在浏览器层做超时自动跳过）。

**安全代价**：无新增凭证；但要严格处理登出标记与循环保护，否则会出现「退出即自动登录」或 401 循环。

### 4.4 C1 长有效期 JWT

- **做法**：把 `jwt_expire_minutes` 从 43200 调到更大（如 129600 = 90 天）。
- **用户体验**：窗口更长，但终归会到期；到期仍需重新认证。
- **安全**：不可吊销令牌的暴露窗口等比放大；XSS 盗窃后果更重；离职/转岗后旧令牌仍可用（除非同时禁用本地账号）。
- **改动**：0 代码，改配置 + 重启；存量令牌不受影响（各自按签发时的 exp）。
- **结论**：不推荐单独使用；如果只想要「更长保持」，方案 B 更安全（B 允许缩短 JWT 同时保持体验）。

### 4.5 C2 引入 refresh token

- **做法（概要）**：回调把 `refresh_token` 存到服务端（或 HttpOnly Cookie 绑定的会话），新增 `POST /api/auth/refresh`；过期前或 401 时刷新；轮换并检测重放。
- **用户体验**：与 B 接近；区别是续期不需要浏览器跳转，适合纯 API 客户端或无法做顶层跳转的场景。
- **安全**：refresh token 是长期凭证，**必须 HttpOnly + Secure + SameSite**；一旦泄漏可长期换取新令牌；需要服务端状态与轮换/吊销逻辑，打破现有无状态设计。
- **前置条件**：生产入口必须 HTTPS。当前是 `http://172.26.2.203:8078`（`config.ini:117,144`），Cookie 无法加 `Secure`，**不建议在 HTTP 下落地**。
- **Keycloak 配置**：`offline_access` 是 optional client scope，加入 `scope` 会触发用户同意页（`consent_required`），破坏静默体验；或者不加 `offline_access`，用普通 refresh token（受 SSO 会话 Idle/Max 约束）。需现场确认 `Use Refresh Tokens`、`Revoke Refresh Token`、`Refresh Token Max Reuse` 的实际值。
- **结论**：暂缓。若未来安全要求把 MSIA JWT 缩短到 1 小时以内，再评估——但即便如此，B 已经能以「浏览器跳转」的方式完成续期，C2 的收益主要体现在无跳转场景。

---

## 5. 推荐组合与实施顺序

### 5.1 推荐组合

**A（保留 30 天 JWT）+ B（静默重认证）+ Keycloak 会话调档（配置）**，分阶段实施：

| 阶段 | 内容 | 类型 | 结果 |
|---|---|---|---|
| P0 | 用 §6 命令核对现状（只读，不改） | 运维 | 确认文档设定与现场一致；确认 JWT 密钥实际长度 |
| P1 | 修 `JWT_SECRET_KEY` 为 ≥64 字节随机值，统一走环境变量；窗口内全员重登一次 | 配置/运维 | 消除 23 字节告警与伪造风险 |
| P2 | Keycloak `SSO Session Idle` / `Max` 调档（建议 Idle 24h / Max 7d；如需「一个月一次」则 Max 30d） | 配置 | 让「点一次之后免密」的窗口覆盖工作日/周末 |
| P3 | 上线方案 B（静默重认证 + 401 自动续期 + 静默失败回落） | 代码 | JWT 失效时自动换新；无点击、无密码 |
| P4（可选） | B 稳定后，把 MSIA JWT 从 30 天缩短到 12h 左右 | 配置 | 缩短被盗窗口；Keycloak 侧禁用用户最迟 12h 生效；体验不变 |
| P5（可选） | 接 `end_session` 全局登出（需 Keycloak 配 `Valid post logout redirect URIs`，前端跳转） | 代码 + 配置 | 解决共享电脑「下一位自动接管」问题；MSIA/BOL 登出仍各自独立 |
| P6（暂缓） | refresh token（C2） | 代码 + 配置 | 仅在 HTTPS + 短 JWT + 无跳转需求时再评估 |

### 5.2 哪些是配置可解、哪些必须改代码

| 需求 | 配置可解 | 必须改代码 |
|---|---|---|
| 同一浏览器「打开即进」多久 | ✅ `config.ini` `jwt_expire_minutes` | — |
| 点一次登录后免密多久 | ✅ Keycloak `SSO Session Idle/Max` | — |
| JWT 失效后**自动**免密续期（无点击） | ❌ | ✅ 方案 B（前端 + 后端） |
| 静默失败优雅回登录页而不是错误页 | ❌ | ✅ `auth.py` 回调分支 + `OidcCallback.tsx` |
| 登出同时注销 Keycloak 会话 | ⚠️ 需先配 post logout URI | ✅ 后端/前端调 `end_session` |
| 下次预填用户名 | ✅ Keycloak `Remember Me`（仅用户名） | — |
| 下次自动填密码 | ❌ 不存在可配置能力 | 不建议（见 §8） |

### 5.3 方案 B 的实施注意点（落地前必看）

1. **登出标记**：`logout()` 写 `sessionStorage['msia-just-logged-out']=1`；`Login.tsx` 的静默尝试先检查该标记，用户主动点「统一身份登录」时清除标记。否则 Keycloak 会话还在，退出后会立刻自动登回。
2. **一次性/节流**：静默尝试用 `sessionStorage` 记录「本页面已尝试过」或 60 秒时间戳；401 循环是这类改造最常见的线上事故。
3. **不要静默处理登录接口的 401**：`/auth/login` 的 401 是密码错误（`client.ts:50-51` 已区分），不能触发 SSO。
4. **单实例**：`workers=1` 或把 state/OTK 外置；8078 若挂多台后端，静默失败率会升高。
5. **`login_hint` 来源**：优先用本地 `User.Username`，它通常等于 Keycloak `login_name`；若要精确，需把 `preferred_username` 随登录响应回传并持久化（小改 `TokenResponse`，可选）。
6. **静默失败文案**：`login_required` 对用户应显示「登录会话已失效，请重新登录」，而不是「统一登录失败」。

---

## 6. 现场核对命令（只读，25.0.6 口径）

> 变量块按既有文档 `keycloak-realm-clients-init.md:11-15`；`kcadm` 认证方式见同文档 B1-1（自签证书用 truststore，25.0.6 无 `--tls-ignore-hostname-verification`）。
> 所有命令均为读取，不写入。

```powershell
# 变量块（每次新窗口重跑）
$KC     = 'C:\sso'
$KCADM  = "$KC\bin\kcadm.bat"
& $KCADM config credentials --server https://localhost:8443 --realm master --user kcadmin --password '<口令>'
```

### C1 realm 会话与令牌现值（最高优先级）

```powershell
& $KCADM get realms/inalfa -r inalfa --fields `
  realm,accessTokenLifespan,ssoSessionIdleTimeout,ssoSessionMaxLifespan,rememberMe,`
  offlineSessionIdleTimeout,offlineSessionMaxLifespan
```

核对点：`ssoSessionIdleTimeout` 应为 86400、`ssoSessionMaxLifespan` 应为 604800、`rememberMe` 应为 false。

### C2 `msia-prod` 客户端

```powershell
$cid = ((& $KCADM get clients -r inalfa -q clientId=msia-prod --fields id) | ConvertFrom-Json)[0].id
& $KCADM get "clients/$cid" -r inalfa --fields clientId,publicClient,standardFlowEnabled,redirectUris,attributes
```

核对点：`redirectUris` 精确等于 `http://172.26.2.203:8078/api/auth/oidc/callback`；`attributes` 含 `pkce.code.challenge.method=S256`；`attributes` 中与 refresh token 相关的项（若有）。

### C3 scope 与「有没有 offline_access」

```powershell
& $KCADM get "clients/$cid/client-scopes"          -r inalfa --fields name
& $KCADM get "clients/$cid/optional-client-scopes" -r inalfa --fields name
```

核对点：default scope 含 `profile`/`email`；optional 是否含 `offline_access`（默认通常有，但只有被加入 `scope` 才生效）。

### C4 discovery：确认端点与能力（含 `end_session_endpoint`）

```powershell
$issuer = 'https://sso.ap.inalfa.local/realms/inalfa'   # 现场若用 IP 口径，替换为实际 issuer
Invoke-RestMethod "$issuer/.well-known/openid-configuration" |
  Select-Object authorization_endpoint,token_endpoint,userinfo_endpoint,end_session_endpoint,grant_types_supported
```

核对点：存在 `end_session_endpoint`（未来做全局登出）与 `authorization_endpoint`（静默探测用）。

### C5 当前用户的 Keycloak 活动会话（验证登出后果）

```powershell
$uid = ((& $KCADM get users -r inalfa -q username=ligu --fields id) | ConvertFrom-Json)[0].id
& $KCADM get "users/$uid/sessions" -r inalfa
```

核对点：MSIA 点「退出登录」后，这条记录**仍在** → 证实 Keycloak 会话未注销；下一次点统一登录会直接发码。

### C6 MSIA 实际生效的 JWT 密钥长度（不打印明文）

```powershell
# 1) 环境变量是否存在（只显示长度/存在性，不显示值）
if ($env:JWT_SECRET_KEY) { "env_present length=$($env:JWT_SECRET_KEY.Length)" } else { 'env_absent' }

# 2) 服务环境变量（NSSM 方式；服务名按现场替换）
nssm get '<服务名>' AppEnvironmentExtra

# 3) 部署目录 config.ini 的值长度（路径按现场替换，例如 D:\MSIA\config.ini）
$line = (Select-String -Path 'D:\MSIA\config.ini' -Pattern '^jwt_secret_key').Line
"ini_length=$(($line -split '=',2)[1].Trim().Length)"
```

核对点：若为 23，与运行日志告警一致；目标 ≥64。

### C7 实际生效的 OIDC 开关与前端可见配置

```powershell
Invoke-RestMethod 'http://172.26.2.203:8078/api/auth/config'
# 期望：{"oidc_enabled":true,"local_login_enabled":<现场值>}
```

同时确认生产 `config.ini` 的 `[oidc] enabled / scopes / redirect_uri` 与 Keycloak 一致（仓库副本 `enabled=false` 不代表服务器）。

### C8 确认单实例运行

```powershell
Get-CimInstance Win32_Process -Filter "Name='msia_server.exe'" | Select-Object ProcessId,CommandLine
netstat -ano | findstr LISTENING | findstr :8000
```

核对点：只有一个 `msia_server.exe`；8078 的代理若指向多台后端，方案 B 会不稳定（§2.5）。

---

## 7. 风险与回滚

| 变更 | 风险 | 回滚方式 | 影响面 |
|---|---|---|---|
| 更换 `JWT_SECRET_KEY` | 存量 JWT 全部失效 → 全员重登 | 保留旧值不能恢复已失效令牌；只能再换回（仍会重登）。建议窗口内操作并提前通知 | 全员一次性登录 |
| 调整 Keycloak SSO Idle/Max | 调大 → 共享电脑/离职人员会话延长；调小 → 用户被频繁踢下线 | `kcadm update realms/inalfa` 写回旧值；已存在的会话可能按旧上限存活至到期 | 全体 SSO 用户 |
| 开启 Remember Me | 只预填用户名，安全影响小，但用户会误以为「记住密码」 | 控制台关掉即可 | 登录页交互 |
| 上线方案 B | 401 循环、退出后自动登回、静默失败落到错误页 | 回滚到上一个已备份的部署包（现有 `dist/msia_server.bak_*` 机制）；不改数据库，回滚无数据风险 | 登录链路 |
| 缩短 JWT 至 12h | 若 B 未生效，用户会更频繁遇到登录页 | 改回 `jwt_expire_minutes` 并重启 | 全员 |
| 启用 `offline_access` | 首次触发同意页，静默失效 | 从 scope 中移除 | 使用 C2 时 |

上线前建议在测试账号上完成 §9 的验收用例，尤其是「登出后不自动登回」与「401 不循环」。

---

## 8. 为什么「浏览器自动填充用户名密码」不能当成方案

1. **Keycloak 登录页是独立站点**（`sso.ap.inalfa.local`），不是 MSIA 的页面。MSIA 无法控制其表单、也无法编程写入浏览器凭据库。
2. **浏览器凭据库不是应用能力**：是否保存、是否提示、是否自动填充，由浏览器/密码管理器策略与用户设置决定；企业终端可能禁用密码保存。应用不能假设它存在。
3. **即使自动填充成功，仍需人工点击「Sign In」**：这解决的是「少打几个字」，不解决「每次都要登录」；对「打开就进」没有任何帮助。
4. **Keycloak 侧当前 `rememberMe=false`**，登录页连「记住我」都没有；打开后也只预填用户名（§3.2），密码仍需输入。
5. **MSIA 本地登录那条「自动登录」不是同一个东西**：它把明文密码存进浏览器 `localStorage` 并自动提交（§2.7）。这既有安全缺陷（明文口令可被 XSS/本机其他账户读取），也会在 P4 单轨关闭本地登录后失效。把它包装成「SSO 自动填充」属于口径混淆。
6. **正确的替代路径**是「令牌保持 + 静默重认证」：用 30 天 JWT 实现「打开即进」，用 `prompt=none` 实现「到期无感续期」。这两者都不需要碰密码。

---

## 9. 验收用例（方案 B 上线时必测）

| # | 场景 | 预期 |
|---|---|---|
| 1 | 同一浏览器，登录后关闭浏览器再打开 | 直接进看板，不出现 Keycloak 页面 |
| 2 | 手动把 `localStorage['msia-auth'].token` 改成无效值，刷新受保护页 | 自动静默重认证一次，成功后继续；失败则回登录页并提示，不循环 |
| 3 | Keycloak 控制台删除该用户全部会话，再刷新受保护页 | 静默失败 → 登录页「会话已失效」；点按钮 → 输入密码 |
| 4 | 点「退出登录（清除缓存）」 | 停在登录页，**不得**自动静默登回（验证 `msia-just-logged-out` 标记） |
| 5 | 共享电脑：A 退出后 B 登录 | 若未做 end_session，B 会以 A 身份进入（已知缺陷，验收时须明确记录；P5 修复） |
| 6 | 后端重启后，已登录用户刷新页面 | 仍可直接进入（JWT 无状态） |
| 7 | 登录进行中后端重启 | 回调 400 / otk 400，用户点一次重试即可 |
| 8 | Keycloak 停机时打开系统 | 浏览器显示连接错误；返回后可正常用交互式登录 |

---

## 附录 A：关键事实速查

| 事实 | 数值 | 出处 |
|---|---|---|
| MSIA JWT 有效期 | 43200 分钟 = 30 天 | `MSIA Report/backend/config.ini:82`；`app/core/config.py:220` |
| MSIA JWT 算法 | HS256 | `config.ini:79`；`app/core/security.py:57` |
| MSIA JWT 存储 | `localStorage['msia-auth']` | `frontend/src/store/auth.ts:6,120-133` |
| MSIA JWT 刷新 | 无 | 全仓无 refresh 端点 |
| 401 行为 | 清状态 + 提示 + `replace('/login')` | `frontend/src/api/client.ts:41-58` |
| OTK 有效期 / 消费 / 绑定 | 60 秒 / 单次 / 不绑定来源 | `app/core/oidc.py:36,215-243` |
| OIDC state 有效期 | 600 秒（10 分钟） | `app/core/oidc.py:35` |
| 回调保存的 Keycloak 凭证 | 仅 id_token（验签后弃用）；refresh_token 丢弃 | `app/api/auth.py:196-204` |
| scopes | `openid profile email`（无 offline_access） | `config.ini:129` |
| 登出 | 仅本地清态，不调 end_session | `app/api/auth.py:261-268` |
| 会话存储 | 无服务端 session；仅内存 state/OTK | `app/core/oidc.py:42-48` |
| 进程模型 | uvicorn 单 worker | `backend/run.py:70-77` |
| Keycloak SSO Idle / Max（文档设定，待现场确认） | 8h / 12h | `keycloak-realm-clients-init.md:318-319,340` |
| Keycloak access token（文档设定） | 15 分钟 | `keycloak-realm-clients-init.md:317,340` |
| rememberMe（文档设定） | false | `keycloak-realm-clients-init.md:310` |
| 生产 JWT 密钥长度 | 23 字节（告警）vs 仓库 64 字节 | 运行日志 + `config.ini:76`；告警源 `jwt/api_jws.py:201-206` |
