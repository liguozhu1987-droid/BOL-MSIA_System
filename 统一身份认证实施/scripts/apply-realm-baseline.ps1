# =============================================================================
# 方案 A 落地：可执行命令块（realm 基线 / 会话 / 暴力破解 / SMTP / 准入组 / 统一初始密码）
# 文件：统一身份认证实施\scripts\apply-realm-baseline.ps1
#
# 用途
#   把《方案A落地清单》里需要「真的敲命令」的动作收成一个可执行文件，运维小白
#   直接复制运行、按菜单选即可。全部走 Keycloak Admin REST（不依赖 kcadm 会话）。
#
# 执行顺序（也是菜单顺序，建议照此走）
#   1) 备份当前 realm 配置（只读 + 落盘，先做这一步）
#   2) 设置会话时长：空闲 1 天 / 最长 7 天（86400 / 604800 秒）
#   3) 设置暴力破解：连续失败 5 次 / 锁定 900 秒
#   4) 设置 SMTP：172.19.253.10:25，from ap_sso@inalfa.com，明文无认证中继
#   5) 实测发信：先 Test connection 探连通，再触发一封设密邮件，确认「确实收到信」
#   6) 查询缺 email / firstName / lastName 的用户
#   7) 批量加入 app-msia / app-bol 准入组
#   8) 批量设置统一初始密码（Temporary=ON，密码运行时交互输入，不落盘）
#
# 运行方式（任选其一）
#   1) 交互菜单：
#      powershell -NoProfile -ExecutionPolicy Bypass -File ".\apply-realm-baseline.ps1"
#   2) 只跑某个动作：
#      ... -Action BackupCurrent
#      ... -Action SetSession
#      ... -Action SetBruteForce
#      ... -Action SetSmtp
#      ... -Action TestEmail
#      ... -Action FindMissingProfile
#      ... -Action AddGroup -Group app-msia -UserList "C:\sso\work\planA\members-msia.txt"
#      ... -Action SetInitialPassword -UserList "C:\sso\work\planA\users-to-init.txt"
#   3) 密码也可以用参数传入（SecureString，不落盘、不进普通命令行历史）：
#      $p = Read-Host -AsSecureString '统一初始密码'
#      ... -Action SetInitialPassword -UserList ... -InitialPassword $p
#
# 前置条件
#   - 能访问 Keycloak 8443（本机或内网）；
#   - 有 master 域的 kcadmin 账号（脚本会提示输入，口令不落盘）；
#   - 证书文件 C:\keycloak\conf\server.crt.pem 可读（用于证书指纹固定校验）。
#
# 影响范围（改配置前必读）
#   - SetSession：✅ 本次是【加长】（8h→1天、12h→7天）。会话【加长不会】使已登录用户失效
#     （只有缩短才会），所以对在用用户【无感】；但仍然先做备份。
#   - SetBruteForce：参数立即生效，会改变失败计数与锁定等待时间（本次无变更，值与原口径一致）。
#   - SetSmtp：改的是邮件配置，不影响登录；但保存后要实测发信才算完成。
#   - AddGroup：只新增组成员关系，不删除、不改其它属性；对应用访问权限立即生效。
#   - SetInitialPassword：会覆盖清单内每个用户当前密码（含用户已自行改过的密码）。
#     清单必须准确，不要对「已首登」的账号重跑。
#
# 密码安全约定
#   SetInitialPassword 的初始密码只通过 Read-Host -AsSecureString 或 -InitialPassword 传入；
#   仅保存在内存变量中，用于 HTTP 请求体；不写入文件、不写日志、不打印到控制台。
#   ⚠ 本脚本【不包含】任何初始密码的值，文档与仓库里也不应有该值。
#
# 兼容性：Windows PowerShell 5.1（不使用 PS7 专属语法）。
# =============================================================================

[CmdletBinding()]
param(
    [ValidateSet('Menu', 'ShowCurrent', 'BackupCurrent', 'SetSession', 'SetBruteForce',
                 'SetSmtp', 'TestEmail', 'FindMissingProfile', 'AddGroup', 'SetInitialPassword')]
    [string]$Action = 'Menu',

    [string]$Server = 'https://172.26.2.203:8443',
    [string]$Realm = 'inalfa',
    [string]$CertPath = 'C:\keycloak\conf\server.crt.pem',
    [string]$WorkDir = 'C:\sso\work\planA',

    # AddGroup 用：app-msia / app-bol / both
    [ValidateSet('app-msia', 'app-bol', 'both')]
    [string]$Group = 'both',

    # AddGroup / SetInitialPassword 用：每行一个 username 的文本文件（UTF-8）
    [string]$UserList = '',

    # SetInitialPassword 用：统一初始密码（SecureString）。不传则运行时交互输入。
    [System.Security.SecureString]$InitialPassword,

    # 仅当证书文件缺失、确实无法做指纹固定时才使用（会打印醒目警告）
    [switch]$SkipCertCheck
)

$ErrorActionPreference = 'Stop'

# -----------------------------------------------------------------------------
# 通用：输出与目录
# -----------------------------------------------------------------------------
function Write-Section {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor Cyan
}

function Write-Ok    { param([string]$T) Write-Host "[OK]   $T" -ForegroundColor Green }
function Write-Warn2 { param([string]$T) Write-Host "[WARN] $T" -ForegroundColor Yellow }
function Write-Fail  { param([string]$T) Write-Host "[FAIL] $T" -ForegroundColor Red }

function Initialize-WorkDir {
    if (-not (Test-Path -LiteralPath $WorkDir)) {
        New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    }
}

# -----------------------------------------------------------------------------
# 通用：SecureString → 明文字符串（调用方负责在用完后置 $null 并 ZeroFreeBSTR）
# -----------------------------------------------------------------------------
function ConvertFrom-Secure {
    param([Parameter(Mandatory)][System.Security.SecureString]$Sec)
    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Sec)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

# -----------------------------------------------------------------------------
# 通用：证书固定（不关闭校验，只认这一张证书的指纹）
# -----------------------------------------------------------------------------
function Initialize-Tls {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

    if ($SkipCertCheck) {
        Write-Warn2 '已按 -SkipCertCheck 关闭证书校验。仅限临时排障，排查完请立刻改回默认方式。'
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        return
    }

    if (-not (Test-Path -LiteralPath $CertPath)) {
        throw "找不到证书文件：$CertPath。请确认 Keycloak 证书路径，或临时使用 -SkipCertCheck（不推荐）。"
    }

    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CertPath)
    $script:ExpectedThumbprint = $cert.Thumbprint
    Write-Host "证书指纹（将按此固定校验）：$script:ExpectedThumbprint"

    # 只接受指纹一致的证书；其它一律拒绝
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {
        param($sender, $certificate, $chain, $errors)
        return ($certificate.GetCertHashString() -eq $script:ExpectedThumbprint)
    }
}

# -----------------------------------------------------------------------------
# 通用：取管理令牌
# 预期输出：控制台打印「已获取管理令牌」，不打印任何口令
# 失败时看哪里：401 → 用户名/口令错；连不上 → 先看 1.1 服务状态与证书
# -----------------------------------------------------------------------------
function Connect-Kc {
    $user = Read-Host 'kcadmin 用户名（通常是 kcadmin）'
    $sec  = Read-Host 'kcadmin 口令（不回显）' -AsSecureString

    $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($ptr)
        $body = @{
            grant_type = 'password'
            client_id  = 'admin-cli'
            username   = $user
            password   = $plain
        }
        $resp = Invoke-RestMethod -Method POST `
            -Uri "$Server/realms/master/protocol/openid-connect/token" `
            -Body $body -ContentType 'application/x-www-form-urlencoded'
        $script:Token = $resp.access_token
        Write-Ok '已获取管理令牌'
    }
    finally {
        if ($null -ne $plain) { $plain = $null }
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

# -----------------------------------------------------------------------------
# 通用：调用 Admin REST
# 失败时看哪里：错误信息里通常带 HTTP 状态与 Keycloak 的 message；403 → 令牌过期或权限不足
# -----------------------------------------------------------------------------
function Invoke-Kc {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        $Body = $null
    )

    $uri = "$Server/$Path"
    $headers = @{ Authorization = "Bearer $script:Token" }

    if ($null -ne $Body) {
        # 用 -InputObject 而不是管道：避免单元素数组（如 execute-actions-email 的
        # @('UPDATE_PASSWORD')）被管道拆成标量，导致 JSON 从数组退化成字符串
        $json = ConvertTo-Json -InputObject $Body -Depth 20 -Compress
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers `
            -ContentType 'application/json; charset=utf-8' -Body $json
    }
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
}

# -----------------------------------------------------------------------------
# 通用：把当前被改字段备份到 JSON（只备份这些字段，避免把 realm 里的密钥落盘）
# SMTP 备份会自动剔除 password 键，避免把凭据写到磁盘。
# -----------------------------------------------------------------------------
function Backup-RealmFields {
    param(
        [Parameter(Mandatory)][string[]]$Names,
        [Parameter(Mandatory)][string]$Tag
    )

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    $snap = [ordered]@{
        takenAt = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
        realm   = $Realm
        server  = $Server
    }
    foreach ($n in $Names) {
        if ($n -eq 'smtpServer' -and $null -ne $rep.smtpServer) {
            $smtp = @{}
            foreach ($k in $rep.smtpServer.PSObject.Properties.Name) {
                if ($k -eq 'password') { continue }   # 不落盘凭据
                $smtp[$k] = $rep.smtpServer.$k
            }
            $snap[$n] = $smtp
        }
        else {
            $snap[$n] = $rep.$n
        }
    }

    Initialize-WorkDir
    $file = Join-Path $WorkDir ('realm-backup-' + $Tag + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
    ($snap | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $file -Encoding UTF8
    Write-Ok "当前值已备份到：$file"
    return $file
}

# -----------------------------------------------------------------------------
# 通用：修改 realm 字段（先 GET 完整对象再 PUT，避免部分更新把其它字段清空）
# -----------------------------------------------------------------------------
function Update-RealmFields {
    param([Parameter(Mandatory)][hashtable]$Fields)

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    foreach ($k in $Fields.Keys) { $rep.$k = $Fields[$k] }
    Invoke-Kc -Method PUT -Path "admin/realms/$Realm" -Body $rep | Out-Null
    Write-Ok "已提交 realm 更新：$(($Fields.Keys | Sort-Object) -join ', ')"
}

# -----------------------------------------------------------------------------
# 通用：确认（必须输入 YES）
# -----------------------------------------------------------------------------
function Confirm-Strong {
    param([Parameter(Mandatory)][string]$Prompt)
    $ans = Read-Host "$Prompt（输入 YES 继续，其它任意键取消）"
    if ($ans -ne 'YES') { Write-Warn2 '已取消，未做任何修改。'; return $false }
    return $true
}

# -----------------------------------------------------------------------------
# 通用：读取用户清单
# -----------------------------------------------------------------------------
function Read-UserList {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        $Path = Read-Host '用户名清单文件路径（每行一个 username）'
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "找不到清单文件：$Path"
    }
    $names = Get-Content -LiteralPath $Path -Encoding UTF8 |
        Where-Object { $_.Trim() -ne '' } |
        ForEach-Object { $_.Trim() }
    if (@($names).Count -eq 0) { throw "清单为空：$Path" }
    Write-Host "清单读取：$(@($names).Count) 个 username"
    return $names
}

# -----------------------------------------------------------------------------
# 通用：按 username 精确查用户
# -----------------------------------------------------------------------------
function Find-User {
    param([Parameter(Mandatory)][string]$Username)
    $enc = [System.Uri]::EscapeDataString($Username)
    $r = Invoke-Kc -Method GET -Path ("admin/realms/$Realm/users?username=$enc&exact=true")
    if ($null -eq $r -or @($r).Count -eq 0) { return $null }
    return @($r)[0]
}

# =============================================================================
# 动作 1：ShowCurrent —— 只读前置核对
#
# 用途：动手前先看生产 realm 的会话、暴力破解、SMTP 配置现值，作为「改前基线」。
# 预期输出：一张表，含 ssoSessionIdleTimeout / ssoSessionMaxLifespan /
#           accessTokenLifespan / actionTokenGeneratedByUserLifespan /
#           bruteForceProtected / failureFactor / waitIncrementSeconds /
#           maxFailureWaitSeconds / smtpServer(host/port/from) 等。
#           不打印 SMTP password。
# 副作用：无（纯 GET）。
# 失败时看哪里：401/403 → 重新登录；超时 → 8443 不通或证书指纹不匹配。
# =============================================================================
function Action-ShowCurrent {
    Write-Section '当前 realm 基线（只读）'

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"

    $rows = @(
        [pscustomobject]@{ 字段 = 'realm';                          值 = $rep.realm }
        [pscustomobject]@{ 字段 = 'ssoSessionIdleTimeout（秒）';     值 = $rep.ssoSessionIdleTimeout }
        [pscustomobject]@{ 字段 = 'ssoSessionMaxLifespan（秒）';     值 = $rep.ssoSessionMaxLifespan }
        [pscustomobject]@{ 字段 = 'accessTokenLifespan（秒）';       值 = $rep.accessTokenLifespan }
        [pscustomobject]@{ 字段 = 'actionToken(User)（秒）';         值 = $rep.actionTokenGeneratedByUserLifespan }
        [pscustomobject]@{ 字段 = 'bruteForceProtected';             值 = $rep.bruteForceProtected }
        [pscustomobject]@{ 字段 = 'failureFactor';                   值 = $rep.failureFactor }
        [pscustomobject]@{ 字段 = 'waitIncrementSeconds';            值 = $rep.waitIncrementSeconds }
        [pscustomobject]@{ 字段 = 'maxFailureWaitSeconds';           值 = $rep.maxFailureWaitSeconds }
        [pscustomobject]@{ 字段 = 'permanentLockout';                值 = $rep.permanentLockout }
        [pscustomobject]@{ 字段 = 'smtpServer.host';                 值 = $rep.smtpServer['host'] }
        [pscustomobject]@{ 字段 = 'smtpServer.port';                 值 = $rep.smtpServer['port'] }
        [pscustomobject]@{ 字段 = 'smtpServer.from';                 值 = $rep.smtpServer['from'] }
        [pscustomobject]@{ 字段 = 'smtpServer.fromDisplayName';      值 = $rep.smtpServer['fromDisplayName'] }
        [pscustomobject]@{ 字段 = 'smtpServer.auth';                 值 = $rep.smtpServer['auth'] }
        [pscustomobject]@{ 字段 = 'smtpServer.starttls';             值 = $rep.smtpServer['starttls'] }
        [pscustomobject]@{ 字段 = 'smtpServer.ssl';                  值 = $rep.smtpServer['ssl'] }
    )
    $rows | Format-Table -AutoSize | Out-String | Write-Host

    Write-Host '目标值（以交底书 §9.3 / §9.5 为准）：'
    Write-Host '  会话：86400 秒（1 天）/ 604800 秒（7 天）；Access Token 900 秒；Action Token 259200 秒'
    Write-Host '  暴力破解：failureFactor=5，waitIncrementSeconds=900，maxFailureWaitSeconds=900'
    Write-Host '  SMTP：host=172.19.253.10 port=25 from=ap_sso@inalfa.com'
    Write-Host '        （smtpServer 为空说明 realm 未配置 Email，需现场确认）'
}

# =============================================================================
# 动作 2：BackupCurrent —— 前置备份（建议第一步就做）
#
# 用途：把后续会被改动的 realm 字段当前值落盘，作为回滚依据。
#       备份内容：会话 4 项 + 暴力破解 8 项 + SMTP 全部键（自动剔除 password）。
# 预期输出：先打印当前值表，再打印备份文件路径（realm-backup-all-<时间戳>.json）。
# 副作用：只读 realm，额外写一个 JSON 到工作目录；不修改任何配置。
# 失败时看哪里：写文件失败 → 工作目录无权限；GET 失败 → 见 ShowCurrent 的排查。
# =============================================================================
function Action-BackupCurrent {
    Action-ShowCurrent

    Write-Section '备份将被改动的字段'
    $fields = @(
        'ssoSessionIdleTimeout', 'ssoSessionMaxLifespan', 'accessTokenLifespan', 'actionTokenGeneratedByUserLifespan',
        'bruteForceProtected', 'failureFactor', 'waitIncrementSeconds', 'maxFailureWaitSeconds',
        'maxDeltaTimeSeconds', 'permanentLockout', 'quickLoginCheckMilliSeconds', 'minimumQuickLoginWaitSeconds',
        'smtpServer'
    )
    $file = Backup-RealmFields -Names $fields -Tag 'all'
    Write-Host '回滚方式：把该 JSON 里的字段值照原样填回控制台对应页面（Realm Settings → Tokens / Security Defenses / Email）。'
    Write-Host "备份文件：$file"
}

# =============================================================================
# 动作 3：SetSession —— 设置 realm 会话时长
#
# 用途：把会话改为【空闲 1 天 / 最长 7 天】（86400 / 604800 秒，交底书 §9.3 口径）。
# 预期输出：备份文件路径 +「已提交 realm 更新」+ 回读的 4 个值。
# 【影响范围】本次是【加长】（原 8h/12h → 1d/7d）。
#   会话加长【不会】使已登录用户失效（只有缩短才会），对在用用户【无感】；
#   不需要维护窗口，但仍会先备份，便于回滚。
# 失败时看哪里：PUT 400 → 字段名拼错或值类型不是数字；回读值与预期不一致 → 看是否被其它自动化覆盖。
# =============================================================================
function Action-SetSession {
    Write-Section '设置 realm 会话时长（加长，对在用用户无感）'
    Write-Host '本次变更：空闲 28800→86400 秒（1 天）；最长 43200→604800 秒（7 天）。'
    Write-Warn2 '方向性说明：会话【加长不会】踢掉已登录用户（只有缩短才会），所以对在用用户无感。'
    Write-Warn2 '仍然先备份当前值；若回滚到更短的值，就会让已登录会话失效，需要维护窗口。'

    $fields = @('ssoSessionIdleTimeout', 'ssoSessionMaxLifespan', 'accessTokenLifespan', 'actionTokenGeneratedByUserLifespan')
    Backup-RealmFields -Names $fields -Tag 'session' | Out-Null

    if (-not (Confirm-Strong '确认把会话改为 空闲 1 天 / 最长 7 天')) { return }

    Update-RealmFields -Fields @{
        ssoSessionIdleTimeout              = 86400    # 1 天（秒）
        ssoSessionMaxLifespan              = 604800   # 7 天（秒）
        accessTokenLifespan                = 900      # 15 分钟（秒），本次不改
        actionTokenGeneratedByUserLifespan = 259200   # 4320 分钟 = 3 天，本次不改
    }

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    Write-Host ("回读：Idle={0}s Max={1}s AccessToken={2}s ActionToken={3}s" -f `
        $rep.ssoSessionIdleTimeout, $rep.ssoSessionMaxLifespan, `
        $rep.accessTokenLifespan, $rep.actionTokenGeneratedByUserLifespan)
    Write-Host '判据：Idle=86400、Max=604800。'
}

# =============================================================================
# 动作 4：SetBruteForce —— 设置暴力破解防护
#
# 用途：连续失败 5 次 → 锁定 900 秒（交底书 §9.3 口径；本轮无变更，值与原口径一致）。
# 预期输出：备份路径 +「已提交 realm 更新」+ 回读值。
# 【影响范围】参数立即生效，不需要重启；会改变失败计数与锁定等待时间。
#   permanentLockout 保持 false（避免永久锁死账号）。
# 失败时看哪里：回读仍为 false → bruteForceProtected 没写进去；用户反映锁得太久 → 看 waitIncrementSeconds。
# =============================================================================
function Action-SetBruteForce {
    Write-Section '设置暴力破解防护（立即生效）'
    Write-Warn2 '此操作立即影响登录失败计数与锁定等待，不需要重启。'

    $fields = @('bruteForceProtected', 'failureFactor', 'waitIncrementSeconds', 'maxFailureWaitSeconds', 'maxDeltaTimeSeconds', 'permanentLockout', 'quickLoginCheckMilliSeconds', 'minimumQuickLoginWaitSeconds')
    Backup-RealmFields -Names $fields -Tag 'bruteforce' | Out-Null

    if (-not (Confirm-Strong '确认按 连续失败 5 次 / 锁定 900 秒 设置暴力破解')) { return }

    Update-RealmFields -Fields @{
        bruteForceProtected          = $true
        failureFactor                = 5
        waitIncrementSeconds         = 900
        maxFailureWaitSeconds        = 900
        maxDeltaTimeSeconds          = 43200
        permanentLockout             = $false
        quickLoginCheckMilliSeconds  = 1000
        minimumQuickLoginWaitSeconds = 60
    }

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    Write-Host ("回读：Protected={0} FailureFactor={1} WaitIncrement={2}s MaxWait={3}s PermanentLockout={4}" -f `
        $rep.bruteForceProtected, $rep.failureFactor, $rep.waitIncrementSeconds, `
        $rep.maxFailureWaitSeconds, $rep.permanentLockout)
    Write-Host '判据：Protected=True、FailureFactor=5、WaitIncrement=900、MaxWait=900。'
}

# =============================================================================
# 动作 5：SetSmtp —— 写入正式 SMTP 参数
#
# 用途：按交底书 §9.5 写入正式邮箱服务（内网明文无认证中继）。
#   host          172.19.253.10
#   port          25
#   from          ap_sso@inalfa.com
#   fromDisplayName Inalfa AME系统统一身份认证
#   auth          false（无认证）
#   starttls      false
#   ssl           false
# 预期输出：备份路径 +「已提交 realm 更新」+ 回读的 7 个键。
# 【影响范围】只影响发信能力，不影响登录；保存成功【不等于】能发信，必须再做动作 6 实测。
# 【备注】当前是明文内网中继；若后续邮件网关启用 STARTTLS，把 starttls 改为 "true"
#        （必要时同步调整端口），保存后【重新做一次实测发信】。
# 失败时看哪里：PUT 400 → smtpServer 必须是「字符串到字符串」的 map；
#               发信失败 → 先看动作 6 的 Test connection 输出，再看邮件网关是否拦 25 端口。
# =============================================================================
function Action-SetSmtp {
    Write-Section '设置 SMTP（正式服务参数）'
    Write-Host '目标：host=172.19.253.10  port=25  from=ap_sso@inalfa.com  auth/starttls/ssl=false'
    Write-Warn2 '保存成功只代表配置写进去了，不代表能发信。必须接着跑「实测发信」。'

    Backup-RealmFields -Names @('smtpServer') -Tag 'smtp' | Out-Null

    if (-not (Confirm-Strong '确认按上述正式参数写入 realm 的 Email 配置')) { return }

    Update-RealmFields -Fields @{
        smtpServer = @{
            host            = '172.19.253.10'
            port            = '25'
            from            = 'ap_sso@inalfa.com'
            fromDisplayName = 'Inalfa AME系统统一身份认证'
            auth            = 'false'
            starttls        = 'false'
            ssl             = 'false'
        }
    }

    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    $s = $rep.smtpServer
    Write-Host ("回读：host={0} port={1} from={2} fromDisplayName={3} auth={4} starttls={5} ssl={6}" -f `
        $s['host'], $s['port'], $s['from'], $s['fromDisplayName'], $s['auth'], $s['starttls'], $s['ssl'])
    Write-Host '判据：7 个键与上面目标值逐字一致。下一步请跑「实测发信」。'
}

# =============================================================================
# 动作 6：TestEmail —— 实测发信
#
# 用途：分两步验证邮件链路。
#   6.1 用 realm 里已保存的 smtpServer 调 Admin REST 的 testSMTPConnection，
#       证明「连得上、能握手」；
#   6.2 对 1 个测试账号触发 execute-actions-email（UPDATE_PASSWORD），
#       让 Keycloak 真的发一封设密邮件，然后由人确认收件箱【确实收到】。
# 预期输出：6.1 成功/失败；6.2 打印被触发账号与提示去收件箱确认。
# 【影响范围】6.2 会给测试账号加一个 UPDATE_PASSWORD 必需动作（该账号下次登录会被要求改密）；
#   仅对测试账号操作，不要对正式用户跑。
# 【判据】必须是「确实收到邮件」，不是「Test connection successful」，也不是「保存成功」。
# 失败时看哪里：testSMTPConnection 404/405 → 该版本不支持该端点，改用控制台 Test Connection；
#   execute-actions-email 400 → 该用户没有 email 或 email 非法；keycloak.log 搜 Failed to send email。
# =============================================================================
function Action-TestEmail {
    Write-Section '实测发信（真正判据是收到信）'

    # 6.1 连通性探测
    $rep = Invoke-Kc -Method GET -Path "admin/realms/$Realm"
    $smtp = $rep.smtpServer
    if ($null -eq $smtp -or $smtp.Count -eq 0) {
        Write-Fail 'realm 里 smtpServer 为空：先跑动作 4（SetSmtp），或到控制台 Realm Settings → Email 填写。'
        return
    }

    try {
        Invoke-Kc -Method POST -Path "admin/realms/$Realm/testSMTPConnection" -Body $smtp | Out-Null
        Write-Ok 'testSMTPConnection 成功：服务器连得上、能握手。'
        Write-Warn2 '注意：这只证明连通，不证明信能到。必须完成下面的 6.2。'
    }
    catch {
        Write-Fail ("testSMTPConnection 失败：{0}" -f $_.Exception.Message)
        Write-Host '若提示 404/405，说明当前版本不提供该端点，请改用控制台 Realm Settings → Email → Test Connection。'
        Write-Host '若提示连接超时/拒绝，检查 25 端口与防火墙，以及 host/port 是否写错。'
    }

    # 6.2 触发一封设密邮件
    Write-Section '触发一封设密邮件（会改测试账号的必需动作）'
    $uName = Read-Host '用于测试的账号 username（建议专用测试账号，不要用正式用户）'
    if ([string]::IsNullOrWhiteSpace($uName)) { Write-Warn2 '未输入用户名，跳过实测发信。'; return }

    $u = Find-User -Username $uName.Trim()
    if ($null -eq $u) { Write-Fail "找不到用户：$uName"; return }
    if ([string]::IsNullOrWhiteSpace([string]$u.email)) {
        Write-Fail "该用户没有 email，Keycloak 无法发信。先补 email（见动作 6/清单 M05）。"
        return
    }
    Write-Host ("目标：{0}  收件邮箱：{1}" -f $u.username, $u.email)

    if (-not (Confirm-Strong '确认向该账号发送 UPDATE_PASSWORD 设密邮件')) { return }

    try {
        # client_id=account：邮件链接回到 Keycloak 自带 account 控制台；lifespan 与 Action Token 口径一致
        Invoke-Kc -Method POST `
            -Path ("admin/realms/$Realm/users/{0}/execute-actions-email?client_id=account&lifespan=259200" -f $u.id) `
            -Body @('UPDATE_PASSWORD') | Out-Null
        Write-Ok '已提交发送请求（HTTP 204）。'
    }
    catch {
        Write-Fail ("发送请求失败：{0}" -f $_.Exception.Message)
        Write-Host '排查：email 缺失/非法；client account 的 Valid redirect URIs 未配置；SMTP 参数错误。'
        return
    }

    Write-Section '现在必须人工确认'
    Write-Host ("1) 打开 {0} 的收件箱（含垃圾箱），确认【确实收到】一封设密邮件；" -f $u.email)
    Write-Host '2) 点邮件里的链接，应能打开改密页；'
    Write-Host '3) 只有「确实收到信」才算通过。Test connection 成功、保存成功都不算。'
    Write-Warn2 ("收尾：测试账号已被加上 UPDATE_PASSWORD 必需动作，若不想保留，请到控制台 Users → {0} → Details 移除该动作。" -f $u.username)
}

# =============================================================================
# 动作 7：FindMissingProfile —— 查询缺 email / firstName / lastName 的用户
#
# 用途：定位首次登录会被「更新资料」页拦住的账号，作为 M05 批量补齐的输入。
# 预期输出：控制台表格（username / enabled / 缺哪个字段）+ 一份 CSV（不含敏感信息）；
#           末尾给出总数与各类缺失计数。
# 副作用：无（纯 GET + 写 CSV 到工作目录）。
# 失败时看哪里：分页取不全 → 看 max 是否被服务端限制；CSV 打不开 → 用 Excel 以 UTF-8 打开。
# =============================================================================
function Action-FindMissingProfile {
    Write-Section '查询资料缺失用户（email / firstName / lastName）'

    $pageSize = 100
    $first = 0
    $all = @()
    do {
        $page = Invoke-Kc -Method GET -Path ("admin/realms/$Realm/users?briefRepresentation=false&first=$first&max=$pageSize")
        $chunk = @($page)
        if ($chunk.Count -eq 0) { break }
        $all += $chunk
        $first += $chunk.Count
    } while ($chunk.Count -eq $pageSize)

    Write-Host "已取回用户：$($all.Count)"

    $bad = @()
    foreach ($u in $all) {
        $miss = @()
        if ([string]::IsNullOrWhiteSpace([string]$u.email))     { $miss += 'email' }
        if ([string]::IsNullOrWhiteSpace([string]$u.firstName)) { $miss += 'firstName' }
        if ([string]::IsNullOrWhiteSpace([string]$u.lastName))  { $miss += 'lastName' }
        if ($miss.Count -gt 0) {
            $bad += [pscustomobject]@{
                username   = $u.username
                enabled    = $u.enabled
                missing    = ($miss -join ',')
                email      = $u.email
                firstName  = $u.firstName
                lastName   = $u.lastName
            }
        }
    }

    $bad | Format-Table username, enabled, missing -AutoSize | Out-String | Write-Host

    Initialize-WorkDir
    $csv = Join-Path $WorkDir 'need-fill.csv'
    if ($bad.Count -eq 0) {
        $bad = @([pscustomobject]@{ username = '<none>'; enabled = $null; missing = ''; email = ''; firstName = ''; lastName = '' })
    }
    $bad | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8

    Write-Section '统计'
    Write-Host ("缺任一字段：{0} 人 / 共 {1} 人" -f (@($bad | Where-Object { $_.username -ne '<none>' }).Count), $all.Count)
    Write-Host ("  缺 email：{0}"     -f @($all | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.email) }).Count)
    Write-Host ("  缺 firstName：{0}" -f @($all | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.firstName) }).Count)
    Write-Host ("  缺 lastName：{0}"  -f @($all | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.lastName) }).Count)
    Write-Ok "明细已导出：$csv"
    Write-Host '下一步：按《方案A落地清单》M05，用中央表 CN_AME_SSO_User.display_name 只填空值补齐。'
}

# =============================================================================
# 动作 8：AddGroup —— 批量加入 app-msia / app-bol
#
# 用途：把清单里的用户加入准入组（幂等：重复加入不会报错）。
# 预期输出：逐用户 OK/FAIL，最后一行汇总；组不存在会直接中止。
# 副作用：仅新增组成员关系，不删除、不改用户其它属性；应用访问权限立即生效。
# 失败时看哪里：用户不存在 → username 是否 login_name 小写、是否已导入；
#              组找不到 → 必须是顶层组 /app-msia、/app-bol，不是子组。
# =============================================================================
function Action-AddGroup {
    Write-Section '批量加入准入组'

    $groupNames = @()
    if ($Group -eq 'both') { $groupNames = @('app-msia', 'app-bol') } else { $groupNames = @($Group) }

    # 取组：只认顶层组，path 必须精确等于 /app-msia 或 /app-bol
    $allGroups = Invoke-Kc -Method GET -Path "admin/realms/$Realm/groups"
    $targets = @()
    foreach ($gn in $groupNames) {
        $hit = @($allGroups | Where-Object { $_.path -eq "/$gn" })
        if ($hit.Count -eq 0) {
            Write-Fail "找不到顶层组 /$gn。请先在控制台 Groups 里确认它是顶层组（不是子组）。"
            return
        }
        $targets += $hit[0]
        Write-Host ("组 /{0}  id={1}" -f $gn, $hit[0].id)
    }

    $names = Read-UserList -Path $UserList
    $names = @($names)
    if (-not (Confirm-Strong "确认把 $($names.Count) 个用户加入 $(($groupNames -join '、'))")) { return }

    $ok = 0
    $fail = @()
    foreach ($n in $names) {
        $u = Find-User -Username $n
        if ($null -eq $u) { $fail += "$n(用户不存在)"; Write-Fail "$n 用户不存在"; continue }

        $allGood = $true
        foreach ($t in $targets) {
            try {
                Invoke-Kc -Method PUT -Path ("admin/realms/$Realm/users/{0}/groups/{1}" -f $u.id, $t.id) | Out-Null
            }
            catch {
                $allGood = $false
                $fail += ("{0}(加 /{1} 失败: {2})" -f $n, $t.path.TrimStart('/'), $_.Exception.Message)
            }
        }

        if ($allGood) { $ok++; Write-Ok $n } else { Write-Fail $n }
    }

    Write-Section '加组结果'
    Write-Host ("成功 {0} 人，失败 {1} 人" -f $ok, $fail.Count)
    if ($fail.Count -gt 0) {
        Write-Host ($fail | Select-Object -Unique | Out-String)
        Write-Host '排查：确认 username 是 login_name 小写、账号已导入 Keycloak；组必须是顶层组。'
    }
}

# =============================================================================
# 动作 9：SetInitialPassword —— 批量设置统一初始密码
#
# 用途：给清单内所有用户设置同一个初始密码，Temporary=ON（首登必须改密）。
# 预期输出：只输出「成功/失败/补加 UPDATE_PASSWORD」的计数与失败用户名；
#           【绝不输出密码本身】。
# 【安全】密码只来自 -InitialPassword（SecureString）或 Read-Host -AsSecureString；
#         仅存在内存中，不写文件、不写日志、不放进普通命令行参数。
# 【风险】会覆盖清单内每个用户当前的密码（包括用户已自行改过的密码）。
#         清单必须准确，不要对「已首登」的账号重跑。
# 【已知约束】若 S01 启用了 specialChars(1)，不含特殊字符的初始密码会被 400 拒绝；
#             此时脚本会提示并终止该用户，需要先按 S01 备注更换初始密码。
# 失败时看哪里：400 User is not local → 联邦用户（清单 M01）；
#              invalid password → 不满足密码策略（看 S01）；
#              400 其它 → 看 Keycloak 返回的 message。
# =============================================================================
function Action-SetInitialPassword {
    Write-Section '批量设置统一初始密码（Temporary=ON）'
    Write-Warn2 '统一初始密码等于全员共享一个已知秘密，只有「首登即强制改密」生效才可接受。'
    Write-Warn2 '此操作会覆盖清单内所有用户当前密码；不要把已首登的用户放进清单。'

    $names = @(Read-UserList -Path $UserList)

    # 密码来源：参数优先，否则交互输入
    if ($null -ne $InitialPassword -and $InitialPassword.Length -gt 0) {
        $sec = $InitialPassword
        Write-Host '已从 -InitialPassword 参数取得初始密码（不回显）。'
    }
    else {
        $sec = Read-Host '请输入统一初始密码（不回显；只存内存，不落盘）' -AsSecureString
    }
    if ($null -eq $sec -or $sec.Length -eq 0) { Write-Warn2 '未提供密码，已取消。'; return }

    $plain = ConvertFrom-Secure -Sec $sec
    try {
        # 策略自检（不改密码策略，只提前提醒，最终以 realm 密码策略为准）
        if ($plain.Length -lt 10) {
            Write-Warn2 "初始密码长度仅 $($plain.Length) 位，低于建议值 10；请确认满足 realm 密码策略后再继续。"
        }
        if ($plain -notmatch '[^a-zA-Z0-9]') {
            Write-Warn2 '初始密码不含特殊字符：当前能设进去，但一旦 S01 启用 specialChars(1)，批量设密会报 invalid password。'
        }

        if (-not (Confirm-Strong "确认对 $($names.Count) 个用户设置该初始密码")) { return }

        $ok = 0
        $fail = @()
        $needFix = @()

        foreach ($n in $names) {
            $u = Find-User -Username $n
            if ($null -eq $u) { $fail += "$n(用户不存在)"; continue }

            try {
                $body = @{
                    type      = 'password'
                    value     = $plain
                    temporary = $true
                }
                Invoke-Kc -Method PUT -Path ("admin/realms/$Realm/users/{0}/reset-password" -f $u.id) -Body $body | Out-Null
                $ok++

                # 复核 requiredActions：正常情况下 temporary=true 会自动加 UPDATE_PASSWORD
                $chk = Invoke-Kc -Method GET -Path ("admin/realms/$Realm/users/{0}?briefRepresentation=true" -f $u.id)
                $ras = @($chk.requiredActions)
                if (-not ($ras -contains 'UPDATE_PASSWORD')) {
                    $needFix += $n
                    $chk.requiredActions = @($ras + 'UPDATE_PASSWORD' | Select-Object -Unique)
                    Invoke-Kc -Method PUT -Path ("admin/realms/$Realm/users/{0}" -f $u.id) -Body $chk | Out-Null
                    Write-Warn2 "$n 缺 UPDATE_PASSWORD，已补"
                }
            }
            catch {
                $fail += ("{0}({1})" -f $n, $_.Exception.Message)
                Write-Fail $n
            }
        }

        Write-Section '设密结果'
        Write-Host ("成功 {0} 人；失败 {1} 人；补加 UPDATE_PASSWORD {2} 人" -f $ok, $fail.Count, $needFix.Count)
        if ($fail.Count -gt 0) {
            Write-Host ($fail | Select-Object -Unique | Out-String)
            Write-Host '排查：400 User is not local → 该账号是联邦用户（见清单 M01）；invalid password → 不满足密码策略（见 S01）。'
        }

        Write-Section '验证判据（必须做）'
        Write-Host '1) 随机抽 1 个账号首次登录：应被强制跳到改密页，且新密码不能等于初始密码；'
        Write-Host '2) 抽 3 个账号看 Credentials：temporary=true、requiredActions 含 UPDATE_PASSWORD；'
        Write-Host '3) 全量核查无 Temporary=OFF（见清单 M07 的 kcadm 核查命令）。'
    }
    finally {
        if ($null -ne $plain) { $plain = $null }
    }
}

# =============================================================================
# 菜单
# =============================================================================
function Show-Menu {
    Write-Host ''
    Write-Host '请选择动作（建议按 1 → 2/3/4 → 5 → 6 → 7 → 8 的顺序）：'
    Write-Host '  0  退出'
    Write-Host '  1  备份当前 realm 配置（只读 + 落盘，建议第一步做）'
    Write-Host '  2  设置会话时长（空闲 1 天 / 最长 7 天）      [加长，不踢已登录用户]'
    Write-Host '  3  设置暴力破解参数（5 次 / 900 秒）          [立即生效]'
    Write-Host '  4  设置 SMTP（172.19.253.10:25，明文无认证）  [保存≠能发信]'
    Write-Host '  5  实测发信（Test connection + 触发设密邮件）  [判据：确实收到信]'
    Write-Host '  6  查询缺 email / firstName / lastName 的用户'
    Write-Host '  7  批量加入 app-msia / app-bol 准入组'
    Write-Host '  8  批量设置统一初始密码（交互输入，Temporary=ON）'
}

function Invoke-Selected {
    param([string]$Name)
    switch ($Name) {
        'ShowCurrent'       { Action-ShowCurrent }
        'BackupCurrent'     { Action-BackupCurrent }
        'SetSession'        { Action-SetSession }
        'SetBruteForce'     { Action-SetBruteForce }
        'SetSmtp'           { Action-SetSmtp }
        'TestEmail'         { Action-TestEmail }
        'FindMissingProfile'{ Action-FindMissingProfile }
        'AddGroup'          { Action-AddGroup }
        'SetInitialPassword'{ Action-SetInitialPassword }
        default             { Write-Warn2 "未知动作：$Name" }
    }
}

# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
Initialize-Tls
Connect-Kc

if ($Action -ne 'Menu') {
    Invoke-Selected -Name $Action
}
else {
    $mapping = @{
        '1' = 'BackupCurrent'
        '2' = 'SetSession'
        '3' = 'SetBruteForce'
        '4' = 'SetSmtp'
        '5' = 'TestEmail'
        '6' = 'FindMissingProfile'
        '7' = 'AddGroup'
        '8' = 'SetInitialPassword'
    }
    do {
        Show-Menu
        $sel = Read-Host '输入编号'
        if ($sel -eq '0') { break }
        if ($mapping.ContainsKey($sel)) {
            Invoke-Selected -Name $mapping[$sel]
        }
        else {
            Write-Warn2 "无效编号：$sel"
        }
    } while ($true)
}

Write-Host ''
Write-Ok '脚本结束。所有口令类输入均未落盘；如做过 realm 修改，请到工作目录核对备份 JSON。'
