# Keycloak 一次性切域名 + 正式证书 · 照做手册（NSSM 服务版）

> 一个窗口内完成：Keycloak 换正式证书并切 `iame.ap.inalfa.local`、三个应用（MSIA / BOL / Capacity）同步改配置、端到端验证。
> 全部走 Windows 服务：启停用 `register-services-nssm.ps1` 或 `Restart-Service`，**不再手工跑 `kc.bat start` / `java -jar`**。
> 本版已作废旧口径：PEM 双文件（`https-certificate-file` / `-key-file`）、控制台启动、单系统切换。
> 不涉及：应用代码改动、新建 realm/client、IIS ARR。

## 现场常量（所有地方照抄，不改大小写）

| 项 | 值 |
|---|---|
| 域名 / issuer | `iame.ap.inalfa.local` ／ `https://iame.ap.inalfa.local:8443/realms/inalfa`（realm `inalfa`） |
| Keycloak | 服务名 `Keycloak`，`C:\keycloak`，JDK `C:\Program Files\Java\jdk-21.0.10`，管理口 `http://127.0.0.1:9000` |
| keystore | `C:\certs\iame.p12`（PKCS12，口令 `IRSCNKettle01`，1 条 `PrivateKeyEntry`） |
| 应用信任包 | `C:\certs\ca-bundle.pem`（中间 CA + 根 CA，**共 2 块**，不含叶子） |
| MSIA | 服务 `MSIA-Server`，`http://iame.ap.inalfa.local:8078`，回调 `…/api/auth/oidc/callback`（**无尾斜杠**） |
| MSIA 配置 | `C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini` → `[oidc]` |
| BOL | 服务 `BOL-Server`，`http://iame.ap.inalfa.local:8090`，回调 `…/api/auth/oidc/callback`（**无尾斜杠**） |
| BOL 配置 | `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini` → `[oidc]`（第 107 行 `redirect_uri`、第 110 行 `front_callback`） |
| Capacity | 服务 `CapacityAPI`，`http://iame.ap.inalfa.local:8000`，client `ics-prod`，退出回 `/login` |
| Capacity 配置 | `C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env`（隐藏文件，列表/读取都要 `-Force`；**不是 ini，也不在 `_internal` 里**），键 `OIDC_ISSUER` / `OIDC_REDIRECT_URI` / `OIDC_FRONTEND_URL` / `OIDC_POST_LOGOUT_REDIRECT_URI` |
| 信任包注入 | `MSIA-Server` / `BOL-Server` / `CapacityAPI` 三个服务的 `SSL_CERT_FILE` = `C:\certs\ca-bundle.pem` |
| 运维脚本 | `C:\Services\register-services-nssm.ps1` |
| 日志 | `C:\Services\logs\<服务名>-stdout.log`、`-stderr.log` |

证书链（`iame.p12` 内 3 张，S1 备份前先按 0.4 复核）：

| # | 主体 | 签发者 | 有效期 |
|---|---|---|---|
| 1 | `CN=iame.ap.inalfa.local`（SAN：`iame` / `msia` / `blo` / `eMotion`） | `CN=ap-SRV-APSH-PKI-01-CA-1` | 2026-11-09 → 2028-07-31 |
| 2 | `CN=ap-SRV-APSH-PKI-01-CA-1` | `CN=INALFA-IRSPKIROOT01-CA` | 2023-08-02 → 2028-07-31 |
| 3 | `CN=INALFA-IRSPKIROOT01-CA`（自签） | 自身 | 2015-10-12 → 2030-10-12 |

---

# 0. 开工前（只读，全 PASS 才动手）

## 0.1 客户端 DNS 硬门槛（服务器能解析 ≠ 客户端能解析）

在**两台不同网段的客户端电脑**上各跑一次（不是 Keycloak 服务器）：

```powershell
Resolve-DnsName iame.ap.inalfa.local -Type A | Format-Table Name, Type, IPAddress -AutoSize
```

应看到（`Name` 带尾点属正常）：

```text
Name                  Type IPAddress
----                  ---- ---------
iame.ap.inalfa.local. A    172.26.2.203
```

怎么判定：

- `Type = A`、`IPAddress = 172.26.2.203`、**只有这一条** → PASS。
- 返回 `CNAME` → 去掉 `-Type A` 再跑一次 `Resolve-DnsName iame.ap.inalfa.local`，看 CNAME 指向谁、那条是否解析到 `172.26.2.203`；能追到同一 IP 也算 PASS。
- 解析到别的 IP 或解析不到 → **停**。先 `ipconfig /flushdns` 重试；仍是错的，找 DNS 管理员，别在 hosts 里临时加行（那只能骗过这一台机器）。
- 怀疑被本机 hosts 覆盖：`Select-String -Path C:\Windows\System32\drivers\etc\hosts -Pattern 'iame'`，有结果就删掉再验。

**两台都 PASS 才开工。** 一台通过、另一台不通过 = 不通过。

## 0.2 客户端四端口可达

在 0.1 通过的客户端执行：

```powershell
Test-NetConnection iame.ap.inalfa.local -Port 8443 | Select-Object ComputerName, TcpTestSucceeded
Test-NetConnection iame.ap.inalfa.local -Port 8078 | Select-Object ComputerName, TcpTestSucceeded
Test-NetConnection iame.ap.inalfa.local -Port 8090 | Select-Object ComputerName, TcpTestSucceeded
Test-NetConnection iame.ap.inalfa.local -Port 8000 | Select-Object ComputerName, TcpTestSucceeded
```

应看到：四条全部 `TcpTestSucceeded = True`。任一 `False` → 停，先查防火墙（规则按 IP+端口，通常不用新增）。

## 0.3 四个服务现状

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Status -App All
```

应看到：`Keycloak` / `MSIA-Server` / `BOL-Server` / `CapacityAPI` 均 `Running`，启动类型 `Automatic`，账号 `LocalSystem`；8443、9000、8078、8090、8000 都有监听。

任一不是 Running → 先起服务、确认业务可用，再开工。

> 判断某应用是否接 SSO，看日志里有没有 OIDC 输出，不要只看配置文件里有没有写——Capacity 就是这么漏掉的：`OIDC discovery 拉取失败` + `idp_unreachable` 才是证据。切换前四个服务都要按这条扫一眼 `-stderr.log`。

## 0.4 证书产物复核（只校验，不生成）

```powershell
$kt = 'C:\Program Files\Java\jdk-21.0.10\bin\keytool.exe'
& $kt -list -v -keystore C:\certs\iame.p12
(Select-String -Path C:\certs\ca-bundle.pem -Pattern 'BEGIN CERTIFICATE').Count
```

第一条会提示输入 keystore 口令（`IRSCNKettle01`）。应看到：

- `Keystore type: PKCS12`
- `Alias name: te-cn-webserver-new1-47e5f4ca-cbd4-4207-96ba-ab39a7cb3440`，`Entry type: PrivateKeyEntry`
- `Certificate chain length: 3`
- `Owner: CN=iame.ap.inalfa.local, ...`，`Issuer: CN=ap-SRV-APSH-PKI-01-CA-1, ...`
- `DNSName=iame.ap.inalfa.local`、`DNSName=msia.ap.inalfa.local`、`DNSName=blo.ap.inalfa.local`、`DNSName=eMotion.ap.inalfa.local`
- `Valid from: ... until: ... 2028年7月31日`

第二条应输出 `2`。

再确认两块分别是谁（两条 `Subject` 必须是中间 CA 与根 CA）：

```powershell
$txt = Get-Content C:\certs\ca-bundle.pem -Raw
[regex]::Matches($txt, '-----BEGIN CERTIFICATE-----([\s\S]*?)-----END CERTIFICATE-----') | ForEach-Object {
    $b = [Convert]::FromBase64String(($_.Groups[1].Value -replace '\s', ''))
    [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($b).Subject
}
```

不符 → 停。链长不是 3、块数不是 2（多出叶子或只有 1 块）、别名不存在、SAN 缺 `iame.ap.inalfa.local`，都先修产物再开工。

另外确认旧自签证书还在（回滚依赖，不要删）：

```powershell
Get-ChildItem C:\keycloak\conf\server.crt.pem, C:\keycloak\conf\server.key.pem | Select-Object Name, Length, LastWriteTime
```

## 0.5 开工判据

| 项 | 硬门槛 |
|---|---|
| 0.1 两台客户端解析到 `172.26.2.203` | **是** |
| 0.2 四端口从客户端可达 | **是** |
| 0.3 四服务 Running | **是** |
| 0.4 `iame.p12` 链长 3 ／ `ca-bundle.pem` 2 块 ／ 旧 PEM 在位 | **是** |
| 0.6 已按 A / B / C 选定一条路（HSTS 与明文端口互斥，见 0.6） | **是** |

全 PASS 才进第 1 章。任何一项不通过，停在原地修，不要靠窗口内现场补。

> 为什么必须用域名访问：`keycloak.conf` 里 `hostname-strict=true`，Keycloak 只接受 `Host: iame.ap.inalfa.local:8443`。用 `172.26.2.203` 或 `127.0.0.1` 访问会 403 或重定向到域名，所以切换后**不能用 IP 验证**，IP 也不再是回滚口径之外的有效地址。

## 0.6 硬冲突：HSTS 会让 8078 / 8090 / 8000 全部打不开（必读）

**现象**：服务端探测全 200，客户端浏览器却打不开。

```text
客户端浏览器：http://iame.ap.inalfa.local:8078
  → This site can't provide a secure connection
  → iame.ap.inalfa.local sent an invalid response.
  → ERR_SSL_PROTOCOL_ERROR

服务器本机： (Invoke-WebRequest http://127.0.0.1:8078/api/auth/config).StatusCode  → 200
            (Invoke-WebRequest http://iame.ap.inalfa.local:8078/api/auth/config).StatusCode → 200
```

**根因**：Keycloak 的 8443 在每个响应里都下发 HSTS：

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

HSTS 以**主机名**为键且**忽略端口**（不是按 origin）。浏览器只要访问过一次 `https://iame.ap.inalfa.local:8443`，就把「`iame.ap.inalfa.local` 一年内一律走 https、连子域也算」记进本地 HSTS 表，随后把 `http://iame.ap.inalfa.local:8078` 自动升级成 `https://iame.ap.inalfa.local:8078`。而 8078 / 8090 / 8000 三个端口只讲明文 HTTP，收到 TLS ClientHello 后回的是 HTTP 字节（uvicorn 表现为连接被判定非法、waitress 表现为挂起不答），握手必然失败。

此前用 `172.26.2.203` 不触发，是因为 **HSTS 不适用于 IP 字面量**——这解释了"换域名前一直好好的"。

**判定命令**（客户端或任意可达机器，只读）：

```powershell
# 1) 确认 8443 在下发 HSTS，记下 max-age 与 includeSubDomains
curl.exe -k -s -o NUL -D - "https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration" |
    Select-String -Pattern 'Strict-Transport-Security'

# 2) 确认三个应用端口自身不下发 HSTS（它们是无辜的）
curl.exe -s -o NUL -D - "http://iame.ap.inalfa.local:8078/api/auth/config" | Select-String -Pattern 'Strict-Transport-Security'
curl.exe -s -o NUL -D - "http://iame.ap.inalfa.local:8090/"                 | Select-String -Pattern 'Strict-Transport-Security'
curl.exe -s -o NUL -D - "http://iame.ap.inalfa.local:8000/health"           | Select-String -Pattern 'Strict-Transport-Security'

# 3) 复现：对明文端口发 TLS，必然失败（这就是浏览器看到的错误）
curl.exe -k -s -S --max-time 8 -o NUL "https://iame.ap.inalfa.local:8078/api/auth/config"   # (35) SEC_E_INVALID_TOKEN
curl.exe -k -s -S --max-time 8 -o NUL "https://iame.ap.inalfa.local:8090/"                  # (28) timed out
```

判据：第 1 条有输出且含 `max-age=31536000` → 就是本坑；第 2 条无输出 → 应用侧没有 HSTS，不用查它们；第 3 条报 35/28 → 明文端口确认不具备 TLS。

**为什么"清浏览器 HSTS 记录"没用**：清掉只是删掉本地这一条，但只要用户再走一次登录，浏览器必须先访问 8443（登录页、discovery、token 端点都在这），Keycloak 立刻把同样的 `max-age=31536000` 写回去，问题在第一次点击「统一登录」时就复发。换浏览器、上隐私窗口同理——隐私窗口里登录一次也会写进该配置档。`includeSubDomains` 还会把 `*.iame.ap.inalfa.local` 一并覆盖，所以子域方案也躲不掉。

**结论（设计冲突，不是偶发故障）**：在域名方案下，「一个主机名 + 三个明文端口」与「Keycloak 启用 HSTS」互斥。**在采用"一应用一主机名"（A 路径）之前，8078 / 8090 / 8000 三条链路在 `iame.ap.inalfa.local` 下都走不通**，且这不是配错、重启、清缓存能解决的。三条出路只有：

| 出路 | 形态 | 代价 |
|---|---|---|
| A | 每个应用一个独立主机名（HSTS 记录不跨主机） | 需新增 A 记录；且要过应用侧「`issuer` 主机名必须等于 `redirect_uri` 主机名」的校验（MSIA/BOL 命中即 503），需改代码 |
| B | 同主机名但**所有端口都上 HTTPS**（应用自己启 TLS 或前置反向代理） | 需反向代理 + 证书（p12 导不出 PEM 私钥，宜用现成 `.pfx` 给 IIS） |
| C | 退回 IP 访问 | 浏览器不套用 HSTS；但 `hostname-strict=true` 与证书 SAN 都不含 IP，等于全量回滚到 R2 |

**判断口径**：现场只要看到「服务端 200、客户端 `ERR_SSL_PROTOCOL_ERROR`」，先跑上面的判定命令，命中就按本节的 A/B/C 选路，不要再去查服务、证书链、`SSL_CERT_FILE`——那些都不参与这个故障。

---

# 1. 切换（S1–S11，按序做）

> 从 S2 停 Keycloak 到 S10 三个应用重启完成，登录一定失败，这是预期空窗，不是故障。
> 每一步只留：命令 → 应看到什么 → 失败怎么办。
> 所有 PowerShell 窗口都要**以管理员身份运行**（`register-services-nssm.ps1` 的启停/写环境变量会校验）。

- [ ] **S1 备份（2 分钟）**

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Dump -App All
```

记下输出的目录，记为 `$bk`（形如 `C:\Services\rollback\baseline-20261110-093000`），然后：

```powershell
$bk = 'C:\Services\rollback\baseline-<时间戳>'      # 换成上一步真实目录

# Capacity 的 .env 固定在 publish 根下（与 CapacityAPI 子目录同级），这里做一次校验
$cap = (Get-ChildItem 'C:\ApplicationFile\ExecuteProgram\Capacity\publish' -Force -File -Filter '.env*' |
        Where-Object { Select-String -Path $_.FullName -Pattern '^\s*OIDC_ISSUER\s*=' -Quiet } |
        Select-Object -First 1).FullName
$cap

Copy-Item C:\keycloak\conf\keycloak.conf, C:\keycloak\conf\server.crt.pem, C:\keycloak\conf\server.key.pem -Destination $bk
Copy-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' "$bk\msia-config.ini"
Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' "$bk\bol-db_config.ini"
Copy-Item $cap "$bk\capacity-env.txt"
Get-FileHash "$bk\server.crt.pem" -Algorithm SHA256 | Out-File "$bk\manifest.txt"
icacls $bk /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F"
Get-ChildItem $bk | Select-Object Name, Length
```

`$cap` 应打印 `C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env`——`.env` 就在 `publish` 根目录下，与 `CapacityAPI` 子目录同级（`publish` 下还有 `data`、`_internal`、`BUILD_INFO.json`、`CapacityAPI.exe`、`DB_VERSION.txt`、`DEPLOYMENT_MARKER.json`），**不在 `_internal` 里**。**这个输出就是权威路径**，记在 `$bk\clients.txt` 首行；S9 / R2 用同一条命令重新定位。

> 为什么命令里必须带 `-Force`：`.env` 是隐藏文件，不加 `-Force` 用 `Get-ChildItem` / 资源管理器都列不出来——这就是最初"找不到配置文件"的原因。别改到 `CapacityAPI\` 子目录或别处同名的 `.env`：`publish\.env` 与 `CapacityAPI\` 是两层，改错副本等于没改。

再把三个应用当前的 OIDC 原值一次打印存档（Capacity 的四行与行号都从这里的输出来）：

```powershell
@(
  'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini',
  'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini',
  $cap
) | ForEach-Object {
    Select-String -Path $_ -Pattern '^\s*(issuer|client_id|redirect_uri|front_callback|OIDC_[A-Z_]+)\s*=' |
        Select-Object Path, LineNumber, Line
} | Tee-Object "$bk\oidc-before.txt"
```

应看到：MSIA / BOL 各自的 `issuer` / `client_id` / `redirect_uri`（BOL 还有 `front_callback`）；Capacity 的 `OIDC_ISSUER` / `OIDC_CLIENT_ID`（`ics-prod`）/ `OIDC_REDIRECT_URI` / `OIDC_FRONTEND_URL` / `OIDC_POST_LOGOUT_REDIRECT_URI` 五行，值都含 `172.26.2.203`。

应看到（文件清单）：`Keycloak.reg`、`MSIA-Server.reg`、`BOL-Server.reg`、`CapacityAPI.reg`、四个 `*-status.txt`，加上 `keycloak.conf`、`server.crt.pem`、`server.key.pem`、`msia-config.ini`、`bol-db_config.ini`、`capacity-env.txt`、`oidc-before.txt`、`manifest.txt`，全部非空。

顺带把当前信任包口径抄下来（回滚用）：`CapacityAPI.reg` / `MSIA-Server.reg` / `BOL-Server.reg` 里 `SSL_CERT_FILE` 现在各指向什么。`CapacityAPI` 这条多半是空的或不是当前 Keycloak 证书——它日志里的 `self-signed certificate` 就是证据；照实际值抄，不要按"应该是"填。

失败：缺文件就不往下做，补齐再开工。`.reg` 含明文口令，`icacls` 必须执行，且不要把 `$bk` 复制到共享盘。

- [ ] **S2 停 Keycloak（1 分钟）**

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Stop -App Keycloak
Get-NetTCPConnection -LocalPort 8443, 9000 -State Listen -ErrorAction SilentlyContinue
```

应看到：`服务已停止`；第二条命令**无输出**。

失败：40 秒仍未停止 → `Get-Process java | Select-Object Id, Path` 看残留，`Stop-Process -Id <PID> -Force` 后再跑一次 Stop。

- [ ] **S3 改 `keycloak.conf`：域名 + keystore（2 分钟）**

```powershell
notepad C:\keycloak\conf\keycloak.conf
```

只改下面这几行，其余不动：

| 现所在行 | 现状 | 改成 |
|---|---|---|
| 40 | `hostname=172.26.2.203` | `hostname=iame.ap.inalfa.local` |
| 63 | `https-certificate-file=C:/keycloak/conf/server.crt.pem` | `# https-certificate-file=C:/keycloak/conf/server.crt.pem` |
| 64 | `https-certificate-key-file=C:/keycloak/conf/server.key.pem` | `# https-certificate-key-file=C:/keycloak/conf/server.key.pem` |
| 63–64 之后 | — | 新增 3 行：`https-key-store-file=C:/certs/iame.p12`<br>`https-key-store-password=IRSCNKettle01`<br>`https-key-store-type=PKCS12` |

**不要动**：45 行 `hostname-strict=true`、46 行 `hostname-strict-https=true`、50 行 `http-enabled=false`、51 行 `https-port=8443`、67–69 行 health 配置、80 行 `http-management-http-enabled=true`。

> 为什么改 keystore：`https-certificate-file` / `https-certificate-key-file` 要求私钥是**未加密的 PKCS#8 PEM**，而 p12 里的私钥受口令保护、导不出来。keystore 方式可以直接被 Keycloak 读取，私钥不出 `.p12`。

保存后核对：

```powershell
Select-String -Path C:\keycloak\conf\keycloak.conf -Pattern '^hostname|^https-key-store|^https-certificate' |
    Select-Object LineNumber, Line
```

应看到：`hostname=iame.ap.inalfa.local`、三行 `https-key-store-*`；`https-certificate-*` 两行都以 `#` 开头（已被注释）。

口令落盘的风险与收紧（必做）：

```powershell
icacls C:\keycloak\conf\keycloak.conf /inheritance:r /grant:r "SYSTEM:(F)" /grant:r "Administrators:(F)"
icacls C:\certs\iame.p12       /inheritance:r /grant:r "SYSTEM:(F)" /grant:r "Administrators:(F)"
```

应看到两条 `已处理 1 个文件`。这两条把权限收到"SYSTEM + 本机管理员"，不再对 `Users` 等普通组开放。

> 取舍说明：口令写在配置文件里就是明文，能读该文件的本机管理员都能取到；Keycloak 服务以 LocalSystem 运行，所以 SYSTEM 必须可读。这是改用 keystore 后必须接受的风险，控制手段只有 ACL 收紧 + 文件不复制到共享目录/临时目录。不要把口令再写进环境变量：那只是从配置文件搬到服务注册表，同样明文，还多一个来源。

失败：改错或不确定 → `Copy-Item "$bk\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force` 复原，重做 S3。

- [ ] **S4 起 Keycloak（1–2 分钟）**

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Start -App Keycloak
Start-Sleep -Seconds 5
(Invoke-WebRequest http://127.0.0.1:9000/health/ready -UseBasicParsing).StatusCode
```

应看到：`服务状态 Running`、`端口 8443 处于 LISTENING`、健康检查 `200`。

失败：

```powershell
Get-Content C:\Services\logs\Keycloak-stderr.log -Tail 40
```

对照第 3 章。**这一步失败只回退 S3 一处**：此时客户端、三个应用、`SSL_CERT_FILE` 都没动，按 R1 恢复 `keycloak.conf` 并重启即可回到切换前状态，不影响任何业务。

- [ ] **S5 证书链 + issuer 回显（1 分钟）**

```powershell
$kt = 'C:\Program Files\Java\jdk-21.0.10\bin\keytool.exe'
& $kt -printcert -sslserver iame.ap.inalfa.local:8443
(curl.exe -k -s 'https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration' | ConvertFrom-Json).issuer
```

应看到：

- `Certificate[1]`：`Owner: CN=iame.ap.inalfa.local`，`Issuer: CN=ap-SRV-APSH-PKI-01-CA-1`
- `Certificate[2]`：`Owner: CN=ap-SRV-APSH-PKI-01-CA-1`
- `Certificate[3]`：`Owner: CN=INALFA-IRSPKIROOT01-CA`
- issuer 逐字符等于 `https://iame.ap.inalfa.local:8443/realms/inalfa`

失败：证书还是旧的（CN=172.26.2.203）→ 回 S3 看 keystore 三行是否生效、旧 PEM 两行是否注释干净，然后 S2→S4 重来；issuer 不对 → 只改 40 行 `hostname`，重做 S4–S5。

- [ ] **S6 改 Keycloak 三个 client（4 分钟）**

浏览器打开 `https://iame.ap.inalfa.local:8443` → `Administration Console` → 登录（master 管理员）→ 左上角切 realm `inalfa`。

`$bk\oidc-before.txt` 已经把三个应用的 `client_id` 与 `redirect_uri` 原值打印出来了，先按它把 `msia-prod` / `bol-prod` / `ics-prod` 的 `Valid redirect URIs`、`Valid post logout redirect URIs` 与 `Web origins` 现有内容原样抄进 `$bk\clients.txt`（回滚依据）。

然后逐个加一行（**保留旧值，不要替换**）：

| client | Valid redirect URIs 新增 | Valid post logout redirect URIs 新增 | Web origins 新增 |
|---|---|---|---|
| `msia-prod` | `http://iame.ap.inalfa.local:8078/api/auth/oidc/callback` | — | `http://iame.ap.inalfa.local:8078` |
| `bol-prod` | `http://iame.ap.inalfa.local:8090/api/auth/oidc/callback` | — | `http://iame.ap.inalfa.local:8090` |
| `ics-prod` | `http://iame.ap.inalfa.local:8000/api/v1/auth/oidc/callback` | `http://iame.ap.inalfa.local:8000/login` | `http://iame.ap.inalfa.local:8000` |

每改完一个点 `Save`。应看到：保存后列表里新旧地址并存（旧的 `172.26.2.203` 行仍在），没有 `*`。

> `ics-prod` 的两组 URI 在不同 Tab 里，容易只改一组：`Valid redirect URIs` 在 `Settings` 上半部分，`Valid post logout redirect URIs` 在它下面单独一栏。**两组都要加**——漏掉后者表现为"能登录、点退出报 `Invalid redirect uri`"。

注意：新增值和 S7–S9 写进应用配置的值必须**逐字符相同**（含尾斜杠有无）。登录时若 Keycloak 报 `Invalid parameter: redirect_uri` → 从浏览器地址栏复制 `redirect_uri=` 的值（先 URL 解码），原样加进 `Valid redirect URIs`，再试一次。

失败：client 名带尾部空格会查不到 → `Clients` 列表里点进去复制 `Client ID`，用 `Trim()` 比对后再改。

- [ ] **S7 改 MSIA 配置（2 分钟）**

```powershell
notepad 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini'
```

`[oidc]` 段改两行（`enabled`、`client_id = msia-prod`、`front_callback = /oidc/callback` 都不动）：

```ini
issuer = https://iame.ap.inalfa.local:8443/realms/inalfa
redirect_uri = http://iame.ap.inalfa.local:8078/api/auth/oidc/callback
```

模板行号：`issuer` 第 106 行、`redirect_uri` 第 117 行；现场这份若按别的文档整块替换过，行号会变，**认键名不认行号**。改完核对：

```powershell
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' `
    -Pattern '^\s*(issuer|redirect_uri)\s*=' | Select-Object LineNumber, Line
Get-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' | Select-Object LastWriteTime
```

应看到两行都是域名口径，`LastWriteTime` 是你刚保存的时间。

只改 exe 同目录这一份：`_internal\config.ini` 已在发布时删除，仓库里 `MSIA Report\backend\config.ini` 改了不生效。

确认没有环境变量抢先生效（代码里环境变量优先，`config.ini` 只在变量缺失时写入）：

```powershell
nssm get MSIA-Server AppEnvironmentExtra
```

应看到只有 `SSL_CERT_FILE`（可能还有 `JWT_SECRET_KEY`），**没有** `OIDC_ISSUER` / `OIDC_REDIRECT_URI`。若有 → 以环境变量为准，必须同步改，否则改 ini 不生效。

- [ ] **S8 改 BOL 配置（2 分钟）**

```powershell
notepad 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini'
```

`[oidc]` 段改两行：

```ini
issuer = https://iame.ap.inalfa.local:8443/realms/inalfa
redirect_uri = http://iame.ap.inalfa.local:8090/api/auth/oidc/callback
```

`redirect_uri` 在第 107 行（原值 `http://172.26.2.203:8090/api/auth/oidc/callback`，**无尾斜杠**）；第 110 行 `front_callback = /oidc/callback/` **保持不动**（它带尾斜杠，本来就如此）。`issuer` 在 `[oidc]` 段内 `redirect_uri` 上方，原值含 `172.26.2.203`。

核对：

```powershell
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' `
    -Pattern '^\s*(issuer|redirect_uri|front_callback)\s*=' | Select-Object LineNumber, Line
nssm get BOL-Server AppEnvironmentExtra
```

应看到三行：`issuer`/`redirect_uri` 为新域名，`front_callback` 仍是 `/oidc/callback/`；服务环境变量只有 `SSL_CERT_FILE`，无 `OIDC_*`。

- [ ] **S9 改 Capacity 配置（3 分钟）**

Capacity 的配置是 `C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env`（dotenv 形式，键名带 `OIDC_` 前缀），不是 `db_config.ini`，也不在 `_internal` 下。先校验路径再打开：

```powershell
$cap = (Get-ChildItem 'C:\ApplicationFile\ExecuteProgram\Capacity\publish' -Force -File -Filter '.env*' |
        Where-Object { Select-String -Path $_.FullName -Pattern '^\s*OIDC_ISSUER\s*=' -Quiet } |
        Select-Object -First 1).FullName
$cap
notepad $cap
```

`$cap` 必须打印 `C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env`；不一致 → 停，先确认改的是不是同一份（`publish\.env` 与 `CapacityAPI\` 子目录是两层，别改到别处的同名文件）。

> `-Force` 不能省：`.env` 是隐藏文件，不加 `-Force` 根本列不出来——这就是最初"找不到配置"的原因。

改**四个键**（不是两个），只把主机名 `172.26.2.203` 换成 `iame.ap.inalfa.local`，端口、路径、协议一律不动：

```dotenv
OIDC_ISSUER=https://iame.ap.inalfa.local:8443/realms/inalfa
OIDC_REDIRECT_URI=http://iame.ap.inalfa.local:8000/api/v1/auth/oidc/callback
OIDC_FRONTEND_URL=http://iame.ap.inalfa.local:8000
OIDC_POST_LOGOUT_REDIRECT_URI=http://iame.ap.inalfa.local:8000/login
```

| 键 | 改前 | 改后 |
|---|---|---|
| `OIDC_ISSUER` | `https://172.26.2.203:8443/realms/inalfa` | `https://iame.ap.inalfa.local:8443/realms/inalfa` |
| `OIDC_REDIRECT_URI` | `http://172.26.2.203:8000/api/v1/auth/oidc/callback` | `http://iame.ap.inalfa.local:8000/api/v1/auth/oidc/callback` |
| `OIDC_FRONTEND_URL` | `http://172.26.2.203:8000` | `http://iame.ap.inalfa.local:8000` |
| `OIDC_POST_LOGOUT_REDIRECT_URI` | `http://172.26.2.203:8000/login` | `http://iame.ap.inalfa.local:8000/login` |

`OIDC_CLIENT_ID`（`ics-prod`）、`OIDC_REQUIRE_GROUP=true`、`OIDC_REQUIRED_GROUP=app-ics`、以及 `OIDC_CLIENT_SECRET` 都不动。

改完核对：

```powershell
Select-String -Path $cap -Pattern '^\s*OIDC_(ISSUER|CLIENT_ID|REDIRECT_URI|FRONTEND_URL|POST_LOGOUT_REDIRECT_URI)\s*=' |
    Select-Object LineNumber, Line
nssm get CapacityAPI AppEnvironmentExtra
```

应看到：

- `OIDC_ISSUER` / `OIDC_REDIRECT_URI` / `OIDC_FRONTEND_URL` / `OIDC_POST_LOGOUT_REDIRECT_URI` 四行都是 `iame.ap.inalfa.local`，`OIDC_CLIENT_ID=ics-prod`；
- `OIDC_REDIRECT_URI` 与 S6 加进 `ics-prod` 的 `Valid redirect URIs` **逐字符相同**；
- `OIDC_POST_LOGOUT_REDIRECT_URI` 与 S6 加进 `Valid post logout redirect URIs` **逐字符相同**；
- 环境变量里此时可能还没有 `SSL_CERT_FILE` 或值不对（它现在报 `self-signed certificate` 就是证据），S10 统一写入。

> **`.env` 的值不能带反引号或引号。** 现场抄下来的原值可能是 `` OIDC_ISSUER=`https://…` `` 这种形态，dotenv 解析后会把反引号当成值的一部分，导致 issuer 比对失败。保存前逐行确认首尾没有 `` ` ``、`'`、`"` 和多余空格。

失败：`redirect_uri` 与 client 里那条差一个字符（多/少尾斜杠、`http` 写成 `https`、路径写成 `/api/auth/…` 而不是 `/api/v1/auth/…`）→ 登录必然 400，回 S6 或本步对齐后再往下。

- [ ] **S10 改三个应用的信任包并重启（2 分钟）**

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action SetEnv -App MSIA     -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App BOL      -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App Capacity -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
Restart-Service MSIA-Server
Restart-Service BOL-Server
Restart-Service CapacityAPI
```

应看到：三条 SetEnv 各输出 `已更新 1 项`，回读确认里有 `SSL_CERT_FILE = C:\certs\ca-bundle.pem`，并提示"必须重启服务"。

```powershell
Get-Service MSIA-Server, BOL-Server, CapacityAPI | Select-Object Name, Status
(Invoke-WebRequest http://127.0.0.1:8078/api/auth/config -UseBasicParsing).StatusCode
(Invoke-WebRequest http://127.0.0.1:8090/ -UseBasicParsing).StatusCode
(Invoke-WebRequest http://127.0.0.1:8000/docs -UseBasicParsing).StatusCode
Get-Content C:\Services\logs\MSIA-Server-stderr.log -Tail 30
Get-Content C:\Services\logs\BOL-Server-stderr.log -Tail 30
Get-Content C:\Services\logs\CapacityAPI-stderr.log -Tail 30
```

应看到：三个 `Running`；三个探测都返回 2xx；三份日志里没有 `CERTIFICATE_VERIFY_FAILED`、`idp_unreachable`、`OIDC 配置不完整`、`unable to get local issuer certificate`。

失败：`CERTIFICATE_VERIFY_FAILED` → `SSL_CERT_FILE` 没改成 `ca-bundle.pem` 或没重启，回 S10 重做；`503 OIDC 配置不完整` → 回 S7/S8/S9，`issuer` 与 `redirect_uri` 主机名必须都是 `iame.ap.inalfa.local`。

> `SSL_CERT_FILE` 是**替换**而不是追加，应用其它 HTTPS 外调也只用这个包；`ca-bundle.pem` 自带中间与根，够用。

- [ ] **S11 端到端验证（5 分钟）**

按第 2 章跑三条链路，并记录：issuer 前后值、证书指纹、`$bk` 路径、停机起止、执行人。

---

# 2. 端到端验证

## 2.1 MSIA

1. 客户端打开 `http://iame.ap.inalfa.local:8078` → 点「统一登录」；
2. 跳转到 `https://iame.ap.inalfa.local:8443/realms/inalfa/protocol/openid-connect/auth?...`，地址栏锁标志正常；
3. 登录后回到 `http://iame.ap.inalfa.local:8078/api/auth/oidc/callback?code=...`（无尾斜杠）→ 进入业务页；
4. Keycloak 控制台 `Events` 里有一条对应 `LOGIN`。

## 2.2 BOL

同上，地址换 `http://iame.ap.inalfa.local:8090`。若登录后先 301 到 `…/api/auth/oidc/callback/?code=...`（Django 补斜杠）再进业务页，属正常。

## 2.3 Capacity

1. 客户端打开 `http://iame.ap.inalfa.local:8000` → 点「统一登录」；
2. 能跳到 `https://iame.ap.inalfa.local:8443/realms/inalfa/...`，登录后回到 `http://iame.ap.inalfa.local:8000` 的业务页；
3. **登录成功后点一次「退出」**，确认浏览器回到 `http://iame.ap.inalfa.local:8000/login`（不是 `Invalid redirect uri` 报错页，也不是停在 Keycloak 的登出页）；
4. `Get-Content C:\Services\logs\CapacityAPI-stderr.log -Tail 50` 里没有 `CERTIFICATE_VERIFY_FAILED`、也没有 `idp_unreachable`。

若第 2 步登录后报权限拒绝（403 / `access denied` / 无权限页），先查 Keycloak 里该用户是否在 `app-ics` 组：`ics-prod` 启用了 `OIDC_REQUIRE_GROUP=true`、`OIDC_REQUIRED_GROUP=app-ics`，不在组里就是没权限，**不要先去怀疑证书或 `SSL_CERT_FILE`**。

## 2.4 正常 vs 故障

| 看到什么 | 结论 |
|---|---|
| 每人要求重登一次，之后正常，不再循环 | 正常（主机名变了，旧会话取不到） |
| 登录成功又跳回登录页、反复循环 | 故障：`iss` 与配置不一致，回 S5 |
| 页面能开，点登录跳回 IP | 故障：应用 `redirect_uri` 没改，回 S7 / S8 / S9 |
| Keycloak 报 `Invalid parameter: redirect_uri` | 故障：client 没加新 URI，回 S6 |
| 能登录，点退出报 `Invalid redirect uri` | 故障：`OIDC_POST_LOGOUT_REDIRECT_URI` 漏改（应用侧或 client 的 `Valid post logout redirect URIs`），回 S6 / S9 |
| 浏览器证书告警 | 故障：访问的主机名不在 SAN，只能用 `iame.ap.inalfa.local` |
| 页面直接报 `ERR_SSL_PROTOCOL_ERROR` / `sent an invalid response`，但服务器本机 `Invoke-WebRequest` 返回 200 | 故障：HSTS 把明文端口升级成了 https，见 0.6（清浏览器 HSTS 无效） |
| 某台电脑打不开、服务器本机正常 | 故障：该机 DNS/防火墙，回 0.1 / 0.2 |
| 应用日志 `CERTIFICATE_VERIFY_FAILED` | 故障：`SSL_CERT_FILE` 未生效或没重启，回 S10 |
| 应用日志 `idp_unreachable` | 故障：拉取 discovery 失败，同上一行，回 S10 |

## 2.5 一次性校验

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Verify -App All
```

应看到：服务状态、端口、`SSL_CERT_FILE`、MSIA/BOL/Capacity 接口探针全 `OK`。

注意：Keycloak 那一段的 discovery 探针走 `https://127.0.0.1:8443`，`Host` 头不匹配会被 403 拒绝，可能显示 `FAIL`。**这不是故障**——以 S5 的域名探针为准。除 Keycloak 探针外，其余项有 `FAIL` 才需要处理。

---

# 3. 失败对照

| 现象 | 最可能原因 | 回到 |
|---|---|---|
| Keycloak 起不来，日志 `Keystore was tampered with, or password is incorrect` | `https-key-store-password` 与 `.p12` 口令不一致 | S3 |
| Keycloak 起不来，日志 `Failed to load private key` / `Invalid keystore format` | 旧 PEM 两行没注释干净；或 `https-key-store-type` 不是 `PKCS12` | S3 |
| Keycloak 起不来，日志提示找不到证书文件 | 路径写成了 `\` 或文件不在 `C:\certs\iame.p12` | S3 |
| `kc.bat` 报 `Unrecognized option` | 抄了 26.x 的参数 | S3 |
| 8443 已监听但健康检查非 200 | 数据库连不上 / realm 未就绪 | 看 `Keycloak-stderr.log`；口令在 `.reg` 里，用 `-Action SetEnv` 修 |
| Verify 里 Keycloak 探针 403 | `hostname-strict=true` 拒绝 `127.0.0.1` 的 Host 头 | 预期行为；用 S5 的域名探针判定 |
| 浏览器 `ERR_CERT_COMMON_NAME_INVALID` | 用了 IP 或别的主机名 | S5 |
| 浏览器 `ERR_SSL_PROTOCOL_ERROR` / `sent an invalid response`（服务端探针 200） | HSTS（`max-age=31536000; includeSubDomains`）把明文端口升级成 https，与 A 路径互斥 | 0.6（**不是**证书、服务或 `SSL_CERT_FILE` 问题） |
| 浏览器 `ERR_CERT_AUTHORITY_INVALID` | 该客户端不信任 `INALFA-IRSPKIROOT01-CA` | 域内机器查 GPO 是否下发根证书；非域机器手工装根 |
| 应用 503 `OIDC 配置不完整` | `issuer` 与 `redirect_uri` 主机不一致，或 `enabled=false` | S7 / S8 / S9 |
| 应用 `CERTIFICATE_VERIFY_FAILED`（含 `self-signed certificate`） | `SSL_CERT_FILE` 未指向 `ca-bundle.pem`，或改完没重启 | S10 |
| 应用 `idp_unreachable` / `OIDC discovery 拉取失败` | 拉不到 `…/.well-known/openid-configuration`：配置仍指 IP、或信任包没生效 | S9 / S10 |
| Keycloak 返回 `Invalid parameter: redirect_uri` | client 的 `Valid redirect URIs` 与应用配置值不是逐字符相同 | S6 |
| 能登录，点退出报 `Invalid redirect uri` | Capacity 的 `OIDC_POST_LOGOUT_REDIRECT_URI` 没改成域名；或 `ics-prod` 的 `Valid post logout redirect URIs` 没加新值 | S6 / S9 |
| Capacity 登录后被拒（403 / 无权限 / `access denied`） | 用户不在 `app-ics` 组（`OIDC_REQUIRE_GROUP=true`），不是证书问题 | Keycloak 里把用户加入 `app-ics` 组 |
| `unable to get local issuer certificate` | `ca-bundle.pem` 缺块（应为 2：中间 + 根） | 0.4 |
| kcadm/Java 客户端 `PKIX path building failed` | 仍信任旧自签证书 | 本手册不用 kcadm；用 Admin Console 改 client |
| 登录反复跳转、Keycloak 正常 | `iss` 与配置不一致 | S5 |
| 域名打不开但服务器本机正常 | 客户端 DNS 或防火墙未通 | 0.1 / 0.2 |

---

# 4. 回滚

判定：切换窗口内 15 分钟定位不到原因，且三个应用有登录不进去的，就回滚，不要在窗口里继续试。

按"已经改到哪一步"选一档，不要跳档。

## 4.1 R1：只回 Keycloak（S3–S5 失败，应用还没动）

```powershell
$bk = 'C:\Services\rollback\baseline-<时间戳>'
Copy-Item "$bk\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force
cd C:\Services
.\register-services-nssm.ps1 -Action Start -App Keycloak
Start-Sleep -Seconds 10
(curl.exe -k -s 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration' | ConvertFrom-Json).issuer
```

判据：

- issuer 回显 `https://172.26.2.203:8443/realms/inalfa`；
- `Test-Path C:\keycloak\conf\server.crt.pem`、`server.key.pem` 都为 `True`（这两个文件全程没删）；
- MSIA / BOL 登录恢复；Capacity 回到切换前状态（它此前 SSO 本来就不通，R1 不负责修它）。

若备份的 `keycloak.conf` 丢了，手工改回三处：40 行 `hostname=172.26.2.203`；删掉三行 `https-key-store-*`；把 63/64 两行的 `#` 去掉。

## 4.2 R2：全部回退（S6 之后失败，应用已改）

顺序不能反：先 Keycloak，再应用配置，最后信任包。

```powershell
$bk = 'C:\Services\rollback\baseline-<时间戳>'
$cap = (Get-ChildItem 'C:\ApplicationFile\ExecuteProgram\Capacity\publish' -Force -File -Filter '.env*' |
        Where-Object { Select-String -Path $_.FullName -Pattern '^\s*OIDC_ISSUER\s*=' -Quiet } |
        Select-Object -First 1).FullName
$cap
Copy-Item "$bk\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force
Copy-Item "$bk\msia-config.ini" 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' -Force
Copy-Item "$bk\bol-db_config.ini" 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' -Force
Copy-Item "$bk\capacity-env.txt" $cap -Force

cd C:\Services
.\register-services-nssm.ps1 -Action Stop  -App Keycloak
.\register-services-nssm.ps1 -Action Start -App Keycloak
.\register-services-nssm.ps1 -Action SetEnv -App MSIA     -CertFile C:\keycloak\conf\server.crt.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App BOL      -CertFile C:\keycloak\conf\server.crt.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App Capacity -CertFile C:\keycloak\conf\server.crt.pem -SecretMode Keep
Restart-Service MSIA-Server
Restart-Service BOL-Server
Restart-Service CapacityAPI
```

Capacity 的 `SSL_CERT_FILE` 回滚值是**旧自签证书**，不是"变回空"：它切换前信任失败就是因为这个变量没指对，恢复成空等于把 SSO 继续留在坏的状态。旧自签证书是回滚后 Keycloak 实际在用的那张，指它才对。

判据（四条同时满足才算回滚成功）：

1. `curl.exe -k -s 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration'` 的 issuer 为 `https://172.26.2.203:8443/realms/inalfa`；
2. 三个服务 `Running`，`http://172.26.2.203:8078`、`:8090`、`:8000` 都能登录；
3. 三个服务的 `AppEnvironmentExtra` 里 `SSL_CERT_FILE` 为 `C:\keycloak\conf\server.crt.pem`，且该文件存在；
4. 三份 `-stderr.log` 无 `CERTIFICATE_VERIFY_FAILED`、无 `idp_unreachable`。

client 侧不用急着动：S6 是"新增一行、保留旧值"，旧 URI 一直在，回滚后照旧可用。新加的三条留到 5.1 一起清。

回滚完成后：把过程记入变更记录，重新排期；不要当天再试第二次。

---

# 5. 收尾

## 5.1 48 小时后清理 client 旧值

`Clients` → `msia-prod` / `bol-prod` / `ics-prod` → `Settings` → 删掉含 `172.26.2.203` 的 `Valid redirect URIs`、`Valid post logout redirect URIs` 与 `Web origins` 行 → `Save`（`ics-prod` 的 post logout 那组别忘）。

判据：三个 client 只剩 `iame.ap.inalfa.local`，且三条链路登录（Capacity 含一次退出回 `/login`）仍正常。清理后登录失败 → 把旧值临时加回，按第 3 章排查。

## 5.2 证书台账

登记：`C:\certs\iame.p12`、`C:\certs\IRSCNKettle01.pfx`、`C:\certs\ca-bundle.pem` 三个文件的 SHA256；别名 `te-cn-webserver-new1-47e5f4ca-cbd4-4207-96ba-ab39a7cb3440`；链 3 张（叶子 / 中间 / 根）的主体与有效期；叶子 SAN 4 条；序列号与指纹；执行人与日期。

到期日 `2028-07-31` 与中间 CA 相同，届时必须整体重签，不能只续叶子。

## 5.3 `SSL_CERT_FILE` 落位记录

值 `C:\certs\ca-bundle.pem`，注入方式 `register-services-nssm.ps1 -Action SetEnv -App MSIA|BOL|Capacity -CertFile ... -SecretMode Keep`（写在服务 `Parameters\AppEnvironmentExtra`，持久生效），三个服务都登记。

记录包内 2 张证书的主体。该变量是"替换"语义，不读 Windows 证书存储，所以包里必须始终含中间 + 根。

## 5.4 旧文件处理

- `C:\keycloak\conf\server.crt.pem` / `server.key.pem` 与 `$bk` 保留 30 天（回滚依赖），之后删。
- `keycloak.conf` 里的 `https-certificate-*` 保持注释状态，不要删行，便于对照。
- 巡检/采集脚本的 `-Server` 改为 `https://iame.ap.inalfa.local:8443`。
- 本机没有 openssl，全部操作用 `keytool` + PowerShell，不要临时找 `openssl.exe`。

## 5.5 变更记录

记一条：时间窗、执行人、`$bk` 路径、切换前后 issuer、证书指纹、`ca-bundle.pem` 块数（2）、三个 client 的新旧 URI、回滚判据（未触发）。
