# R2 回滚清单（方案 C：退回 IP 访问）

> 适用：`keycloak-domain-cutover-step-by-step.md` 第 4 章 R2 的展开版，可直接照着敲。
> 目标态：`https://172.26.2.203:8443`（Keycloak，旧自签证书）+ 三个应用 `http://172.26.2.203:8078 / :8090 / :8000`。
> 全程需要管理员 PowerShell。每步都是「执行 → 判据 → 失败看什么 → 单独回退」。

## 关键设计说明（先读这一条）

**主路径是从 `$bk` 备份整文件覆盖，不是手工编辑。** `Copy-Item` 是字节级复制，不经过任何编码转换；手工改 `keycloak.conf` / `.env` 才是上次 PS 5.1 编码损坏（UTF-8 BOM 写进 `.env` 首行、键名被污染）的来源。只有在备份缺失时，才走各步里标注的「手工路径」。

## 前置结论：旧 PEM 在 = 完整回滚 / 不在 = 降级回滚

R2 的证书部分依赖 `C:\keycloak\conf\server.crt.pem` 与 `server.key.pem` 两个旧文件。**这一项决定走哪条分支，必须在动手前确认**（命令见第 0 步 0.2）。

| 分支 | 条件 | 证书处理 | 三处 `SSL_CERT_FILE` | 浏览器表现 | 业务影响 |
|---|---|---|---|---|---|
| **完整回滚** | 两个 PEM 文件都在 | `hostname` 回 IP；PEM 双文件生效；keystore 三行注释 | 改回 `C:\keycloak\conf\server.crt.pem` | 自签证书告警（点「继续访问」） | 无 |
| **降级回滚** | PEM 已不在（缺失/被删） | **只改 `hostname=172.26.2.203`**；keystore 三行保持不动，继续用 `C:\certs\iame.p12` | **保持 `C:\certs\ca-bundle.pem` 不动**（跳过第 3 步） | 证书名称与地址不匹配告警（证书 SAN 里没有 IP），同样点「继续访问」 | 无，但告警文案不同，需在回滚记录里写明，避免被当成新故障 |

**降级回滚不要试图现场生成 PEM**：本机没有 openssl，Keycloak 要求未加密的 PKCS#8 私钥，从 p12 导不出来。

---

## 第 0 步：阻断预检（只读，必须先跑）

```powershell
# 0.1 备份目录是否完整（把时间戳换成 S1 记下的真实目录）
$bk = 'C:\Services\rollback\baseline-<时间戳>'
Get-ChildItem $bk | Select-Object Name, Length, LastWriteTime

# 0.2 旧 PEM 是否还在磁盘上（R2 的关键依赖，决定完整/降级分支）
Get-ChildItem 'C:\keycloak\conf\server.crt.pem','C:\keycloak\conf\server.key.pem' -ErrorAction SilentlyContinue |
    Select-Object FullName, Length, LastWriteTime

# 0.3 当前 keycloak.conf 的实际状态（确认要改的就是这几行）
Select-String -Path C:\keycloak\conf\keycloak.conf -Pattern '^hostname|^#?\s*https-(key-store|certificate)' |
    Select-Object LineNumber, Line

# 0.4 三份应用配置的现值（确认现在是域名口径）
Get-Content C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini | Select-String '^\s*(issuer|client_id|redirect_uri|front_callback)\s*='
Get-Content C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini  | Select-String '^\s*(issuer|client_id|redirect_uri|front_callback)\s*='
Get-Content 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' | Select-String '^\s*OIDC_'

# 0.5 当前 SSL_CERT_FILE 指向
foreach($s in 'MSIA-Server','BOL-Server','CapacityAPI'){
    "$s : " + (((Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$s\Parameters" -Name AppEnvironmentExtra).AppEnvironmentExtra) -join ' | ')
}
```

### 判据与阻断关系

| 检查项 | 通过 | 不通过怎么办 |
|---|---|---|
| `$bk` 里有 `keycloak.conf`、`server.crt.pem`、`server.key.pem`、`msia-config.ini`、`bol-db_config.ini`、`capacity-env.txt`、三个 `*.reg` | 全部非空 | 缺哪个就改走「手工编辑」分支（第 1、2 步的 B 方案） |
| 旧 PEM 两个文件都在（约 1103 / 1704 字节） | **在** | **改走「降级回滚」**（见开头的分支表），仍可完成回滚，只是浏览器告警类型不同 |
| 当前配置是域名口径 | 命中 | 若本来就是 IP，说明切换没落地，R2 只需处理证书与 env |

---

## 第 1 步：Keycloak 配置回退（`hostname` + 证书）

### 1A 主路径：整文件覆盖（推荐）

```powershell
Copy-Item "$bk\keycloak.conf" 'C:\keycloak\conf\keycloak.conf' -Force
Select-String -Path C:\keycloak\conf\keycloak.conf -Pattern '^hostname|^https-key-store|^#?\s*https-certificate' |
    Select-Object LineNumber, Line
```

**应看到**（与切换前一致）：

| 行 | 内容 |
|---|---|
| 40 | `hostname=172.26.2.203` |
| 63 | `https-certificate-file=C:/keycloak/conf/server.crt.pem`（**不带** `#`） |
| 64 | `https-certificate-key-file=C:/keycloak/conf/server.key.pem`（**不带** `#`） |
| — | **没有**生效的 `https-key-store-*` 三行 |

**失败时看什么**：行号对不上 → 说明 `$bk\keycloak.conf` 不是切换前那份，改用 1B。

**这一步单独回退**：执行前先留一份当前文件，撤回时覆盖回去再重启 Keycloak。

```powershell
Copy-Item C:\keycloak\conf\keycloak.conf "C:\Services\rollback\keycloak.conf.before-r2" -Force
# 撤回：
# Copy-Item "C:\Services\rollback\keycloak.conf.before-r2" C:\keycloak\conf\keycloak.conf -Force
```

### 1B 手工路径（备份不可用时）

只改这四处，其余不动：

| 项 | 改成 |
|---|---|
| `hostname` | `hostname=172.26.2.203` |
| 原第 63 行（`https-key-store-file=C:/certs/iame.p12`） | 行首加 `#` 注释掉 |
| 原第 64 行（`https-key-store-password=...`） | 行首加 `#` 注释掉 |
| 原第 65 行（`https-key-store-type=PKCS12`） | 行首加 `#` 注释掉 |
| 被注释的 `https-certificate-file` / `https-certificate-key-file` | **去掉行首 `#` 和其后空格**，恢复为 `https-certificate-file=C:/keycloak/conf/server.crt.pem`、`https-certificate-key-file=C:/keycloak/conf/server.key.pem` |

> 必须成对切换：Quarkus 同时配置 `https-key-store-*` 与 `https-certificate-*` 会启动失败（互斥）。这是本步最容易被忽略的失败点。

**旧 PEM 的准确路径与口令来源**：路径就是 `C:\keycloak\conf\server.crt.pem` / `server.key.pem`；**这两行没有口令参数**——PEM 私钥必须是未加密的 PKCS#8，切换前能启动就说明它本来就是无口令的，回退时不要再加 `https-certificate-key-password`。

### 1C 降级回滚（旧 PEM 不在时）

只把 `hostname` 改回 `172.26.2.203`，证书相关行全部不动：

- `https-key-store-file` / `-password` / `-type` 三行**保持生效**（继续用 `C:\certs\iame.p12`）；
- 被注释的 `https-certificate-*` 两行**保持注释**；
- 第 3 步（`SSL_CERT_FILE`）整步跳过，保持 `C:\certs\ca-bundle.pem`。

---

## 第 2 步：三份应用配置回 IP（字节级）

### 2A 主路径：从备份恢复

```powershell
# 先各留一份当前值，便于单步撤回
Copy-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini'  'C:\Services\rollback\msia-config.before-r2'   -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini'   'C:\Services\rollback\bol-db.before-r2'        -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env'               'C:\Services\rollback\capacity-env.before-r2'  -Force

# 再覆盖（Copy-Item 是字节级，不经过编码转换）
Copy-Item "$bk\msia-config.ini"  'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' -Force
Copy-Item "$bk\bol-db_config.ini" 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' -Force
Copy-Item "$bk\capacity-env.txt" 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Force
```

核对：

```powershell
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' -Pattern '^\s*(issuer|client_id|redirect_uri|front_callback)\s*=' | Select-Object LineNumber, Line
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini'  -Pattern '^\s*(issuer|client_id|redirect_uri|front_callback)\s*=' | Select-Object LineNumber, Line
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*OIDC_' | Select-Object LineNumber, Line
```

**应看到**：

| 应用 | 键 | 值 |
|---|---|---|
| MSIA `[oidc]` | `issuer` | `https://172.26.2.203:8443/realms/inalfa` |
| | `client_id` | `msia-prod` |
| | `redirect_uri` | `http://172.26.2.203:8078/api/auth/oidc/callback`（**无尾斜杠**） |
| | `front_callback` | `/oidc/callback` |
| BOL `[oidc]` | `issuer` | `https://172.26.2.203:8443/realms/inalfa` |
| | `client_id` | `bol-prod` |
| | `redirect_uri`（第 107 行） | `http://172.26.2.203:8090/api/auth/oidc/callback`（**无尾斜杠**） |
| | `front_callback`（第 110 行） | `/oidc/callback/`（**有尾斜杠**） |
| Capacity `.env` | `OIDC_ISSUER` | `https://172.26.2.203:8443/realms/inalfa` |
| | `OIDC_REDIRECT_URI` | `http://172.26.2.203:8000/api/v1/auth/oidc/callback` |
| | `OIDC_FRONTEND_URL` | `http://172.26.2.203:8000` |
| | `OIDC_POST_LOGOUT_REDIRECT_URI` | `http://172.26.2.203:8000/login` |
| | `OIDC_CLIENT_ID` | `ics-prod`（**不变**） |

**失败时看什么**：出现 `iame.ap.inalfa.local` 残留 → `$bk` 里那份是切换后误存的，改走 2B；出现 `\ufeff` 或首行键名变成 `锘縊DC_ISSUER` → 编码损坏，改走 2C。

### 2B 手工替换（保留字节编码的安全写法）

```powershell
function Repair-Text {
    param([string]$Path, [hashtable]$Map)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $text  = (New-Object System.Text.UTF8Encoding($false)).GetString($bytes)
    if ($hasBom) { $text = $text.TrimStart([char]0xFEFF) }
    foreach ($k in $Map.Keys) { $text = $text.Replace($k, $Map[$k]) }
    $enc = if ($hasBom) { New-Object System.Text.UTF8Encoding($true) } else { New-Object System.Text.UTF8Encoding($false) }
    [System.IO.File]::WriteAllText($Path, $text, $enc)
}
```

只做 `172.26.2.203` ↔ `iame.ap.inalfa.local` 的整串替换即可（两份 ini 各一次，`.env` 一次），不要用 `Set-Content`：PS 5.1 的 `Set-Content -Encoding UTF8` 会**加 BOM**，`.env` 首行键名会被污染，这就是上次那类损坏的成因。

### 2C 编码已损坏的修法

确认：`Format-Hex -Path '...\publish\.env' | Select-Object -First 1`，前 3 字节是 `EF BB BF` 就是 BOM 问题。用 2B 的 `Repair-Text`（`$hasBom` 分支）把 BOM 去掉即可，键值不需要重敲。

---

## 第 3 步：三处 `SSL_CERT_FILE` 指回旧自签

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action SetEnv -App MSIA     -CertFile 'C:\keycloak\conf\server.crt.pem' -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App BOL      -CertFile 'C:\keycloak\conf\server.crt.pem' -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App Capacity -CertFile 'C:\keycloak\conf\server.crt.pem' -SecretMode Keep
```

说明：`SetEnv` 是**合并语义**，只改 `SSL_CERT_FILE`，不动 `KC_DB_PASSWORD` 等其它键；`-SecretMode Keep` 保证不会因为缺占位而提示重输口令。**不要用 `-App All`**——那会把 Keycloak 的服务环境也一起过一遍，没有必要。

验证（写后从注册表回读）：

```powershell
foreach($s in 'MSIA-Server','BOL-Server','CapacityAPI'){
    $lines = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$s\Parameters" -Name AppEnvironmentExtra).AppEnvironmentExtra
    "$s -> " + (($lines | Where-Object { $_ -match '^\s*SSL_CERT_FILE\s*=' }) -join '')
    "   exists: " + (Test-Path -LiteralPath ((($lines | Where-Object { $_ -match '^\s*SSL_CERT_FILE\s*=' })[0] -split '=',2)[1]).Trim())
}
```

**判据**：三行都等于 `SSL_CERT_FILE=C:\keycloak\conf\server.crt.pem`，且 `exists: True`。

**失败时看什么**：`exists: False` → 旧 PEM 不在（回到第 0.2 的阻断分支）；脚本报「不是管理员 PowerShell」→ 用管理员窗口重跑；脚本版本不一致 → 先核对打印的 SHA256 前 8 位。

**单步回退**：改回 `-CertFile 'C:\certs\ca-bundle.pem'` 再跑同样三条命令即可（该命令只改这一个键，天然可逆）。

> 若第 1 步走了「降级回滚」（保留 keystore），则**本步跳过**，`SSL_CERT_FILE` 保持 `C:\certs\ca-bundle.pem` 不动。

---

## 第 4 步：重启顺序与等待判据

顺序固定：**Keycloak → MSIA → BOL → Capacity**（应用重启后要能立刻拉到 discovery）。

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Start -App Keycloak

# 等到 8443 / 9000 都在监听，最多等 120 秒
$deadline = (Get-Date).AddSeconds(120)
do {
    Start-Sleep -Seconds 3
    $l = @(Get-NetTCPConnection -LocalPort 8443,9000 -State Listen -ErrorAction SilentlyContinue)
    "$(Get-Date -Format HH:mm:ss)  listening=$($l.Count)"
} while ($l.Count -lt 2 -and (Get-Date) -lt $deadline)
```

**判据**：

```powershell
# 1) 端口就绪
Get-NetTCPConnection -LocalPort 8443,9000 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess

# 2) 用 IP 取 discovery（此时 hostname=172.26.2.203，Host 头匹配，不会 403）
curl.exe -k -s -o NUL -w "discovery=%{http_code}`n" "https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration"

# 3) 管理端口健康
(Invoke-WebRequest 'http://127.0.0.1:9000/health/ready' -UseBasicParsing).StatusCode
```

应看到：8443 与 9000 各有 LISTENING；`discovery=200`；health 返回 `200`。

**失败时看什么**：

| 现象 | 先看什么 |
|---|---|
| 8443 不监听、进程退出 | `C:\Services\logs\Keycloak-stderr.log` 尾部 50 行；最常见是「同时配了 key-store 和 certificate」，回第 1 步检查互斥 |
| 8443 监听但 `discovery` 403 | Host 头不匹配：确认 `hostname` 已是 `172.26.2.203`，且请求用的是 IP 而不是 `iame.ap.inalfa.local` |
| `discovery` 5xx | 数据库连接（`KC_DB_PASSWORD` 是否被误改）、`keycloak.log` 里的 SQL 报错 |

Keycloak 正常后启动三个应用：

```powershell
.\register-services-nssm.ps1 -Action Start -App MSIA
.\register-services-nssm.ps1 -Action Start -App BOL
.\register-services-nssm.ps1 -Action Start -App Capacity
.\register-services-nssm.ps1 -Action Status -App All
```

`-Action Start` 只等服务 Running + 端口 LISTENING，不做接口探针，所以不会因为 OIDC 还没通而误报。

**单步回退**：`-Action Stop -App All` 后把第 1、2 步的 `.before-r2` 备份覆盖回去，再 `Start`。

---

## 第 5 步：Keycloak 三个 client 的旧 IP URI 核对

进 `https://172.26.2.203:8443/admin`（证书告警点「继续」）→ realm `inalfa` → `Clients`。

| client | Tab / 字段 | 必须存在的旧值 |
|---|---|---|
| `msia-prod` | Settings → Valid redirect URIs | `http://172.26.2.203:8078/api/auth/oidc/callback` |
| | Web origins | `http://172.26.2.203:8078` |
| `bol-prod` | Valid redirect URIs | `http://172.26.2.203:8090/api/auth/oidc/callback` |
| | Web origins | `http://172.26.2.203:8090` |
| `ics-prod` | Valid redirect URIs | `http://172.26.2.203:8000/api/v1/auth/oidc/callback` |
| | **Valid post logout redirect URIs** | `http://172.26.2.203:8000/login` |
| | Web origins | `http://172.26.2.203:8000` |

**判据**：上表六项逐个在列表里能看到；`ics-prod` 的两组分别在不同栏，别只看到 redirect 就算过。

**缺失时补回**：在对应字段点 `+` 粘上表值 → `Save`。注意 `ics-prod` 的 post logout 组是「能登录、点退出报 `Invalid redirect uri`」的唯一原因。

**失败时看什么**：保存后列表里出现 `*` → 有未保存的空白行，删掉空行再存。

**单步回退**：刚加的这几条就是「另一条路」的值，若之后要重回域名，删掉它们即可（改 client 不改应用，随时可逆）。

---

## 第 6 步：端到端验证（四条链路）

| # | 链路 | 操作 | 通过标准 |
|---|---|---|---|
| 1 | Keycloak | `https://172.26.2.203:8443/admin` | **证书告警属预期**，点继续后能进管理台并看到 realm `inalfa` |
| 2 | MSIA | `http://172.26.2.203:8078` → 统一登录 | 跳到 `https://172.26.2.203:8443/realms/inalfa/...`，登录后回到 8078 业务页，页面显示用户 |
| 3 | BOL | `http://172.26.2.203:8090` → 统一登录 | 同上，回到 8090 业务页 |
| 4 | Capacity | `http://172.26.2.203:8000` → 统一登录 → **点退出** | 回到 `http://172.26.2.203:8000/login`，不出现 `Invalid redirect uri` |

补充判据：

```powershell
Get-Content C:\Services\logs\MSIA-Server-stderr.log   -Tail 30 | Select-String 'OIDC|SSL|CERTIFICATE'
Get-Content C:\Services\logs\BOL-Server-stderr.log    -Tail 30 | Select-String 'OIDC|SSL|CERTIFICATE'
Get-Content C:\Services\logs\CapacityAPI-stderr.log   -Tail 30 | Select-String 'OIDC|SSL|CERTIFICATE'
```

应为空（或只有正常的 OIDC 初始化日志），**不应再出现** `CERTIFICATE_VERIFY_FAILED` 或 `idp_unreachable`。

**回滚本身预期会出现、不算故障的现象**：

- `https://172.26.2.203:8443` 证书告警（自签 + CN 不含 IP）→ 接受即可；
- 浏览器仍记得 `iame.ap.inalfa.local` 的 HSTS，`http://iame.ap.inalfa.local:8078` 依旧打不开 → **属预期**，回滚后一律用 IP，不要再用域名验证；
- Keycloak 日志里仍可能出现旧的域名痕迹（历史日志），不影响判据。

---

## 第 7 步：回滚完成后的现场快照清单

| 项 | 应处于的状态 | 快速核对 |
|---|---|---|
| 四个服务 | `Keycloak` / `MSIA-Server` / `BOL-Server` / `CapacityAPI` 全部 Running、Automatic | `.\register-services-nssm.ps1 -Action Status -App All` |
| 监听端口 | 8443、9000、8078、8090、8000 都在 LISTENING | `Get-NetTCPConnection -LocalPort 8443,9000,8078,8090,8000 -State Listen` |
| Keycloak hostname | `hostname=172.26.2.203` | `Select-String keycloak.conf -Pattern '^hostname'` |
| Keycloak 证书类型 | 完整回滚：PEM 双文件生效（`https-certificate-file` / `-key-file` 未注释），`https-key-store-*` 全部注释；降级回滚：keystore 三行生效、`https-certificate-*` 保持注释 | 同上，`^#?\s*https-` |
| MSIA 配置 | `issuer` 为 IP、`redirect_uri` 为 `http://172.26.2.203:8078/api/auth/oidc/callback`、`front_callback=/oidc/callback` | 第 2 步核对命令 |
| BOL 配置 | `redirect_uri`（107 行）为 IP 版、`front_callback`（110 行）为 `/oidc/callback/` | 同上 |
| Capacity `.env` | 四个 `OIDC_*` 全为 IP，`OIDC_CLIENT_ID=ics-prod` | 同上 |
| 三处 `SSL_CERT_FILE` | 完整回滚：都指向 `C:\keycloak\conf\server.crt.pem` 且文件存在；降级回滚：都指向 `C:\certs\ca-bundle.pem` | 第 3 步验证命令 |
| Keycloak client | 三个 client 的 IP 版 redirect（+`ics-prod` 的 post logout）都在 | 第 5 步清单 |
| 浏览器入口 | 三条业务链接全部换回 `http://172.26.2.203:<端口>` | 第 6 步 |

---

## 附录：必须到服务器上现查的项（离线无法确认）

以下都要在服务器上执行，全部只读。

```powershell
# A. 旧 PEM 是否还在（R2 唯一阻断项，决定完整/降级分支）
Get-ChildItem 'C:\keycloak\conf\server.crt.pem','C:\keycloak\conf\server.key.pem' -ErrorAction SilentlyContinue |
    Select-Object Name, Length, LastWriteTime

# B. 备份目录内容是否齐全
Get-ChildItem 'C:\Services\rollback\baseline-<时间戳>' | Select-Object Name, Length

# C. keycloak.conf 的当前行号（确认 40/63/64 是否仍是这些行）
Select-String -Path C:\keycloak\conf\keycloak.conf -Pattern '^hostname|^https-key-store|^#?\s*https-certificate'

# D. 三份配置的现值与编码
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*OIDC_' | Select-Object LineNumber, Line
Format-Hex -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' | Select-Object -First 1

# E. 三处 SSL_CERT_FILE 现值
foreach($s in 'MSIA-Server','BOL-Server','CapacityAPI'){
    "$s : " + (((Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$s\Parameters" -Name AppEnvironmentExtra).AppEnvironmentExtra) -join ' | ')
}

# F. 服务与端口现状
Get-Service Keycloak, MSIA-Server, BOL-Server, CapacityAPI | Select-Object Name, Status, StartType
Get-NetTCPConnection -LocalPort 8443,9000,8078,8090,8000 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess

# G. Keycloak client 的 URI 现状（管理台里看，或只读导一份 realm）
#    管理台路径：Clients -> <client> -> Settings -> Valid redirect URIs / Valid post logout redirect URIs / Web origins
```

**回滚前只需要盯一件事**：A 里的两个 PEM 文件在不在。在 → 走完整 R2（第 1A 步）；不在 → 走第 1C 步的降级回滚（只改 `hostname`，证书与 `SSL_CERT_FILE` 全不动），同样能恢复业务，只是浏览器告警文案不同。
