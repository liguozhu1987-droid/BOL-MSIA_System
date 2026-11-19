<#
.SYNOPSIS
    批量把用户加入 Keycloak 组：保留原台账快照用法，并支持"任意顶层组 + 任意人员范围"。
.DESCRIPTION
    ── 模式一：台账快照（原行为，默认）──────────────────────────────
    不传任何范围参数，或显式 -FromLedger：按下方 $script:Ledger 快照把 12 人
    加进 /app-msia、/app-bol（admin 已按 2026-11-11 决定移出，需单独建号）。
    数据口径：CN_AME_SSO_PermLedger 中 revoked_at IS NULL、system_code IN ('msia','bol')。

    ── 模式二：通用加组（2026-11-11 新增）──────────────────────────
    -GroupPath <路径> 指定目标组，人员范围三选一：
      -AllUsers              中央表 CN_AME_SSO_User 中 status=1 的全部账号（取 login_name 作 username）
      -CsvPath <文件>        至少含 employee_no 列；若同时含 username/login_name 列则直接用它
      -EmployeeNos 'a,b,c'   工号白名单，逗号/分号分隔（与 sync_sso_to_keycloak.ps1 同风格）
    工号要换成 Keycloak username 才能查人，所以需要读一次中央表（employee_no → login_name）。
    -AllUsers 会把排除名单里的 15 个服务/机器账号也带进来，它们在 Keycloak 里不存在，
    会落在"查无此人"，属预期，不是故障。

    ── 两种模式共用的行为 ─────────────────────────────────────────
      1. 校验目标组必须是顶层组：path 精确等于 /app-msia 这类值（区分大小写）。
         同名组嵌在别的父组下（如 /legacy/app-msia）或不存在 → 退出 2，整轮不写。
         应用做的是精确字符串匹配，嵌套组或大小写不一致都会导致登录后 403。
      2. 按 username 精确查找用户（?username=X&exact=true）；查不到只记录并继续，
         不中断整批。
      3. 用 PUT /users/{id}/groups/{groupId} 加组。PUT 天然幂等：重复执行不报错；
         已在组内的记为"已存在"，不会重复计为"新增"。本脚本只加不删，
         永远不会把已在组里的人移除。
      4. 组内成员关系先整组拉一次（分页 100/页）再逐人比对，-AllUsers 两三千人时
         省掉两三千次 GET；拉取失败则退回逐人 GET，结论不变。
      5. 管理员 token 到期自动续（password grant 默认 300 秒，-AllUsers 一定跑超时）。

    权限：sync-client 只有 manage-users / view-users / query-users，没有 manage-groups，
    所以必须用 realm 管理员（默认 kcadmin）走 password grant 取 token。
    凭据不写死在脚本里：用 -AdminPassword 传入；不传则交互式 Read-Host -AsSecureString。

    -DryRun：只读。组树、用户、成员关系照常查询，但不发任何 PUT；
              汇总里的"新增"改为"将添加"。

.NOTES
    文件: scripts/powershell/assign_groups_from_ledger.ps1
    执行方式: 手工（管理员 PowerShell）
    示例: .\assign_groups_from_ledger.ps1 -DryRun
          .\assign_groups_from_ledger.ps1
          .\assign_groups_from_ledger.ps1 -GroupPath /app-msia -EmployeeNos 'ligu,yaole' -DryRun
    退出码: 0=完成（"未找到"只列出，不算失败）
            2=前置校验失败（参数冲突 / 目标组缺失或嵌套 / CSV 缺列 / 凭据缺失）
            3=认证失败或 Keycloak API 错误（含部分用户加组失败）
#>
[CmdletBinding()]
param(
    [string]$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',
    [string]$Realm = 'inalfa',
    [string]$AdminClientId = 'admin-cli',
    [string]$AdminUsername = 'kcadmin',
    [string]$AdminPassword = '',
    [switch]$SkipCertCheck,
    [switch]$DryRun,

    # ---- 台账模式（默认） ----
    # 不传任何范围参数 = 原行为；显式 -FromLedger 等价。
    # 与 -GroupPath / -AllUsers / -CsvPath / -EmployeeNos 同时出现会被拒（退出 2）。
    [switch]$FromLedger,

    # ---- 通用加组模式 ----
    # 目标组路径，必须顶层且大小写与 Keycloak 里完全一致（如 /app-msia）。
    # 不做模糊匹配、不自动建组；嵌套路径直接退出 2。
    [string]$GroupPath = '',
    [switch]$AllUsers,
    [string]$CsvPath = '',
    # 工号白名单。用字符串而非数组：-File 方式调用时数组参数绑定会失效。
    [string]$EmployeeNos = '',

    # ---- 工号解析用的中央库连接（台账模式完全用不到） ----
    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
# Windows PowerShell 5.1 默认只协商到 TLS 1.0/1.1，Keycloak 25 只接受 TLS 1.2+，
# 症状是 "Could not create SSL/TLS secure channel."（端口通、证书也没问题）。
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
if ($SkipCertCheck) {
    # 只用于自签证书的临时环境；生产不要加这个开关。
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
}

# ---------------- 台账快照（2026-11-11） ----------------
# 口径：revoked_at IS NULL AND system_code IN ('msia','bol') AND username <> 'admin'
# 共 16 行；去重后 12 人（ligu / yaole / zhangya4 / zhaop3 同时在两个系统）。
# 名单变化时只改这里：键 = 目标组名，值 = 该组应有的 username 列表。
$script:Ledger = [ordered]@{
    'app-msia' = @(
        'abelmi2', 'fansh1', 'ligu', 'luyu', 'yangli1',
        'yaole', 'zhangp2', 'zhangpe', 'zhangya4', 'zhaop3'
    )
    'app-bol' = @(
        'chenca', 'libi2', 'ligu', 'yaole', 'zhangya4', 'zhaop3'
    )
}

$script:Base = $KeycloakBaseUrl.TrimEnd('/')
$script:Realm = $Realm
$script:AdminClientId = $AdminClientId
$script:AdminUser = $AdminUsername
$script:AdminPass = $AdminPassword
$script:KcToken = ''
$script:KcTokenExpiry = (Get-Date).AddMinutes(-1)
$script:SqlCredential = $null
$script:UserIndex = $null

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
       Keycloak 的 JSON 只包含非空字段，而本脚本启用了 StrictMode，
       裸访问不存在的属性会在运行期抛 "The property 'x' cannot be found"。 #>
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

function Invoke-KcApi {
    <# Keycloak Admin REST 调用。返回解析后的 JSON；204/空响应返回 $null。
       失败时抛出的异常消息里带 HTTP 状态码与响应体（便于定位 realm/client/权限问题）。 #>
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
    $req.UserAgent = 'sso-assign-groups/1.1'
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
        -Uri ("{0}/realms/{1}/protocol/openid-connect/token" -f $script:Base, $script:Realm) `
        -FormBody $form
    $tok = [string](Get-Prop $resp 'access_token' '')
    if ($tok -eq '') {
        throw 'token 响应里没有 access_token（检查 realm / client_id / 用户名密码。client 需启用 Direct Access Grants）。'
    }
    return [pscustomobject]@{
        Token     = $tok
        ExpiresIn = [int](Get-Prop $resp 'expires_in' 0)
    }
}

function Set-KcToken {
    <# 取一次管理员 token，并把过期时间提前 60 秒记下来（留出调用余量）。 #>
    $t = Get-KcAdminToken -User $script:AdminUser -Password $script:AdminPass
    $script:KcToken = $t.Token
    if ($t.ExpiresIn -gt 120) { $ttl = $t.ExpiresIn - 60 } else { $ttl = 30 }
    $script:KcTokenExpiry = (Get-Date).AddSeconds($ttl)
    return $t.ExpiresIn
}

function Assert-KcToken {
    <# token 快到期就重取。-AllUsers 两三千人一轮远超 password grant 的 300 秒，
       不续期会在中途整批 401。 #>
    if ($script:KcToken -ne '' -and (Get-Date) -lt $script:KcTokenExpiry) { return }
    Write-Step '管理员 token 即将到期，重新获取...' 'INFO'
    [void](Set-KcToken)
}

function Get-KcAllGroups {
    <# 遍历完整组树，返回 id/name/path/parentPath 的扁平列表（用于判定组是否顶层）。 #>
    $result = New-Object System.Collections.Generic.List[object]
    $queue = New-Object System.Collections.Generic.Queue[object]
    $seen = @{}

    $top = @(Invoke-KcApi -Method Get -Uri (
        '{0}/admin/realms/{1}/groups?briefRepresentation=false&max=500' -f $script:Base, $script:Realm))
    foreach ($g in $top) {
        if ($null -ne $g) {
            $queue.Enqueue([pscustomobject]@{ Group = $g; ParentPath = '' })
        }
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

        # 完整表示会带 subGroups；缺失时退回 /children 接口（KC 23+ 有）。
        $subsProp = $g.PSObject.Properties['subGroups']
        if ($null -ne $subsProp) {
            $subs = @($subsProp.Value)
        } else {
            try {
                $subs = @(Invoke-KcApi -Method Get -Uri (
                    '{0}/admin/realms/{1}/groups/{2}/children?briefRepresentation=false&max=500' -f
                    $script:Base, $script:Realm, $id))
            } catch {
                if ([int](Get-Prop $_.Exception.Data 'HttpStatus' 0) -eq 404) { $subs = @() }
                else { throw }
            }
        }
        foreach ($s in $subs) {
            if ($null -ne $s) {
                $queue.Enqueue([pscustomobject]@{ Group = $s; ParentPath = $path })
            }
        }
    }
    return , $result
}

function ConvertTo-TopLevelGroupPath {
    <# 把用户给的目标组规整成 /<name>，并在本地先挡掉嵌套路径。
       不做大小写修正：Keycloak 的 path 区分大小写，猜错了只会静默加错组。 #>
    param([Parameter(Mandatory)][string]$Path)
    $p = $Path.Trim()
    if ($p -eq '') { throw '目标组路径为空。' }
    if (-not $p.StartsWith('/')) { $p = '/' + $p }
    if ($p.Length -gt 1) { $p = $p.TrimEnd('/') }
    if ($p -eq '/') { throw '根路径 "/" 不是合法目标组。' }
    $name = $p.Substring(1)
    if ($name.Contains('/')) {
        throw ("只允许顶层组：'{0}' 是嵌套组。应用按精确路径匹配组名，子组里的成员拿不到顶层组权限；请先在控制台把用户放进顶层组。" -f $p)
    }
    return $p
}

function Resolve-TargetGroup {
    <# 目标组必须精确是顶层 /<name>。同名组出现在别的路径（含大小写不同）一律阻断。 #>
    param(
        [Parameter(Mandatory)][object[]]$AllGroups,
        [Parameter(Mandatory)][string]$Path
    )
    $exactPath = ConvertTo-TopLevelGroupPath -Path $Path
    $name = $exactPath.Substring(1)

    $exact = @($AllGroups | Where-Object { [string]$_.Path -ceq $exactPath })
    $conflict = @($AllGroups | Where-Object {
        [string]$_.Name -ieq $name -and [string]$_.Path -cne $exactPath
    })

    if ($conflict.Count -gt 0) {
        $paths = ($conflict | ForEach-Object { $_.Path }) -join '、'
        throw ("组名 '{0}' 存在非顶层/大小写不一致的同名组：{1}。应用按精确字符串匹配，这种组即使加了人也只会得到 403；请先在控制台改正组结构，本轮不做任何写入。" -f $name, $paths)
    }
    if ($exact.Count -eq 0) {
        throw ("顶层组 '{0}' 不存在。请先执行 realm 基线（apply-realm-baseline.ps1 / realm-setup.md 第 7 节）再跑本脚本；不要临时建空组——没有 client role 映射的组，用户登录后仍然没有权限。" -f $exactPath)
    }
    if ($exact.Count -gt 1) {
        throw ("顶层组 '{0}' 匹配到 {1} 个对象（数据异常），请先在控制台核对。" -f $exactPath, $exact.Count)
    }
    return $exact[0]
}

function Find-KcUser {
    <# username 精确查找；Keycloak 的 exact=true 不区分大小写，返回后再核对一次。 #>
    param([Parameter(Mandatory)][string]$UserName)
    $uri = '{0}/admin/realms/{1}/users?username={2}&exact=true&briefRepresentation=true&max=20' -f
        $script:Base, $script:Realm, [uri]::EscapeDataString($UserName)
    $list = @(Invoke-KcApi -Method Get -Uri $uri)
    $hits = @($list | Where-Object {
        $null -ne $_ -and ([string](Get-Prop $_ 'username' '')) -ieq $UserName
    })
    if ($hits.Count -eq 0) { return $null }
    if ($hits.Count -gt 1) {
        Write-Step ("用户 {0} 精确命中 {1} 条，取第一条。" -f $UserName, $hits.Count) 'WARN'
    }
    return $hits[0]
}

function Get-KcGroupMemberIds {
    <# 整组拉一次成员 id 集合（100/页）。返回 hashtable(id -> $true)。 #>
    param([Parameter(Mandatory)][string]$GroupId)
    $set = @{}
    $first = 0
    $pageSize = 100
    while ($true) {
        $uri = '{0}/admin/realms/{1}/groups/{2}/members?briefRepresentation=true&first={3}&max={4}' -f
            $script:Base, $script:Realm, $GroupId, $first, $pageSize
        $page = @(Invoke-KcApi -Method Get -Uri $uri | Where-Object { $null -ne $_ })
        if ($page.Count -eq 0) { break }
        foreach ($u in $page) {
            $id = [string](Get-Prop $u 'id' '')
            if ($id -ne '') { $set[$id] = $true }
        }
        if ($page.Count -lt $pageSize) { break }
        $first += $pageSize
        # 防御：分页参数被忽略时会无限循环。
        if ($first -gt 200000) { break }
    }
    return $set
}

function Test-UserInGroup {
    param(
        [Parameter(Mandatory)][string]$UserId,
        [Parameter(Mandatory)][string]$GroupId,
        [Parameter(Mandatory)][string]$GroupPath
    )
    $uri = '{0}/admin/realms/{1}/users/{2}/groups?briefRepresentation=false&max=500' -f
        $script:Base, $script:Realm, $UserId
    $groups = @(Invoke-KcApi -Method Get -Uri $uri)
    foreach ($g in $groups) {
        if ($null -eq $g) { continue }
        if ([string](Get-Prop $g 'id' '') -eq $GroupId) { return $true }
        if ([string](Get-Prop $g 'path' '') -ceq $GroupPath) { return $true }
    }
    return $false
}

# ---------------- 中央库（只在通用加组模式用到） ----------------

function Get-DbCredential {
    <# 从 credentials.xml 构造 SQL 登录用的 PSCredential（DPAPI 解密）。 #>
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
    <# 执行只读 SQL；优先 Invoke-Sqlcmd，回退 Microsoft.Data.SqlClient。
       与 sync_sso_to_keycloak.ps1 同口径（本脚本只读单表，不需要参数化）。 #>
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

function Get-UserIndex {
    <# 一次读全表，内存里建 employee_no → (login_name, status) 的索引。
       比 IN (...) 省事：-AllUsers 本来就要全表，几千条的白名单也不会撞参数上限。 #>
    if ($null -ne $script:UserIndex) { return $script:UserIndex }
    if ($null -eq $script:SqlCredential) {
        $script:SqlCredential = Get-DbCredential -Path $CredentialFile -Name $SqlCredentialName
    }
    $rows = Invoke-SsoSql -Credential $script:SqlCredential -Query @'
SELECT employee_no, login_name, status
FROM dbo.CN_AME_SSO_User
ORDER BY employee_no
'@
    $idx = @{}
    foreach ($r in @($rows)) {
        if ($null -eq $r) { continue }
        $eno = ([string]$r.employee_no).Trim()
        if ($eno -eq '') { continue }
        $idx[$eno.ToLowerInvariant()] = [pscustomobject]@{
            EmployeeNo = $eno
            LoginName  = ([string]$r.login_name).Trim()
            Status     = [int]$r.status
        }
    }
    $script:UserIndex = $idx
    Write-Step ("中央表索引: {0} 个工号" -f $idx.Count)
    return $idx
}

function Import-CsvAuto {
    <# 读 CSV 并自动判定编码：有 BOM 按 UTF-8，无 BOM 先按严格 UTF-8 试，
       失败回退 GBK（936）——Excel 另存的"CSV（逗号分隔）"默认就是 GBK。 #>
    param([Parameter(Mandatory)][string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { throw 'CSV 文件为空。' }
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        try {
            $strict = New-Object System.Text.UTF8Encoding($false, $true)
            $text = $strict.GetString($bytes)
        } catch {
            $text = [System.Text.Encoding]::GetEncoding(936).GetString($bytes)
        }
    }
    return @($text | ConvertFrom-Csv)
}

function Get-CsvColumn {
    param([string[]]$Columns, [string[]]$Candidates)
    foreach ($c in $Candidates) {
        foreach ($col in $Columns) {
            if ($col -ieq $c) { return $col }
        }
    }
    return ''
}

function New-Entry {
    param([string]$Key, [string]$UserName, [int]$Status = -1)
    return [pscustomobject]@{ Key = $Key; UserName = $UserName; Status = $Status }
}

function Get-PeopleFromEmployeeNos {
    <# 工号 → username。中央表查不到或 login_name 为空的，保留空 UserName，
       后面统一记入"查无此人"，不在这里中断。 #>
    param([string[]]$EmployeeNos)
    $idx = Get-UserIndex
    $list = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($raw in $EmployeeNos) {
        $eno = ([string]$raw).Trim()
        if ($eno -eq '') { continue }
        $k = $eno.ToLowerInvariant()
        if ($seen.ContainsKey($k)) { continue }
        $seen[$k] = $true
        if ($idx.ContainsKey($k)) {
            $hit = $idx[$k]
            if ($hit.Status -ne 1) {
                Write-Step ("工号 {0} 在中央表 status={1}（已离职/停用），仍按名单尝试加组。" -f $hit.EmployeeNo, $hit.Status) 'WARN'
            }
            $list.Add((New-Entry -Key $hit.EmployeeNo -UserName $hit.LoginName -Status $hit.Status))
        } else {
            $list.Add((New-Entry -Key $eno -UserName '' -Status -1))
        }
    }
    return , $list
}

function Get-GenericEntries {
    <# 通用加组的人员范围解析：三选一，返回 [Key, UserName] 列表。 #>
    if ($AllUsers) {
        $idx = Get-UserIndex
        $list = New-Object System.Collections.Generic.List[object]
        $skipped = 0
        foreach ($k in ($idx.Keys | Sort-Object)) {
            $u = $idx[$k]
            if ($u.Status -ne 1) { continue }
            if ($u.LoginName -eq '') { $skipped++; continue }
            $list.Add((New-Entry -Key $u.EmployeeNo -UserName $u.LoginName -Status $u.Status))
        }
        if ($skipped -gt 0) {
            Write-Step ("-AllUsers: 跳过 {0} 个 login_name 为空的在职账号（Keycloak 里没有对应 username）" -f $skipped) 'WARN'
        }
        return , $list
    }

    if ($CsvPath -ne '') {
        if (-not (Test-Path -LiteralPath $CsvPath)) { throw ("CSV 文件不存在: {0}" -f $CsvPath) }
        $rows = @(Import-CsvAuto -Path $CsvPath)
        if ($rows.Count -eq 0) { throw ("CSV 没有数据行: {0}" -f $CsvPath) }
        $cols = @($rows[0].PSObject.Properties.Name)
        $colEno = Get-CsvColumn -Columns $cols -Candidates @('employee_no', 'employeeNo', '工号')
        if ($colEno -eq '') {
            throw ("CSV 至少需要 employee_no 列，实际列为: {0}" -f ($cols -join ', '))
        }
        $colUser = Get-CsvColumn -Columns $cols -Candidates @('username', 'login_name', 'loginName', 'preferred_username', '登录名')
        if ($colUser -ne '') {
            Write-Step ("CSV 使用自带 username 列 '{0}'，不再回表解析工号。" -f $colUser)
            $list = New-Object System.Collections.Generic.List[object]
            $seen = @{}
            foreach ($r in $rows) {
                $eno = ([string](Get-Prop $r $colEno '')).Trim()
                $usr = ([string](Get-Prop $r $colUser '')).Trim()
                if ($eno -eq '' -and $usr -eq '') { continue }
                $k = ($(if ($eno -ne '') { $eno } else { $usr })).ToLowerInvariant()
                if ($seen.ContainsKey($k)) { continue }
                $seen[$k] = $true
                $list.Add((New-Entry -Key $(if ($eno -ne '') { $eno } else { $usr }) -UserName $usr))
            }
            return , $list
        }
        $enos = @()
        foreach ($r in $rows) {
            $v = ([string](Get-Prop $r $colEno '')).Trim()
            if ($v -ne '') { $enos += $v }
        }
        if ($enos.Count -eq 0) { throw ("CSV 的 {0} 列没有任何值: {1}" -f $colEno, $CsvPath) }
        return (Get-PeopleFromEmployeeNos -EmployeeNos $enos)
    }

    # -EmployeeNos
    $enos = @($EmployeeNos -split '[,;]' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
    if ($enos.Count -eq 0) { throw '-EmployeeNos 解析后为空，请检查是否传了工号。' }
    return (Get-PeopleFromEmployeeNos -EmployeeNos $enos)
}

# ---------------- 台账模式的人员范围 ----------------

function Get-LedgerEntries {
    <# 原行为：键 = 组路径，值 = username 列表。台账里存的就是 username，不回表。 #>
    $map = [ordered]@{}
    foreach ($groupName in @($script:Ledger.Keys)) {
        $list = New-Object System.Collections.Generic.List[object]
        foreach ($u in @($script:Ledger[$groupName])) {
            $list.Add((New-Entry -Key ([string]$u) -UserName ([string]$u)))
        }
        $path = '/' + $groupName
        $map[$path] = $list
    }
    return $map
}

# ---------------- 主流程 ----------------

function Resolve-Mode {
    <# 返回 'ledger' 或 'generic'；参数冲突一律在取 token 之前抛出来（退出 2）。 #>
    $hasScope = $false
    if ($AllUsers) { $hasScope = $true }
    if ($CsvPath.Trim() -ne '') { $hasScope = $true }
    if ($EmployeeNos.Trim() -ne '') { $hasScope = $true }

    if ($FromLedger) {
        if ($GroupPath.Trim() -ne '' -or $hasScope) {
            throw '-FromLedger 是原台账用法，不能与 -GroupPath / -AllUsers / -CsvPath / -EmployeeNos 同时使用。'
        }
        return 'ledger'
    }
    if ($GroupPath.Trim() -eq '') {
        if ($hasScope) {
            throw '通用加组必须用 -GroupPath 指定目标组，例如 -GroupPath /app-msia。'
        }
        return 'ledger'   # 一个范围参数都没传 = 原来的默认行为
    }
    $n = 0
    if ($AllUsers) { $n++ }
    if ($CsvPath.Trim() -ne '') { $n++ }
    if ($EmployeeNos.Trim() -ne '') { $n++ }
    if ($n -eq 0) { throw '请三选一指定人员范围：-AllUsers / -CsvPath <文件> / -EmployeeNos ''a,b''' }
    if ($n -gt 1) { throw '-AllUsers / -CsvPath / -EmployeeNos 只能选一个。' }
    return 'generic'
}

function Add-UsersToGroup {
    <# 把一批人加进一个已校验过的组，返回该组的汇总。 #>
    param(
        [Parameter(Mandatory)]$Group,
        [Parameter(Mandatory)]$Entries
    )
    $grp = $Group
    $entries = @($Entries)
    $total = $entries.Count
    $bulk = ($total -gt 200)   # 大批量时不逐行刷屏，只打进度和异常
    $added = 0
    $exists = 0
    $anyFailure = $false
    $notFound = New-Object System.Collections.Generic.List[string]
    $failedList = New-Object System.Collections.Generic.List[string]

    Write-Step ("--- {0}（本轮 {1} 人）---" -f $grp.Path, $total)

    # 成员关系整组拉一次：-AllUsers 两三千人，逐人 GET 会让耗时翻倍。
    # 拉不到就退回逐人校验，结论不变（PUT 幂等，最坏只是"新增"数偏大）。
    $memberIds = $null
    try {
        $memberIds = Get-KcGroupMemberIds -GroupId $grp.Id
        Write-Step ("组内现有成员: {0} 人" -f $memberIds.Count)
    } catch {
        Write-Step ("预取组成员失败，改逐人校验: {0}" -f $_.Exception.Message) 'WARN'
    }

    $i = 0
    foreach ($entry in $entries) {
        $i++
        $key = [string]$entry.Key
        $userName = [string]$entry.UserName

        if ($bulk -and ($i % 200) -eq 0) {
            Write-Step ("  进度 {0}/{1}" -f $i, $total)
        }

        if ($userName -eq '') {
            $notFound.Add(("{0}: 中央表无此人或 login_name 为空" -f $key))
            if (-not $bulk) { Write-Step ("  [未找到] {0}（无可用 username）" -f $key) 'WARN' }
            continue
        }

        try {
            Assert-KcToken
        } catch {
            $anyFailure = $true
            $failedList.Add(("token 刷新失败: {0}；本轮剩余 {1} 人未处理" -f $_.Exception.Message, ($total - $i + 1)))
            Write-Step ("  [失败]   token 刷新失败，提前结束本组: {0}" -f $_.Exception.Message) 'ERROR'
            break
        }

        $kcUser = $null
        try {
            $kcUser = Find-KcUser -UserName $userName
        } catch {
            $anyFailure = $true
            $failedList.Add(("{0}: 查询用户失败 - {1}" -f $userName, $_.Exception.Message))
            Write-Step ("  [失败]   {0}: 查询用户失败 - {1}" -f $userName, $_.Exception.Message) 'ERROR'
            continue
        }
        if ($null -eq $kcUser) {
            $notFound.Add(("{0}: {1} 在 Keycloak 中不存在" -f $key, $userName))
            if (-not $bulk) { Write-Step ("  [未找到] {0}（username={1}）" -f $key, $userName) 'WARN' }
            continue
        }

        $uid = [string](Get-Prop $kcUser 'id' '')
        if ($uid -eq '') {
            $anyFailure = $true
            $failedList.Add(("{0}: 用户对象缺少 id" -f $userName))
            Write-Step ("  [失败]   {0}: 用户对象缺少 id" -f $userName) 'ERROR'
            continue
        }

        try {
            if ($null -ne $memberIds) {
                $inGroup = $memberIds.ContainsKey($uid)
            } else {
                $inGroup = Test-UserInGroup -UserId $uid -GroupId $grp.Id -GroupPath $grp.Path
            }

            if ($inGroup) {
                $exists++
                if (-not $bulk) { Write-Step ("  [已存在] {0}" -f $userName) 'SKIP' }
            } elseif ($DryRun) {
                $added++
                if (-not $bulk) { Write-Step ("  [将添加] {0}" -f $userName) }
            } else {
                Invoke-KcApi -Method Put -Uri (
                    '{0}/admin/realms/{1}/users/{2}/groups/{3}' -f $script:Base, $script:Realm, $uid, $grp.Id) | Out-Null
                $added++
                if (-not $bulk) { Write-Step ("  [新增]   {0}" -f $userName) 'OK' }
            }
        } catch {
            $anyFailure = $true
            $failedList.Add(("{0}: {1}" -f $userName, $_.Exception.Message))
            Write-Step ("  [失败]   {0}: {1}" -f $userName, $_.Exception.Message) 'ERROR'
        }
    }

    return [pscustomobject]@{
        Path       = $grp.Path
        Added      = $added
        Exists     = $exists
        NotFound   = $notFound
        Failed     = $failedList
        AnyFailure = $anyFailure
    }
}

function Invoke-AssignGroups {
    if ($DryRun) {
        Write-Step '*** DryRun：只读校验，不对 Keycloak 做任何写操作 ***' 'WARN'
    }
    Write-Step ("Keycloak: {0}  realm: {1}  管理员: {2}" -f $script:Base, $script:Realm, $script:AdminUser)

    # ---- 1. 模式与参数（全部在取 token 之前判定）----
    $mode = ''
    try {
        $mode = Resolve-Mode
    } catch {
        Write-Step ("参数校验失败: {0}" -f $_.Exception.Message) 'ERROR'
        return 2
    }

    $targetPath = ''
    $entries = $null
    $ledgerMap = $null
    if ($mode -eq 'ledger') {
        $ledgerMap = Get-LedgerEntries
        foreach ($g in @($ledgerMap.Keys)) {
            Write-Step ("台账快照: {0} -> {1} 人" -f $g, @($ledgerMap[$g]).Count)
        }
    } else {
        try {
            $targetPath = ConvertTo-TopLevelGroupPath -Path $GroupPath
        } catch {
            Write-Step ("目标组校验失败: {0}" -f $_.Exception.Message) 'ERROR'
            return 2
        }
        Write-Step ("目标组: {0}（通用加组模式）" -f $targetPath)
        try {
            $entries = @(Get-GenericEntries)
        } catch {
            Write-Step ("人员范围解析失败: {0}" -f $_.Exception.Message) 'ERROR'
            return 2
        }
        if ($entries.Count -eq 0) {
            Write-Step '人员范围解析结果为空，没有可处理的用户。' 'ERROR'
            return 2
        }
        Write-Step ("待处理: {0} 人" -f $entries.Count)
    }

    # ---- 2. 管理员口令 ----
    if ($script:AdminPass -eq '') {
        Write-Host ("请输入 Keycloak 管理员 {0} 的密码（不回显；不落盘、不写日志）：" -f $script:AdminUser)
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

    Write-Step '获取管理员 token（password grant）...'
    try {
        $expires = Set-KcToken
    } catch {
        Write-Step ("取 token 失败: {0}" -f $_.Exception.Message) 'ERROR'
        return 3
    }
    Write-Step ("token 获取成功（有效期 {0} 秒，到期自动续）" -f $expires) 'OK'

    # ---- 3. 组树与目标组 ----
    Write-Step '读取组树...'
    $allGroups = $null
    try {
        $allGroups = Get-KcAllGroups
    } catch {
        Write-Step ("读取组列表失败: {0}" -f $_.Exception.Message) 'ERROR'
        return 3
    }
    Write-Step ("组总数（含子组）: {0}" -f $allGroups.Count)

    # 所有目标组都校验通过后才进入写阶段：避免"第一个组合格先加了一半，第二个不合格才报错"。
    $resolved = [ordered]@{}
    try {
        if ($mode -eq 'ledger') {
            foreach ($groupName in @($script:Ledger.Keys)) {
                $resolved['/' + $groupName] = Resolve-TargetGroup -AllGroups $allGroups -Path ('/' + $groupName)
                Write-Step ("目标组 OK: {0} (id={1})" -f $resolved['/' + $groupName].Path, $resolved['/' + $groupName].Id) 'OK'
            }
        } else {
            $resolved[$targetPath] = Resolve-TargetGroup -AllGroups $allGroups -Path $targetPath
            Write-Step ("目标组 OK: {0} (id={1})" -f $resolved[$targetPath].Path, $resolved[$targetPath].Id) 'OK'
        }
    } catch {
        Write-Step ("前置校验失败: {0}" -f $_.Exception.Message) 'ERROR'
        return 2
    }

    # ---- 4. 逐组加人 ----
    $summaries = New-Object System.Collections.Generic.List[object]
    $anyFailure = $false
    foreach ($path in @($resolved.Keys)) {
        $batch = if ($mode -eq 'ledger') { $ledgerMap[$path] } else { $entries }
        $s = Add-UsersToGroup -Group $resolved[$path] -Entries $batch
        if ($s.AnyFailure) { $anyFailure = $true }
        $summaries.Add($s)
    }

    # ---- 5. 汇总 ----
    Write-Host ''
    Write-Host '================ 汇总 ================' -ForegroundColor Cyan
    $verb = if ($DryRun) { '将加入' } else { '新增' }
    foreach ($s in $summaries) {
        Write-Host ("[{0}] {1} {2} / 已在组 {3} / 查无此人 {4}" -f
            $s.Path, $verb, $s.Added, $s.Exists, $s.NotFound.Count)
        if ($s.NotFound.Count -gt 0) {
            $show = @($s.NotFound | Select-Object -First 30)
            foreach ($n in $show) { Write-Host ("         未找到: {0}" -f $n) -ForegroundColor Yellow }
            if ($s.NotFound.Count -gt $show.Count) {
                Write-Host ("         未找到: 其余 {0} 条已省略（多为排除名单里的服务账号或未同步人员）" -f
                    ($s.NotFound.Count - $show.Count)) -ForegroundColor Yellow
            }
        }
        if ($s.Failed.Count -gt 0) {
            Write-Host ("         失败  : {0}" -f $s.Failed.Count) -ForegroundColor Red
            foreach ($f in $s.Failed) {
                Write-Host ("           - {0}" -f $f) -ForegroundColor Red
            }
        }
    }
    if ($DryRun) {
        Write-Host ''
        Write-Host '（DryRun：未写 Keycloak；"将加入"是按当前成员关系计算的预估。）' -ForegroundColor Yellow
    }

    if ($anyFailure) { return 3 }
    return 0
}

exit (Invoke-AssignGroups)
