<#
.SYNOPSIS
    紧急停号：中央表置停用 → Keycloak 禁用 + 踢会话 → 告警。
.DESCRIPTION
    T01 实施工件（方案文档 7.2 disable_user_now.ps1）。
    用于离职当日/异常账号的紧急处置：
      1. CN_AME_SSO_User.status 置 0（中央表）
      2. Keycloak: GET→改→PUT 整对象 enabled=false + POST logout 踢会话
      3. 写 CN_AME_SSO_SyncLog(phase='KC_EMERGENCY')
      4. 发告警邮件（必须提示"当天通知 IT 从名单移除，否则次日 MERGE 复活"）

    注意: 停号只写中央表与 Keycloak，不改动各系统本地表；
    BOL 侧本地 Token 清理由每小时 sync_sso_status 回写完成（T04）。

.NOTES
    文件: scripts/powershell/disable_user_now.ps1
    执行方式: 手工（管理员 PowerShell）
    示例: .\disable_user_now.ps1 -EmployeeNo 'zhangsan' -Reason '2026-11-05 离职'
    退出码: 0=成功 1=失败
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$EmployeeNo,

    [string]$Reason = '紧急停号（未注明原因）',

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc',
    [string]$KcClientCredentialName = 'keycloak_sync_client',

    [string]$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',
    [string]$Realm = 'inalfa',
    [string]$TokenClientId = 'sync-client',

    [string]$LogDirectory = 'C:\sso\logs',

    [string]$SmtpServer = '172.19.253.10',
    [int]$SmtpPort = 25,
    [string]$AlertFrom = 'sso-notify@inalfa.local',
    [string[]]$AlertTo = @('ligu@inalfa.local'),

    [int]$MaxRetries = 3,
    [int[]]$BackoffSeconds = @(10, 30, 60),

    [switch]$SkipCertCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
# Windows PowerShell 5.1 默认只协商到 TLS 1.0/1.1，而 Keycloak 25 只接受 TLS 1.2+，
# 症状是 "The request was aborted: Could not create SSL/TLS secure channel."（端口通、证书也没问题）。
# 旧版把这一行放在 Invoke-KcApi 的 if ($SkipCertCheck) 里 —— 不跳过证书校验时反而没有启用
# TLS 1.2，等于"最该保护的生产路径"最脆弱。协议协商与证书校验是两件事，必须分开。
# 只显式启用 Tls12：不叠加 Tls13——旧版 Windows Server 的 Schannel 不认这个标志。
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$script:SqlServer = $SqlServer
$script:Database = $Database
$script:LogDirectory = $LogDirectory
$script:LogFile = Join-Path $LogDirectory ("disable_user_now_{0:yyyyMMdd}.log" -f (Get-Date))
$script:KcToken = ''
$script:KcTokenExpiry = (Get-Date).AddMinutes(-1)

# ---------------- 基础函数（与同步脚本保持一致，便于单文件分发） ----------------

function Write-Log {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )
    $line = "{0:yyyy-MM-dd HH:mm:ss} [{1,-5}] {2}" -f (Get-Date), $Level, $Message
    switch ($Level) {
        'WARN'  { Write-Warning $Message }
        'ERROR' { Write-Host $line -ForegroundColor Red }
        default { Write-Host $line }
    }
    try {
        if (-not (Test-Path -LiteralPath $script:LogDirectory)) {
            New-Item -ItemType Directory -Path $script:LogDirectory -Force | Out-Null
        }
        Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
    } catch {
        Write-Warning "写日志文件失败: $_"
    }
}

function Get-SecretFromCredentialFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("凭据文件不存在: {0}。请按 README.md 说明用 DPAPI 生成。" -f $Path)
    }
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $Name))
    if ($null -eq $node) { throw ("凭据文件中找不到条目 '{0}'。" -f $Name) }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    $plain = (New-Object System.Management.Automation.PSCredential(
        ([string]$node.UserName), $secure)).GetNetworkCredential().Password
    return @{ UserName = [string]$node.UserName; Password = $plain }
}

function Get-DbCredential {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("凭据文件不存在: {0}。请按 README.md 说明用 DPAPI 生成。" -f $Path)
    }
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $Name))
    if ($null -eq $node) { throw ("凭据文件中找不到条目 '{0}'。" -f $Name) }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    return New-Object System.Management.Automation.PSCredential(([string]$node.UserName), $secure)
}

function Send-AlertMail {
    param(
        [Parameter(Mandatory)][string]$Subject,
        [Parameter(Mandatory)][string]$Body
    )
    try {
        $msg = New-Object System.Net.Mail.MailMessage
        $msg.From = $AlertFrom
        foreach ($to in $AlertTo) { $msg.To.Add($to) }
        $msg.Subject = $Subject
        $msg.Body = $Body
        $msg.SubjectEncoding = [Text.Encoding]::UTF8
        $msg.BodyEncoding = [Text.Encoding]::UTF8
        $smtp = New-Object System.Net.Mail.SmtpClient($SmtpServer, $SmtpPort)
        $smtp.EnableSsl = $false
        $smtp.Send($msg)
        Write-Log ("告警邮件已发送: {0}" -f $Subject) 'WARN'
    } catch {
        Write-Log ("告警邮件发送失败: {0}" -f $_.Exception.Message) 'ERROR'
    }
}

function Invoke-SsoSql {
    param(
        [Parameter(Mandatory)][string]$Query,
        [hashtable]$Parameters = @{},
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    if (Get-Command -Name Invoke-Sqlcmd -ErrorAction SilentlyContinue) {
        $splat = @{
            ServerInstance = $script:SqlServer
            Database      = $script:Database
            Query         = $Query
            QueryTimeout  = 180
            ErrorAction   = 'Stop'
            Username      = $Credential.UserName
            Password      = $Credential.GetNetworkCredential().Password
        }
        # SqlServer 21.x 的 -Variable 只接受严格的 'name=value' 字符串数组（传 hashtable 会报
        # "The format used to define the new variable ... is invalid"）；且它的占位符是 $(name)，
        # 与本文件所有查询里的 @name 口径不一致（改对格式也会撞 "Must declare the scalar variable"）。
        # 故不用 -Variable，把 @name 就地替换为转义后的字面量。下方 SqlClient 分支仍用真参数。
        if ($Parameters.Count -gt 0) {
            foreach ($k in $Parameters.Keys) {
                $v = $Parameters[$k]
                if ($null -eq $v) {
                    $lit = 'NULL'
                }
                elseif ($v -is [int] -or $v -is [long]) {
                    $lit = [string]$v
                }
                else {
                    $lit = "'" + ([string]$v).Replace("'", "''") + "'"
                }
                # 替换串里的 $ 必须写成 $$，否则会被 [regex]::Replace 当成分组引用
                $rep = $lit.Replace('$', '$$')
                $splat['Query'] = [regex]::Replace(
                    [string]$splat['Query'],
                    ('@' + [regex]::Escape([string]$k) + '\b'),
                    $rep)
            }
        }
        return Invoke-Sqlcmd @splat
    }
    if (-not ('Microsoft.Data.SqlClient.SqlConnection' -as [type])) {
        $dll = Join-Path $PSScriptRoot 'Microsoft.Data.SqlClient.dll'
        if (Test-Path -LiteralPath $dll) { Add-Type -Path $dll -ErrorAction SilentlyContinue }
    }
    if (-not ('Microsoft.Data.SqlClient.SqlConnection' -as [type])) {
        throw '未找到 Invoke-Sqlcmd 且无 Microsoft.Data.SqlClient.dll，无法连接 SQL Server。'
    }
    $connStr = ("Server={0};Database={1};User Id={2};Password={3};TrustServerCertificate=true;Connect Timeout=30" -f
                $script:SqlServer, $script:Database,
                $Credential.UserName, $Credential.GetNetworkCredential().Password)
    $conn = New-Object Microsoft.Data.SqlClient.SqlConnection($connStr)
    try {
        $conn.Open()
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $Query
        $cmd.CommandTimeout = 180
        foreach ($k in $Parameters.Keys) {
            $p = $cmd.CreateParameter()
            $p.ParameterName = $k
            $p.Value = $Parameters[$k]
            [void]$cmd.Parameters.Add($p)
        }
        $reader = $cmd.ExecuteReader()
        $table = New-Object System.Data.DataTable
        $table.Load($reader)
        $reader.Close()
        if ($table.Rows.Count -eq 0) { return $null }
        return @($table.Rows | ForEach-Object {
            $o = [ordered]@{}
            foreach ($c in $table.Columns) { $o[$c.ColumnName] = $_.Item($c.ColumnName) }
            [pscustomobject]$o
        })
    } finally {
        $conn.Dispose()
    }
}

function Write-SyncLog {
    param(
        [Parameter(Mandatory)][string]$Status,
        [string]$Message = '',
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    $q = @"
INSERT INTO dbo.CN_AME_SSO_SyncLog
    (phase, status, message)
VALUES
    ('KC_EMERGENCY', @status, @message)
"@
    # 单引号转义统一由 Invoke-SsoSql 做（H16）；这里预先转义会变成双重转义
    Invoke-SsoSql -Query $q -Parameters @{
        status = $Status; message = $Message
    } -Credential $Credential | Out-Null
}

function Get-Prop {
    <# 安全读属性：对象为 $null、属性缺失、或值为 $null 时返回默认值。
       为什么必须有它：Keycloak 的 JSON 只包含非空字段（没设 lastName 就没有该属性），
       而本脚本启用了 Set-StrictMode -Version Latest —— 裸访问不存在的属性会直接抛
       "The property 'x' cannot be found on this object"（解析期不报错，运行到才炸）。 #>
    param([object]$Object, [Parameter(Mandatory)][string]$Name, [object]$Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name) -and $null -ne $Object[$Name]) { return $Object[$Name] }
        return $Default
    }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p -or $null -eq $p.Value) { return $Default }
    return $p.Value
}

function Set-Prop {
    <# 安全写属性：PSCustomObject 上给"不存在的属性"赋值同样会抛错，必须 Add-Member -Force。 #>
    param([object]$Object, [Parameter(Mandatory)][string]$Name, [object]$Value)
    if ($null -eq $Object) { return }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    } else { $p.Value = $Value }
}

function Get-KcToken {
    $sec = Get-SecretFromCredentialFile -Path $CredentialFile -Name $KcClientCredentialName
    $body = @{
        grant_type = 'client_credentials'
        client_id  = $TokenClientId
        client_secret = $sec.Password
    }
    $resp = Invoke-KcApi -Method Post `
        -Uri "$KeycloakBaseUrl/realms/$Realm/protocol/openid-connect/token" `
        -Body $body -IsTokenRequest
    $script:KcToken = $resp.access_token
    $script:KcTokenExpiry = (Get-Date).AddSeconds([int]$resp.expires_in - 30)
    Write-Log 'Keycloak 管理令牌获取成功' 'INFO'
}

function Invoke-KcApi {
    param(
        [Parameter(Mandatory)][ValidateSet('Get', 'Post', 'Put', 'Delete')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body,
        [switch]$IsTokenRequest
    )
    if ($SkipCertCheck) {
        # 只跳过证书校验；TLS 协议已在脚本启动处无条件启用（2026-11-11 H15）
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
    $headers = @{}
    if (-not $IsTokenRequest) {
        if ($script:KcToken -eq '' -or (Get-Date) -ge $script:KcTokenExpiry) { Get-KcToken }
        $headers['Authorization'] = "Bearer $script:KcToken"
    }
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            $json = $null
            if ($null -ne $Body) { $json = ($Body | ConvertTo-Json -Depth 10 -Compress) }
            $invokeSplat = @{ Method = $Method; Uri = $Uri; Headers = $headers; ErrorAction = 'Stop' }
            if ($null -ne $json) {
                $invokeSplat['Body'] = $json
                $invokeSplat['ContentType'] = 'application/json'
            }
            return Invoke-RestMethod @invokeSplat
        } catch {
            $code = 0; $errBody = ''
            try {
                if ($null -ne $_.Exception.Response) {
                    $code = [int]$_.Exception.Response.StatusCode
                    $stream = $_.Exception.Response.GetResponseStream()
                    if ($null -ne $stream) {
                        $reader = New-Object System.IO.StreamReader($stream)
                        $errBody = $reader.ReadToEnd()
                        $reader.Close()
                    }
                } else { $errBody = $_.Exception.Message }
            } catch { $errBody = '(无法读取错误响应)' }
            $retriable = ($code -eq 0 -or $code -ge 500 -or $code -eq 429)
            if (-not $retriable -or $attempt -ge $MaxRetries) {
                throw ("KC API {0} {1} 失败 (HTTP {2}): {3}" -f $Method, $Uri, $code, $errBody)
            }
            $idx = [math]::Min($attempt - 1, $BackoffSeconds.Count - 1)
            Write-Log ("KC API 失败 (HTTP {0})，{1}s 后重试 ({2}/{3})" -f
$code, $BackoffSeconds[$idx], $attempt, $MaxRetries) 'WARN'
            Start-Sleep -Seconds $BackoffSeconds[$idx]
        }
    }
}

# ---------------- 主流程 ----------------
$cred = $null
$kcSkipped = $false   # KC 段是否被跳过（如用户对象缺 id）；用于把"未完成"显式带到日志与告警
try {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    }
    Write-Log '================ disable_user_now 开始 ================' 'INFO'
    $emp = $EmployeeNo.Trim().ToLower()
    $cred = Get-DbCredential -Path $CredentialFile -Name $SqlCredentialName

    # 1. 中央表置停用
    $u = Invoke-SsoSql -Query @"
SELECT employee_no, login_name, display_name, status FROM dbo.CN_AME_SSO_User
WHERE employee_no = @emp
"@ -Parameters @{ emp = $emp } -Credential $cred
    if ($null -eq $u -or $u.Count -eq 0) {
        throw ("中央人员表中不存在工号 '{0}'，请确认拼写。" -f $emp)
    }
    $loginName = [string]$u[0].login_name
    Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET status = 0, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ emp = $emp } -Credential $cred | Out-Null
    Write-Log ("中央表已置停用: {0} ({1})" -f $emp, $loginName) 'INFO'

    # 2. Keycloak 禁用 + 踢会话
    Get-KcToken
    $found = Invoke-KcApi -Method Get `
        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users?username=$([uri]::EscapeDataString($loginName))&exact=true"
    $kcUser = $null
    if ($null -ne $found) { $arr = @($found); if ($arr.Count -gt 0) { $kcUser = $arr[0] } }
    # JSON 只含非空字段，所有取值走 Get-Prop（StrictMode 下裸访问缺失属性会抛异常）。
    $kcId = [string](Get-Prop $kcUser 'id' '')
    if ($null -eq $kcUser) {
        Write-Log ("Keycloak 中不存在用户 {0}（可能未同步过），仅完成中央表停用。" -f $loginName) 'WARN'
    }
    elseif ($kcId -eq '') {
        # 空 id 绝不能继续拼 URL：/users//logout 只会 404，脚本却以为停号成功——
        # "停号没停成但看起来像成功"是应急脚本最坏的失效方式，所以这里显式标记未完成。
        $kcSkipped = $true
        Write-Log ("【未完成】Keycloak 用户对象缺 id，已跳过禁用/踢会话，请立即在管理控制台手工停用: {0}" -f $loginName) 'WARN'
    }
    else {
        if ([bool](Get-Prop $kcUser 'enabled' $false)) {
            $full = Invoke-KcApi -Method Get -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId"
            if ($null -eq $full) { throw ("GET Keycloak 用户整对象失败(停用): {0}" -f $loginName) }
            Set-Prop $full 'enabled' $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
            Write-Log ("Keycloak 已禁用: {0}" -f $loginName) 'INFO'
        } else {
            Write-Log ("Keycloak 用户已是禁用状态: {0}" -f $loginName) 'INFO'
        }
        try {
            Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/logout"
            Write-Log ("Keycloak 会话已踢除: {0}" -f $loginName) 'INFO'
        } catch {
            Write-Log ("踢会话失败: {0}" -f $_.Exception.Message) 'WARN'
        }
    }

    # 3. 写日志
    $logMsg = ("紧急停号: {0} ({1}) 原因: {2}" -f $emp, $loginName, $Reason)
    if ($kcSkipped) {
        $logMsg += '；【未完成】Keycloak 段未执行（用户对象缺 id），请在管理控制台手工禁用并踢会话'
    }
    Write-SyncLog -Status 'OK' -Message $logMsg -Credential $cred
    Write-Log $logMsg 'INFO'

    # 4. 告警邮件（含 TR14 强制提示）
    $body = @"
$logMsg

【重要】请当天通知 IT 从 AD 名单中移除该人员——
若次日 06:00 的名单仍包含此人，MERGE 会依据名单状态将其复职（status 回 1）。

服务器: $env:COMPUTERNAME
时间:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
操作人: $env:USERNAME
"@
    $mailSubject = ("[SSO紧急停号] {0} ({1})" -f $emp, $loginName)
    if ($kcSkipped) { $mailSubject = ("[SSO紧急停号-未完成] {0} ({1})" -f $emp, $loginName) }
    Send-AlertMail -Subject $mailSubject -Body $body

    Write-Log '================ disable_user_now 结束 ================' 'INFO'
    exit 0
}
catch {
    $msg = 'disable_user_now 执行失败: ' + $_.Exception.Message
    Write-Log $msg 'ERROR'
    if ($null -ne $cred) {
        try {
            Write-SyncLog -Status 'ERROR' -Message $msg -Credential $cred
        } catch { }
    }
    Send-AlertMail -Subject '[SSO告警] 紧急停号失败（ERROR）' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    exit 1
}
