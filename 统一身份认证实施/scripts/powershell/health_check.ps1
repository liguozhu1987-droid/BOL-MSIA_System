<#
.SYNOPSIS
    SSO 每日健康检查：同步新鲜度 / 当日 SyncLog / Keycloak 服务 / 周一 SMTP 测试。
.DESCRIPTION
    T01 实施工件（方案文档 7.3 SSO_HealthCheck）。
    检查项:
      1. MAX(synced_at) > 26h          → 同步链路新鲜度告警（R17）
      2. 当日 SyncLog 存在非 OK 记录   → 同步异常告警
      3. Keycloak 服务未运行           → 服务告警
      4. 每周一                       → SMTP 测试邮件（验证 25 无认证中继可用）

    告警通道: SMTP 172.19.253.10:25 无认证（System.Net.Mail.SmtpClient）。
    检查结果同时写当日日志；不向 SyncLog 写记录（非同步 phase）。

.NOTES
    文件: scripts/powershell/health_check.ps1
    计划任务: SSO_HealthCheck 每日 07:30
    退出码: 0=全部正常 1=存在告警项
#>
[CmdletBinding()]
param(
    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$CredentialName = 'sso_sync_svc',

    [string]$LogDirectory = 'C:\sso\logs',

    [string]$SmtpServer = '172.19.253.10',
    [int]$SmtpPort = 25,
    [string]$AlertFrom = 'sso-notify@inalfa.local',
    [string[]]$AlertTo = @('ligu@inalfa.local'),
    [string]$SmtpTestRecipient = 'ligu@inalfa.local',

    [int]$MaxSyncAgeHours = 26,

    # Keycloak 服务名（NSSM 注册时的服务名，方案文档 7.1）
    [string]$KeycloakServiceName = 'Keycloak'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:SqlServer = $SqlServer
$script:Database = $Database
$script:LogDirectory = $LogDirectory
$script:LogFile = Join-Path $LogDirectory ("health_check_{0:yyyyMMdd}.log" -f (Get-Date))

# ---------------- 基础函数 ----------------

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

function Send-SmtpTestMail {
    <# 周一 SMTP 连通性测试（验证 25 无认证中继未被判垃圾/未失效）。 #>
    try {
        $msg = New-Object System.Net.Mail.MailMessage
        $msg.From = $AlertFrom
        $msg.To.Add($SmtpTestRecipient)
        $msg.Subject = '[SSO健康检查] SMTP 测试邮件'
        $msg.Body = ("每周 SMTP 连通性测试。`n时间: {0}`n服务器: {1}" -f
(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $env:COMPUTERNAME)
        $msg.SubjectEncoding = [Text.Encoding]::UTF8
        $msg.BodyEncoding = [Text.Encoding]::UTF8
        $smtp = New-Object System.Net.Mail.SmtpClient($SmtpServer, $SmtpPort)
        $smtp.EnableSsl = $false
        $smtp.Send($msg)
        Write-Log ("SMTP 测试邮件已发送 -> {0}" -f $SmtpTestRecipient) 'INFO'
        return $true
    } catch {
        Write-Log ("SMTP 测试邮件发送失败: {0}" -f $_.Exception.Message) 'ERROR'
        return $false
    }
}

function Invoke-SsoSql {
    param(
        [Parameter(Mandatory)][string]$Query,
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    if (Get-Command -Name Invoke-Sqlcmd -ErrorAction SilentlyContinue) {
        return Invoke-Sqlcmd -ServerInstance $script:SqlServer -Database $script:Database `
            -Query $Query -QueryTimeout 60 -ErrorAction Stop `
            -Username $Credential.UserName -Password $Credential.GetNetworkCredential().Password
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
        $cmd.CommandTimeout = 60
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

# ---------------- 主流程 ----------------
$problems = @()
$cred = $null
try {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $script:LogDirectory -Force | Out-Null
    }
    Write-Log '================ health_check 开始 ================' 'INFO'
    $cred = Get-DbCredential -Path $CredentialFile -Name $CredentialName

    # ---- 1. 同步新鲜度: MAX(synced_at) > 26h ----
    $sync = Invoke-SsoSql -Query @"
SELECT
    MAX(synced_at) AS last_synced_at,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE status = 1) AS active_users
FROM dbo.CN_AME_SSO_User
"@ -Credential $cred
    if ($null -eq $sync -or $null -eq $sync[0].last_synced_at) {
        $problems += '中央人员表从未成功同步（MAX(synced_at) 为空）'
        Write-Log '中央人员表无任何同步记录' 'ERROR'
    } else {
        $lastSync = [datetime]$sync[0].last_synced_at
        $ageHours = ((Get-Date).ToUniversalTime() - $lastSync).TotalHours
        Write-Log ("最近同步: {0:yyyy-MM-dd HH:mm} UTC（{1:N1} 小时前），在职 {2} 人" -f
$lastSync, $ageHours, $sync[0].active_users) 'INFO'
        if ($ageHours -gt $MaxSyncAgeHours) {
            $problems += ("同步新鲜度超期: 最近一次 MERGE 在 {0:N1} 小时前（阈值 {1}h）" -f
$ageHours, $MaxSyncAgeHours)
        }
    }

    # ---- 2. 当日 SyncLog 非 OK 记录 ----
    $bad = Invoke-SsoSql -Query @"
SELECT phase, status, LEFT(ISNULL(message,''), 200) AS msg, run_at
FROM dbo.CN_AME_SSO_SyncLog
WHERE CONVERT(date, run_at) = CONVERT(date, SYSUTCDATETIME())
  AND status <> 'OK'
ORDER BY run_at DESC
"@ -Credential $cred
    if ($null -ne $bad -and $bad.Count -gt 0) {
        $detail = ($bad | ForEach-Object { "[{0:HH:mm}] {1}/{2}: {3}" -f $_.run_at, $_.phase, $_.status, $_.msg }) -join '; '
        $problems += ("当日 SyncLog 存在 {0} 条非 OK 记录: {1}" -f $bad.Count, $detail)
        Write-Log ("当日非 OK 同步记录 {0} 条" -f $bad.Count) 'ERROR'
    } else {
        Write-Log '当日 SyncLog 无异常记录' 'INFO'
    }

    # ---- 3. Keycloak 服务状态 ----
    $svc = Get-Service -Name $KeycloakServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        $problems += ("Keycloak 服务 '{0}' 不存在（NSSM 未注册或服务名不符）" -f $KeycloakServiceName)
        Write-Log ("服务不存在: {0}" -f $KeycloakServiceName) 'ERROR'
    } elseif ($svc.Status -ne 'Running') {
        $problems += ("Keycloak 服务状态异常: {0}（当前 {1}）" -f $KeycloakServiceName, $svc.Status)
        Write-Log ("Keycloak 服务状态: {0}" -f $svc.Status) 'ERROR'
    } else {
        Write-Log ("Keycloak 服务运行中（{0}）" -f $KeycloakServiceName) 'INFO'
    }

    # ---- 4. 周一 SMTP 测试邮件 ----
    if ((Get-Date).DayOfWeek -eq 'Monday') {
        if (-not (Send-SmtpTestMail)) {
            $problems += '周一 SMTP 测试邮件发送失败'
        }
    }

    # ---- 汇总 ----
    if ($problems.Count -gt 0) {
        $body = ("SSO 健康检查发现 {0} 个问题:`n`n{1}`n`n服务器: {2}`n时间: {3}" -f
$problems.Count, (($problems | ForEach-Object { " - $_" }) -join "`n"),
            $env:COMPUTERNAME, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
        Write-Log $body 'ERROR'
        Send-AlertMail -Subject '[SSO告警] 每日健康检查异常' -Body $body
        Write-Log '================ health_check 结束（存在问题） ================' 'INFO'
        exit 1
    }

    Write-Log '健康检查全部通过' 'INFO'
    Write-Log '================ health_check 结束 ================' 'INFO'
    exit 0
}
catch {
    $msg = 'health_check 执行失败: ' + $_.Exception.Message
    Write-Log $msg 'ERROR'
    try {
        Send-AlertMail -Subject '[SSO告警] 健康检查脚本执行失败' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    } catch { }
    exit 1
}
