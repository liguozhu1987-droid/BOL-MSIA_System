<#
.SYNOPSIS
    sync_sso_to_keycloak.ps1 现场补丁（2026-11-11 修复批），可重复执行。
.DESCRIPTION
    目标机上没有仓库工作区，只能把旧脚本原地升级。本脚本按"函数/文本锚点"精确替换，
    覆盖 18 项（H13 含 12 个子段、H14 含 5 个子段、H17 含 7 个子段、H18 含 8 个子段、
    H19 含 3 个子段、H20 含 2 个子段）：
      H1  Invoke-SsoSql ：去掉 -Variable（SqlServer 21.x 不接受 hashtable；且其占位符是
                          $(name)，与本文件查询里的 @name 不匹配），改为 @name -> 转义字面量。
                          一次覆盖 3 条 SQL 路径：写 SyncLog、回写 kc_user_id、回写 pwd_set。
      H2  Invoke-KcApi  ：(1) token 请求改用 application/x-www-form-urlencoded（值 URL 编码）；
                          (2) 失败时把响应体写进异常消息（三来源提取）。
      H3  Write-SyncLog ：去掉多余的单引号预转义（改由 H1 统一转义，避免双重转义）。
      H4  TLS           ：脚本启动处无条件启用 Tls12（可选，已存在则跳过）。
      H5  默认基址       ：sso.ap.inalfa.local -> iame.ap.inalfa.local:8443（可选，已是新值则跳过）。
      H6  新人分支       ：建号 -> 立即回写 kc_user_id；邀请邮件包 try/catch，失败只记 WARN 不中断。
      H7  汇总行         ：增加"建号但未发邀请"计数与名单。
      H8  计数初始化     ：$inviteFailed / $inviteFailedList。
      H9  邀请邮件参数   ：新增 -InviteClientId（默认 account）/ -InviteRedirectUri（默认空=不传）/
                          -InviteLifespanSeconds（默认 43200）。
      H10 邀请参数日志   ：启动时打印实际使用的 client_id / redirect_uri / lifespan。
      H11 复职重发邀请   ：复职分支的 execute-actions-email 同样改为带 client_id/lifespan。
      H12 if 表达式      ：(if ...) 在 PS 5.1 里不是表达式（会被当命令执行 → 运行期
                          "The term 'if' is not recognized"），改为先取变量再比较。
      H13 StrictMode     ：Keycloak 的 JSON 只回非空字段，裸访问 $kcUser.lastName 运行期抛
                          "The property 'lastName' cannot be found"。新增 Get-Prop/Set-Prop，
                          全部 JSON 取值/写值改走助手；空值不写回（不清空 KC 已有值）。
                          落盘后额外用 AST 检查裸属性访问，命中即回滚。
      H14 已存在分支补洞 ：(a) 新增 -ResendInviteForPasswordless 开关（默认关闭）；
                          (b) 计数器 $kcIdBackfill / $inviteResent；
                          (c) "已存在"分支补写 kc_user_id（中央表为 NULL 时永远补不上的洞）；
                          (d) "已存在但无密码凭证"补发设密邀请，用 KC 侧 requiredActions
                              含 UPDATE_PASSWORD 去重，不会每轮重复发信；
                          (e) 汇总行增加"补发邀请 / 回写 kc_user_id"两个计数。
                          (f) 文件头流程说明同步更新（可选段落）。
      H17 批量静默建号   ：(a) 新增 -SkipInvite 开关（switch，计划任务 -File 可传）；
                          (b) 计数器 $skippedInvite；
                          (c) 建号分支不发 execute-actions-email，按人记一行 INFO
                              `跳过邀请(-SkipInvite): <login>`；
                          (d) 复职分支同样不发（日志带"复职"后缀以便区分）；
                          (e) -ResendInviteForPasswordless 让位：同时指定时跳过一切邮件；
                          (f) 汇总行增加"跳过邀请 N"；
                          (g) 启动日志明确提示开关生效及冲突取舍。
      H18 单人容错       ：(a) 新增 -StopOnError 严格模式开关（默认关 = 容错）；
                          (b) 新增 Get-KcFailureInfo（从异常消息提取 HTTP 码与 Keycloak
                              errorMessage 原文）；
                          (c) 整个"每用户处理体"包一层 try/catch：单个用户失败只记 WARN
                              （工号+login+状态码+errorMessage）并继续，不再让整批归零；
                          (d) catch 里的致命判定：令牌/权限（401/403）、网络（HTTP 0）、
                              非 KC 异常（SQL/凭据）仍立即中止；
                          (e) 计数器 $failed / $failedList；
                          (f) 汇总行增加"失败 N"并列出前 20 条；
                          (g) 全员失败（0 成功）按致命错误处理，避免 exit 0 掩盖系统性配置问题；
                          (h) 文件头流程说明增加单人容错一段。
      H19 姓名清洗       ：(a) 新增 ConvertTo-KcPersonName（按 Keycloak 25.0.6
                              person-name-prohibited-characters 源码规则剔除禁止字符：
                              < > & " $ % ! # ? § ; * ~ / \ | ^ = [ ] { } ( ) 与控制字符；
                              单引号、逗号、冒号、空格保留，O'Brien 不受影响）；
                          (b) Split-DisplayName 第 3 条回退分支（login_name 兜底）出口清洗，
                              连续空白压缩、首尾 trim，清洗后为空则不写 firstName；
                              中文优先的两条分支保持原样，不经过清洗；
                          (c) 文件头"姓名口径"补充清洗说明。
      H20 排除名单定稿   ：(a) -ExcludeEmployeeNos 默认值由 'admin' 改为 15 个服务/机器账号
                              （用户 2026-11-11 定稿：admin 移出名单，要给它建 Keycloak 账号）；
                          (b) "排除名单生效"段前注释同步改写（可选段落）。
                          名单只在本文件维护；sync_ad_to_sso.ps1 默认不传该参数，
                          夜间 06:00 任务因此与手动批量口径一致，不需两处改默认值。

    幂等：每个段落先查"新版标记"，已存在则跳过；重复执行不会二次修改。
    安全：先写临时文件 -> Parser::ParseFile 语法校验 -> 通过后才备份并覆盖目标。
          任一必需段落（H1/H2）既找不到旧版也找不到新版时，整体放弃，目标文件一字不动。
    备份：<BackupDirectory>\sync_sso_to_keycloak.ps1.<时间戳>.bak

.PARAMETER TargetPath
    要修补的脚本，默认 C:\sso\scripts\sync_sso_to_keycloak.ps1
.PARAMETER BackupDirectory
    备份目录，默认 C:\sso\scripts\backup
.PARAMETER DryRun
    只计算与校验，不覆盖目标文件
.PARAMETER Rollback
    用最近一次备份还原目标文件（还原前会先把当前文件另存一份，避免回滚不可逆）

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_sync_sso_to_keycloak.ps1 -DryRun

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_sync_sso_to_keycloak.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_sync_sso_to_keycloak.ps1 -Rollback
#>
[CmdletBinding()]
param(
    [string]$TargetPath = 'C:\sso\scripts\sync_sso_to_keycloak.ps1',
    [string]$BackupDirectory = 'C:\sso\scripts\backup',
    [switch]$DryRun,
    [switch]$Rollback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Applied = 0
$script:Skipped = 0
$script:Failed = New-Object System.Collections.Generic.List[string]
$script:Norm = ''

function Write-Step {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '{0} [{1,-4}] {2}' -f (Get-Date).ToString('HH:mm:ss'), $Level, $Message
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        'SKIP'  { Write-Host $line -ForegroundColor DarkGray }
        default { Write-Host $line }
    }
}

function Test-PsSyntax {
    <# 返回 @{ Ok=布尔; Errors=错误数组 }；空数组直接 return 会被展开成 $null，故用对象包一层。 #>
    param([Parameter(Mandatory)][string]$Path)
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    $list = @($errors)
    return [pscustomobject]@{ Ok = ($list.Count -eq 0); Errors = $list }
}

# ============================ -Rollback ============================
if ($Rollback) {
    if (-not (Test-Path -LiteralPath $BackupDirectory)) {
        Write-Step ("备份目录不存在: {0}" -f $BackupDirectory) 'ERROR'
        exit 2
    }
    $bak = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'sync_sso_to_keycloak.ps1.*.bak' -File |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($bak.Count -eq 0) {
        Write-Step '没有可用备份，无法回滚。' 'ERROR'
        exit 2
    }
    if (Test-Path -LiteralPath $TargetPath) {
        $safety = Join-Path $BackupDirectory ('sync_sso_to_keycloak.ps1.before-rollback.' +
            (Get-Date).ToString('yyyyMMdd-HHmmss') + '.bak')
        Copy-Item -LiteralPath $TargetPath -Destination $safety -Force
        Write-Step ("当前文件已另存: {0}" -f $safety)
    }
    Copy-Item -LiteralPath $bak[0].FullName -Destination $TargetPath -Force
    $chk = Test-PsSyntax -Path $TargetPath
    if (-not $chk.Ok) {
        Write-Step ("回滚后语法校验失败: {0}" -f $chk.Errors[0].Message) 'ERROR'
        exit 3
    }
    Write-Step ("已回滚到: {0}" -f $bak[0].FullName)
    Write-Step '回滚后语法校验: PARSE OK'
    exit 0
}

# ============================ 读取与编码自检 ============================
if (-not (Test-Path -LiteralPath $TargetPath)) {
    Write-Step ("目标脚本不存在: {0}" -f $TargetPath) 'ERROR'
    exit 2
}
$bytes = [System.IO.File]::ReadAllBytes($TargetPath)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }

# PS 5.1 按 ANSI 读无 BOM 的中文脚本会乱码；先确认文件里能读到已知中文，读不到就不动它。
$zhMarker = [string]::new([char[]]@(0x4E2D, 0x592E, 0x4EBA, 0x5458, 0x8868))
if (-not $text.Contains($zhMarker)) {
    Write-Step '编码自检失败: 读不到预期中文内容，文件可能不是 UTF-8（或被改过）。' 'ERROR'
    Write-Step '请先用记事本"另存为 UTF-8"后重试；本脚本不会修改未通过自检的文件。' 'ERROR'
    exit 2
}
if ($text.Contains([string][char]0xFFFD)) {
    Write-Step '编码自检失败: 文件里含 U+FFFD 替换字符，说明已出现乱码。' 'ERROR'
    exit 2
}

$nl = "`n"
if ($text.Contains("`r`n")) { $nl = "`r`n" }
$script:Norm = $text.Replace("`r`n", "`n")

Write-Step ("目标: {0}" -f $TargetPath)
Write-Step ("大小: {0} 字节，换行: {1}，BOM: {2}" -f $bytes.Length,
    $(if ($nl -eq "`r`n") { 'CRLF' } else { 'LF' }), $(if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF) { '有' } else { '无' }))

# ============================ 替换实现 ============================
function Set-FunctionBlock {
    <# 用新版整函数替换旧函数（按 ^function Name { ... ^} 定位）。 #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$NewCode,
        [Parameter(Mandatory)][string]$SkipIfContains,
        [Parameter(Mandatory)][string]$Title
    )
    $pattern = '(?ms)^function\s+' + [regex]::Escape($Name) + '\s*\{.*?^\}'
    $m = [regex]::Match($script:Norm, $pattern)
    if (-not $m.Success) {
        $script:Failed.Add(("{0}: 找不到 function {1}，目标文件结构不符" -f $Title, $Name))
        return
    }
    if ($m.Value.Contains($SkipIfContains)) {
        Write-Step ("{0}: 已是新版，跳过" -f $Title) 'SKIP'
        $script:Skipped++
        return
    }
    $new = ($NewCode -replace "`r`n", "`n").TrimEnd([char]10)
    $before = ($m.Value -split "`n").Count
    $script:Norm = $script:Norm.Substring(0, $m.Index) + $new + $script:Norm.Substring($m.Index + $m.Length)
    $script:Applied++
    Write-Step ("{0}: 已替换（{1} 行 -> {2} 行）" -f $Title, $before, ($new -split "`n").Count)
}

function Set-TextHunk {
    <# 精确文本替换；旧文不存在且新版标记也不存在时按 Optional 决定告警或中止。 #>
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$SkipIfContains,
        [string]$SkipIfContains2 = '',
        [switch]$Optional
    )
    $OldText = $OldText -replace "`r`n", "`n"
    $NewText = $NewText -replace "`r`n", "`n"
    if ($script:Norm.Contains($SkipIfContains) -or
        ($SkipIfContains2 -ne '' -and $script:Norm.Contains($SkipIfContains2))) {
        Write-Step ("{0}: 已是新版，跳过" -f $Title) 'SKIP'
        $script:Skipped++
        return
    }
    if (-not $script:Norm.Contains($OldText)) {
        if ($Optional) {
            Write-Step ("{0}: 未找到待改文本，跳过（可选段落）" -f $Title) 'WARN'
            $script:Skipped++
        }
        else {
            $script:Failed.Add(("{0}: 未找到待改文本" -f $Title))
        }
        return
    }
    $script:Norm = $script:Norm.Replace($OldText, $NewText)
    $script:Applied++
    Write-Step ("{0}: 已替换" -f $Title)
}

# ============================ 新版代码（H1 / H2） ============================
$newSsoSql = @'
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
'@

$newKcApi = @'
function Invoke-KcApi {
    <# Keycloak Admin REST 调用，带退避重试。
       可重试: 网络错误(0)/5xx/429；其余 4xx 快速失败。
       -IsTokenRequest: 令牌端点不附带 Bearer 头，且请求体按表单编码。 #>
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
                # (1) HttpWebResponse（PS 5.1 的 Invoke-RestMethod 走 HttpWebRequest）
                try {
                    $stream = $resp.GetResponseStream()
                    if ($null -ne $stream) {
                        $reader = New-Object System.IO.StreamReader($stream)
                        $errBody = $reader.ReadToEnd()
                        $reader.Close()
                    }
                } catch { }
                # (2) HttpResponseMessage（走 HttpClient 时才有 Content）
                if ([string]::IsNullOrWhiteSpace($errBody)) {
                    try { $errBody = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult() } catch { }
                }
            }
            # (3) 兜底: PowerShell 已把响应正文放进 ErrorDetails
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
'@

# ============================ 应用补丁 ============================
Set-FunctionBlock -Name 'Invoke-SsoSql' -NewCode $newSsoSql `
    -SkipIfContains "`$lit = 'NULL'" -Title 'H1 Invoke-SsoSql(去 -Variable)'

Set-FunctionBlock -Name 'Invoke-KcApi' -NewCode $newKcApi `
    -SkipIfContains 'application/x-www-form-urlencoded' -Title 'H2 Invoke-KcApi(表单编码+错误体)'

Set-TextHunk -Title 'H3 Write-SyncLog(去双重转义)' `
    -OldText 'message = ($Message -replace "''", "''''")' `
    -NewText 'message = $Message' `
    -SkipIfContains 'message = $Message' -Optional

# H4: TLS 无条件启用（插在 $ErrorActionPreference = 'Stop' 之后）
$tlsLine = '[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12'
if ($script:Norm.Contains($tlsLine)) {
    Write-Step 'H4 TLS: 已是新版，跳过' 'SKIP'
    $script:Skipped++
}
else {
    $anchor = "`$ErrorActionPreference = 'Stop'"
    $idx = $script:Norm.IndexOf($anchor)
    if ($idx -lt 0) {
        Write-Step 'H4 TLS: 找不到 $ErrorActionPreference = ''Stop''，跳过（可选段落）' 'WARN'
        $script:Skipped++
    }
    else {
        $eol = $script:Norm.IndexOf([char]10, $idx)
        $tlsBlock = @'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
# Windows PowerShell 5.1 默认只协商到 TLS 1.0/1.1，而 Keycloak 25 只接受 TLS 1.2+，
# 症状是 "The request was aborted: Could not create SSL/TLS secure channel."（端口通、证书也没问题）。
# 这里不依赖 -SkipCertCheck：协议协商与证书校验是两件事，必须分开处理。
# 只显式启用 Tls12：不叠加 Tls13——旧版 Windows Server 的 Schannel 不认这个标志，
# 一旦放进 SecurityProtocol 反而会让握手直接失败。Tls13 由系统在双方都支持时自动协商。
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
'@
        $script:Norm = $script:Norm.Insert($eol + 1, $tlsBlock + "`n")
        $script:Applied++
        Write-Step 'H4 TLS: 已在脚本启动处插入无条件 Tls12'
    }
}

# H5: 默认基址
$kcNew = "    [string]`$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',"
$kcOld1 = "    [string]`$KeycloakBaseUrl = 'https://sso.ap.inalfa.local',"
$kcOld2 = "    [string]`$KeycloakBaseUrl = 'https://sso.ap.inalfa.local:8443',"
if ($script:Norm.Contains("[string]`$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443'")) {
    Write-Step 'H5 默认基址: 已是新版，跳过' 'SKIP'
    $script:Skipped++
}
elseif ($script:Norm.Contains($kcOld1) -or $script:Norm.Contains($kcOld2)) {
    $script:Norm = $script:Norm.Replace($kcOld1, $kcNew).Replace($kcOld2, $kcNew)
    $script:Applied++
    Write-Step 'H5 默认基址: sso.ap.inalfa.local -> iame.ap.inalfa.local:8443'
}
else {
    Write-Step 'H5 默认基址: 未找到待改文本，跳过（可选段落）' 'WARN'
    $script:Skipped++
}

# H8: 新增计数器初始化（H6/H7 依赖）
$h8Old = '$added = 0; $updated = 0; $disabled = 0; $reactivated = 0; $invited = 0; $pwdSetBackfill = 0'
$h8New = @'
$added = 0; $updated = 0; $disabled = 0; $reactivated = 0; $invited = 0; $pwdSetBackfill = 0
$inviteFailed = 0           # 建号成功但邀请邮件没发出去的人数（需管理员手工设密）
$inviteFailedList = @()     # 上述人员的工号
'@
Set-TextHunk -Title 'H8 计数器初始化' -OldText $h8Old -NewText $h8New `
    -SkipIfContains '$inviteFailedList = @()'

# H6: 新人分支（建号后立即回写 kc_user_id；邀请邮件失败只 WARN 不中止）
$h6Old = @'
            $added++
            Write-Log ("建号: {0} ({1})" -f $uLogin, $kcUser.id) 'INFO'
            if ($uEmail -ne '') {
                Invoke-KcApi -Method Post `
                    -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
                    -Body @('UPDATE_PASSWORD')
                $invited++
                Write-Log ("已发邀请设密邮件: {0} -> {1}" -f $uLogin, $uEmail) 'INFO'
            } else {
                # 邮箱暂不用管理：无邮箱跳过邮件邀请，登记待管理员控制台代设密
                $skippedNoEmail += $uLogin
                Write-Log ("用户 {0} 无邮箱，跳过邀请邮件（需管理员控制台代设密+首登改密）" -f $uLogin) 'WARN'
            }
            # 回写 kc_user_id
            Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = @id, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ id = [string]$kcUser.id; emp = [string]$u.employee_no } -Credential $cred | Out-Null
'@
$h6New = @'
            $added++
            Write-Log ("建号: {0} ({1})" -f $uLogin, $kcUser.id) 'INFO'
            # 建号成功即回写 kc_user_id：账号已经建成，不该因为后面的邀请邮件失败而丢掉。
            Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = @id, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ id = [string]$kcUser.id; emp = [string]$u.employee_no } -Credential $cred | Out-Null
            if ($uEmail -ne '') {
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
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
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
'@
Set-TextHunk -Title 'H6 新人分支(建号+回写+邀请不致命)' -OldText $h6Old -NewText $h6New `
    -SkipIfContains '$inviteFailed++'

# H11: 复职重发设密邮件（同一 404 根因：裸数组缺 client_id）
$h11Old = @'
                if ($uEmail -ne '') {
                    Invoke-KcApi -Method Post `
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
                        -Body @('UPDATE_PASSWORD')
                    $invited++
                    Write-Log ("复职重发设密邮件: {0}" -f $uLogin) 'INFO'
'@
$h11New = @'
                if ($uEmail -ne '') {
                    # 与新人分支同一口径：裸数组缺 client_id 会让 Keycloak 解析不到 client 而回 404
                    $reactBody = @{
                        actions   = @('UPDATE_PASSWORD')
                        client_id = $InviteClientId
                        lifespan  = $InviteLifespanSeconds
                    }
                    if ($InviteRedirectUri -ne '') { $reactBody['redirect_uri'] = $InviteRedirectUri }
                    Invoke-KcApi -Method Post `
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
                        -Body $reactBody
                    $invited++
                    Write-Log ("复职重发设密邮件: {0}" -f $uLogin) 'INFO'
'@
Set-TextHunk -Title 'H11 复职重发邀请(补 client_id)' -OldText $h11Old -NewText $h11New `
    -SkipIfContains '$reactBody'

# H12: (if ...) 不是表达式 —— PS 5.1 会把括号里的 if 当命令执行，运行到"已存在"分支即崩
$h12Old = @'
            if ($uEmail -ne '' -and (if ($null -ne $kcUser.email) { [string]$kcUser.email } else { '' }) -ne $uEmail) { $needUpdate = $true }
            if ((if ($null -ne $kcUser.firstName) { [string]$kcUser.firstName } else { '' }) -ne $nameParts.First) { $needUpdate = $true }
            if ((if ($null -ne $kcUser.lastName) { [string]$kcUser.lastName } else { '' }) -ne $nameParts.Last) { $needUpdate = $true }
'@
$h12New = @'
            # PS 5.1 里 (if ...) 不是表达式：括号内的 if 会被当成命令名去执行，
            # 报 "The term 'if' is not recognized as the name of a cmdlet"（解析期不报错，
            # 只有走到这一行才炸）。故先把 KC 侧值取到变量，再比较。
            $kcEmail = if ($null -ne $kcUser.email) { [string]$kcUser.email } else { '' }
            $kcFirst = if ($null -ne $kcUser.firstName) { [string]$kcUser.firstName } else { '' }
            $kcLast = if ($null -ne $kcUser.lastName) { [string]$kcUser.lastName } else { '' }
            # 邮箱暂不用管理：中央表无邮箱时不覆盖 KC 侧已有邮箱，不做差异比对
            if ($uEmail -ne '' -and $kcEmail -ne $uEmail) { $needUpdate = $true }
            if ($kcFirst -ne $nameParts.First) { $needUpdate = $true }
            if ($kcLast -ne $nameParts.Last) { $needUpdate = $true }
'@
Set-TextHunk -Title 'H12 (if ...) 改表达式' -OldText $h12Old -NewText $h12New `
    -SkipIfContains '$kcEmail = if (' -SkipIfContains2 "Get-Prop `$kcUser 'email'"

# ============================ H13: StrictMode 下安全取/写属性 ============================
# 症状: "The property 'lastName' cannot be found on this object."
# 成因: Keycloak 的 JSON 只回非空字段；Set-StrictMode -Version Latest 下裸访问缺失属性
#       直接抛 PropertyNotFoundException（读、写都会抛）。
# 做法: 统一 Get-Prop / Set-Prop；空值一律不写（既避免崩，也避免把已有值清空）。

# H13a: 插入两个助手函数（必须在主流程之前执行，放 Get-KcToken 前面）
$h13aOld = @'
function Get-KcToken {
'@
$h13aNew = @'
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
'@
Set-TextHunk -Title 'H13a 取/写属性助手(Get-Prop/Set-Prop)' -OldText $h13aOld -NewText $h13aNew `
    -SkipIfContains 'function Get-Prop {'

# H13b: 令牌响应（access_token / expires_in）
$h13bOld = @'
    $resp = Invoke-KcApi -Method Post -Uri $uri -Body $body -IsTokenRequest
    $script:KcToken = $resp.access_token
    $script:KcTokenExpiry = (Get-Date).AddSeconds([int]$resp.expires_in - 30)
    Write-Log ('Keycloak 管理令牌获取成功（有效期 {0}s）' -f $resp.expires_in) 'INFO'
'@
$h13bNew = @'
    $tokenResp = Invoke-KcApi -Method Post -Uri $uri -Body $body -IsTokenRequest
    $script:KcToken = [string](Get-Prop $tokenResp 'access_token' '')
    if ($script:KcToken -eq '') {
        throw '令牌端点的返回里没有 access_token，检查 sync-client 的 Service Account 权限与 realm 配置。'
    }
    $expires = [int](Get-Prop $tokenResp 'expires_in' 60)
    $script:KcTokenExpiry = (Get-Date).AddSeconds($expires - 30)
    Write-Log ('Keycloak 管理令牌获取成功（有效期 {0}s）' -f $expires) 'INFO'
'@
Set-TextHunk -Title 'H13b 令牌响应安全取值' -OldText $h13bOld -NewText $h13bNew `
    -SkipIfContains "Get-Prop `$tokenResp 'access_token'"

# H13c: 建号分支（取 id -> 校验 -> 回写 kc_user_id -> 邀请邮件 URL）
$h13cOld = @'
            $added++
            Write-Log ("建号: {0} ({1})" -f $uLogin, $kcUser.id) 'INFO'
            # 建号成功即回写 kc_user_id：账号已经建成，不该因为后面的邀请邮件失败而丢掉。
            Invoke-SsoSql -Query @"
UPDATE dbo.CN_AME_SSO_User
SET kc_user_id = @id, updated_at = SYSUTCDATETIME()
WHERE employee_no = @emp
"@ -Parameters @{ id = [string]$kcUser.id; emp = [string]$u.employee_no } -Credential $cred | Out-Null
            if ($uEmail -ne '') {
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
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
                        -Body $inviteBody
'@
$h13cNew = @'
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
            if ($uEmail -ne '') {
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
'@
Set-TextHunk -Title 'H13c 建号分支安全取 id' -OldText $h13cOld -NewText $h13cNew `
    -SkipIfContains '建号后返回的用户对象缺 id'

# H13d: 已存在分支的差异比对 + 整对象 PUT（空值不比对、不写回）
$h13dOld = @'
            $needUpdate = $false
            if ([string]$kcUser.username -ne $uLogin) { $needUpdate = $true }
            # PS 5.1 里 (if ...) 不是表达式：括号内的 if 会被当成命令名去执行，
            # 报 "The term 'if' is not recognized as the name of a cmdlet"（解析期不报错，
            # 只有走到这一行才炸）。故先把 KC 侧值取到变量，再比较。
            $kcEmail = if ($null -ne $kcUser.email) { [string]$kcUser.email } else { '' }
            $kcFirst = if ($null -ne $kcUser.firstName) { [string]$kcUser.firstName } else { '' }
            $kcLast = if ($null -ne $kcUser.lastName) { [string]$kcUser.lastName } else { '' }
            # 邮箱暂不用管理：中央表无邮箱时不覆盖 KC 侧已有邮箱，不做差异比对
            if ($uEmail -ne '' -and $kcEmail -ne $uEmail) { $needUpdate = $true }
            if ($kcFirst -ne $nameParts.First) { $needUpdate = $true }
            if ($kcLast -ne $nameParts.Last) { $needUpdate = $true }
            if ([bool]$kcUser.enabled -ne ($uStatus -eq 1)) { $needUpdate = $true }
            if ($needUpdate) {
                $full = Get-KcUserById ([string]$kcUser.id)
                if ($null -eq $full) { throw ("GET 整对象失败: {0}" -f $uLogin) }
                $full.username = $uLogin
                if ($uEmail -ne '') { $full.email = $uEmail }
                $full.firstName = $nameParts.First
                $full.lastName = $nameParts.Last
                $full.enabled = ($uStatus -eq 1)
                Invoke-KcApi -Method Put `
                    -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)" `
                    -Body $full
'@
$h13dNew = @'
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
'@
Set-TextHunk -Title 'H13d 已存在分支安全取值/写值' -OldText $h13dOld -NewText $h13dNew `
    -SkipIfContains "`$kcUsername = [string](Get-Prop `$kcUser 'username'"

# H13e: 停用分支（enabled / id 快照）
$h13eOld = @'
        # 4) 离职停用: status=0 且 KC 仍启用 → 禁用 + 踢会话
        if ($uStatus -eq 0 -and [bool]$kcUser.enabled) {
            $full = Get-KcUserById ([string]$kcUser.id)
            if ($null -eq $full) { throw ("GET 整对象失败(停用): {0}" -f $uLogin) }
            $full.enabled = $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)" -Body $full
'@
$h13eNew = @'
        # 4) 离职停用: status=0 且 KC 仍启用 → 禁用 + 踢会话
        # 快照在每轮改动之后重算：上面 PUT 可能已经把 enabled 改掉，不能用旧值判断。
        $kcId = [string](Get-Prop $kcUser 'id' '')
        $kcEnabled = [bool](Get-Prop $kcUser 'enabled' $false)
        if ($uStatus -eq 0 -and $kcEnabled) {
            $full = Get-KcUserById $kcId
            if ($null -eq $full) { throw ("GET 整对象失败(停用): {0}" -f $uLogin) }
            Set-Prop $full 'enabled' $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
'@
Set-TextHunk -Title 'H13e 停用分支安全取值' -OldText $h13eOld -NewText $h13eNew `
    -SkipIfContains "`$kcEnabled = [bool](Get-Prop `$kcUser 'enabled'"

# H13f: 踢会话 URL
$h13fOld = @'
                Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/logout"
'@
$h13fNew = @'
                Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/logout"
'@
Set-TextHunk -Title 'H13f 踢会话 URL 用 $kcId' -OldText $h13fOld -NewText $h13fNew `
    -SkipIfContains 'users/$kcId/logout'

# H13g: 复职分支（含重发邀请 URL）
$h13gOld = @'
        if ($uStatus -eq 1 -and -not [bool]$kcUser.enabled) {
            $full = Get-KcUserById ([string]$kcUser.id)
            if ($null -eq $full) { throw ("GET 整对象失败(复职): {0}" -f $uLogin) }
            $full.enabled = $true
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)" -Body $full
            $reactivated++
            Write-Log ("已复职: {0}" -f $uLogin) 'INFO'
            if (-not [bool]$u.pwd_set) {
                if ($uEmail -ne '') {
                    # 与新人分支同一口径：裸数组缺 client_id 会让 Keycloak 解析不到 client 而回 404
                    $reactBody = @{
                        actions   = @('UPDATE_PASSWORD')
                        client_id = $InviteClientId
                        lifespan  = $InviteLifespanSeconds
                    }
                    if ($InviteRedirectUri -ne '') { $reactBody['redirect_uri'] = $InviteRedirectUri }
                    Invoke-KcApi -Method Post `
                        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/execute-actions-email" `
                        -Body $reactBody
'@
$h13gNew = @'
        if ($uStatus -eq 1 -and -not $kcEnabled) {
            $full = Get-KcUserById $kcId
            if ($null -eq $full) { throw ("GET 整对象失败(复职): {0}" -f $uLogin) }
            Set-Prop $full 'enabled' $true
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
            $reactivated++
            Write-Log ("已复职: {0}" -f $uLogin) 'INFO'
            if (-not [bool]$u.pwd_set) {
                if ($uEmail -ne '') {
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
'@
Set-TextHunk -Title 'H13g 复职分支安全取值' -OldText $h13gOld -NewText $h13gNew `
    -SkipIfContains 'if ($uStatus -eq 1 -and -not $kcEnabled) {'

# H13i: requiredActions（字段常整个缺失）
$h13iOld = @'
            $actions = @()
            if ($null -ne $kcUser.PSObject.Properties['requiredActions'] -and $null -ne $kcUser.requiredActions) {
                $actions = @($kcUser.requiredActions)
            }
'@
$h13iNew = @'
            # requiredActions 在 Keycloak 返回里经常整个字段缺失（没有待办动作时）
            $actions = @(Get-Prop $kcUser 'requiredActions' @())
'@
Set-TextHunk -Title 'H13i requiredActions 安全取值' -OldText $h13iOld -NewText $h13iNew `
    -SkipIfContains "`$actions = @(Get-Prop `$kcUser 'requiredActions'"

# H13j: 凭证查询用 $kcId
$h13jOld = @'
                $pwdCreds = Get-KcPasswordCredentialCount -Id ([string]$kcUser.id)
'@
$h13jNew = @'
                $pwdCreds = Get-KcPasswordCredentialCount -Id $kcId
'@
Set-TextHunk -Title 'H13j 凭证查询用 $kcId' -OldText $h13jOld -NewText $h13jNew `
    -SkipIfContains 'Get-KcPasswordCredentialCount -Id $kcId'

# H7: 汇总行（增加"建号但未发邀请"计数与名单）
$h7Old = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件 {4} / 设密回写 {5} / 设密未知 {6}" -f
        $added, $updated, $disabled, $reactivated, $invited, $pwdSetBackfill, $pwdSetUnknown)
    if ($skippedNoEmail.Count -gt 0) {
        # 无邮箱用户：跳过邮件邀请，需管理员控制台代设密（realm-setup.md 2.1）
        $msg += ("；无邮箱跳过邀请 {0} 人（待管理员代设密）: {1}" -f
            $skippedNoEmail.Count, ($skippedNoEmail -join ', '))
        Write-Log $msg 'WARN'
    } else {
        Write-Log $msg 'INFO'
    }
'@
$h7New = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 建号但未发邀请 {5}（需管理员手工设密）/ 设密回写 {6} / 设密未知 {7}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $pwdSetBackfill, $pwdSetUnknown)
    if ($inviteFailedList.Count -gt 0) {
        $msg += ("；邀请邮件未发出: {0}" -f ($inviteFailedList -join ', '))
    }
    if ($skippedNoEmail.Count -gt 0 -or $inviteFailedList.Count -gt 0) {
        # 无邮箱 / 发信失败：都是"账号已建好但缺设密链路"，需管理员控制台代设密（realm-setup.md 2.1）
        $msg += ("；无邮箱跳过邀请 {0} 人（待管理员代设密）: {1}" -f
            $skippedNoEmail.Count, ($skippedNoEmail -join ', '))
        Write-Log $msg 'WARN'
    } else {
        Write-Log $msg 'INFO'
    }
'@
Set-TextHunk -Title 'H7 汇总(未发邀请计数+名单)' -OldText $h7Old -NewText $h7New `
    -SkipIfContains '邀请邮件成功'

# H9: 邀请邮件参数（client_id / redirect_uri 可配，不再写死）
$h9Old = @'
    [string]$KcClientCredentialName = 'keycloak_sync_client',
'@
$h9New = @'
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
'@
Set-TextHunk -Title 'H9 邀请邮件参数' -OldText $h9Old -NewText $h9New `
    -SkipIfContains "`$InviteRedirectUri = ''"

# H10: 启动时打印实际使用的邀请参数
$h10Old = @'
    Write-Log ("待同步用户 {0} 人" -f @($users).Count) 'INFO'
'@
$h10New = @'
    # 把实际会用的邀请邮件参数打出来，避免下次靠猜（client 不存在 → 404；redirect_uri 不匹配 → 400）
    $shownRedirect = $InviteRedirectUri
    if ($shownRedirect -eq '') { $shownRedirect = '(未传，由 Keycloak 按 client 配置决定)' }
    Write-Log ("邀请邮件参数: client_id={0}; redirect_uri={1}; lifespan={2}s" -f
        $InviteClientId, $shownRedirect, $InviteLifespanSeconds) 'INFO'
    Write-Log ("待同步用户 {0} 人" -f @($users).Count) 'INFO'
'@
Set-TextHunk -Title 'H10 邀请参数日志' -OldText $h10Old -NewText $h10New `
    -SkipIfContains '邀请邮件参数: client_id='

# ============================ H14: 已存在分支补洞 ============================
# 现场症状（2026-11-11）: 13 人 kc_user_id 全 NULL、pwd_set 全 0。abelmi2 账号早在
# Keycloak 里（上一轮建号成功、随后在发邀请 404 处中止），但中央表没写上 id；
# 这一轮走"已存在"分支，旧版该分支只比对资料 —— id 补不上、邀请也不会再发。

# H14a: 新增 -ResendInviteForPasswordless 开关（默认关闭，运维显式开启跑一次）
$h14aOld = @'
    # 引导期 Keycloak 8443 为自签证书时可开；生产走企业证书应保持 $false
    [switch]$SkipCertCheck
)
'@
$h14aNew = @'
    # 引导期 Keycloak 8443 为自签证书时可开；生产走企业证书应保持 $false
    [switch]$SkipCertCheck,

    # 补发邀请（2026-11-11 H14 新增）: 对"账号已在 Keycloak、但一条 password 凭证都没有"
    # 的用户补发一次设密邀请（复用 -InviteClientId / -InviteRedirectUri / -InviteLifespanSeconds）。
    # 默认关闭：正常每轮同步不该给同一批无密码用户重复发信。
    # 去重：KC 侧 requiredActions 已含 UPDATE_PASSWORD = 上一封邀请仍未完成 → 本轮跳过，
    #       所以即使开关一直开着也不会重复轰炸；邀请过期后要重发，先在控制台清掉该 required
    #       action 再跑，或让用户走"忘记密码"。
    # 运维用法：需要补发时显式加 -ResendInviteForPasswordless 跑一次（可与 -EmployeeNos 叠加）。
    [switch]$ResendInviteForPasswordless
)
'@
Set-TextHunk -Title 'H14a 补发邀请开关' -OldText $h14aOld -NewText $h14aNew `
    -SkipIfContains 'ResendInviteForPasswordless'

# H14b: 计数器初始化
# 现场文件与仓库源的注释可能有细微差异，这里只以 "$skippedNoEmail = @()" 这一行的行首为准，
# 整行（含原有尾注释）保留，在其后插入两行——避免因为注释措辞不同就整体放弃。
if ($script:Norm.Contains('$kcIdBackfill = 0')) {
    Write-Step 'H14b 计数器初始化: 已是新版，跳过' 'SKIP'
    $script:Skipped++
}
else {
    $mInit = [regex]::Match($script:Norm, '(?m)^\$skippedNoEmail = @\(\).*$')
    if (-not $mInit.Success) {
        $script:Failed.Add('H14b 计数器初始化: 找不到 $skippedNoEmail = @() 行')
    }
    else {
        $addInit = "`n" +
            '$kcIdBackfill = 0   # "已存在"分支补写 kc_user_id 的人数（H14）' + "`n" +
            '$inviteResent = 0   # 已存在但无密码、本轮补发设密邀请的人数（H14，需 -ResendInviteForPasswordless）'
        $script:Norm = $script:Norm.Insert($mInit.Index + $mInit.Length, $addInit)
        $script:Applied++
        Write-Step 'H14b 计数器初始化: 已替换'
    }
}

# H14c: "已存在"分支末尾 —— 补写 kc_user_id + 无密码补发邀请
$h14cOld = @'
                $updated++
                Write-Log ("更新用户资料(整对象PUT): {0}" -f $uLogin) 'INFO'
                $kcUser = $full
            }
        }
'@
$h14cNew = @'
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
            if ($ResendInviteForPasswordless -and $uStatus -eq 1) {
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
'@
Set-TextHunk -Title 'H14c 已存在分支补写 id + 补发邀请' -OldText $h14cOld -NewText $h14cNew `
    -SkipIfContains '# 3.1) 回写 kc_user_id'

# H14d: 汇总行增加补发邀请 / 回写 kc_user_id 两个计数
$h14dOld = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 建号但未发邀请 {5}（需管理员手工设密）/ 设密回写 {6} / 设密未知 {7}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $pwdSetBackfill, $pwdSetUnknown)
'@
$h14dNew = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown)
'@
Set-TextHunk -Title 'H14d 汇总行' -OldText $h14dOld -NewText $h14dNew `
    -SkipIfContains '补发邀请 {6}'

# H14e: 文件头流程说明（可选，纯注释，找不到也不影响功能）
$h14eOld = @'
          → 已存在走 GET→改→PUT 整对象（硬规则：禁止部分 PUT）
          → status=0 且 enabled → 禁用 + POST logout 踢会话
'@
$h14eNew = @'
          → 已存在走 GET→改→PUT 整对象（硬规则：禁止部分 PUT）
          → 已存在但中央表 kc_user_id 为空/与 KC 不一致 → 补写一次（2026-11-11 H14）
          → 已存在且 KC 侧无密码凭证 → 可选补发设密邀请
            （-ResendInviteForPasswordless，默认关闭；H14）
          → status=0 且 enabled → 禁用 + POST logout 踢会话
'@
Set-TextHunk -Title 'H14e 文件头流程说明' -OldText $h14eOld -NewText $h14eNew `
    -SkipIfContains '（-ResendInviteForPasswordless，默认关闭；H14）' -Optional

# ============================ H17: -SkipInvite 批量静默建号 ============================
# 背景：2800+ 人批量建号，实际使用者没这么多，不能同时发几千封邀请信。
# 要求：只建号 + 回写 kc_user_id，绝不触发 execute-actions-email；用户想登录时再按需设密。

$h17aOld = @'
    [switch]$ResendInviteForPasswordless
)
'@
$h17aNew = @'
    [switch]$ResendInviteForPasswordless,

    # 批量建号静默模式（2026-11-11 H17）: 本轮不发任何邀请邮件。
    # 建号/复职/无密码补发三条链路的 execute-actions-email 全部跳过，只建号 + 回写 kc_user_id；
    # 用户想登录时再由管理员按需设临时密码（或在 SMTP 就绪后走"忘记密码"）。
    # 与 -ResendInviteForPasswordless 同时指定时，以本开关为准（跳过一切邮件），启动日志会提示。
    # 计划任务/批处理可用：switch 参数，-File 方式直接传 -SkipInvite。
    [switch]$SkipInvite
)
'@
Set-TextHunk -Title 'H17a -SkipInvite 参数' -OldText $h17aOld -NewText $h17aNew `
    -SkipIfContains '[switch]$SkipInvite'

# H17b: 计数器。现场文件的注释可能与仓库有字节差，按行首正则插入，整行保留原样。
if ($script:Norm.Contains('$skippedInvite = 0')) {
    Write-Step 'H17b 计数初始化: 已是新版，跳过' 'SKIP'
    $script:Skipped++
}
else {
    $m17b = [regex]::Match($script:Norm, '(?m)^\$inviteResent = 0.*$')
    if (-not $m17b.Success) {
        $script:Failed.Add('H17b 计数初始化: 未找到 $inviteResent = 0 行')
    }
    else {
        $add17b = "`n" + '$skippedInvite = 0  # 因 -SkipInvite 主动跳过邀请邮件的人数（H17；建号/复职两条链路）'
        $script:Norm = $script:Norm.Insert($m17b.Index + $m17b.Length, $add17b)
        $script:Applied++
        Write-Step 'H17b 计数初始化: 已插入 $skippedInvite'
    }
}

# H17c: 建号分支。把 if/else 改成 if/elseif/else 链，SkipInvite 优先级最高。
$h17cOld = @'
            if ($uEmail -ne '') {
                # 邀请设密邮件只是"顺带"，失败只记 WARN 并继续下一个人（2026-11-11 修正：
'@
$h17cNew = @'
            if ($SkipInvite) {
                # H17 批量建号静默模式：不发邀请，用户首次登录前由管理员按需设密。
                $skippedInvite++
                Write-Log ("跳过邀请(-SkipInvite): {0}" -f $uLogin) 'INFO'
            }
            elseif ($uEmail -ne '') {
                # 邀请设密邮件只是"顺带"，失败只记 WARN 并继续下一个人（2026-11-11 修正：
'@
Set-TextHunk -Title 'H17c 建号分支跳过邀请' -OldText $h17cOld -NewText $h17cNew `
    -SkipIfContains '跳过邀请(-SkipInvite):'

# H17d: 复职分支。日志后缀不同，便于和建号分支区分。
$h17dOld = @'
                if ($uEmail -ne '') {
                    # 与新人分支同一口径：裸数组缺 client_id 会让 Keycloak 解析不到 client 而回 404
'@
$h17dNew = @'
                if ($SkipInvite) {
                    $skippedInvite++
                    Write-Log ("跳过邀请(-SkipInvite,复职): {0}" -f $uLogin) 'INFO'
                }
                elseif ($uEmail -ne '') {
                    # 与新人分支同一口径：裸数组缺 client_id 会让 Keycloak 解析不到 client 而回 404
'@
Set-TextHunk -Title 'H17d 复职分支跳过邀请' -OldText $h17dOld -NewText $h17dNew `
    -SkipIfContains '跳过邀请(-SkipInvite,复职):'

# H17e: 补发让位。-SkipInvite 优先于 -ResendInviteForPasswordless。
$h17eOld = '            if ($ResendInviteForPasswordless -and $uStatus -eq 1) {'
$h17eNew = '            if ($ResendInviteForPasswordless -and -not $SkipInvite -and $uStatus -eq 1) {'
Set-TextHunk -Title 'H17e 补发邀请让位' -OldText $h17eOld -NewText $h17eNew `
    -SkipIfContains '-not $SkipInvite'

# H17f: 汇总行增加"跳过邀请 N"。
$h17fOld = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown)
'@
$h17fNew = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9} / 跳过邀请 {10}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown, $skippedInvite)
'@
Set-TextHunk -Title 'H17f 汇总行增加跳过邀请' -OldText $h17fOld -NewText $h17fNew `
    -SkipIfContains '跳过邀请 {10}'

# H17g: 启动日志。放在"待同步用户"之前，批量跑一眼就能在日志头部看到本轮不会发信。
$h17gOld = @'
    Write-Log ("待同步用户 {0} 人" -f @($users).Count) 'INFO'
'@
$h17gNew = @'
    if ($SkipInvite) {
        Write-Log '-SkipInvite 已启用：本轮不发送任何邀请邮件（建号/复职/补发全部跳过），只建号并回写 kc_user_id。' 'WARN'
        if ($ResendInviteForPasswordless) {
            Write-Log '-SkipInvite 与 -ResendInviteForPasswordless 同时指定：以 -SkipInvite 为准，补发邀请不会执行。' 'WARN'
        }
    }
    Write-Log ("待同步用户 {0} 人" -f @($users).Count) 'INFO'
'@
Set-TextHunk -Title 'H17g 启动日志提示' -OldText $h17gOld -NewText $h17gNew `
    -SkipIfContains '-SkipInvite 已启用'

# ============================ H18: 单人容错 ============================
# 现场症状（2026-11-11）: 全量 2851 人，第 1 个人建号就 400
#   error-username-invalid-character / error-person-name-invalid-character，
#   Invoke-KcApi 抛异常 -> 顶层 catch -> 整批终止，其余 2850 人零进展。
# 期望: 落在一个坏数据上的只是这一个人，不是整批。

# H18a: 严格模式开关（默认容错）
$h18aOld = @'
    [switch]$SkipInvite
)
'@
$h18aNew = @'
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
'@
Set-TextHunk -Title 'H18a -StopOnError 严格模式开关' -OldText $h18aOld -NewText $h18aNew `
    -SkipIfContains '[switch]$StopOnError'

# H18b: 失败信息提取助手（HTTP 码 + Keycloak errorMessage 原文）
$h18bOld = @'
# ---------------- 主流程 ----------------
$exitCode = 0
'@
$h18bNew = @'
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

# ---------------- 主流程 ----------------
$exitCode = 0
'@
Set-TextHunk -Title 'H18b 失败信息提取助手 Get-KcFailureInfo' -OldText $h18bOld -NewText $h18bNew `
    -SkipIfContains 'function Get-KcFailureInfo {'

# H18c: 每用户处理体开头 —— 开 try，并先落工号/login 供 catch 使用
$h18cOld = @'
    foreach ($u in $users) {
        $uLogin = [string]$u.login_name
'@
$h18cNew = @'
    foreach ($u in $users) {
        # ================= H18 单人容错 =================
        # 整个用户处理体包在 try/catch 里：单个用户的失败不再让整批归零。
        # 注意: 下面这段 body 保持原缩进（PowerShell 不要求缩进对齐），
        #       避免为加一层 try 而整体重排 250 行、把补丁变成不可核对的大 diff。
        $uLogin = [string]$u.login_name
        $uEmpNo = [string]$u.employee_no
        try {
'@
Set-TextHunk -Title 'H18c 每用户 try 起点' -OldText $h18cOld -NewText $h18cNew `
    -SkipIfContains '# ================= H18 单人容错 ================='

# H18d: 每用户处理体结尾 —— catch + 失败计数
$h18dOld = @'
                # $pwdCreds = 0: 确实没有密码（批量导入用户的正常状态），保持 0，不打日志
            }
        }
    }
'@
$h18dNew = @'
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
'@
Set-TextHunk -Title 'H18d 每用户 catch + 失败计数' -OldText $h18dOld -NewText $h18dNew `
    -SkipIfContains '同步失败(已跳过，继续下一个)'

# H18e: 计数器。按行首正则插在 $skippedInvite 之后，整行保留原样。
if ($script:Norm.Contains('$failedList = @()')) {
    Write-Step 'H18e 计数初始化: 已是新版，跳过' 'SKIP'
    $script:Skipped++
}
else {
    $m18e = [regex]::Match($script:Norm, '(?m)^\$skippedInvite = 0.*$')
    if (-not $m18e.Success) {
        $script:Failed.Add('H18e 计数初始化: 未找到 $skippedInvite = 0 行')
    }
    else {
        $add18e = "`n" +
            '$failed = 0        # 单人失败（HTTP 4xx/5xx，已跳过继续）的人数（H18）' + "`n" +
            '$failedList = @()  # 上述人员的 "工号/login [HTTP 码] errorMessage" 明细（H18）'
        $script:Norm = $script:Norm.Insert($m18e.Index + $m18e.Length, $add18e)
        $script:Applied++
        Write-Step 'H18e 计数初始化: 已插入 $failed / $failedList'
    }
}

# H18f: 汇总行增加"失败 N"
$h18fOld = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9} / 跳过邀请 {10}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown, $skippedInvite)
'@
$h18fNew = @'
    $msg = ("KC 同步完成: 建号 {0} / 更新 {1} / 停用 {2} / 复职 {3} / 邀请邮件成功 {4} / 邀请未发出 {5}（需管理员手工设密）/ 补发邀请 {6} / 回写 kc_user_id {7} / 设密回写 {8} / 设密未知 {9} / 跳过邀请 {10} / 失败 {11}" -f
        $added, $updated, $disabled, $reactivated, $invited, $inviteFailed, $inviteResent, $kcIdBackfill, $pwdSetBackfill, $pwdSetUnknown, $skippedInvite, $failed)
'@
Set-TextHunk -Title 'H18f 汇总行增加失败计数' -OldText $h18fOld -NewText $h18fNew `
    -SkipIfContains '失败 {11}'

# H18g: 失败名单（前 20 条）+ 全员失败兜底（不能 exit 0）
$h18gOld = @'
    if ($skippedNoEmail.Count -gt 0 -or $inviteFailedList.Count -gt 0) {
        # 无邮箱 / 发信失败：都是"账号已建好但缺设密链路"，需管理员控制台代设密（realm-setup.md 2.1）
        $msg += ("；无邮箱跳过邀请 {0} 人（待管理员代设密）: {1}" -f
            $skippedNoEmail.Count, ($skippedNoEmail -join ', '))
        Write-Log $msg 'WARN'
    } else {
        Write-Log $msg 'INFO'
    }
    Write-SyncLog -Status 'OK' -Added $added -Updated $updated -Disabled $disabled `
        -Reactivated $reactivated -Message $msg -Credential $cred
'@
$h18gNew = @'
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
'@
Set-TextHunk -Title 'H18g 失败名单 + 全员失败兜底' -OldText $h18gOld -NewText $h18gNew `
    -SkipIfContains '失败 {0} 人（最多列 20 条）'

# H18h: 文件头流程说明（可选，纯注释）
$h18hOld = @'
          → 写 CN_AME_SSO_SyncLog(phase='KC')。
'@
$h18hNew = @'
          → 写 CN_AME_SSO_SyncLog(phase='KC')。
    单人容错（2026-11-11 H18）:
          默认开启：单个用户在建号/更新/停用/复职时收到 Keycloak 的 4xx/5xx，只记
          WARN（工号 + login + 状态码 + errorMessage 原文）并继续下一个人；令牌/权限
          （401/403）、网络（HTTP 0）、SQL/凭据类错误仍立即中止并告警。
          需要"一出错就停"时加 -StopOnError（建议与 -EmployeeNos 叠加只跑 1 人）。
'@
Set-TextHunk -Title 'H18h 文件头单人容错说明' -OldText $h18hOld -NewText $h18hNew `
    -SkipIfContains '时加 -StopOnError' -Optional

# ============================ H19: 姓名清洗 ============================
# 现场（2026-11-11）: display_name 含 <>\"&' 的 2 条，其中 t&e 已用 -ExcludeEmployeeNos 排除，
# kiron.obrien@inalfa.com / "Kiron O'Brien" 是真人不能排除。
# 澄清: Keycloak 25.0.6 的 person-name 正则允许单引号，O'Brien 本身能过校验；
#       真正会 400 的是 & 括号斜杠这类字符（回退到 login_name 时才会带到 firstName）。

# H19a: 姓名清洗助手
$h19aOld = @'
function Split-DisplayName {
'@
$h19aNew = @'
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
'@
Set-TextHunk -Title 'H19a 姓名清洗助手 ConvertTo-KcPersonName' -OldText $h19aOld -NewText $h19aNew `
    -SkipIfContains 'function ConvertTo-KcPersonName {'

# H19b: 回退分支出口清洗（中文优先的两条分支保持原样）
$h19bOld = @'
    # 3) 回退: login_name（Fallback 为空时退回原文，仍不抛异常）
    $fb = if ([string]::IsNullOrWhiteSpace($Fallback)) { $text } else { $Fallback.Trim() }
    return @{ First = $fb; Last = '' }
'@
$h19bNew = @'
    # 3) 回退: login_name（Fallback 为空时退回原文，仍不抛异常）
    $fb = if ([string]::IsNullOrWhiteSpace($Fallback)) { $text } else { $Fallback.Trim() }
    # H19: 回退值往往是 login_name 原文，可能含 person-name 校验禁止的字符（如 "T&E" 的 &、
    #      括号、斜杠）。不清洗会让一个人 400 卡住整批，清洗后为空则不写 firstName。
    $clean = ConvertTo-KcPersonName -Name $fb
    if ($clean -cne $fb) {
        Write-Log ("姓名清洗: {0} → {1}" -f $fb, $clean) 'INFO'
    }
    return @{ First = $clean; Last = '' }
'@
Set-TextHunk -Title 'H19b 回退分支出口清洗' -OldText $h19bOld -NewText $h19bNew `
    -SkipIfContains '姓名清洗: {0} → {1}'

# H19c: 文件头姓名口径说明（可选，纯注释）
$h19cOld = @'
          lastName 一律留空。畸形数据只走回退，不抛异常。
'@
$h19cNew = @'
          lastName 一律留空。畸形数据只走回退，不抛异常。
          回退值再经 ConvertTo-KcPersonName 清洗（H19）: 剔除 <>&"$%!#?§;*~/\|^=[]{}()
          与控制字符、压缩连续空白；单引号保留（Keycloak 允许）。清洗后为空则不写 firstName。
'@
Set-TextHunk -Title 'H19c 文件头姓名口径说明' -OldText $h19cOld -NewText $h19cNew `
    -SkipIfContains '回退值再经 ConvertTo-KcPersonName 清洗' -Optional

# ============================ H20: 排除名单默认值定稿 ============================
# 现场（2026-11-11）用户定稿: admin 不再排除（要给它建 Keycloak 账号），
# 其余 15 个服务/机器账号照旧排除。
# 名单只在 sync_sso_to_keycloak.ps1 维护；sync_ad_to_sso.ps1 默认不传本参数，
# 夜间 06:00 的任务因此自动与手动批量口径一致。

# H20a: 参数默认值（连同 3 行注释一起换，避免注释还写着 "默认 'admin'"）
$h20aOld = @'
    # 排除名单（2026-11-11 新增）: 逗号/分号分隔的 employee_no，永不推送到 Keycloak。
    # 用字符串而非数组: -File 方式调用时数组参数绑定会失效（"a,b" 会被当成单个字符串）。
    # 默认 'admin' = 共享系统账号，只在各业务系统本地使用。
    [string]$ExcludeEmployeeNos = 'admin',
'@
$h20aNew = @'
    # 排除名单（2026-11-11 新增；H20 定稿）: 逗号/分号分隔的 employee_no，永不推送到 Keycloak。
    # 用字符串而非数组: -File 方式调用时数组参数绑定会失效（"a,b" 会被当成单个字符串）。
    # 默认 15 项 = 服务/机器账号；admin 已移出（用户 2026-11-11 定稿: 要给它建 Keycloak 账号）。
    # 兼作 username 脏数据闸门: t&e 的 &、$duplicate-4f3a 的 $ 都会撞 Keycloak 的 username 校验
    #   （400 error-username-invalid-character），而中央表每天由 MERGE 从 StgAdUser 重灌，
    #   逐条修数据没有意义，只能在同步层拦住。
    # 本文件是唯一权威副本: sync_ad_to_sso.ps1 默认不传本参数，夜间任务沿用这里的默认值。
    [string]$ExcludeEmployeeNos = '$duplicate-4f3a, e-workflow.system, heqi-old, lush-ex, mccaffbr-cn, sccm-admins, sccm-clientpush, sccm-domainjoin, sccm-naa, sccm-siteservers, sccm-sqlreporting, sccm-sqlservice, svc-cohesity-vmware, t&e, zontsso-cn',
'@
Set-TextHunk -Title 'H20a 排除名单默认值改为 15 项' -OldText $h20aOld -NewText $h20aNew `
    -SkipIfContains '$duplicate-4f3a'

# H20b: "排除名单生效" 段前注释（纯注释，可选段落）
$h20bOld = @'
    # ---- 排除名单（2026-11-11 新增）----
    # 共享系统账号（如 admin）只在各业务系统本地使用，不进 Keycloak。
    # 不传 -ExcludeEmployeeNos 等价于排除默认值 admin；传空字符串 '' 可关闭本段。
'@
$h20bNew = @'
    # ---- 排除名单（2026-11-11 新增；H20 定稿 15 项）----
    # 默认排除 15 个服务/机器账号（admin 已移出，需要建号），脏字符不再触发 400。
    # 不传 -ExcludeEmployeeNos = 用参数默认的 15 项；传空字符串 '' 可关闭本段（全员同步）。
'@
Set-TextHunk -Title 'H20b 排除名单段前注释' -OldText $h20bOld -NewText $h20bNew `
    -SkipIfContains '默认排除 15 个服务/机器账号' -Optional

# ============================ 结果与落盘 ============================
Write-Step ('-' * 60)
Write-Step ("替换 {0} 处，跳过 {1} 处" -f $script:Applied, $script:Skipped)

if ($script:Failed.Count -gt 0) {
    foreach ($f in $script:Failed) { Write-Step ("中止: " + $f) 'ERROR' }
    Write-Step '目标文件未做任何修改（全部改动仅在内存中）。' 'ERROR'
    exit 2
}
if ($script:Applied -eq 0) {
    Write-Step '目标已是新版，无需改动。'
    exit 0
}

$out = $script:Norm.Replace("`n", $nl)
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('sync_sso_to_keycloak.patch_' + [guid]::NewGuid().ToString('N') + '.ps1')
[System.IO.File]::WriteAllText($tmp, $out, (New-Object System.Text.UTF8Encoding($true)))

$tmpChk = Test-PsSyntax -Path $tmp
if (-not $tmpChk.Ok) {
    Write-Step ("补丁结果语法校验失败，已放弃（目标未改）: {0}" -f $tmpChk.Errors[0].Message) 'ERROR'
    Write-Step ("临时文件保留供排查: {0}" -f $tmp) 'ERROR'
    exit 3
}
Write-Step '补丁结果语法校验: PARSE OK'

if ($DryRun) {
    Write-Step ('-DryRun 模式：未覆盖目标文件。临时文件: {0}' -f $tmp)
    exit 0
}

if (-not (Test-Path -LiteralPath $BackupDirectory)) {
    New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
}
$bakPath = Join-Path $BackupDirectory ('sync_sso_to_keycloak.ps1.' + (Get-Date).ToString('yyyyMMdd-HHmmss') + '.bak')
Copy-Item -LiteralPath $TargetPath -Destination $bakPath -Force
Write-Step ("已备份原文件: {0}" -f $bakPath)

Copy-Item -LiteralPath $tmp -Destination $TargetPath -Force

$finalChk = Test-PsSyntax -Path $TargetPath
$markers = @(
    @{ Name = 'H1'; Marker = "`$lit = 'NULL'" },
    @{ Name = 'H2-表单'; Marker = 'application/x-www-form-urlencoded' },
    @{ Name = 'H2-错误体'; Marker = '$_.ErrorDetails' },
    @{ Name = 'H4-TLS'; Marker = $tlsLine },
    @{ Name = 'H5-域名'; Marker = 'iame.ap.inalfa.local:8443' },
    @{ Name = 'H6-邀请不致命'; Marker = '$inviteFailed++' },
    @{ Name = 'H7-汇总'; Marker = '邀请邮件成功' },
    @{ Name = 'H8-计数初始化'; Marker = '$inviteFailedList = @()' },
    @{ Name = 'H9-邀请参数'; Marker = "`$InviteRedirectUri = ''" },
    @{ Name = 'H10-邀请参数日志'; Marker = '邀请邮件参数: client_id=' },
    @{ Name = 'H11-复职邀请'; Marker = '$reactBody' },
    # H12 的输出被 H13d 整段覆盖，不再单独做标记检查（H13-用户取值 已隐含它必须已生效）
    @{ Name = 'H13-助手函数'; Marker = 'function Get-Prop {' },
    @{ Name = 'H13-令牌取值'; Marker = "Get-Prop `$tokenResp 'access_token'" },
    @{ Name = 'H13-用户取值'; Marker = "`$kcUsername = [string](Get-Prop `$kcUser 'username'" },
    @{ Name = 'H13-requiredActions'; Marker = "@(Get-Prop `$kcUser 'requiredActions'" },
    @{ Name = 'H14-补发开关'; Marker = '$ResendInviteForPasswordless' },
    @{ Name = 'H14-回写-kc_user_id'; Marker = '回写 kc_user_id: {0} -> {1}' },
    @{ Name = 'H14-补发邀请'; Marker = '$resendBody' },
    @{ Name = 'H17-静默开关'; Marker = '[switch]$SkipInvite' },
    @{ Name = 'H17-计数'; Marker = '$skippedInvite = 0' },
    @{ Name = 'H17-建号跳过'; Marker = '跳过邀请(-SkipInvite):' },
    @{ Name = 'H17-复职跳过'; Marker = '跳过邀请(-SkipInvite,复职):' },
    @{ Name = 'H17-补发让位'; Marker = '-not $SkipInvite' },
    @{ Name = 'H17-汇总'; Marker = '跳过邀请 {10}' },
    @{ Name = 'H17-启动提示'; Marker = '-SkipInvite 已启用' },
    @{ Name = 'H18-严格开关'; Marker = '[switch]$StopOnError' },
    @{ Name = 'H18-失败信息助手'; Marker = 'function Get-KcFailureInfo {' },
    @{ Name = 'H18-每用户try'; Marker = '# ================= H18 单人容错 =================' },
    @{ Name = 'H18-单人失败日志'; Marker = '同步失败(已跳过，继续下一个)' },
    @{ Name = 'H18-失败计数'; Marker = '$failedList = @()' },
    @{ Name = 'H18-汇总失败数'; Marker = '失败 {11}' },
    @{ Name = 'H18-失败名单'; Marker = '失败 {0} 人（最多列 20 条）' },
    @{ Name = 'H18-全员失败兜底'; Marker = '人全部失败、无任何成功动作' },
    @{ Name = 'H19-姓名清洗助手'; Marker = 'function ConvertTo-KcPersonName {' },
    @{ Name = 'H19-回退清洗'; Marker = '姓名清洗: {0} → {1}' },
    @{ Name = 'H19-姓名口径说明'; Marker = '回退值再经 ConvertTo-KcPersonName 清洗' },
    @{ Name = 'H20-排除名单'; Marker = '$duplicate-4f3a, e-workflow.system, heqi-old' }
)
$finalText = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($TargetPath))
if ($finalText.Length -gt 0 -and $finalText[0] -eq [char]0xFEFF) { $finalText = $finalText.Substring(1) }
$missing = @()
foreach ($mk in $markers) {
    if (-not $finalText.Contains($mk.Marker)) { $missing += $mk.Name }
}

# 追加校验: PS 5.1 里 (if ...) 会被解析成"命令 if"——解析期零错误，运行到才炸。
# 用 AST 找 CommandAst 且命令名为 if 的节点，命中就回滚（H12 就是修这个）。
$tk = $null
$astErrs = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($TargetPath, [ref]$tk, [ref]$astErrs)
$badIf = @($ast.FindAll({
    param($n)
    $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'if'
}, $true))

# 再查 StrictMode 下的裸属性访问：$kcUser.lastName 这类写法在字段缺失时
# 运行期抛 "The property 'x' cannot be found"，解析期零错误。这三类变量装的是
# Keycloak 返回的 JSON（只含非空字段），一律必须走 Get-Prop。
$watchVars = @('kcUser', 'tokenResp', 'full')
$bareProp = @($ast.FindAll({
    param($n)
    if ($n -isnot [System.Management.Automation.Language.MemberExpressionAst]) { return $false }
    if ($n.Member -isnot [System.Management.Automation.Language.StringConstantExpressionAst]) { return $false }
    if ($n.Expression -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $false }
    return ($watchVars -contains $n.Expression.VariablePath.UserPath)
}, $true))

if ((-not $finalChk.Ok) -or $missing.Count -gt 0 -or $badIf.Count -gt 0 -or $bareProp.Count -gt 0) {
    Copy-Item -LiteralPath $bakPath -Destination $TargetPath -Force
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    if (-not $finalChk.Ok) {
        Write-Step ("落盘后语法校验失败，已自动回滚: {0}" -f $finalChk.Errors[0].Message) 'ERROR'
    }
    elseif ($missing.Count -gt 0) {
        Write-Step ("落盘后缺少标记 {0}，已自动回滚" -f ($missing -join ', ')) 'ERROR'
    }
    elseif ($badIf.Count -gt 0) {
        Write-Step ("落盘后仍有 (if ...) 写法（行 {0}），已自动回滚" -f
            (($badIf | ForEach-Object { $_.Extent.StartLineNumber }) -join ', ')) 'ERROR'
    }
    else {
        Write-Step ("落盘后仍有 StrictMode 裸属性访问（行 {0}），已自动回滚" -f
            (($bareProp | ForEach-Object { $_.Extent.StartLineNumber }) -join ', ')) 'ERROR'
    }
    exit 3
}

Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
Write-Step ("落盘后校验: PARSE OK，{0} 项标记齐全" -f $markers.Count)
Write-Step ("完成。回滚命令: powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_sync_sso_to_keycloak.ps1 -Rollback")
exit 0
