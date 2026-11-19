# Windows 服务化操作手册（单线执行版）

起点并不统一：**Keycloak 已是 `Running / Automatic` 的系统服务**，**MSIA-Server 服务存在但 `Stopped`**（当前跑的是控制台进程），**BOL 只有控制台进程**，**CapacityAPI 也只有控制台进程**（监听 8000，是第四个 SSO 客户端）。终点是四个服务都在运行、重启服务器后无需登录即可用。

全程 14 步，另有第 8.5 步（CapacityAPI）共 15 步，按顺序执行。每步做完对照"应看到"，不对就停，不要往下走。

> 全文命令都在**同一台机器**上执行：四个应用所在的服务器。四个程序分处多台机器时，在各机器上分别执行属于本机的步骤。

---

## 先填这张表

命令中出现的 `<...>` 全部来自本表，正文不再解释怎么取值。

| 占位符 | 填什么 | 从哪里查（按顺序，取先有值的） | 示例形态 |
|---|---|---|---|
| `<脚本目录>` | 已放好 `register-services-nssm.ps1` 的目录 | 固定为 `C:\Services`，脚本就放在这里 | `C:\Services` |
| `<BOL目录>` | `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer`（已实测，无需再查） | 复核用 `process.txt` 中 `BOLServer.exe` 那条的 `ExecutablePath` | `C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer` |
| `<JAVA_HOME>` | `C:\Program Files\Java\jdk-21.0.10`（已实测，Keycloak 进程正在用） | 复核用 `process.txt` 中占用 8443 的 `java.exe` 的 `ExecutablePath` | `C:\Program Files\Java\jdk-21.0.10` |
| `<证书PEM>` | `C:\keycloak\conf\server.crt.pem`（已实测，1103 字节，当前在用） | 复核用 `Get-ChildItem C:\keycloak\conf\*.pem` | `C:\keycloak\conf\server.crt.pem` |

四项均已确认，正常执行时无需现场取值；若现场与表中不符，以现场为准并同步改本表。

---

## 第 1 步 放脚本、抄下现有环境变量（5 分钟）

**做什么**：把脚本放到固定目录，并导出当前已持久化的环境变量与三个进程的启动命令行。

**在哪**：应用所在服务器，管理员 PowerShell。

**命令**：先把 `register-services-nssm.ps1` 复制到 `C:\Services\`，然后执行：

```powershell
$bk = 'C:\Services\baseline'
New-Item -ItemType Directory -Path C:\Services\logs,$bk,C:\Services\rollback -Force | Out-Null
Get-Item C:\Services\register-services-nssm.ps1 | Select-Object FullName, Length

# BOL 的 OIDC 配置在 db_config.ini，不在环境变量，故不采集
$names = 'JAVA_HOME','KC_DB_PASSWORD','KC_HTTPS_KEY_STORE_PASSWORD','SSL_CERT_FILE','JWT_SECRET_KEY'
$names | ForEach-Object {
    [pscustomobject]@{
        Name    = $_
        Machine = [Environment]::GetEnvironmentVariable($_, 'Machine')
        User    = [Environment]::GetEnvironmentVariable($_, 'User')
    }
} | Format-Table -AutoSize | Out-File "$bk\env-persisted.txt" -Encoding utf8

Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(java|msia_server|BOLServer)\.exe$' } |
    Select-Object Name, ProcessId, ExecutablePath, CommandLine |
    Format-List | Out-File "$bk\cmdline.txt" -Encoding utf8

Get-Content "$bk\env-persisted.txt", "$bk\cmdline.txt"
```

**应看到**
- `FullName` 为 `C:\Services\register-services-nssm.ps1`，`Length` 大于 0。
- `env-persisted.txt` 是一张 `Name / Machine / User` 三列表。**整列为空是正常的**：`SSL_CERT_FILE`、`JAVA_HOME` 等平时只在启动窗口里临时设置，不会出现在这里；这些值要按开头表格"从哪里查"列的下一处去取。
- `cmdline.txt` 有 4 条记录：两个 `java.exe`（一条是帆软 `C:\Kettle\FineReportPublish\jdk`，一条是 Keycloak `C:\Program Files\Java\jdk-21.0.10`）、一个 `msia_server.exe`、一个 `BOLServer.exe`，每条带 `ExecutablePath`。

只有 **MSIA 与 BOL 有控制台窗口**，这两个窗口保持运行，后面切换服务时要在这个窗口里按 `Ctrl+C`。Keycloak 已是服务，没有控制台窗口。

---

## 第 2 步 采进程、端口、服务基线（3 分钟）

**做什么**：记下现在的进程路径与端口占用，回滚和填表都要用。

**在哪**：管理员 PowerShell。

**命令**

```powershell
$bk = 'C:\Services\baseline'
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(java|msia_server|BOLServer)\.exe$' } |
    Select-Object Name, ProcessId, ExecutablePath, CommandLine |
    Format-List | Out-File "$bk\process.txt" -Encoding utf8
netstat -ano | findstr /R /C:":8443 " /C:":9000 " /C:":8078 " /C:":8090 " | Out-File "$bk\ports.txt" -Encoding utf8
Get-Service | Where-Object { $_.Name -match 'Keycloak|MSIA|BOL' } | Format-Table Name, Status, StartType -AutoSize |
    Out-File "$bk\services.txt" -Encoding utf8
Get-FileHash 'C:\keycloak\conf\keycloak.conf' -Algorithm SHA256 | Out-File "$bk\hashes.txt" -Encoding utf8
Get-Content "$bk\process.txt", "$bk\ports.txt"
```

**应看到**
- `process.txt` 有 4 条记录：两个 `java.exe`（帆软与 Keycloak）、`msia_server.exe`、`BOLServer.exe`，每条都有 `ExecutablePath`。
- `ports.txt` 有 `LISTENING` 行，覆盖 8443、9000、8078、8090。**8000 属于 `CapacityAPI`**（第 8.5 步起纳入本手册），不要拿它判断 MSIA。
- `services.txt` 只有两行：`Keycloak`（`Running` / `Automatic`）与 `MSIA-Server`（`Stopped` / `Automatic`），**没有 `BOL-Server`**。这两个服务全程原样保留，本手册不删除、不重装。

---

## 第 3 步 填表（2 分钟）

**做什么**：用前两步的输出填好开头的表。

**在哪**：任意文本编辑器。

**命令**

```powershell
notepad C:\Services\baseline\env-persisted.txt
notepad C:\Services\baseline\process.txt
```

**应看到**：四个占位符全部有确定值，无需再查现场。`env-persisted.txt` 里没有对应项是正常的（见第 1 步）。

---

## 第 4 步 只读预检（2 分钟）

**做什么**：确认 nssm、程序路径、证书、端口、JAVA_HOME 都成立。本步不写任何配置。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Precheck -CertFile '<证书PEM>'
```

**应看到**
- 第一行是 `[INFO] 脚本版本 2.2.1 · SHA256 前 8 位 ...`。**先核对这一行**：版本不是 2.2.1，说明 `C:\Services` 下是旧副本，重新从工程目录复制后再执行，否则后面的报错都不作数。
- `[ OK ] nssm 可用: ...`
- BOL 与 Capacity 段出现 `主程序存在`、`工作目录: ...`、`服务名可用: BOL-Server` / `服务名可用: CapacityAPI`（四个里只有这两个需要新建）。
- Keycloak 与 MSIA 段出现 `[WARN] 服务已存在`，并带当前 `Status / StartType` —— **这是预期的**，本手册对这两个服务只确认不重装。
- 端口检查是 `[WARN] 端口 xxxx 已被占用`，并列出当前控制台进程 —— 控制台实例还在跑，属正常。

出现 `[FAIL]` 就停，按提示改参数后重跑本步。

---

## 第 5 步 确认 MSIA 既有服务（3 分钟）

**做什么**：回读 11-06 手工注册的 `MSIA-Server` 现有配置，确认它指向的就是当前在跑的 exe。本步不注册、不写任何配置。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Register -App MSIA
```

**应看到**
- `[WARN] 服务已存在（Stopped / Automatic），跳过安装与参数写入，仅做只读校验。`
- `现有 Application = C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe`
- `现有 AppDirectory = C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server`（未设置时显示 `(空)`）
- `现有 ObjectName = LocalSystem`
- `本服务未做任何改动。加 -Force 才会按本规范覆盖标准参数与环境变量。`

若 `Application` / `AppDirectory` 与上面不一致会多一行 `[WARN] 服务内 xxx 与本脚本预期不一致（实际 "…"，预期 "…"）`，此时**停**，以现场值为准记录下来，不要加 `-Force`。脚本回读时已剔除 `nssm` 输出里的编码噪声，出现这行就是值真的不同。

**这一步暴露的风险**：该服务是 `Automatic` 却处于 `Stopped`，说明它现在不受控——一旦服务器重启，它会自动拉起 11-06 手工填的那套配置，与将来控制台实例的设置不一定一致。所以下一步必须把它切到服务并验证通过，不能留着半开状态。

---

## 第 6 步 切换 MSIA 到服务（5 分钟）

**做什么**：给既有服务补上 `SSL_CERT_FILE`，然后停掉 MSIA 控制台，改由服务运行并验证。

**在哪**：先到管理员 PowerShell（`C:\Services`），再到 MSIA 控制台窗口。

**命令**（第一段在管理员 PowerShell 执行；按 `Ctrl+C` 后再执行第二段）

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action SetEnv -App MSIA -CertFile '<证书PEM>' -SecretMode Keep
```

到 MSIA 控制台窗口按 `Ctrl+C`，等窗口回到命令提示符（约 10 秒），再执行：

```powershell
Set-Location C:\Services
Get-NetTCPConnection -LocalPort 8078 -State Listen -ErrorAction SilentlyContinue
.\register-services-nssm.ps1 -Action Start  -App MSIA
.\register-services-nssm.ps1 -Action Verify -App MSIA
```

`-Action SetEnv` 只合并环境变量，不碰 `Application`、`ObjectName` 与标准参数，因此不会改掉 11-06 手工配的运行账号；`-SecretMode Keep` 让它不提示任何口令。

**应看到**
- `[ OK ] 已更新 1 项`，随后回读里有 `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`
- 若出现 `环境变量只在新进程生效：必须重启服务`，属正常提示，下一步 `Start` 已经等价于重启
- 端口检查**没有任何输出**，说明 8078 已释放；有输出就先别往下走。
- `[ OK ] 服务状态 Running`
- `[ OK ] 端口 8078 处于 LISTENING`
- `[ OK ] 接口可访问: http://127.0.0.1:8078/api/auth/config（HTTP 200）`
- `校验结果: 全部 PASS`

再用一个真实账号在浏览器登录一次 MSIA，**能跳转到 Keycloak 并成功跳回首页**才算"能连 Keycloak"。通过后才可以关 MSIA 控制台窗口。

`[FAIL] 端口 8078 已被占用` 说明控制台进程没退干净，回控制台窗口确认进程已结束，再重跑 `-Action Start`。

---

## 第 7 步 注册 BOL 服务（3 分钟）

**做什么**：把 `BOLServer.exe` 注册为服务，环境变量只写 `SSL_CERT_FILE`。本步不启动服务。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Register -App BOL -CertFile '<证书PEM>'
```

**应看到**
- `[ OK ] 服务已注册`、`[ OK ] 标准参数写入完成`
- 回读环境变量里**只有** `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`
- `[ OK ] 注册阶段完成（服务未启动）`

**注意**
- BOL 的 OIDC 与 CORS 全部来自 `<BOL目录>\db_config.ini` 的 `[oidc]` 段，**不在服务层配置**，脚本也不会写任何 `OIDC_*`。手工往服务里加会造成双源头，且 `client_secret` 会以明文进注册表。
- `db_config.ini` 当前 `redirect_uri` 无尾斜杠，而 Django 路由带尾斜杠，靠 `APPEND_SLASH` 的 301 兜住；将来换域名时，Keycloak 登记的 URI 必须与该配置逐字符一致（含/不含尾斜杠都要对应）。

`[FAIL] 主程序路径无效` 说明 `-BolExe` 默认值与现场不符，按 `process.txt` 核对后显式传入。

---

## 第 8 步 切换 BOL 到服务（5 分钟）

**做什么**：停掉 BOL 控制台，改由服务运行并验证。

**在哪**：先到 BOL 控制台窗口，再到管理员 PowerShell（`C:\Services`）。

**命令**：在 BOL 控制台窗口按 `Ctrl+C`，等窗口回到提示符。然后：

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Start  -App BOL
.\register-services-nssm.ps1 -Action Verify -App BOL
```

**应看到**
- `[ OK ] 服务状态 Running`
- `[ OK ] 端口 8090 处于 LISTENING`
- `[ OK ] 接口可访问: http://127.0.0.1:8090/（HTTP 200）`
- `校验结果: 全部 PASS`

再打开 BOL 走一次统一登录，能进首页。**通过后才可以关 BOL 控制台窗口。**

---

## 第 8.5 步 注册 CapacityAPI 并切换到服务（5 分钟）

**做什么**：把 `CapacityAPI.exe` 注册为服务，补上 `SSL_CERT_FILE` 证书信任，停掉控制台实例后改由服务运行并验证。

**它是第四个 SSO 客户端**：与 BOL 同一技术栈（Python/FastAPI + uvicorn），同样靠 `SSL_CERT_FILE` 信任 Keycloak 的自签证书。控制台时代这个变量是人工在窗口里设的；服务化后跑在 `LocalSystem` 下没有它，日志会直接报：

```
OIDC discovery 拉取失败：[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate
OIDC 登录跳转失败：idp_unreachable
```

**为什么要做**：CapacityAPI 现在是一个控制台进程（监听 `0.0.0.0:8000`），现场观察到它的 PID 在重启前变过 —— 说明它自己会崩、或被别的操作带重启；崩了没有人拉起来，报错也只留在窗口里滚过去。服务化后由 NSSM 自动重启，并把 stdout/stderr 落到 `C:\Services\logs\CapacityAPI-*.log`，**崩溃自动重启与日志留存就是这次的主要收益**。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**（一次做完）

```powershell
# 1) 先记录现状，并确认 8000 由谁占着
Get-CimInstance Win32_Process -Filter "Name='CapacityAPI.exe'" |
    Select-Object ProcessId, ExecutablePath, CommandLine
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

# 2) 注册（不启动），再补证书信任
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Register -App Capacity
.\register-services-nssm.ps1 -Action SetEnv  -App Capacity -CertFile '<证书PEM>' -SecretMode Keep
```

`1)` 有输出说明控制台实例还在跑。**先到那个控制台窗口按 `Ctrl+C`**，等窗口回到命令提示符、`Get-NetTCPConnection` 不再输出，再继续：

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Start  -App Capacity
.\register-services-nssm.ps1 -Action Verify -App Capacity
```

> 已经用 2.2.0 注册过 CapacityAPI 的现场：**不用卸载重装**，直接跑上面那条 `-Action SetEnv -App Capacity -CertFile '<证书PEM>' -SecretMode Keep`，再 `Start` 一次让新环境变量生效。

**应看到**
- Register：`[ OK ] 服务已注册`、`[ OK ] 标准参数写入完成`
- Register：`[ OK ] 环境变量已写入（共 1 项，合并语义，未涉及的变量保持不变）`，回读里是 `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`
- Register：`Application = C:\ApplicationFile\ExecuteProgram\Capacity\publish\CapacityAPI\CapacityAPI.exe`、`AppDirectory = C:\ApplicationFile\ExecuteProgram\Capacity\publish\CapacityAPI`
- Register：`[ OK ] 注册阶段完成（服务未启动）。下一步：停掉控制台实例，再 -Action Start。`
- SetEnv：`[ OK ] 已更新 1 项`，随后 `[INFO] 回读确认（仅非敏感键，原样打印注册表里的值）:` 下面一行 `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`
- Start：`[INFO] 正在启动...`、`[ OK ] 服务状态 Running`、`[ OK ] 端口 8000 处于 LISTENING`
- Verify：`[ OK ] 服务状态 Running（实际 Running）`、`[ OK ] 端口 8000 处于 LISTENING`
- Verify：`[ OK ] 环境变量已配置: SSL_CERT_FILE`、`[ OK ] SSL_CERT_FILE 指向的文件存在: C:\keycloak\conf\server.crt.pem`
  —— 这两条与 MSIA / BOL 完全相同，是"它真的能信任 Keycloak"的判据，缺一条就不算通过。
- Verify：`[ OK ] 接口可访问: http://127.0.0.1:8000/health（HTTP 200）`
  —— 命中哪条取决于该应用实际暴露的路由。脚本按 `/health` → `/openapi.json` → `/docs` → `/` 的顺序依次试，**任一个 200 即通过**，输出里只出现真正命中的那一条。
- Verify：`校验结果: 全部 PASS`

四条候选都失败时才判 `[FAIL] 接口无响应，已试: http://127.0.0.1:8000/health、http://127.0.0.1:8000/openapi.json、http://127.0.0.1:8000/docs、http://127.0.0.1:8000/`，并提示看 stderr 尾部。这条文案会把试过的路径全列出来，据此就能分清是"端口没起"还是"路由都不匹配"。

**再确认一次 SSO 真的通了**（`Verify` 只能证明证书文件存在，证明不了应用读到了它）：

```powershell
Get-Content C:\Services\logs\CapacityAPI-stderr.log -Tail 40 |
    Select-String 'CERTIFICATE_VERIFY_FAILED|idp_unreachable|OIDC'
```

看**本次重启之后**的时间戳：不应再出现 `CERTIFICATE_VERIFY_FAILED` / `idp_unreachable`（更早的旧行是切换前的，忽略）。然后打开 Capacity 页面点一次统一登录，能跳到 Keycloak 登录页并成功跳回，才算通过。

> **现场教训：判断应用是否接 SSO，不要看配置文件，要看日志。** CapacityAPI 的配置里确实没有 OIDC 段，我据此判成"不接 SSO"，结果它和 BOL 同栈、OIDC 参数由代码或启动脚本注入，日志里一直有 `OIDC discovery 拉取失败` / `idp_unreachable`。判据只有两个：**日志里有没有 OIDC 相关输出**、**点一次统一登录看跳不跳**。控制台时代靠人工 `set SSL_CERT_FILE` 跑通的系统，服务化后必然缺这一条 —— 所以每个新接入的应用，`Verify` 里都必须看到 `环境变量已配置: SSL_CERT_FILE`。

**注意**
- `-App` 的取值是 **`Capacity`**，不是服务名 `CapacityAPI.exe` / `CapacityAPI`；写成服务名会被 `ValidateSet` 直接拒绝（`The argument "CapacityAPI.exe" does not belong to the set "Keycloak,MSIA,BOL,Capacity,All"`）。
- 只在 `StaticEnv` 里写 `SSL_CERT_FILE` 这一条，不要用 `-ExtraEnv` 再补 OIDC 参数：它的 OIDC 配置在应用自身，从服务层写会形成双源头。
- 出错先看 `C:\Services\logs\CapacityAPI-stderr.log` 尾部；怀疑反复重启时用 `-Action Status` 看 PID 是否在变，再对照 `-stderr.log` 的时间。
- `Start` 报 `端口 8000 已被占用` 就是控制台实例没退干净，回那个窗口确认进程结束再重跑。

---

## 第 9 步 确认 Keycloak 既有服务（5 分钟）

**做什么**：回读已在运行的 Keycloak 服务配置，确认它指向 `kc.bat` 且账号为预期值。本步不注册、不写任何配置、不重启。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Register -App Keycloak
```

**应看到**
- `[WARN] 服务已存在（Running / Automatic），跳过安装与参数写入，仅做只读校验。`
- `现有 Application = C:\keycloak\bin\kc.bat`（若显示 `cmd.exe` 包装或其它值，属现场实现差异，记下来即可）
- `现有 ObjectName = ...`
- `本服务未做任何改动。加 -Force 才会按本规范覆盖标准参数与环境变量。`

**不要加 `-Force`**：Keycloak 当前 Running，覆盖参数会改动一个正在提供登录的服务。若确实要统一它的日志/重启策略，放到后续独立窗口做。

---

## 第 10 步 验证 Keycloak 服务（10 分钟）

**做什么**：确认既有服务本身健康，登录链路可用。本步不启动、不停止、不切换。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Verify -App Keycloak
```

**应看到**
- `[ OK ] 服务状态 Running`
- `[ OK ] 端口 8443 处于 LISTENING`、`[ OK ] 端口 9000 处于 LISTENING`
- `[ OK ] OIDC discovery 可达: https://iame.ap.inalfa.local:8443/realms/inalfa/.well-known/openid-configuration（HTTP 200，协商协议 Tls12）`
  —— 这是 Keycloak 的**主判据**，也正是 MSIA / BOL / Capacity 登录依赖的端点；这一行 OK 就说明"能提供登录"。括号里的"协商协议"是探针实际握手用的版本，正常就是 `Tls12`。
- `[WARN] 管理口未暴露健康端点（TCP 可连但零字节关闭），不影响登录，可忽略: http://127.0.0.1:9000/health/ready`
  —— 9000 管理口只作参考，**不计入失败**，出现这行仍算通过，不要为它去调整 Keycloak。
- `校验结果: 全部 PASS`

**域名与回环的先后**：探针先按对外域名 `iame.ap.inalfa.local` 探（`hostname-strict=true` 时用 `127.0.0.1` 作 Host 会被 403），域名通就只用域名。**证书/域名切换完成前**，域名还绑在旧 IP 上，会先出现一行：

```
[INFO] 按 https://iame.ap.inalfa.local:8443/... 探测失败（...），回退到 https://127.0.0.1:8443/... 继续；证书/域名切换完成前这属于预期。
```

随后回环探测 PASS，并补一行 `[WARN] 对外域名 ... 尚不可达，本次判定用的是本机回环地址；证书/域名切换完成后这一行应消失` —— **切换完成前出现这对 INFO/WARN 属正常**，不是故障。切换完成后再跑一次，这两行都应消失。域名可换：加 `-KeycloakProbeHost '<域名>'`，留空 `-KeycloakProbeHost ''` 则只用回环地址。

只有两个地址都探不通才会判 `[FAIL]`（提示针对最后一个地址），且提示会区分原因：证书/握手问题 / 连接被拒绝（8443 无监听）/ 连接超时 / 主机名解析失败 / 返回 HTTP 非 200（realm 名写错、`hostname-strict` 拒绝该 Host，或未启动完成），并附一行 `[INFO] 异常链: ...`。出现 `[FAIL]` 就按提示对应的一类去查，**本步全程只读**，不要用重启或改配置去"试一下"。

> **探针实现（2.2.1 起，别再改回 IWR）**：Keycloak 的 discovery **只走 `SslStream`**，完全不经过 `Invoke-WebRequest`。原因是 PS 5.1 下"拿 PowerShell 脚本块当证书回调"这条路根本走不通：
>
> ```powershell
> # 这个写法在 PS 5.1 下必然失败，不要用
> [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
> ```
>
> 回调是在 TLS 握手线程上被调用的，而那个线程没有 Runspace，于是必抛：
>
> ```
> PSInvalidOperationException: There is no Runspace available to run scripts in this thread.
> The script block you attempted to invoke was:  $true
> ```
>
> 现场 2.1.3 的异常链就是这样：`Invoke-WebRequest` 连试 9 次、每次等满 10 秒超时，才落到 `SslStream` 兜底并通过；也就是说那 9 次是纯粹的等待，不可能成功。2.2.x 已把 IWR 那条路整个删掉，也不再单独打印 `发请求前实际生效 SecurityProtocol`。
>
> **以后要探自签证书的 https，直接用 `SslStream`**：它的证书回调是 .NET 委托（`New-Object System.Net.Security.SslStream($stream, $false, $acceptAll)`），不需要 Runspace；TLS 版本绑在本次握手上（显式传 `Tls12`），不受进程级 `ServicePointManager` 与 ServicePoint 连接池的影响，也就不需要"先设 TLS 1.2、探测完再还原"那一套。
>
> 写自己的探针时注意枚举命名空间：.NET Framework 里是 `[System.Security.Authentication.SslProtocols]::Tls12`；`[System.Net.Security.SslProtocols]` 是 .NET Core/.NET 5+ 的类型，PS 5.1 下报 `Unable to find type`。

再用浏览器打开 `https://iame.ap.inalfa.local:8443/realms/inalfa/account` 或刚切完的 MSIA 走一次统一登录，能完成即通过。

需要看日志时，Keycloak 是既有服务，日志位置取决于 11-06 的配置，用 `nssm get Keycloak AppStdout` 查实际路径，不要按本手册的新路径去找。

---

## 第 11 步 归档基线并收紧权限（3 分钟）

**做什么**：把四个服务的完整配置导出留档，并限制目录访问。

**在哪**：管理员 PowerShell，`C:\Services`。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Dump -App All
icacls 'C:\Services\rollback' /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' /grant:r 'Administrators:(OI)(CI)F'
```

**应看到**
- `[ OK ] 已导出: C:\Services\rollback\baseline-<时间戳>\Keycloak.reg`（`MSIA-Server.reg`、`BOL-Server.reg`、`CapacityAPI.reg` 同理）
- `Keycloak.reg` 记录的是 11-06 既有服务配置，是本手册唯一一份 Keycloak 基线，必须保留
- 每个服务另有 `-status.txt`
- `icacls` 输出"已处理 1 个文件"

`.reg` 里含明文口令，不要复制到仓库或共享盘。

---

## 第 12 步 重启服务器（5 分钟）

**做什么**：验证服务不依赖登录即可自启。

**在哪**：管理员 PowerShell。

**命令**

```powershell
Restart-Computer -Force
```

**应看到**：服务器重启，远程连接恢复。

---

## 第 13 步 重启后不启动任何程序，直接验证（5 分钟）

**做什么**：确认四个服务自动运行、业务可用。

**在哪**：服务器上重连后的管理员 PowerShell（**不要先开任何应用窗口、不要双击 exe**）。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Verify -App All
```

**应看到**
- 四个应用全部 `服务状态 Running`
- 端口 8078、8090、8000、8443、9000 全部 `LISTENING`
- 四个应用均 `接口可访问`（Capacity 那行会命中 `/health`、`/openapi.json`、`/docs`、`/` 中的一个）
- MSIA / BOL / Capacity 各出现 `[ OK ] 环境变量已配置: SSL_CERT_FILE` 与 `[ OK ] SSL_CERT_FILE 指向的文件存在: ...`
- Keycloak 的 discovery 以 `https://iame.ap.inalfa.local:8443/...` 通过（切换完成前会是回环地址 + 一行 WARN，属预期）
- 结尾 `校验结果: 全部 PASS`

Keycloak / MSIA / BOL / Capacity 各做一次真实登录（Capacity 从它的页面点统一登录，确认能跳 Keycloak 再跳回），全部通过即交付完成。

---

## 第 14 步 出问题时退回控制台（10 分钟）

**做什么**：只把本次由本手册接管的 MSIA、BOL、Capacity 退回控制台。**Keycloak 不参与回滚**——它本来就是系统服务，回滚时保持运行不动。

**在哪**：管理员 PowerShell（`C:\Services`），随后到 MSIA、BOL、Capacity 三个应用目录各开一个窗口。

**命令**

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action Stop       -App MSIA
.\register-services-nssm.ps1 -Action Stop       -App BOL
.\register-services-nssm.ps1 -Action Stop       -App Capacity
.\register-services-nssm.ps1 -Action Unregister -App MSIA
.\register-services-nssm.ps1 -Action Unregister -App BOL
.\register-services-nssm.ps1 -Action Unregister -App Capacity
.\register-services-nssm.ps1 -Action ConsoleRollback -App MSIA
.\register-services-nssm.ps1 -Action ConsoleRollback -App BOL
.\register-services-nssm.ps1 -Action ConsoleRollback -App Capacity
```

`-Action Unregister` 会要求逐个输入服务名确认，输入 `MSIA-Server`、`BOL-Server`、`CapacityAPI`，**不要输入 `Keycloak`**。

然后对生成的三个启动器依次右键 →「使用 PowerShell 运行」，按提示输入口令（Capacity 与 BOL 一样会带上 `SSL_CERT_FILE`，但它的 OIDC 口令在应用自身，启动器不会问）：

```powershell
C:\Services\rollback\start-console-msia.ps1
C:\Services\rollback\start-console-bol.ps1
C:\Services\rollback\start-console-capacity.ps1
```

**应看到**
- `Get-Service MSIA-Server,BOL-Server,CapacityAPI` 报"找不到"（这三个服务已删除）
- `Get-Service Keycloak` 仍是 `Running`，8443 继续监听
- MSIA、BOL、Capacity 三个窗口正常运行，端口回到被控制台进程占用
- 业务登录正常

回滚后 MSIA、BOL、Capacity 回到改造前：窗口关闭即停止，重启服务器需人工启动；Capacity 也就失去了"崩溃自动重启 + 日志落盘"，只应作为临时处置。Keycloak 仍由服务托管。

---

## 与证书切换的交界

**证书不归本手册管。** 换证按 [keycloak-domain-cutover-step-by-step.md](keycloak-domain-cutover-step-by-step.md) 执行，本手册只负责让应用跑在服务里。

**唯一的交界点是 `SSL_CERT_FILE`。** 它是写进服务环境变量的；服务化完成后，换证时只需改这个变量的值并重启服务，不用再进控制台窗口重设，这正是服务化带来的好处。

**顺序：先做本手册 14 步（含第 8.5 步），稳定后再换证。** 换证时把值从 `C:\keycloak\conf\server.crt.pem` 改成 `C:\certs\ca-bundle.pem`，**MSIA、BOL、Capacity 三个客户端都要改**，各自改完重启：

```powershell
Set-Location C:\Services
.\register-services-nssm.ps1 -Action SetEnv -App MSIA     -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App BOL      -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action SetEnv -App Capacity -CertFile C:\certs\ca-bundle.pem -SecretMode Keep
.\register-services-nssm.ps1 -Action Stop   -App MSIA
.\register-services-nssm.ps1 -Action Stop   -App BOL
.\register-services-nssm.ps1 -Action Stop   -App Capacity
.\register-services-nssm.ps1 -Action Start  -App MSIA
.\register-services-nssm.ps1 -Action Start  -App BOL
.\register-services-nssm.ps1 -Action Start  -App Capacity
.\register-services-nssm.ps1 -Action Verify -App All
```

不要用 `-Action SetEnv -App All` 换证：那会把 Keycloak 也纳入环境变量合并（会改写它的 `JAVA_HOME` 并在缺项时写占位），而 Keycloak 的证书路径不在这里改。换证完成后 `-Action Verify -App All` 会自动覆盖四个应用，MSIA / BOL / Capacity 三行 `SSL_CERT_FILE 指向的文件存在: C:\certs\ca-bundle.pem` 都通过才算完。

域名/证书切换完成后，Keycloak 探针会自然改走 `https://iame.ap.inalfa.local:8443`，第 10 步里那对"回退到回环地址"的 INFO/WARN 随之消失；不需要改任何参数。

---

# 附录

## A. 参数速查

| NSSM 参数 | 本环境取值 | 含义 |
|---|---|---|
| `Application` | 注册命令里指定的 exe / bat | 被托管的可执行文件 |
| `AppParameters` | Keycloak 为 `start --optimized`，其余为空 | 传给可执行文件的参数 |
| `AppDirectory` | 程序所在目录 | 进程工作目录，影响相对路径配置文件的查找 |
| `Start` | `SERVICE_AUTO_START` | 开机自动启动 |
| `AppStdout` / `AppStderr` | `C:\Services\logs\<服务名>-std{out,err}.log` | 标准输出/错误落盘位置 |
| `AppRotateFiles` / `AppRotateOnline` | `1` / `1` | 在线轮转；进程不退出也能切文件 |
| `AppRotateSeconds` / `AppRotateBytes` | `86400` / `10485760` | 每 1 天或 10 MB 轮转一次 |
| `AppTimestampLog` | `1` | 每行加时间戳 |
| `AppStopMethodConsole` | Keycloak 20000，其余 15000 | 发 Ctrl+C 后等待的毫秒数 |
| `AppStopMethodSkip` | `0` | 不跳过任何停止手段（Ctrl+C → 关窗 → 结束进程） |
| `AppExit Default` | `Restart` | 进程退出后自动重启 |
| `AppRestartDelay` / `AppThrottle` | `5000` / `10000` | 重启前等 5 秒；启动后 10 秒内退出算异常，会拉长间隔 |
| `AppEnvironmentExtra` | 注册后脚本回读的内容 | 服务进程的环境变量，优先级高于应用配置文件 |
| `SSL_CERT_FILE`（环境变量） | MSIA/BOL 指向的 CA 包 | 换证后此值需更新，指向合并后的 `ca-bundle.pem` |

## B. 正文使用的默认值，以及怎么改

正文已按下列默认值写死，现场与默认值不同时，只改对应参数重跑该步。

| 项 | 默认 | 要改时 |
|---|---|---|
| 服务名 | `Keycloak` / `MSIA-Server` / `BOL-Server` / `CapacityAPI` | 加 `-KeycloakService` / `-MsiaService` / `-BolService` / `-CapacityService` |
| 脚本与日志目录 | `C:\Services`、`C:\Services\logs` | 加 `-LogRoot`，并同步改开头的建目录命令 |
| MSIA 端口 | `8078` | 加 `-MsiaPort`。**不要用 8000**，那是 `CapacityAPI` 的端口 |
| BOL 端口 | `8090` | 加 `-BolPort` |
| Capacity 程序与端口 | `...\Capacity\publish\CapacityAPI\CapacityAPI.exe`、`8000` | 加 `-CapacityExe` / `-CapacityPort`；程序无启动参数 |
| Capacity 环境变量 | `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`（必写） | 换证时 `-Action SetEnv -App Capacity -CertFile '<新路径>' -SecretMode Keep`。**与 MSIA / BOL 一致**，因为它是第四个 SSO 客户端；写漏了 OIDC discovery 必报 `CERTIFICATE_VERIFY_FAILED` |
| Keycloak 探针地址 | 优先 `https://iame.ap.inalfa.local:8443`，失败回退 `https://127.0.0.1:8443` | 加 `-KeycloakProbeHost '<域名>'`；传 `''` 则只用回环地址 |
| Keycloak 启动方式 | 直接托管 `kc.bat` | 报"不是有效的 Win32 应用程序"时，注册步骤加 `-KeycloakViaCmd` |
| 运行账号 | `LocalSystem` | 只对新建的 BOL / Capacity 生效；Keycloak 与 MSIA 已存在且默认不改写，需覆盖须加 `-Force`。改专用账号用 `-RunAsAccount '.\svc_xxx'`，会提示输入口令；需先给该账号授"作为服务登录"与目录/证书读权限 |
| nssm 位置 | PATH → `C:\keycloak\nssm.exe` → 其它常见目录 | 放到 `C:\keycloak\nssm.exe` 即可，无需改参数 |
| BOL 的 OIDC 与 CORS | 不写入 | 由 `db_config.ini` 的 `[oidc]` 段管理；服务层只写 `SSL_CERT_FILE`。写 `OIDC_*` 会造成双源头，`client_secret` 还会以明文进注册表 |
| MSIA `JWT_SECRET_KEY` | 不写入（沿用 `config.ini`） | MSIA 既有服务默认不改写环境变量；确需写入时用 `-Force` 重跑，并在提示时输入 `config.ini` 中的同值 |

## C. 故障对照

| 现象 | 处理 |
|---|---|
| `Start-Service` 报 1069 / 7041 | 运行账号口令错或无"作为服务登录"权限；对已存在服务用 `-Action Register -RunAsAccount 'LocalSystem' -Force` 回到默认账号（会覆盖现场参数，先做 `Dump`） |
| 服务 Running 但端口无监听 | 看 `C:\Services\logs\<服务名>-stderr.log` 尾部；多为应用自身监听配置与预期不一致 |
| `CERTIFICATE_VERIFY_FAILED` | `SSL_CERT_FILE` 指向的文件不存在或内容不含对应 CA；`-Action SetEnv -CertFile '<新路径>'` 后 `Restart-Service` |
| Capacity 点统一登录报 `idp_unreachable` | 十有八九是服务环境里没有 `SSL_CERT_FILE`（`Verify -App Capacity` 里缺 `环境变量已配置: SSL_CERT_FILE`）；补写后必须 `Stop` + `Start` 才生效，`Restart-Service` 亦可 |
| `WinError 10048` / `Address already in use` | 还有一个手工实例在跑：`taskkill /F /IM <exe名>`，再 `-Action Start` |
| MSIA 登录后立即 401 | 服务的 `JWT_SECRET_KEY` 与 `config.ini` 不一致；按 B 表最后一行补写后重启服务 |
| 服务反复重启 | `-Action Status` 看 PID 是否变化；`C:\keycloak\logs\keycloak.log` 或 stderr 里有真实原因 |
| Capacity `[FAIL] 接口无响应，已试: …` | 先 `Get-NetTCPConnection -LocalPort 8000` 确认在听；在听但 4 条路径全不通，多半是路由与预置候选不一致，用浏览器打开 `http://127.0.0.1:8000/docs` 看实际路由；同时看 `C:\Services\logs\CapacityAPI-stderr.log` |

## D. 与旧脚本的取舍

本项目只使用 `register-services-nssm.ps1`。同目录的 `install-msia-service.ps1` 仅覆盖 MSIA 且已不再使用，两者都注册 `MSIA-Server`，不可同时执行。

## E. 第四个应用：CapacityAPI 接入实操记录

这一节按实例记录"新增一个应用"到底改了哪里，下一个应用照此复制即可。

**落地位置（脚本 2.2.1）**

| 位置 | 行号 | 内容 |
|---|---|---|
| 参数块 `-App` 的 `ValidateSet` | 72 | 在 `'BOL'` 后加 `'Capacity'`；不加会被参数校验直接拒绝 |
| 参数块新增私有参数 | 121–123 | `$CapacityService` / `$CapacityExe` / `$CapacityPort`，命名与 `-BolExe` / `-BolPort` 同风格 |
| `New-Spec` 的参数与字段 | 533–534、552 | 新增 `[string[]]$ProbeUrls` 及同名字段，承载"多候选探测地址" |
| `Initialize-Specs` 的 Capacity 段 | 638–658 | 一段 `New-Spec`，含 `StaticEnv['SSL_CERT_FILE']` 与 `RequiredEnv @('SSL_CERT_FILE')` |

**填进去的值**

| 项 | 值 |
|---|---|
| `-App` / `Key` | `Capacity`（**不是**服务名 `CapacityAPI`） |
| 服务名 | `CapacityAPI` |
| `Application` | `C:\ApplicationFile\ExecuteProgram\Capacity\publish\CapacityAPI\CapacityAPI.exe` |
| `AppDirectory` | 同目录（`...\CapacityAPI`） |
| `AppParameters` | 空（实测 CommandLine 只有 exe 路径本身） |
| `DisplayName` | `Capacity 产能系统 API` |
| `Ports` | `8000`（实测 `0.0.0.0:8000` 监听） |
| `ProbeUrl` | 空，改用下面的 `ProbeUrls` |
| `ProbeUrls` | `http://127.0.0.1:8000/health`、`/openapi.json`、`/docs`、`/` |
| `RequiredEnv` | `SSL_CERT_FILE`（与 MSIA/BOL 相同，`Verify` 据此检查"已配置"与"文件存在"两条） |
| `StaticEnv` | `SSL_CERT_FILE = C:\keycloak\conf\server.crt.pem`（`Register` / `SetEnv` 写入，`ConsoleRollback` 也会生成这一行） |
| 日志 | `C:\Services\logs\CapacityAPI-stdout.log` / `-stderr.log` |
| 运行账号 | `LocalSystem` |
| `ConsoleCommand` / `ConsoleWorkDir` | `.\CapacityAPI.exe` / 同目录（`ConsoleRollback` 用） |

**为什么 Capacity 也要 `SSL_CERT_FILE`**：它是第四个 SSO 客户端（Python/FastAPI + uvicorn，与 BOL 同栈），日志里有 `OIDC discovery 拉取失败：[SSL: CERTIFICATE_VERIFY_FAILED] ... self-signed certificate` 与 `OIDC 登录跳转失败：idp_unreachable`。最初只看它的配置文件"没有 OIDC 段"，就判成了不接 SSO —— 这个判断是错的。**判据是日志里有没有 OIDC 输出、点一次统一登录跳不跳，不是配置文件里有没有 SSO 段。**

**多候选探针怎么工作**：`Invoke-Probe` 按 `ProbeUrls` 的顺序依次试，任一个返回 200 就 `[ OK ]` 并结束；多候选时每个地址最多 3 次、间隔 2 秒（单地址应用仍是 10 次，行为与之前完全一致）。全部失败才 `[FAIL] 接口无响应，已试: …`，把试过的路径全列出来。这条逻辑是通用的：**以后再遇到健康端点不确定的应用，只把候选路径写进 `ProbeUrls`，不需要动 `Invoke-Probe`**；只有一个地址的应用继续只写 `ProbeUrl`。

**为什么值得做（现场事实）**：CapacityAPI 接入前以控制台进程运行，现场观察到重启前 PID 变过 —— 说明它自己会崩、或被别的操作带重启，崩了没有人拉起，报错只留在窗口里滚过去。服务化后 NSSM 按 `AppExit Default=Restart` 自动拉起，并把 stdout/stderr 写进 `C:\Services\logs`，崩溃现场可回溯。**崩溃自动重启与日志留存，就是这次把它纳入托管的主要收益。**

**验证顺序**：`-Action Precheck -App Capacity` → `Register` → `SetEnv -CertFile '<证书PEM>' -SecretMode Keep` → `Start` → `Verify`。其余动作（`Status` / `Dump` / `Stop` / `Unregister` / `ConsoleRollback`）全部由 spec 驱动，**没有为这个应用写任何特例分支**。回滚启动器只按 spec 里声明的静态变量生成：Capacity 会得到 `SSL_CERT_FILE`（与 BOL 相同），但不会被问 `OIDC_CLIENT_SECRET`（它的 OIDC 配置在应用自身）。
