<#
.SYNOPSIS
    用 NSSM 把 Keycloak / MSIA / BOL / Capacity 四个控制台程序注册为 Windows 服务，并提供回滚到控制台模式的能力。

.DESCRIPTION
    配套手册: 统一身份认证实施/docs/windows-service-nssm-runbook.md

    按动作分段执行，默认只做只读预检：
      -Action Precheck        只读检查（路径/端口/服务冲突/nssm/证书/JAVA_HOME），不写任何配置
      -Action Register        注册服务并写入参数与环境变量，**不自动启动**
      -Action Start           启动服务并等待端口就绪
      -Action Stop            停止服务，并检查残留进程
      -Action Status          只读查看三个服务状态/端口/日志时间
      -Action Verify          逐项校验（服务状态/端口/接口/环境变量/日志），输出 PASS/FAIL
      -Action SetEnv          仅更新环境变量（合并语义，保留未涉及的变量），不重装服务
      -Action Dump            导出当前服务配置做基线（含明文口令，注意保管）
      -Action Unregister      二次确认后卸载服务，日志与回滚脚本保留
      -Action ConsoleRollback 生成各应用的控制台启动器（口令运行时输入），用于退回控制台模式

    设计约束：
      * 不修改任何应用源码与配置文件；
      * 口令/密钥不写进脚本、不落任何文件；
      * 敏感值优先走“运行时交互输入 -> 直接写服务注册表 Parameters\AppEnvironmentExtra”，
        避免出现在 nssm/sc 命令行（命令行对同机其它管理员可见）；
      * 兼容 Windows PowerShell 5.1。

.PARAMETER Action
    见上。默认 Precheck。

.PARAMETER App
    Keycloak / MSIA / BOL / Capacity / All（默认 All）。

.PARAMETER SecretMode
    Prompt      交互输入口令后直接写服务环境（推荐，明文不落盘）
    Placeholder 写入 CHANGE_ME_xxx 占位，之后由人工用 nssm edit 填写
    Keep        不动已有值（只在缺失时写占位）

.PARAMETER RunAsAccount
    服务运行账号：LocalSystem（默认）或 "DOMAIN\user" / ".\localuser"。
    非 LocalSystem 时脚本会交互输入账号口令，并用 nssm 设置 ObjectName。

.PARAMETER ExtraEnv
    额外环境变量，形如 @('OIDC_ENABLED=true','OIDC_ISSUER=https://...')。
    仅作用于本次 -App 选中的应用；用于复刻控制台里实际生效的值。

.EXAMPLE
    .\register-services-nssm.ps1 -Action Precheck

.EXAMPLE
    .\register-services-nssm.ps1 -Action Register -App Keycloak -SecretMode Prompt

.EXAMPLE
    .\register-services-nssm.ps1 -Action Register -App BOL -BolExe 'D:\BOLServer\BOLServer.exe' -ExtraEnv @('OIDC_ENABLED=true','OIDC_ISSUER=https://iame.ap.inalfa.local:8443/realms/inalfa')

.EXAMPLE
    .\register-services-nssm.ps1 -Action Verify -App All

.EXAMPLE
    .\register-services-nssm.ps1 -Action ConsoleRollback -App All

.NOTES
    文件: 统一身份认证实施/scripts/register-services-nssm.ps1
    版本: 2.2.1（启动时打印版本号与自身 SHA256 前 8 位，便于现场核对是否为最新副本）
    权限: Register/Start/Stop/Unregister/SetEnv/Dump 需管理员 PowerShell
    退出码: 0=全部通过 1=存在失败项
#>
[CmdletBinding()]
param(
    [ValidateSet('Precheck', 'Register', 'Start', 'Stop', 'Status', 'Verify', 'SetEnv', 'Dump', 'Unregister', 'ConsoleRollback')]
    [string]$Action = 'Precheck',

    [ValidateSet('Keycloak', 'MSIA', 'BOL', 'Capacity', 'All')]
    [string]$App = 'All',

    [ValidateSet('Prompt', 'Placeholder', 'Keep')]
    [string]$SecretMode = 'Prompt',

    [string]$RunAsAccount = 'LocalSystem',

    [string[]]$ExtraEnv = @(),

    # ---- Keycloak ----
    # 已确认（172.26.2.203 实测）：服务名 Keycloak，状态 Running / Automatic，8443 由 PID 11852 占用
    [string]$KeycloakService = 'Keycloak',
    [string]$KeycloakHome = 'C:\keycloak',
    # 已确认（172.26.2.203 实测）：Keycloak 进程实际使用 C:\Program Files\Java\jdk-21.0.10\bin\java.exe
    [string]$JavaHome = 'C:\Program Files\Java\jdk-21.0.10',
    [int]$KeycloakHttpsPort = 8443,
    [int]$KeycloakMgmtPort = 9000,
    # 登录使用的 realm 名（MSIA/BOL/Capacity 的 discovery 都指向它），Verify 用它拼 OIDC discovery 地址
    [string]$KeycloakRealm = 'inalfa',
    # 探针优先使用的对外域名（握手时作 SNI、请求头作 Host）。hostname-strict=true 时用 127.0.0.1 会被 403，
    # 所以优先按域名探；证书/域名切换完成前域名可能仍指向旧 IP，探针会自动回退到 127.0.0.1 并提示"属预期"。
    # 留空则只用回环地址。
    [string]$KeycloakProbeHost = 'iame.ap.inalfa.local',
    [switch]$KeycloakViaCmd,

    # ---- MSIA ----
    # 服务已存在（172.26.2.203 实测）：Stopped / Automatic / LocalSystem，为 2026-11-06 手工注册。
    # 该服务存在即意味着「重启后会自动启动」的风险，处理方式是确认并启用，不重装、不覆盖手工配置。
    [string]$MsiaService = 'MSIA-Server',
    [string]$MsiaExe = 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe',
    # 已确认（172.26.2.203 实测）：MSIA 自 2026-11-05 起实际监听 8078（配置文件口径，对外也是 8078）；
    # 8000 属于 CapacityAPI，不属本项目，切勿作为 MSIA 的端口
    [int]$MsiaPort = 8078,

    # ---- BOL ----
    # 已确认（172.26.2.203 实测）：BOLServer.exe 位于下述路径，且当前无同名服务，是三个应用里唯一需要从零注册的
    [string]$BolService = 'BOL-Server',
    [string]$BolExe = 'C:\ApplicationFile\ExecuteProgram\BOLServer\BOLServer\BOLServer.exe',
    [int]$BolPort = 8090,

    # ---- Capacity（产能系统 API）----
    # 已确认（172.26.2.203 实测）：当前以控制台进程运行、监听 0.0.0.0:8000，
    # CommandLine 只有 exe 路径本身（无启动参数）。
    # 它是第四个 SSO 客户端（Python/FastAPI + uvicorn，与 BOL 同栈），日志实测：
    #   OIDC discovery 拉取失败：[SSL: CERTIFICATE_VERIFY_FAILED] ... self-signed certificate
    #   OIDC 登录跳转失败：idp_unreachable
    # 说明它同样靠 SSL_CERT_FILE 信任 Keycloak 的自签证书；控制台时代是人工设的，
    # 服务化后在 LocalSystem 下没有这个变量，必须与 MSIA/BOL 一样写进服务环境。
    [string]$CapacityService = 'CapacityAPI',
    [string]$CapacityExe = 'C:\ApplicationFile\ExecuteProgram\Capacity\publish\CapacityAPI\CapacityAPI.exe',
    [int]$CapacityPort = 8000,

    # ---- 公共 ----
    # 已确认（172.26.2.203 实测）：C:\keycloak\conf 下有 server.crt.pem（1103 字节）与 server.key.pem（1704 字节），
    # 当前两个应用校验的就是这张自签证书。换证完成后必须改为合并后的 ca-bundle.pem
    [string]$CertFile = 'C:\keycloak\conf\server.crt.pem',
    [string]$LogRoot = 'C:\Services\logs',
    [string]$RollbackDir = 'C:\Services\rollback',
    [switch]$SkipProbe,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ExitCode = 0
$script:Nssm = ''
$script:Specs = @()
$script:ScriptVersion = '2.2.1'
# 本次运行中已确认“当前 nssm 不支持”的参数，避免对同一参数反复尝试
$script:UnsupportedNssmParams = @{}

# ============================================================
# 输出
# ============================================================

function Get-ScriptFingerprint {
    $path = $PSCommandPath
    if (-not $path) { $path = [string]$MyInvocation.MyCommand.Path }
    try {
        if (-not $path -or -not (Test-Path -LiteralPath $path)) { return '未知' }
        return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.Substring(0, 8).ToLower()
    } catch {
        return '未知'
    }
}

function Show-ScriptVersion {
    Write-Line 'INFO' ('脚本版本 {0} · SHA256 前 8 位 {1} · {2}' -f $script:ScriptVersion, (Get-ScriptFingerprint), $PSCommandPath)
}

function Write-Line {
    param(
        [ValidateSet('OK', 'FAIL', 'WARN', 'INFO')]
        [string]$Level,
        [string]$Message
    )
    switch ($Level) {
        'OK'   { Write-Host ('[ OK ] ' + $Message) -ForegroundColor Green }
        'FAIL' { Write-Host ('[FAIL] ' + $Message) -ForegroundColor Red }
        'WARN' { Write-Host ('[WARN] ' + $Message) -ForegroundColor Yellow }
        default { Write-Host ('[INFO] ' + $Message) -ForegroundColor Cyan }
    }
}

function Write-Section {
    param([string]$Title)
    Write-Host ''
    Write-Host ('=' * 70) -ForegroundColor DarkGray
    Write-Host (' ' + $Title) -ForegroundColor White
    Write-Host ('=' * 70) -ForegroundColor DarkGray
}

function Assert-True {
    param([bool]$Condition, [string]$Message, [string]$FailureHint = '')
    if ($Condition) {
        Write-Line 'OK' $Message
    } else {
        Write-Line 'FAIL' $Message
        if ($FailureHint -ne '') { Write-Line 'INFO' $FailureHint }
        $script:ExitCode = 1
    }
}

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Administrator {
    if (-not (Test-Administrator)) {
        throw '当前不是管理员 PowerShell。注册/启停/删除 Windows 服务必须右键"以管理员身份运行"。'
    }
}

# ============================================================
# 敏感值处理
# ============================================================

function Read-SecretValue {
    param([string]$PromptText)
    $sec = Read-Host -AsSecureString -Prompt $PromptText
    if ($null -eq $sec -or $sec.Length -eq 0) { return '' }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Format-MaskedValue {
    param([string]$Value)
    if ($null -eq $Value) { return '(空)' }
    if ($Value -eq '') { return '(空)' }
    return ('***（长度 {0}）' -f $Value.Length)
}

# ============================================================
# 服务环境变量：直接读写 NSSM 存放位置（注册表 REG_MULTI_SZ）
#   - 读取: 用于“合并”而不是整行覆盖
#   - 写入: 避免口令出现在 nssm/sc 命令行
# ============================================================

function Get-ServiceParamKey {
    param([string]$ServiceName)
    return ('HKLM:\SYSTEM\CurrentControlSet\Services\{0}\Parameters' -f $ServiceName)
}

function Get-ServiceEnvLines {
    param([string]$ServiceName)
    $key = Get-ServiceParamKey -ServiceName $ServiceName
    if (-not (Test-Path -LiteralPath $key)) { return @() }
    $item = $null
    try {
        $item = Get-ItemProperty -LiteralPath $key -Name 'AppEnvironmentExtra' -ErrorAction Stop
    } catch {
        return @()
    }
    if ($null -eq $item) { return @() }
    $raw = $item.AppEnvironmentExtra
    if ($null -eq $raw) { return @() }
    # 注册表里也可能留着早前写回的脏行（变量名被 NUL 打断），统一清理后再交给
    # Merge-EnvLines，避免“键看起来不存在 -> 追加同名键 -> 写出重复键”
    # 用 , 包住：只有一行时 PowerShell 会把单元素数组拆成字符串，
    # 严格模式下调用点再取 .Count 就会抛 PropertyNotFoundStrict
    return ,@(
        $raw |
            ForEach-Object { ([string]$_ -replace "`0", '').Trim() } |
            Where-Object { $_ -ne '' }
    )
}

function Set-ServiceEnvLines {
    param([string]$ServiceName, [string[]]$Lines)
    $key = Get-ServiceParamKey -ServiceName $ServiceName
    if (-not (Test-Path -LiteralPath $key)) {
        New-Item -Path $key -Force | Out-Null
    }
    if ($null -eq $Lines -or $Lines.Count -eq 0) {
        Remove-ItemProperty -LiteralPath $key -Name 'AppEnvironmentExtra' -ErrorAction SilentlyContinue
        return
    }
    New-ItemProperty -LiteralPath $key -Name 'AppEnvironmentExtra' -PropertyType MultiString `
        -Value ([string[]]$Lines) -Force | Out-Null
}

function Merge-EnvLines {
    param([string[]]$Existing, [System.Collections.Specialized.OrderedDictionary]$Updates)

    $result = New-Object System.Collections.Generic.List[string]
    $replaced = @{}
    $seen = @{}

    # 变量名大小写不敏感（Windows 环境变量本身如此），统一用 Updates 里的写法作为规范名
    $canonical = @{}
    foreach ($k in $Updates.Keys) { $canonical[[string]$k] = [string]$k }

    foreach ($line in @($Existing)) {
        $text = ([string]$line).Trim()
        if ($text -eq '') { continue }
        if ($text -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
            $name = $matches[1]
            # 同名只保留第一条：历史脏数据清理后可能撞名，两条都写回就是重复键
            if ($seen.ContainsKey($name)) { continue }
            $seen[$name] = $true

            if ($canonical.ContainsKey($name)) {
                $keyName = $canonical[$name]
                $result.Add(('{0}={1}' -f $keyName, [string]$Updates[$keyName]))
                $replaced[$keyName] = $true
                continue
            }
        }
        $result.Add($text)
    }

    foreach ($name in $Updates.Keys) {
        if (-not $replaced.ContainsKey($name)) {
            $result.Add(('{0}={1}' -f $name, [string]$Updates[$name]))
        }
    }
    return $result.ToArray()
}

function Show-EnvLines {
    param([string]$ServiceName, [string[]]$SecretKeys)
    $lines = @(Get-ServiceEnvLines -ServiceName $ServiceName)
    if ($lines.Count -eq 0) {
        Write-Line 'WARN' ('{0}: AppEnvironmentExtra 为空' -f $ServiceName)
        return
    }
    foreach ($line in $lines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $name = $matches[1]
            $value = $matches[2]
            if (@($SecretKeys) -contains $name) {
                Write-Host ('        {0} = {1}' -f $name, (Format-MaskedValue $value)) -ForegroundColor DarkGray
            } else {
                Write-Host ('        {0} = {1}' -f $name, $value) -ForegroundColor DarkGray
            }
        } else {
            Write-Host ('        ' + $line) -ForegroundColor DarkGray
        }
    }
}

# ============================================================
# 进程 / 端口
# ============================================================

function Get-ProcessPathSafe {
    param([int]$ProcessId)
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return [string]$p.Path
    } catch {
        return ''
    }
}

function Get-ListenerList {
    param([int]$LocalPort)

    $results = @()
    $seen = @{}

    try {
        $conns = @(Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop)
        foreach ($conn in $conns) {
            $owner = [int]$conn.OwningProcess
            if ($seen.ContainsKey([string]$owner)) { continue }
            $seen[[string]$owner] = $true
            $results += [pscustomobject]@{
                ProcessId = $owner
                Address   = [string]$conn.LocalAddress
                Path      = (Get-ProcessPathSafe -ProcessId $owner)
            }
        }
        return $results
    } catch {
        # 回退 netstat
    }

    $lines = @(& netstat.exe -ano 2>$null)
    foreach ($line in $lines) {
        if ($line -match '^\s*TCP\s+(\S+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
            $address = $matches[1]
            $ownerText = $matches[2]
            if ($address -notmatch (':' + $LocalPort + '$')) { continue }
            if ($seen.ContainsKey($ownerText)) { continue }
            $seen[$ownerText] = $true
            $results += [pscustomobject]@{
                ProcessId = [int]$ownerText
                Address   = $address
                Path      = (Get-ProcessPathSafe -ProcessId ([int]$ownerText))
            }
        }
    }
    return $results
}

function Show-ListenerList {
    param([object[]]$Listeners)
    foreach ($item in $Listeners) {
        $pathText = $item.Path
        if ($pathText -eq '') { $pathText = '（不可读，可能为受保护进程）' }
        Write-Line 'INFO' ('PID={0}  {1}  {2}' -f $item.ProcessId, $item.Address, $pathText)
    }
}

function Test-PortListening {
    param([int]$LocalPort)
    return (@(Get-ListenerList -LocalPort $LocalPort).Count -gt 0)
}

# ============================================================
# NSSM 定位
# ============================================================

function Find-Nssm {
    if ($script:Nssm -ne '' -and (Test-Path -LiteralPath $script:Nssm)) { return $script:Nssm }

    $cmd = Get-Command 'nssm' -ErrorAction SilentlyContinue
    if ($null -ne $cmd -and $cmd.Source -ne '') {
        Write-Line 'OK' ('nssm 来源: PATH -> ' + $cmd.Source)
        return $cmd.Source
    }

    $candidates = @(
        (Join-Path $KeycloakHome 'nssm.exe'),
        'C:\nssm\win64\nssm.exe',
        'C:\nssm\nssm.exe',
        'C:\Tools\nssm.exe',
        'C:\ProgramData\chocolatey\bin\nssm.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            Write-Line 'OK' ('nssm 来源: 固定路径 -> ' + $c)
            return $c
        }
    }
    return ''
}

function Assert-Nssm {
    $found = Find-Nssm
    if ($found -eq '') {
        throw ('未找到 nssm.exe。已检查 PATH 与 {0}\nssm.exe 等常见位置。请从 https://nssm.cc/download 取 win64 版放到 {0} 后重试。' -f $KeycloakHome)
    }
    $script:Nssm = $found
    Write-Line 'OK' ('nssm 可用: ' + $script:Nssm)
}

function Invoke-Nssm {
    param([string[]]$Arguments)

    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $script:Nssm @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }

    # nssm.exe 以宽字符（UTF-16）写 stdout，PowerShell 5.1 按单字节代码页解码，
    # 结果是每个字符后面都跟一个 NUL（实测 72 字符的路径读回 144 字符）。
    # 在捕获层统一剥掉，避免下游的比对、显示与 dump 全部被污染。
    $text = ((($output | ForEach-Object { [string]$_ }) -join "`n") -replace "`0", '').Trim()
    if ($code -ne 0) {
        throw ('nssm {0} 失败，退出码 {1}。输出: {2}' -f ($Arguments -join ' '), $code, $text)
    }
    return $text
}

function Get-NssmValue {
    param(
        [string]$ServiceName,
        [string]$Key,
        [switch]$AsLines
    )

    # 唯一的 nssm get 取值入口：调用点不得再各自 Trim / -join / 替换字符。
    # Invoke-Nssm 已在捕获层剥离 NUL，这里负责把被拆碎的多段输出还原：
    #   - AppEnvironmentExtra 天然是多行；
    #   - 单值（Application 等）也可能被拆成“值 + 尾部残留行”，空行一律丢弃。
    $raw = Invoke-Nssm -Arguments @('get', $ServiceName, $Key)
    $lines = @(
        $raw -split "`r?`n" |
            ForEach-Object { ($_ -replace "`0", '').Trim() } |
            Where-Object { $_ -ne '' }
    )

    if ($AsLines) { return $lines }
    return ($lines -join "`n")
}

function Test-NssmValueMatch {
    param([string]$Actual, [string]$Expect)

    # 只比“值”，不比“格式”：两边 Trim 后再比。
    # 路径类值额外忽略末尾分隔符，C:\x 与 C:\x\ 不算不一致。
    $a = ([string]$Actual).Trim()
    $e = ([string]$Expect).Trim()
    if ($a -eq $e) { return $true }
    if ($a.Length -gt 1 -and $e.Length -gt 1) {
        return ($a.TrimEnd('\', '/') -eq $e.TrimEnd('\', '/'))
    }
    return $false
}

# ============================================================
# JAVA_HOME 自动定位（仅 Keycloak）
# ============================================================

function Find-JavaHome {
    if ($JavaHome -ne '') {
        return $JavaHome
    }
    $patterns = @(
        'C:\Program Files\Java\jdk-21*',
        'C:\Program Files\Eclipse Adoptium\jdk-21*',
        'C:\Program Files\Microsoft\jdk-21*'
    )
    foreach ($pattern in $patterns) {
        $found = @(Get-ChildItem -Path $pattern -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
        if ($found.Count -gt 0) {
            return $found[0].FullName
        }
    }
    return ''
}

# ============================================================
# 应用定义
# ============================================================

function New-Spec {
    param(
        [string]$Key,
        [string]$ServiceName,
        [string]$Application,
        [string]$AppParameters,
        [string]$AppDirectory,
        [string]$DisplayName,
        [string]$Description,
        [int[]]$Ports,
        [string]$ProbeUrl,
        # 多候选探测地址（按顺序试，任一 200 即 PASS）；为空时只用 ProbeUrl
        [string[]]$ProbeUrls = @(),
        [string[]]$RequiredEnv,
        [string[]]$SecretKeys,
        [System.Collections.Specialized.OrderedDictionary]$StaticEnv,
        [string]$ConsoleCommand,
        [string]$ConsoleWorkDir
    )

    return [pscustomobject]@{
        Key             = $Key
        ServiceName     = $ServiceName
        Application     = $Application
        AppParameters   = $AppParameters
        AppDirectory    = $AppDirectory
        DisplayName     = $DisplayName
        Description     = $Description
        Ports           = $Ports
        ProbeUrl        = $ProbeUrl
        ProbeUrls       = @($ProbeUrls)
        RequiredEnv     = $RequiredEnv
        SecretKeys      = $SecretKeys
        StaticEnv       = $StaticEnv
        ConsoleCommand  = $ConsoleCommand
        ConsoleWorkDir  = $ConsoleWorkDir
    }
}

function Initialize-Specs {
    $specs = @()

    # ---------- Keycloak ----------
    $kcBat = Join-Path $KeycloakHome 'bin\kc.bat'
    $kcApp = $kcBat
    $kcArgs = 'start --optimized'
    $kcConsole = '.\bin\kc.bat start --optimized'
    if ($KeycloakViaCmd) {
        $kcApp = Join-Path $env:SystemRoot 'System32\cmd.exe'
        $kcArgs = ('/c ""{0}" start --optimized"' -f $kcBat)
        $kcConsole = ('cmd /c ""{0}" start --optimized"' -f $kcBat)
        Write-Line 'INFO' 'Keycloak 使用 cmd.exe 包装方式（-KeycloakViaCmd）'
    }

    $kcEnv = New-Object System.Collections.Specialized.OrderedDictionary
    $resolvedJava = Find-JavaHome
    if ($resolvedJava -ne '') { $kcEnv['JAVA_HOME'] = $resolvedJava }

    $kcRequired = @('JAVA_HOME', 'KC_DB_PASSWORD')
    $kcSecrets = @('KC_DB_PASSWORD', 'KC_HTTPS_KEY_STORE_PASSWORD')

    $specs += New-Spec -Key 'Keycloak' -ServiceName $KeycloakService -Application $kcApp `
        -AppParameters $kcArgs -AppDirectory $KeycloakHome `
        -DisplayName 'Keycloak 统一身份认证（25.0.6）' `
        -Description 'Keycloak 25.0.6 统一身份认证服务（NSSM 托管，8443 HTTPS / 9000 管理口；请勿再手工运行 kc.bat）' `
        -Ports @($KeycloakHttpsPort, $KeycloakMgmtPort) `
        -ProbeUrl ('https://127.0.0.1:{0}/realms/{1}/.well-known/openid-configuration' -f $KeycloakHttpsPort, $KeycloakRealm) `
        -RequiredEnv $kcRequired -SecretKeys $kcSecrets -StaticEnv $kcEnv `
        -ConsoleCommand $kcConsole -ConsoleWorkDir $KeycloakHome

    # ---------- MSIA ----------
    $msiaDir = ''
    if ($MsiaExe -ne '') { $msiaDir = Split-Path -Parent $MsiaExe }

    $msiaEnv = New-Object System.Collections.Specialized.OrderedDictionary
    $msiaEnv['SSL_CERT_FILE'] = $CertFile

    $specs += New-Spec -Key 'MSIA' -ServiceName $MsiaService -Application $MsiaExe `
        -AppParameters '' -AppDirectory $msiaDir `
        -DisplayName 'MSIA 审核管理系统' `
        -Description 'MSIA 审核管理系统后台服务（NSSM 托管；请勿再手工运行 msia_server.exe）' `
        -Ports @($MsiaPort) `
        -ProbeUrl ('http://127.0.0.1:{0}/api/auth/config' -f $MsiaPort) `
        -RequiredEnv @('SSL_CERT_FILE') -SecretKeys @('JWT_SECRET_KEY') -StaticEnv $msiaEnv `
        -ConsoleCommand '.\msia_server.exe' -ConsoleWorkDir $msiaDir

    # ---------- BOL ----------
    $bolDir = ''
    if ($BolExe -ne '') { $bolDir = Split-Path -Parent $BolExe }

    # 已确认（172.26.2.203 实测）：BOL 的 OIDC 配置全部来自 db_config.ini 的 [oidc] 段
    # （issuer / client_id / secret / redirect_uri 等），环境变量里没有对应值。
    # 因此服务环境变量只注入 SSL_CERT_FILE，绝不写任何 OIDC_*：
    #   1) 一写就改变优先级，形成环境变量与配置文件双源头，排障时无法判断实际生效值；
    #   2) OIDC_CLIENT_SECRET 会以明文形式落到服务注册表，比留在配置文件里更难管控。
    $bolEnv = New-Object System.Collections.Specialized.OrderedDictionary
    $bolEnv['SSL_CERT_FILE'] = $CertFile

    $specs += New-Spec -Key 'BOL' -ServiceName $BolService -Application $BolExe `
        -AppParameters '' -AppDirectory $bolDir `
        -DisplayName 'BOL 管理系统' `
        -Description 'BOL 管理系统后台服务（NSSM 托管；请勿再手工运行 BOLServer.exe）' `
        -Ports @($BolPort) `
        -ProbeUrl ('http://127.0.0.1:{0}/' -f $BolPort) `
        -RequiredEnv @('SSL_CERT_FILE') -SecretKeys @() -StaticEnv $bolEnv `
        -ConsoleCommand '.\BOLServer.exe' -ConsoleWorkDir $bolDir

    # ---------- Capacity（产能系统 API）----------
    $capDir = ''
    if ($CapacityExe -ne '') { $capDir = Split-Path -Parent $CapacityExe }

    # SSL_CERT_FILE 与 MSIA/BOL 完全一致：它是第四个 SSO 客户端，服务化后 LocalSystem 下没有这个变量，
    # OIDC discovery 会报 CERTIFICATE_VERIFY_FAILED，登录跳转报 idp_unreachable。
    # 探测路径不固定（该应用是自研 FastAPI 服务，未约定健康端点），故按候选顺序依次试，
    # 任一返回 200 即 PASS；全部失败才 FAIL，并在输出里列出试过哪些路径。
    $capEnv = New-Object System.Collections.Specialized.OrderedDictionary
    $capEnv['SSL_CERT_FILE'] = $CertFile
    $capBase = 'http://127.0.0.1:{0}' -f $CapacityPort

    $specs += New-Spec -Key 'Capacity' -ServiceName $CapacityService -Application $CapacityExe `
        -AppParameters '' -AppDirectory $capDir `
        -DisplayName 'Capacity 产能系统 API' `
        -Description 'Capacity 产能系统 API（NSSM 托管，8000 端口；第四个 SSO 客户端，需 SSL_CERT_FILE 信任 Keycloak 自签证书）' `
        -Ports @($CapacityPort) `
        -ProbeUrl '' `
        -ProbeUrls @(($capBase + '/health'), ($capBase + '/openapi.json'), ($capBase + '/docs'), ($capBase + '/')) `
        -RequiredEnv @('SSL_CERT_FILE') -SecretKeys @() -StaticEnv $capEnv `
        -ConsoleCommand '.\CapacityAPI.exe' -ConsoleWorkDir $capDir

    $script:Specs = $specs
}

function Get-SelectedSpecs {
    if ($App -eq 'All') { return $script:Specs }
    return @($script:Specs | Where-Object { $_.Key -eq $App })
}

# ============================================================
# 通用参数表
# ============================================================

function Get-StandardParamList {
    param([pscustomobject]$Spec)

    $stdout = Join-Path $LogRoot ($Spec.ServiceName + '-stdout.log')
    $stderr = Join-Path $LogRoot ($Spec.ServiceName + '-stderr.log')

    # 停止超时：Keycloak（JVM + kc.bat）给足 Ctrl+C 优雅退出时间；PyInstaller 控制台程序 15 秒足够
    $stopTimeout = 15000
    if ($Spec.Key -eq 'Keycloak') { $stopTimeout = 20000 }

    $list = New-Object System.Collections.Generic.List[object]
    $list.Add(@{ Name = 'AppDirectory'; Value = $Spec.AppDirectory })
    $list.Add(@{ Name = 'DisplayName'; Value = $Spec.DisplayName })
    $list.Add(@{ Name = 'Description'; Value = $Spec.Description })
    $list.Add(@{ Name = 'Start'; Value = 'SERVICE_AUTO_START' })
    $list.Add(@{ Name = 'AppStdout'; Value = $stdout })
    $list.Add(@{ Name = 'AppStderr'; Value = $stderr })
    # AppTimestampLog 不是所有 nssm 版本都有（现场 2.24 的 set 参数表里没有它）。
    # 标为可选：支持就设，不支持只 WARN 跳过，不影响服务可用性
    $list.Add(@{ Name = 'AppTimestampLog'; Value = '1'; Optional = $true; SkipNote = '日志行不带时间戳，其余配置不受影响' })
    $list.Add(@{ Name = 'AppRotateFiles'; Value = '1' })
    $list.Add(@{ Name = 'AppRotateOnline'; Value = '1' })
    $list.Add(@{ Name = 'AppRotateSeconds'; Value = '86400' })
    $list.Add(@{ Name = 'AppRotateBytes'; Value = '10485760' })
    $list.Add(@{ Name = 'AppStopMethodConsole'; Value = [string]$stopTimeout })
    $list.Add(@{ Name = 'AppStopMethodSkip'; Value = '0' })
    $list.Add(@{ Name = 'AppRestartDelay'; Value = '5000' })
    $list.Add(@{ Name = 'AppThrottle'; Value = '10000' })
    if ($Spec.AppParameters -ne '') {
        $list.Add(@{ Name = 'AppParameters'; Value = $Spec.AppParameters })
    }
    return $list
}

function Get-StandardExitSetting {
    return 'Default Restart'
}

# ============================================================
# Precheck
# ============================================================

function Invoke-Precheck {
    Write-Section '只读预检（不写任何配置）'

    Assert-True (Test-Administrator) '当前为管理员 PowerShell' '非管理员无法读取服务环境变量，注册/启停也会失败。'

    try {
        Assert-Nssm
    } catch {
        Write-Line 'FAIL' $_.Exception.Message
        $script:ExitCode = 1
    }

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（服务名 {1}）---' -f $spec.Key, $spec.ServiceName)

        if ($spec.Key -eq 'BOL' -and $spec.Application -eq '') {
            Write-Line 'FAIL' 'BOL 可执行文件路径未提供（-BolExe）' '现场确认 BOLServer.exe 所在目录后重跑，例如 -BolExe ''D:\BOLServer\BOLServer.exe''。BOL 的 db_config.ini 必须与该 exe 同目录。'
        } elseif ($spec.Application -eq '') {
            Write-Line 'FAIL' ('{0} 可执行文件路径为空' -f $spec.Key) '用参数指定实际路径。'
        } elseif (-not (Test-Path -LiteralPath $spec.Application)) {
            Write-Line 'FAIL' ('{0} 不存在: {1}' -f $spec.Key, $spec.Application)
            $script:ExitCode = 1
        } else {
            $item = Get-Item -LiteralPath $spec.Application
            Write-Line 'OK' ('主程序存在: {0}（{1:N0} 字节，{2:yyyy-MM-dd HH:mm:ss}）' -f $item.FullName, $item.Length, $item.LastWriteTime)
        }

        if ($spec.AppDirectory -ne '' -and (Test-Path -LiteralPath $spec.AppDirectory)) {
            Write-Line 'OK' ('工作目录: ' + $spec.AppDirectory)
        } else {
            Write-Line 'FAIL' ('工作目录不存在: ' + $spec.AppDirectory)
            $script:ExitCode = 1
        }

        if ($spec.Key -eq 'Keycloak') {
            $java = [string]$spec.StaticEnv['JAVA_HOME']
            if ($java -eq '') {
                Write-Line 'FAIL' 'JAVA_HOME 未定位到（jdk-21）' '用 -JavaHome ''C:\Program Files\Java\jdk-21.x'' 指定。缺 JAVA_HOME 时服务会回落系统 Java 8 导致启动失败。'
                $script:ExitCode = 1
            } elseif (-not (Test-Path -LiteralPath (Join-Path $java 'bin\java.exe'))) {
                Write-Line 'FAIL' ('JAVA_HOME 下没有 bin\java.exe: ' + $java)
                $script:ExitCode = 1
            } else {
                Write-Line 'OK' ('JAVA_HOME: ' + $java)
            }
        }

        # 服务冲突
        $existing = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            Write-Line 'WARN' ('服务已存在: {0}（{1} / {2}）。Register 默认只回读校验、不改配置；需覆盖请加 -Force。' -f $spec.ServiceName, [string]$existing.Status, [string]$existing.StartType)
        } else {
            Write-Line 'OK' ('服务名可用: ' + $spec.ServiceName)
        }

        # 同 exe 的其它服务
        if ($spec.Application -ne '') {
            $same = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
                    $_.PathName -and ($_.PathName.ToLower().Contains($spec.Application.ToLower()))
                } | Where-Object { $_.Name -ne $spec.ServiceName })
            if ($same.Count -gt 0) {
                Write-Line 'WARN' ('已存在指向同一程序的其它服务: {0}（会抢同一端口）' -f (($same | ForEach-Object { $_.Name }) -join ', '))
            }
        }

        # 端口
        foreach ($port in $spec.Ports) {
            $listeners = @(Get-ListenerList -LocalPort $port)
            if ($listeners.Count -eq 0) {
                Write-Line 'OK' ('端口 {0} 空闲' -f $port)
            } else {
                if ($null -eq $existing) {
                    Write-Line 'WARN' ('端口 {0} 已被占用（服务尚未创建，占用者应为当前控制台实例；切换前必须先停）:' -f $port)
                } elseif ([string]$existing.Status -eq 'Running') {
                    Write-Line 'WARN' ('端口 {0} 已被占用（占用者就是正在运行的 {1} 服务，属正常，不要停服务）:' -f $port, $spec.ServiceName)
                } else {
                    Write-Line 'WARN' ('端口 {0} 已被占用（服务已存在但处于 {1}，占用者另有其人；先确认是否为遗留的控制台实例）:' -f $port, [string]$existing.Status)
                }
                Show-ListenerList -Listeners $listeners
            }
        }

        # 证书
        if (@($spec.RequiredEnv) -contains 'SSL_CERT_FILE') {
            if (Test-Path -LiteralPath $CertFile) {
                Write-Line 'OK' ('SSL_CERT_FILE 目标文件存在: ' + $CertFile)
            } else {
                Write-Line 'FAIL' ('SSL_CERT_FILE 目标文件不存在: ' + $CertFile) '先用换证书手册生成合并包；换证书前可指向当前在用的 PEM。'
                $script:ExitCode = 1
            }
        }

        # 日志目录
        if (Test-Path -LiteralPath $LogRoot) {
            Write-Line 'OK' ('日志目录存在: ' + $LogRoot)
        } else {
            Write-Line 'WARN' ('日志目录不存在，Register 时会创建: ' + $LogRoot)
        }
    }

    Write-Host ''
    Write-Line 'INFO' '预检结束。Register 前请确认：①尚未服务化的应用其控制台实例仍在运行（不要提前关窗）；②手册“执行前必须现场确认”清单已逐项核实。'
}

# ============================================================
# Register
# ============================================================

function Resolve-EnvUpdates {
    param([pscustomobject]$Spec)

    $updates = New-Object System.Collections.Specialized.OrderedDictionary
    $existingLines = Get-ServiceEnvLines -ServiceName $Spec.ServiceName
    $existingKeys = @{}
    foreach ($line in $existingLines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { $existingKeys[$matches[1]] = $true }
    }

    foreach ($name in $Spec.StaticEnv.Keys) {
        $updates[$name] = [string]$Spec.StaticEnv[$name]
    }

    foreach ($name in $Spec.SecretKeys) {
        $already = $existingKeys.ContainsKey($name)
        # 必填项留空时写占位，让预检/启动阶段明确报错；可选项（如 JWT_SECRET_KEY、
        # KC_HTTPS_KEY_STORE_PASSWORD）留空即不写入，避免占位值覆盖应用配置文件里的真实值
        $isRequired = (@($Spec.RequiredEnv) -contains $name)
        switch ($SecretMode) {
            'Keep' {
                if (-not $already -and $isRequired) { $updates[$name] = ('CHANGE_ME_' + $name) }
            }
            'Placeholder' {
                if (-not $already -and $isRequired) { $updates[$name] = ('CHANGE_ME_' + $name) }
            }
            'Prompt' {
                $value = Read-SecretValue ('请输入 {0} 的值{1}' -f $name, $(if ($isRequired) { '' } else { '（直接回车=不写入）' }))
                if ($value -ne '') {
                    $updates[$name] = $value
                } elseif (-not $already -and $isRequired) {
                    $updates[$name] = ('CHANGE_ME_' + $name)
                }
            }
        }
    }

    foreach ($pair in @($ExtraEnv)) {
        if ($pair -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $updates[$matches[1]] = $matches[2]
        } elseif ($pair.Trim() -ne '') {
            Write-Line 'WARN' ('忽略无法解析的 ExtraEnv 项: ' + $pair)
        }
    }

    return $updates
}

function Set-ServiceRunAs {
    param([pscustomobject]$Spec)

    if ($RunAsAccount -eq 'LocalSystem' -or $RunAsAccount -eq '') {
        Invoke-Nssm -Arguments @('set', $Spec.ServiceName, 'ObjectName', 'LocalSystem') | Out-Null
        Write-Line 'OK' ('{0}: 运行账号 LocalSystem' -f $Spec.ServiceName)
        return
    }

    Write-Line 'WARN' ('将把 {0} 设为 {1}。注意：账号口令会短暂出现在进程命令行中（nssm/sc 无免密方式），设完请勿保留命令历史。' -f $Spec.ServiceName, $RunAsAccount)
    $pwd = Read-SecretValue ('请输入 {0} 的口令' -f $RunAsAccount)
    if ($pwd -eq '') {
        Write-Line 'FAIL' '口令为空，跳过账号设置，服务仍以 LocalSystem 运行'
        $script:ExitCode = 1
        return
    }
    Invoke-Nssm -Arguments @('set', $Spec.ServiceName, 'ObjectName', $RunAsAccount, $pwd) | Out-Null
    Write-Line 'OK' ('{0}: 运行账号 {1}（请用 services.msc 登录页复核，并确认该账号有“作为服务登录”权限）' -f $Spec.ServiceName, $RunAsAccount)
}

function Invoke-Register {
    Write-Section '注册 / 更新服务（不自动启动）'

    Assert-Administrator
    Assert-Nssm

    if (-not (Test-Path -LiteralPath $LogRoot)) {
        New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
        Write-Line 'INFO' ('已创建日志目录: ' + $LogRoot)
    }

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('=== {0} -> {1} ===' -f $spec.Key, $spec.ServiceName)

        if ($spec.Application -eq '' -or -not (Test-Path -LiteralPath $spec.Application)) {
            Write-Line 'FAIL' ('主程序路径无效: "{0}"。跳过。' -f $spec.Application)
            $script:ExitCode = 1
            continue
        }

        $existing = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $existing) {
            Write-Line 'INFO' ('nssm install {0} "{1}"' -f $spec.ServiceName, $spec.Application)
            $installArgs = @('install', $spec.ServiceName, $spec.Application)
            # cmd.exe 包装方式的参数含引号，安装时不拆分，随后由 nssm set AppParameters 整体写入
            if ($spec.AppParameters -ne '' -and -not $KeycloakViaCmd) {
                $installArgs += ($spec.AppParameters -split ' ')
            }
            try {
                Invoke-Nssm -Arguments $installArgs | Out-Null
            } catch {
                Write-Line 'FAIL' ('注册失败: ' + $_.Exception.Message)
                Write-Line 'INFO' '若报“不是有效的 Win32 应用程序”，Keycloak 改用 -KeycloakViaCmd 重试（用 cmd.exe 包装 kc.bat）。'
                $script:ExitCode = 1
                continue
            }
            Write-Line 'OK' '服务已注册'
        } else {
            if (-not $Force) {
                # 已存在的服务一律视为现场既有配置（可能是手工建的），默认只回读、不改写，
                # 避免覆盖 Application / ObjectName / 环境变量而导致原本能跑的配置被破坏
                Write-Line 'WARN' ('服务已存在（{0} / {1}），跳过安装与参数写入，仅做只读校验。' -f [string]$existing.Status, [string]$existing.StartType)
                foreach ($key in @('Application', 'AppDirectory', 'ObjectName')) {
                    try {
                        $cur = Get-NssmValue -ServiceName $spec.ServiceName -Key $key
                    } catch {
                        Write-Line 'WARN' ('读取 {0} 失败: {1}' -f $key, $_.Exception.Message)
                        continue
                    }

                    if ($cur -eq '') {
                        Write-Line 'INFO' ('现有 {0} = (空)' -f $key)
                    } else {
                        Write-Line 'INFO' ('现有 {0} = {1}' -f $key, $cur)
                    }

                    $expect = ''
                    if ($key -eq 'Application') { $expect = $spec.Application }
                    elseif ($key -eq 'AppDirectory') { $expect = $spec.AppDirectory }
                    if ($expect -ne '' -and $cur -ne '' -and -not (Test-NssmValueMatch -Actual $cur -Expect $expect)) {
                        # 引号包住两边，便于区分“值真的不同”与“只是空白/格式差异”
                        Write-Line 'WARN' ('服务内 {0} 与本脚本预期不一致（实际 "{1}"，预期 "{2}"）。确认现场为准后，如需按本规范覆盖请加 -Force 重跑。' -f $key, $cur, $expect)
                    }
                }
                Write-Line 'INFO' '本服务未做任何改动。加 -Force 才会按本规范覆盖标准参数与环境变量。'
                continue
            }
            Write-Line 'INFO' '服务已存在，-Force 指定：更新参数，不改 Application'
        }

        # 标准参数
        $failCount = 0
        foreach ($p in (Get-StandardParamList -Spec $spec)) {
            $isOptional = $p.ContainsKey('Optional') -and [bool]$p['Optional']
            $skipNote = '该项不是服务运行的必需参数'
            if ($p.ContainsKey('SkipNote')) { $skipNote = [string]$p['SkipNote'] }

            # 同一参数在本次运行里已确认不支持，就不再重复尝试
            if ($script:UnsupportedNssmParams.ContainsKey([string]$p.Name)) {
                Write-Line 'WARN' ('当前 nssm 版本不支持 {0}，已跳过（{1}）' -f $p.Name, $skipNote)
                continue
            }

            try {
                Invoke-Nssm -Arguments @('set', $spec.ServiceName, $p.Name, [string]$p.Value) | Out-Null
            } catch {
                # 用一次失败的 set 做能力探测：参数名非法时 nssm 不改动任何配置，可重复执行、无副作用
                if ($isOptional -and $_.Exception.Message -match 'Invalid parameter|无效参数') {
                    $script:UnsupportedNssmParams[[string]$p.Name] = $true
                    Write-Line 'WARN' ('当前 nssm 版本不支持 {0}，已跳过（{1}）' -f $p.Name, $skipNote)
                } else {
                    Write-Line 'FAIL' ('设置 {0} 失败: {1}' -f $p.Name, $_.Exception.Message)
                    $failCount++
                    $script:ExitCode = 1
                }
            }
        }
        if ($failCount -eq 0) { Write-Line 'OK' '标准参数写入完成' }

        # 退出后重启策略
        try {
            Invoke-Nssm -Arguments @('set', $spec.ServiceName, 'AppExit', 'Default', 'Restart') | Out-Null
            Write-Line 'OK' 'AppExit Default = Restart（异常退出后自动重启）'
        } catch {
            Write-Line 'FAIL' ('设置 AppExit 失败: ' + $_.Exception.Message)
            $script:ExitCode = 1
        }

        # 运行账号
        Set-ServiceRunAs -Spec $spec

        # 环境变量（合并写入，口令不经过命令行）
        $updates = Resolve-EnvUpdates -Spec $spec
        if ($updates.Count -gt 0) {
            $merged = Merge-EnvLines -Existing (Get-ServiceEnvLines -ServiceName $spec.ServiceName) -Updates $updates
            Set-ServiceEnvLines -ServiceName $spec.ServiceName -Lines $merged
            Write-Line 'OK' ('环境变量已写入（共 {0} 项，合并语义，未涉及的变量保持不变）' -f $updates.Count)
        } else {
            Write-Line 'INFO' '本次没有需要写入的环境变量'
        }

        Write-Host ''
        Write-Line 'INFO' '回读环境变量（敏感值已打码）:'
        Show-EnvLines -ServiceName $spec.ServiceName -SecretKeys $spec.SecretKeys

        # 回读关键参数
        Write-Host ''
        $readBack = @(
            @{ Name = 'Application'; Expect = $spec.Application },
            @{ Name = 'AppDirectory'; Expect = $spec.AppDirectory },
            @{ Name = 'Start'; Expect = 'SERVICE_AUTO_START' }
        )
        foreach ($r in $readBack) {
            $actual = ''
            try { $actual = Get-NssmValue -ServiceName $spec.ServiceName -Key $r.Name } catch { $actual = '' }
            if (Test-NssmValueMatch -Actual $actual -Expect $r.Expect) {
                Write-Host ('        {0} = {1}' -f $r.Name, $actual)
            } else {
                Write-Line 'WARN' ('{0} 回读为 "{1}"，期望 "{2}"' -f $r.Name, $actual, $r.Expect)
            }
        }

        # 必填项检查
        $lines = Get-ServiceEnvLines -ServiceName $spec.ServiceName
        foreach ($need in $spec.RequiredEnv) {
            $hit = @($lines | Where-Object { $_ -match ('^\s*{0}\s*=' -f [regex]::Escape($need)) })
            if ($hit.Count -eq 0) {
                Write-Line 'FAIL' ('缺少必填环境变量: ' + $need)
                $script:ExitCode = 1
            }
        }
        $placeholders = @($lines | Where-Object { $_ -match '=CHANGE_ME_' })
        if ($placeholders.Count -gt 0) {
            Write-Line 'WARN' ('{0} 项仍是 CHANGE_ME 占位，启动前必须填写: {1}' -f $placeholders.Count, (($placeholders | ForEach-Object { ($_ -split '=')[0] }) -join ', '))
        }
    }

    Write-Host ''
    if ($script:ExitCode -eq 0) {
        Write-Line 'OK' '注册阶段完成（服务未启动）。下一步：停掉控制台实例，再 -Action Start。'
    } else {
        Write-Line 'WARN' '注册阶段结束但存在 FAIL 项，先处理再启动。'
    }
}

# ============================================================
# Start / Stop / Status
# ============================================================

function Invoke-Start {
    Write-Section '启动服务'

    Assert-Administrator

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'FAIL' ('服务不存在: ' + $spec.ServiceName)
            Write-Line 'INFO' '先执行 -Action Register。'
            $script:ExitCode = 1
            continue
        }

        # 占位符未填时拒绝启动
        $lines = Get-ServiceEnvLines -ServiceName $spec.ServiceName
        $placeholder = @($lines | Where-Object { $_ -match '=CHANGE_ME_' })
        if ($placeholder.Count -gt 0) {
            Write-Line 'FAIL' ('仍有 CHANGE_ME 占位环境变量: {0}' -f (($placeholder | ForEach-Object { ($_ -split '=')[0] }) -join ', '))
            Write-Line 'INFO' '用 -Action SetEnv -SecretMode Prompt 填写，或用 nssm edit 图形界面填写。'
            $script:ExitCode = 1
            continue
        }

        # 端口占用检查（本服务未运行时不应被占）
        if ([string]$svc.Status -ne 'Running') {
            $blocked = $false
            foreach ($port in $spec.Ports) {
                $listeners = @(Get-ListenerList -LocalPort $port)
                if ($listeners.Count -gt 0) {
                    Write-Line 'FAIL' ('端口 {0} 已被占用，服务会启动失败:' -f $port)
                    Show-ListenerList -Listeners $listeners
                    Write-Line 'INFO' '这通常就是旧的控制台实例。请先在那个窗口按 Ctrl+C（或结束该进程）后再启动服务。'
                    $blocked = $true
                }
            }
            if ($blocked) {
                $script:ExitCode = 1
                continue
            }

            Write-Line 'INFO' '正在启动...'
            try {
                Start-Service -Name $spec.ServiceName
            } catch {
                Write-Line 'FAIL' ('Start-Service 失败: ' + $_.Exception.Message)
                Write-Line 'INFO' ('查看事件查看器“Windows 日志-系统”中来源 Service Control Manager 的 7000/7009/7034，以及 {0} 下的 stderr 日志。' -f $LogRoot)
                $script:ExitCode = 1
                continue
            }
        } else {
            Write-Line 'OK' '服务已在运行'
        }

        # 等待 Running
        $deadline = (Get-Date).AddSeconds(30)
        $running = $false
        while ((Get-Date) -lt $deadline) {
            $cur = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
            if ($null -ne $cur -and [string]$cur.Status -eq 'Running') { $running = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $running) {
            Write-Line 'FAIL' '30 秒内未进入 Running'
            Write-Line 'INFO' ('优先看 stderr 日志: ' + (Join-Path $LogRoot ($spec.ServiceName + '-stderr.log')))
            $script:ExitCode = 1
            continue
        }
        Write-Line 'OK' '服务状态 Running'

        # 等待端口
        $deadline = (Get-Date).AddSeconds(40)
        $allUp = $false
        while ((Get-Date) -lt $deadline) {
            $allUp = $true
            foreach ($port in $spec.Ports) {
                if (-not (Test-PortListening -LocalPort $port)) { $allUp = $false }
            }
            if ($allUp) { break }
            Start-Sleep -Seconds 1
        }
        foreach ($port in $spec.Ports) {
            Assert-True (Test-PortListening -LocalPort $port) ('端口 {0} 处于 LISTENING' -f $port) ('端口 {0} 无监听：核对应用配置里的监听端口是否与预期一致。' -f $port)
        }
    }
}

function Invoke-Stop {
    Write-Section '停止服务'

    Assert-Administrator

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'WARN' '服务不存在，跳过'
            continue
        }
        if ([string]$svc.Status -eq 'Stopped') {
            Write-Line 'OK' '服务已是 Stopped'
        } else {
            try {
                Stop-Service -Name $spec.ServiceName -Force
            } catch {
                Write-Line 'FAIL' ('停止失败: ' + $_.Exception.Message)
                $script:ExitCode = 1
            }
            $deadline = (Get-Date).AddSeconds(40)
            while ((Get-Date) -lt $deadline) {
                $cur = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
                if ($null -ne $cur -and [string]$cur.Status -eq 'Stopped') { break }
                Start-Sleep -Seconds 1
            }
            $cur = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
            Assert-True ($null -ne $cur -and [string]$cur.Status -eq 'Stopped') '服务已停止' '超过 40 秒仍未停止：检查是否有子进程（java / msia_server / BOLServer）未退出，必要时 taskkill 后再试。'
        }

        # 残留进程与端口
        $exeName = ''
        if ($spec.Application -ne '') { $exeName = Split-Path -Leaf $spec.Application }
        if ($spec.Key -eq 'Keycloak') { $exeName = 'java.exe' }
        if ($exeName -ne '') {
            $residual = @(Get-Process -Name ([System.IO.Path]::GetFileNameWithoutExtension($exeName)) -ErrorAction SilentlyContinue)
            if ($residual.Count -gt 0) {
                Write-Line 'WARN' ('仍有同名进程运行（可能是别的实例）: {0}' -f (($residual | ForEach-Object { $_.Id }) -join ', '))
                Write-Line 'INFO' ('确认是本服务残留时用: taskkill /F /IM {0}' -f $exeName)
            }
        }
        foreach ($port in $spec.Ports) {
            $listeners = @(Get-ListenerList -LocalPort $port)
            if ($listeners.Count -eq 0) {
                Write-Line 'OK' ('端口 {0} 已释放' -f $port)
            } else {
                Write-Line 'WARN' ('端口 {0} 仍有监听:' -f $port)
                Show-ListenerList -Listeners $listeners
            }
        }
    }
}

function Invoke-Status {
    Write-Section '服务状态（只读）'

    if ($script:Nssm -eq '') { $null = Find-Nssm }

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'WARN' '服务未注册'
        } else {
            $info = Get-CimInstance Win32_Service -Filter ("Name='" + $spec.ServiceName + "'") -ErrorAction SilentlyContinue
            Write-Line 'INFO' ('状态: {0}  启动类型: {1}' -f [string]$svc.Status, [string]$svc.StartType)
            if ($null -ne $info) {
                Write-Line 'INFO' ('运行账号: ' + [string]$info.StartName)
                Write-Line 'INFO' ('进程 PID: ' + [string]$info.ProcessId)
            }
        }

        foreach ($port in $spec.Ports) {
            $listeners = @(Get-ListenerList -LocalPort $port)
            if ($listeners.Count -eq 0) {
                Write-Line 'INFO' ('端口 {0}: 无监听' -f $port)
            } else {
                Show-ListenerList -Listeners $listeners
            }
        }

        $stdout = Join-Path $LogRoot ($spec.ServiceName + '-stdout.log')
        $stderr = Join-Path $LogRoot ($spec.ServiceName + '-stderr.log')
        foreach ($f in @($stdout, $stderr)) {
            if (Test-Path -LiteralPath $f) {
                $item = Get-Item -LiteralPath $f
                Write-Line 'INFO' ('日志 {0}: {1:N0} 字节，最后写入 {2:yyyy-MM-dd HH:mm:ss}' -f $item.Name, $item.Length, $item.LastWriteTime)
            } else {
                Write-Line 'INFO' ('日志 {0}: 不存在' -f (Split-Path -Leaf $f))
            }
        }
    }
}

# ============================================================
# Verify
# ============================================================

function Get-ProbeErrorKind {
    param([System.Exception]$Exception)

    # 把外层与内层异常消息拼起来分类，用于给出可操作的提示
    $msg = ''
    $cur = $Exception
    $depth = 0
    while ($null -ne $cur -and $depth -lt 6) {
        $msg += ' ' + [string]$cur.Message
        $cur = $cur.InnerException
        $depth++
    }

    if ($msg -match 'trust relationship|SSL/TLS secure channel|AuthenticationException|证书|安全通道') { return 'cert' }
    if ($msg -match 'actively refused|No connection could be made|积极拒绝|目标计算机积极拒绝') { return 'refused' }
    if ($msg -match 'timed out|timeout|超时') { return 'timeout' }
    if ($msg -match 'name or service not known|无法解析|No such host') { return 'dns' }
    return 'other'
}

function Get-ExceptionChainText {
    param([System.Exception]$Exception)

    # 外层 Message + 每层 InnerException.Message（最多 6 层）+ 最内层 StackTrace 首两帧
    $parts = New-Object System.Collections.Generic.List[string]
    $cur = $Exception
    $depth = 0
    while ($null -ne $cur -and $depth -lt 6) {
        $parts.Add(('L{0} [{1}] {2}' -f $depth, $cur.GetType().Name, [string]$cur.Message))
        $cur = $cur.InnerException
        $depth++
    }
    $innermost = $Exception
    while ($null -ne $innermost.InnerException) { $innermost = $innermost.InnerException }
    if ($innermost.StackTrace) {
        $frames = @($innermost.StackTrace -split "`r?`n" | Select-Object -First 2)
        if ($frames.Count -gt 0) { $parts.Add('Stack: ' + ($frames -join ' ; ')) }
    }
    return ($parts -join ' | ')
}

function Invoke-HttpProbeOnce {
    param([string]$Url, [int]$TimeoutSec = 10)

    # 只发一次 GET，返回状态码；异常交给调用方分类。
    # 注意：本函数不再用于 https 探测——PS 5.1 下用 scriptblock 跳过证书校验会在握手线程上崩，见下
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return [int]$resp.StatusCode
}

function Get-KeycloakDiscoveryViaSslStream {
    param([string]$Url)

    # Keycloak 的唯一探针：不经过 ServicePointManager / Invoke-WebRequest。
    #
    # 为什么不用 Invoke-WebRequest：现场实测（2.1.3 异常链）已经证明
    #   [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    # 这种“用 PowerShell 脚本块当证书回调”的写法在 PS 5.1 下根本不可用——回调在 TLS 握手线程上
    # 执行，该线程没有 Runspace，必然抛：
    #   PSInvalidOperationException: There is no Runspace available to run scripts in this thread.
    #   The script block you attempted to invoke was:  $true
    # 于是握手必失败、每次要等满超时，再换别的办法。SslStream 的授权回调是 .NET 委托，
    # 不需要 Runspace，且 TLS 版本绑在本次握手上，不受进程级 ServicePointManager 影响。
    # 以后要探自签证书的 https，直接用这条路径，别再折腾 IWR + 脚本块回调。
    #

    # 协议枚举用 [System.Security.Authentication.SslProtocols]：.NET Framework 里 SslStream
    # 的协议枚举在这个命名空间；[System.Net.Security.SslProtocols] 是 .NET Core/.NET 5+ 的类型，
    # 在 .NET Framework（PS 5.1）里不存在，现场实测报 "Unable to find type"，故不用。
    $u = [Uri]$Url
    $result = @{ Ok = $false; Status = 0; TlsProtocol = ''; Message = ''; Chain = '' }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.ReceiveTimeout = 10000
        $client.SendTimeout = 10000
        $client.Connect($u.Host, $u.Port)
        $acceptAll = { param($sender, $certificate, $chain, $errors) $true }
        $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $acceptAll)
        try {
            $ssl.AuthenticateAsClient($u.Host, $null, [System.Security.Authentication.SslProtocols]::Tls12, $false)
            $result.TlsProtocol = [string]$ssl.SslProtocol

            $path = $u.PathAndQuery
            $reqText = "GET $path HTTP/1.1`r`nHost: $($u.Host):$($u.Port)`r`nConnection: close`r`n`r`n"
            $reqBytes = [System.Text.Encoding]::ASCII.GetBytes($reqText)
            $ssl.Write($reqBytes, 0, $reqBytes.Length)
            $ssl.Flush()

            # 只读到状态行就够（'HTTP/1.1 200' 至少 12 字节）
            $buf = New-Object byte[] 1024
            $ms = New-Object System.IO.MemoryStream
            while ($ms.Length -lt 64) {
                $n = $ssl.Read($buf, 0, $buf.Length)
                if ($n -le 0) { break }
                $ms.Write($buf, 0, $n)
                if ($ms.Length -ge 12) { break }
            }
            $head = [System.Text.Encoding]::ASCII.GetString($ms.ToArray())
            if ($head -match '^HTTP/\d\.\d\s+(\d{3})') {
                $result.Status = [int]$matches[1]
                $result.Ok = ($result.Status -eq 200)
            } else {
                $result.Message = '无法解析状态行: ' + $head
            }
        } finally {
            $ssl.Dispose()
        }
    } catch {
        $result.Message = [string]$_.Exception.Message
        $result.Chain = Get-ExceptionChainText -Exception $_.Exception
    } finally {
        $client.Close()
    }
    return ,$result
}

function Write-KeycloakProbeHint {
    param([hashtable]$Result, [string]$Url)

    # SslStream 探针已接受任意证书，所以这里的“证书/握手”类失败意味着服务端握手阶段就断了
    $text = [string]$Result.Message + ' ' + [string]$Result.Chain
    $kind = 'other'
    if ($text -match 'actively refused|No connection could be made|积极拒绝') { $kind = 'refused' }
    elseif ($text -match 'timed out|timeout|超时') { $kind = 'timeout' }
    elseif ($text -match 'trust relationship|SSL/TLS|AuthenticationException|证书|安全通道|certificate') { $kind = 'cert' }
    elseif ($text -match 'name or service not known|无法解析|No such host') { $kind = 'dns' }

    if ($Result.Status -gt 0) {
        Write-Line 'FAIL' ('OIDC discovery 返回 HTTP {0}（非 200）: {1}' -f $Result.Status, $Url)
        Write-Line 'INFO' '端点存在但未就绪：核对 realm 名是否为 inalfa、Keycloak 是否启动完成（看 stderr 尾部）。'
    } else {
        switch ($kind) {
            'cert' {
                Write-Line 'FAIL' ('OIDC discovery 失败：证书/握手问题（探针已接受任意证书，仍在握手阶段失败）: ' + $Url)
                Write-Line 'INFO' ('核对 8443 是否真的提供 HTTPS、证书链是否完整；当前证书文件: ' + $CertFile)
            }
            'refused' {
                Write-Line 'FAIL' ('OIDC discovery 失败：连接被拒绝，8443 上没有服务在监听: ' + $Url)
                Write-Line 'INFO' '确认 Keycloak 服务为 Running，且配置的 https-port 是 8443；看 stderr 日志首屏。'
            }
            'timeout' {
                Write-Line 'FAIL' ('OIDC discovery 失败：连接超时: ' + $Url)
                Write-Line 'INFO' '多为防火墙/安全软件拦截本机回环，或 Keycloak 尚未启动完成；先在浏览器打开同地址确认。'
            }
            'dns' {
                Write-Line 'FAIL' ('OIDC discovery 失败：主机名解析失败: ' + $Url)
                Write-Line 'INFO' '本探针用 127.0.0.1，不应出现解析问题；检查 hosts 是否被改写。'
            }
            default {
                Write-Line 'FAIL' ('OIDC discovery 失败: {0}（{1}）' -f $Url, $Result.Message)
                Write-Line 'INFO' '服务可能刚启动、依赖（数据库/网络）不可用，或被代理拦截；先看 stderr 日志尾部。'
            }
        }
    }
    if ([string]$Result.Chain -ne '') {
        Write-Line 'INFO' ('异常链: ' + $Result.Chain)
    }
    $script:ExitCode = 1
}

function Write-KeycloakMgmtHealth {
    $url = 'http://127.0.0.1:{0}/health/ready' -f $KeycloakMgmtPort

    # 管理口只作参考：现场实测 9000 可建立 TCP 但零字节关闭，不影响登录，因此永远不计入失败
    try {
        $status = Invoke-HttpProbeOnce -Url $url -TimeoutSec 5
        Write-Line 'OK' ('管理口健康端点: {0}（HTTP {1}）' -f $url, $status)
    } catch {
        Write-Line 'WARN' ('管理口未暴露健康端点（TCP 可连但零字节关闭），不影响登录，可忽略: {0}' -f $url)
    }
}

function Invoke-Probe {
    param([pscustomobject]$Spec)

    if ($SkipProbe) {
        Write-Line 'INFO' '已跳过后端探测（-SkipProbe）'
        return
    }
    # 候选探测地址：Capacity 配了多个（健康端点不固定），其余应用只有一个 ProbeUrl
    $candidates = @($Spec.ProbeUrls | Where-Object { [string]$_ -ne '' })
    if ($candidates.Count -eq 0 -and $Spec.ProbeUrl -ne '') { $candidates = @($Spec.ProbeUrl) }
    if ($candidates.Count -eq 0) {
        Write-Line 'INFO' '该应用未配置探测地址'
        return
    }

    if ($Spec.Key -eq 'Keycloak') {
        # 主判据：OIDC discovery —— MSIA/BOL/Capacity 登录真正依赖的端点
        # 只走 SslStream：PS 5.1 下用 scriptblock 跳过证书校验会在握手线程上抛
        # "no Runspace available"，IWR 那条路必失败且每次要等满超时，故不再尝试
        #
        # 地址优先用对外域名：hostname-strict=true 时用 127.0.0.1 作 Host 会被 403。
        # SslStream 的 AuthenticateAsClient($u.Host, ...) 会把 $u.Host 当 SNI，请求头也用它作 Host，
        # 因此按域名探就是"带正确 SNI/Host"。域名不通（切换完成前仍绑旧 IP、或 DNS 未就绪）时
        # 回退到 Spec.ProbeUrl（127.0.0.1）继续判定，并明确提示这属于切换前的预期状态。
        $targets = @()
        if ($KeycloakProbeHost -ne '') {
            $targets += ('https://{0}:{1}/realms/{2}/.well-known/openid-configuration' -f $KeycloakProbeHost, $KeycloakHttpsPort, $KeycloakRealm)
        }
        if ($targets.Count -eq 0 -or $targets[$targets.Count - 1] -ne $Spec.ProbeUrl) {
            $targets += $Spec.ProbeUrl
        }

        $goodUrl = ''
        $goodResult = $null
        for ($t = 0; $t -lt $targets.Count; $t++) {
            $target = $targets[$t]
            $fb = $null
            for ($i = 1; $i -le 3; $i++) {
                $fbArr = @(Get-KeycloakDiscoveryViaSslStream -Url $target)
                $fb = $fbArr[$fbArr.Count - 1]
                if ($fb.Ok) { break }
                if ($i -lt 3) { Start-Sleep -Seconds 2 }
            }
            if ($fb.Ok) {
                $goodUrl = $target
                $goodResult = $fb
                break
            }
            if ($t -lt ($targets.Count - 1)) {
                Write-Line 'INFO' ('按 {0} 探测失败（{1}），回退到 {2} 继续；证书/域名切换完成前这属于预期。' -f $target, $fb.Message, $targets[$t + 1])
            } else {
                Write-KeycloakProbeHint -Result $fb -Url $target
            }
        }
        if ($null -ne $goodResult) {
            Write-Line 'OK' ('OIDC discovery 可达: {0}（HTTP {1}，协商协议 {2}）' -f $goodUrl, $goodResult.Status, $goodResult.TlsProtocol)
            if ($goodUrl -ne $targets[0]) {
                Write-Line 'WARN' ('对外域名 {0} 尚不可达，本次判定用的是本机回环地址；证书/域名切换完成后这一行应消失。' -f ('https://{0}:{1}' -f $KeycloakProbeHost, $KeycloakHttpsPort))
            }
        }

        Write-KeycloakMgmtHealth
        return
    }

    # 单地址应用保持原样（10 次、间隔 2 秒）；多候选应用每个地址最多 3 次，避免总耗时过长
    $attempts = 10
    if ($candidates.Count -gt 1) { $attempts = 3 }
    foreach ($target in $candidates) {
        for ($i = 1; $i -le $attempts; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri $target -UseBasicParsing -TimeoutSec 5
                Write-Line 'OK' ('接口可访问: {0}（HTTP {1}）' -f $target, [int]$resp.StatusCode)
                return
            } catch {
                if ($i -lt $attempts) { Start-Sleep -Seconds 2 }
            }
        }
    }
    Write-Line 'FAIL' ('接口无响应，已试: ' + ($candidates -join '、'))
    Write-Line 'INFO' '服务可能刚启动、依赖（数据库/网络）不可用，或被代理拦截。先看 stderr 日志尾部。'
    $script:ExitCode = 1
}

function Invoke-Verify {
    Write-Section '校验服务'

    if ($script:Nssm -eq '') { $null = Find-Nssm }

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Assert-True $false ('服务已注册: ' + $spec.ServiceName) '未找到服务，先 -Action Register。'
            continue
        }

        Assert-True ([string]$svc.Status -eq 'Running') ('服务状态 Running（实际 {0}）' -f [string]$svc.Status) '执行 -Action Start；启动即停先看 stderr 首屏。'
        Assert-True ([string]$svc.StartType -eq 'Automatic') ('启动类型 Automatic（实际 {0}）' -f [string]$svc.StartType) 'nssm set <服务名> Start SERVICE_AUTO_START'

        foreach ($port in $spec.Ports) {
            Assert-True (Test-PortListening -LocalPort $port) ('端口 {0} 处于 LISTENING' -f $port) ('端口 {0} 无监听：核对应用自身监听端口配置。' -f $port)
        }

        # 环境变量
        $lines = Get-ServiceEnvLines -ServiceName $spec.ServiceName
        foreach ($need in $spec.RequiredEnv) {
            $hit = @($lines | Where-Object { $_ -match ('^\s*{0}\s*=' -f [regex]::Escape($need)) })
            Assert-True ($hit.Count -gt 0) ('环境变量已配置: ' + $need) ('AppEnvironmentExtra 里缺少 {0}。' -f $need)
        }
        $placeholders = @($lines | Where-Object { $_ -match '=CHANGE_ME_' })
        Assert-True ($placeholders.Count -eq 0) '无 CHANGE_ME 占位残留' '用 -Action SetEnv -SecretMode Prompt 填写。'

        if (@($spec.RequiredEnv) -contains 'SSL_CERT_FILE') {
            $sslLine = @($lines | Where-Object { $_ -match '^\s*SSL_CERT_FILE\s*=' })
            if ($sslLine.Count -gt 0) {
                $sslPath = (($sslLine[0] -split '=', 2)[1]).Trim()
                Assert-True (Test-Path -LiteralPath $sslPath) ('SSL_CERT_FILE 指向的文件存在: ' + $sslPath) '证书包被移动/换名后必须同步改服务环境变量。'
            }
        }

        # 日志
        $stderr = Join-Path $LogRoot ($spec.ServiceName + '-stderr.log')
        if (Test-Path -LiteralPath $stderr) {
            $tail = ''
            try { $tail = ((Get-Content -LiteralPath $stderr -Tail 200 -ErrorAction SilentlyContinue) -join "`n") } catch { $tail = '' }
            $keys = @('Traceback', 'CERTIFICATE_VERIFY_FAILED', 'SSLError', 'Address already in use', 'WinError 10048', 'ImproperlyConfigured')
            $hits = @($keys | Where-Object { $tail.Contains($_) })
            if ($hits.Count -eq 0) {
                Write-Line 'OK' ('stderr 尾部 200 行无异常关键字（{0}）' -f (Split-Path -Leaf $stderr))
            } else {
                Write-Line 'FAIL' ('stderr 尾部发现: {0}' -f ($hits -join ', '))
                Write-Line 'INFO' ('请打开查看原文（日志可能含敏感信息，脚本不打印内容）: ' + $stderr)
                $script:ExitCode = 1
            }
        } else {
            Write-Line 'WARN' ('stderr 日志不存在: ' + $stderr)
        }

        Invoke-Probe -Spec $spec
    }

    Write-Host ''
    if ($script:ExitCode -eq 0) {
        Write-Section '校验结果: 全部 PASS'
    } else {
        Write-Section '校验结果: 存在 FAIL 项，按上面提示处理'
    }
}

# ============================================================
# SetEnv
# ============================================================

function Invoke-SetEnv {
    Write-Section '更新环境变量（合并语义，不重装服务）'

    Assert-Administrator

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'FAIL' '服务不存在，先 Register'
            $script:ExitCode = 1
            continue
        }

        $updates = Resolve-EnvUpdates -Spec $spec
        if ($updates.Count -eq 0) {
            Write-Line 'INFO' '没有需要更新的变量'
            continue
        }

        $merged = Merge-EnvLines -Existing (Get-ServiceEnvLines -ServiceName $spec.ServiceName) -Updates $updates
        Set-ServiceEnvLines -ServiceName $spec.ServiceName -Lines $merged
        Write-Line 'OK' ('已更新 {0} 项' -f $updates.Count)
        Show-EnvLines -ServiceName $spec.ServiceName -SecretKeys $spec.SecretKeys

        # 写后回读：从注册表重新取值（不用内存里的 $merged），只原样回显本次更新过的非敏感键，
        # 便于确认落盘值完整、没被折行截断；敏感键照旧不输出，-SecretMode Keep 的语义不变
        $stored = @(Get-ServiceEnvLines -ServiceName $spec.ServiceName)
        $plainKeys = @($updates.Keys | Where-Object { @($spec.SecretKeys) -notcontains [string]$_ })
        if ($plainKeys.Count -gt 0) {
            Write-Line 'INFO' '回读确认（仅非敏感键，原样打印注册表里的值）:'
            foreach ($name in $plainKeys) {
                $hit = @($stored | Where-Object { $_ -match ('^\s*{0}\s*=' -f [regex]::Escape([string]$name)) })
                if ($hit.Count -gt 0) {
                    Write-Host ('        ' + [string]$hit[0]) -ForegroundColor DarkGray
                } else {
                    Write-Line 'WARN' ('回读确认失败：注册表里没有 {0}' -f $name)
                }
            }
        } else {
            Write-Line 'INFO' '本次更新的都是敏感键，按 -SecretMode 不输出回读值。'
        }

        if ([string]$svc.Status -eq 'Running') {
            Write-Line 'WARN' '环境变量只在新进程生效：必须重启服务。'
            Write-Host ('        Restart-Service -Name {0}' -f $spec.ServiceName) -ForegroundColor Yellow
        }
    }
}

# ============================================================
# Dump
# ============================================================

function Invoke-Dump {
    Write-Section '导出服务配置基线'

    if ($script:Nssm -eq '') { Assert-Nssm }

    $dir = Join-Path $RollbackDir ('baseline-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    foreach ($spec in (Get-SelectedSpecs)) {
        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'WARN' ('{0} 未注册，跳过' -f $spec.ServiceName)
            continue
        }

        $file = Join-Path $dir ($spec.ServiceName + '.reg')
        try {
            $text = Invoke-Nssm -Arguments @('dump', $spec.ServiceName)
            [System.IO.File]::WriteAllText($file, $text, (New-Object System.Text.UTF8Encoding($true)))
            Write-Line 'OK' ('已导出: ' + $file)
        } catch {
            Write-Line 'FAIL' ('导出失败: ' + $_.Exception.Message)
            $script:ExitCode = 1
        }

        $infoFile = Join-Path $dir ($spec.ServiceName + '-status.txt')
        $portLines = @()
        foreach ($port in $spec.Ports) {
            $listeners = @(Get-ListenerList -LocalPort $port)
            if ($listeners.Count -eq 0) {
                $portLines += ('{0}: 无监听' -f $port)
            } else {
                foreach ($l in $listeners) { $portLines += ('{0}: PID {1} {2}' -f $port, $l.ProcessId, $l.Path) }
            }
        }
        $statusText = @(
            ('服务: {0}' -f $spec.ServiceName),
            ('状态: {0} / {1}' -f [string]$svc.Status, [string]$svc.StartType),
            ('导出时间: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
            '',
            '端口:'
        ) + $portLines
        [System.IO.File]::WriteAllText($infoFile, ($statusText -join "`r`n"), (New-Object System.Text.UTF8Encoding($true)))
        Write-Line 'OK' ('已导出: ' + $infoFile)
    }

    Write-Host ''
    Write-Line 'WARN' '导出的 .reg 含 AppEnvironmentExtra 明文口令/密钥。请按口令管理要求存放（加密介质或受限 ACL 目录），不要放进代码仓库。'
    Write-Host ('        icacls "{0}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" /grant:r "Administrators:(OI)(CI)F"' -f $dir) -ForegroundColor Yellow
}

# ============================================================
# Unregister
# ============================================================

function Invoke-Unregister {
    Write-Section '卸载服务'

    Assert-Administrator

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0}（{1}）---' -f $spec.Key, $spec.ServiceName)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'INFO' '服务不存在，无需卸载'
            continue
        }

        if (-not $Force) {
            $answer = Read-Host ('输入服务名 {0} 确认卸载（其它输入=跳过）' -f $spec.ServiceName)
            if (([string]$answer).Trim() -ne $spec.ServiceName) {
                Write-Line 'INFO' '已跳过'
                continue
            }
        }

        if ($script:Nssm -eq '') { Assert-Nssm }

        if ([string]$svc.Status -ne 'Stopped') {
            try { Stop-Service -Name $spec.ServiceName -Force } catch { Write-Line 'WARN' ('停止失败: ' + $_.Exception.Message) }
            $deadline = (Get-Date).AddSeconds(40)
            while ((Get-Date) -lt $deadline) {
                $cur = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
                if ($null -eq $cur -or [string]$cur.Status -eq 'Stopped') { break }
                Start-Sleep -Seconds 1
            }
        }

        try {
            Invoke-Nssm -Arguments @('remove', $spec.ServiceName, 'confirm') | Out-Null
        } catch {
            Write-Line 'FAIL' ('删除服务失败: ' + $_.Exception.Message)
            Write-Line 'INFO' '服务可能仍被进程占用：先 taskkill 对应进程，再重试；或 sc.exe delete <服务名>。'
            $script:ExitCode = 1
            continue
        }

        Start-Sleep -Seconds 1
        $after = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        Assert-True ($null -eq $after) ('服务已删除: ' + $spec.ServiceName) '删除后仍可见，通常是有句柄占用，重启后消失。'

        Write-Line 'INFO' ('日志保留在 {0}，未删除' -f $LogRoot)
    }
}

# ============================================================
# ConsoleRollback
# ============================================================

function Get-LauncherBody {
    param([pscustomobject]$Spec)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('# 由 register-services-nssm.ps1 生成，用于服务化回滚到控制台模式。')
    $lines.Add('# 口令在运行时交互输入，不落盘。关闭窗口即停止本应用。')
    $lines.Add('')
    $lines.Add('function Read-Secret {')
    $lines.Add('    param([string]$Name)')
    $lines.Add('    $sec = Read-Host -AsSecureString -Prompt (''输入 '' + $Name)')
    $lines.Add('    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)')
    $lines.Add('    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }')
    $lines.Add('    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }')
    $lines.Add('}')
    $lines.Add('')

    if ($Spec.Key -eq 'Keycloak') {
        $java = ''
        if ($Spec.StaticEnv.Contains('JAVA_HOME')) { $java = [string]$Spec.StaticEnv['JAVA_HOME'] }
        $lines.Add(('$env:JAVA_HOME = ''{0}''' -f $java))
        $lines.Add('$env:KC_DB_PASSWORD = Read-Secret ''KC_DB_PASSWORD''')
        $lines.Add('if ($env:KC_DB_PASSWORD -eq '''') { Write-Host ''KC_DB_PASSWORD 为空，Keycloak 连不上数据库，已中止。'' -ForegroundColor Red; return }')
        $lines.Add('$env:KC_HTTPS_KEY_STORE_PASSWORD = Read-Secret ''KC_HTTPS_KEY_STORE_PASSWORD（未启用 keystore 时直接回车）''')
        $lines.Add('if ($env:KC_HTTPS_KEY_STORE_PASSWORD -eq '''') { Remove-Item Env:\KC_HTTPS_KEY_STORE_PASSWORD }')
        $lines.Add(('Set-Location ''{0}''' -f $Spec.ConsoleWorkDir))
        $lines.Add(('& {0}' -f $Spec.ConsoleCommand))
    } elseif ($Spec.Key -eq 'MSIA') {
        $lines.Add(('$env:SSL_CERT_FILE = ''{0}''' -f $CertFile))
        $lines.Add('$env:JWT_SECRET_KEY = Read-Secret ''JWT_SECRET_KEY（若一直用 config.ini 里的值，直接回车）''')
        $lines.Add('if ($env:JWT_SECRET_KEY -eq '''') { Remove-Item Env:\JWT_SECRET_KEY }')
        $lines.Add(('Set-Location ''{0}''' -f $Spec.ConsoleWorkDir))
        $lines.Add(('& {0}' -f $Spec.ConsoleCommand))
    } else {
        # 只按 spec 声明的静态变量生成：BOL 与 Capacity 都是 SSO 客户端，都会从 StaticEnv 得到
        # SSL_CERT_FILE；不接 SSO 的应用 StaticEnv 为空，这里自然什么都不写，也不会被硬塞变量
        foreach ($name in $Spec.StaticEnv.Keys) {
            $lines.Add(('$env:{0} = ''{1}''' -f $name, [string]$Spec.StaticEnv[$name]))
        }
        foreach ($pair in @($ExtraEnv)) {
            if ($pair -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$' -and $matches[1] -ne 'OIDC_CLIENT_SECRET') {
                $lines.Add(('$env:{0} = ''{1}''' -f $matches[1], $matches[2]))
            }
        }
        $lines.Add(('Set-Location ''{0}''' -f $Spec.ConsoleWorkDir))
        $lines.Add(('& {0}' -f $Spec.ConsoleCommand))
    }

    $lines.Add('')
    $lines.Add('# 退出后本窗口保留，便于查看报错；确认无残留进程再关窗。')
    return $lines
}

function Invoke-ConsoleRollback {
    Write-Section '生成控制台启动器（回滚用）'

    if (-not (Test-Path -LiteralPath $RollbackDir)) {
        New-Item -ItemType Directory -Path $RollbackDir -Force | Out-Null
    }

    foreach ($spec in (Get-SelectedSpecs)) {
        Write-Host ''
        Write-Line 'INFO' ('--- {0} ---' -f $spec.Key)

        $svc = Get-Service -Name $spec.ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $svc) {
            Write-Line 'WARN' ('服务仍存在（{0}）。必须先卸载，否则会与控制台实例抢端口。' -f [string]$svc.Status)
        }

        if ($spec.ConsoleWorkDir -eq '' -or -not (Test-Path -LiteralPath $spec.ConsoleWorkDir)) {
            Write-Line 'FAIL' ('工作目录不存在，无法生成启动器: "{0}"。用 -BolExe / -MsiaExe 指定实际路径后重跑。' -f $spec.ConsoleWorkDir)
            $script:ExitCode = 1
            continue
        }

        $file = Join-Path $RollbackDir ('start-console-' + $spec.Key.ToLower() + '.ps1')
        $body = (Get-LauncherBody -Spec $spec) -join "`r`n"
        [System.IO.File]::WriteAllText($file, $body, (New-Object System.Text.UTF8Encoding($true)))
        Write-Line 'OK' ('已生成: ' + $file)
    }

    Write-Host ''
    Write-Line 'INFO' '回滚顺序：'
    Write-Host '        1) nssm stop <服务名>；确认端口已释放（netstat -ano | findstr :<端口>）'
    Write-Host '        2) .\register-services-nssm.ps1 -Action Unregister -App <应用>'
    Write-Host '        3) 右键“使用 PowerShell 运行”对应 start-console-*.ps1，按提示输入口令'
    Write-Host '        4) 验证端口与接口，再关掉旧窗口前先确认业务已恢复'
}

# ============================================================
# 入口
# ============================================================

Initialize-Specs

Show-ScriptVersion

switch ($Action) {
    'Precheck'        { Invoke-Precheck }
    'Register'        { Invoke-Register }
    'Start'           { Invoke-Start }
    'Stop'            { Invoke-Stop }
    'Status'          { Invoke-Status }
    'Verify'          { Invoke-Verify }
    'SetEnv'          { Invoke-SetEnv }
    'Dump'            { Invoke-Dump }
    'Unregister'      { Invoke-Unregister }
    'ConsoleRollback' { Invoke-ConsoleRollback }
}

exit $script:ExitCode
