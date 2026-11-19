<#
.SYNOPSIS
    零改动切换 Microsoft Entra 邮箱账号：核查、默认组、清空本地用户、重置中央表、切换后校验。
.DESCRIPTION
    本脚本是《零改动切换 Microsoft Entra 邮箱账号》执行手册的唯一配套脚本，按 -Action 分步执行：

      Precheck          默认。只读。检查 IdP、用户名模板、groups mapper、默认组、用户结构、
                        中央表重复邮箱与保留名单，输出 keep_users / keep_usernames /
                        email_duplicates 三个文件。有阻断项时退出 2。
      SetDefaultGroups  把 app-msia、app-bol 设为 realm 默认组。不带 -Execute 只预演。
      Purge             删除 Keycloak 本地用户（默认 Scope=Local），随后全量登出并核对会话。
                        不带 -Execute 只预演；执行时必须用 -ExpectedKeepCount 明确核对后的
                        数据库保留人数，作为第二道闸门。
      ResetDb           可选。重置中央表 kc_user_id / pwd_set（保留名单除外）。切换后这两列
                        不再参与身份，不重置也不影响登录；只在需要把中央表恢复成"无绑定"状态时执行。
                        不带 -Execute 只预演。
      Verify            只读。核对默认组、groups mapper、用户结构、会话；中央表字段仅作参考。

    设计口径：
      1. 账号名取自 Entra 的 preferred_username（完整 UPN）。本脚本不写 CN_AME_SSO_UserMap，
         应用查不到映射时回落到 preferred_username，因此账号名自然等于邮箱。
      2. "本地用户"= federationLink 为空、username 不含 @、不是服务账号、不在保留名单。
         broker 建的用户 federationLink 同样为空，所以额外用 username 含 @ 识别并跳过，
         避免重复执行时误删已由 Entra 建档的账号。
      3. 保留名单 = 中央表 admin + source='MANUAL' + 邮箱重复（同一邮箱多行）的账号；
         另加 Keycloak 服务账号（serviceAccountClientId 非空或 username 以 service-account- 开头）。
         支持 -KeepFile / -KeepUsernames 追加人工确认的账号。
      4. 所有删除动作只调用 Keycloak 管理 REST 的 DELETE /users/{id}，不碰数据库业务表；
         中央表字段重置单独用 -Action ResetDb 执行。

    凭据：
      Keycloak 管理员口令不写死。用 -AdminPassword 传入；不传则交互式 Read-Host -AsSecureString。
      数据库口令从 credentials.xml（DPAPI）读取，默认条目 sso_sync_svc。

.NOTES
    文件: scripts/powershell/entra_email_cutover.ps1
    执行方式: 手工（管理员 PowerShell，建议在 Keycloak / 跳板机上执行）
    示例:
      .\entra_email_cutover.ps1 -Action Precheck
      .\entra_email_cutover.ps1 -Action Precheck -SkipCertCheck
      .\entra_email_cutover.ps1 -Action SetDefaultGroups -Execute
      .\entra_email_cutover.ps1 -Action Purge
      .\entra_email_cutover.ps1 -Action Purge -Execute -ExpectedKeepCount 40
      .\entra_email_cutover.ps1 -Action ResetDb
      .\entra_email_cutover.ps1 -Action ResetDb -Execute
      .\entra_email_cutover.ps1 -Action Verify
      回滚清理 UPN 账号:
      .\entra_email_cutover.ps1 -Action Purge -Scope Federated -Execute -ExpectedKeepCount 40
    退出码: 0=完成（有告警也算完成）
            2=前置校验/参数/保留人数闸门失败，未执行或未完成写入
            3=认证、Keycloak API 或数据库错误（含部分用户删除失败）
#>
[CmdletBinding()]
param(
    [ValidateSet('Precheck', 'SetDefaultGroups', 'Purge', 'ResetDb', 'Verify')]
    [string]$Action = 'Precheck',

    [string]$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',
    [string]$Realm = 'inalfa',

    # 管理员所在 realm：kcadmin 在 master；若管理员建在 inalfa 里就传 inalfa。
    [string]$AdminRealm = 'master',
    [string]$AdminClientId = 'admin-cli',
    [string]$AdminUsername = 'kcadmin',
    [string]$AdminPassword = '',
    [switch]$SkipCertCheck,

    [string]$IdpAlias = 'oidc',
    [string[]]$ClientIds = @('msia-prod', 'bol-prod'),

    # Purge 的范围：Local=本地短名用户（切换时用）；Federated=username 含 @ 的 UPN 账号（回滚清理用）
    [ValidateSet('Local', 'Federated')]
    [string]$Scope = 'Local',

    [switch]$Execute,

    # 执行 Purge 时必须填写：Precheck 输出的数据库保留人数（现场口径应为 40）。
    [int]$ExpectedKeepCount = 0,

    # 追加保留名单：文件一行一个 username；或直接传逗号/分号分隔的 username。
    [string]$KeepFile = '',
    [string]$KeepUsernames = '',

    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc',

    [string]$OutDirectory = 'C:\sso\tmp',
    [ValidateRange(50, 1000)]
    [int]$PageSize = 100
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
if ($SkipCertCheck) {
    # 仅用于内网自签证书的临时环境；生产优先把企业 CA 装进本机信任链。
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
}

$script:Base = $KeycloakBaseUrl.TrimEnd('/')
$script:Realm = $Realm
$script:AdminRealm = $AdminRealm
$script:AdminClientId = $AdminClientId
$script:AdminUser = $AdminUsername
$script:AdminPass = $AdminPassword
$script:KcToken = ''
$script:KcTokenExpiry = (Get-Date).AddMinutes(-1)
$script:SqlCredential = $null
$script:KeepInfo = $null
$script:Pass = 0
$script:Warn = 0
$script:Fatal = 0

# ---------------- 基础函数 ----------------

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

function Get-Prop {
    <# 安全读属性：对象为 $null、属性缺失、或值为 $null 时返回默认值。
       本脚本启用 StrictMode；Keycloak 的 JSON 只包含非空字段，裸访问会抛异常。 #>
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

function Add-Check {
    <# 统一记录检查结论：通过/告警/阻断。 #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][bool]$Ok,
        [string]$Detail = '',
        [switch]$Fatal
    )
    $suffix = if ($Detail -ne '') { ' — ' + $Detail } else { '' }
    if ($Ok) {
        $script:Pass++
        Write-Step ("[通过] {0}{1}" -f $Name, $suffix) 'OK'
    } elseif ($Fatal) {
        $script:Fatal++
        Write-Step ("[阻断] {0}{1}" -f $Name, $suffix) 'ERROR'
    } else {
        $script:Warn++
        Write-Step ("[告警] {0}{1}" -f $Name, $suffix) 'WARN'
    }
}

function Invoke-KcApi {
    <# Keycloak Admin REST 调用。返回解析后的 JSON；204/空响应返回 $null。
       失败时异常消息带 HTTP 状态码与响应体。 #>
    param(
        [Parameter(Mandatory)][ValidateSet('Get', 'Post', 'Put', 'Delete')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [string]$FormBody = ''
    )
    $req = [System.Net.HttpWebRequest]([System.Net.WebRequest]::Create($Uri))
    $req.Method = $Method.ToUpperInvariant()
    $req.Timeout = 30000
    $req.ReadWriteTimeout = 30000
    $req.Accept = 'application/json'
    $req.UserAgent = 'entra-email-cutover/1.0'
    if ($script:KcToken -ne '') {
        $req.Headers.Add('Authorization', ('Bearer ' + $script:KcToken))
    }
    if ($FormBody -ne '') {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($FormBody)
        $req.ContentType = 'application/x-www-form-urlencoded'
        $req.ContentLength = $bytes.Length
        $stream = $req.GetRequestStream()
        try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
    } elseif ($Method -eq 'POST' -or $Method -eq 'PUT') {
        $req.ContentLength = 0
    }

    try {
        $resp = $req.GetResponse()
    } catch [System.Net.WebException] {
        $status = 0
        $detail = $_.Exception.Message
        if ($null -ne $_.Exception.Response) {
            try {
                $status = [int]$_.Exception.Response.StatusCode
                $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream(), [System.Text.Encoding]::UTF8)
                $detail = $sr.ReadToEnd()
                $sr.Dispose()
            } catch { }
        }
        $ex = New-Object System.Exception((
            'Keycloak {0} {1} 失败 (HTTP {2}): {3}' -f $Method.ToUpperInvariant(), $Uri, $status, $detail))
        $ex.Data['HttpStatus'] = $status
        throw $ex
    }

    try {
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $text = $sr.ReadToEnd()
        $sr.Dispose()
    } finally {
        $resp.Close()
    }
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return ($text | ConvertFrom-Json)
}

function Get-KcAdminToken {
    param(
        [Parameter(Mandatory)][string]$User,
        [Parameter(Mandatory)][string]$Password
    )
    $form = @(
        'grant_type=password'
        ('client_id=' + [uri]::EscapeDataString($script:AdminClientId))
        ('username=' + [uri]::EscapeDataString($User))
        ('password=' + [uri]::EscapeDataString($Password))
    ) -join '&'
    $resp = Invoke-KcApi -Method Post `
        -Uri ("{0}/realms/{1}/protocol/openid-connect/token" -f $script:Base, $script:AdminRealm) `
        -FormBody $form
    $tok = [string](Get-Prop $resp 'access_token' '')
    if ($tok -eq '') {
        throw 'token 响应里没有 access_token（检查 admin realm / client_id / 用户名密码；admin-cli 需启用 Direct Access Grants）。'
    }
    return [pscustomobject]@{
        Token     = $tok
        ExpiresIn = [int](Get-Prop $resp 'expires_in' 0)
    }
}

function Set-KcToken {
    # 取新 token 前清掉旧 token，避免 token 端点收到过期 Bearer 头。
    $script:KcToken = ''
    $t = Get-KcAdminToken -User $script:AdminUser -Password $script:AdminPass
    $script:KcToken = $t.Token
    if ($t.ExpiresIn -gt 120) { $ttl = $t.ExpiresIn - 60 } else { $ttl = 30 }
    $script:KcTokenExpiry = (Get-Date).AddSeconds($ttl)
    return $t.ExpiresIn
}

function Assert-KcToken {
    if ($script:KcToken -ne '' -and (Get-Date) -lt $script:KcTokenExpiry) { return }
    Write-Step '管理员 token 即将到期，重新获取...'
    [void](Set-KcToken)
}

# ---------------- Keycloak 查询 ----------------

function Get-KcAllGroups {
    <# 遍历完整组树，返回 id/name/path/parentPath 的扁平列表（用于判定组是否顶层）。 #>
    $result = New-Object System.Collections.Generic.List[object]
    $queue = New-Object System.Collections.Generic.Queue[object]
    $seen = @{}

    $top = @(Invoke-KcApi -Method Get -Uri (
        '{0}/admin/realms/{1}/groups?briefRepresentation=false&max=500' -f $script:Base, $script:Realm) |
        Where-Object { $null -ne $_ })
    foreach ($g in $top) {
        $queue.Enqueue([pscustomobject]@{ Group = $g; ParentPath = '' })
    }

    while ($queue.Count -gt 0) {
        $node = $queue.Dequeue()
        $g = $node.Group
        $id = [string](Get-Prop $g 'id' '')
        if ($id -eq '' -or $seen.ContainsKey($id)) { continue }
        $seen[$id] = $true

        $name = [string](Get-Prop $g 'name' '')
        $parent = [string]$node.ParentPath
        $path = [string](Get-Prop $g 'path' '')
        if ($path -eq '') {
            if ($parent -eq '') { $path = '/' + $name } else { $path = $parent + '/' + $name }
        }
        $result.Add([pscustomobject]@{ Id = $id; Name = $name; Path = $path; ParentPath = $parent })

        $subsProp = $g.PSObject.Properties['subGroups']
        if ($null -ne $subsProp) {
            $subs = @($subsProp.Value | Where-Object { $null -ne $_ })
        } else {
            try {
                $subs = @(Invoke-KcApi -Method Get -Uri (
                    '{0}/admin/realms/{1}/groups/{2}/children?briefRepresentation=false&max=500' -f
                    $script:Base, $script:Realm, $id) | Where-Object { $null -ne $_ })
            } catch {
                if ([int](Get-Prop $_.Exception.Data 'HttpStatus' 0) -eq 404) { $subs = @() }
                else { throw }
            }
        }
        foreach ($s in $subs) {
            $queue.Enqueue([pscustomobject]@{ Group = $s; ParentPath = $path })
        }
    }
    return , $result
}

function Resolve-TopLevelGroup {
    <# 目标组必须精确是顶层 /<name>。同名组出现在别的路径（含大小写不同）一律阻断。 #>
    param(
        [Parameter(Mandatory)][object[]]$AllGroups,
        [Parameter(Mandatory)][string]$Path
    )
    $p = $Path.Trim()
    if (-not $p.StartsWith('/')) { $p = '/' + $p }
    if ($p.Length -gt 1) { $p = $p.TrimEnd('/') }
    $name = $p.Substring(1)
    if ($name.Contains('/')) {
        throw ("只允许顶层组：'{0}' 是嵌套组；应用按精确字符串匹配组名，子组成员仍会 403。" -f $p)
    }

    $exact = @($AllGroups | Where-Object { [string]$_.Path -ceq $p })
    $conflict = @($AllGroups | Where-Object {
        [string]$_.Name -ieq $name -and [string]$_.Path -cne $p
    })
    if ($conflict.Count -gt 0) {
        $paths = ($conflict | ForEach-Object { $_.Path }) -join '、'
        throw ("组名 '{0}' 存在非顶层/大小写不一致的同名组：{1}。请先在控制台改正组结构，本轮不做写入。" -f $name, $paths)
    }
    if ($exact.Count -eq 0) {
        throw ("顶层组 '{0}' 不存在。请先按 realm 基线创建顶层组，不要临时建空组。" -f $p)
    }
    if ($exact.Count -gt 1) {
        throw ("顶层组 '{0}' 匹配到 {1} 个对象（数据异常），请先在控制台核对。" -f $p, $exact.Count)
    }
    return $exact[0]
}

function Get-KcDefaultGroups {
    $list = @(Invoke-KcApi -Method Get -Uri (
        '{0}/admin/realms/{1}/default-groups' -f $script:Base, $script:Realm) | Where-Object { $null -ne $_ })
    return , $list
}

function Get-KcAllUsers {
    <# 拉全量用户（briefRepresentation=false，含 federationLink / serviceAccountClientId）。 #>
    $list = New-Object System.Collections.Generic.List[object]
    $first = 0
    $pages = 0
    while ($true) {
        $pages++
        if ($pages -gt 200) { throw '用户分页超过 200 页，疑似接口异常，停止。' }
        $uri = '{0}/admin/realms/{1}/users?briefRepresentation=false&first={2}&max={3}' -f
            $script:Base, $script:Realm, $first, $PageSize
        $page = @(Invoke-KcApi -Method Get -Uri $uri | Where-Object { $null -ne $_ })
        if ($page.Count -eq 0) { break }
        foreach ($u in $page) { $list.Add($u) }
        if ($page.Count -lt $PageSize) { break }
        $first += $PageSize
    }
    return , $list
}

function Get-KcClient {
    param([Parameter(Mandatory)][string]$ClientId)
    $uri = '{0}/admin/realms/{1}/clients?clientId={2}' -f
        $script:Base, $script:Realm, [uri]::EscapeDataString($ClientId)
    $list = @(Invoke-KcApi -Method Get -Uri $uri | Where-Object { $null -ne $_ })
    $hits = @($list | Where-Object { [string](Get-Prop $_ 'clientId' '') -eq $ClientId })
    if ($hits.Count -eq 0) { return $null }
    return $hits[0]
}

function Get-GroupsMapperStatus {
    <# 检查 client 直属 mapper 里的 Group Membership：claim 名、full.path、id.token.claim。
       返回 State = OK / NOT_ON_CLIENT / BAD。 #>
    param($Client)
    if ($null -eq $Client) {
        return [pscustomobject]@{ State = 'MISSING_CLIENT'; Detail = 'client 不存在' }
    }
    $cid = [string](Get-Prop $Client 'id' '')
    $uri = '{0}/admin/realms/{1}/clients/{2}/protocol-mappers/models' -f $script:Base, $script:Realm, $cid
    $mappers = @(Invoke-KcApi -Method Get -Uri $uri | Where-Object { $null -ne $_ })
    $gm = @($mappers | Where-Object { [string](Get-Prop $_ 'protocolMapper' '') -eq 'oidc-group-membership-mapper' })
    if ($gm.Count -eq 0) {
        return [pscustomobject]@{
            State  = 'NOT_ON_CLIENT'
            Detail = 'client 直属 mapper 没有 Group Membership（可能在 client scope；需按文档人工核对）'
        }
    }
    $m = $gm[0]
    $cfg = Get-Prop $m 'config' $null
    $claim = [string](Get-Prop $cfg 'claim.name' '')
    $full = [string](Get-Prop $cfg 'full.path' '')
    $idToken = [string](Get-Prop $cfg 'id.token.claim' '')
    $problems = New-Object System.Collections.Generic.List[string]
    if ($claim -ne 'groups') { $problems.Add(("claim.name={0}（应为 groups）" -f $claim)) }
    if ($full -ne 'false') { $problems.Add(("full.path={0}（应为 false，否则令牌是 /app-msia）" -f $full)) }
    if ($idToken -ne 'true') { $problems.Add(("id.token.claim={0}（应为 true）" -f $idToken)) }
    if ($problems.Count -gt 0) {
        return [pscustomobject]@{ State = 'BAD'; Detail = ($problems -join '；') }
    }
    return [pscustomobject]@{ State = 'OK'; Detail = 'claim=groups, full.path=false, id.token.claim=true' }
}

# ---------------- 数据库 ----------------

function Get-DbCredential {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("凭据文件不存在: {0}。" -f $Path)
    }
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $Name))
    if ($null -eq $node) { throw ("凭据文件中找不到条目 '{0}'。" -f $Name) }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    return New-Object System.Management.Automation.PSCredential(([string]$node.UserName), $secure)
}

function Invoke-SsoSql {
    <# 执行 SQL；优先 Invoke-Sqlcmd，回退 Microsoft.Data.SqlClient。
       允许用一条批处理做 UPDATE 后 SELECT @@ROWCOUNT（返回结果集）。 #>
    param(
        [Parameter(Mandatory)][string]$Query,
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    if (Get-Command -Name Invoke-Sqlcmd -ErrorAction SilentlyContinue) {
        $splat = @{
            ServerInstance = $SqlServer
            Database       = $Database
            Query          = $Query
            QueryTimeout   = 180
            ErrorAction    = 'Stop'
            Username       = $Credential.UserName
            Password       = $Credential.GetNetworkCredential().Password
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
                $SqlServer, $Database,
                $Credential.UserName, $Credential.GetNetworkCredential().Password)
    $conn = New-Object Microsoft.Data.SqlClient.SqlConnection($connStr)
    try {
        $conn.Open()
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $Query
        $cmd.CommandTimeout = 180
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

function Get-SqlCredential {
    if ($null -eq $script:SqlCredential) {
        $script:SqlCredential = Get-DbCredential -Path $CredentialFile -Name $SqlCredentialName
    }
    return $script:SqlCredential
}

function ConvertTo-SqlNvarcharList {
    <# 把 username 列表转成 SQL 的 N'..' 列表；单引号转义。空列表给一个不可能匹配的值。 #>
    param([string[]]$Values)
    $escaped = @($Values | Where-Object { $_ -ne '' } | ForEach-Object { "N'" + ($_ -replace "'", "''") + "'" })
    if ($escaped.Count -eq 0) { return "N'__EMPTY_KEEP_LIST__'" }
    return ($escaped -join ', ')
}

function Get-DbStats {
    $q = @'
SELECT
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User) AS total_rows,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User
      WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> '') AS email_filled,
    (SELECT COUNT(DISTINCT LTRIM(RTRIM(LOWER(email)))) FROM dbo.CN_AME_SSO_User
      WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> '') AS distinct_email,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_UserMap) AS usermap_rows,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE kc_user_id IS NOT NULL) AS kc_id_filled,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE pwd_set = 1) AS pwd_set_1,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User
      WHERE email IS NOT NULL AND LEN(LTRIM(RTRIM(email))) > 50) AS email_over_50
'@
    $rows = @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
    if ($rows.Count -eq 0) { throw '中央表统计查询没有返回结果。' }
    return $rows[0]
}

function Get-DuplicateEmailRows {
    $q = @'
;WITH d AS (
    SELECT LTRIM(RTRIM(LOWER(email))) AS email_key
    FROM dbo.CN_AME_SSO_User
    WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> ''
    GROUP BY LTRIM(RTRIM(LOWER(email)))
    HAVING COUNT(*) > 1
)
SELECT u.employee_no, u.login_name, u.display_name, u.email, u.source, u.status,
       d.email_key
FROM dbo.CN_AME_SSO_User u
JOIN d ON LTRIM(RTRIM(LOWER(u.email))) = d.email_key
ORDER BY d.email_key, u.employee_no
'@
    return @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
}

function Get-DuplicateEmailGroups {
    <# 按邮箱汇总撞车组，供手册 2.3 的四组核对使用。 #>
    $q = @'
;WITH d AS (
    SELECT LTRIM(RTRIM(LOWER(email))) AS email_key, COUNT(*) AS user_count
    FROM dbo.CN_AME_SSO_User
    WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> ''
    GROUP BY LTRIM(RTRIM(LOWER(email)))
    HAVING COUNT(*) > 1
)
SELECT d.email_key,
       d.user_count,
       STUFF((
           SELECT ', ' + u2.login_name + '(' + u2.source + ',' + CAST(u2.status AS varchar(10)) + ')'
           FROM dbo.CN_AME_SSO_User u2
           WHERE LTRIM(RTRIM(LOWER(u2.email))) = d.email_key
           ORDER BY u2.login_name
           FOR XML PATH(''), TYPE
       ).value('.', 'nvarchar(max)'), 1, 2, '') AS login_names
FROM d
ORDER BY d.user_count DESC, d.email_key
'@
    return @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
}

function Get-OverlongUsers {
    <# 邮箱/UPN 长度预检：BOL 本地 username 为 50，MSIA 为 varchar(100)。
       中央表 email 作为 UPN 的现场代理值；最终以 Entra 导出的 userPrincipalName 为准。 #>
    $q = @'
SELECT employee_no, login_name, display_name, email, source, status,
       LEN(LTRIM(RTRIM(email))) AS email_len
FROM dbo.CN_AME_SSO_User
WHERE email IS NOT NULL
  AND LEN(LTRIM(RTRIM(email))) > 50
ORDER BY email_len DESC, login_name
'@
    return @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
}

function Get-KeepRows {
    $q = @'
;WITH d AS (
    SELECT LTRIM(RTRIM(LOWER(email))) AS email_key
    FROM dbo.CN_AME_SSO_User
    WHERE email IS NOT NULL AND LTRIM(RTRIM(email)) <> ''
    GROUP BY LTRIM(RTRIM(LOWER(email)))
    HAVING COUNT(*) > 1
)
SELECT u.employee_no, u.login_name, u.display_name, u.email, u.source, u.status,
       CASE
           WHEN u.employee_no = 'admin' THEN 'ADMIN'
           WHEN u.source = 'MANUAL'     THEN 'MANUAL'
           ELSE 'SHARED_EMAIL'
       END AS keep_reason,
       d.email_key
FROM dbo.CN_AME_SSO_User u
LEFT JOIN d ON LTRIM(RTRIM(LOWER(u.email))) = d.email_key
WHERE u.employee_no = 'admin'
   OR u.source = 'MANUAL'
   OR d.email_key IS NOT NULL
ORDER BY keep_reason, u.employee_no
'@
    return @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
}

function Get-KeepInfo {
    <# 保留名单 = 中央表规则 + 文件/参数追加 + admin 硬保底。
       返回 Set（小写 username）、Rows（数据库行）、DbCount（数据库规则命中行数）、Extras。 #>
    if ($null -ne $script:KeepInfo) { return $script:KeepInfo }

    $rows = @(Get-KeepRows)
    $set = @{}
    $list = New-Object System.Collections.Generic.List[object]
    $dbCount = 0

    foreach ($r in $rows) {
        $u = ([string](Get-Prop $r 'login_name' '')).Trim()
        if ($u -eq '') { continue }
        $dbCount++
        $key = $u.ToLowerInvariant()
        if (-not $set.ContainsKey($key)) {
            $set[$key] = $true
            $list.Add($r)
        }
    }
    if (-not $set.ContainsKey('admin')) {
        $set['admin'] = $true
        Write-Step '中央表保留名单未包含 admin，已强制加入（admin 是唯一应急入口）。' 'WARN'
    }

    $extras = New-Object System.Collections.Generic.List[string]
    if ($KeepFile.Trim() -ne '') {
        if (-not (Test-Path -LiteralPath $KeepFile)) { throw ("KeepFile 不存在: {0}" -f $KeepFile) }
        foreach ($line in (Get-Content -LiteralPath $KeepFile)) {
            $v = ([string]$line).Trim()
            if ($v -ne '' -and -not $v.StartsWith('#')) { $extras.Add($v) }
        }
    }
    if ($KeepUsernames.Trim() -ne '') {
        foreach ($v in ($KeepUsernames -split '[,;]')) {
            if ($v.Trim() -ne '') { $extras.Add($v.Trim()) }
        }
    }
    foreach ($v in $extras) {
        $key = $v.ToLowerInvariant()
        if (-not $set.ContainsKey($key)) {
            $set[$key] = $true
            Write-Step ("追加保留账号: {0}" -f $v)
        }
    }

    $script:KeepInfo = [pscustomobject]@{
        Set     = $set
        Rows    = $list
        DbCount = $dbCount
        Extras  = @($extras | Select-Object -Unique)
    }
    return $script:KeepInfo
}

function Test-IsServiceAccount {
    param($User)
    $svc = [string](Get-Prop $User 'serviceAccountClientId' '')
    $name = [string](Get-Prop $User 'username' '')
    return ($svc -ne '') -or ($name -like 'service-account-*')
}

# ---------------- Action: Precheck ----------------

function Invoke-Precheck {
    Write-Step ("==== 只读核查  {0}  realm={1} ====" -f $script:Base, $script:Realm)

    # 1. realm
    Write-Step '--- 1. realm 设置 ---'
    $realmRep = $null
    try {
        $realmRep = Invoke-KcApi -Method Get -Uri ("{0}/admin/realms/{1}" -f $script:Base, $script:Realm)
    } catch {
        Add-Check -Name '读取 realm' -Ok $false -Detail $_.Exception.Message -Fatal
        return 3
    }
    $dupEmail = [bool](Get-Prop $realmRep 'duplicateEmailsAllowed' $false)
    $emailAsUser = [bool](Get-Prop $realmRep 'registrationEmailAsUsername' $false)
    $dupDetail = if ($dupEmail) {
        'duplicateEmailsAllowed=true：允许重复邮箱；身份仍按 username(UPN) 区分'
    } else {
        'duplicateEmailsAllowed=false：多人共用同一邮箱时，第二个人首登会报 email already exists；处理见手册 2.2'
    }
    $emailDetail = if ($emailAsUser) {
        'registrationEmailAsUsername=true：新建用户取 email，不是 preferred_username(UPN)；只有 mail=UPN 时才等效，需现场确认'
    } else {
        'registrationEmailAsUsername=false：用户名按模板/preferred_username 生成'
    }
    Add-Check -Name 'realm 可读' -Ok $true -Detail ("realm={0}" -f (Get-Prop $realmRep 'realm' $script:Realm))
    Add-Check -Name 'Duplicate emails' -Ok $dupEmail -Detail $dupDetail
    Add-Check -Name 'Email as username' -Ok (-not $emailAsUser) -Detail $emailDetail

    # 2. IdP
    Write-Step '--- 2. Entra Identity Provider ---'
    $idp = $null
    try {
        $idp = Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/identity-provider/instances/{2}' -f $script:Base, $script:Realm, $IdpAlias)
    } catch {
        $st = [int](Get-Prop $_.Exception.Data 'HttpStatus' 0)
        if ($st -eq 404) {
            Add-Check -Name ("IdP '{0}' 存在" -f $IdpAlias) -Ok $false `
                -Detail '未找到；请先按 entra-broker-setup-runbook.md 配好 IdP' -Fatal
            return 2
        }
        Add-Check -Name ("读取 IdP '{0}'" -f $IdpAlias) -Ok $false -Detail $_.Exception.Message -Fatal
        return 3
    }
    $idpEnabled = [bool](Get-Prop $idp 'enabled' $false)
    $hideOnLogin = [bool](Get-Prop $idp 'hideOnLoginPage' $false)
    $firstFlow = [string](Get-Prop $idp 'firstBrokerLoginFlowAlias' '')
    Add-Check -Name ("IdP '{0}' 已启用" -f $IdpAlias) -Ok $idpEnabled -Detail ("enabled={0}" -f $idpEnabled) -Fatal
    Add-Check -Name '登录页显示 Entra ID 按钮' -Ok (-not $hideOnLogin) -Detail ("hideOnLoginPage={0}" -f $hideOnLogin)
    Add-Check -Name '首次登录流程已替换默认流程' -Ok ($firstFlow -ne '' -and $firstFlow -ne 'first broker login') `
        -Detail ("firstBrokerLoginFlowAlias='{0}'；默认流程会要求补资料/邮箱验证，批量首登会被拦" -f $firstFlow)

    # 3. IdP username mapper
    Write-Step '--- 3. 用户名模板（决定账号名是不是完整 UPN） ---'
    $idpMappers = @()
    try {
        $idpMappers = @(Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/identity-provider/instances/{2}/mappers' -f
            $script:Base, $script:Realm, $IdpAlias) | Where-Object { $null -ne $_ })
    } catch {
        Add-Check -Name '读取 IdP mappers' -Ok $false -Detail $_.Exception.Message -Fatal
    }
    $userMappers = @($idpMappers | Where-Object {
        [string](Get-Prop $_ 'identityProviderMapper' '') -eq 'oidc-username-idp-mapper'
    })
    if ($userMappers.Count -eq 0) {
        Add-Check -Name '用户名模板' -Ok $false `
            -Detail '未显式配置 Username Template Importer。Keycloak 默认取 preferred_username（完整 UPN），效果等同本方案；但本方案要求显式配置以便审计，请按手册 1.2 添加模板后再跑一次。'
    } else {
        foreach ($m in $userMappers) {
            $cfg = Get-Prop $m 'config' $null
            $tpl = [string](Get-Prop $cfg 'template' '')
            $target = [string](Get-Prop $cfg 'target' '')
            $badLocalpart = $tpl -match '\|\s*localpart'
            $badAlias = $tpl -match '\$\{ALIAS\}'
            $okTpl = (-not $badLocalpart) -and (-not $badAlias) -and ($tpl -match '\$\{CLAIM\.preferred_username\}')
            Add-Check -Name ("用户名模板 '{0}'" -f ([string](Get-Prop $m 'name' ''))) -Ok $okTpl `
                -Detail ("template='{0}', target='{1}'；本方案要求完整 UPN，不能带 localpart 或 ALIAS 前缀" -f $tpl, $target) -Fatal
            Add-Check -Name '用户名模板 Target' -Ok ($target -ne 'BROKER_ID') `
                -Detail ("target='{0}'；BROKER_ID 会改联邦关联键，本方案不要用" -f $target) -Fatal
        }
    }

    # 4. 准入组与默认组
    Write-Step '--- 4. 组 ---'
    $allGroups = $null
    try {
        $allGroups = Get-KcAllGroups
    } catch {
        Add-Check -Name '读取组树' -Ok $false -Detail $_.Exception.Message -Fatal
    }
    $groupIds = @{}
    if ($null -ne $allGroups) {
        foreach ($gn in @('app-msia', 'app-bol')) {
            try {
                $g = Resolve-TopLevelGroup -AllGroups $allGroups -Path ('/' + $gn)
                $groupIds[$gn] = $g.Id
                Add-Check -Name ("顶层组 {0}" -f $gn) -Ok $true -Detail ("id={0}" -f $g.Id)
            } catch {
                Add-Check -Name ("顶层组 {0}" -f $gn) -Ok $false -Detail $_.Exception.Message -Fatal
            }
        }
    }
    $defaults = @()
    try {
        $defaults = Get-KcDefaultGroups
        $defaultNames = @($defaults | ForEach-Object { [string](Get-Prop $_ 'name' '') })
        $hasBoth = ($defaultNames -contains 'app-msia') -and ($defaultNames -contains 'app-bol')
        Add-Check -Name '默认组包含 app-msia + app-bol' -Ok $hasBoth `
            -Detail ("当前默认组: {0}" -f (($defaultNames -join ', ') -replace '^$', '(空)'))
    } catch {
        Add-Check -Name '读取默认组' -Ok $false -Detail $_.Exception.Message -Fatal
    }

    # 5. client groups mapper
    Write-Step '--- 5. 应用 client 的 groups mapper（403 高发点） ---'
    foreach ($cid in $ClientIds) {
        $client = $null
        try {
            $client = Get-KcClient -ClientId $cid
        } catch {
            Add-Check -Name ("client {0}" -f $cid) -Ok $false -Detail $_.Exception.Message -Fatal
            continue
        }
        if ($null -eq $client) {
            Add-Check -Name ("client {0}" -f $cid) -Ok $false -Detail '未找到该 clientId' -Fatal
            continue
        }
        $st = Get-GroupsMapperStatus -Client $client
        Add-Check -Name ("client {0} 的 groups mapper" -f $cid) -Ok ($st.State -eq 'OK') `
            -Detail $st.Detail -Fatal:($st.State -eq 'BAD')
    }

    # 6. 用户结构
    Write-Step '--- 6. Keycloak 用户结构 ---'
    $users = @()
    try {
        $users = Get-KcAllUsers
        $total = $users.Count
        $local = @($users | Where-Object {
            [string](Get-Prop $_ 'federationLink' '') -eq '' -and
            -not (Test-IsServiceAccount $_)
        }).Count
        $fed = @($users | Where-Object { [string](Get-Prop $_ 'federationLink' '') -ne '' }).Count
        $atUsers = @($users | Where-Object {
            ([string](Get-Prop $_ 'username' '')).Contains('@') -and -not (Test-IsServiceAccount $_)
        }).Count
        $svc = @($users | Where-Object { Test-IsServiceAccount $_ }).Count
        Write-Step ("用户总数 {0}：本地候选 {1}，LDAP 联邦 {2}，username 含 @ {3}，服务账号 {4}" -f
            $total, $local, $fed, $atUsers, $svc)
        Add-Check -Name '已有 Entra 建档账号（username 含 @）' -Ok ($atUsers -eq 0) `
            -Detail ("{0} 个；Purge 会跳过这些账号，回滚清理前先确认来源" -f $atUsers)
    } catch {
        Add-Check -Name '读取用户列表' -Ok $false -Detail $_.Exception.Message -Fatal
    }

    # 7. 中央表
    Write-Step '--- 7. 中央表 CN_AME_SSO_User ---'
    $keepInfo = $null
    try {
        $s = Get-DbStats
        Write-Step ("总行 {0}，邮箱有值 {1}，distinct 邮箱 {2}，UserMap {3} 行" -f
            $s.total_rows, $s.email_filled, $s.distinct_email, $s.usermap_rows)
        Write-Step ("kc_user_id 有值 {0}，pwd_set=1 {1}，邮箱长度>50 {2}" -f
            $s.kc_id_filled, $s.pwd_set_1, $s.email_over_50)

        $dups = @(Get-DuplicateEmailRows)
        $distinctDup = @($dups | ForEach-Object { [string](Get-Prop $_ 'email_key' '') } | Select-Object -Unique).Count
        Write-Step ("重复邮箱：{0} 行，涉及 {1} 个邮箱（重复行数 = 总行 - distinct = {2}）" -f
            $dups.Count, $distinctDup, ([int]$s.total_rows - [int]$s.distinct_email))
        Add-Check -Name '重复邮箱已盘点' -Ok ($dups.Count -eq 0) `
            -Detail ("{0} 行；这些账号会保留在本地，不参与本次清空。处理原则见手册第 2 节" -f $dups.Count)

        $groups = @(Get-DuplicateEmailGroups)
        if ($groups.Count -gt 0) {
            Write-Step '撞车组（按人数降序）:'
            $groups | ForEach-Object {
                Write-Step ("  {0}  {1} 人  {2}" -f
                    [string](Get-Prop $_ 'email_key' ''), [string](Get-Prop $_ 'user_count' ''),
                    [string](Get-Prop $_ 'login_names' '')) 'WARN'
            }
        }
        $long = @(Get-OverlongUsers)
        Add-Check -Name '邮箱/UPN 长度不超过 BOL 上限 50' -Ok ($long.Count -eq 0) `
            -Detail ("{0} 行长度>50；BOL 本地 username 为 50，MSIA 为 varchar(100)。超长时 BOL 建档是未捕获的 500。最终以 Entra 导出的 userPrincipalName 为准" -f $long.Count)
        $over100 = @($long | Where-Object { [int](Get-Prop $_ 'email_len' 0) -gt 100 })
        Add-Check -Name '邮箱/UPN 长度不超过 MSIA 上限 100' -Ok ($over100.Count -eq 0) `
            -Detail ("{0} 行长度>100；MSIA 本地 username 为 varchar(100)" -f $over100.Count)

        $keepInfo = Get-KeepInfo
        Write-Step ("数据库保留名单 {0} 行" -f $keepInfo.DbCount)
        Add-Check -Name '保留名单非空' -Ok ($keepInfo.DbCount -gt 0) -Detail ("DbCount={0}" -f $keepInfo.DbCount) -Fatal
        Add-Check -Name '保留名单口径（现场应为 40：admin + 39）' -Ok ($keepInfo.DbCount -eq 40) `
            -Detail ("当前 {0}；不等于 40 时不要直接执行 Purge，先按手册 2.3 解释差额" -f $keepInfo.DbCount)
    } catch {
        Add-Check -Name '中央表检查' -Ok $false -Detail $_.Exception.Message -Fatal
    }

    # 8. 计划任务
    Write-Step '--- 8. 定期任务与手工误执行风险 ---'
    try {
        $task = Get-ScheduledTask -TaskName 'SSO_AD_Import' -ErrorAction Stop
        $taskArgs = @($task.Actions | ForEach-Object { [string]$_.Arguments }) -join ' '
        $hasSkip = $taskArgs -match '-SkipKeycloakSync'
        Add-Check -Name 'SSO_AD_Import 已停止串联 Keycloak' -Ok $hasSkip `
            -Detail ("State={0}；Arguments='{1}'。未加 -SkipKeycloakSync 会在下一轮触发时按 login_name 重建本地短名账号" -f $task.State, $taskArgs)
    } catch {
        Add-Check -Name '未发现 SSO_AD_Import 定期任务' -Ok $true `
            -Detail ('现场确认该任务未部署：只剩 sync_ad_to_sso.ps1 / sync_sso_to_keycloak.ps1 被手工误执行的风险。' +
                'sync_sso_to_keycloak.ps1 已内置拒绝保护（Keycloak 多数用户为邮箱格式时退出 2），无需再改任务')
    }

    # 9. 输出文件
    Write-Step '--- 9. 输出清单 ---'
    if ($null -ne $keepInfo) {
        try {
            if (-not (Test-Path -LiteralPath $OutDirectory)) {
                New-Item -ItemType Directory -Force -Path $OutDirectory | Out-Null
            }
            $ts = Get-Date -Format 'yyyyMMdd_HHmmss'

            $keepCsv = Join-Path $OutDirectory ("keep_users_{0}.csv" -f $ts)
            $keepInfo.Rows | Select-Object employee_no, login_name, display_name, email, source, status, keep_reason |
                Export-Csv -LiteralPath $keepCsv -NoTypeInformation -Encoding UTF8

            $keepTxt = Join-Path $OutDirectory ("keep_usernames_{0}.txt" -f $ts)
            @($keepInfo.Rows | ForEach-Object { [string](Get-Prop $_ 'login_name' '') } |
                Where-Object { $_ -ne '' } | Select-Object -Unique) |
                Set-Content -LiteralPath $keepTxt -Encoding UTF8

            $dupCsv = Join-Path $OutDirectory ("email_duplicates_{0}.csv" -f $ts)
            @(Get-DuplicateEmailRows) |
                Select-Object employee_no, login_name, display_name, email, source, status, email_key |
                Export-Csv -LiteralPath $dupCsv -NoTypeInformation -Encoding UTF8

            $groupCsv = Join-Path $OutDirectory ("email_collision_groups_{0}.csv" -f $ts)
            @(Get-DuplicateEmailGroups) |
                Select-Object email_key, user_count, login_names |
                Export-Csv -LiteralPath $groupCsv -NoTypeInformation -Encoding UTF8

            $longCsv = Join-Path $OutDirectory ("overlong_usernames_{0}.csv" -f $ts)
            @(Get-OverlongUsers) |
                Select-Object employee_no, login_name, display_name, email, email_len, source, status |
                Export-Csv -LiteralPath $longCsv -NoTypeInformation -Encoding UTF8

            Write-Step ("保留名单 CSV : {0}" -f $keepCsv) 'OK'
            Write-Step ("保留名单 TXT : {0}" -f $keepTxt) 'OK'
            Write-Step ("重复邮箱 CSV: {0}" -f $dupCsv) 'OK'
            Write-Step ("撞车组 CSV  : {0}" -f $groupCsv) 'OK'
            Write-Step ("超长清单 CSV: {0}" -f $longCsv) 'OK'
        } catch {
            Add-Check -Name '输出清单文件' -Ok $false -Detail $_.Exception.Message
        }
    }

    Write-Host ''
    Write-Host '================ 核查汇总 ================' -ForegroundColor Cyan
    Write-Host ("通过 {0} / 告警 {1} / 阻断 {2}" -f $script:Pass, $script:Warn, $script:Fatal)
    if ($script:Fatal -gt 0) {
        Write-Host '结论: NO-GO —— 先处理阻断项，不要进入清空步骤。' -ForegroundColor Red
        return 2
    }
    Write-Host '结论: GO（告警项按手册逐条确认后继续）' -ForegroundColor Green
    return 0
}

# ---------------- Action: SetDefaultGroups ----------------

function Invoke-SetDefaultGroups {
    Write-Step ("==== 设置默认组  realm={0} ====" -f $script:Realm)
    if (-not $Execute) { Write-Step '预演模式：不写入 Keycloak；加 -Execute 才生效。' 'WARN' }

    $allGroups = Get-KcAllGroups
    $targets = @()
    foreach ($gn in @('app-msia', 'app-bol')) {
        $g = Resolve-TopLevelGroup -AllGroups $allGroups -Path ('/' + $gn)
        $targets += $g
    }
    $defaults = Get-KcDefaultGroups
    $defaultIds = @{}
    foreach ($d in $defaults) {
        $id = [string](Get-Prop $d 'id' '')
        if ($id -ne '') { $defaultIds[$id] = $true }
    }

    $added = 0
    $exists = 0
    foreach ($g in $targets) {
        if ($defaultIds.ContainsKey($g.Id)) {
            $exists++
            Write-Step ("[已存在] {0}" -f $g.Path) 'SKIP'
            continue
        }
        if ($Execute) {
            Invoke-KcApi -Method Put -Uri (
                '{0}/admin/realms/{1}/default-groups/{2}' -f $script:Base, $script:Realm, $g.Id) | Out-Null
            $added++
            Write-Step ("[新增] {0}" -f $g.Path) 'OK'
        } else {
            Write-Step ("[将添加] {0}" -f $g.Path)
        }
    }

    $after = Get-KcDefaultGroups
    $afterNames = @($after | ForEach-Object { [string](Get-Prop $_ 'name' '') })
    Write-Step ("当前默认组: {0}" -f (($afterNames -join ', ') -replace '^$', '(空)'))
    if ($Execute) {
        $ok = ($afterNames -contains 'app-msia') -and ($afterNames -contains 'app-bol')
        if (-not $ok) {
            Write-Step '设置后核对失败：默认组里没有同时出现 app-msia 与 app-bol。' 'ERROR'
            return 3
        }
        Write-Step '设置完成并已核对。' 'OK'
    } else {
        Write-Step ("预演结果：新增 {0}，已存在 {1}。" -f $added, $exists)
    }
    Write-Step '提醒：Default Groups 只对新建用户生效，已存在用户不追溯；配置后 app-msia/app-bol 不再承担准入控制含义。' 'WARN'
    return 0
}

# ---------------- Action: Purge ----------------

function Invoke-Purge {
    Write-Step ("==== 清空 Keycloak 本地用户  Scope={0}  realm={1} ====" -f $Scope, $script:Realm)
    if (-not $Execute) { Write-Step '预演模式：只统计，不删除；加 -Execute 才执行删除。' 'WARN' }

    $keepInfo = Get-KeepInfo
    Write-Step ("数据库保留名单: {0} 行（admin + MANUAL + 重复邮箱）" -f $keepInfo.DbCount)
    if ($keepInfo.Extras.Count -gt 0) {
        Write-Step ("人工追加保留: {0} 个" -f $keepInfo.Extras.Count)
    }

    if ($Execute) {
        if ($ExpectedKeepCount -le 0) {
            Write-Step '拒绝执行：删除必须用 -ExpectedKeepCount 指定 Precheck 输出的数据库保留人数（现场口径 40）。' 'ERROR'
            return 2
        }
        if ($ExpectedKeepCount -ne $keepInfo.DbCount) {
            Write-Step ("拒绝执行：-ExpectedKeepCount={0}，实际数据库保留人数={1}。请重新跑 Precheck 并解释差额。" -f
                $ExpectedKeepCount, $keepInfo.DbCount) 'ERROR'
            return 2
        }
    }

    $users = Get-KcAllUsers
    $service = New-Object System.Collections.Generic.List[object]
    $keepHit = New-Object System.Collections.Generic.List[object]
    $brokered = New-Object System.Collections.Generic.List[object]
    $ldap = New-Object System.Collections.Generic.List[object]
    $targets = New-Object System.Collections.Generic.List[object]

    foreach ($u in $users) {
        $uname = [string](Get-Prop $u 'username' '')
        $fed = [string](Get-Prop $u 'federationLink' '')
        if (Test-IsServiceAccount $u) { $service.Add($u); continue }
        if ($keepInfo.Set.ContainsKey($uname.ToLowerInvariant())) { $keepHit.Add($u); continue }

        $hasAt = $uname.Contains('@')
        if ($Scope -eq 'Local') {
            if ($fed -ne '') { $ldap.Add($u); continue }
            if ($hasAt) { $brokered.Add($u); continue }
            $targets.Add($u)
        } else {
            # Federated：只清 username 含 @ 的 UPN 账号；LDAP 与短名本地账号不动。
            if ($hasAt) { $targets.Add($u) } else { $ldap.Add($u) }
        }
    }

    Write-Host ''
    Write-Host '---------------- 待删除清单 ----------------' -ForegroundColor Cyan
    Write-Host ("Keycloak 用户总数      : {0}" -f $users.Count)
    Write-Host ("保留名单命中           : {0}" -f $keepHit.Count)
    Write-Host ("服务账号（恒定保留）   : {0}" -f $service.Count)
    if ($Scope -eq 'Local') {
        Write-Host ("已由 Entra 建档（含 @）: {0}  （本轮跳过）" -f $brokered.Count)
        Write-Host ("LDAP 联邦用户          : {0}  （本轮跳过）" -f $ldap.Count)
    } else {
        Write-Host ("非 UPN 账号            : {0}  （本轮跳过）" -f $ldap.Count)
    }
    Write-Host ("本轮将删除             : {0}" -f $targets.Count) -ForegroundColor Yellow
    Write-Host ("删除后预计剩余         : {0}" -f ($users.Count - $targets.Count))
    if ($targets.Count -gt 0) {
        Write-Host '前 20 个待删除账号:'
        $targets | Select-Object -First 20 | ForEach-Object {
            Write-Host ("  - {0}" -f [string](Get-Prop $_ 'username' ''))
        }
    }

    if ($targets.Count -eq 0) {
        Write-Step '没有需要删除的账号，结束。' 'OK'
        return 0
    }
    if (-not $Execute) {
        Write-Step '预演结束：未删除任何账号。确认上面的数字后，用 -Execute -ExpectedKeepCount <数字> 执行。' 'WARN'
        return 0
    }

    Write-Step ("开始删除 {0} 个账号..." -f $targets.Count)
    $deleted = 0
    $gone = 0
    $failed = New-Object System.Collections.Generic.List[string]
    $i = 0
    foreach ($u in $targets) {
        $i++
        if (($i % 100) -eq 0) { Write-Step ("  进度 {0}/{1}" -f $i, $targets.Count) }
        try { Assert-KcToken } catch {
            $failed.Add(("token 刷新失败: {0}；剩余 {1} 个未处理" -f $_.Exception.Message, ($targets.Count - $i + 1)))
            Write-Step ("  token 刷新失败，提前结束: {0}" -f $_.Exception.Message) 'ERROR'
            break
        }
        $id = [string](Get-Prop $u 'id' '')
        $uname = [string](Get-Prop $u 'username' '')
        try {
            Invoke-KcApi -Method Delete -Uri (
                '{0}/admin/realms/{1}/users/{2}' -f $script:Base, $script:Realm, $id) | Out-Null
            $deleted++
        } catch {
            $st = [int](Get-Prop $_.Exception.Data 'HttpStatus' 0)
            if ($st -eq 404) {
                $gone++
            } else {
                $failed.Add(("{0}: {1}" -f $uname, $_.Exception.Message))
                Write-Step ("  [失败] {0}: {1}" -f $uname, $_.Exception.Message) 'ERROR'
            }
        }
    }

    Write-Step ("删除完成：成功 {0}，已被删除 {1}，失败 {2}" -f $deleted, $gone, $failed.Count) `
        $(if ($failed.Count -eq 0) { 'OK' } else { 'WARN' })

    Write-Step '执行全量登出...'
    try {
        Invoke-KcApi -Method Post -Uri (
            '{0}/admin/realms/{1}/logout-all' -f $script:Base, $script:Realm) | Out-Null
        Write-Step '全量登出已执行。' 'OK'
    } catch {
        Write-Step ("全量登出失败: {0}" -f $_.Exception.Message) 'WARN'
    }

    try {
        $sessions = @(Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/sessions?max=100' -f $script:Base, $script:Realm) | Where-Object { $null -ne $_ })
        $offline = @(Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/offline-sessions?max=100' -f $script:Base, $script:Realm) | Where-Object { $null -ne $_ })
        Write-Step ("残留会话 {0} 个，离线会话 {1} 个（各最多显示 100 条）" -f $sessions.Count, $offline.Count) `
            $(if (($sessions.Count + $offline.Count) -eq 0) { 'OK' } else { 'WARN' })
        if ($sessions.Count -gt 0) {
            $sessions | Select-Object -First 5 | ForEach-Object {
                Write-Host ("  会话: {0}" -f [string](Get-Prop $_ 'username' '')) -ForegroundColor Yellow
            }
        }
        if ($offline.Count -gt 0) {
            $offline | Select-Object -First 5 | ForEach-Object {
                Write-Host ("  离线会话: {0}" -f [string](Get-Prop $_ 'username' '')) -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Step ("会话核对失败（需人工在管理台复查）: {0}" -f $_.Exception.Message) 'WARN'
    }

    if ($failed.Count -gt 0) {
        Write-Host ''
        Write-Host '失败明细（最多 20 条）:' -ForegroundColor Red
        $failed | Select-Object -First 20 | ForEach-Object { Write-Host ("  - {0}" -f $_) -ForegroundColor Red }
        return 3
    }
    return 0
}

# ---------------- Action: ResetDb ----------------

function Get-DbResetCounts {
    param([Parameter(Mandatory)][string]$KeepListSql)
    $q = @"
SELECT
    COUNT(*) AS rows_total,
    ISNULL(SUM(CASE WHEN kc_user_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS kc_id_filled,
    ISNULL(SUM(CASE WHEN pwd_set = 1 THEN 1 ELSE 0 END), 0) AS pwd_set_1
FROM dbo.CN_AME_SSO_User
WHERE login_name NOT IN ($KeepListSql)
"@
    $rows = @(Invoke-SsoSql -Query $q -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
    if ($rows.Count -eq 0) { throw '中央表字段统计没有返回结果。' }
    return $rows[0]
}

function Invoke-ResetDb {
    Write-Step ("==== 重置中央表字段  {0}/{1} ====" -f $SqlServer, $Database)
    if (-not $Execute) { Write-Step '预演模式：只统计，不更新；加 -Execute 才执行 UPDATE。' 'WARN' }

    $keepInfo = Get-KeepInfo
    $keepList = ConvertTo-SqlNvarcharList -Values @($keepInfo.Set.Keys)
    Write-Step ("保留名单 {0} 个 username（admin + MANUAL + 重复邮箱 + 人工追加）" -f $keepInfo.Set.Count)

    $before = Get-DbResetCounts -KeepListSql $keepList
    Write-Step ("待处理行 {0}：其中 kc_user_id 有值 {1}，pwd_set=1 {2}" -f
        $before.rows_total, $before.kc_id_filled, $before.pwd_set_1)

    if (-not $Execute) {
        Write-Step '预演结束：未更新任何行。确认数字后用 -Action ResetDb -Execute 执行。' 'WARN'
        return 0
    }

    $sql = @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = NULL,
    pwd_set    = 0
WHERE login_name NOT IN ($keepList);
SELECT @@ROWCOUNT AS affected;
"@
    $r = @(Invoke-SsoSql -Query $sql -Credential (Get-SqlCredential) | Where-Object { $null -ne $_ })
    $affected = 0
    if ($r.Count -gt 0) { $affected = [int](Get-Prop $r[0] 'affected' 0) }
    Write-Step ("UPDATE 完成，影响 {0} 行。" -f $affected) 'OK'

    $after = Get-DbResetCounts -KeepListSql $keepList
    Write-Step ("复核：kc_user_id 有值 {0}，pwd_set=1 {1}（都应为 0）" -f $after.kc_id_filled, $after.pwd_set_1) `
        $(if (([int]$after.kc_id_filled -eq 0) -and ([int]$after.pwd_set_1 -eq 0)) { 'OK' } else { 'WARN' })
    if (([int]$after.kc_id_filled -ne 0) -or ([int]$after.pwd_set_1 -ne 0)) { return 3 }
    return 0
}

# ---------------- Action: Verify ----------------

function Invoke-Verify {
    Write-Step ("==== 切换后校验  realm={0} ====" -f $script:Realm)
    $bad = 0

    # 默认组
    try {
        $defaults = Get-KcDefaultGroups
        $names = @($defaults | ForEach-Object { [string](Get-Prop $_ 'name' '') })
        $ok = ($names -contains 'app-msia') -and ($names -contains 'app-bol')
        Write-Step ("默认组: {0}" -f (($names -join ', ') -replace '^$', '(空)')) $(if ($ok) { 'OK' } else { 'ERROR' })
        if (-not $ok) { $bad++ }
    } catch {
        Write-Step ("读取默认组失败: {0}" -f $_.Exception.Message) 'ERROR'
        $bad++
    }

    # groups mapper
    foreach ($cid in $ClientIds) {
        try {
            $client = Get-KcClient -ClientId $cid
            $st = Get-GroupsMapperStatus -Client $client
            Write-Step ("client {0} groups mapper: {1} — {2}" -f $cid, $st.State, $st.Detail) `
                $(if ($st.State -eq 'OK') { 'OK' } elseif ($st.State -eq 'BAD') { 'ERROR' } else { 'WARN' })
            if ($st.State -eq 'BAD') { $bad++ }
        } catch {
            Write-Step ("client {0} 检查失败: {1}" -f $cid, $_.Exception.Message) 'ERROR'
            $bad++
        }
    }

    # 用户结构
    try {
        $users = Get-KcAllUsers
        $local = @($users | Where-Object {
            [string](Get-Prop $_ 'federationLink' '') -eq '' -and -not (Test-IsServiceAccount $_)
        }).Count
        $fed = @($users | Where-Object { [string](Get-Prop $_ 'federationLink' '') -ne '' }).Count
        $at = @($users | Where-Object {
            ([string](Get-Prop $_ 'username' '')).Contains('@') -and -not (Test-IsServiceAccount $_)
        }).Count
        $svc = @($users | Where-Object { Test-IsServiceAccount $_ }).Count
        Write-Step ("用户总数 {0}：本地 {1}，LDAP 联邦 {2}，UPN 账号 {3}，服务账号 {4}" -f
            $users.Count, $local, $fed, $at, $svc)
        $keepInfo = Get-KeepInfo
        $keepCount = @($users | Where-Object {
            $keepInfo.Set.ContainsKey(([string](Get-Prop $_ 'username' '')).ToLowerInvariant())
        }).Count
        Write-Step ("保留账号仍在 Keycloak 中: {0} 个（数据库名单 {1} 行）" -f $keepCount, $keepInfo.DbCount) `
            $(if ($keepCount -ge $keepInfo.DbCount) { 'OK' } else { 'WARN' })
    } catch {
        Write-Step ("读取用户结构失败: {0}" -f $_.Exception.Message) 'ERROR'
        $bad++
    }

    # 会话
    try {
        $sessions = @(Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/sessions?max=100' -f $script:Base, $script:Realm) | Where-Object { $null -ne $_ })
        $offline = @(Invoke-KcApi -Method Get -Uri (
            '{0}/admin/realms/{1}/offline-sessions?max=100' -f $script:Base, $script:Realm) | Where-Object { $null -ne $_ })
        Write-Step ("残留会话 {0}，离线会话 {1}" -f $sessions.Count, $offline.Count) `
            $(if (($sessions.Count + $offline.Count) -eq 0) { 'OK' } else { 'WARN' })
    } catch {
        Write-Step ("会话核对失败: {0}" -f $_.Exception.Message) 'WARN'
    }

    # 中央表（只读参考：本方案不再要求重置 kc_user_id / pwd_set，这两列不参与登录）
    try {
        $keepInfo = Get-KeepInfo
        $keepList = ConvertTo-SqlNvarcharList -Values @($keepInfo.Set.Keys)
        $c = Get-DbResetCounts -KeepListSql $keepList
        Write-Step ("中央表非保留行 {0}：kc_user_id 有值 {1}，pwd_set=1 {2}（参考值，不影响登录）" -f
            $c.rows_total, $c.kc_id_filled, $c.pwd_set_1) 'INFO'

        $s = Get-DbStats
        Write-Step ("中央表 UserMap 行数: {0}（本方案不写映射，应保持不变）" -f $s.usermap_rows)
    } catch {
        Write-Step ("中央表复核失败: {0}" -f $_.Exception.Message) 'ERROR'
        $bad++
    }

    Write-Host ''
    if ($bad -gt 0) {
        Write-Host ("校验结论: 有 {0} 项阻断问题，按上面的 ERROR 行处理。" -f $bad) -ForegroundColor Red
        return 2
    }
    Write-Host '校验结论: 通过（WARN 项按手册人工确认）。' -ForegroundColor Green
    return 0
}

# ---------------- 主流程 ----------------

function Invoke-Main {
    Write-Step ("Keycloak: {0}  realm: {1}  adminRealm: {2}  action: {3}" -f
        $script:Base, $script:Realm, $script:AdminRealm, $Action)

    # 数据库动作优先确认凭据，避免做到一半才发现 credentials.xml 不可用。
    if ($Action -in @('Precheck', 'Purge', 'ResetDb', 'Verify')) {
        # Precheck 允许数据库失败后继续报告 Keycloak 结论；其余动作直接失败。
        try { [void](Get-SqlCredential) } catch {
            if ($Action -ne 'Precheck') {
                Write-Step ("数据库凭据不可用: {0}" -f $_.Exception.Message) 'ERROR'
                return 2
            }
            Write-Step ("数据库凭据不可用，中央表部分将标记阻断: {0}" -f $_.Exception.Message) 'WARN'
        }
    }

    # 管理员口令
    if ($script:AdminPass -eq '') {
        Write-Host ("请输入 Keycloak 管理员 {0}（realm {1}）的密码（不回显；不落盘、不写日志）：" -f
            $script:AdminUser, $script:AdminRealm)
        try {
            $sec = Read-Host -AsSecureString
        } catch {
            Write-Step ("无法交互读取密码：{0}。请用 -AdminPassword 传入，或改在交互式 PowerShell 中运行。" -f $_.Exception.Message) 'ERROR'
            return 2
        }
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try { $script:AdminPass = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ($script:AdminPass -eq '') {
            Write-Step '密码为空，已中止。' 'ERROR'
            return 2
        }
    } else {
        Write-Step '使用 -AdminPassword 传入的密码（注意：命令行参数可能留在 PowerShell 历史/进程列表里）。' 'WARN'
    }

    try {
        $expires = Set-KcToken
        Write-Step ("token 获取成功（有效期 {0} 秒，到期自动续）" -f $expires) 'OK'
    } catch {
        Write-Step ("取 token 失败: {0}" -f $_.Exception.Message) 'ERROR'
        return 3
    }

    switch ($Action) {
        'Precheck'        { return (Invoke-Precheck) }
        'SetDefaultGroups' { return (Invoke-SetDefaultGroups) }
        'Purge'           { return (Invoke-Purge) }
        'ResetDb'         { return (Invoke-ResetDb) }
        'Verify'          { return (Invoke-Verify) }
    }
    return 2
}

exit (Invoke-Main)
