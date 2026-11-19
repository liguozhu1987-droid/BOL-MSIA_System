# Keycloak 证书与域名单批切换手册（方案 B）

> 状态：2026-11-09 定稿。执行方式为**单批**——一个窗口内完成"换证书 + 切域名 + 三个系统同步改配置 + 验证"，不再分两批。
> 原因：IT 交付的 pfx（`IRSCNKettle01.pfx`）SAN 无 `IP:172.26.2.203`，原"第一批只换证书、issuer 保持 IP"的方案不成立，已作废（原文见附录 A）。
> 环境：Keycloak 25.0.6，`C:\keycloak`，`C:\keycloak\conf\keycloak.conf`，8443 HTTPS + 9000 管理端口，NSSM 托管。
> 不覆盖：两个应用的代码改动、realm/client 新建、IIS ARR 的完整配置。

## 0. 最终字面值（所有系统按此表改，不再二次确认）

| 项 | 值 |
|---|---|
| 域名 | `iame.ap.inalfa.local`（已定稿；`sso.ap.inalfa.local` 作废，历史文档旧值保留并标注作废） |
| Keycloak issuer | `https://iame.ap.inalfa.local:8443/realms/inalfa` |
| MSIA 对外地址 | `http://iame.ap.inalfa.local:8078` |
| MSIA 回调 | `http://iame.ap.inalfa.local:8078/api/auth/oidc/callback`（**无尾斜杠**） |
| BOL 对外地址 | `http://iame.ap.inalfa.local:8090` |
| BOL 回调 | `http://iame.ap.inalfa.local:8090/api/auth/oidc/callback/`（**带尾斜杠**） |
| `webOrigins` | `http://iame.ap.inalfa.local:8078`、`http://iame.ap.inalfa.local:8090`（无尾斜杠、无路径） |
| 证书文件 | `C:\certs\IRSCNKettle01.pfx`（SHA256 `28FF0FA0AD530B2B6B8E96CB49D9F53967235A5A5899DE5B210BC4572CF47558`） |

> 待现场确认（不编造）：NSSM 服务名、`JAVA_HOME` 实际路径、Keycloak 服务运行账号、MSIA/BOL 的服务名或启动方式、两个应用 `config.ini`/`db_config.ini` 的实际生效路径。

---

## 1. 窗口前准备清单（可提前交 IT 或自己准备）

### 1.1 前置项

| # | 项 | 谁做 | 判据 | 失败怎么办 |
|---|---|---|---|---|
| P1 | DNS A 记录 `iame.ap.inalfa.local → 172.26.2.203` | IT，可提前 1–2 天 | `Resolve-DnsName iame.ap.inalfa.local` 返回 `172.26.2.203` | 无解析不进窗口 |
| P2 | 两台**不同网段**机器验证解析与端口连通 | 自己，窗口前 1 天 | 两台机器上 8078/8090/8443 三个端口全 `TcpTestSucceeded=True` | 任一失败先查 DNS/防火墙，不进窗口 |
| P3 | 防火墙确认 | 自己 | 主机名解析到同一 IP，规则按 IP+端口照旧有效，**不需要新增开放** | 只有解析到别的 IP 时才要重开 |
| P4 | 产物 1：`keycloak-ssl.p12` | 自己，见 2.3 | `keytool -list` 显示 `PrivateKeyEntry`、`Certificate chain length: 3` | 转换失败查别名/口令 |
| P5 | 产物 2：`inaalfa-ca-chain.pem`（根 + 中间） | 自己，见 3.1 | 文件内 2 个 `BEGIN CERTIFICATE` 块 | 见 3.3 报错对照 |
| P6 | 产物 3：`ca-bundle.pem`（P5 + Python 默认公共根） | 自己，见 3.2 | 应用侧 TLS 探测返回 `TLS OK` | 见 3.3 |
| P7 | 备份：`keycloak.conf`、旧 `server.crt.pem`、旧 `server.key.pem` | 自己，见 2.4 末尾 | 备份目录含三文件 + `manifest.txt` | 无备份不开工 |
| P8 | 两个应用的待改配置文本（改好的整段 `[oidc]`） | 自己，见 5.2/5.3 | 文本已备好，窗口内粘贴即用 | 现写会拉长空窗 |
| P9 | client 的新 redirect URI / webOrigins 提前追加 | 自己，见 5.4，**窗口前做，不停机** | 控制台新旧值并存 | 失败不影响现网 |

### 1.2 两台机器上的验证命令（同一段，在每台各跑一次）

```powershell
Resolve-DnsName iame.ap.inalfa.local | Select-Object Name,Type,IPAddress
Test-NetConnection iame.ap.inalfa.local -Port 8078 | Select-Object ComputerName,TcpTestSucceeded
Test-NetConnection iame.ap.inalfa.local -Port 8090 | Select-Object ComputerName,TcpTestSucceeded
Test-NetConnection iame.ap.inalfa.local -Port 8443 | Select-Object ComputerName,TcpTestSucceeded
```

判据：两台机器三个端口全部 `True`。只有服务器本机能解析、或只在 hosts 文件里加了解析，都不算通过。

---

## 2. 证书核验（已完成，记录在案）

### 2.1 文件与核验方式

- 文件：`IRSCNKettle01.pfx`，5,891 字节，DER 编码 PKCS#12 v3；SHA256 见第 0 章。
- 核验方式：PowerShell `X509Certificate2Collection.Import` + `EphemeralKeySet`（私钥只在内存，不落盘、不导出）。本机无 openssl，核验不依赖它。
- 口令按约定来源取得，未写入任何文档、脚本或日志。

（续签或换新文件时，复用下面这段脚本重跑一次。）

```powershell
$pfx = 'C:\certs\IRSCNKettle01.pfx'
$sec = Read-Host 'PFX 口令' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
try {
    $col = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2Collection
    $col.Import($pfx, $plain, 'EphemeralKeySet')
    "条目数: $($col.Count)"
    foreach ($c in $col) {
        "----"
        "Subject   : $($c.Subject)"
        "Issuer    : $($c.Issuer)"
        "NotBefore : $($c.NotBefore.ToString('yyyy-MM-dd HH:mm:ss'))"
        "NotAfter  : $($c.NotAfter.ToString('yyyy-MM-dd HH:mm:ss'))"
        "HasPrivateKey: $($c.HasPrivateKey)"
        "Thumbprint: $($c.Thumbprint)"
        foreach ($e in $c.Extensions) {
            if ($e.Oid.Value -in '2.5.29.17','2.5.29.37','2.5.29.19') { "$($e.Oid.FriendlyName): $($e.Format($false))" }
        }
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
```

### 2.2 实测记录

核验时间 2026-11-09。

| # | 项 | 实测值 |
|---|---|---|
| 1 | Subject CN | `CN=iame.ap.inalfa.local, OU=ICT, O=Inalfa-roofsystems` |
| 2 | SAN（DNS，逐条） | `DNS Name=iame.ap.inalfa.local`；`DNS Name=msia.ap.inalfa.local`；`DNS Name=blo.ap.inalfa.local`；`DNS Name=capacity.ap.inalfa.local`；`DNS Name=ieMotion.ap.inalfa.local` |
| 3 | SAN（IP，逐条） | **无（0 条）** |
| 4 | 有效期（本地时间） | `2026-11-09 10:19:32` → `2028-07-31 15:58:56` |
| 5 | 是否含私钥 | `True`，RSA 2048（RSACng）；私钥模数与证书公钥一致 |
| 6 | 证书链 | 完整 3 级，中间与根均随包提供；`X509Chain.Build=True`，无状态错误 |
| 7 | EKU | `Client Authentication (1.3.6.1.5.5.7.3.2), Server Authentication (1.3.6.1.5.5.7.3.1)` |
| 8 | 颁发者与链 | 叶子 `CN=iame.ap.inalfa.local, OU=ICT, O=Inalfa-roofsystems` → 中间 `CN=ap-SRV-APSH-PKI-01-CA-1, DC=ap, DC=inalfa, DC=local` → 根 `CN=INALFA-IRSPKIROOT01-CA, DC=inalfa, DC=local`（自签，至 2030-10-12） |

其它：序列号 `5500000FF28EF9487ABA983FD8000000000FF2`，指纹 `A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A`，签名算法 `sha256RSA`。

### 2.3 判定

| 门槛 | 结果 |
|---|---|
| SAN 含 `iame.ap.inalfa.local` | 通过 |
| SAN 含 `IP:172.26.2.203` | 不通过（方案 B 下不再需要，切域名后所有客户端都走域名） |
| 私钥存在且配对 | 通过 |
| 链完整（根 + 中间随包） | 通过 |
| EKU 含 Server Authentication | 通过 |
| 有效期 | 通过（当前有效；`NotAfter` 与中间 CA 到期日相同，到期必须整体重签，无法只续叶子） |

结论：**可用于本次单批切换**。唯一约束是切换后所有客户端（两个应用、kcadm、巡检脚本、用户书签）都必须改走 `iame.ap.inalfa.local`，不能再用 IP。

---

## 3. 证书落地：keytool 转 PKCS12（本机唯一主线）

### 3.1 为什么不用 PEM

本机已实测**没有 openssl**（`C:\Program Files\Git\usr\bin\openssl.exe` 也不存在），而 PowerShell 5.1 的 .NET Framework 没有私钥 PEM 导出 API。用 PEM 路线必须先装 openssl 或换 PS7，属于给自己加步骤。keytool 随 JDK 天然存在，且 PFX 本身就是 PKCS12，转换零成本。

| 方式 | 本机可行性 | 结论 |
|---|---|---|
| PKCS12 keystore（`https-key-store-*`） | 只需 `keytool`，已具备 | **主线** |
| PEM（`https-certificate-file` / `https-certificate-key-file`） | 需 PS7 或装 openssl | 备选，见 3.6 |

### 3.2 先看清 PFX 里的别名

```powershell
$env:JAVA_HOME = '<以 NSSM AppEnvironmentExtra 里的值为准>'
$kt = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
& $kt -list -v -keystore C:\certs\IRSCNKettle01.pfx -storetype PKCS12 -storepass '<PFX口令>'
```

判据：输出里有一行 `Alias name:`（记下来），该条为 `Entry type: PrivateKeyEntry`，且 `Certificate chain length: 3`。若只有 `trustedCertEntry`，说明 PFX 没有私钥，停止。

### 3.3 转成 Keycloak 用的 keystore

```powershell
& $kt -importkeystore `
  -srckeystore C:\certs\IRSCNKettle01.pfx -srcstoretype PKCS12 -srcstorepass '<PFX口令>' -srcalias '<3.2 记下的别名>' `
  -destkeystore C:\keycloak\conf\keycloak-ssl.p12 -deststoretype PKCS12 `
  -deststorepass '<keystore 新口令>' -destkeypass '<同上>' -destalias keycloak-tls
```

判据（必须复核，不能只看命令成功）：

```powershell
& $kt -list -v -keystore C:\keycloak\conf\keycloak-ssl.p12 -storetype PKCS12 -storepass '<keystore 新口令>'
```

- `Alias name: keycloak-tls`、`Entry type: PrivateKeyEntry`、`Certificate chain length: 3`；
- SAN 行含 `iame.ap.inalfa.local`；
- 有效期与 2.2 一致。

### 3.4 改 `keycloak.conf`

```powershell
# 先备份（P7）
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$bk = "C:\keycloak\conf\backup-$ts"
New-Item -ItemType Directory -Path $bk | Out-Null
Copy-Item C:\keycloak\conf\keycloak.conf, C:\keycloak\conf\server.crt.pem, C:\keycloak\conf\server.key.pem -Destination $bk
Get-FileHash $bk\server.crt.pem, $bk\server.key.pem -Algorithm SHA256 | Out-File "$bk\manifest.txt"
notepad C:\keycloak\conf\keycloak.conf
```

PEM 两行必须删除或整体注释（不能与 keystore 三行并存）；同时把 `hostname` 改成域名：

```
# https-certificate-file=C:/keycloak/conf/server.crt.pem
# https-certificate-key-file=C:/keycloak/conf/server.key.pem
https-key-store-file=C:/keycloak/conf/keycloak-ssl.p12
https-key-store-type=PKCS12
hostname=iame.ap.inalfa.local
```

口令不写进配置文件，走 NSSM 环境变量（优先级高于配置文件）：

```powershell
# 整行覆盖，必须把原有 JAVA_HOME、KC_DB_PASSWORD 一起写回，否则服务起不来
nssm set <服务名> AppEnvironmentExtra "JAVA_HOME=<原值>" "KC_DB_PASSWORD=<原值>" "KC_HTTPS_KEY_STORE_PASSWORD=<keystore 新口令>"
nssm get <服务名> AppEnvironmentExtra
```

### 3.5 备选：PEM 路线（需 PS7 或装 openssl）

不推荐，仅在必须保持 PEM 模式时使用：

- 证书链 PEM：PowerShell 5.1 可导出（见 4.1 的同类脚本，把全部证书按"叶子 → 中间 → 根"写出即可）；
- 私钥 PEM：只能在 PowerShell 7 上 `$rsa.ExportPkcs8PrivateKeyPem()`，或在装有 openssl 的机器上 `openssl pkcs12 -nocerts -nodes`；
- 落位后 `keycloak.conf` 用 `https-certificate-file` / `https-certificate-key-file` 指向两个文件，`hostname` 同样改成域名。

---

## 4. 应用侧信任包：根 + 中间合并 PEM

两个应用的 OIDC 客户端走 Python `urllib`，信任来源是 `SSL_CERT_FILE`，**不读 Windows 证书存储**，而 `SSL_CERT_FILE` 是"替换"不是"追加"。

### 4.1 导出根与中间（PowerShell，不依赖 openssl）

```powershell
$pfx = 'C:\certs\IRSCNKettle01.pfx'
$col = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2Collection
$col.Import($pfx, '<PFX口令>', 'EphemeralKeySet')

$sb = New-Object System.Text.StringBuilder
foreach ($c in ($col | Where-Object { -not $_.HasPrivateKey })) {
    [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----')
    [void]$sb.AppendLine([Convert]::ToBase64String($c.RawData, 'InsertLineBreaks'))
    [void]$sb.AppendLine('-----END CERTIFICATE-----')
}
$sb.ToString() | Set-Content C:\certs\inalfa-ca-chain.pem -Encoding ascii
(Select-String -Path C:\certs\inalfa-ca-chain.pem -Pattern 'BEGIN CERTIFICATE').Count
```

判据：块数 = 2（中间 `ap-SRV-APSH-PKI-01-CA-1` + 根 `INALFA-IRSPKIROOT01-CA`）。私钥条目 `HasPrivateKey=True` 已被过滤，不会写进文件。

### 4.2 合并公共根（否则其它 HTTPS 调用会连带失败）

```powershell
python -c "import ssl; print(ssl.get_default_verify_paths().cafile)"
Get-Content C:\certs\inalfa-ca-chain.pem, '<上一条输出的 cacert.pem 路径>' | Set-Content C:\sso\conf\ca-bundle.pem -Encoding ascii
```

判据：`ca-bundle.pem` 内除 2 个企业 CA 块外，还有公共根块（块数远大于 2）。

> 过渡技巧：若想**窗口前**就把 `SSL_CERT_FILE` 换掉、避免窗口内多一次应用重启，可在这个包里额外并入**旧自签证书** `C:\keycloak\conf\server.crt.pem`（切换前它就存在）。这样切换前后两个证书都被信任，应用可以在窗口前改完并重启，窗口内少两步。

### 4.3 只放叶子 / 只放根分别会怎样

| 包内容 | 现象 | 原因 |
|---|---|---|
| 只放叶子（Keycloak 服务器证书） | 现在能通；**续签或换证书当天立即** `CERTIFICATE_VERIFY_FAILED` | 叶子被当成信任锚，链不参与校验，证书一换锚点就失效 |
| 只放根 | 通常能通（服务端会把中间证书一起发，我们的 keystore 已含 3 级链）；若出现 `unable to get local issuer certificate`，说明服务端没发中间 | 缺中间是**服务端发送问题**，不是客户端缺根 |
| 只放根/只放叶子，不与公共根合并 | 登录能通，但应用其它 HTTPS 外调（邮件、外部接口）报 `CERTIFICATE_VERIFY_FAILED` | `SSL_CERT_FILE` 替换了默认根集合 |
| 根 + 中间 + 公共根（推荐） | 全部正常 | — |

---

## 5. 单批窗口时间线

### 5.1 时间线（耗时均为预估，实际以现场为准）

| 步 | 动作 | 预估 | 失败即回退到 |
|---|---|---|---|
| T-1 | 做完第 1 章 P1–P9；client 新 URI 已提前追加；两份 PEM、keystore、备份、应用配置文本全部就位 | 提前 1–2 天 | 不满足就不进窗口 |
| 1 | `nssm stop <服务名>` | 1 分钟 | `nssm start` 恢复原状 |
| 2 | 放置 `keycloak-ssl.p12`、改 `keycloak.conf`（证书三行 + `hostname`）、改 NSSM 环境变量 | 2 分钟 | 还原 `backup-<时间戳>` 里的 `keycloak.conf` 与 `AppEnvironmentExtra` |
| 3 | `kc.bat build`（校验 conf 写法，未知选项会直接报错） | 1 分钟 | 修 conf；退出码非 0 不继续 |
| 4 | `nssm start`，看日志与 9000 健康检查 | 2–3 分钟 | 见第 9 章回滚；起步失败按第 10 章对照表 |
| 5 | 验证证书与 issuer（第 7.1–7.2 步） | 1 分钟 | 证书不对 → 换回旧 PEM 重启（约 4 分钟）；issuer 不对 → 改回 `hostname` 重启 |
| 6 | MSIA：粘贴预热好的 `[oidc]` 段，重启服务 | 2–3 分钟 | 还原两键重启（约 3 分钟） |
| 7 | BOL：粘贴预热好的 `[oidc]` 段，重启服务 | 2–3 分钟 | 同上 |
| 8 | 两个应用各走一次真实登录；`kcadm get realms`；巡检脚本跑通 | 5 分钟 | 见第 10 章 |
| 9 | 记录变更（issuer 前后值、指纹、备份目录、执行人） | 2 分钟 | — |

**总停机区间（预估）**：从第 1 步停 Keycloak 到第 7 步两个应用改完重启，**登录链路中断 10–20 分钟**；建议预留 30 分钟窗口，另留 30 分钟观察。

### 5.2 登录必然中断的那一段

第 1 步到第 7 步之间：Keycloak 已按域名宣告 issuer，而任一应用仍按 IP 校验 → 该应用登录必失败（`id_token iss 不匹配` 或 503）。这不是故障，是窗口内的正常空窗。

压缩空窗的四个做法：

1. 第 6/7 步的配置**先在文本文件里写好**，窗口内只做"粘贴 + 保存 + 重启"；
2. client 的新 redirect URI / `webOrigins` 在 T-1 提前追加，窗口内不再动 Keycloak 控制台；
3. `SSL_CERT_FILE` 在 T-1 提前改为含"旧自签 + 新 CA"的合并包（见 4.2 过渡技巧），窗口内不必再改、不必再重启应用；
4. 两个应用的重启命令提前写好，必要时并行执行（若两者互不依赖）。

### 5.3 依赖顺序（不可颠倒）

DNS/A 记录 → 应用按域名可达 → 应用信任新 CA → client 白名单 → Keycloak `hostname` → 应用 `issuer` + `redirect_uri`。前四项都可以在窗口前完成，只有后两项必须在窗口内。

---

## 6. 三个系统的最终配置（粘贴即用）

### 6.1 Keycloak `C:\keycloak\conf\keycloak.conf`

```
hostname=iame.ap.inalfa.local
https-port=8443
https-key-store-file=C:/keycloak/conf/keycloak-ssl.p12
https-key-store-type=PKCS12
# https-certificate-file / https-certificate-key-file 必须注释或删除
```

NSSM 环境变量：`JAVA_HOME`（原值）、`KC_DB_PASSWORD`（原值）、`KC_HTTPS_KEY_STORE_PASSWORD`（keystore 口令）。

### 6.2 MSIA（`config.ini` 的 `[oidc]` 段，或环境变量 `OIDC_ISSUER`）

```
issuer = https://iame.ap.inalfa.local:8443/realms/inalfa
redirect_uri = http://iame.ap.inalfa.local:8078/api/auth/oidc/callback
```

### 6.3 BOL（`db_config.ini` 的 `[oidc]` 段）

```
issuer = https://iame.ap.inalfa.local:8443/realms/inalfa
redirect_uri = http://iame.ap.inalfa.local:8090/api/auth/oidc/callback/
```

> 两个应用的 `validate_config` 要求 `issuer` 主机与 `redirect_uri` 主机逐字符一致；本方案三个系统都挂在 `iame.ap.inalfa.local`，只是端口不同，条件自然满足。
> BOL 的 `db_config.ini` 有源码版与 exe 版两处，改**实际生效**的那份（exe 同目录），否则改完重启无效。

### 6.4 Keycloak client（窗口前追加）

```powershell
$kc = 'C:\keycloak\bin\kcadm.bat'
& $kc config credentials --server https://172.26.2.203:8443 --realm master --user <管理员> --truststore C:\keycloak\conf\kcadm-truststore.jks --truststore-password changeit

& $kc get clients -r inalfa -q clientId=msia-prod --fields id,clientId,redirectUris,webOrigins
& $kc get clients -r inalfa -q clientId=bol-prod  --fields id,clientId,redirectUris,webOrigins

# 数组字段是整体替换：旧值必须一起写回
& $kc update clients/<msia-prod 的 id> -r inalfa `
  -s 'redirectUris=["http://172.26.2.203:8078/api/auth/oidc/callback","http://iame.ap.inalfa.local:8078/api/auth/oidc/callback"]' `
  -s 'webOrigins=["http://172.26.2.203:8078","http://iame.ap.inalfa.local:8078"]'

& $kc update clients/<bol-prod 的 id> -r inalfa `
  -s 'redirectUris=["http://172.26.2.203:8090/api/auth/oidc/callback/","http://iame.ap.inalfa.local:8090/api/auth/oidc/callback/"]' `
  -s 'webOrigins=["http://172.26.2.203:8090","http://iame.ap.inalfa.local:8090"]'
```

### 6.5 域名化后要跟着改的口径

| 项 | 改成 | 不改的后果 |
|---|---|---|
| `kcadm` truststore | 删旧别名 `keycloak-local`，导入 `C:/certs/inalfa-ca-chain.pem` 里两张 CA（见 6.6） | `PKIX path building failed`，所有批量脚本失败 |
| 巡检/采集脚本 `-Server` | `https://iame.ap.inalfa.local:8443` | 按 IP 调 discovery 报证书主机名不匹配 |
| 用户书签 | 新域名 | 旧书签能开页面，但登录会跳新域名重登一次 |

### 6.6 kcadm truststore 换锚

```powershell
$kt = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
& $kt -list -keystore C:\keycloak\conf\kcadm-truststore.jks -storepass changeit
& $kt -delete -alias keycloak-local -keystore C:\keycloak\conf\kcadm-truststore.jks -storepass changeit
& $kt -importcert -alias inalfa-ca-intermediate -file C:\certs\ca-intermediate.cer -keystore C:\keycloak\conf\kcadm-truststore.jks -storepass changeit -noprompt
& $kt -importcert -alias inalfa-ca-root -file C:\certs\ca-root.cer -keystore C:\keycloak\conf\kcadm-truststore.jks -storepass changeit -noprompt
& $kt -list -keystore C:\keycloak\conf\kcadm-truststore.jks -storepass changeit
```

`ca-intermediate.cer` / `ca-root.cer` 从 `inalfa-ca-chain.pem` 里按块拆出（第一块是中间，第二块是根）。

---

## 7. 验证（全过才算切换成功）

### 7.1 对端看到的是不是新证书

```powershell
$h='iame.ap.inalfa.local'; $p=8443
$tcp = New-Object System.Net.Sockets.TcpClient($h,$p)
$ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(),$false,({param($s,$c,$ch,$e) $true}))
$ssl.AuthenticateAsClient($h)
$c = [System.Security.Cryptography.X509Certificates.X509Certificate2]$ssl.RemoteCertificate
$c.Subject; $c.Issuer; $c.NotBefore; $c.NotAfter
($c.Extensions | Where-Object { $_.Oid.FriendlyName -match 'Subject Alternative' } | ForEach-Object { $_.Format($false) })
$ssl.Dispose(); $tcp.Close()
```

判据：Subject = `CN=iame.ap.inalfa.local, OU=ICT, O=Inalfa-roofsystems`，Issuer = 企业 CA，SAN 含 5 条域名。

### 7.2 issuer 回显

```powershell
(Invoke-RestMethod 'https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration').issuer
```

判据：**逐字符**等于 `https://iame.ap.inalfa.local:8443/realms/inalfa`。多一个端口、少一个尾斜杠都算失败。

### 7.3 应用与工具

| 检查 | 命令 / 方式 | 判据 |
|---|---|---|
| MSIA 登录 | 浏览器走完整流程 | 跳转到 `iame.ap.inalfa.local:8443` 授权页，回调后进入业务页 |
| BOL 登录 | 同上 | 同上，回调带尾斜杠 |
| Keycloak 事件 | 控制台 Events | 出现对应 `LOGIN` |
| kcadm | `& $kc get realms -r inalfa` | 返回结果，无 PKIX 报错 |
| 应用信任 | 以各服务账号跑 TLS 探测 | `TLS OK` |
| 管理端口 | `Invoke-WebRequest http://127.0.0.1:9000/health/ready` | `StatusCode=200` |

---

## 8. 用户会看到什么（先告知，别当成故障）

**1. 所有人都要重新登录一次。** 浏览器按站点隔离存储，主机名从 `172.26.2.203` 换成 `iame.ap.inalfa.local` 后，旧登录状态在新地址取不到。判断标准：登录一次后能正常进入业务页、后续不再反复弹登录就是正常；反复跳回登录页或报 401/证书错误，才按第 9 章查。

**2. 只有能解析该域名的电脑才打得开。** 未配 DNS 的机器打开 `http://iame.ap.inalfa.local:8078` 会显示"无法访问此网站"，而服务器本机正常。判据是第 1 章 P2 的两台不同网段机器；服务器本机能解析不算数。

**3. 旧 IP 书签仍能打开页面**，但点登录会跳到新域名并重新登录一次——预期行为。

---

## 9. 回滚（单批，按序执行）

### 9.1 触发条件

出现以下任一情况且 10 分钟内定位不到原因：服务起不来、两个应用全部登录失败、issuer 与应用配置对不上。

### 9.2 顺序：先退 issuer，再退应用，最后才决定证书

```powershell
# 第 1 步：Keycloak 退回 IP 口径（约 3–4 分钟）
nssm stop <服务名>
# 编辑 C:\keycloak\conf\keycloak.conf：hostname=172.26.2.203
$env:JAVA_HOME = '<原值>'
& C:\keycloak\bin\kc.bat build
nssm start <服务名>
Start-Sleep -Seconds 30
(Invoke-RestMethod 'https://172.26.2.203:8443/realms/inalfa/.well-known/openid-configuration').issuer
```

```powershell
# 第 2 步：两个应用还原 issuer 与 redirect_uri 旧值，各自重启（约 5–10 分钟）
# MSIA: issuer = https://172.26.2.203:8443/realms/inalfa
#       redirect_uri = http://172.26.2.203:8078/api/auth/oidc/callback
# BOL : redirect_uri = http://172.26.2.203:8090/api/auth/oidc/callback/
```

第 3 步：**只在确认新证书本身有问题时**才换回旧证书（约 4–5 分钟）：

```powershell
$bk = 'C:\keycloak\conf\backup-<时间戳>'
nssm stop <服务名>
# 还原 keycloak.conf（其中仍是 PEM 三行 + 旧 hostname）
Copy-Item "$bk\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force
# 还原 AppEnvironmentExtra：去掉 KC_HTTPS_KEY_STORE_PASSWORD，保留 JAVA_HOME / KC_DB_PASSWORD
& C:\keycloak\bin\kc.bat build
nssm start <服务名>
```

### 9.3 各步判据

| 步 | 判据 | 耗时（预估） |
|---|---|---|
| 退 `hostname` | discovery 回显恢复 `https://172.26.2.203:8443/realms/inalfa` | 3–4 分钟 |
| 退应用配置 | 两个应用点登录从 503 恢复为 302 跳转 IP 授权页 | 5–10 分钟 |
| 换回旧证书 | 探针取回的指纹等于 `backup-<时间戳>` 里旧证书指纹 | 4–5 分钟 |

> 若只是域名切换出问题、证书本身正常，**第 3 步不要做**：新旧证书都可用，换回旧自签反而让应用重新面对旧的信任配置。回滚后把 `hostname` 改动记入变更记录，重新排期。

---

## 10. 失败对照表

| 现象 | 原因 | 排查 |
|---|---|---|
| 服务起不来，日志 `Keystore was tampered with, or password was incorrect` | keystore 口令不一致 | `nssm get <服务名> AppEnvironmentExtra` 核对 `KC_HTTPS_KEY_STORE_PASSWORD`；用 keytool 单独打开 p12 |
| 日志 `Failed to load private key` / `Invalid keystore format` | PEM 行与 keystore 行并存，或文件不是 PKCS12 | 检查是否残留 `https-certificate-file`；确认 `keycloak-ssl.p12` 存在且非 0 字节 |
| 浏览器 `NET::ERR_CERT_COMMON_NAME_INVALID` | 访问的主机名不在 SAN | 7.1 探针看 SAN；只能用 `iame.ap.inalfa.local` 访问 |
| 浏览器 `ERR_CERT_AUTHORITY_INVALID` | 客户端不信任企业根 | 域内机器确认 GPO 已分发根证书；非域机器需手工安装 |
| 应用 `CERTIFICATE_VERIFY_FAILED` | `SSL_CERT_FILE` 未更新或未重启 | 变量是否进了服务环境、运行账号能否读 `ca-bundle.pem` |
| 应用 `unable to get local issuer certificate` | 信任包缺中间，或服务端未发中间 | 4.1 块数应为 2；`keytool -list` 链长应为 3 |
| 应用 503 `OIDC 配置不完整` | `issuer` 主机与 `redirect_uri` 主机不一致 | 6.2/6.3 两处主机都必须是 `iame.ap.inalfa.local` |
| 回调后登录失败、Keycloak 日志正常 | `iss` 与配置不一致 | 7.2 回显逐字符比对 |
| `kcadm` 报 `PKIX path building failed` | truststore 还是旧自签 | 6.6 删旧别名、导新 CA |
| 第二批按 IP 访问报 `hostname '172.26.2.203' doesn't match` | 新证书无 IP SAN | 全部改走域名；脚本 `-Server` 一并改 |
| `kc.bat build` 报 `Unrecognized option` | 抄了 26.x 的参数 | 对照现有 conf，25.0.6 不接受 `hostname-strict-https` 等已移除项 |

---

## 11. 完成判据

- [ ] P1–P9 全部完成，两台不同网段机器三端口全通
- [ ] `keycloak-ssl.p12` 链长 3、别名 `keycloak-tls`、SAN 含 `iame.ap.inalfa.local`
- [ ] `inalfa-ca-chain.pem` 两块，`ca-bundle.pem` 含公共根
- [ ] 备份目录含 `keycloak.conf` + 旧证书 + `manifest.txt`
- [ ] `kc.bat build` 退出码 0；服务 `Running`；9000 健康检查 200
- [ ] 7.1 探针显示新证书与新 SAN；7.2 回显为域名口径
- [ ] MSIA、BOL 各一次真实登录通过，Keycloak 有 `LOGIN`
- [ ] `kcadm get realms` 成功；`kcadm-truststore.jks` 无 `keycloak-local`
- [ ] 两个应用 `SSL_CERT_FILE` 指向新包且已重启
- [ ] 脚本 `-Server` 已切域名；用户已通知更新书签
- [ ] 变更记录：issuer 前后值、证书指纹、备份目录、停机时段、执行人

---

## 12. 已知项与纪律

| 项 | 说明 |
|---|---|
| `blo.ap.inalfa.local` 疑似 `bol` 笔误 | 仅记录。本方案两个应用都走 `iame.ap.inalfa.local` 的 8078/8090，不受影响，不要求重签；若将来 BOL 单独用主机名再处理 |
| 有效期与中间 CA 同日到期 | 2028-07-31，届时必须整体重签，不能只续叶子 |
| 口令纪律 | 不写入文档/脚本/日志；私钥不导出、不落盘；核验用 `EphemeralKeySet`，进程结束即释放 |
| 现场确认项 | NSSM 服务名、`JAVA_HOME`、服务运行账号、MSIA/BOL 服务名与配置生效路径 |

---

## 附录 A. 作废：原「第一批：只换证书」

> **作废，不执行。** 原因：本证书 SAN 无 `IP:172.26.2.203`，而第一批要求 issuer 保持 `https://172.26.2.203:8443/realms/inalfa`，客户端按 IP 校验证书主机名，换上去后 MSIA/BOL 登录、`kcadm`、巡检脚本全部失败。现按方案 B 单批执行，本节内容仅作追溯保留；其中"备份 → 停服 → `kc.bat build` → 启动"的步骤已被第 5 章复用。

原案要点（已不再适用）：

- 第一批只换 `C:\keycloak\conf` 下证书文件（或 keystore），`hostname` 不动，issuer 保持 IP 口径；
- 停机 3–10 分钟，回滚点仅 Keycloak 侧备份目录，≤5 分钟；
- 第二批再切域名与 issuer，停机 30–60 分钟，回滚需同时撤三个系统；
- 两批之间可间隔任意时长，但不要合并成一次窗口。

原案作废后，"两批不要合并"的约束随之失效；本手册第 5 章的 30 分钟窗口即原两批的合并形态，回滚风险已由第 9 章的分步顺序对冲。
