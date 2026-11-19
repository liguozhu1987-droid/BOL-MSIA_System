<#
.SYNOPSIS
    MSIA 正式服务化托管：用 NSSM 把 msia_server.exe 注册为 Windows 服务。

.DESCRIPTION
    分段执行，默认只做 install（不自动启动）：
      -Install    注册服务并写入 NSSM 参数（幂等：已存在则拒绝覆盖）
      -Start      启动服务并等待端口就绪
      -Verify     逐项校验服务/端口/接口/日志/环境变量，输出 PASS/FAIL
      -Uninstall  二次确认后卸载服务，并提示回滚到手工模式

    本脚本不修改 MSIA 业务代码，不修改 config.ini，不打印任何密钥/口令。
    环境变量（SSL_CERT_FILE / JWT_SECRET_KEY）不通过命令行传参（引号会被吃掉），
    需在 nssm edit 的 Environment 页手工填写；脚本只检测缺失并给出应填内容。

.PARAMETER ServiceName
    Windows 服务名，默认 MSIA-Server。

.PARAMETER ExePath
    主程序路径，默认 C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe。

.PARAMETER LogDirectory
    标准输出/错误日志目录，默认 <部署目录>\logs。目录不存在时自动创建。

.PARAMETER ConfigPath
    指定 config.ini 路径。为空时按程序查找顺序自动定位（exe 目录 > _internal > 当前目录 > backend）。

.PARAMETER Port
    监听端口，默认 8078。仅用于占用检查与接口校验，不写入任何配置。

.PARAMETER ExpectedClientId
    校验时期望的 OIDC client_id，默认 msia-prod。

.PARAMETER ExpectedCertFile
    SSL_CERT_FILE 应指向的证书文件，默认 C:\keycloak\conf\server.crt.pem。

.PARAMETER MinJwtSecretBytes
    JWT_SECRET_KEY 最小字节数，默认 64。

.PARAMETER DependOnService
    可选的服务依赖（例如 Keycloak 的 NSSM 服务名）。为空则不设置依赖，脚本不硬编码任何 Keycloak 服务名。

.PARAMETER Backend
    后端方式。nssm（默认）= 用 NSSM 托管；sc = 不用 NSSM，生成 start-msia.cmd 包装脚本 +
    sc.exe create/failure/start。现场 nssm 不在 PATH 且找不到时用 sc 降级。

.EXAMPLE
    .\install-msia-service.ps1
    只注册服务，不启动。

.EXAMPLE
    .\install-msia-service.ps1 -Install -Start -Verify
    注册、启动并校验。

.EXAMPLE
    .\install-msia-service.ps1 -Verify
    只做只读校验。

.EXAMPLE
    .\install-msia-service.ps1 -Uninstall
    二次确认后卸载服务。

.EXAMPLE
    .\install-msia-service.ps1 -Install -Backend sc
    nssm 不在 PATH 且找不到时的降级方案：生成 start-msia.cmd 并用 sc.exe 注册。

.NOTES
    文件: 统一身份认证实施/scripts/install-msia-service.ps1
    兼容: Windows PowerShell 5.1（不使用 PS7 专有语法）
    权限: install / start / uninstall 需管理员
    退出码: 0=全部通过 1=存在失败项
#>
[CmdletBinding()]
param(
    [string]$ServiceName = 'MSIA-Server',
    [string]$ExePath = 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\msia_server.exe',
    [string]$LogDirectory = 'C:\ApplicationFile\ExecuteProgram\msia_sever\msia_server\logs',
    [string]$ConfigPath = '',
    [int]$Port = 8078,
    [string]$ExpectedClientId = 'msia-prod',
    [string]$ExpectedCertFile = 'C:\keycloak\conf\server.crt.pem',
    [int]$MinJwtSecretBytes = 64,
    [string]$DependOnService = '',
    [ValidateSet('nssm', 'sc')]
    [string]$Backend = 'nssm',

    [switch]$Install,
    [switch]$Start,
    [switch]$Verify,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ServiceName = $ServiceName
$script:ExePath = $ExePath
$script:ExeDir = Split-Path -Parent $ExePath
$script:LogDirectory = $LogDirectory
$script:ConfigPath = $ConfigPath
$script:Port = $Port
$script:ExpectedClientId = $ExpectedClientId
$script:ExpectedCertFile = $ExpectedCertFile
$script:MinJwtSecretBytes = $MinJwtSecretBytes
$script:DependOnService = $DependOnService
$script:StdoutLog = Join-Path $LogDirectory 'msia-stdout.log'
$script:StderrLog = Join-Path $LogDirectory 'msia-stderr.log'
$script:Backend = $Backend
$script:WrapperPath = Join-Path $script:ExeDir 'start-msia.cmd'
$script:JwtPlaceholder = '__REPLACE_WITH_64_BYTE_SECRET__'
$script:NSSM = ''
$script:EnvCache = $null
$script:ExitCode = 0

# ============================================================
# 输出与断言
# ============================================================

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
    Write-Host ('=' * 66) -ForegroundColor DarkGray
    Write-Host (' ' + $Title) -ForegroundColor White
    Write-Host ('=' * 66) -ForegroundColor DarkGray
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message,
        [string]$FailureHint = ''
    )

    if ($Condition) {
        Write-Line 'OK' $Message
    } else {
        Write-Line 'FAIL' $Message
        if ($FailureHint -ne '') {
            Write-Line 'INFO' $FailureHint
        }
        $script:ExitCode = 1
    }
}

function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Administrator {
    if (-not (Test-Administrator)) {
        throw '当前不是管理员 PowerShell。注册/启动/删除 Windows 服务必须右键"以管理员身份运行"。'
    }
    Write-Line 'OK' '管理员权限检查通过'
}

# ============================================================
# 配置定位与读取
# ============================================================

function Get-ConfigCandidates {
    return @(
        @{ Path = (Join-Path $script:ExeDir 'config.ini'); Source = 'exe 目录（程序查找顺序第 1 位）' },
        @{ Path = (Join-Path $script:ExeDir '_internal\config.ini'); Source = '_internal（第 2 位）' },
        @{ Path = (Join-Path (Get-Location).Path 'config.ini'); Source = '当前工作目录（第 3 位，服务化后由 AppDirectory 决定）' },
        @{ Path = (Join-Path $script:ExeDir 'backend\config.ini'); Source = 'backend（第 4 位）' }
    )
}

function Initialize-ConfigPath {
    if ($script:ConfigPath -ne '' -and (Test-Path -LiteralPath $script:ConfigPath)) {
        return
    }
    if ($script:ConfigPath -ne '') {
        return
    }

    $candidates = Get-ConfigCandidates
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c.Path) {
            $script:ConfigPath = $c.Path
            return
        }
    }
}

function Read-IniValue {
    param(
        [string]$IniPath,
        [string]$Section,
        [string]$Key
    )

    if ($IniPath -eq '' -or -not (Test-Path -LiteralPath $IniPath)) {
        return ''
    }

    $bytes = [System.IO.File]::ReadAllBytes($IniPath)
    $text = ''
    try {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    } catch {
        $text = ''
    }
    # UTF-8 解码失败（含替换字符）时按 GBK 再试，兼容现场 ANSI 保存的 config.ini
    if ($text.Contains([string][char]0xFFFD)) {
        try {
            $text = [System.Text.Encoding]::GetEncoding(936).GetString($bytes)
        } catch {
            # 保持 UTF-8 结果
        }
    }
    $text = $text.TrimStart([char]0xFEFF)

    $inSection = $false
    foreach ($rawLine in ($text -split '\r?\n')) {
        $line = $rawLine.Trim()
        if ($line -eq '') { continue }
        if ($line.StartsWith(';')) { continue }
        if ($line.StartsWith('#')) { continue }
        if ($line -match '^\[(.+)\]$') {
            $inSection = ($matches[1].Trim().ToLower() -eq $Section.ToLower())
            continue
        }
        if ($inSection -and $line -match '^([^=]+)=(.*)$') {
            if ($matches[1].Trim().ToLower() -eq $Key.ToLower()) {
                return $matches[2].Trim()
            }
        }
    }
    return ''
}

# ============================================================
# NSSM 自动发现
# ============================================================

function Get-NssmFromServicePathName {
    param([string]$PathName)

    if ($PathName -eq '') { return '' }
    $text = $PathName.Trim()

    # PathName 形如 "C:\...\nssm.exe" "ServiceName" 或 C:\...\nssm.exe ServiceName
    if ($text.StartsWith('"')) {
        $second = $text.IndexOf('"', 1)
        if ($second -gt 1) {
            $candidate = $text.Substring(1, $second - 1)
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
        return ''
    }

    $match = [regex]::Match($text, '^(.+?nssm\.exe)\b', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($match.Success) {
        $candidate = $match.Groups[1].Value.Trim()
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return ''
}

function Find-NssmExecutable {
    if ($script:NSSM -ne '' -and (Test-Path -LiteralPath $script:NSSM)) {
        return $script:NSSM
    }

    # a) PATH
    $cmd = Get-Command 'nssm' -ErrorAction SilentlyContinue
    if ($null -ne $cmd -and $cmd.Source -ne '') {
        $script:NSSM = $cmd.Source
        Write-Line 'OK' ('nssm 来源: PATH → ' + $script:NSSM)
        return $script:NSSM
    }

    # b) 从已注册服务反查（Keycloak 等既有 NSSM 服务）
    try {
        $nssmServices = @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {
                $_.PathName -and ($_.PathName -like '*nssm*')
            })
        foreach ($svc in $nssmServices) {
            $candidate = Get-NssmFromServicePathName -PathName ([string]$svc.PathName)
            if ($candidate -ne '') {
                $script:NSSM = $candidate
                Write-Line 'OK' ('nssm 来源: 服务 {0} 的 PathName → {1}' -f $svc.Name, $script:NSSM)
                return $script:NSSM
            }
        }
    } catch {
        Write-Line 'INFO' ('反查已注册服务失败（不影响后续扫描）: ' + $_.Exception.Message)
    }

    # c) 常见目录扫描（无权限/不存在静默跳过）
    $roots = @(
        'C:\nssm',
        'C:\nssm\win64',
        'C:\Tools',
        'C:\keycloak',
        'C:\Program Files',
        'C:\ProgramData\chocolatey\bin'
    )
    $scanStart = Get-Date
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        if (((Get-Date) - $scanStart).TotalSeconds -gt 60) {
            Write-Line 'INFO' '目录扫描已超过 60 秒，跳过剩余目录。'
            break
        }
        try {
            $found = @(Get-ChildItem -LiteralPath $root -Filter 'nssm.exe' -Recurse -File -ErrorAction SilentlyContinue |
                    Select-Object -First 1)
            if ($found.Count -gt 0) {
                $script:NSSM = $found[0].FullName
                Write-Line 'OK' ('nssm 来源: 目录扫描 → ' + $script:NSSM)
                return $script:NSSM
            }
        } catch {
            # 目录无权限或扫描中断，继续下一个
        }
    }

    return ''
}

function Assert-Nssm {
    $found = Find-NssmExecutable
    if ($found -eq '') {
        $script:NSSM = ''
        throw '未找到 nssm.exe（已检查 PATH、已注册服务的 PathName、C:\nssm / C:\Tools / C:\keycloak / C:\Program Files / Chocolatey）。请改用 -Backend sc 走 sc.exe 降级方案，或安装 NSSM 后重跑。'
    }
    $script:NSSM = $found
    Write-Line 'OK' ('nssm 可用: ' + $script:NSSM)
}

function Get-WrapperEnvEntries {
    $table = @{}
    if (-not (Test-Path -LiteralPath $script:WrapperPath)) {
        return $table
    }
    try {
        $lines = @(Get-Content -LiteralPath $script:WrapperPath -Encoding UTF8 -ErrorAction Stop)
    } catch {
        return $table
    }
    foreach ($line in $lines) {
        $text = ([string]$line).Trim()
        if ($text -match '^set\s+"?([A-Za-z_][A-Za-z0-9_]*)=') {
            if ($text -match '^set\s+"([A-Za-z_][A-Za-z0-9_]*)=(.*)"$') {
                $table[$matches[1]] = $matches[2]
            } elseif ($text -match '^set\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
                $table[$matches[1]] = $matches[2].Trim()
            }
        }
    }
    return $table
}

function Get-ServiceEnvEntries {
    if ($null -ne $script:EnvCache) {
        return $script:EnvCache
    }

    $table = @{}

    if ($script:Backend -eq 'sc') {
        $table = Get-WrapperEnvEntries
        $script:EnvCache = $table
        return $table
    }

    if ($script:NSSM -eq '') {
        $script:EnvCache = $table
        return $table
    }

    $raw = @()
    try {
        $raw = @(& $script:NSSM get $script:ServiceName AppEnvironmentExtra 2>$null)
        if ($LASTEXITCODE -ne 0) {
            $raw = @()
        }
    } catch {
        $raw = @()
    }

    $joined = (@($raw) -join "`n")
    foreach ($line in ($joined -split '[\r\n]+')) {
        $text = ([string]$line).Trim()
        if ($text -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $table[$matches[1]] = $matches[2].Trim()
        }
    }

    $script:EnvCache = $table
    return $table
}

function Get-EffectiveEnvValue {
    param([string]$Key)

    $entries = Get-ServiceEnvEntries
    if ($entries.ContainsKey($Key)) {
        $source = 'NSSM AppEnvironmentExtra'
        if ($script:Backend -eq 'sc') {
            $source = 'start-msia.cmd'
        }
        return [pscustomobject]@{
            Value  = [string]$entries[$Key]
            Source = $source
        }
    }

    $machineValue = [Environment]::GetEnvironmentVariable($Key, 'Machine')
    if ($null -ne $machineValue -and ([string]$machineValue).Trim() -ne '') {
        return [pscustomobject]@{
            Value  = ([string]$machineValue).Trim()
            Source = '系统环境变量 (Machine)'
        }
    }

    return $null
}

# ============================================================
# 进程与端口
# ============================================================

function Get-ProcessDetail {
    param([int]$ProcessId)

    $path = ''
    $startTime = ''
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        try { $path = [string]$proc.Path } catch { $path = '' }
        try { $startTime = $proc.StartTime.ToString('yyyy-MM-dd HH:mm:ss') } catch { $startTime = '' }
    }

    return [pscustomobject]@{
        ProcessId = $ProcessId
        Path      = $path
        StartTime = $startTime
    }
}

function Get-PortListeners {
    param([int]$LocalPort)

    $results = @()
    $seen = @{}

    try {
        $conns = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop
        foreach ($conn in @($conns)) {
            if ($seen.ContainsKey([string]$conn.OwningProcess)) { continue }
            $seen[[string]$conn.OwningProcess] = $true
            $detail = Get-ProcessDetail -ProcessId ([int]$conn.OwningProcess)
            $results += [pscustomobject]@{
                ProcessId    = $detail.ProcessId
                Path         = $detail.Path
                StartTime    = $detail.StartTime
                LocalAddress = [string]$conn.LocalAddress
            }
        }
        return $results
    } catch {
        # 回退 netstat，兼容 Get-NetTCPConnection 不可用的环境
    }

    $lines = @(& netstat.exe -ano 2>$null)
    foreach ($line in $lines) {
        if ($line -match '^\s*TCP\s+(\S+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
            $localAddress = $matches[1]
            $pidText = $matches[2]
            if ($localAddress -notmatch (':' + $LocalPort + '$')) { continue }
            if ($seen.ContainsKey($pidText)) { continue }
            $seen[$pidText] = $true
            $detail = Get-ProcessDetail -ProcessId ([int]$pidText)
            $results += [pscustomobject]@{
                ProcessId    = $detail.ProcessId
                Path         = $detail.Path
                StartTime    = $detail.StartTime
                LocalAddress = $localAddress
            }
        }
    }
    return $results
}

function Show-PortListeners {
    param([object[]]$Listeners)

    foreach ($listener in $Listeners) {
        $pathText = $listener.Path
        if ($pathText -eq '') { $pathText = '（无法读取，可能为受保护进程）' }
        Write-Line 'INFO' ('PID={0}  Local={1}  Path={2}  StartTime={3}' -f $listener.ProcessId, $listener.LocalAddress, $pathText, $listener.StartTime)
    }
}

# ============================================================
# 前置检查
# ============================================================

function Assert-Executable {
    if (-not (Test-Path -LiteralPath $script:ExePath)) {
        throw ('主程序不存在: {0}（请用 -ExePath 指定实际路径）' -f $script:ExePath)
    }
    $item = Get-Item -LiteralPath $script:ExePath
    Write-Line 'OK' ('主程序存在: {0}（{1:N0} 字节，修改时间 {2:yyyy-MM-dd HH:mm:ss}）' -f $item.FullName, $item.Length, $item.LastWriteTime)
}

function Assert-ConfigFile {
    if ($script:ConfigPath -ne '') {
        if (-not (Test-Path -LiteralPath $script:ConfigPath)) {
            throw ('指定的配置文件不存在: {0}' -f $script:ConfigPath)
        }
        Write-Line 'OK' ('使用指定配置: ' + $script:ConfigPath)
        return
    }

    $candidates = Get-ConfigCandidates
    $existing = @()
    $found = $null
    $seen = @{}

    foreach ($c in $candidates) {
        $key = $c.Path.ToLower()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-Path -LiteralPath $c.Path) {
            $existing += $c
            if ($null -eq $found) { $found = $c }
        }
    }

    if ($null -eq $found) {
        throw ('找不到 config.ini（已按顺序检查 exe 目录、_internal、当前目录、backend）。程序启动会因缺少 DATABASE_URL 失败，请先从备份恢复。')
    }

    $script:ConfigPath = $found.Path
    Write-Line 'OK' ('生效配置: {0}（{1}）' -f $found.Path, $found.Source)

    if ($existing.Count -gt 1) {
        foreach ($c in $existing) {
            Write-Line 'INFO' ('同时存在: {0}（{1}）' -f $c.Path, $c.Source)
        }
        Write-Line 'WARN' '存在多份 config.ini，程序只读第一份；请确认内容一致或只保留一份。'
    }
}

function Assert-LogDirectory {
    if (-not (Test-Path -LiteralPath $script:LogDirectory)) {
        try {
            New-Item -ItemType Directory -Path $script:LogDirectory -Force | Out-Null
        } catch {
            throw ('日志目录不存在且创建失败: {0}（{1}）' -f $script:LogDirectory, $_.Exception.Message)
        }
        Write-Line 'INFO' ('已创建日志目录: ' + $script:LogDirectory)
    }

    $probe = Join-Path $script:LogDirectory ('.write_probe_' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        Set-Content -LiteralPath $probe -Value 'probe' -Encoding ASCII
        Remove-Item -LiteralPath $probe -Force
    } catch {
        throw ('日志目录不可写: {0}（{1}）。服务账户将无法写日志，请调整 NTFS 权限。' -f $script:LogDirectory, $_.Exception.Message)
    }
    Write-Line 'OK' ('日志目录可写: ' + $script:LogDirectory)
}

function Assert-PortFree {
    $listeners = @(Get-PortListeners -LocalPort $script:Port)
    if ($listeners.Count -gt 0) {
        Write-Line 'FAIL' ('端口 {0} 已被占用，安装/启动会失败：' -f $script:Port)
        Show-PortListeners -Listeners $listeners
        Write-Line 'INFO' '请先确认上面进程是不是手工打开的 msia_server.exe：是则关闭该窗口/结束进程；不是则改用 -Port 或改 config.ini [server] port，二者必须一致。'
        throw ('端口 {0} 已被占用。' -f $script:Port)
    }
    Write-Line 'OK' ('端口 {0} 当前空闲' -f $script:Port)
}

# ============================================================
# 环境变量检查
# ============================================================

function Test-RequiredEnvironment {
    param([switch]$Strict)

    $needManual = $false
    $envOwner = 'AppEnvironmentExtra'
    if ($script:Backend -eq 'sc') {
        $envOwner = 'start-msia.cmd'
    }

    # ---- SSL_CERT_FILE ----
    $ssl = Get-EffectiveEnvValue 'SSL_CERT_FILE'
    if ($null -eq $ssl) {
        if ($Strict) {
            Assert-True $false 'SSL_CERT_FILE 已配置' ($envOwner + ' 与系统环境变量都没有该值；OIDC 访问 Keycloak 会报证书校验失败。')
        } else {
            Write-Line 'WARN' ($envOwner + ' 与系统环境变量均未设置 SSL_CERT_FILE。')
            $needManual = $true
        }
    } else {
        $certExists = Test-Path -LiteralPath $ssl.Value
        if ($certExists) {
            Write-Line 'OK' ('SSL_CERT_FILE 已配置（来源: {0}）: {1}' -f $ssl.Source, $ssl.Value)
        } else {
            Write-Line 'FAIL' ('SSL_CERT_FILE 指向的文件不存在: {0}（来源: {1}）' -f $ssl.Value, $ssl.Source)
            Write-Line 'INFO' ('应指向包含企业根 CA 的 PEM，例如: ' + $script:ExpectedCertFile)
            $script:ExitCode = 1
        }
    }

    # ---- JWT_SECRET_KEY ----
    $jwt = Get-EffectiveEnvValue 'JWT_SECRET_KEY'
    $jwtValue = ''
    $jwtSource = ''

    if ($null -ne $jwt) {
        $jwtValue = $jwt.Value
        $jwtSource = $jwt.Source
    } else {
        $jwtValue = Read-IniValue $script:ConfigPath 'security' 'jwt_secret_key'
        $jwtSource = 'config.ini [security]（未设置环境变量，运行时回退此值）'
        Write-Line 'WARN' ($envOwner + ' 与系统环境变量均未设置 JWT_SECRET_KEY。')
        $needManual = $true
    }

    if ($jwtValue -eq '') {
        Write-Line 'FAIL' 'JWT_SECRET_KEY 既无环境变量值，config.ini 里也为空。'
        Write-Line 'INFO' ('请把长度不少于 {0} 字节的随机字符串写入 {1}。' -f $script:MinJwtSecretBytes, $envOwner)
        $script:ExitCode = 1
    } else {
        $jwtBytes = [System.Text.Encoding]::UTF8.GetByteCount($jwtValue)
        if ($jwtBytes -ge $script:MinJwtSecretBytes) {
            Write-Line 'OK' ('JWT_SECRET_KEY 长度 {0} 字节 ≥ {1} 字节（来源: {2}；值已脱敏）' -f $jwtBytes, $script:MinJwtSecretBytes, $jwtSource)
        } else {
            Write-Line 'FAIL' ('JWT_SECRET_KEY 长度仅 {0} 字节，低于要求 {1} 字节（来源: {2}；值已脱敏）' -f $jwtBytes, $script:MinJwtSecretBytes, $jwtSource)
            if ($script:Backend -eq 'sc') {
                Write-Line 'INFO' '请编辑 start-msia.cmd 里的 set "JWT_SECRET_KEY=..."，替换成 ≥64 字节的随机字符串，然后重启服务。'
            } else {
                Write-Line 'INFO' '当前生效值被环境变量覆盖成了短值。请在 nssm edit 的 Environment 页改成 ≥64 字节的随机字符串。'
            }
            $script:ExitCode = 1
            $needManual = $true
        }
    }

    if ($needManual) {
        Show-ManualEnvInstruction
    }
}

function Show-ManualEnvInstruction {
    Write-Host ''
    if ($script:Backend -eq 'sc') {
        Write-Line 'WARN' '需要人工编辑包装脚本填写环境变量（sc 方案的环境变量以明文存在脚本里）：'
        Write-Host ('        notepad ' + $script:WrapperPath) -ForegroundColor Yellow
        Write-Host '      把下面两行替换为实际值（等号两侧不要加引号、不要加空格）：'
        Write-Host ''
        Write-Host ('        set "SSL_CERT_FILE=' + $script:ExpectedCertFile + '"') -ForegroundColor Yellow
        Write-Host ('        set "JWT_SECRET_KEY=<长度不少于 {0} 字节的随机字符串>"' -f $script:MinJwtSecretBytes) -ForegroundColor Yellow
        Write-Host ''
        Write-Line 'INFO' '编辑后必须重启服务（-Start）才生效。JWT 值请从安全处获取，本脚本不会打印任何密钥。'
        Write-Line 'WARN' '该文件含明文密钥，保存后收紧 ACL：'
        Write-Host ('        icacls "' + $script:WrapperPath + '" /inheritance:r /grant:r "SYSTEM:(R)" /grant:r "Administrators:(F)"') -ForegroundColor Yellow
        return
    }

    Write-Line 'WARN' '需要人工在 NSSM 图形界面填写服务环境变量（不要用命令行传参，引号会被吃掉）：'
    Write-Host '        nssm edit ' -NoNewline -ForegroundColor Yellow
    Write-Host $script:ServiceName -ForegroundColor Yellow
    Write-Host '      切到 Environment 页，新增下面两行（等号两侧不要加引号、不要加空格）：'
    Write-Host ''
    Write-Host ('        SSL_CERT_FILE=' + $script:ExpectedCertFile) -ForegroundColor Yellow
    Write-Host ('        JWT_SECRET_KEY=<长度不少于 {0} 字节的随机字符串>' -f $script:MinJwtSecretBytes) -ForegroundColor Yellow
    Write-Host ''
    Write-Line 'INFO' 'JWT 值请从安全处获取，本脚本不会打印任何密钥。保存后需重启服务（-Start）才生效。'
}

# ============================================================
# install
# ============================================================

function Invoke-Install {
    Write-Section ('安装服务: ' + $script:ServiceName)

    try {
        Assert-Administrator
        Assert-Executable
        Assert-ConfigFile
        Assert-Nssm
        Assert-LogDirectory
        Assert-PortFree

        $existing = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            Write-Line 'FAIL' ('服务 {0} 已存在（状态: {1}，启动类型: {2}）。为避免覆盖现有配置，本次不做任何修改。' -f $script:ServiceName, [string]$existing.Status, [string]$existing.StartType)
            Write-Line 'INFO' '如需重建：先执行 .\install-msia-service.ps1 -Uninstall，再执行 -Install。'
            Write-Line 'INFO' '如只需启动或校验：-Start / -Verify。'
            $script:ExitCode = 1
            return
        }

        $sameExeServices = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
                $_.PathName -and ($_.PathName.ToLower() -like '*msia_server.exe*')
            })
        if ($sameExeServices.Count -gt 0) {
            $names = (@($sameExeServices | ForEach-Object { $_.Name })) -join ', '
            Write-Line 'FAIL' ('已存在指向 msia_server.exe 的服务: {0}。同一 exe 不应注册两个服务（会抢同一端口）。' -f $names)
            Write-Line 'INFO' '请先确认旧服务用途并卸载（或改用旧服务名执行 -Start / -Verify），不要直接覆盖。'
            $script:ExitCode = 1
            return
        }

        Write-Line 'INFO' '正在注册服务...'
        & $script:NSSM install $script:ServiceName $script:ExePath
        if ($LASTEXITCODE -ne 0) {
            throw ('nssm install 失败，退出码 {0}' -f $LASTEXITCODE)
        }

        $params = @(
            @{ Name = 'AppDirectory'; Value = $script:ExeDir },
            @{ Name = 'DisplayName'; Value = 'MSIA 审核管理系统' },
            @{ Name = 'Description'; Value = 'MSIA 审核管理系统后台服务（由 NSSM 托管；请勿手工启动 msia_server.exe）' },
            @{ Name = 'Start'; Value = 'SERVICE_AUTO_START' },
            @{ Name = 'AppStdout'; Value = $script:StdoutLog },
            @{ Name = 'AppStderr'; Value = $script:StderrLog },
            @{ Name = 'AppRotateFiles'; Value = '1' },
            @{ Name = 'AppRotateOnline'; Value = '1' },
            @{ Name = 'AppRotateSeconds'; Value = '86400' },
            @{ Name = 'AppRotateBytes'; Value = '10485760' },
            @{ Name = 'AppStopMethodConsole'; Value = '15000' },
            @{ Name = 'AppThrottle'; Value = '5000' }
        )

        foreach ($p in $params) {
            & $script:NSSM set $script:ServiceName $p.Name $p.Value
            if ($LASTEXITCODE -ne 0) {
                throw ('nssm set {0} 失败，退出码 {1}' -f $p.Name, $LASTEXITCODE)
            }
        }

        & $script:NSSM set $script:ServiceName AppExit Default Restart
        if ($LASTEXITCODE -ne 0) {
            throw ('nssm set AppExit 失败，退出码 {0}' -f $LASTEXITCODE)
        }

        if ($script:DependOnService -ne '') {
            & $script:NSSM set $script:ServiceName DependOnService $script:DependOnService
            if ($LASTEXITCODE -ne 0) {
                throw ('nssm set DependOnService 失败，退出码 {0}' -f $LASTEXITCODE)
            }
            Write-Line 'OK' ('已设置服务依赖: ' + $script:DependOnService)
        }

        Write-Line 'OK' ('服务注册完成: {0}' -f $script:ServiceName)
        Write-Host ''
        Write-Line 'INFO' '回读关键参数（应与下面期望值一致）:'
        $readBack = @(
            @{ Name = 'Application'; Expect = $script:ExePath },
            @{ Name = 'AppDirectory'; Expect = $script:ExeDir },
            @{ Name = 'Start'; Expect = 'SERVICE_AUTO_START' },
            @{ Name = 'AppStdout'; Expect = $script:StdoutLog },
            @{ Name = 'AppStderr'; Expect = $script:StderrLog },
            @{ Name = 'AppExit'; Expect = 'Default Restart' }
        )
        foreach ($r in $readBack) {
            $actual = ''
            try {
                $actual = (@(& $script:NSSM get $script:ServiceName $r.Name 2>$null) -join ' ').Trim()
            } catch {
                $actual = ''
            }
            if ($actual -eq $r.Expect) {
                Write-Host ('        {0} = {1}' -f $r.Name, $actual)
            } else {
                Write-Line 'WARN' ('{0} 回读为 "{1}"，期望 "{2}"' -f $r.Name, $actual, $r.Expect)
            }
        }

        Write-Host ''
        $script:EnvCache = $null
        Test-RequiredEnvironment

        Write-Host ''
        if ($script:ExitCode -eq 0) {
            Write-Line 'OK' '安装阶段完成。服务未自动启动（按设计）。下一步：'
        } else {
            Write-Line 'WARN' '安装阶段完成，但存在上面标 FAIL 的项，先处理再启动。下一步：'
        }
        Write-Host '        1) 按上面提示用 nssm edit 填写环境变量（如已配置可跳过）'
        Write-Host ('       2) .\install-msia-service.ps1 -Start -ServiceName ''{0}''' -f $script:ServiceName)
        Write-Host ('       3) .\install-msia-service.ps1 -Verify -ServiceName ''{0}''' -f $script:ServiceName)
    } catch {
        Write-Line 'FAIL' ('安装中止: ' + $_.Exception.Message)
        Write-Line 'INFO' '若服务已被部分创建，执行 .\install-msia-service.ps1 -Uninstall 清理后重试。'
        $script:ExitCode = 1
    }
}

# ============================================================
# sc 后端（NSSM 不可用时的降级方案）
# ============================================================

function Show-ScBackendLimitations {
    Write-Host ''
    Write-Line 'WARN' 'sc 降级方案有三个短板，必须知晓：'
    Write-Host '        1) 无日志轮转：stdout/stderr 只追加写，需要人工按天清理或归档。'
    Write-Host '        2) sc stop / Stop-Service 可能残留 msia_server 进程（子进程不归 SCM 管），需 taskkill 兜底。'
    Write-Host '        3) 环境变量以明文写在 start-msia.cmd 中，必须收紧 ACL（见下面 icacls 命令）。'
    Write-Host ''
}

function New-ScWrapper {
    if (Test-Path -LiteralPath $script:WrapperPath) {
        Write-Line 'WARN' ('包装脚本已存在，保持原样不覆盖（防止覆盖已填的密钥）: ' + $script:WrapperPath)
        return
    }

    $content = @(
        '@echo off',
        'chcp 65001 >nul',
        'rem MSIA start wrapper generated by install-msia-service.ps1',
        'rem 本文件必须保存为 UTF-8 无 BOM，否则 cmd 读取中文会乱码。',
        ('cd /d "' + $script:ExeDir + '"'),
        ('set "SSL_CERT_FILE=' + $script:ExpectedCertFile + '"'),
        ('set "JWT_SECRET_KEY=' + $script:JwtPlaceholder + '"'),
        ('"' + $script:ExePath + '" >> "' + $script:StdoutLog + '" 2>> "' + $script:StderrLog + '"'),
        ''
    ) -join "`r`n"

    [System.IO.File]::WriteAllText($script:WrapperPath, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Line 'OK' ('已生成包装脚本（UTF-8 无 BOM）: ' + $script:WrapperPath)
    Write-Line 'WARN' '请用记事本打开确认保存编码为 UTF-8（无 BOM）；若改成 ANSI 或 UTF-8 BOM，cmd 可能读错。'
    Write-Line 'WARN' ('该文件含明文密钥，请立即收紧权限: icacls "' + $script:WrapperPath + '" /inheritance:r /grant:r "SYSTEM:(R)" /grant:r "Administrators:(F)"')
}

function Invoke-Install-Sc {
    Write-Section ('安装服务（sc.exe 降级）: ' + $script:ServiceName)

    try {
        Assert-Administrator
        Assert-Executable
        Assert-ConfigFile
        Assert-LogDirectory
        Assert-PortFree

        $existing = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            Write-Line 'FAIL' ('服务 {0} 已存在（状态: {1}，启动类型: {2}）。为避免覆盖现有配置，本次不做任何修改。' -f $script:ServiceName, [string]$existing.Status, [string]$existing.StartType)
            Write-Line 'INFO' '如需重建：先执行 .\install-msia-service.ps1 -Uninstall -Backend sc，再执行 -Install -Backend sc。'
            $script:ExitCode = 1
            return
        }

        $sameExeServices = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object {
                $_.PathName -and ($_.PathName.ToLower() -like '*msia_server.exe*')
            })
        if ($sameExeServices.Count -gt 0) {
            $names = (@($sameExeServices | ForEach-Object { $_.Name })) -join ', '
            Write-Line 'FAIL' ('已存在指向 msia_server.exe 的服务: {0}。同一 exe 不应注册两个服务（会抢同一端口）。' -f $names)
            Write-Line 'INFO' '请先确认旧服务用途并卸载（或改用旧服务名执行 -Start / -Verify），不要直接覆盖。'
            $script:ExitCode = 1
            return
        }

        New-ScWrapper

        # sc.exe 的键值参数要求 "键= 值" 形式且 = 后必须有空格；
        # 路径含空格时 binPath 必须再包一层转义引号，否则 SCM 找不到文件。
        # 通过 cmd.exe /c 执行整行，避免 PowerShell 5.1 对嵌入引号的转义差异。
        $createLine = 'sc.exe create "' + $script:ServiceName + '" binPath= "\"' + $script:WrapperPath + '\"" start= auto DisplayName= "MSIA 审核管理系统"'
        Write-Line 'INFO' ('执行: ' + $createLine)
        & cmd.exe /c $createLine
        if ($LASTEXITCODE -ne 0) {
            throw ('sc.exe create 失败，退出码 {0}。可用 sc.exe qc {1} 查看现状。' -f $LASTEXITCODE, $script:ServiceName)
        }

        $descLine = 'sc.exe description "' + $script:ServiceName + '" "MSIA 审核管理系统后台服务（sc.exe 方案，包装脚本 start-msia.cmd）"'
        & cmd.exe /c $descLine | Out-Null
        $failLine = 'sc.exe failure "' + $script:ServiceName + '" reset= 86400 actions= restart/5000/restart/5000/restart/5000'
        & cmd.exe /c $failLine | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Line 'WARN' ('sc.exe failure 设置失败（退出码 {0}），服务仍可运行但崩溃后不会自动重启。' -f $LASTEXITCODE)
        } else {
            Write-Line 'OK' '已设置失败自动重启: 5 秒后重启，最多 3 次，计数器 86400 秒重置'
        }

        Write-Line 'OK' ('服务注册完成: {0}' -f $script:ServiceName)
        Write-Host ''
        Write-Line 'INFO' '回读服务配置（BINARY_PATH_NAME 应指向 start-msia.cmd）:'
        & sc.exe qc $script:ServiceName

        Show-ScBackendLimitations

        Write-Host ''
        $script:EnvCache = $null
        Test-RequiredEnvironment

        Write-Host ''
        if ($script:ExitCode -eq 0) {
            Write-Line 'OK' '安装阶段完成。服务未自动启动（按设计）。下一步：'
        } else {
            Write-Line 'WARN' '安装阶段完成，但存在上面标 FAIL 的项，先处理再启动。下一步：'
        }
        Write-Host '        1) 编辑 start-msia.cmd，替换 JWT 占位并核对证书路径'
        Write-Host '        2) 按上面的 icacls 命令收紧脚本权限'
        Write-Host ('       3) .\install-msia-service.ps1 -Start -Backend sc -ServiceName ''{0}''' -f $script:ServiceName)
        Write-Host ('       4) .\install-msia-service.ps1 -Verify -Backend sc -ServiceName ''{0}''' -f $script:ServiceName)
    } catch {
        Write-Line 'FAIL' ('安装中止: ' + $_.Exception.Message)
        Write-Line 'INFO' '若服务已被部分创建，执行 .\install-msia-service.ps1 -Uninstall -Backend sc 清理后重试。'
        $script:ExitCode = 1
    }
}

# ============================================================
# start
# ============================================================

function Invoke-Start {
    Write-Section ('启动服务: ' + $script:ServiceName)

    try {
        Assert-Administrator

        $svc = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            throw ('服务 {0} 不存在。请先执行 -Install。' -f $script:ServiceName)
        }

        if ([string]$svc.Status -eq 'Running') {
            Write-Line 'OK' ('服务已在运行: {0}' -f $script:ServiceName)
        } else {
            Assert-Executable
            Assert-PortFree

            if ($script:Backend -eq 'sc') {
                if (-not (Test-Path -LiteralPath $script:WrapperPath)) {
                    throw ('包装脚本不存在: {0}。请先执行 -Install -Backend sc。' -f $script:WrapperPath)
                }
                $script:EnvCache = $null
                $jwt = Get-EffectiveEnvValue 'JWT_SECRET_KEY'
                if ($null -eq $jwt -or $jwt.Value -eq '' -or $jwt.Value -eq $script:JwtPlaceholder) {
                    throw ('start-msia.cmd 里的 JWT_SECRET_KEY 仍是空值或占位符。请先编辑该文件填入 ≥{0} 字节的随机字符串。' -f $script:MinJwtSecretBytes)
                }
                Write-Line 'INFO' '正在用 sc.exe start 启动服务...'
                & sc.exe start $script:ServiceName
                if ($LASTEXITCODE -ne 0) {
                    throw ('sc.exe start 失败，退出码 {0}。' -f $LASTEXITCODE)
                }
            } else {
                Write-Line 'INFO' '正在启动服务...'
                Start-Service -Name $script:ServiceName
            }

            $deadline = (Get-Date).AddSeconds(20)
            $running = $false
            while ((Get-Date) -lt $deadline) {
                $current = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
                if ($null -ne $current -and [string]$current.Status -eq 'Running') {
                    $running = $true
                    break
                }
                Start-Sleep -Seconds 1
            }

            if (-not $running) {
                Write-Line 'FAIL' '服务在 20 秒内未进入 Running。'
                Write-Line 'INFO' ('请查看 stderr 日志: ' + $script:StderrLog)
                Write-Line 'INFO' '常见原因: config.ini 缺 [database]、数据库连不上、端口被占、exe 被杀软拦截。'
                $script:ExitCode = 1
                return
            }
            Write-Line 'OK' ('服务状态: Running')
        }

        $deadline = (Get-Date).AddSeconds(15)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            $listeners = @(Get-PortListeners -LocalPort $script:Port)
            if ($listeners.Count -gt 0) {
                $listening = $true
                break
            }
            Start-Sleep -Seconds 1
        }

        if ($listening) {
            Write-Line 'OK' ('端口 {0} 已进入 LISTENING' -f $script:Port)
            Show-PortListeners -Listeners $listeners
            Write-Line 'INFO' '下一步执行 -Verify 做接口与日志校验。'
        } else {
            Write-Line 'FAIL' ('服务显示 Running，但端口 {0} 无监听。' -f $script:Port)
            Write-Line 'INFO' ('优先核对 config.ini [server] port 是否等于 {0}，再看 stderr 日志: {1}' -f $script:Port, $script:StderrLog)
            $script:ExitCode = 1
        }
    } catch {
        Write-Line 'FAIL' ('启动中止: ' + $_.Exception.Message)
        $script:ExitCode = 1
    }
}

# ============================================================
# verify
# ============================================================

function Invoke-Verify {
    Write-Section ('校验服务: ' + $script:ServiceName)

    $svc = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        Assert-True $false ('服务已注册: ' + $script:ServiceName) '未找到该服务。先执行 -Install，或核对 -ServiceName 是否拼写一致。'
        Write-Line 'INFO' '校验中止：服务不存在，后面的端口/接口检查没有意义。'
        return
    }

    # 1. 服务状态
    Assert-True ([string]$svc.Status -eq 'Running') ('服务状态 Running（实际: {0}）' -f [string]$svc.Status) '服务未运行：执行 -Start；若启动即停，先看 stderr 日志首屏报错。'
    Write-Line 'INFO' ('启动类型: {0}（期望 Automatic）' -f [string]$svc.StartType)

    # 2. 端口监听
    $listeners = @(Get-PortListeners -LocalPort $script:Port)
    Assert-True ($listeners.Count -gt 0) ('端口 {0} 处于 LISTENING' -f $script:Port) ('端口 {0} 无监听：服务可能启动失败，或 config.ini [server] port 不是 {0}。' -f $script:Port)
    if ($listeners.Count -gt 0) {
        Show-PortListeners -Listeners $listeners
        $pathMatched = $false
        foreach ($listener in $listeners) {
            if ($listener.Path -ne '' -and $listener.Path.ToLower() -eq $script:ExePath.ToLower()) {
                $pathMatched = $true
            }
        }
        if ($pathMatched) {
            Write-Line 'OK' '监听进程的可执行文件与 -ExePath 一致'
        } else {
            Write-Line 'WARN' '监听进程路径未匹配 -ExePath：可能手工启动了另一个目录的 exe，或进程路径不可读。'
        }
    }

    # 3. 登录配置接口
    $uri = ('http://127.0.0.1:{0}/api/auth/config' -f $script:Port)
    $cfg = $null
    for ($i = 1; $i -le 10; $i++) {
        try {
            $cfg = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 3
            break
        } catch {
            if ($i -lt 10) { Start-Sleep -Seconds 1 }
        }
    }

    if ($null -eq $cfg) {
        Assert-True $false ('接口可访问: {0}' -f $uri) '接口无响应：服务可能刚启动、数据库连接失败或端口被其它程序占用。先看 stderr 日志尾部。'
    } else {
        Write-Line 'OK' ('接口可访问: {0}' -f $uri)
        $names = @($cfg.PSObject.Properties.Name)

        $enabled = $false
        if ($names -contains 'oidc_enabled') {
            $enabled = ($cfg.oidc_enabled -eq $true)
        }
        Assert-True $enabled ('oidc_enabled=true（实际: {0}）' -f [string]$enabled) 'OIDC 未启用：核对 config.ini [oidc] enabled 与 OIDC_ENABLED 环境变量（环境变量优先）。'
        if ($names -contains 'local_login_enabled') {
            Write-Line 'INFO' ('local_login_enabled={0}（双轨期应为 True）' -f [string]$cfg.local_login_enabled)
        }

        $clientId = ''
        $clientIdSource = ''
        if ($names -contains 'client_id') {
            $clientId = [string]$cfg.client_id
            $clientIdSource = '接口 /api/auth/config'
        }
        if ($clientId -eq '') {
            $envCid = Get-EffectiveEnvValue 'OIDC_CLIENT_ID'
            if ($null -ne $envCid) {
                $clientId = $envCid.Value
                $clientIdSource = $envCid.Source
            }
        }
        if ($clientId -eq '') {
            $clientId = Read-IniValue $script:ConfigPath 'oidc' 'client_id'
            $clientIdSource = 'config.ini [oidc]'
        }
        Write-Line 'INFO' ('client_id={0}（来源: {1}）' -f $clientId, $clientIdSource)
        Write-Line 'INFO' '说明: /api/auth/config 当前只返回两个开关，不含 client_id；client_id 由脚本从生效配置/环境变量读取比对。'
        Assert-True ($clientId -eq $script:ExpectedClientId) ('client_id={0}（期望 {1}）' -f $clientId, $script:ExpectedClientId) '核对 config.ini [oidc] client_id 与 Keycloak 控制台 Clients 里的客户端 ID 是否一致。'
    }

    # 4. stderr 日志尾部
    $stderrFiles = @(Get-ChildItem -LiteralPath $script:LogDirectory -Filter 'msia-stderr*.log' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending)
    if ($stderrFiles.Count -eq 0) {
        Assert-True $false 'stderr 日志文件存在' ('在 {0} 下未找到 msia-stderr*.log：AppStderr 可能未指向日志目录。' -f $script:LogDirectory)
    } else {
        $latest = $stderrFiles[0]
        $text = ''
        try {
            $lines = @(Get-Content -LiteralPath $latest.FullName -Tail 200 -ErrorAction SilentlyContinue)
            $text = $lines -join "`n"
        } catch {
            $text = ''
        }

        $patterns = @('DuplicateSectionError', 'SSLError', 'SSLCertVerificationError', 'CERTIFICATE_VERIFY_FAILED', 'Traceback')
        $hits = @()
        foreach ($p in $patterns) {
            if ($text.Contains($p)) { $hits += $p }
        }

        if ($hits.Count -eq 0) {
            Write-Line 'OK' ('stderr 尾部 200 行未发现异常关键字（{0}）' -f $latest.Name)
        } else {
            Write-Line 'FAIL' ('stderr 尾部发现异常关键字: {0}（{1}）' -f ($hits -join ', '), $latest.Name)
            Write-Line 'INFO' ('请直接打开 {0} 查看原文；日志可能含敏感信息，本脚本不打印内容。' -f $latest.FullName)
            $script:ExitCode = 1
        }
    }

    # 5. 服务环境变量
    $script:EnvCache = $null
    if ($script:Backend -eq 'sc') {
        if (Test-Path -LiteralPath $script:WrapperPath) {
            Write-Line 'OK' ('包装脚本存在: ' + $script:WrapperPath)
        } else {
            Assert-True $false ('包装脚本存在: ' + $script:WrapperPath) 'sc 方案依赖 start-msia.cmd；文件缺失时服务无法启动。'
        }
    } elseif ($script:NSSM -eq '') {
        $null = Find-NssmExecutable
    }
    if (-not (Test-Administrator)) {
        Write-Line 'WARN' '当前非管理员，读取服务环境变量可能失败；建议用管理员 PowerShell 复跑 -Verify。'
    }
    Test-RequiredEnvironment -Strict

    Write-Host ''
    if ($script:ExitCode -eq 0) {
        Write-Section '校验结果: 全部 PASS'
    } else {
        Write-Section '校验结果: 存在 FAIL 项，按上面提示处理'
    }
}

# ============================================================
# uninstall
# ============================================================

function Invoke-Uninstall {
    Write-Section ('卸载服务: ' + $script:ServiceName)

    try {
        $svc = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-Line 'INFO' ('服务 {0} 不存在，无需卸载。' -f $script:ServiceName)
            Show-ManualRollback
            return
        }

        Assert-Administrator

        Write-Line 'WARN' '卸载后 MSIA 不再随开机启动，且不会再写日志文件；业务会中断，直到按手工模式重新启动。'
        $answer = Read-Host ('请输入服务名 {0} 以确认卸载（其它输入将取消）' -f $script:ServiceName)
        if (([string]$answer).Trim() -ne $script:ServiceName) {
            Write-Line 'INFO' '输入不匹配，已取消卸载，未做任何修改。'
            return
        }

        if ($script:Backend -eq 'nssm') {
            Assert-Nssm
        }

        if ([string]$svc.Status -ne 'Stopped') {
            Write-Line 'INFO' '正在停止服务...'
            if ($script:Backend -eq 'sc') {
                & sc.exe stop $script:ServiceName 2>$null | Out-Null
            } else {
                & $script:NSSM stop $script:ServiceName 2>$null | Out-Null
            }
            $deadline = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $deadline) {
                $current = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
                if ($null -ne $current -and [string]$current.Status -eq 'Stopped') { break }
                Start-Sleep -Seconds 1
            }
            $current = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
            if ($null -ne $current -and [string]$current.Status -ne 'Stopped') {
                Write-Line 'WARN' '服务在 15 秒内未停止，继续尝试卸载（可能失败）。'
            }
        }

        if ($script:Backend -eq 'sc') {
            $residual = @(Get-Process -Name 'msia_server' -ErrorAction SilentlyContinue)
            if ($residual.Count -gt 0) {
                Write-Line 'WARN' ('sc stop 后仍残留 msia_server 进程: {0}' -f (($residual | ForEach-Object { $_.Id }) -join ', '))
                Write-Line 'INFO' '需要时用 taskkill 兜底: taskkill /F /IM msia_server.exe'
            }
        }

        Write-Line 'INFO' '正在从服务控制管理器删除...'
        if ($script:Backend -eq 'sc') {
            & sc.exe delete $script:ServiceName 2>$null | Out-Null
        } else {
            & $script:NSSM remove $script:ServiceName confirm 2>$null | Out-Null
        }
        if ($LASTEXITCODE -ne 0) {
            throw ('删除服务失败，退出码 {0}。可先用 -Start 确认服务可停，再重试。' -f $LASTEXITCODE)
        }

        Start-Sleep -Seconds 1
        $after = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $after) {
            Write-Line 'OK' ('服务已删除: ' + $script:ServiceName)
        } else {
            Write-Line 'FAIL' ('服务仍然存在（状态: {0}）。' -f [string]$after.Status)
            $script:ExitCode = 1
        }

        Write-Line 'INFO' ('日志文件保留在 {0}，未删除；如需留档请自行备份。' -f $script:LogDirectory)
        Show-ManualRollback
    } catch {
        Write-Line 'FAIL' ('卸载中止: ' + $_.Exception.Message)
        $script:ExitCode = 1
    }
}

function Show-ManualRollback {
    Write-Host ''
    if ($script:Backend -eq 'sc') {
        Write-Line 'INFO' '回滚到手工模式（sc 方案直接运行包装脚本，关窗即断）：'
        Write-Host ('        ' + $script:WrapperPath)
        Write-Host ''
        Write-Line 'INFO' ('该脚本已含 cd、SSL_CERT_FILE、JWT_SECRET_KEY 与日志重定向；文件不存在时按下面的 PowerShell 方式启动。')
        Write-Host ('        cd ' + $script:ExeDir)
        Write-Host '        $env:SSL_CERT_FILE = ''C:\keycloak\conf\server.crt.pem'''
        Write-Host '        $env:JWT_SECRET_KEY = ''<与原包装脚本相同的 ≥64 字节值>'''
        Write-Host '        .\msia_server.exe'
        Write-Host ''
        Write-Line 'INFO' '注意：先确认服务已删除、8078 无监听，再手工启动，避免两个进程抢同一端口。'
        Write-Line 'INFO' ('start-msia.cmd 未删除，保留在 {0}，其中含明文密钥，注意权限。' -f $script:WrapperPath)
        return
    }

    Write-Line 'INFO' '回滚到手工模式（临时，关窗即断）：'
    Write-Host ('        cd ' + $script:ExeDir)
    Write-Host '        $env:SSL_CERT_FILE = ''C:\keycloak\conf\server.crt.pem'''
    Write-Host '        $env:JWT_SECRET_KEY = ''<与原服务环境变量相同的 ≥64 字节值>'''
    Write-Host '        .\msia_server.exe'
    Write-Host ''
    Write-Line 'INFO' '注意：手工模式没有日志文件、关闭窗口即停止；确认服务确实删除后再启动，避免两个进程抢同一端口。'
}

# ============================================================
# 入口
# ============================================================

Initialize-ConfigPath

if ($Uninstall) {
    Invoke-Uninstall
    exit $script:ExitCode
}

if ($Install -or (-not $Start -and -not $Verify)) {
    if ($script:Backend -eq 'sc') {
        Invoke-Install-Sc
    } else {
        Invoke-Install
    }
}

if ($Start) {
    Invoke-Start
}

if ($Verify) {
    Invoke-Verify
}

exit $script:ExitCode
