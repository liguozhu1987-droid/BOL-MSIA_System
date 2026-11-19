<#
.SYNOPSIS
    只读比对：Entra ID 的 UPN / onPremisesSamAccountName 与中央表 login_name 的差异。
.DESCRIPTION
    用途：Keycloak 以 Entra 作 broker 时，Keycloak 的 username 取自 Entra 令牌里的
    preferred_username（= UPN），而我们的中央表 CN_AME_SSO_User.login_name 是
    AD 的 sAMAccountName。两者对不上时，登录"成功"但会新建一个带 @ 的账号、
    组全丢、每日同步脚本按 login_name 查不到人。本脚本只做差异盘点和分类，
    不写数据库、不改 Keycloak、不发邮件。

    输入：
      1) -EntraCsvPath  从 Entra 导出的用户清单，至少含 UPN 列；
                        建议同时含 onPremisesSamAccountName 列。
                        推荐用 Graph 取（列名固定）：
                        GET /users?$select=userPrincipalName,onPremisesSamAccountName,mail,accountEnabled&$top=999
                        也可用 Entra 管理中心 → 用户 → 所有用户 → 下载用户（列名可能是本地化中文，
                        脚本会报出实际列名，重命名表头后再跑）。
      2) 中央表 dbo.CN_AME_SSO_User（只读 SELECT）。

    输出（默认 C:\sso\tmp）：
      upn_login_diff_<时间戳>.csv   全量分类明细，UTF-8 BOM，可直接 Excel 打开
      控制台汇总：各分类计数 + 需人工看的样本

    分类口径（对应手册 4 节的三条路）：
      OK               UPN 前缀与 login_name 完全相同 → 路 1 直接可用
      OK_CASE          仅大小写不同 → 路 1 可用（Keycloak username 不区分大小写）
      PATH2            UPN 前缀不同，但 onPremisesSamAccountName == login_name
                       → 必须让 Entra 下发 sAMAccountName（路 2）
      PATH3            两者都与 login_name 不同，只有 UPN
                       → 只能用 UPN 作 username（路 3），或先治理数据
      NOT_IN_ENTRA     中央表有这个 login_name，Entra 导出里找不到
                       → 切过去这批人登不上
      NO_UPN           Entra 记录缺 userPrincipalName（数据异常）

.NOTES
    文件: scripts/powershell/compare_upn_login.ps1
    执行方式: 手工（只读，可在任意时间跑）
    示例: .\compare_upn_login.ps1 -EntraCsvPath C:\sso\tmp\entra-users.csv
          .\compare_upn_login.ps1 -EntraCsvPath C:\sso\tmp\entra-users.csv -OnlyActive
    退出码: 0=比对完成（有差异也算完成） 2=输入/参数错误 3=数据库或凭据错误
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EntraCsvPath,

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc',

    [string]$OutDirectory = 'C:\sso\tmp',

    # 只比中央表里 status=1 的账号
    [switch]$OnlyActive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )
    $line = '{0:HH:mm:ss} [{1,-5}] {2}' -f (Get-Date), $Level, $Message
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        'OK'    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
}

function Import-CsvAuto {
    <# 自动判定编码：有 BOM 按 UTF-8；无 BOM 先按严格 UTF-8 解，失败回退 GBK(936)。
       Excel 另存的 CSV 是 GBK，直接 Import-Csv 会把中文列名读成乱码。#>
    param([Parameter(Mandatory)][string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { throw "文件为空: $Path" }
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    if ($hasBom) {
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    } else {
        $enc = $null
        try {
            $strict = New-Object System.Text.UTF8Encoding($false, $true)
            [void]$strict.GetString($bytes)
            $enc = [System.Text.Encoding]::UTF8
        } catch {
            $enc = [System.Text.Encoding]::GetEncoding(936)
        }
        $text = [System.IO.File]::ReadAllText($Path, $enc)
    }
    if ([string]::IsNullOrWhiteSpace($text)) { throw "文件没有内容: $Path" }
    return @($text | ConvertFrom-Csv)
}

function Get-CsvColumn {
    <# 按候选名（忽略大小写）找实际列名；找不到返回空串。 #>
    param(
        [Parameter(Mandatory)][string[]]$Columns,
        [Parameter(Mandatory)][string[]]$Candidates
    )
    foreach ($c in $Candidates) {
        foreach ($col in $Columns) {
            if ($col.Trim() -ieq $c) { return $col }
        }
    }
    return ''
}

function Get-CellValue {
    <# 安全取单元格：列不存在返回空串，避免 StrictMode 抛属性不存在。 #>
    param([object]$Row, [string]$Column)
    if ($Column -eq '' -or $null -eq $Row) { return '' }
    $p = $Row.PSObject.Properties[$Column]
    if ($null -eq $p -or $null -eq $p.Value) { return '' }
    return ([string]$p.Value).Trim()
}

function Get-SsoUsers {
    <# 只读查询中央表。返回 employee_no / login_name / display_name / email / status / source。 #>
    param(
        [Parameter(Mandatory)][string]$Server,
        [Parameter(Mandatory)][string]$SqlDatabase,
        [Parameter(Mandatory)][string]$CredPath,
        [Parameter(Mandatory)][string]$CredName
    )
    if (-not (Test-Path -LiteralPath $CredPath)) {
        throw "凭据文件不存在: $CredPath"
    }
    [xml]$doc = Get-Content -LiteralPath $CredPath -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $CredName))
    if ($null -eq $node) { throw ("凭据文件 {0} 中找不到条目 '{1}'。" -f $CredPath, $CredName) }

    $user = [string]$node.UserName
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    $sqlCred = New-Object System.Data.SqlClient.SqlCredential($user, $secure)
    $cs = ('Server={0};Database={1};Encrypt=True;TrustServerCertificate=True;Application Name=sso-compare-upn;' -f $Server, $SqlDatabase)

    $conn = New-Object System.Data.SqlClient.SqlConnection($cs, $sqlCred)
    try {
        $conn.Open()
        $cmd = $conn.CreateCommand()
        $cmd.CommandTimeout = 120
        $cmd.CommandText = @'
SELECT employee_no, login_name, display_name, email, status, source
FROM dbo.CN_AME_SSO_User
ORDER BY login_name
'@
        $rd = $cmd.ExecuteReader()
        $list = New-Object System.Collections.Generic.List[object]
        try {
            while ($rd.Read()) {
                $list.Add([pscustomobject]@{
                    employee_no = $(if ($rd.IsDBNull(0)) { '' } else { [string]$rd.GetValue(0) })
                    login_name  = $(if ($rd.IsDBNull(1)) { '' } else { [string]$rd.GetValue(1) })
                    display_name = $(if ($rd.IsDBNull(2)) { '' } else { [string]$rd.GetValue(2) })
                    email       = $(if ($rd.IsDBNull(3)) { '' } else { [string]$rd.GetValue(3) })
                    status      = $(if ($rd.IsDBNull(4)) { '' } else { [string]$rd.GetValue(4) })
                    source      = $(if ($rd.IsDBNull(5)) { '' } else { [string]$rd.GetValue(5) })
                })
            }
        } finally {
            $rd.Close()
        }
        return $list
    } finally {
        $conn.Close()
        $conn.Dispose()
    }
}

function ConvertTo-Row {
    <# 把 Entra 导出的一行规范化成固定字段，后续不再摸原始列名。 #>
    param([object]$Row, [string]$UpnCol, [string]$OnPremCol, [string]$MailCol, [string]$EnabledCol)
    $upn = Get-CellValue -Row $Row -Column $UpnCol
    $prefix = ''
    if ($upn -ne '') {
        $at = $upn.IndexOf('@')
        if ($at -gt 0) { $prefix = $upn.Substring(0, $at) } else { $prefix = $upn }
    }
    return [pscustomobject]@{
        Upn      = $upn
        UpnPrefix = $prefix
        OnPrem   = (Get-CellValue -Row $Row -Column $OnPremCol)
        Mail     = (Get-CellValue -Row $Row -Column $MailCol)
        Enabled  = (Get-CellValue -Row $Row -Column $EnabledCol)
    }
}

# ---------------------------------------------------------------- 主流程

if (-not (Test-Path -LiteralPath $EntraCsvPath)) {
    Write-Step ("Entra 导出文件不存在: {0}" -f $EntraCsvPath) 'ERROR'
    exit 2
}

try {
    $entraRaw = @(Import-CsvAuto -Path $EntraCsvPath)
} catch {
    Write-Step ("读取 Entra 导出失败: {0}" -f $_.Exception.Message) 'ERROR'
    exit 2
}
if ($entraRaw.Count -eq 0) {
    Write-Step 'Entra 导出里没有任何行，检查文件是否导出成功。' 'ERROR'
    exit 2
}

$cols = @($entraRaw[0].PSObject.Properties.Name)
$colUpn = Get-CsvColumn -Columns $cols -Candidates @(
    'userPrincipalName', 'user principal name', 'UPN', 'upn', '用户主体名称', '用户主体名'
)
$colOnPrem = Get-CsvColumn -Columns $cols -Candidates @(
    'onPremisesSamAccountName', 'on-premises sam account name', 'onPremisesSam', 'sAMAccountName'
)
$colMail = Get-CsvColumn -Columns $cols -Candidates @('mail', 'email', '邮件', '电子邮件')
$colEnabled = Get-CsvColumn -Columns $cols -Candidates @('accountEnabled', 'account enabled', '已启用')

if ($colUpn -eq '') {
    Write-Step '找不到 UPN 列。实际列名如下，请把表头改成 userPrincipalName 后重跑：' 'ERROR'
    Write-Host ('    ' + ($cols -join ' | '))
    exit 2
}
if ($colOnPrem -eq '') {
    Write-Step '未找到 onPremisesSamAccountName 列：将只按 UPN 前缀判定，PATH2 无法识别。' 'WARN'
}

$entra = New-Object System.Collections.Generic.List[object]
foreach ($r in $entraRaw) {
    $entra.Add((ConvertTo-Row -Row $r -UpnCol $colUpn -OnPremCol $colOnPrem -MailCol $colMail -EnabledCol $colEnabled))
}
Write-Step ("Entra 记录 {0} 条；列映射 UPN={1} / onPremSam={2}" -f $entra.Count, $colUpn, $(if ($colOnPrem -eq '') { '(缺)' } else { $colOnPrem })) 'INFO'

# 建两个索引：按 UPN 前缀、按 onPremSamAccountName（均小写）。重复时保留第一条并计数。
$byPrefix = @{}
$byOnPrem = @{}
$dupPrefix = 0
$dupOnPrem = 0
foreach ($e in $entra) {
    if ($e.UpnPrefix -ne '') {
        $k = $e.UpnPrefix.ToLowerInvariant()
        if ($byPrefix.ContainsKey($k)) { $dupPrefix++ } else { $byPrefix[$k] = $e }
    }
    if ($e.OnPrem -ne '') {
        $k2 = $e.OnPrem.ToLowerInvariant()
        if ($byOnPrem.ContainsKey($k2)) { $dupOnPrem++ } else { $byOnPrem[$k2] = $e }
    }
}
if ($dupPrefix -gt 0) { Write-Step ("UPN 前缀重复 {0} 条（同名不同域），按第一条匹配" -f $dupPrefix) 'WARN' }
if ($dupOnPrem -gt 0) { Write-Step ("onPremisesSamAccountName 重复 {0} 条，按第一条匹配" -f $dupOnPrem) 'WARN' }

try {
    $users = @(Get-SsoUsers -Server $SqlServer -SqlDatabase $Database -CredPath $CredentialFile -CredName $SqlCredentialName)
} catch {
    Write-Step ("读中央表失败: {0}" -f $_.Exception.Message) 'ERROR'
    exit 3
}
Write-Step ("中央表记录 {0} 条" -f $users.Count) 'INFO'

$results = New-Object System.Collections.Generic.List[object]
$count = [ordered]@{
    OK = 0; OK_CASE = 0; PATH2 = 0; PATH3 = 0; NOT_IN_ENTRA = 0; NO_UPN = 0
}
$emptyLogin = 0

foreach ($u in $users) {
    $login = ([string]$u.login_name).Trim()
    if ($login -eq '') { $emptyLogin++; continue }
    if ($OnlyActive -and ([string]$u.status) -ne '1') { continue }

    $key = $login.ToLowerInvariant()
    $hit = $null
    if ($byOnPrem.ContainsKey($key)) { $hit = $byOnPrem[$key] }
    elseif ($byPrefix.ContainsKey($key)) { $hit = $byPrefix[$key] }

    $verdict = ''
    $note = ''
    if ($null -eq $hit) {
        $verdict = 'NOT_IN_ENTRA'
        $note = 'Entra 导出里没有这个登录名'
    } elseif ($hit.Upn -eq '') {
        $verdict = 'NO_UPN'
        $note = '该 Entra 记录缺 userPrincipalName'
    } elseif ($hit.OnPrem -ne '' -and $hit.OnPrem -ieq $login) {
        if ($hit.UpnPrefix -ieq $login) {
            if ($hit.UpnPrefix -ceq $login) { $verdict = 'OK'; $note = 'UPN 前缀与 login_name 一致' }
            else { $verdict = 'OK_CASE'; $note = '仅大小写不同' }
        } else {
            $verdict = 'PATH2'
            $note = ('UPN 前缀为 {0}，需取 onPremisesSamAccountName' -f $hit.UpnPrefix)
        }
    } else {
        $verdict = 'PATH3'
        if ($hit.OnPrem -eq '') {
            $note = '纯云账号（无 onPremSam），只能用 UPN 作 username'
        } else {
            $note = ('onPremSam={0} 与 login_name 也不一致' -f $hit.OnPrem)
        }
    }
    $count[$verdict]++

    $results.Add([pscustomobject]@{
        verdict      = $verdict
        employee_no  = $u.employee_no
        login_name   = $login
        display_name = $u.display_name
        status       = $u.status
        source       = $u.source
        email        = $u.email
        upn          = $(if ($null -eq $hit) { '' } else { $hit.Upn })
        upn_prefix   = $(if ($null -eq $hit) { '' } else { $hit.UpnPrefix })
        onprem_sam   = $(if ($null -eq $hit) { '' } else { $hit.OnPrem })
        note         = $note
    })
}

# Entra 有、中央表没有的账号（只给数量，不作为差异清单主体）
$dbKeys = @{}
foreach ($u in $users) {
    $n = ([string]$u.login_name).Trim().ToLowerInvariant()
    if ($n -ne '') { $dbKeys[$n] = $true }
}
$entraOnly = 0
foreach ($e in $entra) {
    $p = $e.UpnPrefix.ToLowerInvariant()
    $o = $e.OnPrem.ToLowerInvariant()
    $inDb = (($p -ne '') -and $dbKeys.ContainsKey($p)) -or (($o -ne '') -and $dbKeys.ContainsKey($o))
    if (-not $inDb) { $entraOnly++ }
}

if (-not (Test-Path -LiteralPath $OutDirectory)) {
    New-Item -ItemType Directory -Path $OutDirectory -Force | Out-Null
}
$stamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
$csvPath = Join-Path $OutDirectory ('upn_login_diff_{0}.csv' -f $stamp)
$results | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding UTF8

Write-Host ''
Write-Step '===== 比对结果 =====' 'OK'
Write-Host ('  OK（路 1 直接可用，大小写完全一致） : {0}' -f $count['OK'])
Write-Host ('  OK_CASE（路 1 可用，仅大小写不同）  : {0}' -f $count['OK_CASE'])
Write-Host ('  PATH2（需 Entra 下发 onPremSam）    : {0}' -f $count['PATH2'])
Write-Host ('  PATH3（只能用 UPN 作 username）     : {0}' -f $count['PATH3'])
Write-Host ('  NOT_IN_ENTRA（切过去登不上）        : {0}' -f $count['NOT_IN_ENTRA'])
Write-Host ('  NO_UPN（Entra 记录缺 UPN）          : {0}' -f $count['NO_UPN'])
Write-Host ('  Entra 有、中央表没有的账号           : {0}' -f $entraOnly)
if ($emptyLogin -gt 0) { Write-Host ('  中央表 login_name 为空的记录         : {0}' -f $emptyLogin) }
Write-Host ''
Write-Step ("明细已写入: {0}" -f $csvPath) 'OK'

$needLook = @($results | Where-Object { $_.verdict -in @('PATH2', 'PATH3', 'NOT_IN_ENTRA') })
if ($needLook.Count -gt 0) {
    Write-Host ''
    Write-Step ("需要人工确认的前 20 条（共 {0} 条）" -f $needLook.Count) 'WARN'
    $needLook | Select-Object -First 20 verdict, login_name, upn, onprem_sam, note |
        Format-Table -AutoSize | Out-String -Width 220 | Write-Host
}

Write-Host ''
Write-Step '口径提示：OK/OK_CASE 占绝大多数 → 走路 1（Keycloak 模板截掉 @域名）；PATH2 多 → 先实测 Entra 能否下发 onPremSam；PATH3 多 → 只能走 UPN 作 username，需同步改 UserMap 与授组口径。' 'INFO'

exit 0
