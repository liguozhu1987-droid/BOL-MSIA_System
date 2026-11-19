# Capacity 统一身份登录验收手册（新用户全新建档）

> 适用：Capacity 已切到 `https://iame.ap.inalfa.local:8008`，Keycloak 为 `https://iame.ap.inalfa.local:8443`（realm `inalfa`）。
> 本次只测 **Capacity 一个系统**，不涉及 MSIA / BOL。
> 目标：用一个**在 Capacity 里没有本地账号**的真实 AD 用户，走完「首次登录 → 自动建档 → 待分配角色 → 配权后进入业务页并完成写操作」全链路。

## 1. 适用范围与时间点

| 项 | 值 |
|---|---|
| 被测系统 | Capacity `https://iame.ap.inalfa.local:8008` |
| 身份提供方 | Keycloak `https://iame.ap.inalfa.local:8443`，realm `inalfa` |
| 客户端 | `ics-prod` |
| 测试性质 | 新用户首次登录（全新建档），只读核对 + 一次写操作 |
| 建议时段 | 业务低峰；测试账号的操作会真实落库 |

## 2. 测试前准备

### 2.1 账号

| # | 要求 | 怎么确认 |
|---|---|---|
| 1 | 真实 AD 测试账号，已加入准入组 `app-ics` | Keycloak 管理台 → Users → 该用户 → Groups 含 `app-ics`；AD 侧组成员同步到 Keycloak 后再登录 |
| 2 | 该账号在 Capacity **没有**既有本地账号 | 用员工号在 Capacity 账号管理里搜不到；`CN_AME.dbo.CN_AME_SSO_UserMap` 中也无该员工号记录 |
| 3 | （可选）验证「老账号绑定」时，另备第二个有本地账号的测试人 | 该人已能在 Capacity 本地登录，且账号能对上同一员工号 |

> `app-ics` 不在组里 → 登录能过、回跳后 403。这是本次最常见的误判，先查组，再查应用。

### 2.2 服务器侧只读基线（测前做一次）

在应用服务器上执行，记录到测试记录表：

```powershell
(Get-Service CapacityAPI).Status
(Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 10).StatusCode
Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Get-Content 'C:\Services\logs\CapacityAPI-stderr.log' -Tail 5
```

判据：服务 `Running`、`/health` 返回 `200`、记下开始时间与日志尾部行数（事后比对用）。任一项不满足，先修服务，不要开始浏览器测试。

## 3. 浏览器操作步骤

逐步做，每步记「通过 / 不通过」，不通过时按第 6 节查。

### 3.1 清掉该站点的浏览器数据

- 做什么：清除 `iame.ap.inalfa.local` 的 Cookie 与站点数据；或直接用**无痕窗口**（等价，且不用清正常窗口的登录态）。
- 通过判据：无痕窗口首次打开 8008 时是未登录状态。
- 不对时看哪里：正常窗口里若在其他标签页已登录，会直接进业务页，误判成「新用户免登录」——一律用无痕窗口复测。

### 3.2 打开 Capacity

- 做什么：访问 `https://iame.ap.inalfa.local:8008`。
- 通过判据：出现 Capacity 登录页；地址栏为 `https` 且**无证书警告**。
- 不对时看哪里：证书警告 → 证书/绑定问题（`plan-b-https-cutover-playbook.md` 常见失败对照 1–7）；打不开 → 先回 2.2 确认 `http://127.0.0.1:8000/health` 是 200，再看 IIS 站点状态。

### 3.3 点「统一身份登录」

- 做什么：在登录页点「统一身份登录」。
- 通过判据：浏览器 302 到 `https://iame.ap.inalfa.local:8443/realms/inalfa/...`，出现 Keycloak 登录页。
- 不对时看哪里：DevTools → Network 看该次请求的 `Location`；若是 `Invalid redirect uri` 或停在 8008，按第 6 节第 2 条查。

### 3.4 输入 AD 账号

- 做什么：在 Keycloak 页面输入测试账号与域密码。账号格式按现场实际，通常是 `域名\账号` 或 UPN（`账号@域名`）。
- 通过判据：密码通过，页面开始回跳（不再停在 Keycloak 登录页）。
- 不对时看哪里：账号格式（先用能登录其他内部系统的同一写法）、账号是否被锁、组是否已同步到 Keycloak。

### 3.5 回跳并核对身份

- 做什么：等回跳到 Capacity，看页面右上角/用户菜单。
- 通过判据：显示的用户名或员工号与测试账号一致；不是空白、不是 `undefined`、不是别人。
- 不对时看哪里：显示成另一个账号 → 第 6 节第 4 条（重复建档）；空白 → 看 Capacity 日志尾部有无用户映射报错。

### 3.6 记录首次登录后的角色状态

- 做什么：查看当前用户角色/权限状态，并截图。
- 通过判据：角色为 `sso_pending`。
- 说明：此时**业务页面大概率进不去（403 或空白），这是设计行为，不是故障**。不要在这一步反复重登或改配置。
- 不对时看哪里：若是 403 且提示"未开通"，属正常；若是 500 或跳回登录页，按第 6 节第 3 条查。

### 3.7 退出

- 做什么：点「退出」。
- 通过判据：回到 `https://iame.ap.inalfa.local:8008/login`；Keycloak 侧不报 `Invalid redirect uri`。
- 不对时看哪里：若停在 Keycloak 错误页，记录页面上的 `redirect_uri` 原值与报错文本，按第 6 节第 2 条查。

## 4. 管理员侧核对（只读，最后做）

### 4.1 对照表是否有新建档记录

```sql
SELECT * FROM CN_AME.dbo.CN_AME_SSO_UserMap
WHERE emp_no = '<员工号>' OR email = '<邮箱>';
```

判据：出现该用户的一条记录，员工号/邮箱与测试账号一致（首次登录应新增，而不是命中别人）。用员工号优先，邮箱只在员工号对不上时用。

### 4.2 Keycloak 管理台

| 项 | 位置 | 判据 |
|---|---|---|
| 用户存在 | Users 搜索员工号/账号 | 能搜到，账号未被禁用 |
| 会话已建立 | 该用户 → Sessions | 有一条来自 8008 登录的会话（测试期间） |
| 组含准入组 | 该用户 → Groups | 含 `app-ics` |

### 4.3 应用日志

```powershell
Get-Content 'C:\Services\logs\CapacityAPI-stderr.log' -Tail 200 |
    Select-String 'CERTIFICATE_VERIFY_FAILED|idp_unreachable'
```

判据：**没有**命中。有命中按第 6 节第 1 条处理。

## 5. 配权后的第二轮验证

1. 管理员把该用户角色从 `sso_pending` 调整为实际角色（按岗位授予，测试后回收）。
2. 浏览器先退出，再重新打开 `https://iame.ap.inalfa.local:8008`（无痕窗口可继续用）。
3. 用同一账号再登录一次。
4. 进入一个业务页面并完成**一次写操作**（保存/提交一类），刷新页面确认数据仍在。

判据：能进业务页 + 写操作成功 + 刷新后数据可见，三项全过才算通过。只看到页面不算通过。

## 6. 失败对照表

| # | 现象 | 最可能原因 | 先查什么 |
|---|---|---|---|
| 1 | 日志/页面出现 `idp_unreachable` | 应用侧拉不到 Keycloak 的 discovery，多为信任链或地址不通 | 日志尾部是否有 `CERTIFICATE_VERIFY_FAILED`；`SSL_CERT_FILE` 是否指向 `C:\certs\ca-bundle.pem`、块数是否 6；`https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration` 是否 200 |
| 2 | Keycloak 报 `Invalid redirect uri`，或点登录后停在 8008 | 客户端 `ics-prod` 的回跳地址缺当前域名/端口 | Keycloak 管理台 → Clients → `ics-prod` → Valid redirect URIs 是否含 `https://iame.ap.inalfa.local:8008/*`；退出流程另查 Post logout redirect URIs |
| 3 | 能登录，回跳后 403 / 提示未开通 | 用户不在 `app-ics` 组，或角色仍是 `sso_pending` | Keycloak 用户 Groups 是否含 `app-ics`（第 4.2）；角色状态是否 `sso_pending`（未配权时 403 属预期） |
| 4 | 登录后看到的是另一个账号 | 浏览器残留会话，或该员工号在 Capacity 已有本地账号被匹配（重复建档） | 用无痕窗口重测；查 `CN_AME_SSO_UserMap` 同员工号是否多条；查 Capacity 用户表同员工号是否重复 |
| 5 | 卡在 Keycloak 页面无法回跳 | 回跳地址未放行、Cookie/站点数据异常，或浏览器拦截 | Keycloak 页面上的错误文本；DevTools → Network 里回跳请求的 `Location`；清站点数据后用无痕重试 |

## 7. 测试记录表模板

| 测试人 | AD 账号 | 组 | 浏览器 | 开始时间 | 回跳结果 | 角色 | 写操作结果 | 结论 | 截图编号 |
|---|---|---|---|---|---|---|---|---|---|
|  |  | `app-ics` |  |  | 通过 / 失败 | `sso_pending` / 实际角色 | 未做 / 通过 / 失败 | 通过 / 不通过 | S1–Sn |
|  |  |  |  |  |  |  |  |  |  |

配套记录：2.2 的基线时间与日志行数、4.1 的 UserMap 查询结果、4.3 的日志检索结果。
