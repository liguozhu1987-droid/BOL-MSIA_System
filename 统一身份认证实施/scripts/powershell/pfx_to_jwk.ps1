<#
.SYNOPSIS
    把带私钥的 pfx 转成 Keycloak「Private key」字段可粘贴的 JWK（RS256）。

.DESCRIPTION
    用途：Entra 侧要求客户端用 private_key_jwt 认证（Client JWT signed with private key）时，
    把 RSA 私钥转成 JWK JSON，供 Keycloak 的「Private key」字段粘贴。
    注意：Keycloak 25.0.6 的 IdP 页面没有「Private key」字段，私钥取自 realm 的
    active 签名密钥（realm keys 导入用 PEM，不吃 JWK）；本脚本的 JWK 只在
    有该字段的版本/构建上直接可用。见手册 2.4。

    本脚本只做本地转换：
      - 不发起任何网络请求（不校验 CRL/时间戳/在线证书状态）；
      - 不读写证书存储（首选 EphemeralKeySet 把 pfx 读进内存；老 .NET 退回 Exportable 时
        会落一个用户密钥容器，由系统回收，不往证书存储里装任何东西）；
      - 不调用 openssl / keytool / java，只用 .NET 的 RSA.ExportParameters。

    同时打印证书的 Subject、SHA-1 / SHA-256 指纹、x5t / x5t#S256（base64url），
    用来和 Entra 应用上登记的证书指纹逐位核对。

    !! 安全须知 !!
    输出的 .json 文件里是【明文 RSA 私钥】。它的唯一用途是粘进 Keycloak 的
    Private key 字段：粘贴并保存成功后立即删除该文件（含回收站），
    不要留在 C:\sso\conf、不要进备份、不要随附件发送、不要截图。
    脚本本身不记录、不回显口令，也不写任何日志。

.PARAMETER PfxPath
    pfx / p12 文件路径（必须含私钥）。

.PARAMETER OutFile
    JWK 输出路径。默认与 pfx 同目录、同名 + .jwk.json。

.PARAMETER Password
    pfx 口令。不给则用 Read-Host -AsSecureString 交互输入（不回显）。

.EXAMPLE
    .\pfx_to_jwk.ps1 -PfxPath C:\sso\conf\iame.p12

.EXAMPLE
    .\pfx_to_jwk.ps1 -PfxPath C:\sso\conf\iame.p12 -OutFile C:\sso\tmp\idp.jwk.json

.NOTES
    文件: scripts/powershell/pfx_to_jwk.ps1
    执行方式: 手工，在 Keycloak 主机或任何有 .NET 的 Windows 上（离线可跑）
    退出码: 0=成功 2=参数/文件错误 3=证书或私钥错误
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PfxPath,

    [string]$OutFile = '',

    [SecureString]$Password
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

function ConvertTo-Base64Url {
    <# 字节数组 → base64url（去掉 = 填充，+ / 换成 - _）。空数组返回空串。 #>
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { return '' }
    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function ConvertTo-JwkInteger {
    <# RSA 参数 → 最短长度的大端无符号字节 → base64url。
       ExportParameters 返回的数组可能带前导 0x00（符号位），JWK 要求去掉。 #>
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { throw 'RSA 参数为空，无法转换。' }
    $i = 0
    while ($i -lt ($Bytes.Length - 1) -and $Bytes[$i] -eq 0) { $i++ }
    if ($i -eq 0) { return (ConvertTo-Base64Url -Bytes $Bytes) }
    return (ConvertTo-Base64Url -Bytes $Bytes[$i..($Bytes.Length - 1)])
}

function Get-HexThumbprint {
    param([byte[]]$Bytes)
    return (($Bytes | ForEach-Object { $_.ToString('X2') }) -join '')
}

# ---------------------------------------------------------------- 参数检查

if (-not (Test-Path -LiteralPath $PfxPath -PathType Leaf)) {
    Write-Step ("pfx 不存在: {0}" -f $PfxPath) 'ERROR'
    exit 2
}
$PfxPath = (Resolve-Path -LiteralPath $PfxPath).ProviderPath
if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = [System.IO.Path]::ChangeExtension($PfxPath, '.jwk.json')
}
$outDir = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($OutFile))
if (-not (Test-Path -LiteralPath $outDir -PathType Container)) {
    Write-Step ("输出目录不存在: {0}" -f $outDir) 'ERROR'
    exit 2
}

if ($null -eq $Password -or $Password.Length -eq 0) {
    $Password = Read-Host -AsSecureString -Prompt ("请输入 pfx 口令 [{0}]" -f [System.IO.Path]::GetFileName($PfxPath))
    if ($null -eq $Password -or $Password.Length -eq 0) {
        Write-Step '没有输入口令，退出。' 'ERROR'
        exit 2
    }
}

# ---------------------------------------------------------------- 读证书

# pfx 导入方式决定私钥能不能导出，这里按顺序试：
#   1) Exportable|EphemeralKeySet —— 私钥只在进程内存，不落密钥容器（首选）
#   2) Exportable                 —— 老 .NET 不认 EphemeralKeySet 时用（会落一个用户密钥容器）
# 每种导入方式下再试两个通道：CNG（GetRSAPrivateKey）与 CAPI（$cert.PrivateKey）。
# 从 pfx 导入的 CNG 密钥若没有 AllowPlaintextExport 策略，ExportParameters($true) 会抛
# "The requested operation is not supported"，这时换 CAPI 通道往往能拿到参数。

function Get-RsaMaterialFromCert {
    <# 返回 @{ Key=...; Parameters=... }；两个通道都失败返回 $null，错误写进 $script:KeyError。 #>
    param([Parameter(Mandatory)][System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert)
    foreach ($channel in @('cng', 'capi')) {
        $key = $null
        try {
            if ($channel -eq 'cng') {
                $key = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($Cert)
            } else {
                $key = $Cert.PrivateKey
            }
        } catch {
            $script:KeyError = $_.Exception.Message
            $key = $null
        }
        if ($null -eq $key) { continue }
        if ($key -isnot [System.Security.Cryptography.RSA]) {
            $script:KeyError = '私钥不是 RSA（ECC 证书请改用 ES256，Private key 字段填法不同）。'
            continue
        }
        try {
            $prm = $key.ExportParameters($true)
            if ($null -ne $prm.D) { return @{ Key = $key; Parameters = $prm } }
            $script:KeyError = '取不到私钥参数。'
        } catch {
            $script:KeyError = $_.Exception.Message
        }
    }
    return $null
}

$flagsList = @(
    ([System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable -bor
     [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet),
    ([System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)
)

$cert = $null
$rsaKey = $null
$p = $null
$loadError = $null
$loadedAny = $false
$script:KeyError = ''

foreach ($flags in $flagsList) {
    $candidate = $null
    try {
        $candidate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($PfxPath, $Password, $flags)
        $loadedAny = $true
    } catch {
        $loadError = $_.Exception.Message
        continue
    }
    if (-not $candidate.HasPrivateKey) {
        $loadError = '这张证书没有私钥（拿到的可能只是 .cer 公钥证书）。'
        $candidate.Dispose()
        continue
    }
    $material = Get-RsaMaterialFromCert -Cert $candidate
    if ($null -ne $material) {
        $cert = $candidate
        $rsaKey = $material.Key
        $p = $material.Parameters
        break
    }
    $candidate.Dispose()
}

if ($null -eq $cert) {
    if (-not $loadedAny) {
        Write-Step ("读取 pfx 失败（口令错或文件损坏）: {0}" -f $loadError) 'ERROR'
    } else {
        Write-Step ("私钥不可导出: {0}" -f $script:KeyError) 'ERROR'
        Write-Step '处置: 从原 keystore 重新导出 p12（keytool -importkeystore -srcstoretype PKCS12 ...），或导出 pfx 时勾选「可导出」；不要拿 .cer 试。' 'WARN'
    }
    exit 3
}

if ($null -eq $p.Exponent -or $null -eq $p.Modulus) {
    Write-Step '取不到公钥参数（n/e 为空）。' 'ERROR'
    exit 3
}

$modBits = $p.Modulus.Length * 8
if ($modBits -lt 2048) {
    Write-Step ("密钥长度 {0} bit，低于 2048，Entra/Keycloak 都可能拒绝，换证书再来。" -f $modBits) 'WARN'
}

# ---- JWK：只放 Keycloak / Nimbus 认的字段
$jwk = [ordered]@{
    kty = 'RSA'
    n   = ConvertTo-JwkInteger -Bytes $p.Modulus
    e   = ConvertTo-JwkInteger -Bytes $p.Exponent
    d   = ConvertTo-JwkInteger -Bytes $p.D
    p   = ConvertTo-JwkInteger -Bytes $p.P
    q   = ConvertTo-JwkInteger -Bytes $p.Q
    dp  = ConvertTo-JwkInteger -Bytes $p.DP
    dq  = ConvertTo-JwkInteger -Bytes $p.DQ
    qi  = ConvertTo-JwkInteger -Bytes $p.InverseQ
    alg = 'RS256'
}
$json = ($jwk | ConvertTo-Json -Compress -Depth 3)

# UTF-8 不带 BOM：Keycloak 的 Private key 字段直接粘贴整段 JSON；带 BOM 会把首个字符弄脏。
[System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))

# ---------------------------------------------------------------- 指纹

$sha1   = ([System.Security.Cryptography.SHA1]::Create()).ComputeHash($cert.RawData)
$sha256 = ([System.Security.Cryptography.SHA256]::Create()).ComputeHash($cert.RawData)
$x5t     = ConvertTo-Base64Url -Bytes $sha1
$x5tS256 = ConvertTo-Base64Url -Bytes $sha256

Write-Host ''
Write-Step '证书信息（拿去和 Entra 应用上登记的证书逐位对）' 'INFO'
Write-Host ('    Subject      : ' + $cert.Subject)
Write-Host ('    Issuer       : ' + $cert.Issuer)
Write-Host ('    NotAfter     : ' + $cert.NotAfter.ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host ('    序列号       : ' + $cert.SerialNumber)
Write-Host ('    密钥         : RSA {0} bit' -f $modBits)
Write-Host ('    SHA-1        : ' + (Get-HexThumbprint -Bytes $sha1))
Write-Host ('    SHA-256      : ' + (Get-HexThumbprint -Bytes $sha256))
Write-Host ('    x5t          : ' + $x5t)
Write-Host ('    x5t#S256     : ' + $x5tS256)
Write-Host ''
Write-Step ("JWK 已写出: {0}" -f $OutFile) 'OK'
Write-Step '这个文件是明文私钥。粘进 Keycloak 的 Private key 并保存后，立刻删除它（含回收站）。' 'WARN'
Write-Host '    粘法：IdP 页面若有「Private key」字段（更高版本/定制构建），粘整段 JSON；Keycloak 25.0.6 的 oidc 页面没有这个字段，'
Write-Host '         那里的 assertion 用 realm 的 active 签名密钥签（导入要 PEM），详见手册 2.4。'
Write-Host '    提醒：这一步只改变「Keycloak 怎么向 Entra 证明自己」，不解决 AADSTS50146（那是 Entra 签令牌的环节）。'

if ($null -ne $rsaKey) { $rsaKey.Dispose() }
$cert.Dispose()
exit 0
