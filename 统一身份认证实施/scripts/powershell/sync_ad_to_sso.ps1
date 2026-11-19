<#
.SYNOPSIS
    每日 AD 名单同步：名单文件 → 暂存表 → 防错检查 → MERGE → 串联 Keycloak 同步。
.DESCRIPTION
    T01 实施工件（数据流 1，方案文档 3.2）。
    流程：找当日 CSV(ad_users_yyyyMMdd.csv) → 校验清洗 → DELETE 灌暂存表(SqlBulkCopy)
          → 防错检查（任一命中 ABORTED + 写 SyncLog + 告警邮件）→ 执行 MERGE 合并进
          CN_AME_SSO_User → 写 SyncLog → 串联调用 sync_sso_to_keycloak.ps1。

    防错规则（2026-11-02 随邮箱策略调整）:
      ABORTED（写 SyncLog + 告警邮件）: 行数骤降>30% / 停用占比>10% / 登录名或工号重复
      告警放行（不中止）: 邮箱格式非法→置空不同步并发告警邮件; 邮箱重复→仅 WARN 放行
      （用户确认"邮箱暂不用管理"，email 允许空/重复，唯一索引已降级为普通索引）

    连接账号 sso_sync_svc；口令从 C:\sso\conf\credentials.xml（DPAPI 加密）读取，不落明文。
    MERGE 规则：禁止改写 login_name；source='MANUAL' 的行不被 AD 同步覆盖。

.PARAMETER Source
    csv   ：从共享目录/本地目录读取当日名单 CSV（L2 主通道，默认）
    table ：从数据库表直接读取（L3 兜底，需配合 -TableSourceQuery）

.PARAMETER CsvDirectory
    名单 CSV 所在目录。文件名规则 ad_users_yyyyMMdd.csv。
    CSV 列名（UTF-8 编码）：userName,realName,email,mobile,enable,employeeNo

.NOTES
    文件: scripts/powershell/sync_ad_to_sso.ps1
    计划任务: SSO_AD_Import 每日 06:00（内部串联 KC 同步）
    依赖:
      1) SQL 连接：优先 Invoke-Sqlcmd（SqlServer 模块，随 SSMS 安装）；
         不可用时回退 Microsoft.Data.SqlClient.dll（需放置于脚本同目录，
         可从 NuGet 获取 Microsoft.Data.SqlClient）。
      2) SqlBulkCopy 灌数依赖 Microsoft.Data.SqlClient.dll（同上）。
      3) credentials.xml：见 README.md「凭据文件生成」一节。
    退出码: 0=成功 1=中止/失败
#>
[CmdletBinding()]
param(
    [ValidateSet('csv', 'table')]
    [string]$Source = 'csv',

    [string]$CsvDirectory = 'C:\sso\import',

    [string]$TableSourceQuery = '',

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$CredentialName = 'sso_sync_svc',

    [string]$LogDirectory = 'C:\sso\logs',

    [string]$SmtpServer = '172.19.253.10',
    [int]$SmtpPort = 25,
    [string]$AlertFrom = 'sso-notify@inalfa.local',
    [string[]]$AlertTo = @('ligu@inalfa.local'),

    [double]$RowDropAbortRatio = 0.30,
    [double]$DisabledAbortRatio = 0.10,

    [switch]$SkipKeycloakSync,
    [string]$KeycloakSyncScript = 'C:\sso\scripts\sync_sso_to_keycloak.ps1',

    # 传给 Keycloak 同步的排除名单（2026-11-11 新增；H20 定稿）：逗号/分号分隔的 employee_no。
    # 默认留空 = 不传该参数，由 sync_sso_to_keycloak.ps1 自己的默认值（15 个服务/机器账号）生效。
    # 这样名单只在一个文件里维护，不会出现两处默认值漂移；需要夜间临时换名单时才在这里传。
    [string]$KeycloakExcludeEmployeeNos = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- 内部状态 ----------------
$script:SqlServer = $SqlServer
$script:Database = $Database
$script:LogDirectory = $LogDirectory
$script:LogFile = Join-Path $LogDirectory ("sync_ad_to_sso_{0:yyyyMMdd}.log" -f (Get-Date))

# ---------------- 基础函数 ----------------

function Write-Log {
    <# 统一日志：控制台 + 当日日志文件（UTF-8）。级别: INFO/WARN/ERROR #>
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
    <# 从 DPAPI 加密的 credentials.xml 读取指定账号口令。
       注意: ConvertFrom-SecureString 默认 CurrentUser 作用域——文件必须由
       计划任务的同一运行账号在同一台机器上生成，否则无法解密。 #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("凭据文件不存在: {0}。请按 README.md 说明用 DPAPI 生成（ConvertTo-SecureString | ConvertFrom-SecureString）。" -f $Path)
    }
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $Name))
    if ($null -eq $node) {
        throw ("凭据文件 {0} 中找不到名为 '{1}' 的条目。" -f $Path, $Name)
    }
    $user = [string]$node.UserName
    if ([string]::IsNullOrWhiteSpace($user)) {
        throw ("凭据条目 '{0}' 缺少 UserName。" -f $Name)
    }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    return New-Object System.Management.Automation.PSCredential($user, $secure)
}

function Send-AlertMail {
    <# 告警邮件：SMTP 172.19.253.10:25 无密码无认证不开 TLS（本环境既定），
       使用 System.Net.Mail.SmtpClient。发送失败只记日志，不中断主流程。 #>
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
        $smtp.DeliveryMethod = 'Network'
        $smtp.Send($msg)
        Write-Log ("告警邮件已发送: {0} -> {1}" -f $Subject, ($AlertTo -join ',')) 'WARN'
    } catch {
        Write-Log ("告警邮件发送失败: {0}" -f $_.Exception.Message) 'ERROR'
    }
}

function Invoke-SsoSql {
    <# 执行 SQL 并返回结果行（SELECT）或 $null（非查询）。
       优先 Invoke-Sqlcmd（SqlServer 模块）；不可用回退 Microsoft.Data.SqlClient。 #>
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
        }
        if ($Parameters.Count -gt 0) { $splat['Variable'] = $Parameters }
        # SQL 登录用 -Username/-Password（模块参数，不走 Windows 集成）
        $splat['Username'] = $Credential.UserName
        $splat['Password'] = $Credential.GetNetworkCredential().Password
        return Invoke-Sqlcmd @splat
    }

    # ---- 回退: .NET Microsoft.Data.SqlClient ----
    if (-not ('Microsoft.Data.SqlClient.SqlConnection' -as [type])) {
        $dll = Join-Path $PSScriptRoot 'Microsoft.Data.SqlClient.dll'
        if (Test-Path -LiteralPath $dll) {
            Add-Type -Path $dll -ErrorAction SilentlyContinue
        }
    }
    if (-not ('Microsoft.Data.SqlClient.SqlConnection' -as [type])) {
        throw ('未找到 Invoke-Sqlcmd，且脚本目录无 Microsoft.Data.SqlClient.dll。' +
               '请安装 SSMS/SqlServer 模块，或将 Microsoft.Data.SqlClient.dll' +
               '（NuGet）放到脚本同目录。')
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
    <# 写同步日志。phase: LOAD/MERGE/KC/KC_EMERGENCY；status: OK/ABORTED/ERROR #>
    param(
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][string]$Status,
        [int]$SrcRows = 0,
        [int]$Added = 0,
        [int]$Updated = 0,
        [int]$Disabled = 0,
        [int]$Reactivated = 0,
        [string]$Message = '',
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    $q = @"
INSERT INTO dbo.CN_AME_SSO_SyncLog
    (phase, src_rows, added, updated, disabled, reactivated, status, message)
VALUES
    (@phase, @src_rows, @added, @updated, @disabled, @reactivated, @status, @message)
"@
    Invoke-SsoSql -Query $q -Parameters @{
        phase = $Phase; src_rows = $SrcRows; added = $Added; updated = $Updated
        disabled = $Disabled; reactivated = $Reactivated; status = $Status
        message = ($Message -replace "'", "''")
    } -Credential $Credential | Out-Null
}

function Test-EmailFormat {
    param([string]$Email)
    if ([string]::IsNullOrWhiteSpace($Email)) { return $false }
    return ($Email -match '^[^@\s]+@[^@\s]+\.[^@\s]+$')
}

function ConvertTo-Status {
    <# CSV enable 列 → status 位。支持 1/0、true/false、yes/no、在职/离职。 #>
    param([string]$Enable)
    if ([string]::IsNullOrWhiteSpace($Enable)) { return 1 }
    switch ($Enable.Trim().ToLower()) {
        '0' { return 0 }
        'false' { return 0 }
        'no' { return 0 }
        '离职' { return 0 }
        default { return 1 }
    }
}

function Import-AdRows {
    <# 按 -Source 读取名单，统一规范为内部对象数组。 #>
    param([Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential)
    if ($Source -eq 'table') {
        if ([string]::IsNullOrWhiteSpace($TableSourceQuery)) {
            throw "-Source table 必须提供 -TableSourceQuery（返回列需含 userName/realName/email/mobile/enable/employeeNo）"
        }
        $rows = Invoke-SsoSql -Query $TableSourceQuery -Credential $Credential
        if ($null -eq $rows) { return @() }
        return @($rows)
    }
    # csv 模式：当日文件，找不到允许回退昨日（带告警），再无则抛错
    $today = Get-Date
    $candidates = @(
        (Join-Path $CsvDirectory ("ad_users_{0:yyyyMMdd}.csv" -f $today)),
        (Join-Path $CsvDirectory ("ad_users_{0:yyyyMMdd}.csv" -f $today.AddDays(-1)))
    )
    $csvPath = $null
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            if ($c -eq $candidates[1]) {
                # 回退昨日文件必须告警——保证"当日名单缺失"可见（方案文档 M3），
                # 同时避免周末/节假日 IT 不投递时链路中断（用旧数据不会造成误停用）
                $fbMsg = ("当日名单 {0} 不存在，本次回退使用昨日文件: {1}。请确认 IT 投递是否正常。" -f
                    $candidates[0], $c)
                Write-Log $fbMsg 'WARN'
                Send-AlertMail -Subject '[SSO告警] 当日 AD 名单缺失（已回退昨日文件）' -Body ($fbMsg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
            }
            $csvPath = $c
            break
        }
    }
    if ($null -eq $csvPath) {
        throw ("未找到名单 CSV（{0} 或昨日文件）。按约定 IT 每日 06:00 前投递。" -f
$candidates[0])
    }
    Write-Log ("读取名单文件: {0}" -f $csvPath) 'INFO'
    # 编码显式 UTF8（IT 约定），避免中文姓名乱码
    $rows = Import-Csv -LiteralPath $csvPath -Encoding UTF8
    if ($null -eq $rows) { return @() }
    return @($rows)
}

function ConvertTo-StagingRows {
    <# 清洗 + 校验。返回 @{ Rows=@(...); DupLogins=@(); DupEmails=@(); BadRows=@(); NulledEmails=@() }
       DupEmails: 邮箱重复（新策略放行，仅记录）; NulledEmails: 格式非法已置空的"login:email"串 #>
    param([Parameter(Mandatory)][object[]]$RawRows)
    $result = @{
        Rows = @(); DupLogins = @(); DupEmails = @(); BadRows = @(); NulledEmails = @()
    }
    $seenLogin = @{}
    $seenEmail = @{}
    $seenEmp = @{}
    foreach ($r in $RawRows) {
        # 列缺失防护（StrictMode 下访问不存在属性会抛错，这里显式判定给出友好信息）
        foreach ($col in 'userName', 'email', 'enable') {
            if ($null -eq $r.PSObject.Properties[$col]) {
                throw ("名单缺少必需列 '{0}'。约定列: userName,realName,email,mobile,enable,employeeNo" -f $col)
            }
        }
        $rawLogin = if ($null -ne $r.userName) { [string]$r.userName } else { '' }
        $login = $rawLogin.Trim().ToLower()
        if ($login -eq '') { $result.BadRows += ('登录名为空: {0}' -f ($rawJson = ($r | ConvertTo-Json -Compress -Depth 3))); continue }

        $rawEmp = if ($null -ne $r.PSObject.Properties['employeeNo']) { [string]$r.employeeNo } else { '' }
        $empNo = $rawEmp.Trim()
        # 12.3 修订: AD 名单无工号时 employee_no = login_name（登录名已验证唯一稳定）
        if ($empNo -eq '') { $empNo = $login }

        if ($seenLogin.ContainsKey($login)) { $result.DupLogins += $login; continue }
        $seenLogin[$login] = $true
        if ($seenEmp.ContainsKey($empNo)) { $result.DupLogins += ("工号重复: {0}" -f $empNo); continue }
        $seenEmp[$empNo] = $true

        $email = if ($null -ne $r.email) { [string]$r.email } else { '' }
        $email = $email.Trim()
        if ($email -ne '') {
            if (-not (Test-EmailFormat $email)) {
                # 邮箱格式非法：置空不同步 + 告警（不跳过整行、不整体中止）
                $result.NulledEmails += ("{0} -> {1}" -f $login, $email)
                $email = ''
            } else {
                $ek = $email.ToLower()
                if ($seenEmail.ContainsKey($ek)) {
                    # 邮箱暂不用管理：重复不再中止，仅 WARN 记录后放行
                    $result.DupEmails += ("{0}:{1}" -f $login, $email)
                } else {
                    $seenEmail[$ek] = $true
                }
            }
        }

        $realName = if ($null -ne $r.PSObject.Properties['realName']) { [string]$r.realName } else { '' }
        $mobile = if ($null -ne $r.PSObject.Properties['mobile']) { [string]$r.mobile } else { '' }

        $result.Rows += [pscustomobject]@{
            employee_no  = $empNo
            login_name   = $login
            display_name = $realName.Trim()
            email        = $email
            mobile       = $mobile.Trim()
            status       = ConvertTo-Status ([string]$r.enable)
        }
    }
    return $result
}

function Invoke-StageLoad {
    <# DELETE 清空暂存表 + SqlBulkCopy 灌入。
       说明: 设计文档写 TRUNCATE，但 TRUNCATE 需 ALTER 权限，而 sso_sync_svc
       仅授予 SELECT/INSERT/UPDATE/DELETE（权限最小化），故用 DELETE 等价实现
       （暂存表无 IDENTITY 列，无需 RESEED）。 #>
    param(
        [Parameter(Mandatory)][object[]]$Rows,
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    Invoke-SsoSql -Query 'DELETE FROM dbo.CN_AME_SSO_StgAdUser' -Credential $Credential | Out-Null

    if (-not ('Microsoft.Data.SqlClient.SqlBulkCopy' -as [type])) {
        $dll = Join-Path $PSScriptRoot 'Microsoft.Data.SqlClient.dll'
        if (Test-Path -LiteralPath $dll) { Add-Type -Path $dll -ErrorAction SilentlyContinue }
    }
    if (-not ('Microsoft.Data.SqlClient.SqlBulkCopy' -as [type])) {
        throw '灌数需要 Microsoft.Data.SqlClient.dll（置于脚本同目录）或已安装 SqlServer 模块环境。'
    }

    $table = New-Object System.Data.DataTable
    foreach ($col in 'employee_no', 'login_name', 'display_name', 'email', 'mobile',
                     'dept_code', 'dept_name', 'title', 'status', 'ad_object_guid', 'loaded_at') {
        [void]$table.Columns.Add($col)
    }
    $now = (Get-Date).ToUniversalTime()
    foreach ($r in $Rows) {
        $row = $table.NewRow()
        $row['employee_no'] = $r.employee_no
        $row['login_name'] = $r.login_name
        $row['display_name'] = if ([string]::IsNullOrEmpty($r.display_name)) { [DBNull]::Value } else { $r.display_name }
        $row['email'] = if ([string]::IsNullOrEmpty($r.email)) { [DBNull]::Value } else { $r.email }
        $row['mobile'] = if ([string]::IsNullOrEmpty($r.mobile)) { [DBNull]::Value } else { $r.mobile }
        $row['dept_code'] = [DBNull]::Value
        $row['dept_name'] = [DBNull]::Value
        $row['title'] = [DBNull]::Value
        $row['status'] = [byte]$r.status
        $row['ad_object_guid'] = [DBNull]::Value
        $row['loaded_at'] = $now
        $table.Rows.Add($row)
    }

    $connStr = ("Server={0};Database={1};User Id={2};Password={3};TrustServerCertificate=true;Connect Timeout=30" -f
                $script:SqlServer, $script:Database,
                $Credential.UserName, $Credential.GetNetworkCredential().Password)
    $bulk = New-Object Microsoft.Data.SqlClient.SqlBulkCopy(
        $connStr, ([Microsoft.Data.SqlClient.SqlBulkCopyOptions]::KeepIdentity -bor
                   [Microsoft.Data.SqlClient.SqlBulkCopyOptions]::KeepNulls))
    try {
        $bulk.DestinationTableName = 'dbo.CN_AME_SSO_StgAdUser'
        $bulk.BatchSize = 500
        $bulk.BulkCopyTimeout = 300
        foreach ($c in $table.Columns) {
            [void]$bulk.ColumnMappings.Add($c.ColumnName, $c.ColumnName)
        }
        $bulk.WriteToServer($table)
    } finally {
        $bulk.Dispose()
    }
    $staged = Invoke-SsoSql -Query 'SELECT COUNT(*) AS cnt FROM dbo.CN_AME_SSO_StgAdUser' -Credential $Credential
    return [int]$staged[0].cnt
}

function Invoke-MergeCentralUser {
    <# 执行方案文档 4.3 的 MERGE，并用 OUTPUT 捕获增/改/停/复计数。
       硬规则: 不改写 login_name；source='MANUAL' 行不被覆盖。 #>
    param([Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential)
    $mergeSql = @'
CREATE TABLE #merge_out (
    action     NVARCHAR(10),
    new_status TINYINT,
    old_status TINYINT
);

MERGE dbo.CN_AME_SSO_User AS t
USING dbo.CN_AME_SSO_StgAdUser AS s
   ON t.employee_no = s.employee_no
WHEN MATCHED AND (
        ISNULL(t.display_name,'') <> ISNULL(s.display_name,'')
     OR ISNULL(t.email,'')        <> ISNULL(s.email,'')
     OR ISNULL(t.mobile,'')       <> ISNULL(s.mobile,'')
     OR ISNULL(t.dept_code,'')    <> ISNULL(s.dept_code,'')
     OR ISNULL(t.dept_name,'')    <> ISNULL(s.dept_name,'')
     OR ISNULL(t.title,'')        <> ISNULL(s.title,'')
     OR t.status                  <> s.status
     OR ISNULL(t.ad_object_guid,'00000000-0000-0000-0000-000000000000')
        <> ISNULL(s.ad_object_guid,'00000000-0000-0000-0000-000000000000')
     )
   AND t.source <> N'MANUAL'
THEN UPDATE SET
        t.display_name = s.display_name, t.email = s.email, t.mobile = s.mobile,
        t.dept_code = s.dept_code, t.dept_name = s.dept_name, t.title = s.title,
        t.status = s.status, t.ad_object_guid = s.ad_object_guid,
        t.source = N'AD', t.synced_at = SYSUTCDATETIME(), t.updated_at = SYSUTCDATETIME()
        -- 故意不更新 login_name / kc_user_id：登录名变更走"停旧建新"
WHEN NOT MATCHED BY TARGET THEN
    INSERT (employee_no, login_name, display_name, email, mobile,
            dept_code, dept_name, title, status, ad_object_guid, source, synced_at)
    VALUES (s.employee_no, s.login_name, s.display_name, s.email, s.mobile,
            s.dept_code, s.dept_name, s.title, s.status, s.ad_object_guid, N'AD', SYSUTCDATETIME())
WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> N'MANUAL' THEN
    UPDATE SET t.status = 0, t.synced_at = SYSUTCDATETIME(), t.updated_at = SYSUTCDATETIME()
OUTPUT $action, inserted.status, deleted.status
    INTO #merge_out (action, new_status, old_status);

SELECT
    SUM(CASE WHEN action = 'INSERT' THEN 1 ELSE 0 END) AS added,
    SUM(CASE WHEN action = 'UPDATE' AND new_status = 1 AND old_status = 1 THEN 1 ELSE 0 END) AS updated,
    SUM(CASE WHEN action = 'UPDATE' AND new_status = 0 THEN 1 ELSE 0 END) AS disabled,
    SUM(CASE WHEN action = 'UPDATE' AND new_status = 1 AND old_status = 0 THEN 1 ELSE 0 END) AS reactivated
FROM #merge_out;

DROP TABLE #merge_out;
'@
    $r = Invoke-SsoSql -Query $mergeSql -Credential $Credential
    if ($null -eq $r) { return @{ added = 0; updated = 0; disabled = 0; reactivated = 0 } }
    return @{
        added = [int]$r[0].added; updated = [int]$r[0].updated
        disabled = [int]$r[0].disabled; reactivated = [int]$r[0].reactivated
    }
}

# ---------------- 主流程 ----------------
$exitCode = 0
$cred = $null
try {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    }
    Write-Log '================ sync_ad_to_sso 开始 ================' 'INFO'
    $cred = Get-DbCredential -Path $CredentialFile -Name $CredentialName

    # 1. 读取名单
    $raw = Import-AdRows -Credential $cred
    if ($raw.Count -eq 0) {
        throw '名单为空（0 行），视为异常，中止。'
    }

    # 2. 清洗校验
    $clean = ConvertTo-StagingRows -RawRows $raw
    $abortReasons = @()
    if ($clean.BadRows.Count -gt 0)  { $abortReasons += ("登录名为空的坏行 {0} 条（例: {1}）" -f $clean.BadRows.Count, $clean.BadRows[0]) }
    if ($clean.DupLogins.Count -gt 0) { $abortReasons += ("登录名/工号重复 {0} 个（例: {1}）" -f $clean.DupLogins.Count, $clean.DupLogins[0]) }
    if ($clean.Rows.Count -eq 0) { $abortReasons += '清洗后有效行数为 0' }
    # 邮箱类问题按新策略只告警不中止（2026-11-02：邮箱暂不用管理）
    if ($clean.NulledEmails.Count -gt 0) {
        $nulledMsg = ("邮箱格式非法已置空 {0} 个: {1}" -f $clean.NulledEmails.Count, ($clean.NulledEmails -join '; '))
        Write-Log $nulledMsg 'WARN'
        Send-AlertMail -Subject '[SSO告警] AD 名单存在格式非法邮箱（已置空放行）' -Body ($nulledMsg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    }
    if ($clean.DupEmails.Count -gt 0) {
        Write-Log ("邮箱重复 {0} 个（新策略放行，仅记录）: {1}" -f $clean.DupEmails.Count, ($clean.DupEmails -join '; ')) 'WARN'
    }

    # 3. 行数骤降检查（与上次成功 LOAD 比较）
    $prev = Invoke-SsoSql -Query @"
SELECT TOP 1 src_rows FROM dbo.CN_AME_SSO_SyncLog
WHERE phase = 'LOAD' AND status = 'OK' ORDER BY id DESC
"@ -Credential $cred
    if ($null -ne $prev -and [int]$prev[0].src_rows -gt 0) {
        $prevRows = [int]$prev[0].src_rows
        $threshold = $prevRows * (1 - $RowDropAbortRatio)
        if ($clean.Rows.Count -lt $threshold) {
            $abortReasons += ("行数骤降: 本次 {0} 行 vs 上次 {1} 行（阈值 {2}，降幅 {3:N1}%）" -f
$clean.Rows.Count, $prevRows, [int]$threshold,
                (100 * (1 - $clean.Rows.Count / $prevRows)))
        }
    }

    # 4. 停用占比检查
    $disabledCount = @($clean.Rows | Where-Object { $_.status -eq 0 }).Count
    $disabledRatio = $disabledCount / $clean.Rows.Count
    if ($disabledRatio -gt $DisabledAbortRatio) {
        $abortReasons += ("停用占比过高: {0}/{1}（{2:N1}% > {3:N0}%）" -f
$disabledCount, $clean.Rows.Count, (100 * $disabledRatio), (100 * $DisabledAbortRatio))
    }

    if ($abortReasons.Count -gt 0) {
        $msg = '防错检查未过，已中止: ' + ($abortReasons -join '; ')
        Write-Log $msg 'ERROR'
        Write-SyncLog -Phase 'LOAD' -Status 'ABORTED' -SrcRows $clean.Rows.Count `
            -Message $msg -Credential $cred
        Send-AlertMail -Subject '[SSO告警] AD名单同步中止（防错检查）' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
        exit 1
    }

    Write-Log ("防错检查通过: 有效 {0} 行（停用 {1} 行，历史基数 {2}）" -f
$clean.Rows.Count, $disabledCount, $(if ($null -ne $prev) { $prev[0].src_rows } else { 'N/A' })) 'INFO'

    # 5. 灌暂存表
    $staged = Invoke-StageLoad -Rows $clean.Rows -Credential $cred
    if ($staged -ne $clean.Rows.Count) {
        throw ("灌表后行数不符: 暂存表 {0} vs 清洗后 {1}" -f $staged, $clean.Rows.Count)
    }
    Write-Log ("暂存表灌入完成: {0} 行" -f $staged) 'INFO'
    Write-SyncLog -Phase 'LOAD' -Status 'OK' -SrcRows $staged `
        -Message ("Source={0}; 有效行 {1}; 停用 {2}" -f $Source, $clean.Rows.Count, $disabledCount) `
        -Credential $cred

    # 6. MERGE 合并
    $m = Invoke-MergeCentralUser -Credential $cred
    Write-Log ("MERGE 完成: 新增 {0} / 更新 {1} / 停用 {2} / 复职 {3}" -f
$m.added, $m.updated, $m.disabled, $m.reactivated) 'INFO'
    Write-SyncLog -Phase 'MERGE' -Status 'OK' -SrcRows $staged `
        -Added $m.added -Updated $m.updated -Disabled $m.disabled -Reactivated $m.reactivated `
        -Message 'MERGE dbo.CN_AME_SSO_User 完成' -Credential $cred
}
catch {
    $msg = 'sync_ad_to_sso 执行失败: ' + $_.Exception.Message
    Write-Log $msg 'ERROR'
    if ($null -ne $cred) {
        try {
            Write-SyncLog -Phase 'LOAD' -Status 'ERROR' -Message $msg -Credential $cred
        } catch {
            Write-Log ('写 SyncLog(ERROR) 失败: {0}' -f $_.Exception.Message) 'ERROR'
        }
    }
    Send-AlertMail -Subject '[SSO告警] AD名单同步失败（ERROR）' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    exit 1
}

# 7. 串联 Keycloak 同步（数据链路成功后）
if (-not $SkipKeycloakSync) {
    Write-Log '串联调用 sync_sso_to_keycloak.ps1 ...' 'INFO'
    try {
        # 排除名单默认留空（H20）: 空就不传，让下游用自己的默认 15 项。
        # PowerShell 5.1 给外部 exe 传参不支持 hashtable splat，故用数组拼可选参数。
        $exArgs = @()
        if ($KeycloakExcludeEmployeeNos -ne '') {
            $exArgs = @('-ExcludeEmployeeNos', $KeycloakExcludeEmployeeNos)
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $KeycloakSyncScript `
            -SqlServer $SqlServer -Database $Database `
            -CredentialFile $CredentialFile -SqlCredentialName $CredentialName `
            -LogDirectory $LogDirectory `
            -SmtpServer $SmtpServer -SmtpPort $SmtpPort `
            -AlertFrom $AlertFrom -AlertTo $AlertTo `
            @exArgs
        $kcExit = $LASTEXITCODE
        if ($kcExit -ne 0) {
            Write-Log ("sync_sso_to_keycloak.ps1 返回非零: {0}" -f $kcExit) 'ERROR'
            $exitCode = $kcExit
        }
    } catch {
        $msg = '串联调用 Keycloak 同步失败: ' + $_.Exception.Message
        Write-Log $msg 'ERROR'
        if ($null -ne $cred) {
            try {
                Write-SyncLog -Phase 'KC' -Status 'ERROR' -Message $msg -Credential $cred
            } catch { }
        }
        Send-AlertMail -Subject '[SSO告警] Keycloak 同步串联失败' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
        $exitCode = 1
    }
}

Write-Log ('================ sync_ad_to_sso 结束（exit={0}） ================' -f $exitCode) 'INFO'
exit $exitCode
