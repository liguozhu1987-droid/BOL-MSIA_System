# MSIA 重部署操作手册（含 OIDC 改造版本）

> 适用对象：现场运维/实施人员（无需懂代码）
> 本次发布内容：统一身份认证（Keycloak OIDC）相关后端代码 + 防御性改动（大小写不敏感身份解析、配置体检）+ 对应前端页面
> 版本标识：`20261105-1600`（构建时间 2026-11-05 16:00）
> 形态：Windows 单机、PyInstaller `onedir` 打包（`msia_server.exe` + `_internal\`）

---

## 0. 本次部署包长什么样

| 项 | 值 |
|---|---|
| 部署包 | `MSIA-deploy-20261105_1602.zip`（37.20 MB，731 个条目） |
| 包内只有两样 | `msia_server.exe`、`_internal\`（整个目录） |
| **包里没有** | `config.ini`、`storage\`、`.env`（故意剔除，见第 3 节） |
| exe | `2026-11-05 16:00:12`，15,141,673 字节（14.44 MB） |
| 前端产物 | 包内 `_internal\dist\assets\index-vQ0-LQKJ.js`（2,922,117 字节）、`index-cmljLy-Y.css`（6,497 字节） |
| 启动前置 | **必须设置 `SSL_CERT_FILE`**（指向企业根 CA），否则访问 Keycloak 会报证书校验失败（见 3.4） |

**先记住一句话：只换 `msia_server.exe` 和 `_internal\`，其它一律不动。**

---

## 1. 停机与备份

### 1.1 先确认服务以什么方式运行

```powershell
# A. 是否注册成了 Windows 服务
Get-Service | Where-Object { $_.Name -like '*msia*' -or $_.DisplayName -like '*MSIA*' } |
  Select-Object Name, DisplayName, Status, StartType

# B. 是否有进程在跑（看 Path 确认是哪个目录的 exe）
Get-Process msia_server -ErrorAction SilentlyContinue |
  Select-Object Id, Path, StartTime

# C. 端口有没有在听（记录端口号，默认应为 8000）
netstat -ano | findstr LISTENING | findstr :8000
```

### 1.2 停机

```powershell
# 若为服务（把 <服务名> 换成 1.1 里查到的 Name）
Stop-Service -Name '<服务名>'
Get-Service '<服务名>'      # 确认 Status = Stopped

# 若为控制台窗口运行
Stop-Process -Name msia_server -Force
Start-Sleep -Seconds 3
Get-Process msia_server -ErrorAction SilentlyContinue   # 应无输出
```

> 必须确认进程真的退出了。`_internal\` 里的文件被占用时替换会失败或出现"半新半旧"的坏目录。

### 1.3 整目录备份（必做）

假设部署目录是 `D:\MSIA`（请按现场实际路径替换）：

```powershell
$D   = 'D:\MSIA'
$BAK = 'D:\MSIA_bak_20261105'

if (Test-Path $BAK) { $BAK = "D:\MSIA_bak_20261105_" + (Get-Date -Format 'HHmmss') }

Copy-Item -Path $D -Destination $BAK -Recurse -Force
'备份完成 -> ' + $BAK
Get-ChildItem $BAK | Select-Object Name, LastWriteTime
```

备份必须包含：`msia_server.exe`、`_internal\`、`config.ini`、`storage\`。
**`storage\` 里是业务附件与导出文件，丢了无法从代码恢复。**

---

## 2. 只替换 exe + `_internal`

```powershell
$D    = 'D:\MSIA'
$TMP  = 'D:\msia_deploy_tmp'
$BAK  = 'D:\MSIA_bak_20261105'      # 用 1.3 实际生成的路径

# 1) 解压部署包到临时目录（解压后应有 msia_server.exe 与 _internal 两项）
if (Test-Path $TMP) { Remove-Item $TMP -Recurse -Force }
Expand-Archive -Path 'D:\MSIA-deploy-20261105_1602.zip' -DestinationPath $TMP -Force
Get-ChildItem $TMP | Select-Object Name

# 2) 先删旧的 _internal，再拷新的（保持目录结构）
Remove-Item "$D\_internal" -Recurse -Force
Copy-Item "$TMP\_internal" "$D\_internal" -Recurse -Force

# 3) 换 exe
Copy-Item "$TMP\msia_server.exe" "$D\msia_server.exe" -Force

# 4) 校验：exe 时间应是 2026-11-05 16:00，且 config.ini / storage 原封不动
Get-Item "$D\msia_server.exe" | Select-Object LastWriteTime, Length
Get-Item "$D\config.ini", "$D\storage" | Select-Object Name, LastWriteTime
Get-ChildItem "$D\_internal\dist\assets" | Select-Object Name, Length
```

预期：

- `msia_server.exe` → `2026-11-05 16:00:12`，`15,141,673` 字节
- `_internal\dist\assets` → `index-cmljLy-Y.css`（6,497 字节）、`index-vQ0-LQKJ.js`（2,922,117 字节）
- `config.ini`、`storage` 的时间戳**不变**（变了你就是多拷了东西）

### 为什么绝对不能覆盖 `config.ini` 和 `storage`

| 对象 | 被覆盖的后果 |
|---|---|
| `config.ini` | 数据库连接串、邮箱、`jwt_secret_key`、`system_url` 全部变成本机开发值 → 连不上库 / 所有人被强制重新登录 / 邮件地址错 |
| `storage\` | 业务附件与导出文件被空目录替换 → 数据丢失，只能从备份恢复 |

> 部署包里已刻意剔除 `config.ini`（含 `_internal\config.ini`），避免把构建机的数据库口令带到现场。
> 若现场目录**原本就没有** `config.ini`，程序会启动失败（缺 `DATABASE_URL`）——先从 `MSIA_bak_...` 找回。

---

## 3. `config.ini` 追加 `[oidc]` 段

### 3.1 操作位置

打开 `D:\MSIA\config.ini`（**服务器上这份，不是构建机那份**），滚动到文件最末尾，另起一行空行后，把 3.2 的整段粘贴进去并保存。
注意：记事本保存时选择「UTF-8」；文件里原有内容一行都不要删改。

> 生效优先级（了解即可）：操作系统环境变量 > `config.ini` > `.env`。
> 若现场曾在系统环境变量里设过 `OIDC_*`，那份会盖住 `config.ini`，需一并核对。

### 3.2 完整模板（本次的值已填好，`enabled` 保持 `false`）

```ini
[oidc]
# ===== 统一身份认证 (Keycloak) =====
# 是否启用"统一身份登录"。本次第一次启动必须保持 false（先验证部署），
# 验证通过后再改 true 重启。false 时行为与改造前完全一致。
enabled = false

# Keycloak realm 的 issuer 地址，必须与 Keycloak 里 realm 配置完全一致（结尾不带斜杠）。
# 本环境证书按 IP 发布，issuer 用 IP 口径（与浏览器实际访问 Keycloak 的地址一致）；
# 不要再写 sso.ap.inalfa.local —— 证书里没有该域名的 SAN，会证书校验失败。
issuer = https://172.26.2.203:8443/realms/inalfa

# Keycloak 客户端 ID（Keycloak 控制台 Clients 里创建的那个）
client_id = msia-prod

# 客户端密钥：从 Keycloak 控制台 Clients > msia-prod > Credentials 复制。
# 建议不写在这里，改用 Windows 系统环境变量 OIDC_CLIENT_SECRET（避免明文落盘）。
# 若只能写字面值，填在这里并保证文件仅运维可读。
client_secret =

# 授权回调地址：必须与 Keycloak 里 msia-prod 的 Valid redirect URIs 逐字符一致
#（协议、IP、端口、大小写、结尾不能多斜杠）。
# 下面这一行是"8078 有反向代理"时用的值；若 8078 没有代理，改成 :8000（见第 6 节）
redirect_uri = http://172.26.2.203:8078/api/auth/oidc/callback

# 后端登录成功后跳转的前端页面路径（一般不用改）
front_callback = /oidc/callback

# 准入组：Keycloak 用户必须有这个组才允许进 MSIA，否则提示"未开通本系统访问权限"
required_group = app-msia

# Keycloak 里存在、但 MSIA 本地用户表没有的人，是否自动建最低权限账号(reviewee)
auto_create_user = true

# 授权范围，一般不用改
scopes = openid profile email
```

### 3.3 各键取值依据

| 键 | 本次值 | 说明 |
|---|---|---|
| `enabled` | `false` | 先验证部署是否成功，再开功能；改 `true` 后登录页才出现"统一身份登录"按钮 |
| `issuer` | `https://172.26.2.203:8443/realms/inalfa` | realm 名为 `inalfa`；证书 SAN 按 IP 签发，**必须用 IP 口径**，且与浏览器访问 Keycloak 的地址一致 |
| `client_id` | `msia-prod` | 现场已重建的 Keycloak 客户端 |
| `client_secret` | 空（推荐用环境变量） | 由 Keycloak 侧提供，本手册不写明文 |
| `redirect_uri` | 先按 `:8078` 填 | 必须与 Keycloak 里填的完全一致；端口对不对由第 6 节判定后定稿 |
| `required_group` | `app-msia` | Keycloak 组名，组名大小写敏感 |
| `auto_create_user` | `true` | 双轨期方便首次登录建号 |
| `scopes` | `openid profile email` | 需要 `email`/`name` 补全用户资料 |

### 3.4 启动必须带 `SSL_CERT_FILE`（否则连不上 Keycloak）

程序用 Python 标准库校验 Keycloak 的 HTTPS 证书，**不会**自动使用 Windows「受信任的根证书颁发机构」。
必须通过环境变量 `SSL_CERT_FILE` 指向一个包含企业根 CA 的 PEM 文件：

```powershell
# 1) 确认证书文件存在（PEM 格式，内容是根 CA 证书链）
Get-Item 'D:\MSIA\certs\inalfa-root-ca.pem' | Select-Object FullName, Length

# 2) 临时生效（只对当前窗口启动的进程有效，适合先验证）
$env:SSL_CERT_FILE = 'D:\MSIA\certs\inalfa-root-ca.pem'

# 3) 永久生效（系统级，需管理员 PowerShell；设置后要重开窗口/重注册服务）
[Environment]::SetEnvironmentVariable('SSL_CERT_FILE', 'D:\MSIA\certs\inalfa-root-ca.pem', 'Machine')
```

注意：

- `SSL_CERT_FILE` 是**替换**默认根证书集合，不是追加。所以这个 PEM 里必须真的有企业根 CA。
- 若程序以 Windows 服务方式运行，`[Environment]::SetEnvironmentVariable(..., 'Machine')` 后需重启服务
  （或确认 NSSM/服务配置里已带该环境变量）。
- 判断是否生效：日志里不再出现 `OIDC HTTPS 证书校验失败`；若仍失败，先核对证书 SAN 是否含
  `IP:172.26.2.203`，再核对 `issuer` 是否也用了同一个 IP。

---

## 4. 启动

```powershell
# 方式 A：注册成了服务
Start-Service -Name '<服务名>'
Get-Service '<服务名>' | Select-Object Name, Status

# 方式 B：控制台运行（建议先用这种方式看日志，确认没问题再转服务）
cd D:\MSIA
$env:SSL_CERT_FILE = 'D:\MSIA\certs\inalfa-root-ca.pem'   # 必加, 见 3.4
.\msia_server.exe
```

启动后窗口里应看到类似（端口以 `config.ini [server] port` 为准，现网配置是 8000）：

```
  MSIA Audit Management System
  Listen:  http://0.0.0.0:8000
  DB:      ...
  Storage: ...
应用就绪, 监听 0.0.0.0:8000
```

若窗口一闪而过或报错，先看是不是 `config.ini` 缺内容 / 数据库连不上；把窗口里的报错原文留存。

---

## 5. 四条验证（按顺序做，前三条是硬门槛）

在服务器本机新开一个 PowerShell 窗口执行。**端口请按实际改**（下面示例用 8000）。

### 5.1 路由已进入程序（最关键）

```powershell
$j = Invoke-RestMethod http://127.0.0.1:8000/openapi.json
$j.paths.Keys | Where-Object { $_ -like '*oidc*' }
```

预期输出两行，必须一字不差：

```
/api/auth/oidc/login
/api/auth/oidc/callback
```

只有这两条都在，才说明新版本真的生效了。若输出为空 → 换的不是新 exe（回到第 2 节核对 exe 时间戳）。

### 5.2 回调地址存在（应为 400，不能是 404）

```powershell
try {
  Invoke-WebRequest 'http://127.0.0.1:8000/api/auth/oidc/callback' -UseBasicParsing
} catch {
  $_.Exception.Response.StatusCode.value__
  $_.ErrorDetails.Message
}
```

预期（注意分两种状态，2026-11-05 这一版新增了关闭态守卫）：

`enabled=false`（本次第一次部署就是这个状态）：

```
503
{"detail":"统一登录未启用"}
```

`enabled=true`（开启后再验）：

```
400
{"detail":"登录状态无效，请重试"}
```

- 得到 **503 + "统一登录未启用"** 且当前 `enabled=false` → 正确：路由在，关闭态直接拒绝（新版本行为）。
- 得到 **400 + "登录状态无效"** 且当前 `enabled=true` → 正确：路由在，只是没带 `state` 参数（Keycloak 回调时会带）。
- 得到 **404 + {"detail":"Not Found"}** → 仍是旧版本或打到了别的服务，**不要继续**。

### 5.3 配置加载正确

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/auth/config
```

预期（`enabled=false` 阶段）：

```
oidc_enabled        local_login_enabled
------------        -------------------
False               True
```

说明：`oidc_enabled=False` 是预期的（还没开开关）；`local_login_enabled=True` 表示本地账密登录仍然可用（双轨期）。
若把 `enabled` 改成 `true` 并重启，这里应变 `True`。

### 5.4 前端是新构建

```powershell
(Invoke-WebRequest 'http://127.0.0.1:8000/' -UseBasicParsing).Content | Select-String 'index-vQ0-LQKJ.js'
```

预期：能匹配到 `index-vQ0-LQKJ.js`。
若匹配不到（出现别的 hash，如 `index-DYZK23Sn.js`）→ 前端还是旧的，说明 `_internal` 没换成功。

---

## 6. 8078 是不是反向代理，怎么判、怎么处理

### 6.1 判断

```powershell
# 1) 8078 上有没有程序在监听（False = 没人监听，8078 不可用）
Test-NetConnection 172.26.2.203 -Port 8078 -InformationLevel Quiet

# 2) 看是哪个进程占用 8078（有 PID 就说明有 IIS/ARR 之类在前面）
netstat -ano | findstr LISTENING | findstr :8078

# 3) 通过 8078 打一个"不需要登录"的接口
try { Invoke-RestMethod 'http://172.26.2.203:8078/api/auth/config' } catch { $_.Exception.Message }
```

判读：

| 现象 | 结论 |
|---|---|
| 8078 无人监听 | 8078 不可用，见 6.2 处理 A |
| 8078 能返回 `{"oidc_enabled":...,"local_login_enabled":...}` | 反代正常且保留了 `/api` 前缀 → 处理 B |
| 8078 返回 404 / 502 / 静态页面 | 反代存在但路径被改写、或指向了错误站点 → 处理 B 的排查 |

### 6.2 两种处理

**处理 A：8078 没有反向代理（后端只监听 8000）**

1. `config.ini`：`redirect_uri = http://172.26.2.203:8000/api/auth/oidc/callback`
2. Keycloak 控制台 → Clients → `msia-prod` → Valid redirect URIs 改成上面同一串
3. 用户访问地址也相应改为 `http://172.26.2.203:8000/login`
4. 重启 MSIA

**处理 B：8078 有反向代理**

1. `redirect_uri` 保持 `http://172.26.2.203:8078/api/auth/oidc/callback`（与 Keycloak 完全一致）
2. 让网络/运维核对反代规则：**必须保留 `/api` 前缀原样转发**，且目标指向 MSIA 后端端口
3. 用 6.1 的第 3 条命令复测，直到 8078 也能正常返回 `/api/auth/config` 的 JSON
4. 之后浏览器全程只走 8078

> 端口不要"两边都试"。`redirect_uri` 与 Keycloak 的 Valid redirect URIs 必须**完全一致**，差一个端口就会在授权阶段报错。

---

## 7. 回滚

### 7.1 软回滚（最快，保留新程序）

适用：新版本本身正常，但不想现在开统一登录。

1. `config.ini` 里 `enabled = false`（或删掉 `[oidc]` 段）
2. 重启服务
3. 复查 5.3：`oidc_enabled=False`，登录页不显示"统一身份登录"按钮，行为回到改造前

### 7.2 硬回滚（还原旧版本）

适用：新程序起不来 / 报错无法放行。

```powershell
$D   = 'D:\MSIA'
$BAK = 'D:\MSIA_bak_20261105'      # 1.3 生成的备份

Stop-Service -Name '<服务名>'        # 或 Stop-Process -Name msia_server -Force
Start-Sleep -Seconds 3

Remove-Item "$D\_internal" -Recurse -Force
Copy-Item "$BAK\_internal" "$D\_internal" -Recurse -Force
Copy-Item "$BAK\msia_server.exe" "$D\msia_server.exe" -Force
Copy-Item "$BAK\config.ini" "$D\config.ini" -Force

Start-Service -Name '<服务名>'
```

还原后复查 5.1：预期**查不到** `/api/auth/oidc/*`（旧版本本来就没有），且 5.3 返回 `local_login_enabled=True`、原业务功能正常。

---

## 8. 已知现象与注意点

1. **重启会让"正在登录中"的用户失败。**
   登录过程中的 `state`/`nonce`/PKCE 与一次性码都存在进程内存里（单进程、`workers=1`）。
   重启后这些临时数据清空，回跳的用户会看到「登录状态无效，请重试」——**让用户重新点一次"统一身份登录"即可**，不是故障。
   建议在低峰期做重启。

2. **旧登录态（JWT）不受影响**，有效期 30 天。前提是 `jwt_secret_key` 没被改动；若从备份还原了 `config.ini`，secret 与旧值一致，用户无需重登。

3. **杀毒软件可能拦截新 exe**。打包已禁用 UPX 压缩并写入版本信息以降低误报；首次启动前把 `D:\MSIA` 加入杀软白名单更稳。

4. **前端缓存**：`index.html` 每次回源校验、`assets` 带 hash 长缓存，正常刷新即可；若用户仍看到旧页面，Ctrl+F5 强刷。

5. **Keycloak 侧三项必须与本地一致**：`client_id`、`client_secret`、Valid redirect URIs（含端口）。
   密钥不建议写进 `config.ini`，优先用系统环境变量 `OIDC_CLIENT_SECRET`（设置后需重启服务生效）。

6. **`enabled=true` 后若配置不完整，登录端点直接 503（这是有意的）。**
   新版本增加配置体检：`client_secret` 为空、`redirect_uri` 仍含 `127.0.0.1`/`localhost`、
   `issuer` 与 `redirect_uri` 主机名不一致、`issuer` 非 `https` 时，
   `GET /api/auth/oidc/login` 返回 `503` + `OIDC 配置不完整: ...`（同时日志有 ERROR 明细）。
   按提示改 `config.ini`/环境变量后重启即可，不要把它当成程序故障。

7. **`issuer` 与 `redirect_uri` 的主机名必须一致**（都写 IP 或都写域名）。
   本环境用 IP 口径：`issuer=https://172.26.2.203:8443/...`、`redirect_uri=http://172.26.2.203:8078/...`。
   混用会直接触发上面的 503 体检（主机名不一致）。

8. **首次开启（`enabled=true`）后再验一轮**：
   5.3 应返回 `oidc_enabled=True` → 浏览器走完整流程：登录页出现"统一身份登录" → Keycloak 认证 → 回到 MSIA 并进入系统。
   若停在 Keycloak 报 `invalid_redirect_uri`，回到第 6 节核对端口与前缀。

---

## 9. 本次未做的事（避免误解）

- 本手册只覆盖"把新程序换上去"。**服务器上的所有操作由现场人员执行**，构建机未连接生产环境。
- 未开启 OIDC（`enabled` 仍为 `false`），未改动 Keycloak、未灌用户、未改数据库。
- 本次发布**不含数据库结构变更**：无迁移脚本、无新表新列；`CN_AME_SSO_*` 五表若尚未建立，属于既有前置条件，不随本次部署创建。
