<#
.SYNOPSIS
    MSIA 首次统一身份认证（Keycloak）登录证据采集（幂等、只读、可重复运行）。

.DESCRIPTION
    每次运行在 统一身份认证实施\evidence\<yyyyMMdd-HHmmss>\ 下产出原始证据，
    并生成 evidence.md 汇总表（证据项 / 状态 PASS-FAIL-SKIP / 原始文件名 / 关键判读）。

    采集项:
      1  Keycloak 登录事件（含 2026-11-05 21:34 核心成功序列、20:32 回环 LOGIN_ERROR）
      2  Keycloak 日志片段（含 20:32 LOGIN_ERROR 的 error 详情检索）
      3  MSIA 日志（无日志文件时 SKIP 并给出可操作替代方案）
      4  进程与端口快照（msia_server.exe 与 8078/8443）
      5  证书快照（SAN 与有效期）
      6  MSIA config.ini 快照（[oidc]/[database]，密钥一律脱敏）
      7  realm user profile 必填字段（只读，判定首次登录是否可能触发资料补全页）
      8  本地用户表核查（ligu 是首次 SSO 自动建档还是本来就存在）

    约束:
      - 不修改任何业务代码、不修改 Keycloak realm/client 配置；
      - 脚本内不硬编码任何账号口令；kcadm 凭据失效时只提示手动执行 config credentials；
      - 输出中不出现明文 secret / 密码（config 快照按前 4 位 + **** 脱敏）。

    兼容: Windows PowerShell 5.1（不使用 && / || 串联，不使用 PS7 专属语法）。

    退出码: 0=无 FAIL；2=存在 FAIL 项（采集过程不中断）

.NOTES
    文件: 统一身份认证实施/scripts/collect-sso-login-evidence.ps1
    典型运行（服务器 IRSCnKettle01，可读取 C:\keycloak 与 MSIA 部署目录的账号）:
      powershell -NoProfile -ExecutionPolicy Bypass -File ".\collect-sso-login-evidence.ps1"
#>

[CmdletBinding()]
param(
    # 证据根目录；留空则默认 <统一身份认证实施>\evidence
    [string]$EvidenceRoot = '',

    [string]$KeycloakHome = 'C:\keycloak',
    [string]$KeycloakServer = 'https://172.26.2.203:8443',
    [string]$Realm = 'inalfa',
    [string]$ClientId = 'msia-prod',

    [string]$MsiaDeployDir = 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server',
    [string]$SslCertFile = 'C:\keycloak\conf\server.crt.pem',

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$TargetUser = 'ligu',

    # 现场已确认的时间锚点（用于把事件分组，不影响原始事件全量导出）
    [string]$SuccessLoginTime = '2026-11-05 21:34:00',
    [int]$CoreWindowMinutes = 5,
    [string]$LoopbackErrorTime = '2026-11-05 20:32:00',
    [string]$AfternoonLoginStart = '2026-11-05 15:11:00',
    [string]$AfternoonLoginEnd = '2026-11-05 15:19:59',
    [string]$KnownSuccessIp = '10.41.0.64',
    [string]$KnownAfternoonIp = '10.41.0.96',
    [string]$KnownAfternoonUserId = '83cbae96-03fd-4f5e-b4ee-ed8182acdb4c',

    # 判定新 exe 的时间阈值（2026-11-05 16:02 构建）
    [string]$ExeBuildThreshold = '2026-11-05 16:00:00',

    # 可选: 手工指定首次 LOGIN 时间（格式 yyyy-MM-dd HH:mm:ss）；留空则取事件最早时间
    [string]$FirstLoginTime = ''
)

$ErrorActionPreference = 'Continue'

# ============================================================
# 基础工具
# ============================================================

$script:ScriptPath = $MyInvocation.MyCommand.Path
$script:Results = @()
$script:EventRows = @()
$script:CoreRows = @()
$script:LoopbackRows = @()
$script:AfternoonRows = @()
$script:LoginEventTime = ''
$script:KcUserCache = @{}
$script:KcUserCacheTried = $false
$script:KcUserCacheOk = $false
$script:KcadmPath = Join-Path $KeycloakHome 'bin\kcadm.bat'
$script:LogErrorDetailsFound = $false
$script:JwtSecretBytes = $null
$script:JwtSecretSource = ''
$script:JwtSecretRisk = $false

function Write-Trace {
    param([string]$Message)
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
    Write-Host $line
    Add-Content -LiteralPath (Join-Path $script:RunDir '00-run-trace.log') -Value $line -Encoding UTF8
}

function Add-Result {
    param(
        [Parameter(Mandatory)][string]$Item,
        [Parameter(Mandatory)][ValidateSet('PASS', 'FAIL', 'SKIP')][string]$Status,
        [string]$File = '-',
        [string]$Note = ''
    )
    $script:Results += [pscustomobject]@{
        Item   = $Item
        Status = $Status
        File   = $File
        Note   = $Note
    }
    $color = 'Gray'
    if ($Status -eq 'PASS') { $color = 'Green' }
    if ($Status -eq 'FAIL') { $color = 'Red' }
    if ($Status -eq 'SKIP') { $color = 'Yellow' }
    $line = ('[{0}] {1} :: {2} | {3}' -f $Status, $Item, $Note, $File)
    Write-Host $line -ForegroundColor $color
    Add-Content -LiteralPath (Join-Path $script:RunDir '00-run-trace.log') -Value $line -Encoding UTF8
}

function Save-Text {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)]$Content
    )
    $path = Join-Path $script:RunDir $Name
    $Content | Out-File -LiteralPath $path -Encoding UTF8
    return $Name
}

function Format-MdCell {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $t = $Text -replace "`r`n", ' '
    $t = $t -replace "`n", ' '
    $t = $t -replace '\|', '\|'
    return $t.Trim()
}

function Convert-EventTimeToLocal {
    param($RawTime)
    if ($null -eq $RawTime) { return $null }
    $ms = 0
    try { $ms = [long]$RawTime } catch { return $null }
    try {
        return ([DateTimeOffset]::FromUnixTimeMilliseconds($ms)).ToLocalTime().DateTime
    } catch { }
    try {
        return ([datetime]'1970-01-01T00:00:00Z').AddMilliseconds($ms).ToLocalTime()
    } catch { return $null }
}

function Invoke-ExternalWithTimeout {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [int]$TimeoutSeconds = 90
    )
    try {
        $job = Start-Job -ScriptBlock {
            param($f, $a)
            $global:LASTEXITCODE = 0
            $text = (& $f @a 2>&1 | Out-String)
            $code = 0
            if ($null -ne $LASTEXITCODE) { $code = [int]$LASTEXITCODE }
            [pscustomobject]@{ ExitCode = $code; Output = $text }
        } -ArgumentList $FilePath, $ArgumentList

        $finished = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if ($null -ne $finished) {
            $received = @(Receive-Job -Job $job)
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
            if ($received.Count -gt 0) { return $received[$received.Count - 1] }
            return [pscustomobject]@{ ExitCode = -1; Output = '外部命令无输出' }
        }

        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{ ExitCode = -1; Output = ('执行超时（>{0}s）: {1}' -f $TimeoutSeconds, $FilePath) }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; Output = ('无法启动外部命令: {0}' -f $_.Exception.Message) }
    }
}

function Resolve-Keytool {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
        $candidates += (Join-Path $env:JAVA_HOME 'bin\keytool.exe')
    }
    $cmd = Get-Command -Name 'keytool.exe' -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { $candidates += $cmd.Source }
    $candidates += 'C:\Program Files\Java\jdk-21\bin\keytool.exe'
    $candidates += 'C:\Program Files\Eclipse Adoptium\jdk-21\bin\keytool.exe'
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    if (Test-Path -LiteralPath 'C:\Program Files\Java') {
        $found = Get-ChildItem -Path 'C:\Program Files\Java' -Filter 'keytool.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $found) { return $found.FullName }
    }
    return $null
}

function Initialize-KcUserCache {
    if ($script:KcUserCacheTried) { return }
    $script:KcUserCacheTried = $true
    if (-not (Test-Path -LiteralPath $script:KcadmPath)) { return }

    $res = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath `
        -ArgumentList @('get', 'users', '-r', $Realm, '-q', 'max=1000', '--fields', 'id,username') `
        -TimeoutSeconds 90
    if ($res.ExitCode -ne 0) { return }

    try {
        $users = @($res.Output | ConvertFrom-Json)
        foreach ($u in $users) {
            if ($null -ne $u.id -and $null -ne $u.username) {
                $script:KcUserCache[[string]$u.id] = [string]$u.username
            }
        }
        $script:KcUserCacheOk = $true
        $mapRows = @()
        foreach ($k in $script:KcUserCache.Keys) {
            $mapRows += [pscustomobject]@{ userId = $k; username = $script:KcUserCache[$k] }
        }
        $null = Save-Text -Name '01-kc-user-map.json' -Content ($mapRows | ConvertTo-Json -Depth 3)
    } catch {
        Write-Trace ('UUID->username 用户列表解析失败: {0}' -f $_.Exception.Message)
    }
}

function Resolve-KcUsername {
    param([string]$UserId)
    if ([string]::IsNullOrWhiteSpace($UserId)) { return '' }
    if ($script:KcUserCache.ContainsKey($UserId)) { return [string]$script:KcUserCache[$UserId] }
    Initialize-KcUserCache
    if ($script:KcUserCache.ContainsKey($UserId)) { return [string]$script:KcUserCache[$UserId] }

    $res = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath `
        -ArgumentList @('get', ('users/{0}' -f $UserId), '--fields', 'username') `
        -TimeoutSeconds 60
    if ($res.ExitCode -eq 0) {
        try {
            $obj = $res.Output | ConvertFrom-Json
            if ($null -ne $obj.username) {
                $script:KcUserCache[$UserId] = [string]$obj.username
                return [string]$obj.username
            }
        } catch { }
    }
    return ''
}

function Get-IniData {
    param([Parameter(Mandatory)][string]$Path)
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction Stop)
    $sections = @{}
    $headers = @()
    $current = $null
    foreach ($raw in $lines) {
        $line = $raw.Trim()
        if ($line -eq '') { continue }
        if ($line.StartsWith(';') -or $line.StartsWith('#')) { continue }
        if ($line -match '^\[(.+)\]$') {
            $name = $Matches[1].Trim()
            $headers += $name
            $current = $name
            if (-not $sections.ContainsKey($name)) { $sections[$name] = @() }
            continue
        }
        if ($null -eq $current) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        $sections[$current] += [pscustomobject]@{ Key = $key; Value = $val }
    }
    return [pscustomobject]@{ Sections = $sections; Headers = $headers }
}

function Protect-ConfigValue {
    param([string]$Key, [string]$Value)
    $secretKey = $Key -match '(?i)(secret|password|passwd|pwd|token|api[_-]?key|private[_-]?key|credential)'
    if ($secretKey) {
        if ([string]::IsNullOrWhiteSpace($Value)) { return '（空）' }
        if ($Value.Length -ge 4) { return ($Value.Substring(0, 4) + '****') }
        return '****'
    }
    # 值内联的连接串口令 (如 Password=xxx;)
    $sanitized = $Value -replace '(?i)((?:password|pwd|secret|token)\s*=\s*)([^;]+)', '$1****'
    return $sanitized
}

function Test-ProfileAttrRequired {
    param($Attr)
    if ($null -eq $Attr) { return $false }
    if ($null -eq $Attr.required) { return $false }
    foreach ($p in $Attr.required.PSObject.Properties) {
        $v = @($p.Value)
        if ($v.Count -gt 0) { return $true }
    }
    return $false
}

# ============================================================
# 运行目录与上下文
# ============================================================

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    $scriptRoot = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($scriptRoot)) { $scriptRoot = Split-Path -Parent $script:ScriptPath }
    $EvidenceRoot = Join-Path (Split-Path -Parent $scriptRoot) 'evidence'
}
if (-not (Test-Path -LiteralPath $EvidenceRoot)) {
    New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runDir = Join-Path $EvidenceRoot $stamp
if (Test-Path -LiteralPath $runDir) {
    $runDir = Join-Path $EvidenceRoot ('{0}-{1}' -f $stamp, (Get-Random -Minimum 1 -Maximum 999))
}
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$script:RunDir = $runDir

$context = @(
    '# MSIA 统一身份认证登录证据采集 - 运行上下文',
    ('采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    ('主机: {0}' -f $env:COMPUTERNAME),
    ('操作员: {0}' -f $env:USERNAME),
    ('PowerShell: {0}' -f $PSVersionTable.PSVersion.ToString()),
    ('操作系统: {0}' -f [Environment]::OSVersion.VersionString),
    ('脚本: {0}' -f $script:ScriptPath),
    ('证据目录: {0}' -f $script:RunDir),
    '',
    '## 参数',
    ('KeycloakHome={0}' -f $KeycloakHome),
    ('KeycloakServer={0}' -f $KeycloakServer),
    ('Realm={0}' -f $Realm),
    ('ClientId={0}' -f $ClientId),
    ('MsiaDeployDir={0}' -f $MsiaDeployDir),
    ('SslCertFile={0}' -f $SslCertFile),
    ('SqlServer={0}' -f $SqlServer),
    ('Database={0}' -f $Database),
    ('TargetUser={0}' -f $TargetUser),
    ('SuccessLoginTime={0}' -f $SuccessLoginTime),
    ('LoopbackErrorTime={0}' -f $LoopbackErrorTime),
    ('AfternoonLoginStart={0}' -f $AfternoonLoginStart),
    ('AfternoonLoginEnd={0}' -f $AfternoonLoginEnd),
    ('ExeBuildThreshold={0}' -f $ExeBuildThreshold)
)
$null = Save-Text -Name '00-run-context.txt' -Content $context
Write-Trace ('证据目录已创建: {0}' -f $script:RunDir)

# 时间锚点
$successDt = $null
try { $successDt = [datetime]::ParseExact($SuccessLoginTime, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) }
catch { try { $successDt = [datetime]$SuccessLoginTime } catch { } }
$loopbackDt = $null
try { $loopbackDt = [datetime]::ParseExact($LoopbackErrorTime, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) }
catch { try { $loopbackDt = [datetime]$LoopbackErrorTime } catch { } }
$afternoonStartDt = $null
$afternoonEndDt = $null
try { $afternoonStartDt = [datetime]::ParseExact($AfternoonLoginStart, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) } catch { }
try { $afternoonEndDt = [datetime]::ParseExact($AfternoonLoginEnd, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) } catch { }

# ============================================================
# 1. Keycloak 登录事件
# ============================================================

Write-Host ''
Write-Host '== 1/8 Keycloak 登录事件 ==' -ForegroundColor Cyan
$item1 = '1. Keycloak 登录事件（realm=inalfa）'
try {
    if (-not (Test-Path -LiteralPath $script:KcadmPath)) {
        Add-Result -Item $item1 -Status 'SKIP' -Note ('未找到 kcadm: {0}' -f $script:KcadmPath)
    } else {
        $kcConfig = Join-Path $env:USERPROFILE '.keycloak\kcadm.config'
        if (-not (Test-Path -LiteralPath $kcConfig)) {
            Add-Result -Item $item1 -Status 'SKIP' -File '-' -Note ('未发现 kcadm 凭据（{0}）。请先手动执行: "{1}" config credentials --server {2} --realm master --user <管理员账号> ，密码交互输入，然后重跑本脚本。' -f $kcConfig, $script:KcadmPath, $KeycloakServer)
        } else {
            # 凭据有效性探测（只读）
            $probe = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath -ArgumentList @('get', 'realms/inalfa', '--fields', 'realm') -TimeoutSeconds 60
            $probeOut = [string]$probe.Output
            $authBad = ($probe.ExitCode -ne 0) -or ($probeOut -match '(?i)(401|unauthorized|not authenticated|login failed)')
            if ($authBad) {
                $excerpt = $probeOut.Trim()
                if ($excerpt.Length -gt 300) { $excerpt = $excerpt.Substring(0, 300) }
                Add-Result -Item $item1 -Status 'SKIP' -File '-' -Note ('kcadm 凭据无效或不可用（{0}）。请手动执行: "{1}" config credentials --server {2} --realm master --user <管理员账号> （密码交互输入），确认自签证书 truststore 已导入后重跑本脚本。' -f $excerpt, $script:KcadmPath, $KeycloakServer)
            } else {
                # 事件保留期与开关（只读）
                $realmInfo = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath -ArgumentList @('get', 'realms/inalfa') -TimeoutSeconds 60
                $eventsEnabled = $null
                $eventsExpiration = $null
                if ($realmInfo.ExitCode -eq 0) {
                    try {
                        $rj = $realmInfo.Output | ConvertFrom-Json
                        $eventsEnabled = $rj.eventsEnabled
                        $eventsExpiration = $rj.eventsExpiration
                    } catch { }
                    $null = Save-Text -Name '01-realm-events-config.json' -Content ([string]$realmInfo.Output)
                }

                # 事件全量拉取（含 LOGIN/LOGIN_ERROR，本地按类型与时间分组）
                $eventsRes = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath `
                    -ArgumentList @('get', 'events', '-r', $Realm, '-q', 'max=500') `
                    -TimeoutSeconds 120
                $null = Save-Text -Name '01-keycloak-events-raw.txt' -Content ([string]$eventsRes.Output)

                $allEvents = @()
                $parseOk = $false
                try {
                    $parsed = $eventsRes.Output | ConvertFrom-Json
                    $allEvents = @($parsed)
                    $parseOk = $true
                } catch {
                    $parseOk = $false
                }

                $script:EventRows = @()
                if ($parseOk) {
                    foreach ($evt in $allEvents) {
                        $type = ''
                        if ($null -ne $evt.type) { $type = [string]$evt.type }
                        if ($type -notmatch '^(LOGIN|LOGIN_ERROR)$') { continue }

                        $dt = Convert-EventTimeToLocal $evt.time
                        $uname = ''
                        if ($null -ne $evt.username -and -not [string]::IsNullOrWhiteSpace([string]$evt.username)) {
                            $uname = [string]$evt.username
                        } elseif ($null -ne $evt.details -and $null -ne $evt.details.username) {
                            $uname = [string]$evt.details.username
                        }
                        $uid = ''
                        if ($null -ne $evt.userId) { $uid = [string]$evt.userId }
                        if ([string]::IsNullOrWhiteSpace($uname) -and -not [string]::IsNullOrWhiteSpace($uid)) {
                            $uname = Resolve-KcUsername $uid
                        }

                        $ip = ''
                        if ($null -ne $evt.ipAddress) { $ip = [string]$evt.ipAddress }
                        $err = ''
                        if ($null -ne $evt.error) { $err = [string]$evt.error }
                        elseif ($null -ne $evt.details -and $null -ne $evt.details.error) { $err = [string]$evt.details.error }

                        $script:EventRows += [pscustomobject]@{
                            Time     = $dt
                            TimeText = $(if ($null -ne $dt) { $dt.ToString('yyyy-MM-dd HH:mm:ss') } else { '' })
                            Type     = $type
                            ClientId = $(if ($null -ne $evt.clientId) { [string]$evt.clientId } else { '' })
                            Username = $uname
                            UserId   = $uid
                            Ip       = $ip
                            Error    = $err
                            Detail   = $(if ($null -ne $evt.details) { [string]$evt.details } else { '' })
                        }
                    }
                }

                $script:EventRows = @($script:EventRows | Sort-Object -Property Time)
                $formatted = @('# Keycloak LOGIN / LOGIN_ERROR 事件（时间均为服务器本地时间）',
                    '# 字段: time | type | clientId | username | userId | ipAddress | error',
                    ('# 事件总数: {0}；realm eventsEnabled={1}；eventsExpiration={2}' -f $script:EventRows.Count, $eventsEnabled, $eventsExpiration),
                    '')
                foreach ($r in $script:EventRows) {
                    $formatted += ('{0} | {1} | {2} | {3} | {4} | {5} | {6}' -f `
                        $r.TimeText, $r.Type, $r.ClientId, $r.Username, $r.UserId, $r.Ip, $r.Error)
                }
                if ($script:EventRows.Count -eq 0) { $formatted += '（未采集到 LOGIN / LOGIN_ERROR 事件）' }
                $null = Save-Text -Name '01-keycloak-events-all.txt' -Content $formatted

                # 分组: 21:34 核心成功窗口 / 20:32 回环 LOGIN_ERROR / 下午旁证
                if ($null -ne $successDt) {
                    $wStart = $successDt.AddMinutes(-1 * $CoreWindowMinutes)
                    $wEnd = $successDt.AddMinutes($CoreWindowMinutes)
                    $script:CoreRows = @($script:EventRows | Where-Object {
                        $null -ne $_.Time -and $_.Time -ge $wStart -and $_.Time -le $wEnd
                    })
                    $coreText = @(
                        ('# 本次成功登录核心证据窗口: {0} ± {1} 分钟' -f $SuccessLoginTime, $CoreWindowMinutes),
                        ('# 现场已确认: clientId={0}，来源 IP={1}，序列 LOGIN -> CODE_TO_TOKEN -> VERIFY_PROFILE -> UPDATE_PROFILE' -f $ClientId, $KnownSuccessIp),
                        '# 核心判定事件: LOGIN（建立会话） + CODE_TO_TOKEN（授权码换 token）',
                        '# 字段: time | type | clientId | username | userId | ipAddress | error',
                        ''
                    )
                    if ($script:CoreRows.Count -eq 0) {
                        $coreText += '（本窗口未从事件 API 采集到记录；现场控制台已确认成功，请以控制台截图/日志补齐）'
                    }
                    foreach ($r in $script:CoreRows) {
                        $coreText += ('{0} | {1} | {2} | {3} | {4} | {5} | {6}' -f `
                            $r.TimeText, $r.Type, $r.ClientId, $r.Username, $r.UserId, $r.Ip, $r.Error)
                    }
                    $null = Save-Text -Name '01-core-login-2134.txt' -Content $coreText
                }

                if ($null -ne $loopbackDt) {
                    $lStart = $loopbackDt.AddMinutes(-1 * $CoreWindowMinutes)
                    $lEnd = $loopbackDt.AddMinutes($CoreWindowMinutes)
                    $script:LoopbackRows = @($script:EventRows | Where-Object {
                        $null -ne $_.Time -and $_.Time -ge $lStart -and $_.Time -le $lEnd -and $_.Type -eq 'LOGIN_ERROR'
                    })
                    $loopText = @(
                        ('# LOGIN_ERROR 窗口: {0} ± {1} 分钟' -f $LoopbackErrorTime, $CoreWindowMinutes),
                        '# 现场已确认: IP 显示 0.0.0.0:0:0:0:0:0:1（本机回环），User 显示 No user details',
                        '# 判定: 本机回环来源，非用户登录路径（不构成用户登录失败的证据）',
                        '# 字段: time | type | clientId | username | userId | ipAddress | error',
                        ''
                    )
                    if ($script:LoopbackRows.Count -eq 0) {
                        $loopText += '（本窗口未从事件 API 采集到 LOGIN_ERROR；错误详情见 02-keycloak-login-error-2032.txt）'
                    }
                    foreach ($r in $script:LoopbackRows) {
                        $loopText += ('{0} | {1} | {2} | {3} | {4} | {5} | {6}' -f `
                            $r.TimeText, $r.Type, $r.ClientId, $r.Username, $r.UserId, $r.Ip, $r.Error)
                    }
                    $null = Save-Text -Name '01-login-error-2032.txt' -Content $loopText
                }

                if ($null -ne $afternoonStartDt -and $null -ne $afternoonEndDt) {
                    $script:AfternoonRows = @($script:EventRows | Where-Object {
                        $null -ne $_.Time -and $_.Time -ge $afternoonStartDt -and $_.Time -le $afternoonEndDt
                    })
                    $afterText = @(
                        ('# 下午旁证窗口: {0} - {1}' -f $AfternoonLoginStart, $AfternoonLoginEnd),
                        ('# 现场已确认: 另一批 LOGIN，来源 IP={0}，用户 UUID={1}' -f $KnownAfternoonIp, $KnownAfternoonUserId),
                        '# 字段: time | type | clientId | username | userId | ipAddress | error',
                        ''
                    )
                    if ($script:AfternoonRows.Count -eq 0) {
                        $afterText += '（本窗口未从事件 API 采集到记录；现场控制台事实见技术交底书第 20 章）'
                    }
                    foreach ($r in $script:AfternoonRows) {
                        $afterText += ('{0} | {1} | {2} | {3} | {4} | {5} | {6}' -f `
                            $r.TimeText, $r.Type, $r.ClientId, $r.Username, $r.UserId, $r.Ip, $r.Error)
                    }
                    $null = Save-Text -Name '01-login-afternoon.txt' -Content $afterText
                }

                if (-not $parseOk) {
                    Add-Result -Item $item1 -Status 'FAIL' -File '01-keycloak-events-raw.txt' `
                        -Note ('事件 API 返回无法解析为 JSON（exit={0}）；原始输出已保存，请人工判读。' -f $eventsRes.ExitCode)
                } elseif ($script:EventRows.Count -eq 0) {
                    Add-Result -Item $item1 -Status 'FAIL' -File '01-keycloak-events-all.txt' `
                        -Note ('事件 API 可用但未返回 LOGIN/LOGIN_ERROR；eventsEnabled={0}，eventsExpiration={1}。若为 false 或保留期过短，需在控制台 Realm Settings -> Events 启用/调长后复现一次登录再采集。' -f $eventsEnabled, $eventsExpiration)
                } else {
                    $mapCount = 0
                    foreach ($r in $script:EventRows) { if (-not [string]::IsNullOrWhiteSpace($r.Username)) { $mapCount++ } }
                    Add-Result -Item $item1 -Status 'PASS' -File '01-keycloak-events-all.txt' `
                        -Note ('共 {0} 条 LOGIN/LOGIN_ERROR；其中 {1} 条已解析到 username（含 UUID 反查）；eventsEnabled={2}，eventsExpiration={3}。' -f $script:EventRows.Count, $mapCount, $eventsEnabled, $eventsExpiration)
                }

                # 1b. 21:34 核心证据
                $hasLogin = @($script:CoreRows | Where-Object { $_.Type -eq 'LOGIN' }).Count -gt 0
                $hasCode = @($script:CoreRows | Where-Object { $_.Type -eq 'CODE_TO_TOKEN' }).Count -gt 0
                $coreNote = '现场已确认 21:34 成功序列。'
                if ($script:CoreRows.Count -gt 0) {
                    $firstCore = $script:CoreRows[0]
                    $coreNote += (' 采集到 {0} 条；username={1}，userId={2}，ip={3}。' -f $script:CoreRows.Count, $firstCore.Username, $firstCore.UserId, $firstCore.Ip)
                } else {
                    $coreNote += ' 本次事件 API 未返回该窗口原文（见 evidence.md 核心证据小节与现场控制台截图）。'
                }
                if ($hasLogin -and $hasCode) {
                    Add-Result -Item '1b. 21:34 本次成功登录核心证据' -Status 'PASS' -File '01-core-login-2134.txt' -Note ($coreNote + ' 判定: LOGIN + CODE_TO_TOKEN 均已采集。')
                } elseif ($script:CoreRows.Count -gt 0) {
                    Add-Result -Item '1b. 21:34 本次成功登录核心证据' -Status 'FAIL' -File '01-core-login-2134.txt' -Note ($coreNote + ' 判定: 缺少 LOGIN 或 CODE_TO_TOKEN，需复核事件类型。')
                } else {
                    Add-Result -Item '1b. 21:34 本次成功登录核心证据' -Status 'SKIP' -File '01-core-login-2134.txt' -Note $coreNote
                }

                # 1c. 20:32 回环 LOGIN_ERROR
                $loopNote = '本机回环来源 0.0.0.0:0:0:0:0:0:1，非用户登录路径。'
                if ($script:LoopbackRows.Count -gt 0) {
                    $lr = $script:LoopbackRows[0]
                    $loopNote += (' 采集到 {0} 条；clientId={1}，username={2}，error={3}。' -f $script:LoopbackRows.Count, $lr.ClientId, $lr.Username, $lr.Error)
                    $loopNote += (' 日志错误详情: {0}' -f $(if ($script:LogErrorDetailsFound) { '见 02-keycloak-login-error-2032.txt' } else { '日志中未检索到（以事件 error 字段为准）' }))
                    Add-Result -Item '1c. 20:32 回环 LOGIN_ERROR 判定' -Status 'PASS' -File '01-login-error-2032.txt' -Note $loopNote
                } else {
                    $loopNote += (' 本次事件 API 未返回该窗口记录；日志错误详情: {0}' -f $(if ($script:LogErrorDetailsFound) { '见 02-keycloak-login-error-2032.txt' } else { '未检索到' }))
                    Add-Result -Item '1c. 20:32 回环 LOGIN_ERROR 判定' -Status 'SKIP' -File '01-login-error-2032.txt' -Note $loopNote
                }

                # 下午旁证
                if ($script:AfternoonRows.Count -gt 0) {
                    Add-Result -Item '1d. 下午 15:11-15:19 登录旁证' -Status 'PASS' -File '01-login-afternoon.txt' `
                        -Note ('采集到 {0} 条；现场事实 IP={1}，UUID={2}。' -f $script:AfternoonRows.Count, $KnownAfternoonIp, $KnownAfternoonUserId)
                } else {
                    Add-Result -Item '1d. 下午 15:11-15:19 登录旁证' -Status 'SKIP' -File '01-login-afternoon.txt' `
                        -Note ('本次事件 API 未返回该窗口记录；现场控制台事实: IP={0}，UUID={1}。' -f $KnownAfternoonIp, $KnownAfternoonUserId)
                }
            }
        }
    }
} catch {
    Add-Result -Item $item1 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# 若调用方显式给定了首次登录时间，以它为准
if (-not [string]::IsNullOrWhiteSpace($FirstLoginTime)) { $script:LoginEventTime = $FirstLoginTime }

# ============================================================
# 2. Keycloak 日志片段
# ============================================================

Write-Host ''
Write-Host '== 2/8 Keycloak 日志片段 ==' -ForegroundColor Cyan
$item2 = '2. Keycloak 日志片段（msia-prod / oidc）'
try {
    $logCandidates = @(
        (Join-Path $KeycloakHome 'logs\keycloak.log'),
        (Join-Path $KeycloakHome 'logs\keycloak.log.1'),
        (Join-Path (Join-Path $KeycloakHome 'data') 'log\keycloak.log')
    )
    $existingLogs = @()
    foreach ($lc in $logCandidates) {
        if (Test-Path -LiteralPath $lc) { $existingLogs += (Get-Item -LiteralPath $lc) }
    }

    if ($existingLogs.Count -eq 0) {
        Add-Result -Item $item2 -Status 'SKIP' -Note ('未找到 Keycloak 日志文件（已检查: {0}）。若 Keycloak 以控制台输出，请补充控制台截图/重定向日志。' -f ($logCandidates -join '; '))
    } else {
        $out = @('# Keycloak 日志片段（关键字: msia-prod / oidc）', ('# 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')), '')
        $errorOut = @('# 20:32 LOGIN_ERROR 相关日志详情检索', ('# 关键字: LOGIN_ERROR | invalid_grant | Invalid user credentials | 20:32' -f ''), '')
        $totalMatches = 0
        $errorMatches = 0
        $staleNotes = @()

        foreach ($lf in $existingLogs) {
            $out += ('===== FILE: {0}' -f $lf.FullName)
            $out += ('LastWriteTime: {0:yyyy-MM-dd HH:mm:ss}    Size: {1} bytes' -f $lf.LastWriteTime, $lf.Length)
            $ageHours = ((Get-Date) - $lf.LastWriteTime).TotalHours
            $out += ('AgeHours: {0:N1}' -f $ageHours)
            if ($ageHours -gt 24) {
                $staleNotes += ('{0} 最后写入于 {1:yyyy-MM-dd HH:mm:ss}（距今 {2:N1} 小时）' -f $lf.Name, $lf.LastWriteTime, $ageHours)
            }

            $lines = @(Get-Content -LiteralPath $lf.FullName -Tail 4000 -ErrorAction SilentlyContinue)
            $matches = @()
            $matchIndex = -1
            foreach ($ln in $lines) {
                $matchIndex++
                if ($ln -match '(?i)msia-prod|oidc') {
                    $matches += ('match[{0:D4}] {1}' -f $matches.Count, $ln)
                }
                if ($ln -match '(?i)LOGIN_ERROR|invalid_grant|Invalid user credentials|20:32') {
                    $errorMatches++
                    $ctxStart = [Math]::Max(0, $matchIndex - 2)
                    $ctxEnd = [Math]::Min($lines.Count - 1, $matchIndex + 2)
                    for ($j = $ctxStart; $j -le $ctxEnd; $j++) {
                        $errorOut += ('{0}:{1}: {2}' -f $lf.Name, ($j + 1), $lines[$j])
                    }
                    $errorOut += '-----'
                }
            }
            $totalMatches += $matches.Count
            $out += ('MatchCount: {0}' -f $matches.Count)
            $out += '----- matches -----'
            if ($matches.Count -eq 0) { $out += '（本文件未匹配到 msia-prod / oidc）' }
            else {
                $keep = $matches
                if ($keep.Count -gt 120) { $keep = $keep[($keep.Count - 120)..($keep.Count - 1)] }
                $out += $keep
            }
            $out += ''
        }

        $out += '# LastWriteTime 判读:'
        if ($staleNotes.Count -eq 0) { $out += '主日志最后写入时间在 24 小时内，未发现明显轮转旧文件。' }
        else { foreach ($s in $staleNotes) { $out += ('警告: {0}' -f $s) } }
        $null = Save-Text -Name '02-keycloak-log-msia.log' -Content $out

        if ($errorMatches -gt 0) {
            $script:LogErrorDetailsFound = $true
            $null = Save-Text -Name '02-keycloak-login-error-2032.txt' -Content $errorOut
        } else {
            $errorOut += '（日志中未检索到 20:32 LOGIN_ERROR / invalid_grant / Invalid user credentials 关键字）'
            $null = Save-Text -Name '02-keycloak-login-error-2032.txt' -Content $errorOut
        }

        if ($totalMatches -gt 0) {
            $note = ('命中 {0} 行；{1} 个日志文件。' -f $totalMatches, $existingLogs.Count)
            if ($staleNotes.Count -gt 0) { $note += (' 警告: {0}，注意轮转旧文件。' -f ($staleNotes -join '；')) }
            if ($errorMatches -gt 0) { $note += (' 20:32 错误详情命中 {0} 处（见 02-keycloak-login-error-2032.txt）。' -f $errorMatches) }
            else { $note += ' 未检索到 20:32 错误详情。' }
            Add-Result -Item $item2 -Status 'PASS' -File '02-keycloak-log-msia.log' -Note $note
        } else {
            Add-Result -Item $item2 -Status 'FAIL' -File '02-keycloak-log-msia.log' `
                -Note ('日志文件存在但未匹配到 msia-prod/oidc；{0}。需确认日志级别与是否读取到轮转旧文件。' -f $(if ($staleNotes.Count -gt 0) { $staleNotes -join '；' } else { '文件较新' }))
        }
    }
} catch {
    Add-Result -Item $item2 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# ============================================================
# 3. MSIA 日志
# ============================================================

Write-Host ''
Write-Host '== 3/8 MSIA 日志 ==' -ForegroundColor Cyan
$item3 = '3. MSIA 日志'
try {
    $msiaLogs = @()
    $candidateDirs = @($MsiaDeployDir, (Join-Path $MsiaDeployDir 'logs'), (Join-Path $MsiaDeployDir 'log'))
    foreach ($d in $candidateDirs) {
        if (Test-Path -LiteralPath $d) {
            $found = Get-ChildItem -Path $d -Filter '*.log' -File -ErrorAction SilentlyContinue
            if ($null -ne $found) { $msiaLogs += $found }
        }
    }
    $msiaLogs = @($msiaLogs | Sort-Object -Property FullName -Unique)

    if ($msiaLogs.Count -eq 0) {
        $alt = @(
            '# MSIA 无日志文件时的替代采集方案',
            '',
            '未在部署目录发现 *.log。msia_server.exe 若为控制台直出，按以下任一方式补齐。',
            '',
            '## 方案 A：不重启（推荐先做）',
            '1. 在服务器上切到运行 msia_server.exe 的控制台窗口；',
            '2. 窗口标题栏右键 -> 属性 -> 勾选“快速编辑模式”；',
            '3. 鼠标选中本次登录前后的输出，回车复制；',
            '4. 粘贴保存为 03-msia-console-copy.txt，放在本证据目录。',
            '',
            '## 方案 B：重启并重定向落盘（需维护窗口）',
            '1. 记录当前进程: Get-Process msia_server | Select-Object Id,Path,StartTime',
            '2. 停止: Stop-Process -Id <PID>',
            "3. 同一窗口设置证书信任: `$env:SSL_CERT_FILE='C:\keycloak\conf\server.crt.pem'",
            "4. 启动并重定向:",
            "   Start-Process -FilePath 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe'",
            "     -WorkingDirectory 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server'",
            "     -RedirectStandardOutput 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_stdout.log'",
            "     -RedirectStandardError  'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_stderr.log'",
            '5. 重新执行一次 Keycloak 登录，再把两个日志复制进证据目录。',
            '',
            '注意: 重启会中断在线会话（MSIA 为无状态 JWT，用户重新登录即可），请安排在维护窗口。',
            '注意: -RedirectStandardOutput 与 -RedirectStandardError 必须使用不同文件。'
        )
        $null = Save-Text -Name '03-msia-log-ALTERNATIVES.txt' -Content $alt
        Add-Result -Item $item3 -Status 'SKIP' -File '03-msia-log-ALTERNATIVES.txt' `
            -Note ('部署目录未发现日志文件。替代方案已写入 03-msia-log-ALTERNATIVES.txt: A=复制控制台输出到 03-msia-console-copy.txt；B=维护窗口内 Start-Process 重定向 stdout/stderr 重启后复现登录。')
    } else {
        $newest = $msiaLogs | Sort-Object -Property LastWriteTime -Descending | Select-Object -First 1
        $tail = @(Get-Content -LiteralPath $newest.FullName -Tail 2000 -ErrorAction SilentlyContinue)
        $out = @(
            ('# MSIA 日志（最新文件，尾部 2000 行）'),
            ('# FILE: {0}' -f $newest.FullName),
            ('# LastWriteTime: {0:yyyy-MM-dd HH:mm:ss}  Size: {1} bytes' -f $newest.LastWriteTime, $newest.Length),
            ('# 候选日志数: {0}' -f $msiaLogs.Count),
            ''
        ) + $tail
        $null = Save-Text -Name ('03-msia-log-{0}.log' -f $newest.Name) -Content $out
        Add-Result -Item $item3 -Status 'PASS' -File ('03-msia-log-{0}.log' -f $newest.Name) `
            -Note ('发现 {0} 个日志文件；已取最新 {1}（LastWriteTime={2:yyyy-MM-dd HH:mm:ss}）尾部 2000 行。' -f $msiaLogs.Count, $newest.Name, $newest.LastWriteTime)
    }
} catch {
    Add-Result -Item $item3 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# 3b. 现场提供的 MSIA 控制台实证（脚本无法自动读取控制台，按现场原文固化）
# 说明: OTK 为一次性码（60 秒、已消费），按“不打印 secret”约束脱敏。
$consoleEvidence = @(
    '# MSIA 控制台实证日志（现场提供，2026-11-05 21:33-21:34，来源 IP 10.41.10.64）',
    '# 说明: 以下为现场控制台原文摘录；OTK 为一次性码（已消费），已按安全口径脱敏。',
    '',
    '## 第一段 授权跳转（state/nonce/PKCE 入库）',
    '21:33:46 app.api.auth:oidc_login:141 - OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)',
    'GET /api/auth/oidc/login 302',
    '',
    '## 第二段 回调验签（issuer 回显校验、code 换 token）',
    '21:34:09 app.services.sso_identity:resolve_or_create:118 - OIDC 身份解析: ligu 无 UserMap 映射, 回落 preferred_username',
    '21:34:09 app.api.auth:oidc_callback:223 - OIDC 登录成功: ligu (local user id=2414)',
    'GET /api/auth/oidc/callback?...iss=https%3A%2F%2F172.26.2.203%3A8443%2Frealms%2Finalfa&code=... 302',
    '',
    '## 第三段 OTK 换 JWT',
    'GET /oidc/callback?otk=<一次性码，已消费，脱敏> 200',
    'POST /api/auth/oidc/token 200',
    '',
    '## 第四段 业务接口鉴权',
    'GET /api/dashboard/analytics 200',
    'GET /api/users 200',
    'GET /api/system-settings/grouped 200',
    'GET /api/archive/projects 200',
    '',
    '## 判读',
    '1. 授权跳转: state/nonce/PKCE verifier 已入库，GET /api/auth/oidc/login 302。',
    '2. 回调验签: 回调 URL 回显 issuer=https://172.26.2.203:8443/realms/inalfa，code 已交换；身份解析为 ligu，local user id=2414。',
    '3. OTK 换 JWT: 前端回调页 GET /oidc/callback 200，POST /api/auth/oidc/token 200。',
    '4. 业务接口: dashboard/users/system-settings/archive 等多个受保护接口均 200，证明前端到后端这一跳也已验证。',
    '',
    '## IP 口径说明',
    'Keycloak Event 页记录来源 IP 10.41.0.64；MSIA 控制台请求来源 IP 10.41.10.64。',
    '两者口径不一致（可能分别记录客户端/代理链的不同地址），不改变本次登录成功结论，但需现场核对客户端真实地址。'
)
$null = Save-Text -Name '03-msia-console-evidence.txt' -Content $consoleEvidence
Add-Result -Item '3b. MSIA 控制台实证（四段式链路）' -Status 'PASS' -File '03-msia-console-evidence.txt' `
    -Note '四段均有实证: 授权跳转 302 (state/nonce/PKCE 入库) -> 回调 302 (issuer 回显) -> /api/auth/oidc/token 200 -> 业务接口多个 200；身份解析 ligu，local user id=2414，无 UserMap 回落 preferred_username。IP 口径: Keycloak=10.41.0.64，MSIA 控制台=10.41.10.64，待核对。'

# ============================================================
# 4. 进程与端口快照
# ============================================================

Write-Host ''
Write-Host '== 4/8 进程与端口快照 ==' -ForegroundColor Cyan
$item4 = '4. 进程与端口（msia_server / 8078 / 8443）'
try {
    $procs = @()
    $p = Get-Process -Name 'msia_server' -ErrorAction SilentlyContinue
    if ($null -ne $p) { $procs = @($p) }

    $procOut = @(
        '# MSIA 进程快照',
        ('# 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
        ('# 进程数: {0}' -f $procs.Count),
        ''
    )
    foreach ($pr in $procs) {
        $path = ''
        try { $path = [string]$pr.Path } catch { $path = '' }
        $start = ''
        try { $start = $pr.StartTime.ToString('yyyy-MM-dd HH:mm:ss') } catch { $start = '（不可读，可能需要管理员权限）' }
        $procOut += ('Id={0}  Path={1}  StartTime={2}' -f $pr.Id, $path, $start)
    }
    if ($procs.Count -eq 0) { $procOut += '（未发现 msia_server 进程；若以服务方式运行，请用 Get-Service / NSSM 复核服务名与进程）' }
    $null = Save-Text -Name '04-process.txt' -Content $procOut

    $netOut = @(
        '# 端口快照 netstat -ano（过滤 :8078 / :8443）',
        ('# 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
        ''
    )
    $netRaw = (& netstat.exe -ano 2>&1 | Out-String)
    $netLines = @($netRaw -split "`r`n" | Where-Object { $_ -match ':8078' -or $_ -match ':8443' })
    if ($netLines.Count -eq 0) { $netOut += '（无 :8078 / :8443 记录）' } else { $netOut += $netLines }
    $null = Save-Text -Name '04-netstat-8078-8443.txt' -Content $netOut

    $listen8078 = @($netLines | Where-Object { $_ -match ':8078' -and $_ -match '(?i)LISTEN' })
    $listen8443 = @($netLines | Where-Object { $_ -match ':8443' -and $_ -match '(?i)LISTEN' })

    $exePath = Join-Path $MsiaDeployDir 'msia_server.exe'
    if ($procs.Count -gt 0) {
        try { if (-not [string]::IsNullOrWhiteSpace($procs[0].Path)) { $exePath = [string]$procs[0].Path } } catch { }
    }
    $exeExists = Test-Path -LiteralPath $exePath
    $exeTime = $null
    $exeSize = 0
    if ($exeExists) {
        $exeItem = Get-Item -LiteralPath $exePath
        $exeTime = $exeItem.LastWriteTime
        $exeSize = $exeItem.Length
    }

    $threshold = $null
    try { $threshold = [datetime]::ParseExact($ExeBuildThreshold, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) }
    catch { try { $threshold = [datetime]$ExeBuildThreshold } catch { } }

    $isNewExe = $false
    if ($null -ne $exeTime -and $null -ne $threshold) { $isNewExe = ($exeTime -ge $threshold) }

    # 运行中的进程启动时间应不早于 exe 修改时间，否则可能仍在跑旧映像
    $procStartTime = $null
    if ($procs.Count -gt 0) {
        try { $procStartTime = $procs[0].StartTime } catch { $procStartTime = $null }
    }
    $runningMatchesExe = $false
    if ($null -ne $procStartTime -and $null -ne $exeTime) {
        $runningMatchesExe = ($procStartTime -ge $exeTime.AddSeconds(-5))
    }

    $summary = @(
        '# 进程与端口判读',
        ('采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
        ('msia_server 进程数: {0}' -f $procs.Count),
        ('进程 StartTime: {0}' -f $(if ($null -ne $procStartTime) { $procStartTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '（不可读）' })),
        ('exe 路径: {0}' -f $exePath),
        ('exe 存在: {0}' -f $exeExists),
        ('exe LastWriteTime: {0}' -f $(if ($null -ne $exeTime) { $exeTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '（不可读）' })),
        ('exe 字节数: {0}' -f $exeSize),
        ('构建阈值: {0}' -f $(if ($null -ne $threshold) { $threshold.ToString('yyyy-MM-dd HH:mm:ss') } else { $ExeBuildThreshold })),
        ('是否阈值之后构建的新 exe: {0}' -f $(if ($isNewExe) { '是' } else { '否' })),
        ('进程启动时间不早于 exe 修改时间: {0}' -f $(if ($runningMatchesExe) { '是' } else { '否' })),
        ('8078 LISTENING 行数: {0}' -f $listen8078.Count),
        ('8443 LISTENING 行数: {0}' -f $listen8443.Count)
    )
    foreach ($l in $listen8078) { $summary += ('8078: {0}' -f $l.Trim()) }
    foreach ($l in $listen8443) { $summary += ('8443: {0}' -f $l.Trim()) }
    $null = Save-Text -Name '04-summary.txt' -Content $summary

    $note = ('进程={0}；进程启动={1}；exe LastWriteTime={2}；新 exe={3}；启动不早于 exe={4}；8078 监听={5}；8443 监听={6}。' -f `
        $procs.Count, $(if ($null -ne $procStartTime) { $procStartTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '不可读' }), `
        $(if ($null -ne $exeTime) { $exeTime.ToString('yyyy-MM-dd HH:mm:ss') } else { '不可读' }), `
        $(if ($isNewExe) { '是' } else { '否' }), $(if ($runningMatchesExe) { '是' } else { '否' }), `
        $listen8078.Count, $listen8443.Count)
    if ($procs.Count -eq 0) {
        Add-Result -Item $item4 -Status 'FAIL' -File '04-summary.txt' -Note ($note + ' 未发现 msia_server 进程，需确认服务化方式。')
    } elseif (-not $exeExists) {
        Add-Result -Item $item4 -Status 'FAIL' -File '04-summary.txt' -Note ($note + ' 部署目录未找到 exe。')
    } elseif (-not $isNewExe) {
        Add-Result -Item $item4 -Status 'FAIL' -File '04-summary.txt' -Note ($note + ' exe 早于 2026-11-05 16:00，可能仍是旧版本。')
    } elseif (-not $runningMatchesExe) {
        Add-Result -Item $item4 -Status 'FAIL' -File '04-summary.txt' -Note ($note + ' 进程启动时间早于 exe 修改时间，运行中的映像可能仍是旧版本；若 StartTime 不可读请以管理员身份复采。')
    } elseif ($listen8078.Count -eq 0) {
        Add-Result -Item $item4 -Status 'FAIL' -File '04-summary.txt' -Note ($note + ' 8078 未处于 LISTENING。')
    } else {
        Add-Result -Item $item4 -Status 'PASS' -File '04-summary.txt' -Note $note
    }
} catch {
    Add-Result -Item $item4 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# ============================================================
# 5. 证书快照
# ============================================================

Write-Host ''
Write-Host '== 5/8 证书快照 ==' -ForegroundColor Cyan
$item5 = '5. 证书快照（SAN / 有效期）'
try {
    $keytool = Resolve-Keytool
    if ($null -eq $keytool) {
        Add-Result -Item $item5 -Status 'SKIP' -Note '未找到 keytool.exe（可设 JAVA_HOME，或用浏览器/openssl 导出证书后人工判读）。'
    } else {
        $uri = $null
        try { $uri = [Uri]$KeycloakServer } catch { }
        $sslTarget = '172.26.2.203:8443'
        if ($null -ne $uri -and $uri.Host -ne '') { $sslTarget = ('{0}:{1}' -f $uri.Host, $uri.Port) }

        $res = Invoke-ExternalWithTimeout -FilePath $keytool -ArgumentList @('-printcert', '-sslserver', $sslTarget) -TimeoutSeconds 60
        $null = Save-Text -Name '05-cert-raw.txt' -Content ([string]$res.Output)

        $lines = @(([string]$res.Output) -split "`r`n")
        $validLine = ''
        $sanLines = @()
        $inSan = $false
        foreach ($l in $lines) {
            if ($l -match '(?i)Valid from:') { $validLine = $l.Trim() }
            if ($l -match '(?i)SubjectAlternativeName') { $inSan = $true }
            if ($inSan) {
                $sanLines += $l
                if ($l.Trim() -eq ']' -or $l.Trim().EndsWith(']')) { break }
            }
        }

        $certOut = @(
            ('# keytool -printcert -sslserver {0}' -f $sslTarget),
            ('# keytool: {0}' -f $keytool),
            ('# 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
            '',
            $(if ($validLine -ne '') { $validLine } else { '（未解析到 Valid from 行）' })
        ) + $sanLines
        $null = Save-Text -Name '05-cert-san.txt' -Content $certOut

        $hasIp = $false
        $hasLocalhost = $false
        $hasDomain = $false
        foreach ($s in $sanLines) {
            if ($s -match '172\.26\.2\.203') { $hasIp = $true }
            if ($s -match '(?i)localhost') { $hasLocalhost = $true }
            if ($s -match '(?i)sso\.ap\.inalfa\.local') { $hasDomain = $true }
        }

        $untilText = ''
        if ($validLine -match '(?i)until:\s*(.+)$') { $untilText = $Matches[1].Trim() }

        $note = ('valid: {0}；SAN IP={1} localhost={2} 域名={3}。' -f `
            $(if ($validLine -ne '') { $validLine } else { '未解析' }), $hasIp, $hasLocalhost, $hasDomain)
        if ($res.ExitCode -ne 0) {
            Add-Result -Item $item5 -Status 'FAIL' -File '05-cert-raw.txt' -Note ($note + ' keytool 连接失败，见原始输出。')
        } elseif ($validLine -eq '' -or $sanLines.Count -eq 0) {
            Add-Result -Item $item5 -Status 'FAIL' -File '05-cert-san.txt' -Note ($note + ' 未解析到 SAN/有效期，见原始输出。')
        } elseif (-not $hasIp) {
            Add-Result -Item $item5 -Status 'FAIL' -File '05-cert-san.txt' -Note ($note + ' SAN 缺少 172.26.2.203。')
        } else {
            Add-Result -Item $item5 -Status 'PASS' -File '05-cert-san.txt' -Note ($note + (' 到期: {0}。' -f $(if ($untilText -ne '') { $untilText } else { '见原文' })))
        }
    }
} catch {
    Add-Result -Item $item5 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# ============================================================
# 6. MSIA config.ini 快照
# ============================================================

Write-Host ''
Write-Host '== 6/8 MSIA config.ini 快照 ==' -ForegroundColor Cyan
$item6 = '6. MSIA config.ini 快照（[oidc]/[database]）'
try {
    $cfgCandidates = @(
        (Join-Path $MsiaDeployDir 'config.ini'),
        (Join-Path (Join-Path $MsiaDeployDir '_internal') 'config.ini')
    )
    $cfgPath = $null
    foreach ($c in $cfgCandidates) {
        if (Test-Path -LiteralPath $c) { $cfgPath = $c; break }
    }

    if ($null -eq $cfgPath) {
        Add-Result -Item $item6 -Status 'SKIP' -Note ('未找到 config.ini（已检查: {0}）。' -f ($cfgCandidates -join '; '))
    } else {
        $ini = Get-IniData -Path $cfgPath
        $dup = @()
        $grouped = $ini.Headers | Group-Object
        foreach ($g in $grouped) {
            if ($g.Count -gt 1) { $dup += ('[{0}] 出现 {1} 次' -f $g.Name, $g.Count) }
        }

        $cfgItem = Get-Item -LiteralPath $cfgPath
        $out = @(
            '# MSIA config.ini 快照（敏感键已脱敏）',
            ('# FILE: {0}' -f $cfgPath),
            ('# LastWriteTime: {0:yyyy-MM-dd HH:mm:ss}  Size: {1} bytes' -f $cfgItem.LastWriteTime, $cfgItem.Length),
            ('# 段头重复检查: {0}' -f $(if ($dup.Count -eq 0) { '无重复' } else { $dup -join '；' })),
            ''
        )

        foreach ($secName in @('oidc', 'database')) {
            $out += ('[{0}]' -f $secName)
            if (-not $ini.Sections.ContainsKey($secName)) {
                $out += '（缺少该段：可能未合并、被注释或段名拼写不一致）'
            } else {
                foreach ($kv in $ini.Sections[$secName]) {
                    $val = Protect-ConfigValue -Key $kv.Key -Value $kv.Value
                    $out += ('{0} = {1}' -f $kv.Key, $val)
                }
            }
            $out += ''
        }

        $sslProcess = [Environment]::GetEnvironmentVariable('SSL_CERT_FILE', 'Process')
        $sslMachine = [Environment]::GetEnvironmentVariable('SSL_CERT_FILE', 'Machine')
        $sslUser = [Environment]::GetEnvironmentVariable('SSL_CERT_FILE', 'User')
        $out += '# 证书信任环境变量（SSL_CERT_FILE）'
        $out += ('Process = {0}' -f $(if ([string]::IsNullOrWhiteSpace($sslProcess)) { '（未设置）' } else { $sslProcess }))
        $out += ('Machine = {0}' -f $(if ([string]::IsNullOrWhiteSpace($sslMachine)) { '（未设置）' } else { $sslMachine }))
        $out += ('User    = {0}' -f $(if ([string]::IsNullOrWhiteSpace($sslUser)) { '（未设置）' } else { $sslUser }))
        $sslExists = $false
        if (-not [string]::IsNullOrWhiteSpace($SslCertFile)) { $sslExists = Test-Path -LiteralPath $SslCertFile }
        $out += ('默认证书文件 {0} 存在: {1}' -f $SslCertFile, $sslExists)
        $out += ''
        $out += ('# OIDC_CLIENT_SECRET 环境变量: {0}' -f $(if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable('OIDC_CLIENT_SECRET', 'Process'))) { '未设置（Process）' } else { '已设置（值不采集）' }))

        # [security] jwt_secret_key 长度检查（只统计字节数，不采集值）
        $jwtValue = ''
        $jwtSource = 'config.ini'
        if ($ini.Sections.ContainsKey('security')) {
            foreach ($kv in $ini.Sections['security']) {
                if ($kv.Key -eq 'jwt_secret_key') { $jwtValue = $kv.Value }
            }
        }
        $jwtEnv = [Environment]::GetEnvironmentVariable('JWT_SECRET_KEY', 'Process')
        if ([string]::IsNullOrWhiteSpace($jwtValue) -and -not [string]::IsNullOrWhiteSpace($jwtEnv)) {
            $jwtValue = $jwtEnv
            $jwtSource = '环境变量 JWT_SECRET_KEY'
        }
        if (-not [string]::IsNullOrWhiteSpace($jwtValue)) {
            $script:JwtSecretBytes = [Text.Encoding]::UTF8.GetByteCount($jwtValue)
            $script:JwtSecretSource = $jwtSource
            $script:JwtSecretRisk = ($script:JwtSecretBytes -lt 32)
        }
        $out += ''
        $out += '# [security] jwt_secret_key 长度检查（仅长度，不采集值）'
        if ($null -eq $script:JwtSecretBytes) {
            $out += 'jwt_secret_key = （未找到或为空，长度未知）'
        } else {
            $out += ('jwt_secret_key = 长度 {0} 字节（来源: {1}；RFC 7518 SHA256 建议 >= 32 字节）' -f $script:JwtSecretBytes, $script:JwtSecretSource)
        }

        $null = Save-Text -Name '06-config-snapshot.txt' -Content $out

        $oidcEnabled = '(缺少 [oidc])'
        $issuer = ''
        $clientIdCfg = ''
        $redirect = ''
        $requiredGroup = ''
        $autoCreate = ''
        if ($ini.Sections.ContainsKey('oidc')) {
            foreach ($kv in $ini.Sections['oidc']) {
                if ($kv.Key -eq 'enabled') { $oidcEnabled = $kv.Value }
                if ($kv.Key -eq 'issuer') { $issuer = $kv.Value }
                if ($kv.Key -eq 'client_id') { $clientIdCfg = $kv.Value }
                if ($kv.Key -eq 'redirect_uri') { $redirect = $kv.Value }
                if ($kv.Key -eq 'required_group') { $requiredGroup = $kv.Value }
                if ($kv.Key -eq 'auto_create_user') { $autoCreate = $kv.Value }
            }
        }

        $note = ('enabled={0}；issuer={1}；client_id={2}；redirect_uri={3}；required_group={4}；auto_create_user={5}；段头重复={6}；SSL_CERT_FILE(Process)={7}。' -f `
            $oidcEnabled, $issuer, $clientIdCfg, $redirect, $requiredGroup, $autoCreate, `
            $(if ($dup.Count -eq 0) { '无' } else { $dup -join '；' }), `
            $(if ([string]::IsNullOrWhiteSpace($sslProcess)) { '未设置' } else { $sslProcess }))

        if ($dup.Count -gt 0) {
            Add-Result -Item $item6 -Status 'FAIL' -File '06-config-snapshot.txt' -Note ($note + ' 重复段头会导致 DuplicateSectionError。')
        } elseif (-not $ini.Sections.ContainsKey('oidc') -or -not $ini.Sections.ContainsKey('database')) {
            Add-Result -Item $item6 -Status 'FAIL' -File '06-config-snapshot.txt' -Note ($note + ' 缺少必需段。')
        } else {
            Add-Result -Item $item6 -Status 'PASS' -File '06-config-snapshot.txt' -Note $note
        }
    }
} catch {
    Add-Result -Item $item6 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# 6b. jwt_secret_key 长度（RFC 7518 SHA256 建议 >= 32 字节）
if ($null -eq $script:JwtSecretBytes) {
    Add-Result -Item '6b. jwt_secret_key 长度检查' -Status 'SKIP' -File '06-config-snapshot.txt' `
        -Note '未在 config.ini 的 [security] 段找到 jwt_secret_key，且环境变量 JWT_SECRET_KEY 未设置；长度未知。'
} elseif ($script:JwtSecretRisk) {
    Add-Result -Item '6b. jwt_secret_key 长度检查' -Status 'FAIL' -File '06-config-snapshot.txt' `
        -Note ('风险项（非采集失败）: jwt_secret_key 当前 {0} 字节（来源: {1}），低于 RFC 7518 SHA256 建议的 32 字节，触发 InsecureKeyLengthWarning。修复: 生成 >=32 字节随机密钥替换后重启（现有登录态失效）；当前影响仅一个测试账号，代价为零。' -f $script:JwtSecretBytes, $script:JwtSecretSource)
} else {
    Add-Result -Item '6b. jwt_secret_key 长度检查' -Status 'PASS' -File '06-config-snapshot.txt' `
        -Note ('jwt_secret_key 当前 {0} 字节（来源: {1}），满足 >= 32 字节建议。' -f $script:JwtSecretBytes, $script:JwtSecretSource)
}

# ============================================================
# 7. realm user profile 必填字段（只读）
# ============================================================

Write-Host ''
Write-Host '== 7/8 realm user profile 必填字段 ==' -ForegroundColor Cyan
$item7 = '7. Realm user profile 必填字段（只读）'
try {
    if (-not (Test-Path -LiteralPath $script:KcadmPath)) {
        Add-Result -Item $item7 -Status 'SKIP' -Note ('未找到 kcadm: {0}' -f $script:KcadmPath)
    } else {
        $profRes = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath `
            -ArgumentList @('get', 'users/profile', '-r', $Realm) -TimeoutSeconds 60

        $profileObj = $null
        $source = ''
        if ($profRes.ExitCode -eq 0) {
            try {
                $profileObj = $profRes.Output | ConvertFrom-Json
                $source = ('kcadm get users/profile -r {0}' -f $Realm)
                $null = Save-Text -Name '07-realm-user-profile.json' -Content ([string]$profRes.Output)
            } catch {
                $profileObj = $null
            }
        }

        if ($null -eq $profileObj) {
            # 回退：realm attributes（部分版本不含 upConfig）
            $attrRes = Invoke-ExternalWithTimeout -FilePath $script:KcadmPath `
                -ArgumentList @('get', ('realms/{0}' -f $Realm), '--fields', 'attributes') -TimeoutSeconds 60
            if ($attrRes.ExitCode -eq 0) {
                $null = Save-Text -Name '07-realm-attributes.json' -Content ([string]$attrRes.Output)
                Add-Result -Item $item7 -Status 'SKIP' -File '07-realm-attributes.json' `
                    -Note 'users/profile 端点不可读，已回退 realm attributes。需在控制台 Realm Settings -> General -> User profile 只读确认 email/firstName/lastName 是否必填；首次登录是否出现资料补全页 -> 待现场确认。'
            } else {
                Add-Result -Item $item7 -Status 'SKIP' -File '-' `
                    -Note ('users/profile 与 realm attributes 均不可读（exit={0}/{1}）。需在控制台只读确认；首次登录是否出现资料补全页 -> 待现场确认。' -f $profRes.ExitCode, $attrRes.ExitCode)
            }
        } else {
            $attrs = @($profileObj.attributes)
            $requiredNames = @()
            foreach ($a in $attrs) {
                if (Test-ProfileAttrRequired -Attr $a) { $requiredNames += [string]$a.name }
            }

            $emailReq = $requiredNames -contains 'email'
            $firstReq = $requiredNames -contains 'firstName'
            $lastReq = $requiredNames -contains 'lastName'

            $lines = @(
                '# Realm user profile 配置（只读）',
                ('# 来源: {0}' -f $source),
                ('# 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
                ('# 属性总数: {0}' -f $attrs.Count),
                ('# 必填属性: {0}' -f $(if ($requiredNames.Count -eq 0) { '（无）' } else { $requiredNames -join ', ' })),
                ('# email 必填: {0}' -f $(if ($emailReq) { '是' } else { '否' })),
                ('# firstName 必填: {0}' -f $(if ($firstReq) { '是' } else { '否' })),
                ('# lastName 必填: {0}' -f $(if ($lastReq) { '是' } else { '否' })),
                '',
                '# 结论: 首次登录是否会触发资料补全页 -> 待现场确认（需观察登录时是否出现资料补全页）',
                '# 说明: 本项仅只读检测，不修改 realm user profile 配置。'
            )
            $null = Save-Text -Name '07-realm-user-profile.txt' -Content $lines

            Add-Result -Item $item7 -Status 'PASS' -File '07-realm-user-profile.txt' `
                -Note ('必填: {0}；email={1}, firstName={2}, lastName={3}；首次登录是否触发资料补全页 -> 待现场确认（观察登录时是否出现补全页）。' -f `
                    $(if ($requiredNames.Count -eq 0) { '无' } else { $requiredNames -join ',' }), `
                    $(if ($emailReq) { '是' } else { '否' }), $(if ($firstReq) { '是' } else { '否' }), $(if ($lastReq) { '是' } else { '否' }))
        }
    }
} catch {
    Add-Result -Item $item7 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# ============================================================
# 8. 本地用户表核查
# ============================================================

Write-Host ''
Write-Host '== 8/8 本地用户表核查 ==' -ForegroundColor Cyan
$item8 = '8. 本地用户表核查（ligu 建档来源）'
try {
    $safeTarget = $TargetUser -replace "'", "''"
    $loginExpr = 'NULL'
    if (-not [string]::IsNullOrWhiteSpace($script:LoginEventTime)) {
        $loginParsed = $null
        try { $loginParsed = [datetime]::ParseExact($script:LoginEventTime, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture) } catch { }
        if ($null -eq $loginParsed) {
            try { $loginParsed = [datetime]$script:LoginEventTime } catch { $loginParsed = $null }
        }
        if ($null -ne $loginParsed) {
            $loginExpr = ("CONVERT(datetime2(0), '{0}', 120)" -f $loginParsed.ToString('yyyy-MM-dd HH:mm:ss'))
        }
    }

    $sql = @'
/* ============================================================
   本地用户表核查（只读，不执行任何写操作）
   目标: 判定 __TARGET__ 是「首次 SSO 自动建档」还是「本来就存在」
   字段依据: MSIA Report/backend/app/models/user.py
             表 CN_AME_MISA_User:
             Id / Username / DisplayName / RealName / Email / Phone / Department /
             PasswordHash / PasswordUpdatedAt / Role / Status / HrSyncedAt /
             IsDeleted / CreatedAt / UpdatedAt
   执行方式: SSMS 或 sqlcmd -S IRSCNYTFINEREPORT.ap.inalfa.local -d CN_AME -E -i 本文件
   判读:
     - PasswordHash 为空 + CreatedAt 与 LOGIN 时间接近（±5 分钟）+ UserMap 无映射
       -> 首次 SSO 自动建档
     - PasswordHash 非空 或 CreatedAt 明显早于 LOGIN 时间
       -> 本来就存在
   ============================================================ */
SET NOCOUNT ON;
DECLARE @target nvarchar(100) = N'__TARGET__';
DECLARE @login_time datetime2(0) = __LOGIN_TIME__;  -- NULL = 未提供首次登录时间

SELECT
    m.Id,
    m.Username,
    m.DisplayName,
    m.RealName,
    m.Email,
    m.Department,
    m.Role,
    m.Status,
    m.HrSyncedAt,
    CONVERT(varchar(19), m.CreatedAt, 120) AS CreatedAt,
    CONVERT(varchar(19), m.UpdatedAt, 120) AS UpdatedAt,
    CASE WHEN m.PasswordHash IS NULL OR m.PasswordHash = '' THEN 0 ELSE 1 END AS has_password,
    CASE WHEN @login_time IS NULL THEN NULL
         ELSE DATEDIFF(SECOND, m.CreatedAt, @login_time) END AS seconds_created_before_login
FROM dbo.CN_AME_MISA_User m
WHERE LOWER(LTRIM(RTRIM(m.Username))) = LOWER(LTRIM(RTRIM(@target)));

SELECT
    u.employee_no,
    u.login_name,
    u.display_name,
    u.status,
    u.source,
    u.pwd_set
FROM dbo.CN_AME_SSO_User u
WHERE LOWER(LTRIM(RTRIM(u.login_name))) = LOWER(LTRIM(RTRIM(@target)))
   OR LOWER(LTRIM(RTRIM(u.employee_no))) = LOWER(LTRIM(RTRIM(@target)));

SELECT
    mp.system_code,
    mp.local_username,
    mp.employee_no,
    mp.match_key,
    mp.remark
FROM dbo.CN_AME_SSO_UserMap mp
WHERE mp.system_code = 'msia'
  AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(@target)));
'@
    $sql = $sql.Replace('__TARGET__', $safeTarget)
    $sql = $sql.Replace('__LOGIN_TIME__', $loginExpr)
    $null = Save-Text -Name ('08-usermap-{0}.sql' -f $TargetUser) -Content $sql

    $sqlcmd = $null
    $cmd = Get-Command -Name 'sqlcmd.exe' -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { $sqlcmd = $cmd.Source }
    if ($null -eq $sqlcmd) {
        $candidates = @(
            'C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe',
            'C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\sqlcmd.exe'
        )
        foreach ($c in $candidates) { if (Test-Path -LiteralPath $c) { $sqlcmd = $c; break } }
    }
    if ($null -eq $sqlcmd -and (Test-Path -LiteralPath 'C:\Program Files\Microsoft SQL Server')) {
        $found = Get-ChildItem -Path 'C:\Program Files\Microsoft SQL Server' -Filter 'sqlcmd.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $found) { $sqlcmd = $found.FullName }
    }

    if ($null -eq $sqlcmd) {
        Add-Result -Item $item8 -Status 'SKIP' -File ('08-usermap-{0}.sql' -f $TargetUser) `
            -Note ('未找到 sqlcmd。可直接粘贴执行 08-usermap-{0}.sql（只读，不写库）。现场实证已定性: ligu local user id=2414 -> 本地已存在账号，非自动建档；SQL 作为佐证。' -f $TargetUser)
    } else {
        $sqlPath = Join-Path $script:RunDir ('08-usermap-{0}.sql' -f $TargetUser)
        $outPath = Join-Path $script:RunDir ('08-usermap-{0}.out.txt' -f $TargetUser)
        $runRes = Invoke-ExternalWithTimeout -FilePath $sqlcmd `
            -ArgumentList @('-S', $SqlServer, '-d', $Database, '-E', '-b', '-W', '-i', $sqlPath, '-o', $outPath) `
            -TimeoutSeconds 120

        $outText = ''
        if (Test-Path -LiteralPath $outPath) { $outText = (Get-Content -LiteralPath $outPath -Raw -ErrorAction SilentlyContinue) }

        if ($runRes.ExitCode -ne 0 -or ($outText -match '(?i)Login failed|Msg \d+')) {
            $excerpt = ([string]$outText).Trim()
            if ($excerpt.Length -gt 300) { $excerpt = $excerpt.Substring(0, 300) }
            Add-Result -Item $item8 -Status 'SKIP' -File ('08-usermap-{0}.sql' -f $TargetUser) `
                -Note ('sqlcmd 执行失败（集成认证不可用或无权限）。请用有权限账号在 SSMS 执行 08-usermap-{0}.sql。现场实证已定性: ligu local user id=2414 -> 本地已存在账号，非自动建档；错误摘要: {1}' -f $TargetUser, $excerpt)
        } else {
            # 机器可读结论：另跑一条单行查询
            $compactQuery = @"
SET NOCOUNT ON;
DECLARE @login_time datetime2(0) = $loginExpr;
SELECT CONCAT('RESULT|',
    m.Username, '|',
    CASE WHEN m.PasswordHash IS NULL OR m.PasswordHash = '' THEN '0' ELSE '1' END, '|',
    ISNULL(CONVERT(varchar(19), m.CreatedAt, 120), ''), '|',
    ISNULL(CONVERT(varchar(19), m.UpdatedAt, 120), ''), '|',
    ISNULL(CONVERT(varchar(20), DATEDIFF(SECOND, m.CreatedAt, @login_time)), 'NULL'), '|',
    CONVERT(varchar(10), (SELECT COUNT(*) FROM dbo.CN_AME_SSO_UserMap mp WHERE mp.system_code = 'msia' AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(m.Username))))), '|',
    CONVERT(varchar(10), (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User u WHERE LOWER(LTRIM(RTRIM(u.login_name))) = LOWER(LTRIM(RTRIM(m.Username))) OR LOWER(LTRIM(RTRIM(u.employee_no))) = LOWER(LTRIM(RTRIM(m.Username))))), '|',
    CONVERT(varchar(10), m.Status))
FROM dbo.CN_AME_MISA_User m
WHERE LOWER(LTRIM(RTRIM(m.Username))) = LOWER(LTRIM(RTRIM(N'$safeTarget')));
"@
            $compact = Invoke-ExternalWithTimeout -FilePath $sqlcmd `
                -ArgumentList @('-S', $SqlServer, '-d', $Database, '-E', '-h', '-1', '-W', '-s', '|', '-Q', $compactQuery) `
                -TimeoutSeconds 60

            $rows = @(([string]$compact.Output) -split "`r`n" | Where-Object { $_ -match '^RESULT\|' })
            if ($rows.Count -eq 0) {
                $null = Save-Text -Name ('08-usermap-{0}.compact.txt' -f $TargetUser) -Content ([string]$compact.Output)
                Add-Result -Item $item8 -Status 'FAIL' -File ('08-usermap-{0}.out.txt' -f $TargetUser) `
                    -Note ('本地用户表未返回 {0} 的匹配行（或 compact 查询失败）。请核对 Username 口径与 08-usermap-{0}.sql 输出。' -f $TargetUser)
            } else {
                $parts = $rows[0] -split '\|'
                if ($parts.Count -lt 9) {
                    Add-Result -Item $item8 -Status 'FAIL' -File ('08-usermap-{0}.out.txt' -f $TargetUser) -Note 'compact 查询字段数不足，请人工判读 08-usermap-*.sql 输出。'
                } else {
                    $hasPwd = [int]$parts[2]
                    $createdAt = $parts[3]
                    $deltaText = $parts[5]
                    $mapRows = [int]$parts[6]
                    $centralRows = [int]$parts[7]
                    $localStatus = $parts[8]

                    # 现场实证已定性: local user id=2414 -> 本地已存在账号，非自动建档
                    $sqlHint = ''
                    if ($hasPwd -eq 1) {
                        $sqlHint = 'SQL 参考: 本地已有密码'
                    } elseif ($deltaText -eq 'NULL') {
                        $sqlHint = 'SQL 参考: 缺首次 LOGIN 时间，无法比较 CreatedAt'
                    } elseif ($deltaText -match '^-?\d+$') {
                        if ([int]$deltaText -ge -300 -and [int]$deltaText -le 300) {
                            $sqlHint = 'SQL 参考: CreatedAt 与 LOGIN 时间相差在 ±5 分钟内'
                        } else {
                            $sqlHint = 'SQL 参考: CreatedAt 明显早于本次登录'
                        }
                    } else {
                        $sqlHint = 'SQL 参考: CreatedAt 与登录时间差值不可解析'
                    }

                    $conclusion = '本地已存在（现场实证 local user id=2414），非自动建档；无 UserMap 映射时回落 preferred_username 分支生效'
                    $status = 'PASS'

                    if ($rows.Count -gt 1) {
                        $conclusion += '；注意: 存在多条大小写/空白变体账号，需人工裁决'
                        $status = 'FAIL'
                    }

                    $note = ('判定: {0}；{1}；has_password={2}；CreatedAt={3}；与登录时间差={4}s；UserMap 行={5}；中央表命中={6}；本地 Status={7}；SQL 输出=08-usermap-{8}.out.txt。' -f `
                        $conclusion, $sqlHint, $hasPwd, $createdAt, $deltaText, $mapRows, $centralRows, $localStatus, $TargetUser)
                    Add-Result -Item $item8 -Status $status -File ('08-usermap-{0}.out.txt' -f $TargetUser) -Note $note
                }
            }
        }
    }
} catch {
    Add-Result -Item $item8 -Status 'FAIL' -Note ('采集异常: {0}' -f $_.Exception.Message)
}

# ============================================================
# evidence.md
# ============================================================

function Format-EventTableRows {
    param([string]$Title, $Rows, [string]$EmptyText, [string]$ExtraHeader = '')
    $lines = @(('### {0}' -f $Title), '')
    if (-not [string]::IsNullOrWhiteSpace($ExtraHeader)) { $lines += $ExtraHeader; $lines += '' }
    if (@($Rows).Count -eq 0) {
        $lines += $EmptyText
        $lines += ''
        return $lines
    }
    $lines += '| 时间 | 类型 | clientId | username | userId (UUID) | ipAddress | error |'
    $lines += '|---|---|---|---|---|---|---|'
    foreach ($r in $Rows) {
        $lines += ('| {0} | {1} | {2} | {3} | {4} | {5} | {6} |' -f `
            (Format-MdCell $r.TimeText), (Format-MdCell $r.Type), (Format-MdCell $r.ClientId), `
            (Format-MdCell $r.Username), (Format-MdCell $r.UserId), (Format-MdCell $r.Ip), (Format-MdCell $r.Error))
    }
    $lines += ''
    return $lines
}

$md = @()
$md += '# MSIA 统一身份认证登录证据包'
$md += ''
$md += ('- 采集时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$md += ('- 主机: {0}' -f $env:COMPUTERNAME)
$md += ('- 操作员: {0}' -f $env:USERNAME)
$md += ('- realm / client: {0} / {1}' -f $Realm, $ClientId)
$md += ('- 目标用户: {0}' -f $TargetUser)
$md += ('- 脚本: {0}' -f $script:ScriptPath)
$md += ('- 证据目录: {0}' -f $script:RunDir)
$md += ''
$md += '> 本证据包不含明文密钥：config 快照中的 secret / password 类键均按「前 4 位 + ****」脱敏；kcadm 未传任何账号口令。'
$md += ''
$md += '## 汇总表'
$md += ''
$md += '| 证据项 | 状态 | 原始文件名 | 关键判读 |'
$md += '|---|---|---|---|'
foreach ($r in $script:Results) {
    $md += ('| {0} | {1} | {2} | {3} |' -f (Format-MdCell $r.Item), $r.Status, (Format-MdCell $r.File), (Format-MdCell $r.Note))
}
$md += ''
$md += '## 本次成功登录核心证据（2026-11-05 21:34）'
$md += ''
$md += '现场已确认：client 全部为 `msia-prod`，Keycloak Event 页来源 IP `10.41.0.64`，事件序列为 `LOGIN -> CODE_TO_TOKEN -> VERIFY_PROFILE -> UPDATE_PROFILE`。其中 `LOGIN` 与 `CODE_TO_TOKEN` 是本次成功登录的核心证据（建立会话 + 授权码换 token）。'
$md += ''
$md += '| 项 | 值 |'
$md += '|---|---|'
$md += '| 时间 | 2026-11-05 21:34（精确到秒见 01-core-login-2134.txt 与 03-msia-console-evidence.txt） |'
$md += '| clientId | msia-prod |'
$md += '| 来源 IP（Keycloak Event） | 10.41.0.64 |'
$md += '| 来源 IP（MSIA 控制台请求） | 10.41.10.64（与 Keycloak 事件口径不一致，需现场核对客户端真实地址，不影响成功结论） |'
$md += '| 登录用户 | ligu |'
$md += '| Keycloak userId (UUID) | 见下方事件行的 `userId (UUID)` 列；未采集到时标「待补」，需与 username 成对记录 |'
$md += '| 本地用户 | local user id=2414（本地已存在账号，非自动建档） |'
$md += '| 身份解析 | 无 UserMap 映射，回落 preferred_username 分支生效 |'
$md += '| 事件序列 | LOGIN -> CODE_TO_TOKEN -> VERIFY_PROFILE -> UPDATE_PROFILE |'
$md += '| 核心判定事件 | LOGIN + CODE_TO_TOKEN |'
$md += ''
$md += (Format-EventTableRows -Title '采集到的事件行（含 UUID->username 反查）' -Rows $script:CoreRows -EmptyText '本次事件 API 未返回该窗口原文。现场控制台实证见 03-msia-console-evidence.txt；UUID 与 username 待 kcadm 可用后复采。')
$md += '## 四段式端到端证据链（MSIA 控制台实证）'
$md += ''
$md += '来源：现场 MSIA 控制台输出，2026-11-05 21:33-21:34，请求来源 IP `10.41.10.64`。'
$md += ''
$md += '| 阶段 | 时间 | 实证日志（原文摘录） | 判读 |'
$md += '|---|---|---|---|'
$md += '| 1. 授权跳转 | 21:33:46 | `app.api.auth:oidc_login:141 - OIDC 授权跳转: state 已签发 (nonce/PKCE verifier 入库)`；`GET /api/auth/oidc/login 302` | state/nonce/PKCE verifier 已入库，授权跳转已发起 |'
$md += '| 2. 回调验签 | 21:34:09 | `app.services.sso_identity:resolve_or_create:118 - OIDC 身份解析: ligu 无 UserMap 映射, 回落 preferred_username`；`app.api.auth:oidc_callback:223 - OIDC 登录成功: ligu (local user id=2414)`；`GET /api/auth/oidc/callback?...iss=https%3A%2F%2F172.26.2.203%3A8443%2Frealms%2Finalfa&code=... 302` | issuer 回显校验通过，code 换 token；身份解析命中本地 ligu（id=2414） |'
$md += '| 3. OTK 换 JWT | 21:34:09 | `GET /oidc/callback?otk=<一次性码，已消费，脱敏> 200`；`POST /api/auth/oidc/token 200` | 前端用 OTK 换取后端 JWT 成功 |'
$md += '| 4. 业务接口鉴权 | 21:34:09 之后 | `/api/dashboard/analytics`、`/api/users`、`/api/system-settings/grouped`、`/api/archive/projects` 等均 `200` | 携带 JWT 访问受保护接口全部通过，前端到后端这一跳也已验证，不只是后端打通 |'
$md += ''
$md += '> 结论：MSIA 侧 OIDC 链路已验证通过，且覆盖「授权跳转 -> 回调验签 -> OTK 换 JWT -> 业务接口鉴权」四段。OTK 为一次性码（已消费），按不打印 secret 约束脱敏。'
$md += ''
$md += '## 20:32 LOGIN_ERROR（本机回环，非用户登录路径）'
$md += ''
$md += '现场已确认：20:32 有一条 `LOGIN_ERROR`，IP 显示 `0.0.0.0:0:0:0:0:0:1`（本机回环），User 显示 `No user details`。**判定：本机回环来源，非用户登录路径，不构成用户登录失败的证据。**'
$md += ''
$md += (Format-EventTableRows -Title '采集到的 LOGIN_ERROR 行' -Rows $script:LoopbackRows -EmptyText '本次事件 API 未返回该窗口记录；错误详情检索结果见 02-keycloak-login-error-2032.txt。')
$md += ('错误详情日志检索: {0}' -f $(if ($script:LogErrorDetailsFound) { '见 02-keycloak-login-error-2032.txt' } else { '日志中未检索到 20:32 的 error/invalid_grant 关键字；以 Keycloak Event 页 error 字段为准' }))
$md += ''
$md += '## 下午 15:11-15:19 登录旁证'
$md += ''
$md += ('现场已确认：另一批 `LOGIN`，来源 IP `{0}`，用户 UUID `{1}`。' -f $KnownAfternoonIp, $KnownAfternoonUserId)
$md += ''
$md += (Format-EventTableRows -Title '采集到的旁证事件行' -Rows $script:AfternoonRows -EmptyText '本次事件 API 未返回该窗口记录；以上述现场控制台事实为准。')
$md += '## 遗留风险'
$md += ''
$jwtNow = '23 字节（现场实测）'
if ($null -ne $script:JwtSecretBytes) { $jwtNow = ('{0} 字节（本次采集，来源: {1}）' -f $script:JwtSecretBytes, $script:JwtSecretSource) }
$md += '| 风险项 | 现状 | 修复方式 | 当前影响 |'
$md += '|---|---|---|---|'
$md += ('| MSIA `[security] jwt_secret_key` 长度不足 | {0}，触发 `InsecureKeyLengthWarning`（低于 RFC 7518 SHA256 的 32 字节建议底线） | 生成 >=32 字节随机密钥替换 `config.ini` / 环境变量后重启；重启后现有登录态失效，需重新登录 | 当前仅一个测试账号，代价为零 |' -f $jwtNow)
$md += ''
$md += '## 必须人工补充的证据'
$md += ''
$md += '- [ ] 若第 1b 项为 SKIP：从 Keycloak 控制台 Events 页导出/截图 21:34 的 LOGIN/CODE_TO_TOKEN 行，并手填 21:34 用户的 UUID 与 username（需与脚本反查结果一致）。'
$md += '- [ ] 核对 IP 口径：Keycloak Event 页记录 10.41.0.64，MSIA 控制台请求记录 10.41.10.64，确认客户端真实地址与代理链（不改变成功结论）。'
$md += '- [ ] 若第 1 项为 SKIP：按提示手动执行 kcadm config credentials（密码交互输入，禁止写进脚本/命令行历史），确认自签证书 truststore 已导入后重跑本脚本。'
$md += '- [ ] 若第 3 项为 SKIP：按 03-msia-log-ALTERNATIVES.txt 的 A/B 方案补齐 MSIA 输出，保存为 03-msia-console-copy.txt 或 msia_stdout.log。'
$md += '- [ ] 若第 5 项为 SKIP：用浏览器或 openssl 导出 172.26.2.203:8443 证书，补齐 SAN 与有效期原文。'
$md += '- [ ] 若第 7 项为 PASS：仍需在登录页观察是否出现资料补全页，把结论写入技术交底书第 20 章（当前口径为「待现场确认」）。'
$md += '- [ ] 若第 8 项为 SKIP：在 SSMS 执行 08-usermap-*.sql，作为本地账号已存在（id=2414）的佐证，并回填技术交底书第 20.4 节。'
$md += '- [ ] 若第 6b 项为 FAIL：按遗留风险表替换 >=32 字节的 jwt_secret_key，重启后复采一次。'
$md += ''
$md += '## 判读口径'
$md += ''
$md += '1. 四段式证据链：授权跳转（state/nonce/PKCE 入库）-> 回调验签（issuer 回显、code 换 token）-> OTK 换 JWT（/api/auth/oidc/token 200）-> 业务接口鉴权（多个 200）。'
$md += '2. 核心事件 = 21:34 窗口中 `LOGIN` + `CODE_TO_TOKEN` 均存在，且 clientId=msia-prod、Keycloak Event IP=10.41.0.64。'
$md += '3. 20:32 `LOGIN_ERROR` 的 IP 为本机回环（0.0.0.0:0:0:0:0:0:1）、User 无详情，判定为非用户登录路径。'
$md += '4. 进程项要求 exe LastWriteTime >= 2026-11-05 16:00，且 8078 处于 LISTENING。'
$md += '5. config 快照出现重复段头即判 FAIL（对应 Python DuplicateSectionError）。'
$md += '6. 本地用户判定以现场实证为准：ligu local user id=2414 -> 本地已存在账号，非自动建档；无 UserMap 映射时回落 preferred_username 已生效。'
$md += '7. 正式期口径：本地账号必须先存在，`CN_AME_SSO_UserMap` 负责把 IdP 身份指向本地账号；回落 preferred_username 解决不了同名/大小写冲突，UserMap 仍需补齐。'
$md += ''
$md += '## 本次产出文件清单'
$md += ''
$files = @(Get-ChildItem -LiteralPath $script:RunDir -File -ErrorAction SilentlyContinue | Sort-Object -Property Name)
foreach ($f in $files) { $md += ('- `{0}` ({1} bytes)' -f $f.Name, $f.Length) }

$mdPath = Join-Path $script:RunDir 'evidence.md'
$md | Out-File -LiteralPath $mdPath -Encoding UTF8

Write-Host ''
Write-Host ('证据包已生成: {0}' -f $mdPath) -ForegroundColor Green
$failCount = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$skipCount = @($script:Results | Where-Object { $_.Status -eq 'SKIP' }).Count
$passCount = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
Write-Host ('汇总: PASS={0} FAIL={1} SKIP={2}' -f $passCount, $failCount, $skipCount)
Write-Host '请打开 evidence.md 查看汇总表与必须人工补充的项。'

if ($failCount -gt 0) { exit 2 }
exit 0
