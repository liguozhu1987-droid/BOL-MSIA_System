# 方案 A 落地清单：Keycloak 自管密码（AD 只供名单）

> **适用现场**：Keycloak 25.0.6 / realm `inalfa` / client `msia-prod`、`bol-prod` / 服务器 `IRSCnKettle01`（172.26.2.203）
> **方案口径**：AD 只提供 `username` + `email`，**不提供密码**（AD 从不对外提供密码哈希）；密码权威归 Keycloak，**不做 LDAP / User Federation 联邦**。
> **本清单的性质**：按实际执行顺序排列的操作清单。每项四件事：做什么 / 怎么做 / 做完的判据 / 失败时去哪里看。
> **不编造原则**：凡本文标注 **【需现场确认】** 的，都是没有核实过的现场值，必须用紧随其后的命令核对后再填。
> **配套文档**：`统一身份认证技术交底书_MSIA与BOL实施实录.md` 第 21 章、`keycloak/realm-setup.md`、`docs/keycloak-msia-sso-guide-for-beginners.md`。

---

## 0. 开工前准备（照抄即可）

### 0.1 三条前置口径（先确认，再动手）

| # | 口径 | 为什么必须先确认 |
|---|---|---|
| 1 | Keycloak 里这些人是**本地用户**，不是 LDAP 联邦用户 | 本地用户的密码存在 `keycloak` 库 `CREDENTIAL` 表；联邦用户的密码在 AD，本地设密会直接失败或白设 |
| 2 | SMTP 是**正式服务**（`172.19.253.10:25`），但 realm 内是否已配置、是否实测发信成功 **【需现场确认】** | 决定邮件邀请链路能不能用；批量开通仍走统一初始密码，不依赖它 |
| 3 | 不要用 `Login with email` 登录 | 用户拿邮箱登进来，身份解析按 `preferred_username` 对不上本地 `login_name`，会命中失败或建新号 |

### 0.2 命令环境（每开一个新窗口都要跑一次）

```powershell
# 1) kcadm 入口
$KCADM = 'C:\keycloak\bin\kcadm.bat'

# 2) 登录管理通道（<kcadmin 口令> 是物理封存的现场值，不写进任何文档）
& $KCADM config credentials --server 'https://172.26.2.203:8443' --realm master `
  --user kcadmin --password '<kcadmin 口令>'

# 3) 验证登录成功（能返回 realm 名即通过）
& $KCADM get realms/inalfa --fields realm,enabled
```

✅ 判据：`config credentials` 输出 `Logging into https://172.26.2.203:8443 as user kcadmin of realm master`，第 3 条返回 `"realm":"inalfa","enabled":true`。

❌ 失败排查：
- 报证书/SSL 错误 → kcadm 不信任自签证书，检查 `C:\keycloak\conf\kcadm-truststore.jks`（别名 `keycloak-local`，storepass `changeit`）；换过证书必须重建这个 truststore（见 3.2）。
- 报 `401` → 口令错，或你在 `master` 域用了业务域账号。`kcadmin` 只存在于 `master`。
- 所有后续命令都报 401/403 → 证书换过但没重跑第 2 条，会话还是旧的。

### 0.3 工作目录

```powershell
$WORK = 'C:\sso\work\planA'
New-Item -ItemType Directory -Path $WORK -Force | Out-Null
Set-Location $WORK
```

> 下面所有导出文件的路径都相对 `$WORK`。**导出的用户清单含邮箱/姓名，属于个人信息，用完按现场数据管理规定处理。**

### 0.4 执行顺序总览

```text
必须做（P0）       M01 确认无 LDAP 联邦
                  M02 导出账号基线（谁缺什么）
                  M03 关掉 VERIFY_EMAIL
                  M04 核查 user profile 必填项
                  M05 批量补齐 email / firstName / lastName
                  M06 Temporary + UPDATE_PASSWORD 配置
                  M07 统一初始密码（运行时输入，不落盘）
                  M08 批量加入 app-msia / app-bol
                  M09 停用账号禁用与漏检
                  M10 大小写重复建档核查
建议做（P1）      S01 密码策略 / S02 暴力破解 / S03 会话时长
                  S04 事件保留期 / S05 备份策略 / S06 首登抽检 / S07 新员工路径
证书切换时做（P2）C01 issuer 迁移 / C02 CA 证书与 truststore
                  C03 ARR 真实 IP / C04 切回邮件邀请 / C05 切换后回归核对
```

> **M03/M04/M05 必须在 M07 之前做完**。否则用户拿着临时密码登进来，会先被「更新资料」页拦住，还可能因为邮箱为空直接登不进去——这不是密码问题，却会被当成密码问题来排查。

---

## 1. 必须做（P0）

### M01 确认没有 LDAP / User Federation

**做什么**：确认 realm 里没有把 AD 当用户存储接进来。若存在联邦 provider，本地 `set-password` 会失败或只改本地影子记录，用户拿 AD 密码登录，本次所有临时密码方案全部作废。

**怎么做**：

```powershell
& $KCADM get components -r inalfa -q type=org.keycloak.storage.UserStorageProvider
```

控制台等价路径：`Realm Settings → User Federation`。

**做完的判据**：命令返回 `[]`（空数组），或控制台 `User Federation` 页面为空列表。

**失败时去哪里看**：若有返回，先看 `name` / `providerId` 字段判断是不是 LDAP/AD；不要在没确认前执行任何 `set-password`。此时要先决定：删除该 provider（可能带走已导入用户）还是改走联邦方案——**属现场决策，先停下来问**。

---

### M02 导出账号基线（先知道谁缺什么）

**做什么**：把 Keycloak 现有全部用户导出成一份基线，后续所有批量操作都用它做前后对比。

**怎么做**：

```powershell
& $KCADM get users -r inalfa -q max=10000 `
  --fields id,username,email,firstName,lastName,enabled,emailVerified,createdTimestamp `
  | Out-File -LiteralPath (Join-Path $WORK 'kc-users-baseline.json') -Encoding UTF8

# 统计：总数 / 缺邮箱 / 缺姓或名 / 已禁用
$users = Get-Content (Join-Path $WORK 'kc-users-baseline.json') -Raw | ConvertFrom-Json
$stat = [pscustomobject]@{
  total          = @($users).Count
  no_email       = @($users | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.email) }).Count
  no_firstname   = @($users | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.firstName) }).Count
  no_lastname    = @($users | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.lastName) }).Count
  disabled       = @($users | Where-Object { $_.enabled -eq $false }).Count
  email_unverified = @($users | Where-Object { $_.emailVerified -eq $false }).Count
}
$stat | Format-List
```

**做完的判据**：`kc-users-baseline.json` 能解析成对象数组，`total` 等于 Keycloak 控制台 `Users` 列表的总条数（控制台右上角有计数）。四个「缺失数」记录下来，作为 M05 的作业量。

**失败时去哪里看**：返回空数组 → 多半是 `-q max` 参数没生效或 realm 名错；先 `& $KCADM get users -r inalfa --fields username --max 5` 核对。JSON 解析报错 → 文件里混入了 kcadm 的提示行，用 `Get-Content ... | Select-Object -Skip 1` 看一下首行。

> **【需现场确认】** 导入脚本是否把 `display_name` 写进了 `firstName`。若 `no_firstname` 接近总数而 `no_email` 为 0，说明只导了用户名和邮箱，姓名要另行补（见 M05）。

---

### M03 关掉 `VERIFY_EMAIL`（并核查它当前是不是默认必需动作）

**做什么**：确认 `VERIFY_EMAIL` 既没启用、也没被设为「默认动作」。**为什么批量开通要关**：① 统一初始密码 + 强制改密已能保证账号由本人启用；② AD 导入的 `email` 允许空、允许重复，一旦它是默认必需动作，这些用户首次登录就会卡在验证页且无法自救；③ 邮箱在本方案中不是受管属性，验证无实际收益。**注意：理由不是「发不出邮件」——SMTP 是正式服务，但批量开通仍不启用本动作。**

**怎么做（先查）**：

```powershell
& $KCADM get authentication/required-actions -r inalfa `
  --fields alias,name,enabled,defaultAction,priority
```

期望输出里 `VERIFY_EMAIL` 对应的 `enabled=false`、`defaultAction=false`。

控制台等价路径：`Realm Settings → Authentication → Required Actions` 页签，看 `Verify Email` 行的 `Enabled` 与 `Default Action` 两列。

**怎么做（再改，仅在查到不符时执行）**：

```powershell
& $KCADM update authentication/required-actions/VERIFY_EMAIL -r inalfa `
  -s enabled=false -s defaultAction=false
```

**做完的判据**：再跑一次查询，`VERIFY_EMAIL` 的 `enabled`、`defaultAction` 均为 `false`。并且 `UPDATE_PASSWORD` 的 `enabled=true`（M06 要用到）。

**失败时去哪里看**：若 `authentication/required-actions/VERIFY_EMAIL` 报 404，说明 25.0.6 的 alias 大小写不同，改用 `& $KCADM get authentication/required-actions -r inalfa` 原样输出里 `alias` 字段的值。若改完刷新又变回去，说明有别的管理员在改，看 `Realm Settings → Events → Admin events` 里谁改的。

---

### M04 核查 `user profile` 的必填项（决定首登会不会弹「更新资料」页）

**做什么**：Keycloak 的用户资料是「声明式必填」。只要 `email` / `firstName` / `lastName` 被标为 required，而用户这三个字段有空的，首次登录就会被强制跳到资料补全页——用户会以为「密码不对/系统坏了」。

**怎么做**：

```powershell
& $KCADM get users/profile -r inalfa
```

在返回的 JSON 里找 `attributes`，逐项看每个字段的 `required` 值，重点看 `email`、`firstName`、`lastName`。

控制台等价路径：`Realm Settings → General → User profile`（25.0.6 若该入口不可见，改用上面的命令；这是只读核查，不改配置）。

**做完的判据**：能明确写出「这三项中哪几项是 required」。把它记到 M05 的作业范围里。

**失败时去哪里看**：命令 404 / 报错 → 25.0.6 不支持 `users/profile` 端点，退回 `Realm Settings → General` 页面用肉眼确认，或查 `keycloak.log` 中 `UserProfile` 相关行。

> **【需现场确认】本次 21:34 成功登录的 Keycloak 事件序列里出现了 `VERIFY_PROFILE → UPDATE_PROFILE`**，这通常意味着资料补全页**确实被触发过**。请在控制台只读确认 required 标记，并抽一个缺姓名的账号实测一次首登，才能定论。两种收口方式：
> - **首选**：不做任何配置修改，直接按 M05 把三字段补齐（改动小、不动 realm 结构）；
> - **备选**：把 `firstName`/`lastName` 的 `required` 关掉（改动 realm 级配置，会影响所有 client，需评审）。

---

### M05 批量补齐 `email` / `firstName` / `lastName`

**做什么**：按「以中央表为准」补齐 Keycloak 侧缺失字段。原则：**只填空值，不覆盖已有值**（避免把用户在 KC 里改过的名字打回去）。

**怎么做（第一步：生成待补清单）**：

```powershell
$users = Get-Content (Join-Path $WORK 'kc-users-baseline.json') -Raw | ConvertFrom-Json
$bad = $users | Where-Object {
  [string]::IsNullOrWhiteSpace([string]$_.email) -or
  [string]::IsNullOrWhiteSpace([string]$_.firstName) -or
  [string]::IsNullOrWhiteSpace([string]$_.lastName)
}
$bad | Select-Object id,username,email,firstName,lastName |
  Export-Csv -LiteralPath (Join-Path $WORK 'need-fill.csv') -NoTypeInformation -Encoding UTF8
"待补人数: $($bad.Count)"
```

**怎么做（第二步：从中央表取权威值，导出 CSV）**：

```sql
-- 在 SSMS 里对 CN_AME 执行，结果另存为 need-fill-source.csv（UTF-8）
SELECT u.login_name                    AS username,
       ISNULL(u.email, '')             AS email,
       ISNULL(u.display_name, '')      AS display_name
FROM dbo.CN_AME_SSO_User u
ORDER BY u.login_name;
```

**怎么做（第三步：按 username 合并并写入 Keycloak，只填空值）**：

```powershell
$src = Import-Csv (Join-Path $WORK 'need-fill-source.csv') -Encoding UTF8
$map = @{}
foreach ($r in $src) { $map[$r.username.ToLower()] = $r }

$users = Get-Content (Join-Path $WORK 'kc-users-baseline.json') -Raw | ConvertFrom-Json
$log = @()
foreach ($u in $users) {
  $key = ([string]$u.username).ToLower()
  if (-not $map.ContainsKey($key)) { continue }
  $s = $map[$key]

  $sets = @()
  if ([string]::IsNullOrWhiteSpace([string]$u.email) -and $s.email -ne '') {
    $sets += ('email={0}' -f $s.email)
  }
  # 中文姓名整体放 firstName；西文按空格拆 first/last
  if ([string]::IsNullOrWhiteSpace([string]$u.firstName) -or [string]::IsNullOrWhiteSpace([string]$u.lastName)) {
    $dn = [string]$s.display_name
    if ($dn -ne '') {
      if ($dn -match '[\u4e00-\u9fa5]') {
        if ([string]::IsNullOrWhiteSpace([string]$u.firstName)) { $sets += ('firstName={0}' -f $dn) }
      } else {
        $parts = $dn.Trim() -split '\s+', 2
        if ([string]::IsNullOrWhiteSpace([string]$u.firstName)) { $sets += ('firstName={0}' -f $parts[0]) }
        if ($parts.Count -ge 2 -and [string]::IsNullOrWhiteSpace([string]$u.lastName)) { $sets += ('lastName={0}' -f $parts[1]) }
      }
    }
  }
  if ($sets.Count -eq 0) { continue }

  $kcArgs = @('update', "users/$($u.id)", '-r', 'inalfa')
  foreach ($s1 in $sets) { $kcArgs += @('-s', $s1) }
  & $KCADM @kcArgs | Out-Null
  $log += [pscustomobject]@{ username = $u.username; applied = ($sets -join '; ') }
}
$log | Export-Csv -LiteralPath (Join-Path $WORK 'fill-applied.csv') -NoTypeInformation -Encoding UTF8
"已补人数: $($log.Count)"
```

**做完的判据**：
1. `fill-applied.csv` 里每行都有实际写入的字段；
2. 重跑 M02 的统计，`no_email` / `no_firstname` / `no_lastname` 应显著下降（允许少量确实无邮箱/无姓名的账号留存，需单独列名单）；
3. 抽 3 个被补过的账号，打开 `Users → <用户名> → Details`，三字段有值。

**失败时去哪里看**：
- `kcadm update` 无输出无报错但没生效 → 该字段被 user profile 的 validator 拒绝（如邮箱格式非法）；用控制台改一个试试，会看到具体校验提示。
- 报 409 → 邮箱与别人重复且 realm 开了 `Duplicate emails=OFF`（本环境允许重复，若报 409 说明被改过），在 `Realm Settings → General` 核对 `Duplicate emails`。
- 姓名写进去了但显示乱码 → 是 CSV 编码问题（必须 UTF-8，中文不能存成 ANSI）。

---

### M06 `Temporary` 开关与 `UPDATE_PASSWORD` 必需动作的正确配置

**做什么**：让「管理员代设的统一初始密码」只能用一次，用完必须改；不能长期有效。

**正确的组合（缺一不可）**：

| 项 | 应设 | 设错的后果 |
|---|---|---|
| `Credentials → Set password` 的 `Temporary` | **ON** | OFF = 临时密码永久有效，管理员知道的密码一直能登 |
| `Details → Required user actions` 里的 `Update Password` | **ON** | ON（Temporary 开启时 Keycloak 会自动加；没加就手动补） |
| `VERIFY_EMAIL` | OFF | ON = 用户收不到验证邮件，永远卡住（见 M03） |

**怎么做（控制台路径，单人）**：

1. `Users → 搜索用户名 → Credentials → Set password`；
2. `Password` / `Password confirmation` 填临时密码；
3. `Temporary` 开关拨到 **ON** → `Save`；
4. 回到 `Details` 页签，`Required user actions` 里确认有 `Update Password`（没有就选中后 `Save`）。

**怎么做（命令行，可批量）**：

```powershell
# 单人
& $KCADM set-password -r inalfa --username '<用户名>' --new-password '<临时密码>' --temporary

# 核查 requiredActions（应含 UPDATE_PASSWORD）
$uid = (& $KCADM get users -r inalfa -q username='<用户名>' -q exact=true --fields id | ConvertFrom-Json).id
& $KCADM get "users/$uid" -r inalfa --fields username,enabled,requiredActions
```

若 `requiredActions` 里没有 `UPDATE_PASSWORD`（个别版本 `--temporary` 不自动加），用控制台第 4 步补，或用下面的命令：

```powershell
& $KCADM update "users/$uid" -r inalfa -s 'requiredActions=["UPDATE_PASSWORD"]'
```

**实际用户体验（照这个跟用户解释，避免被当成故障）**：

```text
1. 登录页输入：用户名（login_name 小写）+ 部门管理员告知的统一初始密码
2. 若密码正确 → 进入「Update Password」页，要求输入两遍新密码
   - 新密码必须满足密码策略（长度/大小写/数字/特殊字符/不能是用户名或邮箱）
   - 新密码不能与最近几次旧密码相同（passwordHistory）
3. 若资料不全（见 M04/M05）→ 再跳「Update your profile」页，补姓/名/邮箱
4. 完成后自动回到 MSIA/BOL
```

> 用户常见的三个误会：「我密码输对了为什么还要我改」「为什么又让我填资料」「改完为什么还要重新登一次」。按上面 1–4 提前说明即可。

**做完的判据**：`kcadm get users/<id> --fields requiredActions` 返回 `["UPDATE_PASSWORD"]`；`kcadm get users/<id>/credentials` 里该凭据 `temporary: true`；用一个测试账号实际登一次，确认出现改密页。

**失败时去哪里看**：
- 登录后没出现改密页 → `requiredActions` 没设上（回上面核查命令），或用户此前已完成过改密。
- 改密页报「密码不符合策略」→ 看 `Realm Settings → Security → Password policy` 的实际值（见 S01）。
- `set-password` 报 400 `User is not local` → 见 M01，这个账号是联邦用户。
- 改密提交后 500 → 看 `C:\keycloak\logs\keycloak.log`，搜 `UPDATE_PASSWORD` 与 `ERROR`。

---

### M07 统一初始密码：设置与告知（全员同一密码，几百个用户）

**决策（2026-11-09）**：不逐一发放随机临时密码。**全员使用同一个初始密码**，`Temporary=ON`，首次登录强制改密。

**三条铁律**：

1. 初始密码的值**不得写入任何文档、脚本、清单、日志或聊天记录**；
2. 只能由管理员在脚本运行时交互输入（`Read-Host -AsSecureString`），单独封存，交接按密件处理；
3. 脚本不落盘、不把密码放进命令行参数、不写日志（`apply-realm-baseline.ps1` 已按此实现）。

**风险与缓解（必须随方案评审，不能只写「已强制改密」就算完）**：

统一初始密码等于**全员共享一个已知秘密**。在「已设密但未首登」的窗口内，任何人只要知道某个用户名 + 这个初始密码就能冒名登录。**只有在「首登即强制改密」确实生效时，这个方案才可接受。**

| # | 缓解措施 | 是否已实施 |
|---|---|---|
| 1 | `Temporary=ON` + `UPDATE_PASSWORD` 必需动作同时生效，并逐个核查（M06） | 本次必须做 |
| 2 | 密码策略含 `passwordHistory`（≥1），确保用户新密码不能是初始密码；同时 `notUsername` / `notEmail`（S01） | 本次必须做 |
| 3 | **建议项（不擅自实施）**：给「已设密但 14 天未首登」的账号设处置机制——到期前提醒、到期后禁用。判定条件：`requiredActions` 仍含 `UPDATE_PASSWORD` 且 `createdTimestamp` 超过 14 天。执行方式与影响面需业务/安全负责人评审后决定 | 待决策 |
| 4 | 初始密码只用于一次性批量开通，**不得作为长期应急口令**；每次批量开通后即视为已消耗 | 管理约定 |
| 5 | **建议项（不擅自实施）**：当前初始密码与现有管理员口令**命名风格高度相似**，存在用户顺推管理员口令的风险。建议正式推广前更换为一个与任何管理员口令无关的字符串（如随机短语），换值只走「运行时输入」，不写文档 | 待决策 |
| 6 | **约束（不是建议，是硬限制）**：当前初始密码**不含特殊字符**。若后续在 S01 里启用 `specialChars(1)`，这个初始密码将**无法通过密码策略校验**，`reset-password` 会被拒（`invalid password`）。启用该策略前必须先更换初始密码，两者必须同步实施 | 需同步 |

**怎么做**：

```powershell
# 用新的可执行命令块脚本，按菜单选 8（批量设置统一初始密码）
powershell -NoProfile -ExecutionPolicy Bypass `
  -File 'C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\统一身份认证实施\scripts\apply-realm-baseline.ps1'

# 或单独只跑「批量设密」功能：
powershell -NoProfile -ExecutionPolicy Bypass `
  -File 'C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\统一身份认证实施\scripts\apply-realm-baseline.ps1' `
  -Action SetInitialPassword -UserList 'C:\sso\work\planA\users-to-init.txt'
```

脚本行为：读入用户名清单 → 提示输入统一初始密码（`-InitialPassword` 传入或 `Read-Host -AsSecureString` 交互输入，均不回显、不落盘）→ 逐用户 `reset-password` 且 `temporary=true` → 复核并补加 `UPDATE_PASSWORD` → 只输出「成功/失败」计数，**不输出任何密码**。脚本对「不含特殊字符」的密码会给出警告，但不阻断。

**告知方式（值不落文档）**：通过部门会议/内网公告/IT 服务台统一通知「初始密码向部门管理员获取」，密码本身由部门管理员口头传达；通知里只写用户名规则（`login_name` 小写）与首登步骤。建议把首登窗口控制在 1–2 周内，期间每天核对未首登名单。

**做完的判据**：
1. 脚本输出的成功数 = 清单人数，失败数为 0；
2. 抽 3 个账号 `kcadm get users/<id>/credentials` 显示 `temporary: true`，`requiredActions` 含 `UPDATE_PASSWORD`；
3. 抽 1 个账号真实登录，确认进入改密页且**新密码不能与初始密码相同**；
4. 全量核查无 `Temporary=OFF` 的账号：

```powershell
& $KCADM get users -r inalfa -q max=10000 --fields username,requiredActions,enabled |
  Out-File (Join-Path $WORK 'kc-required-actions.json') -Encoding UTF8
```

> **审计局限（必须知道）**：全员共用同一初始密码时，登录事件里的 `username` 只能说明「谁登录了」，**无法区分是本人还是知道该密码的他人**。因此首登完成率、首登时间集中度是主要观测指标；异常集中登录（深夜、异地、同一 IP 多个账号）要单独排查。

**失败时去哪里看**：
- `set-password` 报 400 `User is not local` → 联邦用户，见 M01。
- `set-password` 报 `invalid password` → 初始密码不满足密码策略（`Realm Settings → Security → Password policy`），换一个满足策略的值重试。
- 用户报「密码错误」→ 先查 `Users → <用户名> → Credentials` 是否 `temporary`，再看 `Events` 里的 `LOGIN_ERROR`（是否 `invalid_user_credentials`）；确认不是把邮箱当用户名（邮箱登录未开，见 0.1 第 3 条）。
- 用户报「登录后一直进不去」→ 不是密码问题，回到 M04/M05 看资料必填。
- 批量跑到一半失败 → 逐条查失败用户名；**不要重跑全量**（已设成功的账号会被重设为初始密码，用户可能已经改过密，重设等于把他踢回初始态）。

---

### M08 批量把用户加入 `app-msia` / `app-bol`

**做什么**：把「有该系统权限」的人加进对应准入组。**漏加的后果是 403「未开通本系统访问权限」**，且 403 发生在 OIDC 回调之后，用户会看到「登录成功了但进不去」。

**怎么做（先取组 ID）**：

```powershell
$gMsia = (& $KCADM get groups -r inalfa -q search=app-msia --fields id,name,path | ConvertFrom-Json)
$gBol  = (& $KCADM get groups -r inalfa -q search=app-bol  --fields id,name,path | ConvertFrom-Json)
$gMsia | Select-Object name,path,id
$gBol  | Select-Object name,path,id
```

✅ 判据：`path` 必须是 `/app-msia`、`/app-bol`（顶层组）。若出现 `/xxx/app-msia`，是建成了子组，令牌里会带全路径导致 403。

**怎么做（批量加组）**：

```powershell
function Add-UsersToGroup {
  param([string]$GroupId, [string]$ListFile)
  $names = Get-Content $ListFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() }
  $ok = 0; $fail = @()
  foreach ($n in $names) {
    $u = (& $KCADM get users -r inalfa -q username=$n -q exact=true --fields id | ConvertFrom-Json)
    if ($null -eq $u -or $null -eq $u.id) { $fail += "$n(用户不存在)"; continue }
    & $KCADM update "users/$($u.id)/groups/$GroupId" -r inalfa -n | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok++ } else { $fail += "$n(加组失败)" }
  }
  "成功 $ok 人；失败: $($fail -join ', ')"
}

Add-UsersToGroup -GroupId $gMsia.id -ListFile (Join-Path $WORK 'members-msia.txt')
Add-UsersToGroup -GroupId $gBol.id  -ListFile (Join-Path $WORK 'members-bol.txt')
```

> 成员清单从哪来：**以权限台账为准**。`realm-setup.md` §7 记录了首批 13 人名单位，但后续变更要按台账。若台账字段未核实，**【需现场确认】`CN_AME_SSO_PermLedger` 的表结构与导出 SQL**，不要凭猜写。

**做完的判据**：随机抽 3 人执行

```powershell
$uid = (& $KCADM get users -r inalfa -q username='<用户名>' -q exact=true --fields id | ConvertFrom-Json).id
& $KCADM get "users/$uid/groups" -r inalfa --fields name,path
```

返回里应含 `app-msia`（或 `app-bol`）。更强的判据是用 `Clients → msia-prod → Client scopes → Evaluate`，选该用户生成 token，确认 `groups` claim = `["app-msia"]`（**不带斜杠**）。

**失败时去哪里看**：
- 用户登录后 403 → 先查组，再查 mapper 的 `Full group path` 是否为 OFF（`Clients → msia-prod → Mappers → groups`）。
- `users/<id>/groups/<gid>` 报 404 → 组 ID 拿错（`search` 可能匹配到多个组），用完整 `get groups` 列表核对。
- 加组成功但 token 里没有 → token 是登录时签发的旧 token，让用户退出重登。

---

### M09 AD 已停用账号在 Keycloak 里禁用，并核对有没有漏

**做什么**：中央表 `CN_AME_SSO_User.status=0` 的人，Keycloak 侧必须 `Enabled=OFF`，并踢掉现有会话。停用是「永不物理删除」。

**怎么做（正确驱动方式）**：由 `sync_sso_to_keycloak.ps1` 统一执行（`status=0 且附 enabled → 禁用 + POST logout`）。**不要手工在控制台逐个人点**——手工做的会被下次同步按中央表覆盖，且容易漏。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File 'C:\WorkFile\D\OPEX\04-Digital_development\2026\AI Agent Development Application\统一身份认证实施\scripts\powershell\sync_sso_to_keycloak.ps1'
```

> **【需现场确认】** `sync_sso_to_keycloak.ps1` 对「新建用户且有邮箱」会调用 `execute-actions-email`。**SMTP 是正式服务，该调用理论上可用**，但「realm 已配置 Email、实测发信成功」本轮未核实。核查命令：`kcadm get realms/inalfa --fields realm,smtpServer,smtpPort,smtpFrom` 与 `Realm Settings → Email → Test Connection`。未确认前，建号后按 M07 统一设初始密码，不依赖邮件链路；如实测发信失败，再评估给脚本加 `-SkipEmailInvite` 开关。

**怎么做（核对有没有漏）**：

```sql
-- 在 SSMS 对 CN_AME 执行：中央表里应停用的人
SELECT login_name, employee_no, status, updated_at
FROM dbo.CN_AME_SSO_User
WHERE status = 0
ORDER BY login_name;
```

把结果导出为 `central-disabled.csv`（列名 `login_name`）。

```powershell
# Keycloak 侧当前已禁用的账号
$all = Get-Content (Join-Path $WORK 'kc-users-baseline.json') -Raw | ConvertFrom-Json
$kcDisabled = $all | Where-Object { $_.enabled -eq $false } | Select-Object username
$kcDisabled | Export-Csv -LiteralPath (Join-Path $WORK 'kc-disabled.csv') -NoTypeInformation -Encoding UTF8

# 比对：中央停用但 KC 仍启用 = 漏禁用
$central = Import-Csv (Join-Path $WORK 'central-disabled.csv')
$enabled = $all | Where-Object { $_.enabled -eq $true } | ForEach-Object { ([string]$_.username).ToLower() }
$missed = $central | Where-Object { $enabled -contains ([string]$_.login_name).ToLower() }
"漏禁用人数: $(@($missed).Count)"
$missed | Export-Csv -LiteralPath (Join-Path $WORK 'missed-disable.csv') -NoTypeInformation -Encoding UTF8
```

再用 SQL 侧交叉核对（`91_usermap_integrity_checks.sql` 第 8 节）：

```sql
-- 8.1 MSIA：中央 status=0 但本地 Status 仍启用
SELECT m.Username, m.Status AS local_status, u.status AS central_status
FROM dbo.CN_AME_MISA_User m
JOIN dbo.CN_AME_SSO_User u ON u.login_name = LOWER(LTRIM(RTRIM(m.Username)))
WHERE u.status = 0 AND m.Status = 1;

-- 8.2 BOL：中央 status=0 但本地仍 ACTIVE
SELECT e.username, e.status AS local_status, u.status AS central_status
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
JOIN dbo.CN_AME_SSO_User u ON u.login_name = LOWER(LTRIM(RTRIM(e.username)))
WHERE u.status = 0 AND e.status = 'ACTIVE';
```

**做完的判据**：
1. `missed-disable.csv` 为空（或差异已逐条写明原因）；
2. `91` 号脚本第 8 节两条查询返回空，或差异已由业务确认；
3. 抽一个被停用的人实测：登录页报 `Account is disabled`，已登录的会话被踢（再访问系统要重新认证）。

**失败时去哪里看**：
- 禁用没生效 → 看 `C:\sso\logs\sync_sso_to_keycloak_<日期>.log`，搜 `已禁用并踢会话`；再看 `CN_AME_SSO_SyncLog` 的 `phase='KC'` 行。
- 踢会话失败（日志写「踢会话失败(不影响停用结果)」）→ 用户可能仍能用旧的本地 JWT 走进 MSIA/BOL；这是已知设计边界，需靠本地账号状态同步（MSIA `SSO_USER_SYNC_ENABLED` / BOL 每小时回写）兜底。
- 停用的人又能登 → 先查中央表是否被复职（`status=1`），再看 AD 名单是否把人带回来了（`StgAdUser`）。

---

### M10 大小写重复建档的核查（SQL Server 排序规则相关）

**做什么**：查「同一自然人存在两个仅大小写/首尾空白不同的账号」。这类账号会让身份解析随机命中，权限、密码、令牌全部分叉。

**怎么做（第一步：跑既有校验脚本）**：

```powershell
# 在 SSMS 里整份执行（只读，不含写入）
# 统一身份认证实施\scripts\sql\91_usermap_integrity_checks.sql
```

重点看这三节，**预期全部为空**：

| 节 | 查什么 | 预期 |
|---|---|---|
| 4.2 | 本地表内仅大小写/空白不同的重复行 | 空 |
| 4.3 | 中央 `login_name` 命中多个本地账号 | 空 |
| 6 | 中央表 `login_name` 大小写重复 | 空（`UQ_CN_AME_SSO_User_Login` 在 CI 排序规则下也会拦） |

**怎么做（第二步：Keycloak 库侧复核）**：

```sql
-- 对 keycloak 库执行（realm_id 用子查询定位）
SELECT LOWER(username) AS username_lower, COUNT(*) AS cnt
FROM user_entity
WHERE realm_id = (SELECT id FROM realm WHERE name = 'inalfa')
GROUP BY LOWER(username)
HAVING COUNT(*) > 1;
```

**做完的判据**：`91` 号脚本 4.2 / 4.3 / 6 节为空；keycloak 库查询为空。

**失败时去哪里看**：
- `91` 第 4.2 节有行 → **不要批量自动合并**。逐条人工裁决：保留有 `PasswordHash`/有业务数据的那条，另一条在 `UserMap` 只登记一条，旧账号按「停旧建新」口径处理。
- `91` 第 4.3 节有行 → 说明本地账号一对多，先确认哪条是真实在用的（看 `CreatedAt`、`LastLogin`、业务数据量），再决定。
- `user_entity` 查询报权限不足 → 换 `keycloak_svc` 或 DBA 账号执行；Keycloak 侧 username 按小写归一存储，**理论上不会出现仅大小写不同的重复**，这条查询用于复核，不是新增风险。

---

## 2. 建议做（P1）

### S01 密码策略

**建议值**（与 `keycloak/realm-setup.md` §3 对齐，现场以命令查出的实际值为准）：

| 项 | 建议 | 理由 |
|---|---|---|
| 最小长度 | 12（现状 10） | 自助重置依赖邮件、且要求邮箱可用；被撞库后多数情况只能找管理员，加长度是最便宜的收益 |
| 必须含大写/小写/数字/特殊字符 | 各 ≥1 | 与现状一致 |
| Not username / Not email | ON | 防「用户名当密码」 |
| 密码历史 | 5 | 防改回临时密码 |
| 密码过期 | OFF | 内部系统，强制定期改密会显著增加重置工单 |

**怎么做**：

```powershell
# 先看现状
& $KCADM get realms/inalfa --fields realm,passwordPolicy

# 再改（仅在确认现状不符时执行）
& $KCADM update realms/inalfa -s 'passwordPolicy=length(12) and digits(1) and lowerCase(1) and upperCase(1) and specialChars(1) and notUsername(undefined) and notEmail(undefined) and passwordHistory(5)'
```

**判据**：再查一次 `passwordPolicy` 返回新串；用一个测试账号设一个 10 位密码，被拒并提示长度不足。

**失败排查**：改完不生效 → 语法串写错（少空格、`and` 拼错）；`passwordHistory` 需要 Keycloak 能读取历史凭据，若历史空则首几次不生效属正常。

> **提醒**：策略越严，重置工单越多（自助重置要先确认邮件链路真的可用）。邮件自助重置未实测前，不建议开到「16 位 + 季度强制改」。

> **与 M07 的冲突（必须一起看）**：当前统一初始密码**不含特殊字符**。若把上表的 `specialChars(1)` 直接上线，`reset-password` 会对这个初始密码报 `invalid password`，M07 的批量设密会整体失败。启用 `specialChars(1)` 之前，必须先把初始密码换成含特殊字符的新值（且不写入任何文件），两者同步实施；只改策略不改密码，等于把批量开通打断。

---

### S02 暴力破解防护

**建议值**（与交底书 9.3、`realm-setup.md` §4 对齐）：

| 项 | 建议 | 说明 |
|---|---|---|
| Brute Force Detection | ON | 必开 |
| Failure factor | 5 | 5 次失败开始惩罚 |
| Wait increment | **900 秒（15 分钟）** | 与交底书 §9.3「失败 5 次锁 900 秒」一致；本文早期写的 60 秒作废 |
| Max failure wait | 900 秒（15 分钟） | 单次锁定时长上限 |
| Permanent lockout | **OFF** | 无自助重置，永久锁定只能管理员手工解锁，会变成工单洪水 |
| Max delta time | 43200 秒（12 小时） | **暴力破解计数窗口**，指「12 小时内的失败次数累计」；与会话最长 7 天不是同一个参数，别混 |

```powershell
& $KCADM get realms/inalfa --fields realm,bruteForceProtected,failureFactor,waitIncrementSeconds,maxFailureWaitSeconds,maxDeltaTimeSeconds,permanentLockout

# 仅在现状不符时执行
& $KCADM update realms/inalfa `
  -s bruteForceProtected=true -s failureFactor=5 `
  -s waitIncrementSeconds=900 -s maxFailureWaitSeconds=900 `
  -s maxDeltaTimeSeconds=43200 -s permanentLockout=false
```

**判据**：故意用错密码试 5 次，第 6 次提示「Invalid username or password.」且等待时间明显变长；`Realm Settings → Security defenses` 页面显示 ON。

**失败排查**：锁定了却不自动解 → 看 `permanentLockout` 是否被误开；解锁方式：控制台 `Users → <用户> → 右上角 Action → Clear brute force` 或用 `kcadm delete attack-detection/brute-force/users/<userId>`。

---

### S03 会话时长

**建议值**（**以交底书 §9.3 为准**；现场决定 2026-11-09 改为 1 天 / 7 天，覆盖原 8h/12h，原值作废）：

```powershell
& $KCADM get realms/inalfa --fields realm,ssoSessionIdleTimeout,ssoSessionMaxLifespan,accessTokenLifespan,actionTokenGeneratedByUserLifespan
```

| 项 | 建议 | 说明 |
|---|---|---|
| SSO Session Idle | **86400 秒（1 天）** | 现场决定；加长不踢已登录用户 |
| SSO Session Max | **604800 秒（7 天）** | 超过此时长强制重新认证 |
| Access Token Lifespan | 900 秒（15 分钟） | 现状值，保持 |
| Action Token (User) Lifespan | 4320 分钟（3 天） | 用于邮件设密/重置链接 |

> **方向性说明**：本次是**加长**，不会让已登录用户失效（只有缩短才会）。因此对在用用户**无感**，但仍建议在低峰执行并回读确认。

**重要背景**：两系统目前都**只做本地登出**，Keycloak 的 SSO Cookie 不会清（详见 `docs/sso-session-and-silent-login.md` §2.4）。共享电脑上「A 退出、B 点统一登录」会直接进 A 的账号。会话放宽到 1 天/7 天后该窗口更长，**该风险作为独立事项跟进**（例如共享机位强制本地登出），不要靠调低全局 Idle 解决。

**判据**：改完后刷新页面值不变；空闲超过 Idle 后访问需重新登录。

**失败排查**：改了但行为没变 → 用户在旧会话里；让他退出后重登（会话参数在新建会话时生效）。

---

### S04 事件审计的保留期

**建议值**：

| 项 | 建议 | 说明 |
|---|---|---|
| Save Events（用户事件） | ON | 登录/登出/登录失败/改密全靠它 |
| Expiration（用户事件） | **90 天** | `eventsExpiration` 单位是**秒**，90 天 = `7776000` |
| Save Admin Events | ON | 谁改了 realm/client/用户 靠它 |
| Include Representation | **OFF** | 打开会把请求体写进库，可能含 client secret |

```powershell
& $KCADM get events/config -r inalfa

& $KCADM update events/config -r inalfa `
  -s eventsEnabled=true -s eventsExpiration=7776000 `
  -s adminEventsEnabled=true -s adminEventsDetailsEnabled=false
```

**做完的判据**：`get events/config` 返回 `eventsEnabled=true`、`eventsExpiration=7776000`；`Events` 页能按时间筛选到最新登录事件。

**失败时去哪里看**：
- 【需现场确认】`events/config` 返回体里是否有 `adminEventsExpiration` 字段。25.0.6 的 `Expiration` 通常只清理**用户事件**；**管理员事件不自动过期**，需要定期在控制台 `Clear admin events` 或按时间导出后清理，否则库会持续增长。
- 事件页空白 → 看 `eventsEnabled` 是否被关，或 `eventsListeners` 是否只剩 `jboss-logging`（本环境默认如此，事件仍会入库）。
- 磁盘/库增长快 → 先确认 `eventsExpiration` 单位没写成「天」（写成 7776000 天等于永不过期）。

---

### S05 备份：数据库备份 vs realm 结构导出（**哪个能救用户，哪个只能救配置**）

**一句话结论**：

| 备份方式 | 能救什么 | **不能**救什么 | 恢复后用户要做什么 |
|---|---|---|---|
| **SQL Server `keycloak` 库完整备份** | 用户账号、**密码哈希（凭证）**、组、client、secret、会话表、签名密钥 | 跨版本直接还原（Keycloak 版本必须一致） | **不用重设密码**，直接登录 |
| **realm 导出（JSON）** | realm/client/组/mapper/策略等**配置结构** | **不含密码/凭据**（导出永远拿不到密码哈希） | **全部用户必须重设密码** |

> 所以：**日常救「用户能不能登录」靠数据库备份；realm 导出只能救「配置改坏了怎么回滚」。两个都要做，不能互相替代。**

**怎么做（数据库备份）**：

```powershell
# <dbuser>/<dbpwd> 从现场凭据文件取，不要写进文档或命令行历史
sqlcmd -S IRSCNYTFINEREPORT.ap.inalfa.local -d master `
  -U '<dbuser>' -P '<dbpwd>' `
  -Q "BACKUP DATABASE keycloak TO DISK='D:\backup\keycloak_$(Get-Date -Format yyyyMMdd_HHmm).bak' WITH INIT, COMPRESSION, CHECKSUM"
```

建议：每日 01:00 全备 + 保留 30 天；每季度做一次**还原演练**（在测试实例还原并启动一次 Keycloak，确认能登录）。

**怎么做（realm 导出）**：

```powershell
# 计划任务每周日 02:00（realm-setup.md §10 已有 SSO_KC_Export）
& 'C:\keycloak\bin\kc.bat' export --dir 'C:\sso\kc-export' --realm inalfa
```

**判据**：
1. `D:\backup\` 下每天有一个 `.bak`，大小与前一天同量级（骤降说明备份失败或库被清）；
2. 每季度还原演练成功（能启动、能用测试账号登录）；
3. `C:\sso\kc-export` 下有本周的 JSON，且能用 `kcadm create realms -f` 在某测试实例导入（只验证格式，不覆盖生产）。

**失败时去哪里看**：备份作业日志（任务计划程序历史）；`sqlcmd` 报错码 3201/3241 多为路径或权限问题；`kc.bat export` 报错看 `C:\keycloak\logs\keycloak.log`，注意 export 模式要求数据库配置可连。

---

### S06 首登体验抽检（上线前必做）

**做什么**：挑 3 个真实用户（1 个有邮箱有姓名、1 个刚刚被 M05 补齐、1 个无邮箱），各走一遍完整首登，验证 M03–M07 的组合真的生效。

**怎么做**：每人按 `用户名 + 统一初始密码` 登录（密码向部门管理员口径获取，不写在本清单里），记录四步链路各花了多久、卡在哪一页。

**判据**：三人全部能到「改密页 →（按需）资料页 → 回到系统」；MSIA/BOL 业务接口返回 200；`Events` 页能看到 `LOGIN → UPDATE_PASSWORD` 序列。

**失败排查**：任何一人卡住，按卡住页面定位：改密页卡住 → S01 策略；资料页卡住 → M04/M05；403 → M08；登录失败 → M07。

---

### S07 新员工入职路径（SMTP 正式服务期）

**做什么**：明确「新入职的人怎么拿到第一个密码」。

**怎么做**：新员工由 AD → 中央表 → `sync_sso_to_keycloak.ps1` 建号，脚本会尝试发邀请邮件。SMTP 是正式服务，该路径**理论上可用**；但需先确认 realm 已配置 Email 且实测发信成功（`Realm Settings → Email → Test Connection` 或 `kcadm get realms/inalfa --fields smtpServer`）。

- 若邮件链路已实测通过：新员工走「收邮件 → 设密」自动路径；
- 若未确认或实测失败：建号后由管理员按 M07 统一设初始密码并通过部门管理员告知，**不要**让新员工等一封可能发不出的邮件。

**判据**：新员工从入职名单出现到能登录，有人负责、有台账记录、有完成时间；邮件路径与人工路径在台账上可区分。

**失败排查**：`C:\sso\logs\sync_sso_to_keycloak_<日期>.log` 搜该用户名；`CN_AME_SSO_SyncLog` 对应行；`execute-actions-email` 报错看 `keycloak.log` 中 `Failed to send email`。

---

## 3. 证书切换时做（P2）

> 前提：CA 证书签发后，`hostname` 从 IP 口径切到 `sso.ap.inalfa.local`，并接入 IIS ARR。**这一批操作会改变 issuer，所有已登录用户会失效一次**，必须排窗口。

### C01 issuer / hostname 迁移的影响面

**做什么**：切换前把「谁引用了 issuer」全部列出来，避免切完一半系统登不上。

**怎么做（先盘点）**：

```powershell
# Keycloak 当前 issuer 回显（切换前后各跑一次，做对比）
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$d = Invoke-RestMethod 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration'
$d.issuer
[Net.ServicePointManager]::ServerCertificateValidationCallback = $null
```

受影响的配置（逐项改）：

| 位置 | 字段 | 改什么 |
|---|---|---|
| MSIA `backend/config.ini` | `[oidc] issuer` | IP 口径 → `https://sso.ap.inalfa.local/realms/inalfa` |
| MSIA `[oidc] redirect_uri` | 回调地址 | 若 MSIA 也上域名，同步改；否则保持 IP:8078 |
| BOL `db_config.ini` | `[oidc] issuer` / `redirect_uri` | 同上 |
| Keycloak client `msia-prod` / `bol-prod` | `Valid redirect URIs` / `Web origins` | 加新域名行，**不要删旧行**（回滚要用） |
| Keycloak `keycloak.conf` | `hostname` / `hostname-strict` | `sso.ap.inalfa.local` / `true` |

**判据**：`/.well-known/openid-configuration` 的 `issuer` 与三处配置逐字一致；MSIA `/api/auth/config` 正常；真实登录一次成功。

**失败排查**：`IP address mismatch` / `issuer mismatch` → 回到 `docs/keycloak-msia-sso-guide-for-beginners.md` §1.4 的口径核对；MSIA 启动时体检不过会返回 503（见 `app/core/oidc.py` 的 `validate_config`）。

---

### C02 CA 证书替换 + kcadm truststore 重建

**做什么**：把 `C:\keycloak\conf\server.crt.pem` / `server.key.pem` 换成企业证书，并让 kcadm 继续信任。

**怎么做**：

```powershell
# 1) 替换证书后重启服务
Restart-Service -Name 'Keycloak'
Start-Sleep -Seconds 30

# 2) 确认 8443 在监听
Get-NetTCPConnection -State Listen -LocalPort 8443 | Select-Object LocalAddress,LocalPort,OwningProcess

# 3) 重建 kcadm truststore（把新证书导进去）
& '<JDK路径>\bin\keytool.exe' -importcert -noprompt `
  -alias keycloak-local -file 'C:\keycloak\conf\server.crt.pem' `
  -keystore 'C:\keycloak\conf\kcadm-truststore.jks' -storepass changeit

# 4) 重新登录 kcadm（换了证书必须重登，否则后续命令全报 401/403）
& $KCADM config credentials --server 'https://172.26.2.203:8443' --realm master `
  --user kcadmin --password '<kcadmin 口令>'
```

**判据**：`Restart-Service` 后 `State=Running`；8443 监听正常；`kcadm get realms/inalfa` 返回正常；浏览器打开登录页证书链验证通过（无「不安全」提示）。

**失败排查**：`C:\keycloak\logs\service-stderr.log`（起不来）、`C:\keycloak\logs\keycloak.log`（证书加载失败）；私钥有口令时需在 `keycloak.conf` 配 `https-key-store-password`（PEM 模式补对应配置项）；**不要为了「让证书好过」关掉 `Require SSL`**。

---

### C03 ARR 反代后的真实 IP 与 proxy-headers

**做什么**：经 IIS ARR 后，Keycloak 事件里的 `ipAddress` 默认会变成反代机地址，审计价值下降。

**怎么做**：确认 `keycloak.conf` 里

```properties
proxy-headers=xforwarded
hostname-strict=true
```

并在 IIS ARR 规则里转发 `X-Forwarded-For` / `X-Forwarded-Proto` / `X-Forwarded-Host`。

**判据**：切换后触发一次登录，`Events` 页里该条事件的 `ipAddress` 是**用户真实终端 IP**，不是 `127.0.0.1` 也不是 ARR 机 IP。

**失败排查**：仍显示反代机 IP → 检查 ARR 规则是否真的写了 `X-Forwarded-For`；检查 Keycloak 是否重启使配置生效。

> 顺带说明：本次 21:34 的实证里 Keycloak Event 记录 `10.41.0.64`、MSIA 控制台记录 `10.41.10.64`，两者口径不一致，属待核对项（见交底书 20.1）。C03 做完后可解释这一差异。

---

### C04 确认 SMTP 配置并启用「邀请设密邮件」（可选增强）

**做什么**：SMTP 已是正式服务（`172.19.253.10:25`），但 realm 内是否已配置、是否实测发信成功 **【需现场确认】**。确认后，邮件邀请可作为批量开通之外的常规路径，降低长期人力成本。

**怎么做**：

1. 先核对 realm 当前配置（`smtpServer` 是一个 map，里面的键就是 host / port / from / fromDisplayName / auth / starttls / ssl）：

```powershell
& $KCADM get realms/inalfa --fields realm,smtpServer
```

2. 若 `smtpServer` 为空，进控制台 `Realm Settings → Email` 按正式服务填（与交底书 §9.5 一致）：

| 字段 | 值 |
|---|---|
| `Host` | `172.19.253.10` |
| `Port` | `25` |
| `From` | `ap_sso@inalfa.com` |
| `From Display Name` | `Inalfa AME系统统一身份认证` |
| `Authentication` | OFF（`auth=false`，本服务为无认证内网中继） |
| `Enable StartTLS` | OFF（`starttls=false`，当前为**明文**中继） |
| `Enable SSL` | OFF（`ssl=false`） |

   > 若后续邮件网关启用 STARTTLS，需把 `starttls` 改为 `true`（必要时同步调整端口）后保存，并**重新做一次实测发信**，不能只看保存成功。
3. 保存后点 `Test Connection`（只证明连得上、能握手），然后做**实测发信**：对 1 个测试账号执行 `execute-actions-email`（见第 5 步），确认收件箱**确实收到**验证信。**判据是「确实收到信」，不是「Test Connection 成功」或「保存成功」**。
4. `Realm Settings → General` 确认 `Forgot password = ON`；
5. 对未首登用户（仍含 `UPDATE_PASSWORD`）执行：

```powershell
$uid = (& $KCADM get users -r inalfa -q username='<用户名>' -q exact=true --fields id | ConvertFrom-Json).id
& $KCADM create "users/$uid/execute-actions-email" -r inalfa -b '["UPDATE_PASSWORD"]'
```

> kcadm 的 `create` 对应 POST；若该版本命令不适用，控制台 `Users → <用户名> → Credentials → Credential reset → Send email` 等价。

5. **批量开通仍以 M07 的统一初始密码为主**；邮件邀请只用于零散补开、忘记密码，以及后续新员工自动路径（S07）。

**判据**：`Test Connection` 绿；测试账号能收到邮件并完成设密；`Action Token Lifespan` 足够长（否则链接过期，见 S03）。

**失败排查**：邮件进垃圾箱 → 发件域 SPF/DKIM（找 IT）；链接过期 → `Action Token Generated By User Lifespan`；点击链接报 `Invalid requester` → client 的 `Valid redirect URIs` 与链接域不一致。

---

### C05 切换后回归核对

**做什么**：证书 + 域名切换后，把 P0 的核对项再跑一遍（配置变了，用户状态没变，但解析与事件口径会变）。

**怎么做**：重跑 M02（导出基线）、M08 的抽检、M09 的比对、C01 的 issuer 对比、C03 的 IP 核对，以及 `collect-sso-login-evidence.ps1` 一次完整采集。

**判据**：与切换前的基线相比，用户数、缺字段数、组归属、禁用数均无异常变化；证据包能复现一次成功登录。

---

## 4. 一页速查：判据与排查入口

| 症状 | 最可能原因 | 先看这里 |
|---|---|---|
| 登录页报密码错，但密码确认是对的 | 用了邮箱登录 / 用户名大小写错 / 账号被禁用 | `Users → <用户名> → Details`；`Events → LOGIN_ERROR` |
| 登录成功但进不去系统（403） | 没加 `app-msia` / `app-bol` 组，或 mapper `Full group path=ON` | M08；`Clients → Mappers → groups` |
| 登录成功后被要求填资料 | user profile 必填项缺失 | M04 / M05 |
| 登录成功后被要求验证邮箱 | `VERIFY_EMAIL` 被设为默认必需动作 | M03 |
| 改了密还是登不进 | 新密码不满足策略 / 被 Brute Force 锁定 | S01 / S02 |
| 统一初始密码能登但没要求改密 | `Temporary=OFF` 或 `UPDATE_PASSWORD` 未生效 | M06 |
| 停用的人还能进 | 中央表未停用 / KC 未同步 / 本地 JWT 未失效 | M09 |
| 同一个人有两个账号 | 大小写重复建档 | M10 |
| 邮件发不出 | realm 未配置 Email / SMTP 不通 / 发件域被拦 | 本清单 0.1；C04 |

**日志与证据位置**：
- Keycloak 主日志：`C:\keycloak\logs\keycloak.log`
- 服务启动错误：`C:\keycloak\logs\service-stderr.log`（25.0.6 若不存在，看 NSSM 配置的 stdout/stderr 路径）
- 同步日志：`C:\sso\logs\sync_sso_to_keycloak_<yyyyMMdd>.log`、`C:\sso\logs\sync_ad_to_sso_<yyyyMMdd>.log`
- 同步结果表：`CN_AME.dbo.CN_AME_SSO_SyncLog`（`phase='KC'`）
- 登录证据包：`统一身份认证实施\evidence\<yyyyMMdd-HHmmss>\evidence.md`
- 控制台事件：`Realm Settings → Events`（用户事件）、`Admin events`（管理操作）

---

## 5. 需现场确认项汇总（逐条核完再动手）

| # | 待确认项 | 核查方式 |
|---|---|---|
| 1 | **SMTP 是正式服务**（`172.19.253.10:25`、from `ap_sso@inalfa.com`），但 realm 内是否已配置 Email、是否实测发信成功未核实 | `Realm Settings → Email → Test Connection`；`kcadm get realms/inalfa --fields smtpServer`；**真正判据是对测试账号发一封并确认收到** |
| 2 | `user profile` 中 email/firstName/lastName 的 required 实际值 | `kcadm get users/profile -r inalfa` |
| 3 | 导入时是否写入了 firstName/lastName | M02 统计 `no_firstname` / `no_lastname` |
| 4 | 密码策略实际值（realm-setup 说有大写等，交底书只写长度 10） | `kcadm get realms/inalfa --fields passwordPolicy` |
| 5 | 会话时长实际值（口径已定 **空闲 1 天 / 最长 7 天**，需核对生产是否已改；原 8h/12h 已作废） | `kcadm get realms/inalfa --fields ssoSessionIdleTimeout,ssoSessionMaxLifespan`（期望 86400 / 604800） |
| 6 | 事件保留期实际值 | `kcadm get events/config -r inalfa` |
| 7 | `app-msia` / `app-bol` 当前成员是否与台账一致 | M08 的抽检命令 + 台账 |
| 8 | `sync_sso_to_keycloak.ps1` 建号时 `execute-actions-email` 的实际表现（SMTP 是正式服务，理论上可用，但需确认已实测发信） | 用测试账号实跑一次建号分支，看日志与 SyncLog，并确认收件箱收到信 |
| 9 | `CN_AME_SSO_PermLedger` 的表结构与导出 SQL | 查库 `sp_help 'dbo.CN_AME_SSO_PermLedger'` |
