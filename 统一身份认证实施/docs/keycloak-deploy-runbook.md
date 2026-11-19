# Keycloak 部署操作手册（IRSCnKettle01 · Windows）

> 依据：`keycloak/keycloak.conf`（T01）。目标版本 **Keycloak 25.0.6**（26.x 因 SQL Server 2017 不支持 `OPTIMIZE_FOR_SEQUENTIAL_KEY` 已回退，见第 10 节）。
> 目标：在 `IRSCnKettle01.ap.inalfa.local` 上把 Keycloak 跑起来（NSSM 服务），**不依赖 CA 证书**（8443 走本机回环自签）。
> 适用范围：从空机到 "Keycloak 内部已活着 + master 域可登录"。realm/clients/SMTP 初始化是下一步，见 `keycloak/realm-setup.md` 与 `keycloak/clients.md`。
> **本次执行入口**：第 10 节《回退重装可执行清单》。第 1–9 节是首次安装的通用流程与排障参考，配置项与验证阈值以第 10 节为准。

## 0. 前置条件核对（按 25.0.6 回退路径对齐）

> 本节已按第 10 节的回退重装流程重写状态口径：P2/P3/P4 不再做"预检"，改为在 10.6 建库时一次性达成，避免文档与实际做法冲突。

| # | 条件 | 验证方式 | 状态 |
|---|---|---|---|
| P1 | JDK 21 已装 | `java -version`、`Get-ChildItem 'C:\Program Files\Java' -Directory` | ✅ 已完成；**实际安装目录待记录**（见 10.1-T3） |
| P2 | keycloak 库存在且可用 | — | ⏭ 不适用：25 重装由 **10.5-D2/D3 删库重建**（26 建到一半的库 25 无法接管） |
| P3 | 登录名映射 USER + db_owner | — | ⏭ 不适用：由 **10.5-D4** 重建库内用户（删库会连用户一起删） |
| P4 | 库排序规则为 CS | — | ⏭ 不适用：由 **10.5-D3** 建库时指定 `Latin1_General_CS_AS` |
| P5 | openssl 可用 | `where openssl` | ➖ 本次不需要：复用 26 备份中的自签 PEM（10.4）。仅当 PEM 丢失时才回第 2 节重新生成 |
| P6 | 安装包 `keycloak-25.0.6.zip` 已就位且完整 | `Get-FileHash`（见 10.1-T1） | ⬜ 待确认（路径与哈希） |
| P7 | `keycloak_svc` 新口令已生成并封存 | — | ⬜ 待确认（见 10.1-T5） |

P3/P4 的核对 SQL 保留作**事后验收**用（正常应由 10.6 直接达成；若仍不满足，回 10.6 重做，不要单独用下面的 `ALTER` 补）：

```sql
USE keycloak;
SELECT dp.name AS user_name, r.name AS db_role
FROM sys.database_principals dp
JOIN sys.database_role_members drm ON drm.member_principal_id = dp.principal_id
JOIN sys.database_roles r ON r.principal_id = drm.role_principal_id
WHERE dp.name = 'keycloak_svc';   -- 换成实际登录名，应看到 db_owner
```

> ⚠️ 上述 `ALTER DATABASE ... COLLATE` 只适用于**已存在且仍在空库**的场景；25 重装是删库重建（10.5-D3），不要在这里先改一次排序规则。

> ⚠️ 登录名安全红线：ytview 实测是 **sysadmin**，不要用它长期跑 Keycloak。让 DBA 建专用登录：
> `CREATE LOGIN keycloak_svc WITH PASSWORD='<强口令>';` → keycloak 库内 `CREATE USER` + `ALTER ROLE db_owner ADD MEMBER`。
> 若登录名不是 `keycloak_svc`，同步改 `C:\keycloak\conf\keycloak.conf` 的 `db-username`。

## 1. 装包（26.x 首次安装流程，已不适用于当前环境）

> ⚠️ **本次回退重装请直接执行第 10 节**，不要走本节。本节保留作"从零新装、SQL Server ≥2019 时"的参考：第 10 节的 10.4 已包含等价的解压/驱动/证书复用动作。

```bat
:: 1.1 下载 Keycloak 服务器发行包（GitHub Releases）。SQL Server 2017 环境只能用 25.0.6：
::     keycloak-25.0.6.zip；SQL Server 2019+ 才可用 26.x
::     解压到 C:\keycloak（得到 bin\conf\lib\providers\ 等目录）
:: 1.2 下载 MSSQL JDBC 驱动（mssql-jdbc 12.x，选 jre11 或更新变体，兼容 JDK21），
::     放入 providers 目录：
mkdir C:\keycloak\logs
copy "C:\Users\%USERNAME%\Downloads\mssql-jdbc-12.x.x.jre11.jar" C:\keycloak\providers\
```

## 2. 生成 8443 自签 PEM

8443 只被同机 IIS ARR 访问（ARR 不校验证书），自签即可；**对外 443 的企业证书装在 IIS，不经 Keycloak**。

```bat
cd C:\keycloak\conf
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 ^
  -keyout server.key.pem -out server.crt.pem -subj "/CN=localhost"
dir server.*.pem
```

> `http-enabled=false` 时这两个文件缺失会导致启动直接失败——先确认文件在位。

> ⚠️ **Git Bash 坑（实测踩过）**：在 Git Bash 里执行时，`-subj "/CN=localhost"` 中的 `/CN=...` 会被 MSYS 自动转换成 Windows 路径，报错
> `req: subject name ... is not in that format: 'C:/Program Files/Git/CN=localhost'`。
> 解决（二选一）：① 命令前加前缀 `MSYS_NO_PATHCONV=1`；② 把 `-subj` 改成 `-subj "//CN=localhost"`（双斜杠，MSYS 不转换，openssl 收到的仍是 `/CN=localhost`）。cmd 下无此问题。

## 3. 落地配置文件

把实施工件 `统一身份认证实施\keycloak\keycloak.conf` 复制到 `C:\keycloak\conf\keycloak.conf`（已含库连接、8443 自签证书路径、health 等全部生产项）。**build 之前必须就位**（build 会读取其中的 db 配置）。

## 4. build（预构建，之后才能 --optimized 启动）

```bat
cd C:\keycloak\bin
kc.bat build
```

看到构建完成、无报错即可。JDBC 驱动已在 providers\ 中，此步会把它打进运行时。

## 5. 创建初始管理员（按 Keycloak **25.0.6** 口径）

> 25.0.6 官方文档《Server Administration Guide → Creating the first administrator》只给出两种方式：**本机 welcome page**、或首次启动前设 **`KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`** 环境变量。
> 26.x 才有的 `bootstrap-admin`（含 `tools bootstrap-admin`）、`--bootstrap-admin-username/--bootstrap-admin-password`、`KC_BOOTSTRAP_ADMIN_*`、`hostname-strict-https`，在 25.0.6 中**一律不存在**，不要照抄。

### 5A. 环境变量法（首选，可无头执行）

```powershell
Set-Location C:\keycloak\bin
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-21.0.10'   # 回填实际目录
$env:KC_DB_PASSWORD   = '<keycloak_svc 口令>'
$env:KEYCLOAK_ADMIN   = 'kcadmin'
$env:KEYCLOAK_ADMIN_PASSWORD = '<kcadmin 强口令>'
.\kc.bat start --optimized
```

- 变量全名：`KEYCLOAK_ADMIN`（用户名，非 email；master 域按用户名登录）、`KEYCLOAK_ADMIN_PASSWORD`；
- **只在首次启动、且 master 域还没有任何用户时生效**——必须在 10.5 删库重建之后执行；
- 首次启动会顺带跑 Liquibase 建 100+ 张表（数分钟，勿中途中断）；
- 创建完成后 `Ctrl+C` 停掉前台进程，**立即清除这两个临时变量**（不要写进系统环境变量或 NSSM）；
- 口令物理封存，不进文档、不进 git。

### 5B. 本机 welcome page（替代路径，需人工交互）

首次启动后浏览器访问根路径 → 出现"创建管理员"引导页，填用户名/口令。本环境关了 8080，需走 `https://127.0.0.1:8443`。

- 取舍：不依赖环境变量，但要求首次启动时库为空，且必须有人在服务器前操作、不能被别的客户端抢先完成初始化。

> ⚠️ 不适用：`--import-realm` 导入带用户的 realm。realm import 只处理被导入的那个 realm，**无法创建 master 域管理员**，本场景不可用。

## 6. NSSM 注册为 Windows 服务

```bat
:: 6.1 安装（NSSM 需已安装；没有则 nssm.mkai 官网下载 win64 版放入 PATH）
nssm install Keycloak "C:\keycloak\bin\kc.bat" start --optimized

:: 6.2 服务参数
nssm set Keycloak AppDirectory C:\keycloak
:: 必须同时给 JAVA_HOME：服务不继承用户变量，缺了会回落系统 Java 8
nssm set Keycloak AppEnvironmentExtra "JAVA_HOME=C:\Program Files\Java\jdk-21.0.10" "KC_DB_PASSWORD=<keycloak_svc口令>"
nssm set Keycloak Start SERVICE_AUTO_START
nssm set Keycloak AppStdout C:\keycloak\logs\service-stdout.log
nssm set Keycloak AppStderr C:\keycloak\logs\service-stderr.log
nssm set Keycloak AppExit Default Restart
nssm set Keycloak AppThrottle 15000
```

> 此处**只放** `JAVA_HOME` 与 `KC_DB_PASSWORD`。`KEYCLOAK_ADMIN*` 只在首次启动的临时会话里用（第 5 节），绝不写进服务配置。

要点：

- **KC_DB_PASSWORD 必须配在 NSSM 服务环境里**（`AppEnvironmentExtra`），只设用户环境变量对服务不生效——这是最常见的"本地能起、服务起不来"原因；
- `keycloak.conf` 的 `db-password=${KC_DB_PASSWORD}` 从这里取值，口令不落配置文件；
- 若 `nssm start` 报"不是有效的 Win32 应用程序"（个别 NSSM 版本不直接支持 .bat），改用 cmd.exe 包装：
  `nssm install Keycloak "C:\Windows\System32\cmd.exe" /c ""C:\keycloak\bin\kc.bat" start --optimized"`

### 6.3 防火墙：把 8443 关成"仅本机回环"

Keycloak 25/26 的 keycloak.conf **没有监听地址参数**，8443 默认听所有网卡。用防火墙规则兑现设计（Windows 防火墙不过滤回环流量，故 127.0.0.1 访问不受影响）：

```bat
netsh advfirewall firewall add rule name="Block-Keycloak-8443-Inbound" dir=in action=block protocol=TCP localport=8443
```

## 7. 启动与验证

```bat
nssm start Keycloak

:: 7.1 等 30-60 秒后验证（自签证书用 -k）
curl -k https://127.0.0.1:8443/realms/master/protocol/openid-connect/certs
curl http://127.0.0.1:9000/health/ready
netstat -ano | findstr "8443 9000"
```

| 验证项 | 预期 |
|---|---|
| `health/ready` | 返回 `200` + `{"status":"UP","checks":[...]}`（未就绪时 503，等一会再试） |
| `keycloak.log` | 有 Liquibase changelog 执行记录 + `Started Keycloak` + 监听 8443 |
| 数据库表数 | `USE keycloak; SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE';` → **100+ 张** |

> ⚠️ **PowerShell 坑（实测踩过）**：本机 PATH 可能没有 `curl.exe`，且 PowerShell 5.1 里 `curl` 只是 `Invoke-WebRequest` 别名、不支持 `-k`。改用原生写法：
> ```powershell
> # health（纯 HTTP，无需处理证书）
> Invoke-RestMethod -Uri 'http://127.0.0.1:9000/health/ready' | ConvertTo-Json -Depth 6
> # 8443（自签需临时跳过校验，仅当前会话生效）
> [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
> Invoke-RestMethod -Uri 'https://127.0.0.1:8443/realms/master/protocol/openid-connect/certs' | ConvertTo-Json -Depth 6
> ```
> ServerCertificateValidationCallback 是会话级的，不要写进长期运行的脚本。或直接浏览器开 `https://127.0.0.1:8443` 点"继续访问"看登录页。
| netstat | 8443 在听（设计上全网卡，已由防火墙规则收敛为实际仅本机可达）；9000 管理端口仅回环 |
| 健康检查脚本 | `health_check.ps1`（实施工件）跑通 |

## 8. 常见故障速查

| 现象 | 原因 / 处理 |
|---|---|
| 服务启动即退出，日志为空 | JDK 不是 21 或 JAVA_HOME 没进**服务**环境；`java -version` 核对 |
| 日志报连接数据库失败 | ① KC_DB_PASSWORD 没配在 NSSM 服务环境（改完重启服务）；② keycloak_svc 在 keycloak 库没映射 USER/db_owner（P3）；③ db-url 的 databaseName 误写成 CN_AME |
| 启动报 HTTPS/证书相关错误 | `C:\keycloak\conf\server.crt.pem`、`server.key.pem` 缺失或路径与 conf 不一致 |
| 表没建起来 | 看日志 Liquibas 段；确认连的是 keycloak 库；登录名无 DDL 权限 |
| 本地手动能起、NSSM 服务起不来 | KC_DB_PASSWORD 只在用户环境设过；或 .bat 不被 NSSM 直接支持（换 cmd.exe 包装，见 6.2） |
| 8443 从别的机器能访问 | 防火墙规则没加成功；补第 6.3 节命令 |

## 9. 回滚与卸载

```bat
nssm stop Keycloak
nssm remove Keycloak confirm
:: 如需彻底重来：DBA 执行 DROP DATABASE keycloak（库内只有 KC 自己的表，无业务数据）
```

## 10. 回退重装：Keycloak 26.x → 25.0.6（可执行清单）

> **本节所有命令与验证项均按 Keycloak 25.0.6 口径**。凡 26.x 才有的写法一律不适用：`bootstrap-admin` / `tools bootstrap-admin` / `--bootstrap-admin-username|--bootstrap-admin-password` / `KC_BOOTSTRAP_ADMIN_*` / `hostname-strict-https`。现场已实测：25.0.6 上执行 `kc.bat tools bootstrap-admin --help` 报找不到该命令，正是版本口径不符，不是安装包损坏。

> **触发原因（已实测）**：Keycloak 26.x 的 Liquibase 脚本在 SQL Server 上执行
> `CREATE INDEX ... WITH (OPTIMIZE_FOR_SEQUENTIAL_KEY = ON)`，该选项 **SQL Server 2019 才支持**；
> 本环境是 SQL Server **2017 Express**（`14.0.2042.3`），启动报
> `'OPTIMIZE_FOR_SEQUENTIAL_KEY' is not a recognized CREATE INDEX option`，建表失败、服务自停。
> 降级到 25.0.6（25 的最后一个维护版，Liquibase 不含该选项）即可兼容。

**执行边界（先读）**

- 本清单只负责"服务器上把 Keycloak 25.0.6 跑起来"。realm `inalfa`、clients、SMTP、灌用户**不在本清单**，见 `realm-setup.md` / `clients.md`。
- 需在变更窗口内执行：删服务、改目录名、`DROP DATABASE` 均不可逆。执行前必须完成 10.1 的 T4（确认 `keycloak` 库内只有 Keycloak 自身表）。
- **本清单没有 `collectstatic`**：那是 Django（BOL）侧的构建步骤，与 Keycloak 无关，切勿在 `C:\keycloak` 下执行任何 `manage.py` 命令。
- 每步都写「判据」。判据不满足就停在该步处理，**不要带着问题往下走**。

### 版本兼容矩阵

| SQL Server 版本 | Keycloak 26.x | Keycloak 25.0.6 |
|---|---|---|
| 2019+ | ✅ | ✅ |
| 2017（本环境） | ❌ `OPTIMIZE_FOR_SEQUENTIAL_KEY` 不识别 | ✅ |
| 2016 及以下 | ❌ | ⚠️ 建议验证后再定 |

### 10.1 现场确认项 T1–T6（逐项填好再开始）

先开一个**提升的管理员 PowerShell**（在 IRSCnKettle01 上），把这段变量落地。后面所有步骤复用；**每新开一个窗口都要重跑这段**（`$env:` 变量不跨会话、更不会被服务继承）。

```powershell
$KC      = 'C:\keycloak'
$KCBase  = 'C:\keycloak_26_backup'
$Pkg     = 'C:\Install\keycloak-25.0.6.zip'      # 待确认，见 T1
$SvcName = 'Keycloak'                            # 待确认，见 T2
$JdkHome = 'C:\Program Files\Java\jdk-21.0.10'   # 待确认，见 T3
$DbPwd   = '<keycloak_svc 新口令>'               # 只存在于本会话内存，不写文件
$NSSM    = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $NSSM) { $NSSM = Join-Path $KC 'nssm.exe' }
```

| # | 确认项 | 确认命令 | 判据 | 不通过怎么办 |
|---|---|---|---|---|
| T1 | 25.0.6 安装包位置与完整性 | 见下方 T1 命令 | 大小 >120 MB；SHA256 与下载机一致 | 重新下载/重新传送；半截包会导致解压缺文件、build 报错 |
| T2 | 服务名与 nssm 路径 | 见 T2 命令 | 服务名与 `$SvcName` 一致；能找到 `nssm.exe` | 改 `$SvcName`；找 nssm 路径回填 `$NSSM` |
| T3 | JDK 21 实际安装目录 | 见 T3 命令 | 存在 21.x 目录 | 回填实际路径到 `$JdkHome`；`java -version` 显示 8 属正常（见下方说明） |
| T4 | SQL 侧现状（版本/库/登录名/库内有没有业务表） | 见 T4 SQL | 库内全部是 KC 内置表 | 出现任何业务表 → **停**，找 DBA，不得 DROP |
| T5 | `keycloak_svc` 新口令已生成并封存 | 无命令 | 口令有书面封存或存入 `credentials.xml` | 没有就先改（10.5-D5 会一并轮换） |
| T6 | 无第三方应用占用 keycloak 库 | `sys.dm_exec_sessions` | 无 `keycloak_svc` 的活跃会话 | 确认来源；有第三方 → 停并确认用途 |

**T1：定位安装包 + 完整性**

```powershell
Get-ChildItem -Path 'C:\', 'D:\', 'C:\Install' -Filter 'keycloak-25.0.6.zip' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
    Select-Object FullName, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}, LastWriteTime
Get-FileHash -Path $Pkg -Algorithm SHA256 | Format-List Path, Hash
```

判据：命中路径与预期一致（回填 `$Pkg`）；`MB` 约 150–170；哈希与下载机 `Get-FileHash` 结果一致。

**传送方式（若包不在服务器本地）**：二选一，落位后再算一次哈希比对。
- RDP 盘重定向：连接时勾选本地磁盘，然后在服务器上 `Copy-Item '\\TSCLIENT\<盘符>\...\keycloak-25.0.6.zip' $Pkg`；
- 管理共享：在下载机执行 `Copy-Item '<本地路径>\keycloak-25.0.6.zip' '\\IRSCnKettle01\c$\Install\'`（需管理员共享权限）。

**T2：服务名与 nssm**

```powershell
Get-Service | Where-Object { $_.Name -match 'keycloak' } | Select-Object Name, Status, StartType
sc.exe qc $SvcName
Test-Path $NSSM
```

**T3：JDK 21 目录**

```powershell
Get-ChildItem 'C:\Program Files\Java', 'C:\Program Files\Eclipse Adoptium' -Directory -ErrorAction SilentlyContinue |
    Select-Object FullName
java -version                                  # 可能显示 8，属正常
$env:JAVA_HOME                                 # 当前会话
[Environment]::GetEnvironmentVariable('JAVA_HOME','Machine')
```

> 说明：机器 PATH 里排在前面的若是 Java 8，`java -version` 就显示 8，**这不代表不能用 21**。Keycloak 的 `kc.bat` 优先用 `JAVA_HOME`，所以关键是**显式把 `$JdkHome` 指到 21 目录**，并把 `JAVA_HOME` 写进 NSSM 服务环境（10.9）。

**T4：SQL 侧现状（在 IRSCNYTFINEREPORT 上执行，SSMS，DBA 身份）**

```sql
SELECT @@VERSION AS sql_version;
SELECT name, collation_name, state_desc FROM sys.databases WHERE name = 'keycloak';
SELECT name, type_desc, is_disabled FROM sys.sql_logins WHERE name = 'keycloak_svc';
SELECT TABLE_NAME FROM keycloak.INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME;
GO
```

判据：`sql_version` 为 2017（`14.0.x`）；库存在（将被 10.6 删除重建）；表清单全部是 `DATABASECHANGELOG*` / `REALM` / `CLIENT*` / `USER_*` 等 Keycloak 内置表。

**T6：库占用检查**

```sql
SELECT spid, loginame, hostname, program_name, status
FROM sys.dm_exec_sessions
WHERE loginame = 'keycloak_svc';
GO
```

判据：无输出（10.3 删服务后应只剩空结果）。

### 10.2 步骤 A：停服 + 删服务（IRSCnKettle01｜提升的管理员 PowerShell）

```powershell
& $NSSM stop $SvcName
& $NSSM remove $SvcName confirm
sc.exe query $SvcName                                              # 预期：失败 1060（服务不存在）
Get-Service $SvcName -ErrorAction SilentlyContinue                 # 预期：无输出
Get-CimInstance Win32_Process -Filter "Name='java.exe'" |
    Where-Object { $_.CommandLine -like '*keycloak*' } |
    Select-Object ProcessId, CommandLine                           # 预期：无输出
```

**判据**：`sc query` 返回 1060；没有命中 `C:\keycloak` 的 java 进程。

**失败处置**：
- `remove` 报 *Access is denied* → 确认是**提升**的窗口；
- 仍有 java 进程 → 按 PID 精确结束，**只杀命令行含 `C:\keycloak` 的**（机器上可能跑着别的 Java 应用，禁止按进程名批量杀）：
  ```powershell
  Stop-Process -Id <PID> -Force
  ```
- 服务名与预期不符 → 回 T2 修正 `$SvcName` 后重跑本步。

> 这一步没做干净，10.5 的 `DROP DATABASE` 就会被连接占用（见 10.11 第 1 行）。

### 10.3 步骤 B：整目录改名备份 + 明文口令止血（IRSCnKettle01｜管理员）

```powershell
Test-Path $KCBase            # 预期 False
if (Test-Path $KCBase) { Rename-Item $KCBase ("C:\keycloak_26_backup_" + (Get-Date -f yyyyMMddHHmm)) }
Rename-Item $KC $KCBase
Get-ChildItem $KCBase | Select-Object Name
```

**判据**：`C:\keycloak` 不存在；`$KCBase` 内含 `bin`、`conf`、`lib`、`providers`。

**明文口令止血（立即做，不等收尾）**：26 的 `conf\keycloak.conf` 曾以明文写 `db-password`。

```powershell
Select-String -Path "$KCBase\conf\keycloak.conf" -Pattern 'db-password' -SimpleMatch
```

若命中，就地抹掉该行（保留其余内容作对照）：

```powershell
$f = "$KCBase\conf\keycloak.conf"
(Get-Content $f) -replace '^db-password=.*', '# db-password removed: rotated at reinstall' | Set-Content $f -Encoding UTF8
Select-String -Path $f -Pattern 'db-password' -SimpleMatch   # 预期只剩注释行，无口令值
```

**判据**：备份 conf 里不再有口令明文。旧口令的失效靠 10.5-D5 的 `ALTER LOGIN` 轮换（两步配合才算闭环）。

**失败处置**：目录被占用改名失败 → 说明还有进程在跑（回 10.2 查 java 进程）；无权限 → 确认是管理员。

### 10.4 步骤 C：解压改名 + 复用配置/证书/驱动 + 配置兼容门（IRSCnKettle01｜管理员）

```powershell
Expand-Archive -Path $Pkg -DestinationPath 'C:\' -Force
Rename-Item 'C:\keycloak-25.0.6' $KC
New-Item -ItemType Directory -Force "$KC\logs" | Out-Null

Copy-Item "$KCBase\conf\keycloak.conf"  "$KC\conf\"  -Force
Copy-Item "$KCBase\conf\server.crt.pem" "$KC\conf\"  -Force
Copy-Item "$KCBase\conf\server.key.pem" "$KC\conf\"  -Force
Get-ChildItem "$KCBase\providers" -Filter 'mssql-jdbc-*.jar' |
    Copy-Item -Destination "$KC\providers\" -Force
if (Test-Path "$KCBase\nssm.exe") { Copy-Item "$KCBase\nssm.exe" $KC -Force }
```

**判据**：

```powershell
Get-ChildItem "$KC\conf\keycloak.conf", "$KC\conf\server.crt.pem", "$KC\conf\server.key.pem" | Select-Object Name, Length
Get-ChildItem "$KC\providers" -Filter 'mssql-jdbc-*.jar' | Select-Object Name, Length
Get-ChildItem "$KC\bin\kc.bat" | Select-Object Name, Length
```

- 两个 PEM、`keycloak.conf`、`kc.bat` 均存在且长度非 0；
- JDBC 驱动**恰好 1 个**（多版本并存会引起驱动冲突，多出来的一律移走）。

**配置兼容门（build 之前必做）**：

```powershell
$conf = "$KC\conf\keycloak.conf"
Select-String -Path $conf -Pattern 'db-password|hostname-strict-https|http-management-|^log=|metrics-enabled'
```

处理规则：

| 命中项 | 首次尝试 | 若 build/启动报 `Unrecognized option` 或配置告警 |
|---|---|---|
| `db-password=...` | **删除该行**（口令只走 `KC_DB_PASSWORD`） | — |
| `hostname-strict-https=true` | **删除该行**（25.0 起 hostname v2 为默认，该选项已移除） | 若删后仍报同类错，再检查 `hostname-strict` |
| `hostname-strict=true` | 保留 | 报错则一并删除（无副作用：`hostname` 已固定，且 `http-enabled=false`） |
| `http-management-port=9000` | 保留 | 25 已有独立管理口，默认纯 HTTP |
| `log=file` + `log-file=` | 保留 | 报 handler 不识别 → 改 `log=console,file` |
| `metrics-enabled=true` | 保留 | 报错则改为默认（本期不接监控，可删） |

> 说明：25 与 26 的**配置项**确有差异，以 build/启动输出为准逐行删减，每次只删一项再重跑，便于定位。删除这些项都不影响设计目标：8443 仍只在回环、HTTPS 仍由 `http-enabled=false` + 证书保证。
>
> 本表结论的依据：25.0.6 升级指南明确 `hostname-strict-https` **已移除**（25.0 起 hostname v2 为默认）；25.0.0 发布说明已包含 **"Management port for metrics and health endpoints"**，因此 `http-management-port=9000` + `health-enabled=true` 在 25.0.6 上可用（管理口默认纯 HTTP）。`proxy-headers=xforwarded`、`log`/`log-file`、`metrics-enabled` 均为 25 既有选项；若现场仍报未识别，按"删一项重跑一次"处理。

**失败处置**：`Rename-Item` 报目录已存在 → 残留 `C:\keycloak-25.0.6`，确认无人使用后加时间戳改名或删除；PEM 缺失 → 才回第 2 节用 openssl 重新生成（此时 P5 才变成必需项）。

### 10.5 步骤 D：删库重建（IRSCNYTFINEREPORT｜SSMS｜DBA：sysadmin 或 dbcreator+securityadmin）

> 注意：**SQL 全部在 IRSCNYTFINEREPORT 上执行**，不是在 IRSCnKettle01。Keycloak 的运行身份是 `keycloak_svc`（库内 `db_owner`）；建库/建登录需要 DBA 身份。

**D1 现状留证（结果截图存档）**

```sql
SELECT @@VERSION AS sql_version;
SELECT name, collation_name, state_desc FROM sys.databases WHERE name = 'keycloak';
SELECT spid, loginame, hostname, program_name
FROM sys.dm_exec_sessions WHERE loginame IN ('keycloak_svc','ytview');
GO
```

判据：无 `keycloak_svc` 活跃会话。若有，记下 `spid`；D2 的 `ROLLBACK IMMEDIATE` 会强制断开。

**D2 强制断连 + 删库（26 建到一半的库 25 无法接管）**

```sql
USE master;
GO
IF DB_ID('keycloak') IS NOT NULL
BEGIN
    ALTER DATABASE keycloak SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE keycloak;
END
GO
SELECT DB_ID('keycloak') AS db_id_now;   -- 预期 NULL
```

判据：`db_id_now` 为 NULL。

失败处置：报 **3702**（库正在使用）→ 回 D1 找 `spid`，DBA 执行 `KILL <spid>;` 后重跑；仍失败则确认是否有人在 SSMS 开着该库的查询窗口/对象资源管理器（关掉再试）。

**D3 按 CS 排序规则重建 + 开 RCSI**

```sql
CREATE DATABASE keycloak COLLATE Latin1_General_CS_AS;
GO
ALTER DATABASE keycloak SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
```

判据：

```sql
SELECT DATABASEPROPERTYEX('keycloak','Collation') AS collation_name;         -- Latin1_General_CS_AS
SELECT is_read_committed_snapshot_on FROM sys.databases WHERE name='keycloak'; -- 1
GO
```

**D4 重建库内用户并授 db_owner（删库会连用户一起删）**

```sql
USE keycloak;
GO
CREATE USER keycloak_svc FOR LOGIN keycloak_svc;
GO
ALTER ROLE db_owner ADD MEMBER keycloak_svc;
GO
```

失败处置：报 **15007**（登录名不存在）→ 先做 D5 的 `CREATE LOGIN`，再回来重跑 D4。

**D5 登录名：不存在则建，存在则轮换口令（旧明文口令就此失效）**

```sql
IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = 'keycloak_svc')
    EXEC('CREATE LOGIN keycloak_svc WITH PASSWORD = N''<新口令>'', CHECK_POLICY = OFF');
ELSE
    ALTER LOGIN keycloak_svc WITH PASSWORD = N'<新口令>';
GO
```

> 口令中**不要含单引号**（会破坏 `N''` 转义）；用强口令，若 `CHECK_POLICY=ON` 被策略拒绝，改 `OFF` 并记录原因。

**D6 收尾核对**

```sql
SELECT dp.name AS user_name, r.name AS db_role
FROM sys.database_principals dp
JOIN sys.database_role_members drm ON drm.member_principal_id = dp.principal_id
JOIN sys.database_roles r ON r.principal_id = drm.role_principal_id
WHERE dp.name = 'keycloak_svc';
SELECT COUNT(*) AS tables_now FROM keycloak.INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE';
GO
```

判据：`keycloak_svc | db_owner`；`tables_now = 0`（空库，Keycloak 启动时才建表）。

**D7 回填变量**：把新口令写进 10.1 的 `$DbPwd`（只在本会话），或者每次用到时直接粘到 `$env:KC_DB_PASSWORD`。

### 10.6 步骤 E：build（IRSCnKettle01｜管理员｜显式 JDK 21）

```powershell
Set-Location "$KC\bin"
$env:JAVA_HOME = $JdkHome
$env:Path      = "$JdkHome\bin;" + $env:Path
$env:KC_DB_PASSWORD = $DbPwd
java -version                                   # 判据：显示 21.x
.\kc.bat build 2>&1 | Tee-Object "$KC\logs\build.log"
$LASTEXITCODE                                   # 判据：0
```

**判据**：`$LASTEXITCODE = 0`；`build.log` 无 `Unrecognized option`、无 `ERROR`；`$KC\lib\quarkus\` 下有 build 产物。

**失败处置**：

| 现象 | 判断 | 动作 |
|---|---|---|
| `Unrecognized option: <某配置项>` | 25/26 配置差异 | 按 10.4 表删该项，重跑 build（一次只删一项） |
| `Unsupported class file major version` / `A JNI error has occurred` | 用到了 Java 8 | 核对 `java -version` 已是 21、`$JdkHome` 正确 |
| 多个驱动冲突告警 | providers 里多个 mssql jar | 只留一个 jar |
| db 连接/口令报错 | — | build 阶段**不连库**，此类报错一般是 `db-url`/`db-username` 写错，回 conf 核对 |

### 10.7 步骤 F：创建初始管理员 kcadmin（25.0.6 口径：`KEYCLOAK_ADMIN` 环境变量｜IRSCnKettle01｜管理员｜同一会话）

> **25.0.6 没有 `bootstrap-admin` 命令**（`tools bootstrap-admin` 是 26.x 的命令分组写法，25 会报未知命令/未知参数）。25.0.6 的官方创建方式是首次启动前设 `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`。

**前置**：10.5-D6 已确认库为空（`tables_now = 0`）；NSSM 服务尚未注册（或已停）；本会话已设 `$JdkHome`、`$DbPwd`。

> 若之前已经跑过一次 `kc.bat start`（表已建、甚至已有 master realm）但没建成管理员，环境变量可能不再生效。先确认：
> ```sql
> SELECT COUNT(*) AS realm_cnt FROM keycloak.dbo.REALM;
> SELECT COUNT(*) AS user_cnt  FROM keycloak.dbo.USER_ENTITY;
> ```
> `realm_cnt > 0` 而 `user_cnt = 0` 时，最稳妥的做法是**回 10.5-D2/D3 重建空库**，再执行本节。

```powershell
Set-Location "$KC\bin"
$env:JAVA_HOME = $JdkHome
$env:KC_DB_PASSWORD = $DbPwd
$env:KEYCLOAK_ADMIN = 'kcadmin'
$env:KEYCLOAK_ADMIN_PASSWORD = '<kcadmin 强口令>'
Get-ChildItem Env: | Where-Object { $_.Name -like 'KEYCLOAK_ADMIN*' } | Select-Object Name, Value   # 判据：两项都在
.\kc.bat start --optimized
```

说明：
- 变量名就是 `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`；**不要用** `KC_BOOTSTRAP_ADMIN_*`（26.x 口径）；
- 必须**前台**执行 `start`：管理员只在"首次启动且 master 域无用户"时创建，需要这两个变量在同一个进程环境里；
- `--optimized` 启动会同时跑 Liquibase 建 100+ 张表，日志持续数分钟属正常，**不要中途 Ctrl+C**；
- 本环境 `log=file`（只写文件、不输出到控制台），所以前台窗口可能长时间"没反应"，**属正常**。另开一个窗口看进度：`Get-Content C:\keycloak\logs\keycloak.log -Tail 20 -Wait`；
- 启动完成后先在**另一个窗口**做判定（见下），再回到本窗口 Ctrl+C。

**判据（以数据库为准）**：

```sql
SELECT u.USERNAME, r.NAME AS realm_name
FROM keycloak.dbo.USER_ENTITY u
JOIN keycloak.dbo.REALM r ON r.ID = u.REALM_ID
WHERE r.NAME = 'master';
GO
```

预期：出现 `kcadmin`（此库刚重建，master 域不应再有其他账号）。
若报列名不存在 → 先 `SELECT TOP 5 * FROM keycloak.dbo.USER_ENTITY;` 看实际列名，再调整查询。
辅助判据：日志出现启动完成行，且无 `ERROR`。

**停服 + 清除临时变量（必须做，否则凭据留在环境里）**：

```powershell
# 1) 回到正在跑 kc.bat start 的窗口，按 Ctrl+C 结束
# 2) 清除本次会话变量
Remove-Item Env:\KEYCLOAK_ADMIN, Env:\KEYCLOAK_ADMIN_PASSWORD -ErrorAction SilentlyContinue
Get-ChildItem Env: | Where-Object { $_.Name -like 'KEYCLOAK_ADMIN*' }        # 预期：无输出
[Environment]::GetEnvironmentVariable('KEYCLOAK_ADMIN','Machine')            # 预期：空
[Environment]::GetEnvironmentVariable('KEYCLOAK_ADMIN_PASSWORD','Machine')   # 预期：空
```

**红线**：`KEYCLOAK_ADMIN*` 只能存在于"首次启动这一次会话"。写进系统环境变量或 NSSM `AppEnvironmentExtra` 会让明文口令长期留在注册表/服务配置，且每次服务启动都被带上——没有任何必要。它与 `KC_DB_PASSWORD` 不冲突（变量名不同），可以同时存在。

**失败处置**：

| 现象 | 判断 | 动作 |
|---|---|---|
| `Unknown option: 'bootstrap-admin'` / `tools` 下找不到 `bootstrap-admin` | 25.0.6 无此命令（26.x 口径） | 改走本节 `KEYCLOAK_ADMIN` 法；顺带 `.\kc.bat --version` 确认版本是 25.0.6 |
| 启动完成但库里查不到 `kcadmin` | 启动进程没带上变量，或库里已有用户导致跳过创建 | 确认变量在同一会话已生效；确认库是 10.5 刚重建的空库 |
| 启动秒退、日志为空 | 缺 `JAVA_HOME` 或 `KC_DB_PASSWORD` | 回 10.1-T3 / 10.5-D7 核对 |

`kcadmin` 口令**物理封存**，不进文档、不进 git。

### 10.8 步骤 G：NSSM 注册（IRSCnKettle01｜管理员）

```powershell
Set-Location $KC
& $NSSM install $SvcName "$KC\bin\kc.bat" start --optimized
& $NSSM set $SvcName AppDirectory $KC
& $NSSM set $SvcName AppEnvironmentExtra "JAVA_HOME=$JdkHome" "KC_DB_PASSWORD=$DbPwd"
& $NSSM set $SvcName Start SERVICE_AUTO_START
& $NSSM set $SvcName AppStdout "$KC\logs\service-stdout.log"
& $NSSM set $SvcName AppStderr "$KC\logs\service-stderr.log"
& $NSSM set $SvcName AppExit Default Restart
& $NSSM set $SvcName AppThrottle 15000
```

**判据（双环境变量必须落进服务配置）**：

```powershell
& $NSSM get $SvcName Application
& $NSSM get $SvcName AppDirectory
& $NSSM get $SvcName AppEnvironmentExtra
```

预期输出中同时出现 `JAVA_HOME=C:\Program Files\Java\jdk-21.0.10` 与 `KC_DB_PASSWORD=...`，且**只有这两项**——不得出现 `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` / `KC_BOOTSTRAP_ADMIN_*`（出现说明把第 5/10.7 节的临时变量误写进了服务配置，用上面同一条 `set` 覆盖回两项）。

> 这里是最常见的"本地能起、服务起不来"根因：**用户级环境变量不会被服务继承**，必须在 `AppEnvironmentExtra` 显式写上。少了 `JAVA_HOME` 就回落到系统 PATH 的 Java 8，服务会秒退且日志可能为空。

**失败处置**：
- 报"不是有效的 Win32 应用程序" → 用 cmd 包装：
  ```powershell
  & $NSSM install $SvcName 'C:\Windows\System32\cmd.exe' /c "`"$KC\bin\kc.bat`" start --optimized"
  ```
- `AppEnvironmentExtra` 写入后 `get` 看不到两项 → 重新执行一次 `set`（两项必须一条命令内给全，后一次会覆盖前一次）。

### 10.9 步骤 H：启动与验证 V1–V6（IRSCnKettle01｜管理员）

```powershell
& $NSSM start $SvcName
Start-Sleep -Seconds 60
Get-Service $SvcName | Select-Object Name, Status
Get-Content "$KC\logs\keycloak.log" -Tail 20          # 首次启动在跑 Liquibase，最多等 2–3 分钟
```

| # | 判据 | 命令 | 通过条件 |
|---|---|---|---|
| V1 | 服务在跑且用的是 JDK 21 | `Get-CimInstance Win32_Process -Filter "Name='java.exe'" \| Where-Object { $_.CommandLine -like '*keycloak*' } \| ForEach-Object { ($_.CommandLine -split ' ')[0] }` | 服务 `Running`；输出路径含 `jdk-21` |
| V2 | 表已建全 | SQL：`SELECT COUNT(*) FROM keycloak.INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE';` 与 `SELECT COUNT(*) FROM keycloak.dbo.DATABASECHANGELOG WHERE EXECTYPE='FAILED';` | 表数 **≥100**；失败变更 **=0** |
| V3 | 启动完成且无致命错误 | `Select-String -Path "$KC\logs\keycloak.log" -Pattern 'started in\|Started Keycloak' \| Select-Object -Last 2`；`Select-String -Path "$KC\logs\keycloak.log" -Pattern 'ERROR\|FATAL\|OPTIMIZE_FOR_SEQUENTIAL_KEY\|Unrecognized option' \| Select-Object -Last 5` | 有启动完成行；第二个命令**无输出** |
| V4 | 管理端口健康 | `Invoke-RestMethod -Uri 'http://127.0.0.1:9000/health/ready' \| ConvertTo-Json -Depth 6` | HTTP 200 且 `status = UP`（503 表示仍在启动，等 60 秒再试） |
| V5 | 8443 JWKS 可用 | `[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }; (Invoke-RestMethod -Uri 'https://127.0.0.1:8443/realms/master/protocol/openid-connect/certs').keys.Count` | 返回整数 **≥1** |
| V6 | 控制台可登录 | 浏览器 `https://127.0.0.1:8443`（点"继续访问"）→ 用 `kcadmin` 登录（该账号由 10.7 首次启动时的 `KEYCLOAK_ADMIN` 创建）→ 进 `master` 域管理台 | 能进入控制台，看得到 `master` realm；且 10.7 的库查询里只有 `kcadmin` 一个 master 账号 |

端口监听核对（8443 全网卡属设计预期，已由防火墙收敛；9000 预期仅回环）：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8443, 9000 |
    Select-Object LocalAddress, LocalPort, OwningProcess
netstat -ano | Select-String '8443|9000'
```

**失败处置**：9000 返回 503 → 仍在建表，等 1–2 分钟；`BindException` 8443 → `Get-NetTCPConnection -LocalPort 8443` 找占用进程（**443 属 IIS，不要动 IIS**）；V6 打不开但 V4/V5 通 → 多为浏览器证书告警被拦，换 InPrivate 或确认访问的是 `https://`。

### 10.10 步骤 I：收尾（防火墙 / 端口收敛 / 明文口令 / 台账）

```powershell
netsh advfirewall firewall show rule name="Block-Keycloak-8443-Inbound"
# 若不存在：
netsh advfirewall firewall add rule name="Block-Keycloak-8443-Inbound" dir=in action=block protocol=TCP localport=8443
```

**判据**：规则存在且 `Action=Block`；在**另一台内网机**上验证不可达（预期均为 False）：

```powershell
Test-NetConnection -ComputerName IRSCnKettle01.ap.inalfa.local -Port 8443 -InformationLevel Quiet
Test-NetConnection -ComputerName IRSCnKettle01.ap.inalfa.local -Port 9000 -InformationLevel Quiet
```

**明文口令清理（V1–V6 全过后再做）**：

```powershell
Select-String -Path "$KCBase\conf\keycloak.conf" -Pattern 'db-password' -SimpleMatch   # 预期：只剩注释行
Select-String -Path "$KC\conf\keycloak.conf"   -Pattern 'db-password' -SimpleMatch   # 预期：只剩注释行
Remove-Item $KCBase -Recurse -Force          # 26 备份整目录删除（如需留证，先把 logs 归档到受限目录）
Test-Path $KCBase                            # 预期 False
```

**台账**：在 13.2 表格登记"Keycloak 25.0.6 / IRSCnKettle01 / 8443 / 9000 / sso.ap.inalfa.local"，并把 P1–P7 状态勾掉。

### 10.11 失败处置总表

| 现象 | 根因 | 处置 |
|---|---|---|
| DROP 报 3702 库正在使用 | 服务没删干净 / SSMS 占了连接 | 10.2 复查 java 进程；D1 找 spid → `KILL`；D2 的 `SINGLE_USER WITH ROLLBACK IMMEDIATE` 兜底 |
| 服务秒退、`keycloak.log` 为空 | `AppEnvironmentExtra` 缺 `JAVA_HOME`（回落 Java 8），或 nssm 不认 `.bat` | 10.8 判据复查；改用 cmd 包装 |
| `Login failed for user 'keycloak_svc'` | 口令不一致（轮换后 NSSM 里还是旧口令） | `& $NSSM get $SvcName AppEnvironmentExtra` 与 D5 口令比对；改后重启服务 |
| `Cannot open database "keycloak"` | 10.5-D4 没做（用户随库一起被删） | 回 D4 重建 USER + db_owner |
| 启动报 collation / 大小写相关 | 库不是 CS 排序规则 | 回 D3 用 `COLLATE Latin1_General_CS_AS` 重建 |
| 启动报证书/HTTPS 错误 | `server.*.pem` 缺失或路径不符 | 10.4 判据复查；缺失才重新生成 |
| 建表失败、日志出现 `OPTIMIZE_FOR_SEQUENTIAL_KEY` | 跑的还是 26 包（解压错/路径串了） | `.\kc.bat --version` 核对为 25.0.6；核对 `$KC\bin` 来源 |
| `Unrecognized option: ...` | 配置项版本差异 | 10.4 表逐项删，一次一项 |
| `Unknown option: 'bootstrap-admin'` / `tools` 下找不到 `bootstrap-admin` | 25.0.6 没有该命令（`bootstrap-admin`、`tools` 分组都是 26.x 口径） | 改用 `KEYCLOAK_ADMIN` 环境变量法（10.7）；先用 `.\kc.bat --version` 确认版本 |
| 9000 `health/ready` 返回 503 | 仍在建表/启动未完成 | 等 1–2 分钟；持续 503 看 `keycloak.log` 尾部 |
| `BindException: 8443` | 端口被占 | `Get-NetTCPConnection -LocalPort 8443` 定位；勿停 IIS（443 属它） |
| 表数远小于 100 | Liquibase 中断 | 看 `DATABASECHANGELOG` 的 FAILED 记录与日志；必要时回 10.5 重建库再启动 |

**回退阶梯**（按顺序，每次只动一层）：

1. 先判定"是不是包错了"：`kc.bat --version` 不是 25.0.6 → 重做 10.4；
2. 仍报 `OPTIMIZE_FOR_SEQUENTIAL_KEY` → 确认库已按 D3 重建（26 的残留表会干扰）；仍未解决则退到 **24.0.5**（同样不支持该索引选项的假设需实测验证；注意 24 的 hostname 默认仍是 v1 语义，conf 中 `hostname` 需按 v1 理解、`hostname-strict-https` 反而要保留）；
3. 再不行 → 备选 22.0.5 / 21.1.2（需重新验证 OIDC 端点兼容性）；
4. **根治路径**：推动 DBA 将 SQL Server 升级到 2019+，之后可回到 26.x。

### 10.12 通过 / 不通过判定

| 结果 | 条件 | 下一步 |
|---|---|---|
| **PASS** | V1–V6 全绿，且 10.10 的端口收敛（另一台机 8443/9000 均不可达）与明文口令清理完成 | 视为重装成功 → 按 `docs/keycloak-realm-clients-init.md` 执行**清单 A 收尾封口**与**清单 B 建 realm/client**；**之后才允许灌用户** |
| **FAIL-可修** | 某 V 项未过但根因明确（配置项 / 环境变量 / 口令 / 端口） | 按 10.11 处置后**从失败那一步重跑**，禁止跳步继续 |
| **FAIL-需回退** | 25.0.6 仍报 `OPTIMIZE_FOR_SEQUENTIAL_KEY`，或建表反复中断 | 走 10.11 回退阶梯，并同步更新本手册版本矩阵 |

> 判定不通过时**不要**先建 realm 再回头修：realm/client 初始化依赖一个稳定的 25.0.6 运行时，半成品状态会让后续排障同时面对两层问题。

> ⚠️ Express Edition 有 **10GB 库容量上限**——SSO 用户量不大短期够用，但属长期隐患，建议知会 DBA 纳入容量监控。

## 11. 本手册完成后状态

- Keycloak **25.0.6** 以 Windows 服务运行于 IRSCnKettle01，8443 回环 + 自签，9000 健康检查；
- master 域 + kcadmin（break-glass）可用；
- **下一步**（另有文档）：按 `docs/keycloak-realm-clients-init.md` 清单 A 完成收尾封口（服务/健康/IPv6 管理口/防火墙/敏感信息/台账），清单 B 建 realm `inalfa`（SMTP/组/策略）→ `msia-prod`/`bol-prod`/`sync-client`/`account` + groups mapper + secret 注入 → 跑 `sync_sso_to_keycloak.ps1` 灌用户 → 等 CA 证书到手后做 DNS + IIS ARR + 双轨联调。配置语义仍见 `realm-setup.md` / `clients.md`。
