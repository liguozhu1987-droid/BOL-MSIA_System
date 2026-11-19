<#
.SYNOPSIS
    只读盘点：列出 Keycloak 里 username 含 '@' 的账号及其关联/组情况。
.DESCRIPTION
    用途：Entra broker 的 username 模板没配好时，用户登录会新建一个
    "ligu@ap.inalfa.local" 这类带 @ 的账号（与本地 ligu 并存）。本脚本把
    这类账号一次性列出来，供人工判断留/删/改名——脚本只调用 Keycloak 的
    管理 REST 的 GET 接口，不创建、不修改、不删除任何数据。

    输出（默认 C:\sso\tmp）：
      at_username_users_<时间戳>.csv   UTF-8 BOM，可直接 Excel 打开
      控制台汇总：扫描总数、命中数、其中有 IdP 链接的、其中不在任何组的

    列含义：
      UserId / Username / Email / CreatedTime / Enabled
      FederatedIdp          该账号关联的 IdP 别名（多个用 ; 分隔），空 = 没走过 broker
      FederatedUserName     IdP 侧的 user name（通常是对象 id 或 UPN）
      GroupCount / Groups   组数量与组名（空 = 能登但应用会 403）

.NOTES
    文件: scripts/powershell/find_at_username_users.ps1
    执行方式: 手工（只读，可在任意时间跑）
    示例: .\find_at_username_users.ps1 -Realm inalfa
          .\find_at_username_users.ps1 -Realm inalfa -BaseUrl https://iame.ap.inalfa.local:8443
    退出码: 0=完成（有命中也算完成） 2=参数或环境错误 3=取令牌/接口错误
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://iame.ap.inalfa.local:8443',
    [string]$Realm = 'inalfa',

    # 管理员所在 realm：默认 master；若管理员建在 inalfa 里就传 inalfa
    [string]$AdminRealm = 'master',

    # 不给就交互输入（只用于换令牌，不落盘）
    [System.Management.Automation.PSCredential]$Credential,

    # 已有令牌时可直接传，省掉换令牌这一步
    [string]$AccessToken,

    [string]$OutDirectory = 'C:\sso\tmp',

    [ValidateRange(1, 1000)]
    [int]$PageSize = 500
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

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($p) { return $p.Value }
    return $null
}

function ConvertFrom-UnixMs {
    param($Value)
    if ($null -eq $Value) { return '' }
    try {
        $ms = [int64]$Value
        if ($ms -le 0) { return '' }
        return [DateTimeOffset]::FromUnixTimeMilliseconds($ms).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')
    } catch {
        return ''
    }
}

# ---------------------------------------------------------------- 前置检查
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    Write-Step 'BaseUrl 不能为空' 'ERROR'; exit 2
}
$BaseUrl = $BaseUrl.TrimEnd('/')
if ($BaseUrl -notmatch '^https?://') {
    Write-Step "BaseUrl 必须以 http:// 或 https:// 开头：$BaseUrl" 'ERROR'; exit 2
}

if (-not $AccessToken) {
    if (-not $Credential) {
        try {
            $Credential = Get-Credential -Message "Keycloak 管理员（$AdminRealm realm），仅用于换令牌"
        } catch {
            Write-Step '未提供凭据' 'ERROR'; exit 2
        }
    }
    if (-not $Credential) { Write-Step '未提供凭据' 'ERROR'; exit 2 }
}

Write-Step "目标：$BaseUrl  realm=$Realm  adminRealm=$AdminRealm"

# 内网自签证书：跳过校验（只读脚本，且不传任何写入请求）
$oldCallback = [Net.ServicePointManager]::ServerCertificateValidationCallback
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
Write-Step '已跳过 TLS 证书校验（内网自签）' 'WARN'

try {
    # ------------------------------------------------------------ 取令牌
    if (-not $AccessToken) {
        $tokenUri = "$BaseUrl/realms/$AdminRealm/protocol/openid-connect/token"
        $body = @{
            client_id  = 'admin-cli'
            grant_type = 'password'
            username   = $Credential.UserName
            password   = $Credential.GetNetworkCredential().Password
        }
        try {
            $tokenResp = Invoke-RestMethod -Method Post -Uri $tokenUri -Body $body `
                -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30
        } catch {
            Write-Step "取管理员令牌失败：$($_.Exception.Message)" 'ERROR'
            Write-Step "确认 $AdminRealm 的 admin-cli 允许 direct access grant，或改用 -AccessToken 传入" 'ERROR'
            exit 3
        }
        $AccessToken = Get-Prop $tokenResp 'access_token'
        if ([string]::IsNullOrWhiteSpace($AccessToken)) {
            Write-Step '令牌响应里没有 access_token' 'ERROR'; exit 3
        }
    }
    $headers = @{ Authorization = "Bearer $AccessToken" }

    # ------------------------------------------------------------ 拉全量用户
    $users = New-Object System.Collections.Generic.List[object]
    $first = 0
    $pageNo = 0
    while ($true) {
        $pageNo++
        if ($pageNo -gt 200) {
            Write-Step '分页超过 200 页，疑似接口异常，停止' 'ERROR'; exit 3
        }
        $uri = '{0}/admin/realms/{1}/users?briefRepresentation=true&first={2}&max={3}' -f $BaseUrl, $Realm, $first, $PageSize
        try {
            $page = @(Invoke-RestMethod -Method Get -Uri $uri -Headers $headers -TimeoutSec 60)
        } catch {
            Write-Step "拉取用户失败（first=$first）：$($_.Exception.Message)" 'ERROR'; exit 3
        }
        if ($page.Count -eq 0) { break }
        foreach ($u in $page) { $users.Add($u) }
        if ($page.Count -lt $PageSize) { break }
        $first += $PageSize
    }
    Write-Step ("扫描用户 {0} 个" -f $users.Count) 'INFO'

    # ------------------------------------------------------------ 筛 username 含 @
    $hits = @($users | Where-Object {
        $name = Get-Prop $_ 'username'
        $name -and $name.Contains('@')
    })

    if ($hits.Count -eq 0) {
        Write-Step '没有 username 含 @ 的账号（说明模板已在生效，或还没人走过 broker 登录）' 'OK'
        Write-Step '未生成文件：无命中' 'INFO'
        exit 0
    }

    Write-Step ("命中 {0} 个 username 含 @ 的账号，逐个补 IdP 链接与组信息" -f $hits.Count) 'INFO'

    # ------------------------------------------------------------ 逐个补详情
    $rows = New-Object System.Collections.Generic.List[object]
    $idx = 0
    foreach ($u in $hits) {
        $idx++
        $id = [string](Get-Prop $u 'id')
        $username = [string](Get-Prop $u 'username')
        $email = [string](Get-Prop $u 'email')
        $created = ConvertFrom-UnixMs (Get-Prop $u 'createdTimestamp')
        $enabled = Get-Prop $u 'enabled'

        $links = @()
        try {
            $links = @(Invoke-RestMethod -Method Get -Uri "$BaseUrl/admin/realms/$Realm/users/$id/federated-identity" -Headers $headers -TimeoutSec 30)
        } catch {
            $links = @()
        }
        $groups = @()
        try {
            $groups = @(Invoke-RestMethod -Method Get -Uri "$BaseUrl/admin/realms/$Realm/users/$id/groups" -Headers $headers -TimeoutSec 30)
        } catch {
            $groups = @()
        }

        $idpNames = @($links | ForEach-Object { [string](Get-Prop $_ 'identityProvider') } | Where-Object { $_ })
        $idpUsers = @($links | ForEach-Object { [string](Get-Prop $_ 'userName') } | Where-Object { $_ })
        $groupNames = @($groups | ForEach-Object { [string](Get-Prop $_ 'name') } | Where-Object { $_ })

        $rows.Add([pscustomobject]@{
            UserId          = $id
            Username        = $username
            Email           = $email
            CreatedTime     = $created
            Enabled         = $enabled
            FederatedIdp    = ($idpNames -join ';')
            FederatedUserName = ($idpUsers -join ';')
            GroupCount      = $groupNames.Count
            Groups          = ($groupNames -join ';')
        })

        Write-Progress -Activity '读取 IdP 链接与组' -Status $username -PercentComplete ([int](100 * $idx / $hits.Count))
    }
    Write-Progress -Activity '读取 IdP 链接与组' -Completed

    # ------------------------------------------------------------ 输出
    if (-not (Test-Path -LiteralPath $OutDirectory)) {
        New-Item -ItemType Directory -Force -Path $OutDirectory | Out-Null
    }
    $outFile = Join-Path $OutDirectory ('at_username_users_{0}.csv' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $rows | Export-Csv -LiteralPath $outFile -NoTypeInformation -Encoding UTF8

    $withIdp = @($rows | Where-Object { $_.FederatedIdp }).Count
    $noGroup = @($rows | Where-Object { $_.GroupCount -eq 0 }).Count

    Write-Step ("已输出：{0}" -f $outFile) 'OK'
    Write-Step ("命中 {0} 个；其中有 IdP 链接 {1} 个；不在任何组 {2} 个" -f $rows.Count, $withIdp, $noGroup) 'INFO'
    Write-Step '只读完成，未修改任何数据。留/删/改名请看清单后人工决定' 'INFO'
    exit 0
}
finally {
    [Net.ServicePointManager]::ServerCertificateValidationCallback = $oldCallback
}
