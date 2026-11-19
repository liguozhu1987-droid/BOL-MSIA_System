<#
.SYNOPSIS
    为 MSIA 历史问题责任人补写 SSO 用户映射（邮箱 → 原短名），并支持回滚与登录后校验。
.DESCRIPTION
    背景：切换到 Entra 邮箱账号后，Keycloak 的 username = preferred_username = 邮箱。
    MSIA / BOL 解析身份的 SQL 是：

        SELECT m.local_username
        FROM dbo.CN_AME_SSO_UserMap m
        JOIN dbo.CN_AME_SSO_User u ON u.employee_no = m.employee_no
        WHERE m.system_code = 'msia'
          AND UPPER(LTRIM(RTRIM(u.login_name))) = UPPER(LTRIM(RTRIM(@login_name)))

    由此得出两条硬约束（务必先看）：
      1) preferred_username 匹配的是 CN_AME_SSO_User.login_name，不是 UserMap 的任何列。
         UserMap 没有 login_name 列，只有 employee_no / system_code / local_username。
         所以"在 UserMap 里写 login_name = 邮箱"这件事在表结构上不存在。
      2) 只插映射行不够：必须让这 9 人的 CN_AME_SSO_User.login_name 等于其邮箱，
         否则 u.login_name = 邮箱 这个 JOIN 条件不成立，映射永远不会被命中，
         应用会回落 preferred_username（邮箱）并自动新建一个空账号。

    因此本脚本提供两种执行口径：
      -Action Apply                 只写 9 行 UserMap；若发现 login_name 仍为短名则中止（不静默写入无效数据）。
      -Action Apply -AlignLoginName 先把 login_name 改成邮箱，再写 9 行 UserMap；同一事务，失败全回滚。

    默认 -Action Preview，只读、不写库，打印当前状态、判定结果和将执行的 SQL。
    CN_AME_SSO_User.login_name 上有唯一索引 UQ_CN_AME_SSO_User_Login；执行前会检查邮箱是否已被别人占用。
    UserMap 的唯一索引是 (system_code, local_username)，不是 (system_code, employee_no)；
    employee_no + system_code 只是普通索引，允许同一人多行——脚本会同时检查这两类冲突。

    范围说明：本脚本只处理 MSIA 的 9 名责任人（system_code 默认 msia）。
    BOL 的目标账号在 CMC.dbo.CN_IE_BOL_Employee，当前环境无 CMC 只读权限，未纳入。

.NOTES
    文件: scripts/powershell/Add-SsoUserMapForLegacyOwners.ps1
    执行方式: 手工（默认只读；写库需显式 -Action Apply 或 -Action Rollback）
    示例:
      .\Add-SsoUserMapForLegacyOwners.ps1                        # 预览（只读）
      .\Add-SsoUserMapForLegacyOwners.ps1 -Action Apply -WhatIf  # 预览将写入的内容
      .\Add-SsoUserMapForLegacyOwners.ps1 -Action Apply -AlignLoginName
      .\Add-SsoUserMapForLegacyOwners.ps1 -Action Rollback
      .\Add-SsoUserMapForLegacyOwners.ps1 -Action Rollback -RollbackLoginName
      .\Add-SsoUserMapForLegacyOwners.ps1 -Action Verify          # 只读校验
    退出码: 0=完成  2=前置校验/参数/一致性检查未通过，未写入  3=数据库或凭据错误
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Preview', 'Apply', 'Rollback', 'Verify')]
    [string]$Action = 'Preview',

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc',
    [switch]$IntegratedSecurity,

    [ValidateSet('msia', 'bol')]
    [string]$SystemCode = 'msia',

    # Apply 时把 CN_AME_SSO_User.login_name 一并改成邮箱（映射生效的必要条件）
    [switch]$AlignLoginName,

    # Rollback 时把 login_name 从邮箱改回原短名
    [switch]$RollbackLoginName,

    [string]$OutDirectory = 'C:\sso\tmp'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 目标数据（只读统计口径：2026-11-13）
# EmployeeNo = 中央表工号；LocalUsername = 本地短名；MisaUserId = CN_AME_MISA_User.Id
# ExpectedAlive = 未删除问题数（工作台"我的审核问题"默认列表条数）
# ExpectedOpen  = 其中未关闭数（工作台筛选"未关闭"时的条数）
$MapData = @(
    [pscustomobject]@{ EmployeeNo = 'zhaop3';  Email = 'Pengcheng.Zhao@inalfa.com'; LocalUsername = 'zhaop3';  MisaUserId = 4143; ExpectedAlive = 36; ExpectedOpen = 17 },
    [pscustomobject]@{ EmployeeNo = 'luyu';    Email = 'Yulong.Lu@inalfa.com';      LocalUsername = 'luyu';    MisaUserId = 2715; ExpectedAlive = 33; ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'zhangp2'; Email = 'Pengfei.Zhang@inalfa.com';  LocalUsername = 'zhangp2'; MisaUserId = 4022; ExpectedAlive = 18; ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'yuk3';    Email = 'Kent.Yu@inalfa.com';        LocalUsername = 'yuk3';    MisaUserId = 3925; ExpectedAlive = 18; ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'zhug';    Email = 'guopeng.zhu@inalfa.com';    LocalUsername = 'zhug';    MisaUserId = 4244; ExpectedAlive = 16; ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'lizh13';  Email = 'Zhuolin.Li@inalfa.com';     LocalUsername = 'lizh13';  MisaUserId = 2649; ExpectedAlive = 15; ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'hexi';    Email = 'Xiaozhong.He@inalfa.com';   LocalUsername = 'hexi';    MisaUserId = 1963; ExpectedAlive = 9;  ExpectedOpen = 0 },
    [pscustomobject]@{ EmployeeNo = 'chenca';  Email = 'Roger.Chen@inalfa.com';     LocalUsername = 'chenca';  MisaUserId = 188;  ExpectedAlive = 9;  ExpectedOpen = 3 },
    [pscustomobject]@{ EmployeeNo = 'huangf';  Email = 'Falin.Huang@inalfa.com';    LocalUsername = 'huangf';  MisaUserId = 2002; ExpectedAlive = 4;  ExpectedOpen = 0 }
)

$Remark = 'legacy-owner-mapping: email->short name (232 issues restore)'

function Write-Step {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR', 'SKIP')][string]$Level = 'INFO'
    )
    $line = '{0:HH:mm:ss} [{1,-5}] {2}' -f (Get-Date), $Level, $Message
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        'SKIP'  { Write-Host $line -ForegroundColor DarkGray }
        'OK'    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
}

function New-SqlConnection {
    $base = 'Server={0};Database={1};Encrypt=True;TrustServerCertificate=True;Application Name=sso-usermap-legacy;' -f $SqlServer, $Database
    if ($IntegratedSecurity) {
        $conn = New-Object System.Data.SqlClient.SqlConnection ($base + 'Integrated Security=True;')
        $conn.Open()
        return $conn
    }
    if (-not (Test-Path -LiteralPath $CredentialFile)) {
        throw "凭据文件不存在: $CredentialFile（可用 -IntegratedSecurity 改用当前 Windows 账户）"
    }
    [xml]$doc = Get-Content -LiteralPath $CredentialFile -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $SqlCredentialName))
    if ($null -eq $node) { throw ("凭据文件 {0} 中找不到条目 '{1}'。" -f $CredentialFile, $SqlCredentialName) }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    $sqlCred = New-Object System.Data.SqlClient.SqlCredential(([string]$node.UserName), $secure)
    $conn = New-Object System.Data.SqlClient.SqlConnection($base, $sqlCred)
    $conn.Open()
    return $conn
}

function New-Command {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql,
        $Transaction = $null
    )
    $cmd = $Connection.CreateCommand()
    $cmd.CommandTimeout = 120
    $cmd.CommandText = $Sql
    if ($null -ne $Transaction) { $cmd.Transaction = $Transaction }
    return $cmd
}

function Get-Rows {
    <# 执行只读查询并返回 PSCustomObject 列表；@params 为 ordered hashtable（名字不带 @）。 #>
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql,
        [hashtable]$Params = @{},
        $Transaction = $null
    )
    $cmd = New-Command -Connection $Connection -Sql $Sql -Transaction $Transaction
    foreach ($k in $Params.Keys) { [void]$cmd.Parameters.AddWithValue('@' + $k, $Params[$k]) }
    $rd = $cmd.ExecuteReader()
    $list = New-Object System.Collections.Generic.List[object]
    try {
        while ($rd.Read()) {
            $o = [ordered]@{}
            for ($i = 0; $i -lt $rd.FieldCount; $i++) {
                $o[$rd.GetName($i)] = $(if ($rd.IsDBNull($i)) { $null } else { $rd.GetValue($i) })
            }
            $list.Add([pscustomobject]$o)
        }
    } finally {
        $rd.Close()
        $cmd.Dispose()
    }
    return $list
}

function Invoke-NonQuery {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql,
        [Parameter(Mandatory)][hashtable]$Params,
        $Transaction = $null
    )
    $cmd = New-Command -Connection $Connection -Sql $Sql -Transaction $Transaction
    foreach ($k in $Params.Keys) { [void]$cmd.Parameters.AddWithValue('@' + $k, $Params[$k]) }
    try {
        return $cmd.ExecuteNonQuery()
    } finally {
        $cmd.Dispose()
    }
}

function ConvertTo-InList {
    <# 生成 (@p0,@p1,...) 和参数表，避免拼接值。 #>
    param([Parameter(Mandatory)][string[]]$Values, [string]$Prefix = 'p')
    $names = @()
    $params = @{}
    for ($i = 0; $i -lt $Values.Count; $i++) {
        $n = '{0}{1}' -f $Prefix, $i
        $names += '@' + $n
        $params[$n] = $Values[$i]
    }
    return [pscustomobject]@{ InList = '(' + ($names -join ',') + ')'; Params = $params }
}

function Get-CentralUsers {
    param($Connection)
    $emp = @($MapData | ForEach-Object { $_.EmployeeNo })
    $in = ConvertTo-InList -Values $emp -Prefix 'e'
    $sql = @"
SELECT employee_no, login_name, email, status, source
FROM dbo.CN_AME_SSO_User
WHERE employee_no IN $($in.InList)
"@
    return Get-Rows -Connection $Connection -Sql $sql -Params $in.Params
}

function Get-EmailOwners {
    <# 检查这些邮箱是否已被其他工号占用（login_name 唯一索引会挡住改名的情形）。 #>
    param($Connection)
    $emails = @($MapData | ForEach-Object { $_.Email })
    $in = ConvertTo-InList -Values $emails -Prefix 'm'
    $sql = @"
SELECT employee_no, login_name
FROM dbo.CN_AME_SSO_User
WHERE login_name IN $($in.InList)
"@
    return Get-Rows -Connection $Connection -Sql $sql -Params $in.Params
}

function Get-MapRows {
    param($Connection, $Transaction = $null)
    $emp = @($MapData | ForEach-Object { $_.EmployeeNo })
    $loc = @($MapData | ForEach-Object { $_.LocalUsername })
    $inE = ConvertTo-InList -Values $emp -Prefix 'e'
    $inL = ConvertTo-InList -Values $loc -Prefix 'l'
    $sql = @"
SELECT id, employee_no, system_code, local_username, match_key, remark
FROM dbo.CN_AME_SSO_UserMap
WHERE (system_code = @sc AND employee_no IN $($inE.InList))
   OR (system_code = @sc AND local_username IN $($inL.InList))
"@
    $p = @{ sc = $SystemCode }
    foreach ($k in $inE.Params.Keys) { $p[$k] = $inE.Params[$k] }
    foreach ($k in $inL.Params.Keys) { $p[$k] = $inL.Params[$k] }
    return Get-Rows -Connection $Connection -Sql $sql -Params $p -Transaction $Transaction
}

function Get-IssueCounts {
    param($Connection)
    $u = @($MapData | ForEach-Object { $_.LocalUsername })
    $in = ConvertTo-InList -Values $u -Prefix 'u'
    $sql = @"
SELECT u.Username,
       SUM(CASE WHEN i.IsDeleted = 0 THEN 1 ELSE 0 END) AS alive_count,
       SUM(CASE WHEN i.IsDeleted = 0 AND i.Status <> 'closed' THEN 1 ELSE 0 END) AS open_count
FROM dbo.CN_AME_MISA_Issue i
JOIN dbo.CN_AME_MISA_User u ON u.Id = i.OwnerUserId
WHERE u.Username IN $($in.InList)
GROUP BY u.Username
"@
    return Get-Rows -Connection $Connection -Sql $sql -Params $in.Params
}

function Get-MisaUsers {
    param($Connection)
    $u = @($MapData | ForEach-Object { $_.LocalUsername })
    $in = ConvertTo-InList -Values $u -Prefix 'u'
    $sql = @"
SELECT Id, Username, Role, Status
FROM dbo.CN_AME_MISA_User
WHERE Username IN $($in.InList)
"@
    return Get-Rows -Connection $Connection -Sql $sql -Params $in.Params
}

function Show-TargetData {
    Write-Host ''
    Write-Step ("目标数据：{0} 人，{1} 条有效问题（未删除）" -f $MapData.Count, (@($MapData | Measure-Object -Property ExpectedAlive -Sum).Sum)) 'INFO'
    $MapData | Select-Object EmployeeNo, Email, LocalUsername, MisaUserId, ExpectedAlive, ExpectedOpen |
        Format-Table -AutoSize | Out-String -Width 200 | Write-Host
}

function Assert-Preconditions {
    <# 返回 $true 表示通过；不通过时打印原因并返回 $false。 #>
    param($CentralRows, $EmailRows, $MapRows)

    $ok = $true
    $byEmp = @{}
    foreach ($r in $CentralRows) { $byEmp[[string]$r.employee_no] = $r }

    foreach ($d in $MapData) {
        if (-not $byEmp.ContainsKey($d.EmployeeNo)) {
            Write-Step ("中央表缺少工号 {0}" -f $d.EmployeeNo) 'ERROR'; $ok = $false
            continue
        }
        $row = $byEmp[$d.EmployeeNo]
        $dbEmail = ([string]$row.email).Trim()
        if ($dbEmail -ine $d.Email) {
            Write-Step ("{0}: 中央表 email='{1}' 与脚本预期 '{2}' 不一致（数据已漂移，先核对）" -f $d.EmployeeNo, $dbEmail, $d.Email) 'ERROR'
            $ok = $false
        }
        if ([string]$row.status -ne '1') {
            Write-Step ("{0}: 中央表 status={1}，非在职；写入映射后本人也无法登录验证" -f $d.EmployeeNo, $row.status) 'WARN'
        }
    }

    # login_name 唯一索引：目标邮箱若已被别的工号占用，改名会撞唯一约束
    $mine = @{}
    foreach ($d in $MapData) { $mine[$d.Email.ToLowerInvariant()] = $d.EmployeeNo }
    foreach ($r in $EmailRows) {
        $ln = ([string]$r.login_name).Trim()
        if ($ln -eq '') { continue }
        $k = $ln.ToLowerInvariant()
        if ($mine.ContainsKey($k) -and $mine[$k] -ne [string]$r.employee_no) {
            Write-Step ("邮箱 {0} 已被工号 {1} 的 login_name 占用，不能改名" -f $ln, $r.employee_no) 'ERROR'
            $ok = $false
        }
    }

    # UserMap 冲突：唯一索引是 (system_code, local_username)；employee_no 也可能已有行
    foreach ($m in $MapRows) {
        $empNo = [string]$m.employee_no
        $local = [string]$m.local_username
        $hit = $MapData | Where-Object { $_.EmployeeNo -eq $empNo -or $_.LocalUsername -eq $local }
        if ($hit) {
            Write-Step ("UserMap 已存在行：id={0} employee_no={1} local_username={2}（需人工确认是否保留，脚本不覆盖）" -f $m.id, $empNo, $local) 'ERROR'
            $ok = $false
        }
    }

    return $ok
}

# ---------------------------------------------------------------- 主流程
Show-TargetData

try {
    $conn = New-SqlConnection
} catch {
    Write-Step ("连接数据库失败: {0}" -f $_.Exception.Message) 'ERROR'
    exit 3
}

try {
    # ============================================================ Preview
    if ($Action -eq 'Preview') {
        $central = Get-CentralUsers -Connection $conn
        $emailRows = Get-EmailOwners -Connection $conn
        $mapRows = Get-MapRows -Connection $conn

        Write-Host ''
        Write-Step '===== 当前状态（只读） =====' 'OK'
        $view = foreach ($d in $MapData) {
            $c = $central | Where-Object { [string]$_.employee_no -eq $d.EmployeeNo } | Select-Object -First 1
            $ln = if ($c) { ([string]$c.login_name).Trim() } else { '(缺失)' }
            $hasMap = @($mapRows | Where-Object {
                [string]$_.employee_no -eq $d.EmployeeNo -and [string]$_.local_username -eq $d.LocalUsername
            }).Count -gt 0
            [pscustomobject]@{
                EmployeeNo   = $d.EmployeeNo
                login_name   = $ln
                Email        = $d.Email
                映射行       = $(if ($hasMap) { '已存在' } else { '无' })
                映射可生效   = $(if ($ln -ieq $d.Email) { '是' } else { '否：login_name≠邮箱' })
            }
        }
        $view | Format-Table -AutoSize | Out-String -Width 220 | Write-Host

        $needAlign = @($view | Where-Object { $_.'映射可生效' -ne '是' }).Count
        Write-Host ''
        if ($needAlign -gt 0) {
            Write-Step ("{0} 人的 login_name 仍是短名：只插映射行不会命中，需 -AlignLoginName 一并改名" -f $needAlign) 'WARN'
        } else {
            Write-Step '9 人的 login_name 均已等于邮箱，插入映射行即可生效' 'OK'
        }

        Write-Host ''
        Write-Step '===== 将执行的 SQL（Apply -AlignLoginName 时） =====' 'INFO'
        foreach ($d in $MapData) {
            $c = $central | Where-Object { [string]$_.employee_no -eq $d.EmployeeNo } | Select-Object -First 1
            $ln = if ($c) { ([string]$c.login_name).Trim() } else { '' }
            if ($ln -ine $d.Email) {
                Write-Host ("UPDATE dbo.CN_AME_SSO_User SET login_name = '{0}' WHERE employee_no = '{1}' AND login_name = '{2}';" -f $d.Email, $d.EmployeeNo, $ln)
            }
            Write-Host ("INSERT INTO dbo.CN_AME_SSO_UserMap (employee_no, system_code, local_username, match_key, remark) VALUES ('{0}', '{1}', '{2}', 'USERNAME', '{3}');" -f $d.EmployeeNo, $SystemCode, $d.LocalUsername, $Remark)
        }
        Write-Host ''
        Write-Step '===== 回滚 SQL（Rollback） =====' 'INFO'
        foreach ($d in $MapData) {
            Write-Host ("DELETE FROM dbo.CN_AME_SSO_UserMap WHERE system_code = '{0}' AND employee_no = '{1}' AND local_username = '{2}';" -f $SystemCode, $d.EmployeeNo, $d.LocalUsername)
        }
        if ($RollbackLoginName) {
            Write-Host '-- 并执行：'
            foreach ($d in $MapData) {
                Write-Host ("UPDATE dbo.CN_AME_SSO_User SET login_name = '{0}' WHERE employee_no = '{1}' AND login_name = '{2}';" -f $d.LocalUsername, $d.EmployeeNo, $d.Email)
            }
        }
        Write-Host ''
        Write-Step '预览完成，未修改任何数据。' 'OK'
        exit 0
    }

    # ============================================================ Apply
    if ($Action -eq 'Apply') {
        $central = Get-CentralUsers -Connection $conn
        $emailRows = Get-EmailOwners -Connection $conn
        $mapRows = Get-MapRows -Connection $conn
        if (-not (Assert-Preconditions -CentralRows $central -EmailRows $emailRows -MapRows $mapRows)) {
            Write-Step '前置校验未通过，中止（未写入任何数据）' 'ERROR'
            exit 2
        }

        $byEmp = @{}
        foreach ($r in $central) { $byEmp[[string]$r.employee_no] = $r }
        $toAlign = @($MapData | Where-Object {
            ([string]$byEmp[$_.EmployeeNo].login_name).Trim() -ine $_.Email
        })

        if ($toAlign.Count -gt 0 -and -not $AlignLoginName) {
            Write-Step ("{0} 人的 login_name 仍为短名，只插映射不会生效。请加 -AlignLoginName，或先完成中央表改名" -f $toAlign.Count) 'ERROR'
            Write-Step '中止（未写入任何数据）' 'ERROR'
            exit 2
        }

        if (-not $PSCmdlet.ShouldProcess(
                ("{0}: 写 {1} 行 UserMap{2}" -f $Database, $MapData.Count, $(if ($AlignLoginName -and $toAlign.Count -gt 0) { "，并改 $($toAlign.Count) 行 login_name" } else { '' })),
                'Apply')) {
            Write-Step 'WhatIf：仅预演，未写入' 'WARN'
            exit 0
        }

        $tx = $conn.BeginTransaction()
        try {
            $aligned = 0
            if ($AlignLoginName) {
                foreach ($d in $toAlign) {
                    $old = ([string]$byEmp[$d.EmployeeNo].login_name).Trim()
                    $n = Invoke-NonQuery -Connection $conn -Transaction $tx -Sql @'
UPDATE dbo.CN_AME_SSO_User
SET login_name = @email
WHERE employee_no = @emp AND login_name = @old
'@ -Params @{ email = $d.Email; emp = $d.EmployeeNo; old = $old }
                    if ($n -ne 1) { throw ("改 login_name 影响行数异常: {0} 期望 1 实际 {1}" -f $d.EmployeeNo, $n) }
                    $aligned++
                    Write-Step ("login_name: {0} -> {1}" -f $old, $d.Email) 'INFO'
                }
            }

            foreach ($d in $MapData) {
                $n = Invoke-NonQuery -Connection $conn -Transaction $tx -Sql @'
INSERT INTO dbo.CN_AME_SSO_UserMap (employee_no, system_code, local_username, match_key, remark)
VALUES (@emp, @sc, @local, 'USERNAME', @remark)
'@ -Params @{ emp = $d.EmployeeNo; sc = $SystemCode; local = $d.LocalUsername; remark = $Remark }
                if ($n -ne 1) { throw ("插入 UserMap 影响行数异常: {0} 实际 {1}" -f $d.EmployeeNo, $n) }
            }

            $tx.Commit()
            Write-Step ("已提交：改 login_name {0} 行，写 UserMap {1} 行（system_code={2}）" -f $aligned, $MapData.Count, $SystemCode) 'OK'
            Write-Step '下一步：让 9 人各登录一次，按 -Action Verify 的期望条数核对工作台' 'INFO'
        } catch {
            $tx.Rollback()
            Write-Step ("写入失败，已回滚: {0}" -f $_.Exception.Message) 'ERROR'
            exit 3
        } finally {
            $tx.Dispose()
        }
        exit 0
    }

    # ============================================================ Rollback
    if ($Action -eq 'Rollback') {
        $existing = @(Get-MapRows -Connection $conn | Where-Object {
            $e = [string]$_.employee_no; $l = [string]$_.local_username
            @($MapData | Where-Object { $_.EmployeeNo -eq $e -and $_.LocalUsername -eq $l }).Count -gt 0
        })

        if ($existing.Count -eq 0) {
            Write-Step '没有找到本脚本写入的映射行，无需回滚' 'OK'
        } else {
            if (-not (Test-Path -LiteralPath $OutDirectory)) {
                New-Item -ItemType Directory -Force -Path $OutDirectory | Out-Null
            }
            $bak = Join-Path $OutDirectory ('usermap_rollback_backup_{0}.csv' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
            $existing | Select-Object id, employee_no, system_code, local_username, match_key, remark |
                Export-Csv -LiteralPath $bak -NoTypeInformation -Encoding UTF8
            Write-Step ("待删除 {0} 行，已备份: {1}" -f $existing.Count, $bak) 'INFO'
            $existing | Select-Object id, employee_no, system_code, local_username |
                Format-Table -AutoSize | Out-String -Width 180 | Write-Host
        }

        $doLoginRollback = $RollbackLoginName.IsPresent
        $what = "删除 UserMap {0} 行{1}" -f $existing.Count, $(if ($doLoginRollback) { '，并把 login_name 改回短名' } else { '' })
        if (-not $PSCmdlet.ShouldProcess($Database, $what)) {
            Write-Step 'WhatIf：仅预演，未写入' 'WARN'
            exit 0
        }

        $tx = $conn.BeginTransaction()
        try {
            $deleted = 0
            foreach ($d in $MapData) {
                $deleted += Invoke-NonQuery -Connection $conn -Transaction $tx -Sql @'
DELETE FROM dbo.CN_AME_SSO_UserMap
WHERE system_code = @sc AND employee_no = @emp AND local_username = @local
'@ -Params @{ sc = $SystemCode; emp = $d.EmployeeNo; local = $d.LocalUsername }
            }
            $restored = 0
            if ($doLoginRollback) {
                foreach ($d in $MapData) {
                    $restored += Invoke-NonQuery -Connection $conn -Transaction $tx -Sql @'
UPDATE dbo.CN_AME_SSO_User
SET login_name = @local
WHERE employee_no = @emp AND login_name = @email
'@ -Params @{ local = $d.LocalUsername; emp = $d.EmployeeNo; email = $d.Email }
                }
            }
            $tx.Commit()
            Write-Step ("回滚已提交：删除 UserMap {0} 行，恢复 login_name {1} 行" -f $deleted, $restored) 'OK'
        } catch {
            $tx.Rollback()
            Write-Step ("回滚失败，已撤销: {0}" -f $_.Exception.Message) 'ERROR'
            exit 3
        } finally {
            $tx.Dispose()
        }
        exit 0
    }

    # ============================================================ Verify
    if ($Action -eq 'Verify') {
        $central = Get-CentralUsers -Connection $conn
        $mapRows = Get-MapRows -Connection $conn
        $misa = Get-MisaUsers -Connection $conn
        $counts = Get-IssueCounts -Connection $conn
        $byEmp = @{}
        foreach ($r in $central) { $byEmp[[string]$r.employee_no] = $r }
        $byMisa = @{}
        foreach ($r in $misa) { $byMisa[[string]$r.Username] = $r }
        $byCnt = @{}
        foreach ($r in $counts) { $byCnt[[string]$r.Username] = $r }

        $bad = 0
        $rows = foreach ($d in $MapData) {
            $c = $byEmp[$d.EmployeeNo]
            $m = $byMisa[$d.LocalUsername]
            $k = $byCnt[$d.LocalUsername]
            $hasMap = @($mapRows | Where-Object {
                [string]$_.employee_no -eq $d.EmployeeNo -and [string]$_.local_username -eq $d.LocalUsername
            }).Count -gt 0
            $loginOk = $c -and (([string]$c.login_name).Trim() -ieq $d.Email)
            $alive = if ($k) { [int]$k.alive_count } else { 0 }
            $open = if ($k) { [int]$k.open_count } else { 0 }
            $pass = $hasMap -and $loginOk -and ($alive -eq $d.ExpectedAlive) -and ($open -eq $d.ExpectedOpen)
            if (-not $pass) { $bad++ }
            [pscustomobject]@{
                EmployeeNo = $d.EmployeeNo
                映射行     = $(if ($hasMap) { '有' } else { '无' })
                login_name = $(if ($c) { ([string]$c.login_name).Trim() } else { '(缺失)' })
                MISA_Id    = $(if ($m) { [string]$m.Id } else { '(缺失)' })
                Role       = $(if ($m) { [string]$m.Role } else { '' })
                预期有效   = $d.ExpectedAlive
                实际有效   = $alive
                预期未关闭 = $d.ExpectedOpen
                实际未关闭 = $open
                结论       = $(if ($pass) { 'PASS' } else { 'FAIL' })
            }
        }
        $rows | Format-Table -AutoSize | Out-String -Width 240 | Write-Host

        Write-Host ''
        Write-Step '工作台核对口径：MSIA「我的工作台 → 我的审核问题」默认列出 IsDeleted=0 的问题；' 'INFO'
        Write-Step 'reviewee 只返回 OwnerUserId=本人Id 或 OwnerUserName=本人Username 的问题。' 'INFO'
        if ($bad -eq 0) {
            Write-Step ('9 人全部 PASS（合计 {0} 条有效问题）' -f (@($MapData | Measure-Object -Property ExpectedAlive -Sum).Sum)) 'OK'
            exit 0
        }
        Write-Step ("{0} 人未通过，逐行看上面的结论列" -f $bad) 'ERROR'
        exit 2
    }

    Write-Step ("未知 Action: {0}" -f $Action) 'ERROR'
    exit 2
}
finally {
    $conn.Close()
    $conn.Dispose()
}
