<#
.SYNOPSIS
    disable_user_now.ps1 现场补丁（2026-11-11 H15 + H16），可重复执行。
.DESCRIPTION
    应急停号脚本的可靠性与同步脚本同等重要：它平时不执行，一旦执行就是紧急场景，
    所以补丁的原则是"宁可整体放弃，也不产出一个语法通过但运行期崩的版本"。
    本脚本覆盖 4 项（10 个子段）：
      P1 TLS 无条件     ：SecurityProtocol=Tls12 从 -SkipCertCheck 分支里提出来，改到
                          脚本启动处无条件执行（协议协商与证书校验是两件事）。
      P2 默认基址       ：https://sso.ap.inalfa.local -> https://iame.ap.inalfa.local:8443。
      P3 取/写属性助手  ：把 Get-Prop / Set-Prop 复制进本脚本（单文件分发，不依赖同步脚本）。
      P4 KC 段重写      ：5 处 StrictMode 裸属性访问改为助手取值；新增 $kcId 守卫——
                          用户对象缺 id 时明确跳过 KC 段并 WARN，绝不拼 /users//logout。
      P5 Invoke-KcApi   ：只保留证书校验开关，去掉重复的 SecurityProtocol 设置。
      P6 跳过标记初始化 ：$kcSkipped = $false（供日志/告警使用，避免 StrictMode 未定义变量）。
      P7 未完成要吵出来 ：KC 段被跳过时，SyncLog 文案与告警标题都标记"未完成"。
      P8 SQL 参数改写   ：Invoke-Sqlcmd 不再传 -Variable（SqlServer 21.x 不接受 hashtable，
                          首次 SQL 调用就报 "The format used to define the new variable ...
                          is invalid"），改为把 @name 替换成转义字面量。该函数是所有 SQL
                          的唯一出口（中央表停用、查用户、写 SyncLog），一处改全覆盖。
      P8b 去重复转义    ：Write-SyncLog 不再预先替换单引号——转义统一由 P8 负责，否则
                          消息里的 ' 会被转义两次（同同步脚本 H3）。

    幂等：每段先查新版标记，已存在则跳过；重复执行不会二次修改。
    安全：先写临时文件 -> Parser::ParseFile 语法校验 -> 通过后才备份并覆盖目标；
          落盘后再次校验语法、标记、以及 AST 层面的两类运行期定时炸弹
          （命令名为 if 的 CommandAst、$kcUser/$full 的裸属性访问），任一不合格自动回滚。
    备份：<BackupDirectory>\disable_user_now.ps1.<时间戳>.bak

.PARAMETER TargetPath
    要修补的脚本，默认 C:\sso\scripts\disable_user_now.ps1
.PARAMETER BackupDirectory
    备份目录，默认 C:\sso\scripts\backup
.PARAMETER DryRun
    只计算与校验，不覆盖目标文件
.PARAMETER Rollback
    用最近一次备份还原目标文件（还原前先把当前文件另存一份，避免回滚不可逆）

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_disable_user_now.ps1 -DryRun

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_disable_user_now.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_disable_user_now.ps1 -Rollback
#>
[CmdletBinding()]
param(
    [string]$TargetPath = 'C:\sso\scripts\disable_user_now.ps1',
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
    $bak = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'disable_user_now.ps1.*.bak' -File |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($bak.Count -eq 0) {
        Write-Step '没有可用备份，无法回滚。' 'ERROR'
        exit 2
    }
    if (Test-Path -LiteralPath $TargetPath) {
        $safety = Join-Path $BackupDirectory ('disable_user_now.ps1.before-rollback.' +
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

# 这个脚本里必须有"紧急停号"四个字，读不到就说明不是目标文件或已被改坏。
$zhMarker = [string]::new([char[]]@(0x7D27, 0x6025, 0x505C, 0x53F7))
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

function Set-TextHunk {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$SkipIfContains,
        [switch]$Optional
    )
    $OldText = $OldText -replace "`r`n", "`n"
    $NewText = $NewText -replace "`r`n", "`n"
    if ($script:Norm.Contains($SkipIfContains)) {
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

# ============================ P1: TLS 无条件启用 ============================
$p1Old = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
'@
$p1New = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------
# Windows PowerShell 5.1 默认只协商到 TLS 1.0/1.1，而 Keycloak 25 只接受 TLS 1.2+，
# 症状是 "The request was aborted: Could not create SSL/TLS secure channel."（端口通、证书也没问题）。
# 旧版把这一行放在 Invoke-KcApi 的 if ($SkipCertCheck) 里 —— 不跳过证书校验时反而没有启用
# TLS 1.2，等于"最该保护的生产路径"最脆弱。协议协商与证书校验是两件事，必须分开。
# 只显式启用 Tls12：不叠加 Tls13——旧版 Windows Server 的 Schannel 不认这个标志。
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
'@
Set-TextHunk -Title 'P1 TLS 无条件启用' -OldText $p1Old -NewText $p1New `
    -SkipIfContains '# ---------------- TLS 协议（必须在任何 HTTPS 调用之前，无条件生效） ----------------'

# ============================ P2: 默认基址 ============================
$p2Old = "    [string]`$KeycloakBaseUrl = 'https://sso.ap.inalfa.local',"
$p2New = "    [string]`$KeycloakBaseUrl = 'https://iame.ap.inalfa.local:8443',"
Set-TextHunk -Title 'P2 默认基址' -OldText $p2Old -NewText $p2New `
    -SkipIfContains "iame.ap.inalfa.local:8443"

# ============================ P3: 取/写属性助手 ============================
$p3Old = @'
function Get-KcToken {
'@
$p3New = @'
function Get-Prop {
    <# 安全读属性：对象为 $null、属性缺失、或值为 $null 时返回默认值。
       为什么必须有它：Keycloak 的 JSON 只包含非空字段（没设 lastName 就没有该属性），
       而本脚本启用了 Set-StrictMode -Version Latest —— 裸访问不存在的属性会直接抛
       "The property 'x' cannot be found on this object"（解析期不报错，运行到才炸）。 #>
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

function Set-Prop {
    <# 安全写属性：PSCustomObject 上给"不存在的属性"赋值同样会抛错，必须 Add-Member -Force。 #>
    param([object]$Object, [Parameter(Mandatory)][string]$Name, [object]$Value)
    if ($null -eq $Object) { return }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    } else { $p.Value = $Value }
}

function Get-KcToken {
'@
Set-TextHunk -Title 'P3 取/写属性助手(Get-Prop/Set-Prop)' -OldText $p3Old -NewText $p3New `
    -SkipIfContains 'function Get-Prop {'

# ============================ P4: KC 禁用 + 踢会话段 ============================
$p4Old = @'
    # 2. Keycloak 禁用 + 踢会话
    Get-KcToken
    $found = Invoke-KcApi -Method Get `
        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users?username=$([uri]::EscapeDataString($loginName))&exact=true"
    $kcUser = $null
    if ($null -ne $found) { $arr = @($found); if ($arr.Count -gt 0) { $kcUser = $arr[0] } }
    if ($null -eq $kcUser) {
        Write-Log ("Keycloak 中不存在用户 {0}（可能未同步过），仅完成中央表停用。" -f $loginName) 'WARN'
    } else {
        if ([bool]$kcUser.enabled) {
            $full = Invoke-KcApi -Method Get -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)"
            $full.enabled = $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)" -Body $full
            Write-Log ("Keycloak 已禁用: {0}" -f $loginName) 'INFO'
        } else {
            Write-Log ("Keycloak 用户已是禁用状态: {0}" -f $loginName) 'INFO'
        }
        try {
            Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$($kcUser.id)/logout"
            Write-Log ("Keycloak 会话已踢除: {0}" -f $loginName) 'INFO'
        } catch {
            Write-Log ("踢会话失败: {0}" -f $_.Exception.Message) 'WARN'
        }
    }
'@
$p4New = @'
    # 2. Keycloak 禁用 + 踢会话
    Get-KcToken
    $found = Invoke-KcApi -Method Get `
        -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users?username=$([uri]::EscapeDataString($loginName))&exact=true"
    $kcUser = $null
    if ($null -ne $found) { $arr = @($found); if ($arr.Count -gt 0) { $kcUser = $arr[0] } }
    # JSON 只含非空字段，所有取值走 Get-Prop（StrictMode 下裸访问缺失属性会抛异常）。
    $kcId = [string](Get-Prop $kcUser 'id' '')
    if ($null -eq $kcUser) {
        Write-Log ("Keycloak 中不存在用户 {0}（可能未同步过），仅完成中央表停用。" -f $loginName) 'WARN'
    }
    elseif ($kcId -eq '') {
        # 空 id 绝不能继续拼 URL：/users//logout 只会 404，脚本却以为停号成功——
        # "停号没停成但看起来像成功"是应急脚本最坏的失效方式，所以这里显式标记未完成。
        $kcSkipped = $true
        Write-Log ("【未完成】Keycloak 用户对象缺 id，已跳过禁用/踢会话，请立即在管理控制台手工停用: {0}" -f $loginName) 'WARN'
    }
    else {
        if ([bool](Get-Prop $kcUser 'enabled' $false)) {
            $full = Invoke-KcApi -Method Get -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId"
            if ($null -eq $full) { throw ("GET Keycloak 用户整对象失败(停用): {0}" -f $loginName) }
            Set-Prop $full 'enabled' $false
            Invoke-KcApi -Method Put -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId" -Body $full
            Write-Log ("Keycloak 已禁用: {0}" -f $loginName) 'INFO'
        } else {
            Write-Log ("Keycloak 用户已是禁用状态: {0}" -f $loginName) 'INFO'
        }
        try {
            Invoke-KcApi -Method Post -Uri "$KeycloakBaseUrl/admin/realms/$Realm/users/$kcId/logout"
            Write-Log ("Keycloak 会话已踢除: {0}" -f $loginName) 'INFO'
        } catch {
            Write-Log ("踢会话失败: {0}" -f $_.Exception.Message) 'WARN'
        }
    }
'@
Set-TextHunk -Title 'P4 KC 段(安全取值+缺 id 守卫)' -OldText $p4Old -NewText $p4New `
    -SkipIfContains "elseif (`$kcId -eq '')"

# ============================ P5: Invoke-KcApi 里的 TLS 去重 ============================
$p5Old = @'
    if ($SkipCertCheck) {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    }
'@
$p5New = @'
    if ($SkipCertCheck) {
        # 只跳过证书校验；TLS 协议已在脚本启动处无条件启用（2026-11-11 H15）
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
'@
Set-TextHunk -Title 'P5 Invoke-KcApi TLS 去重' -OldText $p5Old -NewText $p5New `
    -SkipIfContains 'TLS 协议已在脚本启动处无条件启用'

# ============================ P6: $kcSkipped 初始化 ============================
$p6Old = @'
$cred = $null
try {
'@
$p6New = @'
$cred = $null
$kcSkipped = $false   # KC 段是否被跳过（如用户对象缺 id）；用于把"未完成"显式带到日志与告警
try {
'@
Set-TextHunk -Title 'P6 $kcSkipped 初始化' -OldText $p6Old -NewText $p6New `
    -SkipIfContains '$kcSkipped = $false'

# ============================ P7: 未完成要吵出来 ============================
$p7Old = @'
    $logMsg = ("紧急停号: {0} ({1}) 原因: {2}" -f $emp, $loginName, $Reason)
    Write-SyncLog -Status 'OK' -Message $logMsg -Credential $cred
'@
$p7New = @'
    $logMsg = ("紧急停号: {0} ({1}) 原因: {2}" -f $emp, $loginName, $Reason)
    if ($kcSkipped) {
        $logMsg += '；【未完成】Keycloak 段未执行（用户对象缺 id），请在管理控制台手工禁用并踢会话'
    }
    Write-SyncLog -Status 'OK' -Message $logMsg -Credential $cred
'@
Set-TextHunk -Title 'P7 日志标记未完成' -OldText $p7Old -NewText $p7New `
    -SkipIfContains 'Keycloak 段未执行（用户对象缺 id）'

$p7bOld = @'
    Send-AlertMail -Subject ("[SSO紧急停号] {0} ({1})" -f $emp, $loginName) -Body $body
'@
$p7bNew = @'
    $mailSubject = ("[SSO紧急停号] {0} ({1})" -f $emp, $loginName)
    if ($kcSkipped) { $mailSubject = ("[SSO紧急停号-未完成] {0} ({1})" -f $emp, $loginName) }
    Send-AlertMail -Subject $mailSubject -Body $body
'@
Set-TextHunk -Title 'P7b 告警标题标记未完成' -OldText $p7bOld -NewText $p7bNew `
    -SkipIfContains '[SSO紧急停号-未完成]'

# ============================ P8: Invoke-Sqlcmd 参数改写 ============================
# SqlServer 21.x 的 -Variable 只接受严格的 'name=value' 字符串数组，传 hashtable 会直接报
# "The format used to define the new variable for Invoke-Sqlcmd cmdlet is invalid"。
# 即使改对格式，它的占位符是 $(name)，与本文件查询里的 @name 口径也不一致。
# 所以索性不用 -Variable，把 @name 替换成转义后的字面量；下方 SqlClient 分支仍用真参数。
$p8Old = @'
        if ($Parameters.Count -gt 0) { $splat['Variable'] = $Parameters }
'@
$p8New = @'
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
'@
Set-TextHunk -Title 'P8 Invoke-Sqlcmd 参数改写' -OldText $p8Old -NewText $p8New `
    -SkipIfContains "故不用 -Variable，把 @name 就地替换为转义后的字面量"

# ============================ P8b: Write-SyncLog 去重复转义 ============================
$p8bOld = @'
    Invoke-SsoSql -Query $q -Parameters @{
        status = $Status; message = ($Message -replace "'", "''")
    } -Credential $Credential | Out-Null
'@
$p8bNew = @'
    # 单引号转义统一由 Invoke-SsoSql 做（H16）；这里预先转义会变成双重转义
    Invoke-SsoSql -Query $q -Parameters @{
        status = $Status; message = $Message
    } -Credential $Credential | Out-Null
'@
Set-TextHunk -Title 'P8b Write-SyncLog 去重复转义' -OldText $p8bOld -NewText $p8bNew `
    -SkipIfContains '单引号转义统一由 Invoke-SsoSql 做'

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
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('disable_user_now.patch_' + [guid]::NewGuid().ToString('N') + '.ps1')
[System.IO.File]::WriteAllText($tmp, $out, (New-Object System.Text.UTF8Encoding($true)))

$tmpChk = Test-PsSyntax -Path $tmp
if (-not $tmpChk.Ok) {
    Write-Step ("补丁结果语法校验失败，已放弃（目标未改）: {0}" -f $tmpChk.Errors[0].Message) 'ERROR'
    Write-Step ("临时文件保留供排查: {0}" -f $tmp)
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
$bakPath = Join-Path $BackupDirectory ('disable_user_now.ps1.' + (Get-Date).ToString('yyyyMMdd-HHmmss') + '.bak')
Copy-Item -LiteralPath $TargetPath -Destination $bakPath -Force
Write-Step ("已备份原文件: {0}" -f $bakPath)

Copy-Item -LiteralPath $tmp -Destination $TargetPath -Force

$finalChk = Test-PsSyntax -Path $TargetPath
$markers = @(
    @{ Name = 'P1-TLS'; Marker = '[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12' },
    @{ Name = 'P2-域名'; Marker = 'iame.ap.inalfa.local:8443' },
    @{ Name = 'P3-助手函数'; Marker = 'function Get-Prop {' },
    @{ Name = 'P4-缺id守卫'; Marker = "elseif (`$kcId -eq '')" },
    @{ Name = 'P4-安全写enabled'; Marker = "Set-Prop `$full 'enabled'" },
    @{ Name = 'P4-踢会话用kcId'; Marker = 'users/$kcId/logout' },
    @{ Name = 'P5-TLS去重'; Marker = 'TLS 协议已在脚本启动处无条件启用' },
    @{ Name = 'P6-跳过标记'; Marker = '$kcSkipped = $false' },
    @{ Name = 'P7-日志未完成'; Marker = 'Keycloak 段未执行（用户对象缺 id）' },
    @{ Name = 'P7b-告警未完成'; Marker = '[SSO紧急停号-未完成]' },
    @{ Name = 'P8-SQL字面量'; Marker = "故不用 -Variable，把 @name 就地替换为转义后的字面量" },
    @{ Name = 'P8-替换实现'; Marker = "`$splat['Query'] = [regex]::Replace(" },
    @{ Name = 'P8b-去重复转义'; Marker = '单引号转义统一由 Invoke-SsoSql 做' }
)
$finalText = [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($TargetPath))
if ($finalText.Length -gt 0 -and $finalText[0] -eq [char]0xFEFF) { $finalText = $finalText.Substring(1) }
$missing = @()
foreach ($mk in $markers) {
    if (-not $finalText.Contains($mk.Marker)) { $missing += $mk.Name }
}

# 运行期定时炸弹 1: PS 5.1 里 (if ...) 会被解析成"命令 if"，解析期零错误、运行到才炸。
$tk = $null
$astErrs = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($TargetPath, [ref]$tk, [ref]$astErrs)
$badIf = @($ast.FindAll({
    param($n)
    $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'if'
}, $true))

# 运行期定时炸弹 2: StrictMode 下对 JSON 对象裸取/裸写属性。
$watchVars = @('kcUser', 'full')
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
Write-Step ("完成。回滚命令: powershell -NoProfile -ExecutionPolicy Bypass -File .\patch_disable_user_now.ps1 -Rollback")
exit 0
