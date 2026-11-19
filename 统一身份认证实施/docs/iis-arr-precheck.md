# IIS / ARR / URL Rewrite 在位核查（方案 2 第一道门）

> 用途：在决定是否执行「三个应用上 HTTPS + 同主机名不同端口 + 前置反向代理」之前，先确认反代能力是否具备。
> **核查部分只含只读命令**：不安装、不修改、不重启任何服务。唯一例外是第 4 节里随「补齐顺序」给出的安装 / 开启命令，那些是参考命令，必须在批准过的变更窗口内单独执行，不属于本页的核查动作。
> 所有命令需要在**服务器上以管理员 PowerShell** 执行（`netsh http` 与 `Get-WebGlobalModule` 需要管理员）。
> 判据统一按三态标注：**在**（已安装且生效）／**不在**（未安装）／**装了但没启用**（组件在、代理开关或绑定没开）。

---

## 1. IIS 是否安装

### 1.1 功能安装状态（两种系统写法都跑，报错的那个忽略）

```powershell
# Server（Windows Server 2012 及以上）
Get-WindowsFeature -Name Web-Server, Web-Mgmt-Console, Web-WebSockets, Web-Static-Content -ErrorAction SilentlyContinue |
    Select-Object Name, InstallState

# Win10 / Win11（客户端系统）
Get-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole, IIS-WebServer, IIS-ManagementConsole -ErrorAction SilentlyContinue |
    Select-Object FeatureName, State
```

判据：

- `InstallState = Installed` 或 `State = Enabled` → **在**
- `Removed` / `Disabled` / 命令报「找不到功能」→ **不在**
- 两组命令都报错 → 当前不是 Windows 或权限不足，先确认执行环境

### 1.2 服务与进程

```powershell
Get-Service W3SVC, WAS -ErrorAction SilentlyContinue | Select-Object Name, Status, StartType
Test-Path "$env:SystemRoot\System32\inetsrv\appcmd.exe"
Get-Process w3wp -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime
```

判据：

- `W3SVC` 存在且 `Running` + `appcmd.exe` 存在 → **在**（正在跑）
- `W3SVC` 存在但 `Stopped` → **装了但没启用**（可 `Start-Service W3SVC` 后再看，本页不执行）
- 服务不存在、`appcmd.exe` 不存在 → **不在**

### 1.3 站点与端口占用

```powershell
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list site
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list vdir

Get-NetTCPConnection -LocalPort 80,443 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess,
        @{ n = 'Process'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } }
```

判据：

- `list site` 有输出且含 `Default Web Site` → IIS 有站点；`list site` 报错或无输出 → **没有站点**（IIS 可能装了但未配置）
- 80/443 的 `Process` 为 `System`（`http.sys` 以内核态持有）→ 被 http.sys/IIS 占用；为 `w3wp` → IIS 工作进程；为空或其它进程 → 非 IIS 占用
- 80 无监听、443 有监听但属 `System` → 典型「IIS 有 443 绑定但证书没配好」或「iphlpsvc / 其它 http.sys 使用者」，需配合第 3 节确认

---

## 2. ARR（Application Request Routing）与 URL Rewrite 是否安装

> 结论以 **2.2 的模块列表** 为准；1.1 的目录探测只作旁证（升级/静默安装可能改变路径）。

### 2.1 目录与程序集探测

```powershell
'test ARR  ' , (Test-Path 'C:\Program Files\IIS\Application Request Routing')
'arr dll   ' , (Test-Path "$env:SystemRoot\System32\inetsrv\requestRouter.dll")
'rewrite   ' , (Test-Path "$env:SystemRoot\System32\inetsrv\rewrite.dll")
'urlrw dir ' , (Test-Path 'C:\Program Files\IIS\URL Rewrite')

Get-ChildItem 'C:\Program Files\IIS' -ErrorAction SilentlyContinue | Select-Object Name, LastWriteTime
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Application Request Routing|URL Rewrite|IIS' } |
    Select-Object DisplayName, DisplayVersion, InstallDate
```

判据：

- `requestRouter.dll` 存在 → ARR **在**；`rewrite.dll` 存在 → URL Rewrite **在**
- 两个 dll 都不在、`C:\Program Files\IIS` 目录不存在 → 两者**都不在**
- 卸载表里能看到 `Application Request Routing 3.0` / `URL Rewrite Module 2.1` → 安装记录在（可与 dll 对照，判断是否装过又坏了）

### 2.2 全局模块（权威判据）

```powershell
Import-Module WebAdministration -ErrorAction SilentlyContinue
Get-WebGlobalModule -ErrorAction SilentlyContinue |
    Select-Object Name, Image |
    Where-Object { $_.Name -match 'ApplicationRequestRouting|Rewrite' }

& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list module |
    Select-String -Pattern 'ApplicationRequestRouting|Rewrite'
```

判据：

- 出现 `ApplicationRequestRouting`（`Image` 指向 `requestRouter.dll`）→ ARR **在**
- 出现 `Rewrite`（`Image` 指向 `rewrite.dll`）→ URL Rewrite **在**
- `Get-WebGlobalModule` 直接报「无法识别 cmdlet」→ IIS 管理模块没装，只能靠 2.1 的 dll 探测 + 2.3 的 config 判断
- 两个模块都查不到 → 反代能力**不在**，方案 2 进入第 4 节分支

### 2.3 配置文件与代理开关

```powershell
Select-String -Path "$env:SystemRoot\System32\inetsrv\config\applicationHost.config" `
    -Pattern 'applicationRequestRouting|requestRouter|rewrite' |
    Select-Object LineNumber, Line

# ARR 的代理开关（未装 ARR 时该节不存在，命令会报「无法识别的配置节」）
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list config /section:system.webServer/proxy

# 若 IIS 在跑，顺便看已启用的节
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list config /section:system.webServer/proxy /config:* 2>$null |
    Select-String -Pattern 'enabled'
```

判据：

| 输出 | 含义 |
|---|---|
| `applicationHost.config` 有 `<globalModules>` 里的 `requestRouter`，且 `list config /section:system.webServer/proxy` 返回 `enabled="true"` | ARR **在**且**已启用** |
| 有该节但 `enabled="false"` | **装了但没启用**（这是最常见的「ARR 装了却不反代」原因） |
| 命令报「无法识别的配置节」或 config 里完全无 `requestRouter` | ARR **不在** |

---

## 3. 443「TCP 能连、TLS 无应答」的空绑定排查

已知现象（此前从客户端观测）：**443 端口 TCP 握手成功，随后 TLS 握手被对端关闭，`Authentication failed because the remote party has closed the transport stream`；对 443 发明文 HTTP 则超时。**

```powershell
# 3.1 谁在监听 443
Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess,
        @{ n = 'Process'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } }

# 3.2 http.sys 的 URL 注册（是否真有站点在 443 上收请求）
netsh http show servicestate

# 3.3 http.sys 的 SSL 证书绑定（443 是否绑了证书）
netsh http show sslcert

# 3.4 URL 保留
netsh http show urlacl | Select-String -Pattern ':443|:80'

# 3.5 已注册的 SNI 主机名绑定
netsh http show sslcert | Select-String -Pattern 'Hostname|Certificate Hash|IP:port'
```

判据与解释：

| 组合 | 含义 |
|---|---|
| `show sslcert` 的 `SSL Certificate bindings` 段为空（或只有 `:8443` 之类非 443 条目），`show servicestate` 也无 `:443` 的请求队列 | **443 上没有 IIS/ http.sys 的 HTTPS 端点**：TCP 能连是防火墙放行、由 `System` 直接关流；对方案 2 来说等于「没有现成反代」，必须新建绑定 |
| `show sslcert` 有 `0.0.0.0:443` 但 `Certificate Hash` 为空 / 绑定指向已删除的证书 | **装了但没配好**：http.sys 有绑定、无可用证书，TLS 握手被立刻中止——与「TCP 通、TLS 断」高度吻合 |
| `show sslcert` 有 `0.0.0.0:443` 且证书哈希有效，`show servicestate` 有请求队列 | 443 上是**正常工作**的 HTTPS 站点（此时客户端应能拿到 TLS 响应；若仍失败，问题在客户端或中间设备） |
| 443 的 `OwningProcess` 不是 `System`/`4` | 非 http.sys 进程占用，需按 PID 查是谁（可能正是导致无 TLS 响应的原因） |

> 说明：`netsh http show servicestate` 与 `show sslcert` 都以 `http.sys` 为准。若这两条命令输出为空，但 443 仍可连接，说明占用者不是 http.sys——这种情况方案 2 不能直接复用 443，也不建议复用（会被别的进程抢绑定）。

---

## 4. ARR 缺失时的判定分支

现场环境已确认：**Windows Server 2016 Standard（10.0.14393，1607）、64 位、完整桌面体验（非 Server Core）**，对应 **IIS 10.0**。以下第 4.1–4.6 节即按此环境写定。

### 4.1 版本结论（不需要再找更高版本号）

| 组件 | 安装包 | 版本 | 架构 | 结论 |
|---|---|---|---|---|
| URL Rewrite | `rewrite_amd64_en-US.msi` | **2.1** | x64 | 当前最新正式版；微软未发布 2.2/3.x，不必再找更新版本 |
| Application Request Routing | `requestRouter_amd64.msi` | **3.0** | x64 | 当前最新正式版；ARR 3.0 即为终版，没有 4.x |

两者的关系：**ARR 3.0 依赖 URL Rewrite 2.x**，所以 URL Rewrite 是前置件，不是可选项。32 位包（`*_x86.msi`）在此环境一律不要用——系统是 64 位，IIS 工作进程是 64 位，装 32 位包模块不会注册到正确的 `inetsrv` 下。

### 4.2 安装顺序（顺序不能反）

```powershell
# 1) 先确保 IIS 角色完整（含管理工具，否则没有 appcmd / WebAdministration）
Install-WindowsFeature Web-Server -IncludeManagementTools

# 2) 再装 URL Rewrite 2.1（rewrite_amd64_en-US.msi）

# 3) 最后装 ARR 3.0（requestRouter_amd64.msi）

# 4) 装完必须重载 IIS，模块才会被加载
iisreset
```

顺序反了的后果（两种都会遇到）：

| 反法 | 现象 | 处理 |
|---|---|---|
| 先装 ARR 3.0、后装 URL Rewrite 2.1 | ARR 安装程序在前置检查阶段就报「需要先安装 URL Rewrite」，安装直接失败、回滚 | 装好 URL Rewrite 后重装 ARR |
| 两个都装成功，但 ARR 装在 URL Rewrite 之前（例如 URL Rewrite 后补装） | 表面都成功了：`requestRouter.dll` 在、`proxy` 节也在，**但转发不生效**（`enabled=true` 时仍 502/404，或 rewrite 规则不执行） | 先卸载 ARR，再按 URL Rewrite → ARR 的顺序重装，然后 `iisreset` |

#### 4.2.1 静默安装会隐藏错误（现场已发生过一次）

`Start-Process msiexec.exe -ArgumentList '/i ... /qn /norestart' -Wait` 的 **`-Wait` 只等进程退出，不告诉你结果**。MSI 失败时会自己回滚：文件不落地、卸载表无记录、提示全被 `/qn` 吃掉，看起来"装完了"，实际什么都没装。判断装没装成，只有两条路：**退出码** 与 **MSI 日志**。

固定写法（以后所有 MSI 安装都按这个写）：

```powershell
$log = 'C:\Temp\iis-setup\arr-install.log'
$p = Start-Process msiexec.exe -ArgumentList "/i C:\Temp\iis-setup\requestRouter_amd64.msi /qn /norestart /l*v `"$log`"" -Wait -PassThru
"ExitCode = $($p.ExitCode)"
```

退出码含义（`-PassThru` 拿到的 `ExitCode`）：

| 退出码 | 含义 | 该怎么办 |
|---|---|---|
| `0` | 成功 | 继续下一步验证 |
| `3010` | **成功，但需要重启**才完全生效 | 记下来，先重启或继续装完再统一重启；不要当成失败重装 |
| `1603` | 安装过程中发生致命错误（MSI 的通用失败码，具体原因只在日志里） | 打开 `/l*v` 日志，搜 `Return value 3` 定位是哪个动作失败 |
| `1602` | 用户取消 / 安装被中止 | 多为交互安装被关闭，或安装程序主动中止；看日志末尾 `Installation success or error status` |
| `1618` | 另一个安装正在进行 | 等前一个结束（常见于连续两条 `Start-Process` 没等干净），重跑 |
| `1619` / `1620` | 包无法打开 / 包无效 | 文件损坏或不是 MSI，重新拷贝并核对签名 |
| `1625` | 被组策略禁止安装 | 找域策略，或改用离线安装介质流程 |
| `1638` | 已安装同版本的另一产品 | 先卸载旧版本 |

日志里只搜这几个关键字就够：

```powershell
Select-String -Path 'C:\Temp\iis-setup\arr-install.log' -Pattern 'Return value 3|Installation failed|LaunchCondition|CustomAction .* returned|MainEngineThread is returning|Product: .* --'
```

判读：

- 出现 `Return value 3` → 紧接着的几条就是失败的那一步（MSI 用 3 表示"该动作失败并回滚"）；
- 出现 `LaunchCondition` 相关条目 → **前置条件不满足**（最常见：IIS 未安装、系统版本不符）；
- 出现 `Product: Application Request Routing 3.0 -- Installation failed.` → 确认整包回滚，文件不会留下；
- 一条都没有且退出码为 0 → 装成功了，问题在"装到哪去了"（见 4.5 的 dll 位置说明）。

#### 4.2.2 装之前先验前置依赖（顺序不能反的真正原因）

三条依赖是硬性的，任何一条不满足，后一个包会**直接失败并回滚**：

| 安装对象 | 硬前置 | 不满足时的现象 |
|---|---|---|
| URL Rewrite 2.1 | IIS 已安装（`Web-Server` = `Installed`，`W3SVC` 存在，`inetsrv` 目录在） | 退出码 `1603`，日志里有 `LaunchCondition`；`rewrite.dll` 不落地 |
| ARR 3.0 | IIS 已安装 **且** URL Rewrite 已安装 | 同上；即便侥幸装上，`proxy` 节也不会出现、转发不生效 |
| IIS 自身 | Server 2016 安装源（在线或 `-Source` 指向 `sources\sxs`） | `Install-WindowsFeature` 报缺源，功能仍为 `Available` |

装前一条命令自查（只读）：

```powershell
Get-WindowsFeature Web-Server, Web-Static-Content, Web-WebSockets, Web-Mgmt-Console | Select-Object Name, InstallState
Get-Service W3SVC -ErrorAction SilentlyContinue | Select-Object Name, Status
Test-Path "$env:SystemRoot\System32\inetsrv\appcmd.exe"
Get-ChildItem "$env:SystemRoot\System32\inetsrv\rewrite.dll" -ErrorAction SilentlyContinue | Select-Object Name, Length
```

判据：第 1 条全 `Installed`、第 2 条 `Running`、第 3 条 `True`、第 4 条有输出——四条齐了才可以装 ARR。**首条出现 `Available` 就说明 IIS 根本没装**，此时装 URL Rewrite / ARR 必然 1603，先按 4.2.3 补装 IIS。

#### 4.2.3 补装 IIS（Server 2016）

```powershell
# 在线（能访问 Windows Update 或已配置 WSUS）
Install-WindowsFeature Web-Server -IncludeManagementTools

# 脱机（挂载安装介质后，源目录以实际盘符为准）
Install-WindowsFeature Web-Server -IncludeManagementTools -Source 'D:\sources\sxs'

Get-WindowsFeature Web-Server, Web-Mgmt-Console, Web-Static-Content, Web-WebSockets | Select-Object Name, InstallState
Get-Service W3SVC | Select-Object Name, Status, StartType
```

判据：四项全 `Installed`；`W3SVC` 为 `Running`；`Get-ChildItem "$env:SystemRoot\System32\inetsrv\appcmd.exe"` 存在。若安装结果显示 `Restart Needed = Yes`，先重启再继续装 URL Rewrite。

失败先看：报 `0x800f0906` / 缺源 → `-Source` 路径不对（`sources\sxs` 必须在安装介质根下，不是 `install.wim` 所在目录）；报权限 → 用管理员 PowerShell。

判据：`iisreset` 之后按 4.5 逐项确认，三项全过才算「装好了」。

### 4.3 安装包来历校验（以数字签名为准）

把两个 MSI 放在同一目录（例如 `C:\Temp\iis-setup\`），执行：

```powershell
Get-AuthenticodeSignature 'C:\Temp\iis-setup\rewrite_amd64_en-US.msi' |
    Select-Object Status, StatusMessage, @{ n = 'Signer'; e = { $_.SignerCertificate.Subject } }

Get-AuthenticodeSignature 'C:\Temp\iis-setup\requestRouter_amd64.msi' |
    Select-Object Status, StatusMessage, @{ n = 'Signer'; e = { $_.SignerCertificate.Subject } }
```

判据：

- `Status = Valid` **且** `Signer` 中含 `O=Microsoft Corporation`（通常为 `CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US`）→ 包可信，可以装。
- `Status = NotSigned` / `HashMismatch` / `UnknownError`，或签名者不是 Microsoft → **不要装**，换包重取。
- `Status = Valid` 但签名者是第三方（非 Microsoft）→ 不要装。ARR 与 URL Rewrite 的官方 MSI 均由 Microsoft 签名。

### 4.4 Server 2016 特有注意点

| 项 | 事实 | 动作 |
|---|---|---|
| TLS 1.2 | Server 2016 默认启用 TLS 1.2（Schannel 默认含 1.0/1.1/1.2） | 无需额外开启 |
| TLS 1.3 | **Server 2016 不支持 TLS 1.3**（该版本 Schannel 无 TLS 1.3 实现，Server 2022 才有） | 不要按 TLS 1.3 规划证书与客户端；IIS 站点保持 TLS 1.2 即可 |
| 曾被加固脚本关掉 TLS 1.2 | 若有人按「只留 TLS 1.2 以上」以外的策略误关，IIS/ARR 侧握手会失败 | 先只读确认，再在变更窗口恢复 |
| IIS 10.0 与 ARR 3.0 | ARR 3.0 支持 IIS 7.0 及以上，**IIS 10.0 在支持范围内**（虽是 2013 年发布，但在 Server 2016 上正常工作） | 无需降级 IIS，也无需找「适配 IIS 10 的 ARR」 |
| 桌面体验 | 有完整 GUI，IIS 管理器与 PowerShell 都可用 | 不需要 Server Core 的特殊处理 |

TLS 1.2 是否被禁用的只读确认：

```powershell
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2\Server' `
    -ErrorAction SilentlyContinue | Select-Object Enabled, DisabledByDefault

Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2\Client' `
    -ErrorAction SilentlyContinue | Select-Object Enabled, DisabledByDefault
```

判据：

- 键不存在，或 `Enabled = 1`、`DisabledByDefault = 0` → TLS 1.2 **正常**，可继续。
- `Enabled = 0` 或 `DisabledByDefault = 1` → TLS 1.2 **已被禁用**，先恢复（属注册表变更，需单独窗口与重启），否则装好 ARR 也会握手失败。

### 4.5 装完必验三项

```powershell
# 1) 两个模块是否都已注册（iisreset 之后跑）
Import-Module WebAdministration -ErrorAction SilentlyContinue
Get-WebGlobalModule | Where-Object { $_.Name -match 'ApplicationRequestRouting|Rewrite' } |
    Select-Object Name, Image

& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list module |
    Select-String -Pattern 'ApplicationRequestRouting|Rewrite'

# 2) ARR 总代理开关的当前值（默认是 false，必须改成 true 才会真正转发）
& "$env:SystemRoot\System32\inetsrv\appcmd.exe" list config /section:system.webServer/proxy

# 3) 开关的只读确认（看 applicationHost.config 里的实际文本）
Select-String -Path "$env:SystemRoot\System32\inetsrv\config\applicationHost.config" -Pattern '<proxy '
```

判据：

| 检查 | 通过 | 不通过 |
|---|---|---|
| 模块列表 | 出现 `ApplicationRequestRouting`（Image 指向 `requestRouter.dll`）与 `Rewrite`（Image 指向 `rewrite.dll`） | 缺哪个就说明哪个包没装成功，或装了但装完没 `iisreset` |
| `list config /section:system.webServer/proxy` | 能正常返回（说明 ARR 已装），`enabled` 当前值为 `"false"` | 报「无法识别的配置节」→ ARR 未安装或未注册 |
| `applicationHost.config` 中的 `<proxy ` | `enabled="true"` | 为 `false` → 代理总开关没开，所有分发都不会发生 |

补充：**不要用 `C:\Windows\System32\inetsrv\requestRouter.dll` 是否存在来判断 ARR 装没装**。ARR 的模块文件通常在 `C:\Program Files\IIS\Application Request Routing\` 下，不一定落在 `inetsrv`；反过来，`inetsrv` 里没有这个 dll 也完全不等于安装失败。判断装没装，以 `Get-WebGlobalModule` / `appcmd list module` 的模块列表为准；找不到模块时再按下面三条只读命令定位文件与安装记录：

```powershell
Get-ChildItem 'C:\Program Files\IIS','C:\Program Files (x86)\IIS',"$env:SystemRoot\System32\inetsrv","$env:SystemRoot\SysWOW64\inetsrv" `
    -Filter 'requestRouter*' -Recurse -ErrorAction SilentlyContinue | Select-Object FullName, Length, LastWriteTime

Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Application Request Routing|URL Rewrite' } |
    Select-Object DisplayName, DisplayVersion, InstallDate, InstallLocation

Get-ChildItem 'C:\Temp\iis-setup\*.log' -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime
```

判读：文件在 + 卸载表有记录 + 模块列表有 `ApplicationRequestRouting` → 装好了；三者都不在 → 安装被回滚（按 4.2.1 抓退出码与日志重装）；有日志文件就直接按 4.2.1 搜关键字。

开启总开关与转发头白名单的命令（**变更动作，只在此窗口内执行一次**）：

```powershell
$appcmd = "$env:SystemRoot\System32\inetsrv\appcmd.exe"
Import-Module WebAdministration

# ① proxy 段：代理参数（四项都是 proxy 自身的属性）
& $appcmd set config /section:system.webServer/proxy /enabled:"true" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /preserveHostHeader:"true" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /timeout:"00:05:00" /commit:apphost
& $appcmd set config /section:system.webServer/proxy /reverseRewriteHostInResponseHeaders:"false" /commit:apphost

# ② rewrite 段：转发头白名单（不属于 proxy，写法与上面完全不同）
Add-WebConfiguration -PSPath 'MACHINE/WEBROOT/APPHOST' `
    -Filter 'system.webServer/rewrite/allowedServerVariables' -Value @{name='HTTP_X_FORWARDED_PROTO'}
Add-WebConfiguration -PSPath 'MACHINE/WEBROOT/APPHOST' `
    -Filter 'system.webServer/rewrite/allowedServerVariables' -Value @{name='HTTP_X_FORWARDED_FOR'}

# ③ 回读
& $appcmd list config /section:system.webServer/proxy
& $appcmd list config /section:system.webServer/rewrite/allowedServerVariables
```

期望回读：

- `proxy`：`<proxy enabled="true" timeout="00:05:00" preserveHostHeader="true" reverseRewriteHostInResponseHeaders="false">`；
- `rewrite`：含 `<allowedServerVariables><add name="HTTP_X_FORWARDED_PROTO" /><add name="HTTP_X_FORWARDED_FOR" /></allowedServerVariables>`。

不开 `enabled` 时，即使 rewrite 规则、绑定、证书全部正确，请求也只会得到 502 或停留在本地站点——这是「ARR 装了却不反代」最常见的第二个原因（第一个是 4.2 的安装顺序）。

**`allowedServerVariables` 不在 `proxy` 段**：它是 **URL Rewrite** 的设定，完整路径是 `system.webServer/rewrite/allowedServerVariables`，落在 `sectionGroup name="rewrite"` 内；`system.webServer` 下只有 `proxy`（`overrideModeDefault="Deny"`、`allowDefinition="AppHostOnly"`）与 `diskCache` 两个同级 section。把集合挂到 `proxy` 上会被判为未知属性（报 `Unknown attribute`），用 `Add-WebConfigurationProperty -Filter 'system.webServer/proxy' -Name 'allowedServerVariables'` 会报 `Property allowedServerVariables is not found on system.webServer/proxy`。加没加成功，只看 ② 的回读。

#### 4.5.1 配置节路径不明时怎么查

```powershell
# ① 枚举 configSections 下所有 sectionGroup 及其子 section
$cs = ([xml](Get-Content "$env:SystemRoot\System32\inetsrv\config\applicationHost.config")).configuration.configSections
$cs.ChildNodes | Where-Object { $_.NodeType -eq 'Element' } | ForEach-Object {
    [pscustomobject]@{
        Group    = $_.name
        Children = ($_.ChildNodes | Where-Object { $_.NodeType -eq 'Element' } |
                    ForEach-Object { "$($_.LocalName):$($_.name)" }) -join ', '
    }
}

# ② 已知节名、不知归属：看目标节上下 8 行
Select-String -Path "$env:SystemRoot\System32\inetsrv\config\applicationHost.config" `
    -Pattern 'allowedServerVariables' -Context 8, 8
```

判读：① 的 `Children` 里出现 `sectionGroup:rewrite`，即证明该节属于 `rewrite` 而非 `proxy`；② 的输出中，目标行上方最近的 `sectionGroup name="..."` 就是它的归属。

### 4.6 不要用第三方重新打包版本

**只从微软官方渠道或其官方下载直链取 MSI，不要从第三方站点、论坛附件、网盘、"绿色版/集成版/一键包"里取。** 原因：

- 这类包常被重打包注入或改过 `globalModules` 注册，装完表面可用、实际把请求转发到未知地址；
- 重打包后版本号可以随便写，**版本号不能作为可信判据**；
- MSI 一旦被改动，微软签名的哈希即失效，`Get-AuthenticodeSignature` 会立刻显示 `HashMismatch`。

因此本页把**数字签名（`Status = Valid` + 签名者 Microsoft）作为主要判据，版本号只作辅助**：版本号证明"它声称自己是谁"，数字签名证明"它确实是微软发布的那个文件"。

### 4.7 缺什么、要补什么

| 现状 | 需要补的组件 | 说明 |
|---|---|---|
| URL Rewrite 在、ARR 不在 | **Application Request Routing 3.0**（x64 MSI，`requestRouter_amd64.msi`） | ARR 依赖 URL Rewrite，后者已在则只装 ARR |
| 两者都不在 | **URL Rewrite Module 2.1**（`rewrite_amd64_en-US.msi`）+ **ARR 3.0**（`requestRouter_amd64.msi`） | **先装 URL Rewrite，再装 ARR**；顺序反了 ARR 会装不上或模块不注册 |
| IIS 不在 | IIS 角色/功能（Server 2016：`Install-WindowsFeature Web-Server -IncludeManagementTools`，见 4.2；脱机安装需 `-Source D:\sources\sxs`）+ 上述两个 MSI | Server 上装角色通常需要重启；客户端系统用 `IIS-WebServerRole` + `IIS-ManagementConsole` |

安装前置条件（供判断可行性，不在本页执行）：

- **管理员权限**，且安装后通常需要 `iisreset` 才会加载模块；
- IIS 7.0 及以上（本环境若已装 IIS 即满足）；
- 两个 MSI 都是**独立安装包，安装过程不需要联网**，可从任一同版本机器或微软下载中心取来拷贝过去；
- 若机器装过 Web Platform Installer，可先看缓存里是否已有安装包：`C:\Program Files\Microsoft\Web Platform Installer\`（`Get-ChildItem -Recurse -Filter '*.msi'`）。

### 4.8 无外网、又拿不到安装包时的替代

| 替代方案 | 可行性 | 说明 |
|---|---|---|
| 只用 URL Rewrite 做反代 | **不可行** | URL Rewrite 只负责改写规则，真正把请求转发到后端的是 ARR 的 `requestRouter` 代理模块；没有 ARR 时 `system.webServer/proxy` 节都不存在 |
| 换用其它反向代理（nginx for Windows / Caddy / Apache） | 可行，但需另一个安装包 | 与 ARR 一样要「拿到包 + 管理员 + 新端口/新服务」，且运维要新增一套组件 |
| 让三个应用自己上 HTTPS | **不可行（当前条件下）** | MSIA/BOL/Capacity 分别是 uvicorn / waitress / uvicorn，都需要 PEM 私钥；`C:\certs\iame.p12` 的私钥导不出未加密 PKCS#8，本机也没有 openssl；改应用要重新打包 |
| 继续用「一主机名 + 明文端口」 | **不可行** | Keycloak 8443 下发 `Strict-Transport-Security: max-age=31536000; includeSubDomains`，浏览器会把同主机 8078/8090/8000 升级成 https，明文端口必然 `ERR_SSL_PROTOCOL_ERROR` |

结论：**方案 2 必须有一个能终结 TLS 的反向代理**。ARR 之外的选择是另装 nginx/Caddy，代价同样是安装包 + 新组件；不存在「只靠现有组件、零安装」的路径。

---

## 5. 结论：工期落在 3–4 小时还是一整天

把上面几段的结果填进下表，**任一行落在右列即按一整天安排**。

| 结论项 | 判据来源 | 3–4 小时 | 一整天 |
|---|---|---|---|
| IIS | 1.1 / 1.2 | `W3SVC` Running + `appcmd list site` 正常 | 未装，或装了但无站点需从零配 |
| URL Rewrite | 2.2 | 模块 `Rewrite` 存在 | 缺，需装 MSI |
| ARR | 2.2 / 2.3 | 模块 `ApplicationRequestRouting` 存在且 `proxy enabled="true"` | 缺，或装了但 `enabled="false"`（要确认能否安全打开） |
| 443 现状 | 3.5 | 无冲突绑定，可自由新建 | 443 已被未知进程占用，或证书绑定损坏需先修 |
| 证书 | 已有 `C:\certs\IRSCNKettle01.pfx`（含私钥，可被 IIS 直接导入） | 可直接用 | — |
| BOL 的 Django 代理头 | 已知 `settings_prod.py` 无 `SECURE_PROXY_SSL_HEADER` | — | 需改代码并**重新打 PyInstaller exe**，属计划外工作量 |
| 后端改绑回环 | MSIA `[server] host`、BOL `--host` | 纯配置 | — |

**读法**：

- 前四行全部落在「3–4 小时」列 → 方案 2 可按 **3–4 小时**排（主要是建站点、绑证书、写 rewrite、改绑回环、改 redirect URI、验证）。
- 任何一行落在「一整天」列 → 按 **1 个整天**排；若同时命中「ARR 缺失」和「BOL 需重建 exe」，实际是 **1 天 + 打包回归**，建议单独排窗口，不要与回滚或其它变更同窗口。
- 若第 4 节的替代方案被触发（另装 nginx/Caddy），工期按「新组件引入」重新评估，不再是 3–4 小时量级。
