# 方案 2 实施手册：三应用 HTTPS 化 + IIS 反向代理

> 状态：**2026-11-11 已执行完毕，方案 2 主体完成**。三个应用与 Keycloak 全部在 https 上，三条登录链路（8078 / 8090 / 8008）实测通过。本文保留为执行记录 + 复核手册。
> 起点：回滚后的 IP 口径（Keycloak `https://172.26.2.203:8443` + 自签证书，三应用 `http://172.26.2.203:8078 / :8090 / :8000`）。
> 终态：主机名统一 `iame.ap.inalfa.local`，Keycloak 用正式证书，三应用公网端口全 HTTPS（TLS 在 IIS 终结）。

## 最终拓扑（验收口径）

| 组件 | 应用侧 | IIS 反代 | 证书 / 参数 |
|---|---|---|---|
| Keycloak | — | — | `https://iame.ap.inalfa.local:8443`；`hostname=iame.ap.inalfa.local`；`https-key-store-file=C:/certs/iame.p12`；`https-key-store-type=PKCS12`；PEM 两行已注释；证书 `CN=iame.ap.inalfa.local`，`Issuer=CN=ap-SRV-APSH-PKI-01-CA-1`，到期 2028-07-31 |
| MSIA | `host=127.0.0.1`、`port=18078` | `https *:8078` → `http://127.0.0.1:18078/` | `issuer` / `redirect_uri` 均为域名 |
| BOL | `--host 127.0.0.1 --port 18090`（NSSM `AppParameters`） | `https *:8090` → `http://127.0.0.1:18090/` | `AppEnvironmentExtra="SSL_CERT_FILE=C:\certs\ca-bundle.pem"`；`db_config.ini [oidc]` 的 `issuer` / `redirect_uri` 为域名 + 8090 |
| Capacity | 仍 `0.0.0.0:8000`（写死） | `https *:8008` → `http://127.0.0.1:8000/` | `OIDC_ISSUER` 改域名，其余 8008 地址不变 |

三张 IIS 站点统一使用指纹 `A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A`，`appid={4dc3e181-e14b-4a21-b022-59fc669b0914}`。

## 执行顺序与依赖（决定中断窗口长度）

```text
0 前置（离线完成，无业务影响）
   └─ BOL 新版本整目录在此段交付（二选一：预置 `C:\Temp\bol-new\BOLServer`，或已就地替换并在同盘留变更前整目录备份）
A 安装（无业务影响）
   └─ IIS → URL Rewrite → ARR → iisreset → 开总开关
B 反代就绪（预演用临时端口 18078/18090/18000，仍无业务影响）
   └─ 导入证书 → 建站点与 web.config → 用临时端口验证 https→127.0.0.1:真实端口 通
C 窗口（**2026-11-11 已执行完成**；业务中断约 40 分钟，含 keystore 口令排查）
   ├─ C0 核对 Keycloak client 九项 https URI（只读，约 5 分钟）
   ├─ 停三个应用 → C1 切 Keycloak（含 keystore 口令修正）→ C2.1 改三份 issuer/redirect → C2.3 改绑回环
   ├─ C2.4 起三个应用
   ├─ C3 下预演绑定、改用正式端口 8078/8090/8008（应用侧占 18078/18090/8000）
   └─ C4 核 302（确认 client 的 https redirect_uri 已生效）
D 端到端验收（三条登录链路通过）
E 收尾
```

> 上文是「0 前置」到「E 收尾」的完整路径，已全部走完。C 段各步骤保留原样，末尾补「实际执行顺序与偏差」。

**必须遵守的三条顺序**：

1. **站点先通、再改 `redirect_uri`**。反代没通就改 `redirect_uri`，登录会直接断且无法自证。
2. **应用先改绑 `127.0.0.1`、再让 IIS 绑同一端口**。应用占着 `0.0.0.0:<端口>` 时，IIS 绑同一端口会抢不到监听（见「常见失败现象对照」第 8 条）。本次因此把 MSIA / BOL 的内部端口换到 18078 / 18090，见 C 段偏差记录。
3. **不能只切一个应用**。MSIA 会校验 `oidc.issuer` 与 `oidc.redirect_uri` 的主机名必须一致，只把一个应用切到 https 必然失败（2026-11-11 已发生并回退）。三个应用必须与 Keycloak 切域名在同一窗口内完成，顺序固定为 **Keycloak → 三份 issuer/redirect → 应用绑回环**。

---

# 0. 前置条件与开工判据

## 0.1 安装包到位并校验签名

```powershell
New-Item -ItemType Directory -Path 'C:\Temp\iis-setup' -Force | Out-Null
# 把 rewrite_amd64_en-US.msi 与 requestRouter_amd64.msi 放进 C:\Temp\iis-setup

Get-AuthenticodeSignature 'C:\Temp\iis-setup\rewrite_amd64_en-US.msi' |
    Select-Object Status, @{ n = 'Signer'; e = { $_.SignerCertificate.Subject } }
Get-AuthenticodeSignature 'C:\Temp\iis-setup\requestRouter_amd64.msi' |
    Select-Object Status, @{ n = 'Signer'; e = { $_.SignerCertificate.Subject } }
```

判据：两条都 `Status = Valid` 且 `Signer` 含 `O=Microsoft Corporation`。任一不满足 → 停，换包。

失败先看：`HashMismatch` 说明包被改过；`NotSigned` 说明是第三方重打包。

单独回退：无（只读）。

## 0.2 BOL 新版本交付（窗口前必须完成，二选一）

在 BOL 构建机（不是生产服务器）改 `BOL管理系统\backend\bol_platform\settings_prod.py`，在 `ALLOWED_HOSTS` 附近加一行：

```python
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

按现有 PyInstaller 打包流程重新生成**整个输出目录**（`dist\bol-20261110-1812`：`BOLServer.exe`、`_internal\`、`staticfiles\` 等）。整目录怎么交付，两条路径**任选其一**，都算合格：

| 方案 | 做法 | 窗口内动作 |
|---|---|---|
| **甲：预置待换** | 新整目录放 `C:\Temp\bol-new\BOLServer`，运行目录仍是旧版 | C2.2 执行整目录替换 |
| **乙：已就地替换** | 新整目录已直接铺到运行目录 `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer`，变更前整目录备份在**同盘同父目录**（现场为 `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08`） | C2.2 不再动文件，只做配置变更与重启 |

**通用判据（两种方案都查运行目录）**：

```powershell
$run = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer'
Get-FileHash "$run\BOLServer.exe" -Algorithm SHA256 | Select-Object Hash
Test-Path "$run\_internal"
(Get-ChildItem "$run\_internal" | Measure-Object).Count
Test-Path "$run\db_config.ini"
Select-String -Path "$run\db_config.ini" -Pattern '^issuer'
```

- 运行目录 `BOLServer.exe` 的 SHA256 前 8 位为 `C28E23AA`（完整值 `C28E23AAA6F1A2EC943A80B70ED5C1D53344CFCFD0D609C62484609EA7EFC227`，对应 `dist\bol-20261110-1812`）；
- `_internal` 存在且非空；
- `db_config.ini` 存在，且 `issuer` 仍是 IP 口径（指向 `172.26.2.203`；改成域名是 C2.1 的事，此段不该已经变）。

**方案甲另查中转目录**：

```powershell
$new = 'C:\Temp\bol-new\BOLServer'
(Get-ChildItem $new | Measure-Object).Count
Test-Path "$new\_internal"
```

判据：条目数 ≥ 3（至少有 `BOLServer.exe`、`_internal`、`staticfiles`），`_internal` 非空。

**方案乙另查变更前备份**：

```powershell
$old = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08'
Get-FileHash "$old\BOLServer.exe" -Algorithm SHA256 | Select-Object Hash
Test-Path "$old\db_config.ini"
```

判据：`$old\BOLServer.exe` 的哈希**不是** `C28E23AA…`（确认是变更前那一版）、`$old\db_config.ini` 存在。备份目录命名规范 `BOLServer_pre-planb-<yyyyMMdd>`；现场已建的 `BOLServer_08` 可沿用，把 `BOLServer_08` 这个实际名字记入实施记录即可。

两条方案任一判据不满足，**C2 不能开始**——窗口内不允许现场打包。

两条禁止：

- **禁止只替换 `BOLServer.exe`**：这次改动连带 `_internal\base_library.zip` 变化，只换 exe 会与旧 `_internal` 版本错配，轻则启动异常，重则直接起不来。
- **禁止用 `robocopy /MIR` 把新目录镜像到运行目录**：镜像会删掉新包里没有的 `db_config.ini`（那是运行目录独有的，C2.1 刚改过）。

单独回退：方案甲删 `C:\Temp\bol-new` 即可，不影响生产；方案乙不产生中转件，无需回退（真要退版本走 0.3 / C2.2 的备份目录）。

## 0.3 备份点

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Dump -App All
$bk = 'C:\Services\rollback\baseline-<上一步输出的时间戳>'
Copy-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' "$bk\msia-config.ini" -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' "$bk\bol-db_config.ini" -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' "$bk\capacity-env" -Force
# BOL 整目录备份：方案乙已在同盘同父目录留了变更前副本（如 BOLServer_08），本行可跳过；
# 方案甲、或想再在 $bk 下留一份时执行（备选位置）
Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer' "$bk\bol-dir" -Recurse -Force
Copy-Item C:\keycloak\conf\keycloak.conf "$bk\keycloak.conf" -Force
icacls $bk /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F"
Get-ChildItem $bk | Select-Object Name, Length
```

判据：`$bk` 内除 `bol-dir` 外五项都在且非空；BOL 整目录备份两种来源有其一即可——`$bk\bol-dir`，或方案乙的同盘备份（`BOLServer_pre-planb-<yyyyMMdd>` / 现场 `BOLServer_08`），后者必须含 `BOLServer.exe` 与 `db_config.ini`，且 exe 哈希为变更前版本。`.reg` 含明文口令，`icacls` 必须执行。

单独回退：无（只读备份）。

### 0.3.1 窗口前重新打一次备份点（C0 之后、进 C 段之前）

`keycloak.conf` 与三份应用配置在演练和 C0 期间都动过，上面 `$bk` 可能已不代表"窗口前那一瞬"。进 C 段前必须再打一份**只含四个配置**的快照：

```powershell
$pw = 'C:\certs\bk-20261110-pre-window'   # 命名：bk-<yyyyMMdd>-pre-window
New-Item -ItemType Directory -Path $pw -Force | Out-Null
Copy-Item 'C:\keycloak\conf\keycloak.conf' "$pw\keycloak.conf" -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' "$pw\bol-db_config.ini" -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' "$pw\msia-config.ini" -Force
Copy-Item 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' "$pw\capacity-env" -Force
Get-ChildItem $pw | Select-Object Name, Length, LastWriteTime
```

判据：四项都在且 `Length` 均大于 0，`LastWriteTime` 为当天。此目录就是 C 段局部回退时"配置回 IP 口径"的权威来源。

## 0.4 端口与防火墙现状

8078 / 8090 不变，仍由 IIS 监听；Capacity 改走 8008，需新增 8008 放行。8000 的阻断**未执行**，原入口保留（见 C2.3 ④ 待办）。先确认既有放行：

```powershell
Get-NetFirewallRule -Enabled True -Direction Inbound |
    Where-Object { $_.DisplayName -match '8078|8090|8000|8443' } |
    Get-NetFirewallPortFilter | Select-Object Protocol, LocalPort
```

判据：8078 / 8090 / 8000 三条都在（TCP）。缺哪条先补规则，再开工。Capacity 已改走 8008，放行规则 `IAME-CAPACITY-HTTPS-8008` 已建（`Enabled=True`、`Inbound`、`Allow`）；8000 的对外入口本次保留未封，对应旧 URI 需一并保留。

## 0.5 开工判据

| 项 | 判据 |
|---|---|
| 0.1 两个 MSI 签名有效 | 是 |
| 0.2 BOL 交付合格（甲：`C:\Temp\bol-new\BOLServer` 整目录；乙：运行目录已是新版 + 同盘变更前整目录备份），判据见 0.2 | 是 |
| 0.3 备份齐全（`$bk` 五项 + BOL 整目录备份有其一） | 是 |
| 0.3.1 窗口前备份点 `C:\certs\bk-<yyyyMMdd>-pre-window` 四项非空 | 是 |
| 0.4 8078 / 8090 / 8000 / 8008 入站放行 | 是 |
| 0.6 `iame-all.pem` 已追加进 `ca-bundle.pem`（块数 3→6），三应用 `SSL_CERT_FILE` 均指向它 | 是 |
| 四个服务 Running（`-Action Status -App All`） | 是 |
| 客户端能解析 `iame.ap.inalfa.local → 172.26.2.203` | 是 |

任一项不满足 → 停在原地补齐，不要进 A 段。

## 0.6 正式证书的信任链（已按现场做法完成）

切正式证书后，三个 Python 应用要校验的是**签发根 CA**，不是叶子证书。现场做法：把 `C:\certs\iame-all.pem`（叶 + 中间 + 根）追加进 `C:\certs\ca-bundle.pem`，块数由 3 变 6，三个应用统一使用 `SSL_CERT_FILE=C:\certs\ca-bundle.pem`（BOL 原先指向 `C:\keycloak\conf\server.crt.pem` 的旧自签证书，切正式证书时必须改）。

```powershell
$b = 'C:\certs\ca-bundle.pem'
"before=" + ([regex]::Matches((Get-Content $b -Raw), '-----BEGIN CERTIFICATE-----')).Count
Add-Content -Path $b -Value (Get-Content 'C:\certs\iame-all.pem' -Raw) -Encoding ASCII
"after="  + ([regex]::Matches((Get-Content $b -Raw), '-----BEGIN CERTIFICATE-----')).Count
```

判据：块数增加（现场 3 → 6）；三个应用重启后日志无 `CERTIFICATE_VERIFY_FAILED` / `idp_unreachable`，登录通过。追加前先备份（现场保留 `ca-bundle.pem.bak` / `.bak2` 一周）。

---

# A. 安装段（无业务影响）

> **若 A 段此前已完成**（IIS、URL Rewrite 2.1、ARR 3.0 已装，且 A5 模块验证、A6 总开关与白名单回读都通过），本次**不要重跑 A1–A3 的安装命令**，只跑只读确认：A1 的 `Get-WindowsFeature` / `Get-Service W3SVC`、A2 的 `appcmd list module`、A3 的「三条合并判定」、A5 与 A6 的回读。重复执行 MSI 不报错但会覆盖已有配置，还会把「本来就绪」误判成「刚装完」。

## A1 安装 IIS

```powershell
Install-WindowsFeature Web-Server -IncludeManagementTools
Get-WindowsFeature Web-Server, Web-Mgmt-Console | Select-Object Name, InstallState
Get-Service W3SVC | Select-Object Name, Status, StartType
```

判据：两个功能 `Installed`，`W3SVC` 为 `Running`。

失败先看：`Install-WindowsFeature` 报缺源 → 用 `-Source D:\sources\sxs`（挂载安装介质）。

单独回退：`Uninstall-WindowsFeature Web-Server -IncludeManagementTools`（下一段尚未开始前无风险）。

## A2 装 URL Rewrite 2.1（必须在 A1 之后）

```powershell
$log = 'C:\Temp\iis-setup\rewrite-install.log'
$p = Start-Process msiexec.exe `
        -ArgumentList "/i C:\Temp\iis-setup\rewrite_amd64_en-US.msi /qn /norestart /l*v `"$log`"" `
        -Wait -PassThru
"ExitCode = $($p.ExitCode)"

Get-Item "$env:SystemRoot\System32\inetsrv\rewrite.dll" | Select-Object Name, Length
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list module | Select-String 'Rewrite'
```

退出码判读：`0` 成功；`3010` 成功但需重启（先重启再验，不要当失败重装）；`1603` 安装过程中发生致命错误，唯一可查处是日志。

失败时先搜日志：

```powershell
Select-String -Path 'C:\Temp\iis-setup\rewrite-install.log' `
    -Pattern 'Return value 3|LaunchCondition|Installation failed' | Select-Object LineNumber, Line
```

判据：`ExitCode` 为 `0` 或 `3010`，且 `rewrite.dll` 在 `inetsrv` 下（URL Rewrite 的模块确实落在这里，与 ARR 不同）、模块列表出现 `Rewrite`。

失败先看：退出码 `1603` 且日志有 `LaunchCondition` → A1 没真正装完，回 A1 看 `InstallState`（`Available` 就是没装），不要只看「命令没报错」。

单独回退：控制面板卸载「URL Rewrite Module 2.1」。

## A3 装 ARR 3.0（必须在 A2 之后）

**顺序不能反**：URL Rewrite 是 ARR 的硬前置，ARR 安装程序在前置检查阶段就确认 `rewrite.dll` 与全局模块是否就位。

```powershell
$log = 'C:\Temp\iis-setup\arr-install.log'
$p = Start-Process msiexec.exe `
        -ArgumentList "/i C:\Temp\iis-setup\requestRouter_amd64.msi /qn /norestart /l*v `"$log`"" `
        -Wait -PassThru
"ExitCode = $($p.ExitCode)"
```

退出码判读：`0` 成功；`3010` 成功但需重启（重启后再做下面三条判定）；`1603` 安装过程中发生致命错误，看日志。

失败时先搜日志：

```powershell
Select-String -Path 'C:\Temp\iis-setup\arr-install.log' `
    -Pattern 'Return value 3|LaunchCondition|Installation failed' | Select-Object LineNumber, Line
```

判据（**三条合并判定，缺一不算装成**）：

```powershell
# ① 文件落在 ARR 自己的目录下（不是 inetsrv）
Get-ChildItem 'C:\Program Files\IIS\Application Request Routing' -Filter 'requestRouter.dll' -Recurse -ErrorAction SilentlyContinue |
    Select-Object FullName, Length

# ② 模块已注册
Import-Module WebAdministration
Get-WebGlobalModule | Where-Object { $_.Name -match 'ApplicationRequestRouting' } | Select-Object Name, Image

# ③ proxy 配置节能被读出（能返回即说明 ARR 生效，默认 enabled="false"）
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list config /section:system.webServer/proxy
```

三条全过才算装成。**不要用 `C:\Windows\System32\inetsrv\requestRouter.dll` 判断**：ARR 的模块文件通常落在 `C:\Program Files\IIS\Application Request Routing\`，`inetsrv` 下没有它不代表安装失败（依据见 `iis-arr-precheck.md` 4.5）。

失败先看：

- 退出码 `1603` 且日志出现 `LaunchCondition` → 前置条件不满足，多半是 A2 未真正装成，回 A2 重装；
- 退出码 `0` 但 ③ 报「无法识别的配置节」→ 装完没跑 A4，先 `iisreset` 再验；
- 报「需要 URL Rewrite」→ A2 未装或未注册，回 A2。

反序的具体后果：

| 反法 | 现象 |
|---|---|
| 先 ARR、后 URL Rewrite | ARR 在前置检查阶段直接失败并整包回滚：`ExitCode 1603`、日志有 `LaunchCondition`、`C:\Program Files\IIS\Application Request Routing` 目录不生成 |
| 两个都装上但顺序错开（URL Rewrite 后补装） | 表面都成功：dll 在、`proxy` 节也在，但改写规则不执行、转发不生效（`enabled=true` 时仍 502/404）；处理是先卸 ARR，再按 URL Rewrite → ARR 重装并 `iisreset` |

单独回退：控制面板卸载「Application Request Routing 3.0」，再 `iisreset`。

## A4 重载 IIS

```powershell
iisreset
```

判据：命令末尾出现「Internet 服务已成功停止/启动」。

失败先看：`W3SVC` 起不来 → 看事件查看器「系统」最近的 HTTP 错误。

单独回退：无需。

## A5 验证两个模块已注册

```powershell
Import-Module WebAdministration
Get-WebGlobalModule | Where-Object { $_.Name -match 'ApplicationRequestRouting|Rewrite' } | Select-Object Name, Image
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list module | Select-String 'ApplicationRequestRouting|Rewrite'
```

判据：出现 `ApplicationRequestRouting`（`Image` 指向 `C:\Program Files\IIS\Application Request Routing\requestRouter.dll`）和 `Rewrite`（`Image` 指向 `inetsrv\rewrite.dll`）。

失败先看：缺一个 → 对应 MSI 未装成功，或装完没跑 A4。

单独回退：卸载对应 MSI 后 `iisreset`。

## A6 打开 ARR 总开关、必要参数与转发头白名单

两组设定分属**两个不同的配置节**，命令写法也不同：

| 设定 | 真实配置节 | 设置方式 |
|---|---|---|
| `enabled` / `preserveHostHeader` / `timeout` / `reverseRewriteHostInResponseHeaders` | `system.webServer/proxy`（`overrideModeDefault="Deny"`、`allowDefinition="AppHostOnly"`） | `appcmd set config` |
| `web.config` 里 `<set>` 的每个变量都要登记（现场实际两个：`HTTP_X_FORWARDED_PROTO`、`HTTP_X_FORWARDED_FOR`） | `system.webServer/rewrite/allowedServerVariables`（属于 **URL Rewrite**，在 `sectionGroup name="rewrite"` 内） | `Add-WebConfiguration` |

`system.webServer` 下只有 `proxy` 与 `diskCache` 两个同级 section，**`allowedServerVariables` 不在 `proxy` 里**；往 `proxy` 段上挂这个集合会被当成未知属性，直接报 `Unknown attribute`。

```powershell
$appcmd = "$env:SystemRoot\System32\inetsrv\appcmd.exe"
Import-Module WebAdministration

# ① ARR 代理参数（proxy 段）
& $appcmd set config /section:system.webServer/proxy /enabled:"true" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /preserveHostHeader:"true" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /timeout:"00:05:00" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /reverseRewriteHostInResponseHeaders:"false" /commit:apphost

# ② 转发头白名单（rewrite 段，这是唯一生效的写法）
#   以 B2 写进 web.config 的 <set> 为准，有几个变量就登记几条，一个不能少
Add-WebConfiguration -PSPath 'MACHINE/WEBROOT/APPHOST' `
    -Filter 'system.webServer/rewrite/allowedServerVariables' -Value @{name='HTTP_X_FORWARDED_PROTO'}
Add-WebConfiguration -PSPath 'MACHINE/WEBROOT/APPHOST' `
    -Filter 'system.webServer/rewrite/allowedServerVariables' -Value @{name='HTTP_X_FORWARDED_FOR'}

# ③ 回读
& $appcmd list config /section:system.webServer/proxy
& $appcmd list config /section:system.webServer/rewrite/allowedServerVariables
```

判据：

- `proxy` 回读四项齐全：`<proxy enabled="true" timeout="00:05:00" preserveHostHeader="true" reverseRewriteHostInResponseHeaders="false">`；
- `allowedServerVariables` 回读的**条数与 B2 的 `<set>` 数量一致**（现场为 2 条），逐条对上：

```xml
<rewrite>
  <allowedServerVariables>
    <add name="HTTP_X_FORWARDED_PROTO" />
    <add name="HTTP_X_FORWARDED_FOR" />
  </allowedServerVariables>
</rewrite>
```

少一条的后果：整站 `HTTP Error 500.50`，正文点名缺的那个变量（`The server variable "X" is not allowed to be set.`），不是部分路径坏。补齐后**立即生效，不需要 `iisreset`**。

失败先看：

- `enabled` 仍是 `false` → 命令漏了 `/commit:apphost`；
- `allowedServerVariables` 条数少于 `<set>` 条数 → 就是 500.50 的直接原因，补齐缺的那条；
- `allowedServerVariables` 报「已存在 / duplicate collection entry」→ 正常，说明之前加过，不用重加；
- 命令没报错但回读的 `<rewrite>` 段是空的 → 加错了地方（挂到 `proxy` 上属静默不生效），按上面 ② 的写法重做；
- 不确定某个节挂在哪个 `sectionGroup` 下 → 见本节末尾的定位方法。

单独回退：`& $appcmd set config /section:system.webServer/proxy /enabled:"false" /commit:apphost`；白名单可留着不删——缺了它站点报 500.50，留着不影响其它应用。

> 配置节路径不明时怎么查：`Select-String -Path "$env:SystemRoot\System32\inetsrv\config\applicationHost.config" -Pattern 'allowedServerVariables' -Context 8, 8`，向上看最近的 `sectionGroup` 的 `name` 就是归属；完整枚举 `configSections` 的写法见 `iis-arr-precheck.md` 4.5。

---

# B. 反代就绪段（预演，仍无业务影响）

## B1 导入证书到本机存储

```powershell
$pwd = Read-Host -AsSecureString 'IRSCNKettle01.pfx 的口令'
Import-PfxCertificate -FilePath 'C:\certs\IRSCNKettle01.pfx' -CertStoreLocation 'Cert:\LocalMachine\My' -Password $pwd

$thumb = (Get-ChildItem Cert:\LocalMachine\My |
    Where-Object { $_.Subject -match 'iame\.ap\.inalfa\.local' -and $_.HasPrivateKey } |
    Sort-Object NotAfter -Descending | Select-Object -First 1).Thumbprint
$thumb
Get-ChildItem Cert:\LocalMachine\My\$thumb | Select-Object Subject, NotAfter, HasPrivateKey
```

判据：`$thumb` 有值（40 位十六进制），`HasPrivateKey = True`，`NotAfter` 为 2028-07-31。

失败先看：`$thumb` 为空 → pfx 口令错或证书未导入，重跑 `Import-PfxCertificate`。

单独回退：`Remove-Item Cert:\LocalMachine\My\$thumb`（B 段尚未对外生效）。

## B2 建站点目录与 web.config

```powershell
$appcmd = "$env:SystemRoot\System32\inetsrv\appcmd.exe"
foreach ($n in 'msia','bol','capacity') { New-Item -ItemType Directory -Path "C:\inetpub\proxy\$n" -Force | Out-Null }
```

三次写 `web.config`，只改 `http://127.0.0.1:` 后面的端口（8078 / 8090 / 8000）。以 MSIA 为例，另两个照抄换端口：

```powershell
@'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToLocal" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8078/{R:1}" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
            <set name="HTTP_X_FORWARDED_FOR" value="{REMOTE_ADDR}" />
          </serverVariables>
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
'@ | Set-Content -Path 'C:\inetpub\proxy\msia\web.config' -Encoding UTF8
```

判据：三个目录各有一份 `web.config`，其中的端口分别是 8078 / 8090 / 8000。

失败先看：站点报 `500.19` → 配置节被锁或 web.config 无法解析；报 `500.50` 且正文点名某个变量 `is not allowed to be set` → A6 ② 白名单漏登记，按 `<set>` 的条数逐条补齐（`proxy` 段里没有这个集合）。

单独回退：删除 `C:\inetpub\proxy` 目录。

## B3 预演：用临时端口验证「TLS 终结 + 反代」通

临时端口 18078 / 18090 / 18000，只为自证；此时应用还在 `0.0.0.0` 上，`127.0.0.1:<真实端口>` 可达。

```powershell
Import-Module WebAdministration
$guid = '{4dc3e181-e14b-4a21-b022-59fc669b0914}'
$map = @(
    @{ Site='Proxy-MSIA';     Port=18078; Dir='msia'     },
    @{ Site='Proxy-BOL';      Port=18090; Dir='bol'      },
    @{ Site='Proxy-Capacity'; Port=18000; Dir='capacity' }
)
foreach ($m in $map) {
    if (Get-WebSite -Name $m.Site -ErrorAction SilentlyContinue) { Remove-WebSite -Name $m.Site }
    New-WebSite -Name $m.Site -PhysicalPath "C:\inetpub\proxy\$($m.Dir)" `
        -Port $m.Port -IPAddress '172.26.2.203' -HostHeader 'iame.ap.inalfa.local' -Ssl | Out-Null
    netsh http add sslcert hostnameport="iame.ap.inalfa.local:$($m.Port)" certhash=$thumb appid=$guid certstorename=MY
}
netsh http show sslcert | Select-String 'iame.ap.inalfa.local:180'
```

验证（三条都应为 200，且响应体与直连一致）：

```powershell
"MSIA     " + (curl.exe -k -s -o NUL -w "%{http_code}" "https://iame.ap.inalfa.local:18078/api/auth/config")
"BOL      " + (curl.exe -k -s -o NUL -w "%{http_code}" "https://iame.ap.inalfa.local:18090/")
"Capacity " + (curl.exe -k -s -o NUL -w "%{http_code}" "https://iame.ap.inalfa.local:18000/health")
```

判据：三个 `200`；`netsh` 输出里三条 `Hostname: iame.ap.inalfa.local` 绑定都在。现场已全部通过：`:18078/api/auth/config`、`:18090/`、`:18000/health` 均 200。

> Capacity 的健康探针用 `/health`。`/api/v1/health` 在本应用里不存在，返回 `{"detail":"Not Found"}` 属正常——**看到这个 JSON 反而说明请求已经穿过 ARR 到了 FastAPI**，是链路通的旁证，不能当失败。

**三站同时 500，且正文点名某个变量不被允许设置**（`The server variable "..." is not allowed to be set.`，子状态码 `500.50`）→ 直接回 A6 ② 补白名单，不要去查应用和证书：这一条同时命中三个站点，只可能是全局白名单漏登记。

失败先看：

| 现象 | 先看 |
|---|---|
| 握手失败 / 连接被重置 | `netsh http show sslcert` 是否有该端口条目；`appid` 与 `certhash` 是否正确 |
| 502 Bad Gateway | 后端 `http://127.0.0.1:<端口>` 是否可达（`curl.exe -s -o NUL -w "%{http_code}"`）；ARR `enabled` 是否 true |
| 404 且是 IIS 页面 | web.config 的 rewrite 规则没生效（检查 A6 的 `proxy` 段与 `rewrite/allowedServerVariables` 白名单） |

单独回退：`Remove-WebSite -Name 'Proxy-MSIA','Proxy-BOL','Proxy-Capacity'` + `netsh http delete sslcert hostnameport=...`（三条），删掉临时绑定即回到起点。

**B3 全绿之前不要进 C 段**——C 段每一步都不可中断重试。

---

# C. 窗口段（**2026-11-11 已执行完成**；实际中断约 40 分钟，主要耗时在 keystore 口令排查与 BOL 内部端口调整）

> 进入 C 段前完成：B3 三条全 200；C0 九项 https URI 已加好（窗口内只读核对）；0.3.1 窗口前备份点四项非空；BOL 交付按 0.2 的**甲乙任一条**成立（运行目录 `BOLServer.exe` 哈希前 8 位 `C28E23AA`、`_internal` 非空、`db_config.ini` 仍为 IP 口径；甲另有中转目录、乙另有同盘变更前整目录备份）；`$bk` 完整。
> 清理口径：采用甲时 `C:\Temp\bol-new` 用完即清；采用乙时不存在中转目录，把 `C:\Services` 下遗留的 BOL 可执行文件（历史 staging 副本）直接清掉。两种情况下 `C:\Services` 都只放脚本、日志与回滚备份，不留第二份可执行程序。

**窗口内执行序列（照这个顺序走，不看章节号）**：

```text
① 核对 Keycloak client 九项 https URI（C0，只读，约 5 分钟）
② 停三个应用（MSIA / BOL / Capacity）
③ 切 Keycloak 域名 + keystore 并等 30–60 秒（C1）
④ 改三份 issuer / redirect_uri（C2.1）
⑤ 改绑 127.0.0.1（C2.3）
⑥ 起三个应用并验回环（C2.4）
⑦ 站点绑定从临时端口换到正式端口（C3）
⑧ 核对 302 里的 redirect_uri（C4）
⑨ D 段端到端验收
```

> 顺序固定：**Keycloak → 三份 issuer → 应用绑回环**。应用启动时即拉 OIDC discovery，所以 Keycloak 必须先在新域名上就绪；三份 `issuer` 与 `redirect_uri` 必须同一窗口内一起改，只改其中一份或只改一个应用都会因主机名不一致被应用自身拒绝（MSIA，2026-11-11 已实测）。文档章节仍按 C0 → C4 编号，执行顺序以本序列为准。

## C 段开工基线（B 段预演已完成时照此核对，不重做 A / B）

现场已完成 A 段与 B 段，实测基线：

| 项 | 实测值 |
|---|---|
| IIS / URL Rewrite 2.1 / ARR 3.0 | 均已安装；`proxy` 回读为 `enabled="true" timeout="00:05:00" preserveHostHeader="true" reverseRewriteHostInResponseHeaders="false"`；`system.webServer/rewrite/allowedServerVariables` 两条齐全（`HTTP_X_FORWARDED_PROTO`、`HTTP_X_FORWARDED_FOR`） |
| 证书 | `Cert:\LocalMachine\My` 中指纹 `A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A`，`CN=iame.ap.inalfa.local`，`HasPrivateKey=True`，`NotAfter=2028-07-31` |
| 反代目录 | `C:\inetpub\proxy\{msia,bol,capacity}` 各一份 `web.config`：`<set>` 两个变量（`HTTP_X_FORWARDED_PROTO=https`、`HTTP_X_FORWARDED_FOR={REMOTE_ADDR}`），**无** `<proxy>` 元素 |
| 站点 | `IAME-MSIA` / `IAME-BOL` / `IAME-CAPACITY`，host header `iame.ap.inalfa.local`，端口 18078 / 18090 / 18000，均已绑定证书 |
| 预演结果 | 三站全 200：`:18078/api/auth/config`、`:18090/`、`:18000/health` |

**因此窗口内不重做 A 段与 B 段**，只做 C0 的只读核对（URI 已在窗口前加好）与 C1/C2/C3 的配置切换、绑定换端口。开工前只跑一遍只读确认（A5 模块列表、A6 回读、`netsh http show sslcert`、`Get-WebSite`），任一不符再回对应小节。

> 命名口径：反代目录现场为 `C:\inetpub\proxy\{msia,bol,capacity}`（与 B2 示例一致）；**站点名现场为 `IAME-MSIA` / `IAME-BOL` / `IAME-CAPACITY`**，B2 之后各段示例里出现的 `Proxy-*` 一律替换成现场这三个名字，改绑前先 `Get-WebSite | Select-Object Name, PhysicalPath, State` 确认。端口 18078 / 18090 / 18000 与现场一致。

## C0 Keycloak client 的 https URI（**窗口前已完成，窗口内只读核对，约 5 分钟**）

> 状态：三个 client 的 https URI 共九项已于窗口前加好，原有 IP 值全部保留。窗口内**不再改 Keycloak**，只按下表逐条核对，核对不过才回管理台补。

窗口前已执行的动作（留档用）：进 `https://172.26.2.203:8443/admin`（证书告警点继续）→ realm `inalfa` → `Clients`，在既有 IP 值**之外**新增：

| client | Valid redirect URIs 新增 | Valid post logout redirect URIs 新增 | Web origins 新增 |
|---|---|---|---|
| `msia-prod` | `https://iame.ap.inalfa.local:8078/api/auth/oidc/callback` | —（不涉及） | `https://iame.ap.inalfa.local:8078` |
| `bol-prod` | `https://iame.ap.inalfa.local:8090/api/auth/oidc/callback` | —（不涉及） | `https://iame.ap.inalfa.local:8090` |
| `ics-prod` | `https://iame.ap.inalfa.local:8008/api/v1/auth/oidc/callback` | `https://iame.ap.inalfa.local:8008/login` | `https://iame.ap.inalfa.local:8008` |

> `ics-prod` 的 https 口径以 **8008** 为准（2026-11-11 已追加并验证登录）。窗口前曾按 8000 加过一组 `https://iame.ap.inalfa.local:8000/...`，已不再使用，核对时不要求删除，但不要以它作为判据。

**窗口内只读核对清单（九个输入框逐条过，缺一条都不能进 C 段）**：

| # | client | 输入框 | 应看到的值 |
|---|---|---|---|
| 1 | `msia-prod` | Valid redirect URIs | `https://iame.ap.inalfa.local:8078/api/auth/oidc/callback` |
| 2 | `msia-prod` | Valid post logout redirect URIs | 不涉及（保持空白） |
| 3 | `msia-prod` | Web origins | `https://iame.ap.inalfa.local:8078` |
| 4 | `bol-prod` | Valid redirect URIs | `https://iame.ap.inalfa.local:8090/api/auth/oidc/callback` |
| 5 | `bol-prod` | Valid post logout redirect URIs | 不涉及（保持空白） |
| 6 | `bol-prod` | Web origins | `https://iame.ap.inalfa.local:8090` |
| 7 | `ics-prod` | Valid redirect URIs | `https://iame.ap.inalfa.local:8008/api/v1/auth/oidc/callback` |
| 8 | `ics-prod` | Valid post logout redirect URIs | `https://iame.ap.inalfa.local:8008/login` |
| 9 | `ics-prod` | Web origins | `https://iame.ap.inalfa.local:8008` |

两条核对重点：

1. **原 IP 值必须仍在**：每个输入框里 `http://172.26.2.203:8078|8090|8000...` 的旧值不能被覆盖掉——整方案回滚只删 https 行、不重新加 IP 值，旧值没了就只能重建 client。
2. **`ics-prod` 的两个框是独立的**：`Valid redirect URIs` 与 `Valid post logout redirect URIs` 不是同一个输入框，必须分别确认。只加 redirect 未加 post logout 的表现是「能正常登录，点退出报 `Invalid redirect uri`」，且很容易被误判成应用 bug。

判据：九项全部对上，且旧 IP 值全部保留。

失败先看：某框保存后有 `*` → 有空白未保存行，删空行再 `Save`；旧 IP 值消失 → 从实施记录里补回原值再加 https 行。

单独回退：删掉 https 行保留 IP 值，`Save`。

## C1 Keycloak 切域名 + 正式证书（约 2 分钟 + 启动 30–60 秒）

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Stop -App Keycloak
Get-NetTCPConnection -LocalPort 8443,9000 -State Listen -ErrorAction SilentlyContinue

notepad C:\keycloak\conf\keycloak.conf
```

只改这几行：

| 行 | 改成 |
|---|---|
| 40 | `hostname=iame.ap.inalfa.local` |
| 63 | `# https-certificate-file=C:/keycloak/conf/server.crt.pem` |
| 64 | `# https-certificate-key-file=C:/keycloak/conf/server.key.pem` |
| 63–64 之后 | 新增三行：`https-key-store-file=C:/certs/iame.p12`<br>`https-key-store-password=IRSCNKettle01`<br>`https-key-store-type=PKCS12` |

不要动 45/46/50/51/67–69/80 行。

```powershell
.\register-services-nssm.ps1 -Action Start -App Keycloak
$deadline = (Get-Date).AddSeconds(120)
do { Start-Sleep -Seconds 3
     $l = @(Get-NetTCPConnection -LocalPort 8443,9000 -State Listen -ErrorAction SilentlyContinue)
} while ($l.Count -lt 2 -and (Get-Date) -lt $deadline)
curl.exe -k -s -o NUL -w "discovery=%{http_code}`n" "https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration"
```

判据：8443 与 9000 都 LISTENING；`discovery=200`。

失败先看：进程退出 → `C:\Services\logs\Keycloak-stderr.log` 尾部；最常见是 keystore 与 certificate 两组同时生效（互斥），确认 63/64 已加 `#`。

单独回退：`Copy-Item "$pw\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force` + `Start`（`$pw` 是 0.3.1 的窗口前备份点，含 IP + PEM 口径；`$bk` 同名为更早基线）。

## C2 三应用改配置 + BOL 版本处置（甲换 / 乙核对）+ 改绑回环（一次性重启，约 3 分钟）

### C2.0 先判「文件已换、进程没换」（只读，动手前做一次）

文件替换不等于生效：Windows 上正在运行的进程仍持有旧映像，BOL 会一直跑旧代码直到重启。用启动时间与文件时间对比：

```powershell
$run = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer'
Get-Process BOLServer -ErrorAction SilentlyContinue | Select-Object Id, StartTime
Get-Item "$run\BOLServer.exe" | Select-Object LastWriteTime
Get-Service 'BOL-Server' | Select-Object Name, Status
```

判读：

| 观测 | 含义 | 处置 |
|---|---|---|
| `StartTime` 早于 `LastWriteTime` | 进程仍在跑**旧映像**，新代码未生效 | 必须重启；但**不要现在单独重启**——并入下面 C2 的一次性重启 |
| `StartTime` 晚于 `LastWriteTime` | 进程已加载新映像 | 无需为此重启，照常走 C2 |
| `Get-Process` 无输出、服务 `Stopped` | 当前没在跑 | 不用单独启动，窗口内随 C2 一起起 |

> 现场口径：C2 本来就要停三个应用改配置，所以这里的"重启"不需要额外动作，这三条只用于判断**当前对外跑的是新代码还是旧代码**，以及避免窗口前多停一次机。若采用方案乙（已就地替换），这一步尤其要看——文件早就换好了，进程大概率还是旧的。

先停三个应用，避免边改边跑：

```powershell
cd C:\Services
.\register-services-nssm.ps1 -Action Stop -App MSIA
.\register-services-nssm.ps1 -Action Stop -App BOL
.\register-services-nssm.ps1 -Action Stop -App Capacity
```

### C2.1 改三份配置（保字节编码）

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

$p = @{
    'http://172.26.2.203:8078' = 'https://iame.ap.inalfa.local:8078'
    'https://172.26.2.203:8443' = 'https://iame.ap.inalfa.local:8443'
}
Repair-Text 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' $p

$p = @{
    'http://172.26.2.203:8090' = 'https://iame.ap.inalfa.local:8090'
    'https://172.26.2.203:8443' = 'https://iame.ap.inalfa.local:8443'
}
Repair-Text 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' $p

# Capacity 已于 2026-11-11 改到 8008 并验证通过；重跑时两个键都带上，保证幂等
$p = @{
    'http://172.26.2.203:8000'          = 'https://iame.ap.inalfa.local:8008'
    'https://iame.ap.inalfa.local:8000' = 'https://iame.ap.inalfa.local:8008'
    'https://172.26.2.203:8443'         = 'https://iame.ap.inalfa.local:8443'
}
Repair-Text 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' $p
```

核对（三份都要一条 `iame.ap.inalfa.local` 都不剩 `172.26.2.203`）：

```powershell
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini','C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini','C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '172\.26\.2\.203'
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' -Pattern '^\s*(issuer|redirect_uri)\s*='
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini' -Pattern '^\s*(issuer|redirect_uri)\s*='
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*OIDC_(ISSUER|REDIRECT_URI|FRONTEND_URL|POST_LOGOUT_REDIRECT_URI)='
```

判据：第一条无输出；后三条显示 `issuer=https://iame.ap.inalfa.local:8443/realms/inalfa`、`redirect_uri=https://iame.ap.inalfa.local:8078|8090/...`、Capacity 四项都是 `https://iame.ap.inalfa.local:8008...`。

**硬约束：`issuer` 与 `redirect_uri` 主机名必须一致**

MSIA 在启动后首次 OIDC 调用时会自校验主机名，不一致直接拒绝，与 Keycloak 连通性、证书都无关：

```text
OIDC 配置不完整: oidc.issuer 主机名 (172.26.2.203) 与 oidc.redirect_uri 主机名 (iame.ap.inalfa.local) 不一致
```

2026-11-11 现场即因"只把 MSIA 切到 https、issuer 仍是 IP"触发该错误，误判方向是 Keycloak 故障。因此三份配置的 `issuer` 与 `redirect_uri` 必须与 C1 的 Keycloak 切换在同一窗口内一起改；单独切任何一个应用都会失败。

配置改完后先做主机名一致性检查，再起应用：

```powershell
foreach ($f in @(
    'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini',
    'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\db_config.ini')) {
    "=== $f"
    (Select-String -Path $f -Pattern '^\s*(issuer|redirect_uri)\s*=').Line
}
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*OIDC_(ISSUER|REDIRECT_URI)='
```

判据：同一份配置里 `issuer` 与 `redirect_uri` 的主机名完全相同（要么都是 IP，要么都是 `iame.ap.inalfa.local`），不允许混用。

### C2.2 BOL 文件处置（按 0.2 的交付方式二选一）

**方案甲：预置待换 → 窗口内整目录替换**

```powershell
$bolDir = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer'
$new    = 'C:\Temp\bol-new\BOLServer'
# 备份优先放同盘同父目录（本地改名，回滚最快）；命名 BOLServer_pre-planb-<yyyyMMdd>
$oldBk  = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_pre-planb-20261110'

# ① 旧目录整份留底（含 _internal，只留 exe 回退不了）
New-Item -ItemType Directory -Path $oldBk -Force | Out-Null
Copy-Item "$bolDir\*" $oldBk -Recurse -Force

# ② 新目录整份覆盖，跳过 db_config.ini（C2.1 刚改过，不能被旧值盖掉）
Get-ChildItem $new | Where-Object { $_.Name -ne 'db_config.ini' } |
    Copy-Item -Destination $bolDir -Recurse -Force

# ③ 核对
Get-FileHash "$bolDir\BOLServer.exe" -Algorithm SHA256 | Select-Object Hash
(Get-ChildItem "$bolDir\_internal" | Measure-Object).Count
(Get-Item "$bolDir\db_config.ini").LastWriteTime
```

判据：哈希前 8 位为 `C28E23AA`；`_internal` 条目数与 `$new\_internal` 一致且非空；`db_config.ini` 的 `LastWriteTime` 仍是 C2.1 的修改时间（说明没被覆盖）。

失败先看：哈希对不上 → 中转目录不是那份产物，回 0.2 重新取包；`db_config.ini` 时间变旧 → 覆盖范围写错，先用 `$bk\bol-db_config.ini` 恢复再重做。

单独回退：`Copy-Item "$oldBk\*" 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer' -Recurse -Force`。

**方案乙：已就地替换 → 本步不动文件，只核对**

```powershell
$bolDir = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer'
Get-FileHash "$bolDir\BOLServer.exe" -Algorithm SHA256 | Select-Object Hash
(Get-ChildItem "$bolDir\_internal" | Measure-Object).Count
Test-Path 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08\db_config.ini'
Select-String -Path "$bolDir\db_config.ini" -Pattern '^issuer'
```

判据：哈希前 8 位 `C28E23AA`；`_internal` 非空；同盘备份含 `db_config.ini`；`issuer` 已由 C2.1 改成 `https://iame.ap.inalfa.local:8443/realms/inalfa`。

**本步不复制任何文件**——运行目录已经是新版本，再拷一次会把 C2.1 刚改好的 `db_config.ini` 盖回 IP 口径。

单独回退：`Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08\*' 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer' -Recurse -Force`（备份目录名按现场实际，命名规范 `BOLServer_pre-planb-<yyyyMMdd>`）。

### C2.3 改绑 `127.0.0.1`

MSIA（`config.ini` 的 `[server] host`）：

> 现场状态（2026-11-11）：MSIA 单独切 https 失败后已回退——`host=0.0.0.0`、`port=8078`、`redirect_uri=http://172.26.2.203:8078/api/auth/oidc/callback`，8078 的 https 站点绑定与 sslcert 已删，`C:\inetpub\iame\msia\web.config` 反代目标改回 `http://127.0.0.1:8078/`，登录已恢复。明天必须在 C1 切 Keycloak 之后、与 C2.1 同批次重做本步，不要再单独改。

```powershell
Repair-Text 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' @{ 'host = 0.0.0.0' = 'host = 127.0.0.1'; 'host=0.0.0.0' = 'host=127.0.0.1' }
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\config.ini' -Pattern '^\s*host\s*=' -Context 0,0
```

判据：`[server]` 段的 `host` 为 `127.0.0.1`（形状按实际行写，`host = 0.0.0.0` 与 `host=0.0.0.0` 两种都覆盖了）。

BOL（NSSM 启动参数）：

```powershell
nssm get BOL-Server AppParameters
nssm set BOL-Server AppParameters "--host 127.0.0.1 --port 8090"
nssm get BOL-Server AppParameters
```

判据：回读为 `--host 127.0.0.1 --port 8090`。若原参数还有其它项（如 `--workers`），把它们一并写回，不要丢。

Capacity（**host 写死在程序内，配置层与 NSSM 层都改不了**）：现场给服务环境注入 `HOST=127.0.0.1` 并重启后，监听仍是 `0.0.0.0:8000`，变量未被采用；**已按「公网换端口 8008」落地并验证通过**。

动手前复核现场基线：`nssm get CapacityAPI AppParameters` 为空；`Application` 为 `C:\ApplicationFile\ExecuteProgram\Capacity\publish\CapacityAPI\CapacityAPI.exe`，`AppDirectory` 为同目录；`.env` 全量键名中没有 `HOST` / `PORT` / `BIND` / `SERVER_HOST` / `LISTEN`。

```powershell
nssm get CapacityAPI AppParameters
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*(HOST|PORT|BIND|SERVER_HOST|LISTEN)\s*='
```

应用侧不动、`.env` 的 `OIDC_ISSUER` 不动、`web.config` 仍转发 `http://127.0.0.1:8000`（**不用改**），只把对外口径换成 8008。

**实际执行顺序（八步，已全部完成）**

① 加 8008 站点绑定：

```powershell
Import-Module WebAdministration
Get-WebBinding -Name 'IAME-CAPACITY' -Protocol https | Select-Object BindingInformation, Port
New-WebBinding -Name 'IAME-CAPACITY' -Protocol https -Port 8008 `
    -IPAddress '*' -HostHeader 'iame.ap.inalfa.local'
Get-WebBinding -Name 'IAME-CAPACITY' -Protocol https | Select-Object BindingInformation, Port
```

判据：回读出现 `*:8008:iame.ap.inalfa.local`。若报 `Cannot add duplicate collection entry of type 'binding'`，说明这条绑定已经在，**不是失败**，不要重复加（见避坑点 2.6）。

② 给新端口挂证书（`New-WebBinding` 只加站点绑定，不碰证书表）：

```powershell
netsh http add sslcert ipport=0.0.0.0:8008 `
    certhash=A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A `
    appid='{4dc3e181-e14b-4a21-b022-59fc669b0914}' certstorename=MY
netsh http show sslcert | Select-String '0.0.0.0:8008'
```

`appid` 沿用同站点 18000 那条的 GUID。漏这一步、只加绑定不挂证书时，访问新端口表现为 TLS 握手失败（`ERR_SSL_PROTOCOL_ERROR` / `SSL_ERROR_SYSCALL`），不是 503（见避坑点 2.7）。

③ 验新端口通：

```powershell
"CAP health " + (curl.exe -k -s -o NUL -w "%{http_code}`n" "https://iame.ap.inalfa.local:8008/health")
```

判据：`200`。

④ 防火墙只放行 8008（阻断 8000 **未执行**，见下方待办）：

```powershell
New-NetFirewallRule -DisplayName 'IAME-CAPACITY-HTTPS-8008' -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 8008 -Profile Domain,Private,Public

Get-NetFirewallRule -DisplayName 'IAME-CAPACITY-HTTPS-8008' |
    Select-Object DisplayName, Enabled, Action, Direction
```

判据：`IAME-CAPACITY-HTTPS-8008` 存在且 `Enabled=True`、`Direction=Inbound`、`Action=Allow`（现场已回读确认）。

**待办（本次未执行）：阻断外部对 8000 的直连**

- 现状：现场决定先不封口，阻断 8000 的入站规则**本次未创建**，8000 仍是对外可直达的入口。
- 连带影响：只要 8000 未封口，Keycloak `ics-prod` 里旧的 `http://172.26.2.203:8000/...` URI **必须保留**（Valid redirect、Valid post logout、Web origins 三项都不删），否则从 8000 进入的用户会直接报 `Invalid redirect uri`。C0 里"旧值不能覆盖"的要求同样适用于此处。
- 真正封口时才做：新建一条 Block 全封（不要另加回环 Allow，见避坑点 2.8），命名沿用同一风格，如 `IAME-CAPACITY-BLOCK-8000`；验收通过后再统一清理旧 8000 URI。

```powershell
# 封口时才执行，本次未创建
New-NetFirewallRule -DisplayName 'IAME-CAPACITY-BLOCK-8000' -Direction Inbound `
    -Action Block -Protocol TCP -LocalPort 8000 -Profile Domain,Private,Public
```

封口时的验收项（未封口前不执行）：从另一台机器访问 `http://172.26.2.203:8000` 连接被拒；同时本机 `http://127.0.0.1:8000/health` 仍为 `200`；确认无误后再删 `ics-prod` 的 8000 URI。

⑤ `.env` 三处 OIDC 地址与 `CORS_ORIGINS` 改 8008（`OIDC_ISSUER` 仍指 Keycloak 的 8443，不动）：

```powershell
Repair-Text 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' @{
    'iame.ap.inalfa.local:8000' = 'iame.ap.inalfa.local:8008'
}
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*(OIDC_(ISSUER|REDIRECT_URI|FRONTEND_URL|POST_LOGOUT_REDIRECT_URI)|CORS_ORIGINS\s*)='
```

判据：`OIDC_ISSUER` 仍为 `https://iame.ap.inalfa.local:8443/realms/inalfa`；`OIDC_REDIRECT_URI`、`OIDC_FRONTEND_URL`、`OIDC_POST_LOGOUT_REDIRECT_URI`、`CORS_ORIGINS` 均为 8008，文件里不再残留对外 `:8000` 地址。反引号有无须做字节级检查（见避坑点 4.3）。

⑥ 重启 CapacityAPI 并回读回环：

```powershell
nssm restart CapacityAPI
Start-Sleep -Seconds 8
"127 CAP " + (curl.exe -s -o NUL -w "%{http_code}`n" "http://127.0.0.1:8000/health")
```

判据：`200`；监听仍是 `0.0.0.0:8000`（预期，应用改不了）。

⑦ Keycloak `ics-prod` 追加三条 URI（原有 IP 值保留）：

| 输入框 | 追加值 |
|---|---|
| Valid redirect URIs | `https://iame.ap.inalfa.local:8008/api/v1/auth/oidc/callback` |
| Valid post logout redirect URIs | `https://iame.ap.inalfa.local:8008/login` |
| Web origins | `https://iame.ap.inalfa.local:8008` |

⑧ 浏览器验收：打开 `https://iame.ap.inalfa.local:8008/login` 走一次登录，回跳后页面显示用户名 → 通过。

回滚：`Remove-NetFirewallRule -DisplayName 'IAME-CAPACITY-HTTPS-8008'`；`.env` 用 `$pw\capacity-env` 覆盖；`Remove-WebBinding -Name 'IAME-CAPACITY' -Protocol https -BindingInformation '*:8008:iame.ap.inalfa.local'` + `netsh http delete sslcert ipport=0.0.0.0:8008`；删 `ics-prod` 三条 8008 URI；`nssm restart CapacityAPI`。

> Capacity 已按 8008 落地，本手册后续 Capacity 的端口口径（C3 绑定、C4 探针、D 段验收）一律为 **8008**；只有 `web.config` 转发目标与应用自身监听仍是 `127.0.0.1:8000`。

### C2.4 起三个应用并验证回环绑定（前提：C1 的 Keycloak 已在新域名上 `discovery=200`）

```powershell
.\register-services-nssm.ps1 -Action Start -App MSIA
.\register-services-nssm.ps1 -Action Start -App BOL
.\register-services-nssm.ps1 -Action Start -App Capacity
.\register-services-nssm.ps1 -Action Status -App All

Get-NetTCPConnection -LocalPort 8078,8090,8000 -State Listen |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

判据：三个服务 `Running`；MSIA / BOL 两条监听为 `LocalAddress = 127.0.0.1`。Capacity 仍为 `0.0.0.0:8000`（写死，改不了属正常），对外新增 8008 反代入口；8000 仍对外可直达（未封口，见 C2.3 ④ 待办）。

```powershell
"127 MSIA " + (curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:8078/api/auth/config")
"127 BOL  " + (curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:8090/")
"127 CAP  " + (curl.exe -s -o NUL -w "%{http_code}" "http://127.0.0.1:8000/")
```

判据：三个 `200`。

失败先看：

| 现象 | 先看 |
|---|---|
| 服务起不来 | `C:\Services\logs\<服务>-stderr.log` 尾部；MSIA 常见是 `[server] host` 行写坏（格式与原来不一致） |
| 监听仍是 `0.0.0.0` | MSIA 不是改在 `[server]`、BOL 参数没被 NSSM 生效；Capacity 属硬编码，已按 C2.3 落地 8008，监听仍是 `0.0.0.0:8000` 属正常 |
| `127.0.0.1` 直连 502/连接拒绝 | 应用没起来或端口不一致 |

单独回退（本步内可独立做）：三份配置用 `$pw` 覆盖回去（10 分钟前的窗口前快照）、`nssm set BOL-Server AppParameters "<原参数>"`、BOL 目录用备份整份覆盖回去（来源二选一：同盘的 `BOLServer_08` / `BOLServer_pre-planb-*`，或 `$bk\bol-dir`；命令见「C 段局部回退」表），然后 `Start` 三个应用——此时退回「应用 0.0.0.0 + IP 口径」，需要配合 C1 的回退一起才完整可用。

## C3 站点绑定从临时端口切到正式端口（约 2 分钟）

```powershell
Import-Module WebAdministration
$guid = '{4dc3e181-e14b-4a21-b022-59fc669b0914}'
$map = @(
    @{ Site='Proxy-MSIA';     Dir='msia';     Old=18078; New=8078 },
    @{ Site='Proxy-BOL';      Dir='bol';      Old=18090; New=8090 }
)
foreach ($m in $map) {
    netsh http delete sslcert hostnameport="iame.ap.inalfa.local:$($m.Old)" | Out-Null
    Set-WebBinding -Name $m.Site -BindingInformation "172.26.2.203:$($m.Old):iame.ap.inalfa.local" -PropertyName Port -PropertyValue $m.New
    netsh http add sslcert hostnameport="iame.ap.inalfa.local:$($m.New)" certhash=$thumb appid=$guid certstorename=MY
}

# Capacity：8008 的绑定与证书已在 C2.3 ① ② 加好，本步只下掉 18000 临时绑定
netsh http delete sslcert hostnameport="iame.ap.inalfa.local:18000" | Out-Null
Remove-WebBinding -Name 'IAME-CAPACITY' -Protocol https -BindingInformation '*:18000:iame.ap.inalfa.local'
netsh http show sslcert | Select-String 'iame.ap.inalfa.local:8078|iame.ap.inalfa.local:8090|0.0.0.0:8008'
```

判据：MSIA / BOL 两条 SSL 绑定指向 8078 / 8090；Capacity 的 `0.0.0.0:8008` 绑定仍在、18000 已删；`Get-WebBinding -Name 'Proxy-MSIA'` 显示 `https` 与 `172.26.2.203:8078`。

失败先看：`Set-WebBinding` 报找不到绑定 → `BindingInformation` 与实际不一致，先 `Get-WebBinding -Name <站点> -Protocol https` 看实际字符串；`netsh add sslcert` 报 `183`（已存在）→ 先 `delete` 再 `add`。

```powershell
"https MSIA " + (curl.exe -k -s -o NUL -w "%{http_code}`n" "https://iame.ap.inalfa.local:8078/api/auth/config")
"https BOL  " + (curl.exe -k -s -o NUL -w "%{http_code}`n" "https://iame.ap.inalfa.local:8090/")
"https CAP  " + (curl.exe -k -s -o NUL -w "%{http_code}`n" "https://iame.ap.inalfa.local:8008/")
```

判据：三个 `200`，且与回环响应体一致（MSIA `127.0.0.1:18078` / BOL `127.0.0.1:18090` / Capacity `127.0.0.1:8000`）。

单独回退：把 `Set-WebBinding` 的 `New`/`Old` 对调重跑，删新端口 sslcert、加回临时端口；应用保持回环不动（不影响回退到「应用 0.0.0.0」的路径）。

## C4 核对 Keycloak 侧 https URI 已生效

```powershell
# 只读核对：登录入口的 302 应带新的 redirect_uri
curl.exe -k -s -o NUL -D - "https://iame.ap.inalfa.local:8008/api/v1/auth/oidc/login" |
    Select-String 'location'
```

判据：`location` 中的 `redirect_uri` 为 `https%3A%2F%2Fiame.ap.inalfa.local%3A8008%2Fapi%2Fv1%2Fauth%2Foidc%2Fcallback`，`client_id=ics-prod`。

失败先看：出现 `Invalid parameter: redirect_uri` 的页面 → C0 里那条 https URI 没保存，回 C0 补。

单独回退：无（只读）。

## C 段实际执行顺序与偏差（2026-11-11）

实际落的顺序：C0 核对 → 停应用 → C1（Keycloak 换 keystore，口令排错）→ C2.1 三份 issuer/redirect → C2.3 改绑 → C2.4 起应用 → C3 换正式端口 → C4 核 302 → D 验收。

与原文的偏差共四处，均为现场必需：

1. **内部端口换号**：应用不能与被 IIS 占用的端口共存，`8078` / `8090` 交给 IIS，应用侧改为 `18078`（MSIA `config.ini` 的 `port`）与 `18090`（BOL 的 `--port`）；`web.config` 反代目标相应为 `http://127.0.0.1:18078/`、`http://127.0.0.1:18090/`。
2. **先删预演绑定再起应用**：`IAME-BOL` 上 `*:18090` 的预演绑定会占住 HTTP.sys，导致 `BOLServer.exe --port 18090` 绑不上、服务起不来。C3 前必须先 `Remove-WebBinding -Name 'IAME-BOL' -Port 18090`（MSIA 的 `18078` 同理，若无预演绑定可跳过）。
3. **Keycloak keystore 口令重写**：写进 `keycloak.conf` 的口令与实际 `.p12` 不一致时 Keycloak 起不来且 `AppExit=Restart` 每 17 秒重启一次，需用 `keytool` 独立验证后按字面量重写（见「常见失败现象对照」第 13 条）。
4. **Capacity 的 8000 未封口**：`BLOCK` 规则本次决定不做，`http://172.26.2.203:8000/...` 旧 URI 保留。

BOL 的端口与主机只能通过 NSSM `AppParameters` 传（`BOLServer.exe --host --port`，见 `README_DEPLOY.txt`）；`db_config.ini` 里没有 `[server]` 段，不要去改。

---

# D. 端到端验收

浏览器（客户端需能解析 `iame.ap.inalfa.local`），三条登录链路 + 两项补充。**2026-11-11 现场已全部通过**：

| # | 地址 | 通过标准 | 结果 |
|---|---|---|---|
| 1 | `https://iame.ap.inalfa.local:8078`（IIS → `127.0.0.1:18078`） | 统一登录 → 回到业务页，显示用户；**无证书告警** | 通过 |
| 2 | `https://iame.ap.inalfa.local:8090`（IIS → `127.0.0.1:18090`） | 同上 | 通过 |
| 3 | `https://iame.ap.inalfa.local:8008`（IIS → `127.0.0.1:8000`） | 同上 | 通过 |
| 4 | `https://iame.ap.inalfa.local:8008` → 点退出 | 回到 `https://iame.ap.inalfa.local:8008/login`，无 `Invalid redirect uri` | 通过 |
| 5 | Capacity 的 CORS：DevTools → Network → 任一 API 响应头 | `access-control-allow-origin` 含 `https://iame.ap.inalfa.local:8008`（或 `*`）；前后端同源时该头可缺省，不算失败，按下方专项判定 | 通过 |

补充判据：

```powershell
foreach($s in 'MSIA-Server','BOL-Server','CapacityAPI'){
    "=== $s"
    Get-Content "C:\Services\logs\$s-stderr.log" -Tail 40 | Select-String 'CERTIFICATE|idp_unreachable|CSRF|403'
}
curl.exe -k -s -o NUL -w "kc=%{http_code}`n" "https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration"
```

判据：三条日志无 `CERTIFICATE_VERIFY_FAILED` / `idp_unreachable`；`kc=200`。

**Capacity CORS 专项**（`.env` 的 `CORS_ORIGINS`）：

```powershell
Select-String -Path 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' -Pattern '^\s*CORS_ORIGINS\s*='
```

现场值已在 C2.3 ⑤ 改成含 `https://iame.ap.inalfa.local:8008`。判据与处置：

- 前端与 API **同源**（都在 `https://iame.ap.inalfa.local:8008`）→ 浏览器不发跨域请求，此项不影响验收，可不改。
- 前端由**其它源**访问 API（含开发机 `https://localhost:8000` 的场景）→ 必须把该源追加进去且保留原值，否则被浏览器拦（`No 'Access-Control-Allow-Origin' header`）：

```powershell
Repair-Text 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\.env' @{
    '["https://iame.ap.inalfa.local:8008"]' = '["https://iame.ap.inalfa.local:8008","https://localhost:8000"]'
}
nssm restart CapacityAPI
```

替换键按上一条 `Select-String` 的**实际字符串**调整（空格、引号、顺序必须一致）。

**BOL 专项**（验证 CSRF 修复是否生效）：登录 BOL 后在任一业务页做一次「新增/保存」类 POST 操作。

判据：不出现 `CSRF verification failed`。出现 → C2.2 的 exe 没换成新版，或 `SECURE_PROXY_SSL_HEADER` 没进包。

不通过时按「常见失败现象对照」逐条排，不要回头重做 C1。

---

# E. 收尾

1. 归档站点配置：

```powershell
New-Item -ItemType Directory -Path 'C:\Services\backup\planb' -Force | Out-Null
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list site /config /xml > 'C:\Services\backup\planb\sites.xml'
netsh http show sslcert > 'C:\Services\backup\planb\sslcert.txt'
Copy-Item C:\inetpub\proxy\*\web.config 'C:\Services\backup\planb\' -Force
Copy-Item C:\keycloak\conf\keycloak.conf 'C:\Services\backup\planb\keycloak.conf' -Force
```

2. 台账更新（写入实施记录）：三个 client 的 https URI、三条 SSL 绑定（hostnameport + certhash）、`SSL_CERT_FILE` 现状、BOL exe 版本哈希、`proxy` 段三个参数值。2026-11-11 实际终态一并记入：Keycloak `https://iame.ap.inalfa.local:8443` + `iame.p12`（PKCS12，PEM 两行已注释）；MSIA 应用 `127.0.0.1:18078`、IIS `https *:8078`；BOL 应用 `127.0.0.1:18090`、IIS `https *:8090`；Capacity 应用 `0.0.0.0:8000`、IIS `https *:8008`；三站点证书指纹 `A1FC2947BADE887B00E6C0BF4CC0E6FA7D59AC0A`（见拓扑表，以此为准）；防火墙规则 `IAME-CAPACITY-HTTPS-8008`；`ca-bundle.pem` 块数 3→6。
3. 可选清理：C0 里保留的旧 IP URI 建议**保留到验收后一周**再删（回滚要用）。其中 Capacity 的 `http://172.26.2.203:8000/...` 三项在 8000 封口前**不得删除**。
4. **待办清理清单（2026-11-11 遗留，逐项处理后再归档）**：

| # | 对象 | 动作 | 说明 |
|---|---|---|---|
| 1 | `C:\Services\staging\BOLServer.exe` | 删除 | 历史 staging 副本，`C:\Services` 下不留第二份可执行程序 |
| 2 | `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08` | 改名（如 `BOLServer_pre-planb-20261111`）保留 | 变更前整目录备份，留一个回滚周期 |
| 3 | `C:\inetpub\proxy\{msia,bol,capacity}` | 归档后删除 | 预演用目录，正式站点已指向 `C:\inetpub\iame\*`；先把 `web.config` 归档到 `C:\Services\backup\planb` |
| 4 | `C:\certs\ca-bundle.pem.bak` / `.bak2` | 保留一周 | 信任链回滚点 |
| 5 | Capacity 8000 公网口 | **未封口**，保持现状 | 阻断规则本次未创建；`ics-prod` 的 `http://172.26.2.203:8000/...` 三项必须保留 |

5. 收尾确认：`Get-WebSite | Select Name, State, PhysicalPath` 三个站点 `Started`；`netsh http show servicestatus` 无异常队列。

---

# 回滚

## 整方案退回 IP（复用现成清单）

直接按 `统一身份认证实施\docs\rollback-r2-checklist.md` 执行（第 0–7 步），**不要重抄**。本方案比 R2 多出四处，R2 里没有，需在 R2 之后补做：

| 差异点 | 动作 |
|---|---|
| IIS 站点 | `Remove-WebSite -Name 'Proxy-MSIA','Proxy-BOL','Proxy-Capacity'`（站点删除后绑定与 sslcert 一并清理；残留则 `netsh http delete sslcert hostnameport=iame.ap.inalfa.local:8078/8090` + `ipport=0.0.0.0:8008`） |
| 应用回环绑定 | MSIA `[server] host` 改回 `0.0.0.0`；`nssm set BOL-Server AppParameters "--host 0.0.0.0 --port 8090"`；Capacity 改回 `0.0.0.0`（或删掉 `--host`） |
| BOL 版本 | BOL 目录整份覆盖回去，来源二选一：`Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08\*' 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer' -Recurse -Force`（同盘，推荐）或 `Copy-Item "$bk\bol-dir\*" ...`（只回 exe 会与新 `_internal` 错配） |
| Keycloak client | 删掉 C0 加的 https URI（保留 IP 值），`ics-prod` 的 post logout 一并删 |

顺序：先删站点（立刻停止 https 入口）→ 应用改回 `0.0.0.0` → 起服务 → 按 R2 走配置与 Keycloak 回退 → 删 client 的 https URI。判据与 R2 第 6/7 步一致。

## C 段局部回退

| 步骤 | 单独回退 |
|---|---|
| C1 Keycloak | `Copy-Item "$pw\keycloak.conf" C:\keycloak\conf\keycloak.conf -Force` → `Start -App Keycloak` → 用 `https://172.26.2.203:8443` 验 `discovery=200` |
| C2 配置 | 三份配置文件用 `$pw\msia-config.ini` / `bol-db_config.ini` / `capacity-env` 覆盖回去（`$pw` 为窗口前快照；`$bk` 同名为更早基线） |
| C2 BOL 版本 | 来源二选一：`Copy-Item 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer_08\*' 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer' -Recurse -Force`（方案乙的现场备份），或 `Copy-Item "$bk\bol-dir\*" ... -Recurse -Force`；方案乙未在窗口内改过文件的话，本项通常只需回 `db_config.ini` |
| C2 回环绑定 | MSIA `host` 改回 `0.0.0.0`；`nssm set BOL-Server AppParameters "--host 0.0.0.0 --port 8090"`；Capacity 同理 |
| C3 站点端口 | `Set-WebBinding` 把 `Old`/`New` 对调重跑，ssl 绑定同步挪回临时端口 |
| C0 client | 删 https URI 行，`Save` |

局部回退的判据统一是：`http://127.0.0.1:<端口>`（应用侧）与 `https://iame.ap.inalfa.local:<端口>`（反代侧）二者至少一侧 200；两侧都不通说明退到了「业务不可用」，必须整方案回滚。

---

# 常见失败现象对照

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | 登录成功但 BOL 点任何按钮 → `CSRF verification failed. Request aborted.` | Django 看不到 `X-Forwarded-Proto`，认为请求是 http，而浏览器 Origin 是 https | 确认 C2.2 换的是新打好的 exe；`grep SECURE_PROXY_SSL_HEADER` 构建机源码；确认 IIS 侧 web.config 里 `HTTP_X_FORWARDED_PROTO=https` 与 A6 ② 的 `rewrite/allowedServerVariables` 白名单都在 |
| 2 | BOL/MSIA 登录后立刻掉回未登录、反复跳登录页 | Cookie 域/协议不匹配，或 `SESSION_COOKIE_SECURE` 与 https 不一致 | BOL 侧 `SESSION_COOKIE_SECURE=False` 在 https 下可用（不强制改）；若改成 `True` 需重建 exe。先查浏览器是否拒绝 Cookie（Network 里 `Set-Cookie` 是否被标 `Secure`+`SameSite`） |
| 3 | 浏览器报 `Invalid parameter: redirect_uri` | 应用侧 `redirect_uri` 与 Keycloak client 里的值**逐字**不一致（含尾斜杠、http/https、端口） | 以应用配置为准，把 Keycloak 里对应 client 的值改成完全相同；MSIA/BOL 无尾斜杠，BOL 的 `front_callback` 有尾斜杠但与 `redirect_uri` 无关 |
| 4 | Capacity 能登录、点退出报 `Invalid redirect uri` | `ics-prod` 的 **Valid post logout redirect URIs** 漏加 | 补 `https://iame.ap.inalfa.local:8008/login` |
| 5 | 反代站点 502 / 请求停在 IIS 默认页 | ARR 总开关是 `false`，或安装顺序反了导致 `requestRouter` 未注册 | `appcmd list config /section:system.webServer/proxy` 看 `enabled`；为 false 就 `set ... /enabled:"true" /commit:apphost`；仍 502 则 `iisreset` 后复查 A5 模块 |
| 6 | https 握手失败，`curl -k` 报 `SSL_ERROR_SYSCALL` / 连接被重置 | SSL 绑定缺失或证书不匹配：端口有绑定但没 sslcert，或同一 ip:port 上多个主机名只做了 IP 绑定（缺 SNI） | `netsh http show sslcert` 确认 `hostnameport=iame.ap.inalfa.local:<端口>` 存在且 `certhash` 与 `$thumb` 一致；同一端口多主机名时必须用 `hostnameport=` 而不是 `ipport=`（SNI） |
| 7 | 大文件上传报 `413.1` 或 30 秒后 504 | IIS 默认 `maxAllowedContentLength≈30MB`、ARR 默认超时 30 秒 | `appcmd set config "<站点>" -section:requestFiltering -requestLimits.maxAllowedContentLength:209715200`；`appcmd set config "<站点>" -section:serverRuntime -uploadReadAheadSize:1048576`；超时已在 A6 设为 5 分钟，必要时调大 |
| 8 | `New-WebSite` 成功但 https 访问 404/超时，`Get-NetTCPConnection` 显示 `0.0.0.0:8078` 仍被应用占用 | 应用还绑在 `0.0.0.0`，通配地址优先，IIS 的 `172.26.2.203:8078` 抢不到监听 | 必须先把应用改绑 `127.0.0.1`（C2.3）再做 C3；顺序不能反 |
| 9 | 直接访问 `http://iame.ap.inalfa.local:8078` 报 `ERR_SSL_PROTOCOL_ERROR` | 浏览器已缓存 Keycloak 的 HSTS，把 http 升级为 https；8080 类明文端口必然失败 | 这**正是本方案要解决的问题**：走 `https://iame.ap.inalfa.local:8078`。收尾后不再提供 http 入口 |
| 10 | 服务起不来，日志报端口被占用 | 上一轮残留进程或 IIS 已占用同一 ip:port | `Get-NetTCPConnection -LocalPort <端口> -State Listen` 查 PID，先停占用者再起服务 |
| 11 | MSIA 报 `OIDC 配置不完整: oidc.issuer 主机名 (172.26.2.203) 与 oidc.redirect_uri 主机名 (iame.ap.inalfa.local) 不一致` | 应用自身校验 `issuer` 与 `redirect_uri` 主机名必须一致，与 Keycloak 连通性无关 | 同一窗口内把两者一起改成同一主机名（见 C2.1 硬约束）；不要往 Keycloak / 证书方向查 |
| 12 | 日志 `OIDC discovery 拉取失败：[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate` + `idp_unreachable`，浏览器只看到"统一身份认证服务暂不可用" | `SSL_CERT_FILE` 指向的 bundle 不含 Keycloak 当前服务端证书/签发链 | 把 `C:\certs\iame-all.pem`（叶+中间+根）追加进 `C:\certs\ca-bundle.pem`（证书块 3→6），三个应用统一 `SSL_CERT_FILE=C:\certs\ca-bundle.pem`；BOL 原本指向 `C:\keycloak\conf\server.crt.pem`，必须一并改 |
| 13 | Keycloak 启动即退出，日志 `java.io.IOException: keystore password was incorrect`，服务每 17 秒重启一次（`AppExit=Restart`） | 写进 `keycloak.conf` 的 `https-key-store-password` 与实际 `.p12` 口令不一致；口令含 `$`、反引号、`#` 时双引号写法会被插值或截断 | 先用 `keytool -list -keystore C:\certs\iame.p12 -storetype PKCS12` 独立验证口令；确认后 `Read-Host` 取值、按字面量重写那一行（单引号或转义），再 `Start-Service` |
| 14 | 同一 PowerShell 会话里先按默认 TLS 连过某 host:port，之后即使设了 Tls12 仍报 `unexpected error occurred on a send` | `ServicePointManager.SecurityProtocol` 不作用于 `SslStream`，且 ServicePoint 会缓存旧协议/TLS 会话 | 验证服务端一律用裸 TLS：`AuthenticateAsClient($h,$null,[SslProtocols]::Tls12,$false)` 后手工发 HTTP 请求；或换新进程再设协议 |
| 15 | `BOLServer.exe --port 18090` 起不来，端口被占 | IIS 预演绑定 `*:18090` 仍占着 HTTP.sys | 升级到正式端口前先 `Remove-WebBinding -Name 'IAME-BOL' -Port 18090`（MSIA 的 18078 同理），再起服务 |

---

# 实施当天时间盒（2026-11-11 已执行，下表为实际记录）

| 段 | 内容 | 实际 | 卡点 |
|---|---|---|---|
| 0 | 签名校验、BOL 预打包、备份（含 0.3.1 窗口前备份点）、防火墙确认 | 按计划完成 | BOL 打包环境不在本机时要提前一天准备 |
| A | IIS → URL Rewrite → ARR → `iisreset` → 模块与总开关 | 按计划完成 | 缺安装源介质时要挂 ISO；`iisreset` 会短暂断开 IIS 管理 |
| B | 导入证书、建站点与 web.config、临时端口预演 | 按计划完成 | 站点 `serverVariables` 未进 A6 的 `rewrite/allowedServerVariables` 白名单会 500.19 |
| C | 窗口：**C0 九项 URI 只读核对** + 停应用 + Keycloak 切换 + 三份 issuer/redirect + 改绑 + 起应用 + 绑定切端口 | **业务中断约 40 分钟**（含 keystore 口令排查与预演端口腾空） | 实际卡点不是配置顺序，而是 keystore 口令写错导致 Keycloak 17 秒重启循环（见 13），以及预演绑定占着 18090（见 15） |
| D | 三条登录链路 + BOL 专项 + 日志 | 8078 / 8090 / 8008 全通过 | BOL 新代码未生效会导致 CSRF 403：先用 C2.0 的 `StartTime` / `LastWriteTime` 判定，再回 C2.2 |
| E | 归档、台账 | 完成，遗留清理项见 E 段台账 | — |

实际总耗时以窗口记录为准：**中断约 40 分钟**，其中口令排查占大头；配置切换本身仍在 15 分钟量级。

**两个最可能翻车的点**：① 只切单个应用（MSIA 会因 `issuer` / `redirect_uri` 主机名不一致直接拒绝，2026-11-11 已发生）→ 必须 Keycloak + 三份 issuer + 应用回环同窗口整体切；② BOL 新 exe 未真正带上 `SECURE_PROXY_SSL_HEADER` → 表现为「能登录、点什么都失败」，容易误判为会话问题而反复重启。
