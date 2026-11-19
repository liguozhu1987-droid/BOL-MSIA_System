<#
.SYNOPSIS
    中央人员表 → Keycloak Admin REST 同步（幂等：先查后动作）。
.DESCRIPTION
    T01 实施工件（数据流 1 后半段，方案文档 7.2）。
    流程：读 CN_AME_SSO_User 全量 → 按 kc_user_id（无则 username 查，命中回写）
          → 新人 POST 建号 + execute-actions-email(UPDATE_PASSWORD)
          → 已存在走 GET→改→PUT 整对象（硬规则：禁止部分 PUT）
          → 已存在但中央表 kc_user_id 为空/与 KC 不一致 → 补写一次（2026-11-11 H14）
          → 已存在且 KC 侧无密码凭证 → 可选补发设密邀请
            （-ResendInviteForPasswordless，默认关闭；H14）
          → status=0 且 enabled → 禁用 + POST logout 踢会话
          → 复职 enabled=true（pwd_set=0 重发设密邮件）
          → Keycloak 侧存在 type=password 凭证且无待办改密 → 回写 pwd_set=1
            （2026-11-09 修正: 旧口径只看 requiredActions，会把“无密码、无待办”的
              批量导入用户误标为已设密；改以 /users/{id}/credentials 为准）
          → 写 CN_AME_SSO_SyncLog(phase='KC')。
    单人容错（2026-11-11 H18）:
          默认开启：单个用户在建号/更新/停用/复职时收到 Keycloak 的 4xx/5xx，只记
          WARN（工号 + login + 状态码 + errorMessage 原文）并继续下一个人；令牌/权限
          （401/403）、网络（HTTP 0）、SQL/凭据类错误仍立即中止并告警。
          需要"一出错就停"时加 -StopOnError（建议与 -EmployeeNos 叠加只跑 1 人）。
    邮箱策略（2026-11-02，邮箱暂不用管理）:
          email 为空 → 跳过 execute-actions-email 邀请并登记 SyncLog（待管理员控制台
          代设密 + required action 首登改密，见 realm-setup.md 2.1）；
          中央表无邮箱时不覆盖 KC 侧已有邮箱。
    HTTP 失败按 10/30/60 秒退避重试（5xx/429/网络错误可重试，其余 4xx 快速失败）。

    切换保护（Entra 邮箱账号）:
          若 Keycloak 里多数用户已是邮箱格式（username 含 @），说明已完成 Entra 邮箱账号
          切换：此时中央表 login_name 仍是 AD 短名，本脚本按短名查不到人，会把在职者
          重新建成本地密码账号，形成第二套身份。入口处直接拒绝执行并退出 2。
          回滚后 UPN 账号已清理、短名账号重建，判定自然解除，无需绕过开关。

    白名单（2026-11-11 新增）:
          -EmployeeNos <string[]>  只处理这些 employee_no（逗号分隔或数组）
          -FromPermLedger          从 CN_AME_SSO_PermLedger 取 msia/bol 未撤销的
                                   employee_no 去重后作为白名单
          两者都不传 = 原有的全量行为；两者可叠加。白名单命中 0 人 → 写
          SyncLog(ERROR) + 告警 + exit 1，不会静默成功。
          白名单按 employee_no 过滤，空值/重复自动忽略，未命中的工号以 WARN 列出。

    姓名口径（2026-11-11 调整）:
          优先取括号内 2-4 个汉字 → 整串纯汉字 → 否则回退 login_name；
          lastName 一律留空。畸形数据只走回退，不抛异常。
          回退值再经 ConvertTo-KcPersonName 清洗（H19）: 剔除 <>&"$%!#?§;*~/\|^=[]{}()
          与控制字符、压缩连续空白；单引号保留（Keycloak 允许）。清洗后为空则不写 firstName。

    认证方式：默认 sync-client（confidential + Service Account，client_credentials）；
    如需 admin-cli 口令模式，见 Get-KcToken 内注释。
    Keycloak 口令/secret 从 C:\sso\conf\credentials.xml（DPAPI）读取，不落明文。

.NOTES
    文件: scripts/powershell/sync_sso_to_keycloak.ps1
    调用方: sync_ad_to_sso.ps1 串联 / 手工执行
    依赖: 同 sync_ad_to_sso.ps1（Invoke-Sqlcmd 或 Microsoft.Data.SqlClient）
    退出码: 0=成功 1=失败 2=已切换为 Entra 邮箱账号，拒绝执行
#>
[CmdletBinding()]
param(
    [string]$SqlServer = 'IRSCNYTFINEREPORT.ap.inalfa.local',
    [string]$Database = 'CN_AME',
    [string]$CredentialFile = 'C:\sso\conf\credentials.xml',
    [string]$SqlCredentialName = 'sso_sync_svc',
    [string]$KcClientCredentialName = 'keycloak_sync_client',

    # 邀请设密邮件（execute-actions-email）参数。
    # client_id 必须是 inalfa realm 里长期存在且已启用的 client——Keycloak 用它解析 client
    # 并生成邮件里的链接，解析不到就是 404（与用户是否存在无关）。
    #   默认 account（Keycloak 内置，每个 realm 都有、不会被改名/删除），邮件里的链接
    #   落到 Account 控制台，用户在那里完成 UPDATE_PASSWORD——不依赖任何业务应用的
    #   回调地址。realm 里可用的业务 client 是 msia-prod / bol-prod / sync-client
    #   （见 keycloak/clients.md），注意不叫 msia；它们的 Valid Redirect URIs 是应用
    #   OIDC 回调，改 http/https 就变，不适合当邀请落地页。
    # redirect_uri 默认留空 = 不传，由 Keycloak 按该 client 自身配置决定落地页。
    #   不写死的原因：应用入口随时可能从 http 改成 https，写死的值一旦与 client 的
    #   Valid Redirect URIs 不一致，发信立刻变成 400 Invalid redirect uri。
    # 确需固定落地页时再显式传，且必须与该 client 的 Valid Redirect URIs 逐字一致。
    [string]$InviteClientId = 'account',
    [string]$InviteRedirectUri = '',
    [int]$InviteLifespanSeconds = 43200,

    # Keycloak 基址（2026-11-11 域名切换后：直连 8443，旧域名 sso.ap.inalfa.local 作废）。
    # 末尾不要加斜杠；本机调试可改 https://127.0.0.1:8443。
    # 注意：9000 是 management 口（/health、/metrics），Admin REST 与 token 端点都在 8443。
    [string]$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',
    [string]$Realm = 'inalfa',
    [string]$TokenClientId = 'sync-client',

    # 白名单（2026-11-11 新增）: 只处理指定 employee_no；不传 = 保持原全量行为
    [string[]]$EmployeeNos = @(),
    # 从权限台账自动取白名单: CN_AME_SSO_PermLedger 中 msia/bol 未撤销的 employee_no 去重
    [switch]$FromPermLedger,

    # 排除名单（2026-11-11 新增；H20 定稿）: 逗号/分号分隔的 employee_no，永不推送到 Keycloak。
    # 用字符串而非数组: -File 方式调用时数组参数绑定会失效（"a,b" 会被当成单个字符串）。
    # 默认 15 项 = 服务/机器账号；admin 已移出（用户 2026-11-11 定稿: 要给它建 Keycloak 账号）。
    # 兼作 username 脏数据闸门: t&e 的 &、$duplicate-4f3a 的 $ 都会撞 Keycloak 的 username 校验
    #   （400 error-username-invalid-character），而中央表每天由 MERGE 从 StgAdUser 重灌，
    #   逐条修数据没有意义，只能在同步层拦住。
    # 本文件是唯一权威副本: sync_ad_to_sso.ps1 默认不传本参数，夜间任务沿用这里的默认值。
    [string]$ExcludeEmployeeNos = '$duplicate-4f3a, e-workflow.system, heqi-old, lush-ex, mccaffbr-cn, sccm-admins, sccm-clientpush, sccm-domainjoin, sccm-naa, sccm-siteservers, sccm-sqlreporting, sccm-sqlservice, svc-cohesity-vmware, t&e, zontsso-cn',

    [string]$LogDirectory = 'C:\sso\logs',

    [string]$SmtpServer = '172.19.253.10',
    [int]$SmtpPort = 25,
    [string]$AlertFrom = 'sso-notify@inalfa.local',
    [string[]]$AlertTo = @('ligu@inalfa.local'),

    [int]$MaxRetries = 3,
    [int[]]$BackoffSeconds = @(10, 30, 60),

    # 引导期 Keycloak 8443 为自签证书时可开；生产走企业证书应保持 $false
    [switch]$SkipCertCheck,

    # 补发邀请（2026-11-11 H14 新增）: 对"账号已在 Keycloak、但一条 password 凭证都没有"
    # 的用户补发一次设密邀请（复用 -InviteClientId / -InviteRedirectUri / -InviteLifespanSeconds）。
    # 默认关闭：正常每轮同步不该给同一批无密码用户重复发信。
    # 去重：KC 侧 requiredActions 已含 UPDATE_PASSWORD = 上一封邀请仍未完成 → 本轮跳过，
    #       所以即使开关一直开着也不会重复轰炸；邀请过期后要重发，先在控制台清掉该 required
    #       action 再跑，或让用户走"忘记密码"。
    # 运维用法：需要补发时显式加 -ResendInviteForPasswordless 跑一次（可与 -EmployeeNos 叠加）。
    [switch]$ResendInviteForPasswordless,

    # 批量建号静默模式（2026-11-11 H17）: 本轮不发任何邀请邮件。
    # 建号/复职/无密码补发三条链路的 execute-actions-email 全部跳过，只建号 + 回写 kc_user_id；
    # 用户想登录时再由管理员按需设临时密码（或在 SMTP 就绪后走"忘记密码"）。
    # 与 -ResendInviteForPasswordless 同时指定时，以本开关为准（跳过一切邮件），启动日志会提示。
    # 计划任务/批处理可用：switch 参数，-File 方式直接传 -SkipInvite。
    [switch]$SkipInvite,

    # 单人容错（2026-11-11 H18）: 默认开启。
    # 单个用户在建号/更新/停用/复职时收到 Keycloak 的 4xx/5xx（如 400 脏数据、409 冲突），
    # 只记 WARN（工号 + login_name + HTTP 状态码 + errorMessage 原文）、计入"失败 N"，
    # 然后继续下一个人；整批不再因为一条坏数据归零。
    # 以下三类仍视为致命并立即中止（否则 2851 人会刷出 2851 条重复 WARN）：
    #   401/403（令牌失效/权限不足）、HTTP 0（网络/TLS 握手失败）、非 KC 异常（SQL/凭据/文件）。
    # 需要"一出错就停"排查单个人时加本开关（通常与 -EmployeeNos 叠加只跑 1 人）。
    [switch]$StopOnError
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
# Windows PowerShell 5.1 默认只协商到 TLS 1.0/1.1，而 Keycloak 25 只接受 TLS 1.2+，
# 症状是 "The request was aborted: Could not create SSL/TLS secure channel."（端口通、证书也没问题）。
# 这里不依赖 -SkipCertCheck：协议协商与证书校验是两件事，必须分开处理。
# 只显式启用 Tls12：不叠加 Tls13——旧版 Windows Server 的 Schannel 不认这个标志，
# 一旦放进 SecurityProtocol 反而会让握手直接失败。Tls13 由系统在双方都支持时自动协商。
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$script:SqlServer = $SqlServer
$script:Database = $Database
$script:LogDirectory = $LogDirectory
$script:LogFile = Join-Path $LogDirectory ("sync_sso_to_keycloak_{0:yyyyMMdd}.log" -f (Get-Date))
$script:KcToken = ''
$script:KcTokenExpiry = (Get-Date).AddMinutes(-1)

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

function Get-SecretFromCredentialFile {
    <# 从 credentials.xml 取 UserName/Password 明文字符串（DPAPI 解密）。 #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("凭据文件不存在: {0}。请按 README.md 说明用 DPAPI 生成。" -f $Path)
    }
    [xml]$doc = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $node = $doc.SelectSingleNode(("/Credentials/Credential[@Name='{0}']" -f $Name))
    if ($null -eq $node) {
        throw ("凭据文件 {0} 中找不到名为 '{1}' 的条目。" -f $Path, $Name)
    }
    $secure = ConvertTo-SecureString -String ([string]$node.Password) -ErrorAction Stop
    $plain = (New-Object System.Management.Automation.PSCredential(
        ([string]$node.UserName), $secure)).GetNetworkCredential().Password
    return @{ UserName = [string]$node.UserName; Password = $plain }
}

function Get-DbCredential {
    <# 从 credentials.xml 构造 SQL 登录用的 PSCredential。 #>
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
    <# 执行 SQL；优先 Invoke-Sqlcmd，回退 Microsoft.Data.SqlClient。 #>
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
        [int]$Added = 0,
        [int]$Updated = 0,
        [int]$Disabled = 0,
        [int]$Reactivated = 0,
        [string]$Message = '',
        [Parameter(Mandatory)][System.Management.Automation.PSCredential]$Credential
    )
    $q = @"
INSERT INTO dbo.CN_AME_SSO_SyncLog
    (phase, added, updated, disabled, reactivated, status, message)
VALUES
    ('KC', @added, @updated, @disabled, @reactivated, @status, @message)
"@
    Invoke-SsoSql -Query $q -Parameters @{
        added = $Added; updated = $Updated; disabled = $Disabled
        reactivated = $Reactivated; status = $Status; message = $Message
    } -Credential $Credential | Out-Null
}

function Get-Prop {
    <# StrictMode 下安全取属性。
       Keycloak 的 JSON 只回非空字段（没设过 lastName 就没有 lastName），
       Set-StrictMode -Version Latest 下裸访问 $obj.lastName 会直接抛
       PropertyNotFoundException（"The property 'lastName' cannot be found"）。
       这里统一走 PSObject.Properties 判断：属性缺失或值为 $null 一律返回默认值。 #>
    param(
        [object]$Object,
        [Parameter(Mandatory)][string]$Name,
        [object]$Default = $null
    )
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
    <# 安全写属性：目标对象没有该属性时补 NoteProperty。
       JSON 反序列化对象（PSCustomObject）上给不存在的属性赋值同样会抛
       "The property 'x' cannot be found on this object"，不能直接 $obj.x = ... #>
    param(
        [object]$Object,
        [Parameter(Mandatory)][string]$Name,
        [object]$Value
    )
    if ($null -eq $Object) { return }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
    else {
        $p.Value = $Value
    }
}

function Get-KcToken {
    <# 获取 realm 管理令牌。
       默认: sync-client + client_credentials（Service Account，方案文档 7.1）。
       备选: admin-cli + kcadmin 口令（grant_type=password），将 credentials.xml
             中条目改为 kcadmin，并把 $TokenClientId 置为 'admin-cli'、
             函数体切换为 password 模式即可。 #>
    $sec = Get-SecretFromCredentialFile -Path $CredentialFile -Name $KcClientCredentialName
    $body = @{
        grant_type = 'client_credentials'
        client_id  = $TokenClientId
        client_secret = $sec.Password
    }
    $uri = "$KeycloakBaseUrl/realms/$Realm/protocol/openid-connect/token"
    $tokenResp = Invoke-KcApi -Method Post -Uri $uri -Body $body -IsTokenRequest
    $script:KcToken = [string](Get-Prop $tokenResp 'access_token' '')
    if ($script:KcToken -eq '') {
        throw '令牌端点的返回里没有 access_token，检查 sync-client 的 Service Account 权限与 realm 配置。'
    }
    $expires = [int](Get-Prop $tokenResp 'expires_in' 60)
    $script:KcTokenExpiry = (Get-Date).AddSeconds($expires - 30)
    Write-Log ('Keycloak 管理令牌获取成功（有效期 {0}s）' -f $expires) 'INFO'
}

function Invoke-KcApi {
    <# Keycloak Admin REST 调用，带退避重试。
       可重试: 网络错误(0)/5xx/429；其余 4xx 快速失败。
       -IsTokenRequest: 令牌端点不附带 Bearer 头。 #>
    param(
        [Parameter(Mandatory)][ValidateSet('Get', 'Post', 'Put', 'Delete')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body,
        [switch]$IsTokenRequest
    )
    if ($SkipCertCheck) {
        # PS 5.1 无 -SkipCertificateCheck 参数，用回调跳过证书校验（仅引导期）。
        # TLS 协议已在脚本启动处无条件开启，这里只处理证书校验这一件事。
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
    $headers = @{}
    if (-not $IsTokenRequest) {
        if ($script:KcToken -eq '' -or (Get-Date) -ge $script:KcTokenExpiry) {
            Get-KcToken
        }
        $headers['Authorization'] = "Bearer $script:KcToken"
    }
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            $invokeSplat = @{
                Method = $Method
                Uri = $Uri
                Headers = $headers
                ErrorAction = 'Stop'
            }
            if ($null -ne $Body) {
                if ($IsTokenRequest) {
                    # token 端点只接受 application/x-www-form-urlencoded。
                    # 发 JSON 会被 Keycloak 直接回 400（响应体通常为空），与凭据无关。
                    # 值必须做 URL 编码: secret 里含 + / = 时，不编码会被当成表单分隔符而串位。
                    $pairs = @()
                    foreach ($k in $Body.Keys) {
                        $pairs += ('{0}={1}' -f $k,
                            [System.Uri]::EscapeDataString([string]$Body[$k]))
                    }
                    $invokeSplat['Body'] = ($pairs -join '&')
                    $invokeSplat['ContentType'] = 'application/x-www-form-urlencoded'
                }
                else {
                    $invokeSplat['Body'] = ($Body | ConvertTo-Json -Depth 10 -Compress)
                    $invokeSplat['ContentType'] = 'application/json; charset=utf-8'
                }
            }
            return Invoke-RestMethod @invokeSplat
        } catch {
            $code = 0
            $errBody = ''
            $resp = $null
            try { $resp = $_.Exception.Response } catch { }
            if ($null -ne $resp) {
                try { $code = [int]$resp.StatusCode } catch { $code = 0 }
                # ① HttpWebResponse（PS 5.1 的 Invoke-RestMethod 走 HttpWebRequest）
                try {
                    $stream = $resp.GetResponseStream()
                    if ($null -ne $stream) {
                        $reader = New-Object System.IO.StreamReader($stream)
                        $errBody = $reader.ReadToEnd()
                        $reader.Close()
                    }
                } catch { }
                # ② HttpResponseMessage（走 HttpClient 时才有 Content）
                if ([string]::IsNullOrWhiteSpace($errBody)) {
                    try { $errBody = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult() } catch { }
                }
            }
            # ③ 兜底: PowerShell 已把响应正文放进 ErrorDetails
            if ([string]::IsNullOrWhiteSpace($errBody) -and $null -ne $_.ErrorDetails) {
                $errBody = [string]$_.ErrorDetails.Message
            }
            if ([string]::IsNullOrWhiteSpace($errBody)) {
                $errBody = '(响应体为空) ' + $_.Exception.Message
            }
            $retriable = ($code -eq 0 -or $code -ge 500 -or $code -eq 429)
            if (-not $retriable -or $attempt -ge $MaxRetries) {
                throw ("KC API {0} {1} 失败 (HTTP {2}, 第 {3} 次尝试): {4}" -f
$Method, $Uri, $code, $attempt, $errBody)
            }
            $idx = [math]::Min($attempt - 1, $BackoffSeconds.Count - 1)
            $sleep = $BackoffSeconds[$idx]
            Write-Log ("KC API 失败 (HTTP {0}): {1}；{2}s 后重试 ({3}/{4})" -f
$code, $errBody, $sleep, $attempt, $MaxRetries) 'WARN'
            Start-Sleep -Seconds $sleep
        }
    }
    throw ("KC API {0} {1} 重试 {2} 次后仍失败" -f $Method, $Uri, $MaxRetries)
}

function ConvertTo-KcPersonName {
    <# 剔除 Keycloak 25.0.6 person-name-prohibited-characters 禁止的字符（2026-11-11 H19）。
       规则来源（keycloak 25.0.6 源码 PersonNameProhibitedCharactersValidator）:
         ^[^<>&"\v$%!#?§;*~/\\|^=\[\]{}()\p{Cntrl}]+$
       即禁止: < > & " $ % ! # ? § ; * ~ / \ | ^ = [ ] { } ( ) 与所有控制字符、垂直空白。
       注意: 单引号 '、逗号、冒号、半角空格都不在禁止集里（"O'Brien" 能通过校验），故保留，
             避免把真人姓名改成 "OBrien"。
       处理: 删禁止字符 → 连续空白压成一个半角空格 → 去首尾空白。
       返回空串表示清洗后什么都不剩，调用方据此不写 firstName（比写空串安全）。 #>
    param([AllowEmptyString()][string]$Name)
    if ([string]::IsNullOrEmpty($Name)) { return '' }
    $s = [regex]::Replace($Name, '[<>"&$%!#?§;*~/\\|^=\[\]{}()]', '')
    $s = [regex]::Replace($s, '[\x00-\x1F\x7F-\x9F\u2028\u2029]', '')
    $s = [regex]::Replace($s, '\s+', ' ')
    return $s.Trim()
}

function Split-DisplayName {
    <#
      姓名拆分（2026-11-11 调整: 优先提取纯中文姓名，lastName 仍一律留空）
      优先级:
        1) 括号内的 2-4 个连续汉字: "Qi Yuan (袁琪)" → 袁琪
        2) 整串就是汉字: "袁琪" → 袁琪
        3) 都不匹配 → 回退 login_name（畸形数据只走回退，不抛异常）
      畸形示例: "Qi Yuan 袁琪)" 括号未闭合、"Bonnie Jd.su" 无中文、
                "Cnbj ipqc1" 共享账号、"袁琪（Qi Yuan）" 括号内非中文
                → 全部落到第 3 条（如需提取括号外的中文，另行确认后调整）。
    #>
    param(
        [string]$DisplayName,
        [string]$Fallback = ''
    )
    $text = if ($null -eq $DisplayName) { '' } else { $DisplayName.Trim() }
    if ($text -ne '') {
        # 1) 括号内中文姓名（全角/半角括号都认）
        $m = [regex]::Match($text, '[(（]([\u4e00-\u9fa5]{2,4})[)）]')
        if ($m.Success) {
            return @{ First = $m.Groups[1].Value; Last = '' }
        }
        # 2) 整串纯中文
        if ($text -match '^[\u4e00-\u9fa5]+$') {
            return @{ First = $text; Last = '' }
        }
    }
    # 3) 回退: login_name（Fallback 为空时退回原文，仍不抛异常）
    $fb = if ([string]::IsNullOrWhiteSpace($Fallback)) { $text } else { $Fallback.Trim() }
    # H19: 回退值往往是 login_name 原文，可能含 person-name 校验禁止的字符（如 "T&E" 的 &、
    #      括号、斜杠）。不清洗会让一个人 400 卡住整批，清洗后为空则不写 firstName。
    $clean = ConvertTo-KcPersonName -Name $fb
    if ($clean -cne $fb) {
        Write-Log ("姓名清洗: {0} → {1}" -f $fb, $clean) 'INFO'
    }
    return @{ First = $clean; Last = '' }
}

function Find-KcUserByUsername {
    <# 幂等查找: username 精确匹配，返回用户对象或 $null。 #>
    param([Parameter(Mandatory)][string]$Username)
    $uri = "$KeycloakBaseUrl/admin/realms/$Realm/users?username=$([uri]::EscapeDataString($Username))&exact=true"
    $found = Invoke-KcApi -Method Get -Uri $uri
    if ($null -eq $found) { return $null }
    $arr = @($found)
    if ($arr.Count -eq 0) { return $null }
    return $arr[0]
}

function Get-KcUserById {
    param([Parameter(Mandatory)][string]$Id)
    try {
        return Invoke-KcApi -Method Get -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$Id"
    } catch {
        return $null
    }
}

function Get-KcPasswordCredentialCount {
    <#
      判断“Keycloak 侧到底有没有设过密码”（pwd_set 误判修复，2026-11-09）。
      数据来源: GET /admin/realms/{realm}/users/{id}/credentials
                → 凭证数组；type='password' 的条数即密码凭证数。
      kcadm 等价写法: kcadm.sh get users/<id>/credentials -r inalfa
      返回:
        [int]  密码凭证条数（0 = 确实没有密码，批量导入用户的正常状态）
        $null  接口取不到（403/404/网络异常）→ 调用方必须按“未知”处理，
               本轮不回写 pwd_set（宁可保持原值，也不臆测为“已设密”）
    #>
    param([Parameter(Mandatory)][string]$Id)
    try {
        $creds = Invoke-KcApi -Method Get -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$Id/credentials"
        if ($null -eq $creds) { return 0 }
        $pwdCreds = @(@($creds) | Where-Object {
            ($null -ne $_.PSObject.Properties['type']) -and ([string]$_.type -eq 'password')
        })
        return $pwdCreds.Count
    } catch {
        Write-Log ("读取 Keycloak 凭证失败(用户 {0}): {1}；本轮按未知处理，不回写 pwd_set" -f
            $Id, $_.Exception.Message) 'WARN'
        return $null
    }
}

function Get-KcFailureInfo {
    <# 从异常消息里提取 HTTP 状态码与 Keycloak 的 errorMessage 原文。
       Invoke-KcApi 抛出的消息形如:
         KC API Post https://host/admin/realms/inalfa/users 失败 (HTTP 400, 第 1 次尝试): {"errors":[...]}
       返回 @{ Code=<int>; Summary='<field>:<errorMessage>; ...'; IsKcApi=<bool> }。
       Keycloak 的 400 响应体是 {"errors":[{"field":"username","errorMessage":"..."}]}，
       直接打原文太长且难 grep，这里压成 "username:error-username-invalid-character" 形式；
       解析不出来时回退为响应体原文（截断 300 字符）。
       非 KC 异常（SQL/凭据/文件）Code=0、IsKcApi=$false，调用方按致命错误处理。 #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Message)
    $code = 0
    $m = [regex]::Match($Message, '\(HTTP\s+(\d+)\s*,')
    if ($m.Success) { $code = [int]$m.Groups[1].Value }
    $isKcApi = $Message.TrimStart().StartsWith('KC API ')
    $body = $Message
    $sep = $Message.IndexOf('): ')
    if ($sep -ge 0) { $body = $Message.Substring($sep + 3) }
    $summary = ''
    if ($body.TrimStart().StartsWith('{')) {
        try {
            $obj = $body | ConvertFrom-Json
            $parts = @()
            foreach ($e in @(Get-Prop $obj 'errors' @())) {
                $f = [string](Get-Prop $e 'field' '')
                $k = [string](Get-Prop $e 'errorMessage' '')
                if ($f -ne '' -or $k -ne '') { $parts += ('{0}:{1}' -f $f, $k) }
            }
            if ($parts.Count -gt 0) { $summary = ($parts -join '; ') }
        } catch { }
    }
    if ($summary -eq '') { $summary = $body.Trim() }
    if ($summary.Length -gt 300) { $summary = $summary.Substring(0, 300) + '...' }
    return @{ Code = $code; Summary = $summary; IsKcApi = $isKcApi }
}

# ---------------- 切换保护：检测 Keycloak 是否已是邮箱账号体系 ----------------

function Test-KcUsernameLooksLikeEmail {
    <# 返回 $true 表示 Keycloak 里多数用户是邮箱格式（username 含 @），即已完成 Entra 切换。
       判定：含 @ 的用户数 >= 20 且多于不含 @ 的用户数（保留名单里还有约 40 个短名本地账号）。
       读取失败直接抛出，交给主流程按认证/网络错误中止，不静默放行。 #>
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$RealmName,
        [int]$PageSize = 100
    )
    $withAt = 0
    $withoutAt = 0
    $first = 0
    while ($true) {
        $batch = @((Invoke-KcApi -Method Get -Uri (
            "{0}/admin/realms/{1}/users?briefRepresentation=true&first={2}&max={3}" -f
            $BaseUrl, $RealmName, $first, $PageSize)) | Where-Object { $null -ne $_ })
        if ($batch.Count -eq 0) { break }
        foreach ($u in $batch) {
            $name = ''
            if ($null -ne $u.PSObject.Properties['username']) { $name = [string]$u.username }
            if ($name.Contains('@')) { $withAt++ } else { $withoutAt++ }
        }
        if ($batch.Count -lt $PageSize) { break }
        $first += $PageSize
    }
    return (($withAt -ge 20) -and ($withAt -gt $withoutAt))
}

# ---------------- 主流程 ----------------
$exitCode = 0
$cred = $null
$added = 0; $updated = 0; $disabled = 0; $reactivated = 0; $invited = 0; $pwdSetBackfill = 0
$inviteFailed = 0           # 建号成功但邀请邮件没发出去的人数（需管理员手工设密）
$inviteFailedList = @()     # 上述人员的工号
$pwdSetUnknown = 0   # Keycloak 凭证状态读不到、本轮未回写 pwd_set 的人数
$skippedNoEmail = @()   # 无邮箱、跳过邮件邀请的用户（需管理员控制台代设密，见 realm-setup.md 2.1）
$kcIdBackfill = 0   # "已存在"分支补写 kc_user_id 的人数（H14）
$inviteResent = 0   # 已存在但无密码、本轮补发设密邀请的人数（H14，需 -ResendInviteForPasswordless）
$skippedInvite = 0  # 因 -SkipInvite 主动跳过邀请邮件的人数（H17；建号/复职两条链路）
$failed = 0        # 单人失败（HTTP 4xx/5xx，已跳过继续）的人数（H18）
$failedList = @()  # 上述人员的 "工号/login [HTTP 码] errorMessage" 明细（H18）
try {
    if (-not (Test-Path -LiteralPath $LogDirectory)) {
        New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    }
    Write-Log '================ sync_sso_to_keycloak 开始 ================' 'INFO'
    $cred = Get-DbCredential -Path $CredentialFile -Name $SqlCredentialName
    Get-KcToken

    # ---- 切换保护（2026-11 拍板）----
    # 已完成 Entra 邮箱账号切换时，Keycloak 用户名是完整 UPN，中央表 login_name 仍是短名。
    # 按短名查不到人 → 会把 2822 名在职者重新建成本地密码账号，形成第二套身份。
    # 现场确认本脚本没有定期任务，只剩手工误执行的风险，因此在入口处硬拒绝，不提供绕过参数。
    if (Test-KcUsernameLooksLikeEmail -BaseUrl $KeycloakBaseUrl -RealmName $Realm) {
        $emsg = ('拒绝执行：Keycloak 里多数用户已是邮箱格式，说明已完成 Entra 邮箱账号切换。' +
            '按 login_name 同步会对在职者重建本地密码账号（第二套身份）。' +
            '确需回滚，先按《零改动切换 Microsoft Entra 邮箱账号》第 7 节清理 UPN 账号，再运行本脚本。')
        Write-Log $emsg 'ERROR'
        try { Write-SyncLog -Status 'ERROR' -Message $emsg -Credential $cred } catch { }
        try {
            Send-AlertMail -Subject '[SSO告警] Keycloak 同步被拒绝（已切换为 Entra 邮箱账号）' -Body (
                $emsg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
        } catch { }
        exit 2
    }

    $users = Invoke-SsoSql -Query @"
SELECT employee_no, login_name, display_name, email, status, source, pwd_set, kc_user_id
FROM dbo.CN_AME_SSO_User
ORDER BY employee_no
"@ -Credential $cred

    # ---- 白名单（2026-11-11 新增）----
    # 不传 -EmployeeNos / -FromPermLedger 时 $whitelist 为空，下面整段不生效，行为与原来完全一致。
    $whitelist = New-Object System.Collections.Generic.List[string]
    if ($FromPermLedger) {
        $ledgerRows = Invoke-SsoSql -Query @"
SELECT DISTINCT employee_no
FROM dbo.CN_AME_SSO_PermLedger
WHERE system_code IN (N'msia', N'bol')
  AND revoked_at IS NULL
ORDER BY employee_no
"@ -Credential $cred
        foreach ($r in @($ledgerRows)) {
            if ($null -ne $r -and -not [string]::IsNullOrWhiteSpace([string]$r.employee_no)) {
                $whitelist.Add(([string]$r.employee_no).Trim())
            }
        }
        Write-Log ("-FromPermLedger: 从权限台账取到 {0} 个工号（msia/bol，未撤销）" -f @($whitelist).Count) 'INFO'
    }
    foreach ($n in @($EmployeeNos)) {
        if (-not [string]::IsNullOrWhiteSpace($n)) { $whitelist.Add($n.Trim()) }
    }
    $whitelist = @($whitelist | Sort-Object -Unique)

    if ($whitelist.Count -gt 0) {
        $totalInTable = @($users).Count
        $wanted = @{}
        foreach ($n in $whitelist) { $wanted[$n.ToUpperInvariant()] = $n }
        $users = @(@($users) | Where-Object {
            $null -ne $_ -and $wanted.ContainsKey(([string]$_.employee_no).Trim().ToUpperInvariant())
        })
        $hit = @{}
        foreach ($u in $users) { $hit[([string]$u.employee_no).Trim().ToUpperInvariant()] = $true }
        $missing = @($whitelist | Where-Object { -not $hit.ContainsKey($_.ToUpperInvariant()) })

        Write-Log ("白名单启用: 请求 {0} 个工号，中央表命中 {1} 人（表内共 {2} 人）" -f
            $whitelist.Count, $users.Count, $totalInTable) 'INFO'
        if ($missing.Count -gt 0) {
            Write-Log ("以下工号在 CN_AME_SSO_User 中未找到，已跳过: {0}" -f ($missing -join ', ')) 'WARN'
        }
        if ($users.Count -eq 0) {
            $emsg = "白名单命中 0 人（请求 $($whitelist.Count) 个工号: $($whitelist -join ',')），已中止，未做任何 Keycloak 变更。"
            Write-Log $emsg 'ERROR'
            Write-SyncLog -Status 'ERROR' -Message $emsg -Credential $cred
            Send-AlertMail -Subject '[SSO告警] Keycloak 同步中止（白名单 0 命中）' -Body ($emsg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
            exit 1
        }
    }

    # ---- 排除名单（2026-11-11 新增；H20 定稿 15 项）----
    # 默认排除 15 个服务/机器账号（admin 已移出，需要建号），脏字符不再触发 400。
    # 不传 -ExcludeEmployeeNos = 用参数默认的 15 项；传空字符串 '' 可关闭本段（全员同步）。
    $exList = @($ExcludeEmployeeNos -split '[,;]' |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -ne '' })
    if ($exList.Count -gt 0) {
        $exSet = @{}
        foreach ($n in $exList) { $exSet[$n.ToUpperInvariant()] = $true }
        $before = @($users).Count
        $users = @(@($users) | Where-Object {
            $null -ne $_ -and
            -not $exSet.ContainsKey(([string]$_.employee_no).Trim().ToUpperInvariant())
        })
        Write-Log ("排除名单生效: {0} 个工号，{1} → {2} 人" -f
            $exList.Count, $before, @($users).Count) 'INFO'
        if (@($users).Count -eq 0) {
            $emsg = "排除名单后无待同步用户（排除: $($exList -join ',')），已退出，未做任何 Keycloak 变更。"
            Write-Log $emsg 'WARN'
            Write-SyncLog -Status 'OK' -Message $emsg -Credential $cred
            exit 0
        }
    }

    if ($null -eq $users -or @($users).Count -eq 0) {
        Write-Log '中央人员表为空，无需同步。' 'WARN'
        Write-SyncLog -Status 'OK' -Message '中央表为空' -Credential $cred
        exit 0
    }
    # 把实际会用的邀请邮件参数打出来，避免下次靠猜（client 不存在 → 404；redirect_uri 不匹配 → 400）
    $shownRedirect = $InviteRedirectUri
    if ($shownRedirect -eq '') { $shownRedirect = '(未传，由 Keycloak 按 client 配置决定)' }
    Write-Log ("邀请邮件参数: client_id={0}; redirect_uri={1}; lifespan={2}s" -f
        $InviteClientId, $shownRedirect, $InviteLifespanSeconds) 'INFO'
    if ($SkipInvite) {
        Write-Log '-SkipInvite 已启用：本轮不发送任何邀请邮件（建号/复职/补发全部跳过），只建号并回写 kc_user_id。' 'WARN'
        if ($ResendInviteForPasswordless) {
            Write-Log '-SkipInvite 与 -ResendInviteForPasswordless 同时指定：以 -SkipInvite 为准，补发邀请不会执行。' 'WARN'
        }
    }
    Write-Log ("待同步用户 {0} 人" -f @($users).Count) 'INFO'

    foreach ($u in $users) {
        # ================= H18 单人容错 =================
        # 整个用户处理体包在 try/catch 里：单个用户的失败不再让整批归零。
        # 注意: 下面这段 body 保持原缩进（PowerShell 不要求缩进对齐），
        #       避免为加一层 try 而整体重排 250 行、把补丁变成不可核对的大 diff。
        $uLogin = [string]$u.login_name
        $uEmpNo = [string]$u.employee_no
        try {
        $uEmail = if ($null -ne $u.email) { [string]$u.email } else { '' }
        $uName = if ($null -ne $u.display_name) { [string]$u.display_name } else { '' }
        $uStatus = [int]$u.status
        $nameParts = Split-DisplayName -DisplayName $uName -Fallback $uLogin

        # 1) 幂等查找（kc_user_id 优先，username 兜底并回写）
        $kcUser = $null
        if (-not [string]::IsNullOrWhiteSpace([string]$u.kc_user_id)) {
            $kcUser = Get-KcUserById ([string]$u.kc_user_id)
            if ($null -eq $kcUser) {
                Write-Log ("kc_user_id {0} 在 KC 不存在，回落 username 查找: {1}" -f
$u.kc_user_id, $uLogin) 'WARN'
            }
        }
        if ($null -eq $kcUser) {
            $kcUser = Find-KcUserByUsername -Username $uLogin
        }

        # 2) 新人: POST 建号 + 邀请设密邮件
        if ($null -eq $kcUser) {
            # 空值一律不写进 body：Keycloak 不接受空串 email，firstName/lastName 写空串
            # 会在后续 PUT 里把已有值清掉；"字段缺失"比"字段为空"更安全。
            $newUser = @{
                username = $uLogin
                enabled = ($uStatus -eq 1)
                emailVerified = $false
            }
            if ($uEmail -ne '') { $newUser['email'] = $uEmail }
            if ([string]$nameParts.First -ne '') { $newUser['firstName'] = [string]$nameParts.First }
            if ([string]$nameParts.Last -ne '') { $newUser['lastName'] = [string]$nameParts.Last }
            Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users" -Body $newUser
            $kcUser = Find-KcUserByUsername -Username $uLogin
            if ($null -eq $kcUser) { throw ("建号后未找到用户 {0}" -f $uLogin) }
            $added++
            $kcId = [string](Get-Prop $kcUser 'id' '')
            if ($kcId -eq '') { throw ("建号后返回的用户对象缺 id: {0}" -f $uLogin) }
            Write-Log ("建号: {0} ({1})" -f $uLogin, $kcId) 'INFO'
            # 建号成功即回写 kc_user_id：账号已经建成，不该因为后面的邀请邮件失败而丢掉。
            Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = @id, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ id = $kcId; emp = [string]$u.employee_no } -Credential $cred | Out-Null
            if ($SkipInvite) {
                # H17 批量建号静默模式：不发邀请，用户首次登录前由管理员按需设密。
                $skippedInvite++
                Write-Log ("跳过邀请(-SkipInvite): {0}" -f $uLogin) 'INFO'
            }
            elseif ($uEmail -ne '') {
                # 邀请设密邮件只是"顺带"，失败只记 WARN 并继续下一个人（2026-11-11 修正：
                # 旧版一失败就整轮中止，1 个人发信失败会让后面所有人都不跑）。
                # 404 的常见原因只有两类：client_id 在 realm 里不存在，或 redirect_uri 不属于
                # 该 client 的 Valid Redirect URIs。默认不传 redirect_uri，避免应用回调改口径
                # （http→https）时又变成 400 Invalid redirect uri。
                try {
                    $inviteBody = @{
                        actions   = @('UPDATE_PASSWORD')
                        client_id = $InviteClientId
                        lifespan  = $InviteLifespanSeconds
                    }
                    if ($InviteRedirectUri -ne '') { $inviteBody['redirect_uri'] = $InviteRedirectUri }
                    Invoke-KcApi -Method Post `
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/execute-actions-email" `
                        -Body $inviteBody
                    $invited++
                    Write-Log ("已发邀请设密邮件: {0} -> {1}" -f $uLogin, $uEmail) 'INFO'
                } catch {
                    $inviteFailed++
                    $inviteFailedList += $uLogin
                    Write-Log ("邀请设密邮件发送失败（建号已成功，继续下一个）: {0} -> {1}; {2}" -f
                        $uLogin, $uEmail, $_.Exception.Message) 'WARN'
                }
            } else {
                # 邮箱暂不用管理：无邮箱跳过邮件邀请，登记待管理员控制台代设密
                $skippedNoEmail += $uLogin
                Write-Log ("用户 {0} 无邮箱，跳过邀请邮件（需管理员控制台代设密+首登改密）" -f $uLogin) 'WARN'
            }
        }
        else {
            # 3) 已存在: 差异比对 → GET 整对象 → 改 → PUT 整对象（硬规则）
            # Keycloak 的 JSON 只包含非空字段，所有字段一律经 Get-Prop 取，
            # 缺字段当空串处理（StrictMode 下裸访问会抛 PropertyNotFoundException）。
            $needUpdate = $false
            $kcId = [string](Get-Prop $kcUser 'id' '')
            $kcUsername = [string](Get-Prop $kcUser 'username' '')
            $kcEmail = [string](Get-Prop $kcUser 'email' '')
            $kcFirst = [string](Get-Prop $kcUser 'firstName' '')
            $kcLast = [string](Get-Prop $kcUser 'lastName' '')
            if ($kcUsername -ne $uLogin) { $needUpdate = $true }
            # 空值不比对、也不写回：中央表没有的值不能拿来清空 Keycloak 已有值，
            # 否则每轮都会"更新"一次，还会把人工维护的邮箱/姓氏抹掉。
            if ($uEmail -ne '' -and $kcEmail -ne $uEmail) { $needUpdate = $true }
            if ([string]$nameParts.First -ne '' -and $kcFirst -ne [string]$nameParts.First) { $needUpdate = $true }
            if ([string]$nameParts.Last -ne '' -and $kcLast -ne [string]$nameParts.Last) { $needUpdate = $true }
            if ([bool](Get-Prop $kcUser 'enabled' $false) -ne ($uStatus -eq 1)) { $needUpdate = $true }
            if ($needUpdate) {
                $full = Get-KcUserById $kcId
                if ($null -eq $full) { throw ("GET 整对象失败: {0}" -f $uLogin) }
                Set-Prop $full 'username' $uLogin
                if ($uEmail -ne '') { Set-Prop $full 'email' $uEmail }
                if ([string]$nameParts.First -ne '') { Set-Prop $full 'firstName' ([string]$nameParts.First) }
                if ([string]$nameParts.Last -ne '') { Set-Prop $full 'lastName' ([string]$nameParts.Last) }
                Set-Prop $full 'enabled' ($uStatus -eq 1)
                Invoke-KcApi -Method Put `
                    -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" `
                    -Body $full
                $updated++
                Write-Log ("更新用户资料(整对象PUT): {0}" -f $uLogin) 'INFO'
                $kcUser = $full
            }

            # 3.1) 回写 kc_user_id（2026-11-11 H14）：上一轮可能在"建号成功、回写之前"中止
            #      （例如邀请邮件 404），中央表 kc_user_id 会一直是 NULL；而这一轮走的是
            #      "已存在"分支，旧版该分支只比对资料、从不写回，于是这个洞永远补不上。
            #      判据：中央表值空、或与 KC 返回的 id 不一致 → 写一次；一致则不发 SQL。
            $dbKcId = [string]$u.kc_user_id
            if ($kcId -ne '' -and $dbKcId -ne $kcId) {
                Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = @id, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ id = $kcId; emp = [string]$u.employee_no } -Credential $cred | Out-Null
                $kcIdBackfill++
                Write-Log ("回写 kc_user_id: {0} -> {1}" -f $uLogin, $kcId) 'INFO'
            }

            # 3.2) 已存在但无密码 → 补发设密邀请（H14，需显式 -ResendInviteForPasswordless）
            #      旧版只在"新建"和"复职"发邀请：账号先建好、邀请没发出去的（如 abelmi2）
            #      永远收不到信，pwd_set 也永远是 0，结果就是"有账号但登不进"。
            #      去重靠 KC 侧状态，不用额外加列：requiredActions 含 UPDATE_PASSWORD
            #      = 上一封邀请还没完成 → 跳过，不会每轮重复发信。
            #      停用用户（status=0）不发，避免给已离职账号发设密链接。
            if ($ResendInviteForPasswordless -and -not $SkipInvite -and $uStatus -eq 1) {
                $resendPwdCreds = Get-KcPasswordCredentialCount -Id $kcId
                if ($null -eq $resendPwdCreds) {
                    Write-Log ("补发邀请跳过(凭证不可读，无法判断有无密码): {0}" -f $uLogin) 'WARN'
                }
                elseif ($resendPwdCreds -gt 0) {
                    # 已有密码凭证，正常用户，什么都不做
                }
                elseif (@(Get-Prop $kcUser 'requiredActions' @()) -contains 'UPDATE_PASSWORD') {
                    Write-Log ("补发邀请跳过(已有未完成的设密邀请): {0}" -f $uLogin) 'INFO'
                }
                elseif ($uEmail -eq '') {
                    if ($skippedNoEmail -notcontains $uLogin) { $skippedNoEmail += $uLogin }
                    Write-Log ("补发邀请跳过(无邮箱，需管理员控制台代设密): {0}" -f $uLogin) 'WARN'
                }
                else {
                    try {
                        $resendBody = @{
                            actions   = @('UPDATE_PASSWORD')
                            client_id = $InviteClientId
                            lifespan  = $InviteLifespanSeconds
                        }
                        if ($InviteRedirectUri -ne '') { $resendBody['redirect_uri'] = $InviteRedirectUri }
                        Invoke-KcApi -Method Post `
                            -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/execute-actions-email" `
                            -Body $resendBody
                        $invited++
                        $inviteResent++
                        Write-Log ("补发邀请设密邮件: {0} -> {1}" -f $uLogin, $uEmail) 'INFO'
                    } catch {
                        $inviteFailed++
                        $inviteFailedList += $uLogin
                        Write-Log ("补发邀请设密邮件失败（账号已存在，继续下一个）: {0} -> {1}; {2}" -f
                            $uLogin, $uEmail, $_.Exception.Message) 'WARN'
                    }
                }
            }
        }

        # 4) 离职停用: status=0 且 KC 仍启用 → 禁用 + 踢会话
        # 快照在每轮改动之后重算：上面 PUT 可能已经把 enabled 改掉，不能用旧值判断。
        $kcId = [string](Get-Prop $kcUser 'id' '')
        $kcEnabled = [bool](Get-Prop $kcUser 'enabled' $false)
        if ($uStatus -eq 0 -and $kcEnabled) {
            $full = Get-KcUserById $kcId
            if ($null -eq $full) { throw ("GET 整对象失败(停用): {0}" -f $uLogin) }
            Set-Prop $full 'enabled' $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
            try {
                Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/logout"
            } catch {
                Write-Log ("踢会话失败(不影响停用结果): {0} - {1}" -f $uLogin, $_.Exception.Message) 'WARN'
            }
            $disabled++
            Write-Log ("已禁用并踢会话: {0}" -f $uLogin) 'INFO'
        }

        # 5) 复职: status=1 且 KC 仍禁用 → 启用；pwd_set=0 重发设密邮件
        if ($uStatus -eq 1 -and -not $kcEnabled) {
            $full = Get-KcUserById $kcId
            if ($null -eq $full) { throw ("GET 整对象失败(复职): {0}" -f $uLogin) }
            Set-Prop $full 'enabled' $true
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
            $reactivated++
            Write-Log ("已复职: {0}" -f $uLogin) 'INFO'
            if (-not [bool]$u.pwd_set) {
                if ($SkipInvite) {
                    $skippedInvite++
                    Write-Log ("跳过邀请(-SkipInvite,复职): {0}" -f $uLogin) 'INFO'
                }
                elseif ($uEmail -ne '') {
                    # 与新人分支同一口径：裸数组缺 client_id 会让 Keycloak 解析不到 client 而回 404
                    $reactBody = @{
                        actions   = @('UPDATE_PASSWORD')
                        client_id = $InviteClientId
                        lifespan  = $InviteLifespanSeconds
                    }
                    if ($InviteRedirectUri -ne '') { $reactBody['redirect_uri'] = $InviteRedirectUri }
                    Invoke-KcApi -Method Post `
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/execute-actions-email" `
                        -Body $reactBody
                    $invited++
                    Write-Log ("复职重发设密邮件: {0}" -f $uLogin) 'INFO'
                } else {
                    # 无邮箱复职用户：登记待管理员控制台代设密
                    if ($skippedNoEmail -notcontains $uLogin) { $skippedNoEmail += $uLogin }
                    Write-Log ("复职用户 {0} 无邮箱，需管理员控制台代设密" -f $uLogin) 'WARN'
                }
            }
        }

        # 6) pwd_set 回写（2026-11-09 修订，修复“无密码却标已设密”的误判）
        #    旧口径: requiredActions 不含 UPDATE_PASSWORD → 置 1。
        #            批量导入的 1000+ 用户既无密码、也无 requiredAction，会被误标。
        #    新口径: Keycloak 侧存在 type=password 凭证，且 requiredActions 不含
        #            UPDATE_PASSWORD（管理员代设临时密码、仍需首登改密的，保持 0）。
        #    降级: credentials 接口取不到（403/404/网络）→ 状态未知 → 不回写，保持原值。
        if (-not [bool]$u.pwd_set) {
            # requiredActions 在 Keycloak 返回里经常整个字段缺失（没有待办动作时）
            $actions = @(Get-Prop $kcUser 'requiredActions' @())
            if ($actions -contains 'UPDATE_PASSWORD') {
                # 仍待首登改密 → 必然未完成首次设密，保持 0，无需再查凭证（省一次 HTTP）
                Write-Log ("pwd_set 保持 0(待首登改密): {0}" -f $uLogin) 'INFO'
            } else {
                $pwdCreds = Get-KcPasswordCredentialCount -Id $kcId
                if ($null -eq $pwdCreds) {
                    # 取不到 → 未知；绝不臆测成“已设密”
                    $pwdSetUnknown++
                    Write-Log ("pwd_set 未回写(Keycloak 凭证不可读，状态未知): {0}" -f $uLogin) 'WARN'
                } elseif ($pwdCreds -gt 0) {
                    Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET pwd_set = 1, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp AND pwd_set = 0
"@ -Parameters @{ emp = [string]$u.employee_no } -Credential $cred | Out-Null
                    $pwdSetBackfill++
                    Write-Log ("pwd_set 回写=1: {0}" -f $uLogin) 'INFO'
                }
                # $pwdCreds = 0: 确实没有密码（批量导入用户的正常状态），保持 0，不打日志
            }
        }
        }   # H18: 关闭 try 体（上一行关的是 if (-not $u.pwd_set)）
        catch {
            # ---- H18: 单人失败，不终止整批 ----
            $failMsg = [string]$_.Exception.Message
            $failInfo = Get-KcFailureInfo -Message $failMsg
            # 致命判定: -StopOnError / 非 KC 异常（SQL、凭据）/ 网络(HTTP 0) / 令牌与权限(401、403)
            $fatal = ($StopOnError -or (-not $failInfo.IsKcApi) -or
                      ($failInfo.Code -eq 0) -or ($failInfo.Code -eq 401) -or ($failInfo.Code -eq 403))
            if ($fatal) {
                Write-Log ("同步失败(致命，立即中止): 工号={0}; login={1}; {2}" -f
                    $uEmpNo, $uLogin, $failInfo.Summary) 'ERROR'
                throw
            }
            $failed++
            $failedList += ("{0}/{1} [HTTP {2}] {3}" -f $uEmpNo, $uLogin, $failInfo.Code, $failInfo.Summary)
            Write-Log ("同步失败(已跳过，继续下一个): 工号={0}; login={1}; HTTP {2}; {3}" -f
                $uEmpNo, $uLogin, $failInfo.Code, $failInfo.Summary) 'WARN'
        }
    }

    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9} / 跳过邀请 {10} / 失败 {11}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown, $skippedInvite, $failed)
    if ($inviteFailedList.Count -gt 0) {
        $msg += ("；邀请邮件未发出: {0}" -f ($inviteFailedList -join ', '))
    }
    if ($failed -gt 0) {
        # 逐人明细已在上方 WARN 行里；汇总里只列前 20 条，避免 2851 条撑爆一行日志/SyncLog。
        $shownFailed = @($failedList | Select-Object -First 20)
        $msg += ("；失败 {0} 人（最多列 20 条）: {1}" -f $failed, ($shownFailed -join ' | '))
        if ($failed -gt $shownFailed.Count) {
            $msg += ("；其余 {0} 条见上方逐人 WARN 行" -f ($failed - $shownFailed.Count))
        }
    }
    if ($skippedNoEmail.Count -gt 0 -or $inviteFailedList.Count -gt 0 -or $failed -gt 0) {
        # 无邮箱 / 发信失败：都是"账号已建好但缺设密链路"，需管理员控制台代设密（realm-setup.md 2.1）
        $msg += ("；无邮箱跳过邀请 {0} 人（待管理员代设密）: {1}" -f
            $skippedNoEmail.Count, ($skippedNoEmail -join ', '))
        Write-Log $msg 'WARN'
    } else {
        Write-Log $msg 'INFO'
    }
    # H18: 0 成功 + 有失败 = 系统性配置问题（user profile 规则/令牌权限/SMTP），
    #      不能静默退 0，否则计划任务会以为整批跑成功。
    if ($failed -gt 0 -and ($added + $updated + $disabled + $reactivated) -eq 0) {
        throw ("本轮 {0} 人全部失败、无任何成功动作，按致命错误处理：请先核对 realm 的 user profile 校验规则与 sync-client 权限。逐人原因见上方 WARN 行。" -f $failed)
    }
    Write-SyncLog -Status 'OK' -Added $added -Updated $updated -Disabled $disabled `
        -Reactivated $reactivated -Message $msg -Credential $cred
}
catch {
    $msg = 'sync_sso_to_keycloak 执行失败: ' + $_.Exception.Message
    Write-Log $msg 'ERROR'
    if ($null -ne $cred) {
        try {
            Write-SyncLog -Status 'ERROR' -Added $added -Updated $updated -Disabled $disabled `
                -Reactivated $reactivated -Message $msg -Credential $cred
        } catch {
            Write-Log ('写 SyncLog(ERROR) 失败: {0}' -f $_.Exception.Message) 'ERROR'
        }
    }
    Send-AlertMail -Subject '[SSO告警] Keycloak 同步失败（ERROR）' -Body ($msg + "`n`n服务器: $env:COMPUTERNAME`n时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    exit 1
}

Write-Log '================ sync_sso_to_keycloak 结束 ================' 'INFO'
exit 0
