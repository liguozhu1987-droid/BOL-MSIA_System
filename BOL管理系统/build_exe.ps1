<#
.SYNOPSIS
    BOL 管理系统 - 独立可执行程序（exe）打包脚本（含防杀软误报措施与完整性闸门）

.DESCRIPTION
    一键完成标准打包流程，并在每个关键节点设置"完整性闸门"，任一闸门失败立即中止：

      步骤0  前置检查（工具链 + 防误报配置自检）
      步骤1  前端构建（可 -SkipFrontend 跳过）
      闸门1  前端入口 JS 必须真实存在（防杀软静默删除产物）
      步骤2  collectstatic --clear 重新收集静态文件
      闸门2  staticfiles 入口 JS 与前端 dist 完全一致
      步骤3  PyInstaller 打包（onedir + 不加壳 + 嵌入版本信息）
      闸门3  exe 生成且体积合理
      步骤4  装配部署文件（db_config.ini.example + 自动生成 README_DEPLOY.txt）
      闸门4  包内静态文件与入口 JS 完整
      步骤5  生成 ZIP（.NET ZipArchive，正斜杠 + 目录条目）
      闸门5  ZIP 条目数、入口 JS、无反斜杠路径

    设计动机：本项目的杀毒软件曾静默删除前端构建产物与后端源码，导致"打包成功
    但部署后白屏/接口 404"。闸门把这类问题拦截在打包阶段，而不是部署之后。

.EXAMPLE
    .\build_exe.ps1                    # 完整流程
    .\build_exe.ps1 -SkipFrontend      # 前端未改动时跳过构建（更快）
    .\build_exe.ps1 -NoZip             # 只打包不压缩，便于本地直接冒烟测试
    .\build_exe.ps1 -IncludeDbConfig   # 把本机 db_config.ini 也打入 zip（跨机部署慎用）

.NOTES
    详细方法论见同目录《打包防杀软误报方法.md》

    发布候选包用法（输出独立目录，不覆盖 backend\dist，不动运行中进程与既有静态文件）：
      .\build_exe.ps1 -SkipFrontend -NoZip -OutDir 'dist\bol-20261110-1530' `
                      -WorkDir 'build\bol-20261110-1530' -NoStaticClear -SkipStopProcess
#>
[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$NoZip,
    [switch]$IncludeDbConfig,
    # 输出根目录（相对项目根或绝对路径）；指定后 PyInstaller 产物写入此处，不覆盖 backend\dist
    [string]$OutDir = '',
    # PyInstaller 中间产物目录（workpath）；指定后不写入 backend\build
    [string]$WorkDir = '',
    # 跳过 collectstatic --clear：不删除既有 staticfiles 内容，仅按需覆盖写入
    [switch]$NoStaticClear,
    # 跳过"停止正在运行的 BOLServer 进程"：现场发布 / 只读核对时必须使用
    [switch]$SkipStopProcess
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# ============================================================
# 路径定义
# ============================================================
$ROOT     = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND  = Join-Path $ROOT 'backend'
$FRONTEND = Join-Path $ROOT 'frontend'
$FE_DIST  = Join-Path $FRONTEND 'dist'
$STATIC   = Join-Path $BACKEND 'staticfiles'
$SPEC     = Join-Path $BACKEND 'bol_server.spec'
$VERINFO  = Join-Path $BACKEND 'version_info.py'

function Resolve-FromRoot([string]$p) {
    if (-not $p) { return '' }
    if ([System.IO.Path]::IsPathRooted($p)) { return [System.IO.Path]::GetFullPath($p) }
    return [System.IO.Path]::GetFullPath((Join-Path $ROOT $p))
}

$DIST_ROOT = if ($OutDir)  { Resolve-FromRoot $OutDir }  else { Join-Path $BACKEND 'dist' }
$WORK_ROOT = if ($WorkDir) { Resolve-FromRoot $WorkDir } else { Join-Path $BACKEND 'build' }
$DIST     = Join-Path $DIST_ROOT 'BOLServer'
$DIST_SF  = Join-Path $DIST '_internal\staticfiles'
$STAMP    = Get-Date -Format 'yyyyMMdd'
$ZIP_PATH = if ($OutDir) { Join-Path $DIST_ROOT "BOLServer-Deploy-Package-$STAMP.zip" }
            else         { Join-Path $ROOT "BOLServer-Deploy-Package-$STAMP.zip" }
$TOP      = 'BOLServer'

# ============================================================
# 输出与闸门工具
# ============================================================
$script:GateNo = 0

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "    [OK] $msg" -ForegroundColor Green
}

function Write-Info([string]$msg) {
    Write-Host "    $msg" -ForegroundColor Gray
}

function Assert-Gate {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [string]$Hint
    )
    $script:GateNo++
    $passed = $false
    try { $passed = [bool](& $Test) } catch { $passed = $false }

    if (-not $passed) {
        Write-Host ""
        Write-Host "    [闸门 $script:GateNo 失败] $Name" -ForegroundColor Red
        if ($Hint) { Write-Host "    排查建议: $Hint" -ForegroundColor Yellow }
        Write-Host ""
        Write-Host "    打包已中止：产物不完整时继续打包，只会得到一个启动后" -ForegroundColor Red
        Write-Host "    白屏 / 接口 404 的部署包。请先修复再重新执行本脚本。" -ForegroundColor Red
        throw "完整性闸门未通过: $Name"
    }
    Write-Ok "闸门 $script:GateNo 通过 - $Name"
}

function Get-EntryAsset {
    <# 从 index.html 中解析入口 JS 的相对路径（如 assets/index-XXXX.js） #>
    param([string]$IndexHtml)
    if (-not (Test-Path $IndexHtml)) { return $null }
    $raw = Get-Content $IndexHtml -Raw
    $m = [regex]::Match($raw, 'src="(/?assets/[^"]+\.js)"')
    if ($m.Success) { return $m.Groups[1].Value.TrimStart('/') }
    return $null
}

function Invoke-Native {
    <#
      统一执行外部命令（npm / python 等）。

      为什么必须包装：脚本全局 $ErrorActionPreference='Stop'，而 vite、
      PyInstaller 会把 INFO/警告写到 stderr，直接调用会被 PowerShell 判为
      NativeCommandError 而中断打包。这里临时切到 Continue 收集输出，
      再用退出码判定成败。
    #>
    param(
        [string]$Exe,
        [string[]]$CmdArgs,
        [string]$WorkDir,
        [int]$TailLines = 3,
        [string]$FailMsg
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    if ($WorkDir) { Push-Location $WorkDir }
    try {
        $out = & $Exe @CmdArgs 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        if ($WorkDir) { Pop-Location }
        $ErrorActionPreference = $prev
    }
    if ($TailLines -gt 0) {
        $out | Select-Object -Last $TailLines | ForEach-Object { Write-Info $_.ToString() }
    }
    if ($code -ne 0) {
        Write-Host ''
        Write-Host '    ---- 完整输出（末尾 40 行）----' -ForegroundColor Yellow
        $out | Select-Object -Last 40 | ForEach-Object { Write-Host "    $($_.ToString())" -ForegroundColor DarkGray }
        throw "$FailMsg（退出码 $code）"
    }
    return $out
}

function New-DeployReadme {
    <# 生成部署说明，静态文件数量等由本次实际打包结果填入，避免说明与实物不符 #>
    param(
        [string]$Path,
        [string]$EntryAsset,
        [int]$SfCount,
        [string]$ExeSizeMB
    )
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $L = @()
    $L += '============================================================'
    $L += '  BOL 管理分析平台 - 独立可执行程序部署包'
    $L += "  打包时间: $now"
    $L += '============================================================'
    $L += ''
    $L += '[部署步骤]'
    $L += '  1. 将本 ZIP 整体复制到目标机器'
    $L += '  2. 右键解压到任意目录（例如 D:\BOLServer\）'
    $L += '  3. 按需创建数据库配置文件（见下方"数据库配置"）'
    $L += '  4. 运行 BOLServer.exe            # 默认监听 0.0.0.0:8090'
    $L += '  5. 浏览器访问 http://127.0.0.1:8090/'
    $L += ''
    $L += '  !!! BOLServer.exe 不是单文件程序，必须与 _internal 目录一起部署 !!!'
    $L += '      只复制 exe 会报"启动前置条件未满足：静态文件目录不存在"。'
    $L += ''
    $L += '[部署后自检]'
    $L += '  以下任一项缺失，说明解压/复制不完整，或已被杀毒软件删除：'
    $L += "    _internal\staticfiles\index.html          前端入口"
    $L += "    _internal\staticfiles\$EntryAsset"
    $L += '                                                前端入口 JS（缺失则页面白屏）'
    $L += '    _internal\staticfiles\admin\              Django 后台静态资源'
    $L += '    _internal\apps\                           业务模块资源（migrations 等）'
    $L += "  本次打包静态文件总数: $SfCount 个"
    $L += "  本次 BOLServer.exe 体积: $ExeSizeMB MB"
    $L += ''
    $L += '[数据库配置]'
    $L += '  1. 复制 db_config.ini.example 为 db_config.ini（与 exe 同目录）'
    $L += '  2. 确认 driver 与目标机器"已安装"的 ODBC 驱动完全一致，否则接口全部 500：'
    $L += '       PowerShell 执行  Get-OdbcDriver | Select-Object Name'
    $L += '       常见值: ODBC Driver 17 for SQL Server / ODBC Driver 18 for SQL Server'
    $L += '  3. 不创建 db_config.ini 时，程序使用内置默认值（ODBC Driver 18），'
    $L += '     但内置默认不含口令，必须先按第 1 步创建 db_config.ini 才能连接数据库'
    $L += '  4. 报错 IM002 / Data source name not found 即为驱动名不匹配'
    $L += ''
    $L += '[端口配置]'
    $L += '  默认端口: 8090'
    $L += '  自定义:   BOLServer.exe --port 9000'
    $L += '  指定网卡: BOLServer.exe --host 127.0.0.1'
    $L += ''
    $L += '[冒烟测试]'
    $L += '  服务启动后依次验证（PowerShell）：'
    $L += '    Invoke-WebRequest http://127.0.0.1:8090/ -UseBasicParsing'
    $L += '    Invoke-RestMethod http://127.0.0.1:8090/api/auth/guest-login/ -Method POST'
    $L += '  两者均应返回 200。若登录接口返回 500，优先排查 db_config.ini 的驱动名。'
    $L += ''
    $L += '[杀毒软件注意事项]'
    $L += '  本程序为 PyInstaller 打包产物，部分杀软会启发式误报。建议：'
    $L += '  1. 将部署目录加入杀软白名单/排除项（最有效）'
    $L += '  2. 不要对 exe 或 _internal 目录做二次加壳、压缩、加密'
    $L += '  3. 若文件被杀软删除，请勿直接重装，先按《打包防杀软误报方法.md》'
    $L += '     第 6 节的恢复手册找回源码，再重新打包'
    $L += ''
    $L += '============================================================'
    Set-Content -Path $Path -Value $L -Encoding UTF8
}

function New-DeployZip {
    <#
      用 .NET ZipArchive 生成 ZIP：
        - 统一正斜杠路径（Compress-Archive 在部分解压工具下路径分隔符不一致）
        - 显式写入目录条目（保证解压后目录结构完整）
        - Optimal 压缩
    #>
    param(
        [string]$SrcDir,
        [string]$ZipPath,
        [string]$TopFolder
    )
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $zip = [System.IO.Compression.ZipFile]::Open($ZipPath, 'Create')
    try {
        foreach ($d in (Get-ChildItem $SrcDir -Recurse -Directory)) {
            $rel = "$TopFolder/" + $d.FullName.Substring($SrcDir.Length + 1).Replace('\', '/') + '/'
            [void]$zip.CreateEntry($rel)
        }
        foreach ($f in (Get-ChildItem $SrcDir -Recurse -File)) {
            $rel = "$TopFolder/" + $f.FullName.Substring($SrcDir.Length + 1).Replace('\', '/')
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $f.FullName, $rel,
                [System.IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally { $zip.Dispose() }
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor White
Write-Host '  BOL 管理分析平台 - exe 打包（防杀软误报 + 完整性闸门）' -ForegroundColor White
Write-Host "  项目根目录: $ROOT" -ForegroundColor Gray
Write-Host "  参数: SkipFrontend=$SkipFrontend  NoZip=$NoZip  IncludeDbConfig=$IncludeDbConfig" -ForegroundColor Gray
Write-Host "        NoStaticClear=$NoStaticClear  SkipStopProcess=$SkipStopProcess" -ForegroundColor Gray
Write-Host "        输出根目录: $DIST_ROOT" -ForegroundColor Gray
Write-Host "        中间目录  : $WORK_ROOT" -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor White

# ============================================================
# 步骤 0：前置检查（工具链 + 防误报配置自检）
# ============================================================
Write-Step '步骤 0/5  前置检查'

# 0.1 先停掉正在运行的服务，否则 exe / _internal 被占用会导致打包失败
if ($SkipStopProcess) {
    Write-Info '已跳过"停止 BOLServer 进程"（-SkipStopProcess）：不触碰任何正在运行的服务'
}
else {
    $running = Get-Process BOLServer -ErrorAction SilentlyContinue
    if ($running) {
        Write-Info "检测到 BOLServer 正在运行（PID: $(($running | ForEach-Object Id) -join ', ')），先停止..."
        Stop-Process -Name BOLServer -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

# 0.2 工具链
foreach ($cmd in @('python', 'node', 'npm')) {
    $need = if ($cmd -eq 'node' -or $cmd -eq 'npm') { -not $SkipFrontend } else { $true }
    if ($need) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            throw "未找到 $cmd，请确认已安装并加入 PATH（或用 -SkipFrontend 跳过前端构建）"
        }
    }
}
Write-Ok "工具链就绪: python $(python --version 2>&1 | ForEach-Object { $_.ToString().Replace('Python ','') })"

# 0.3 关键文件
foreach ($f in @($SPEC, $VERINFO, (Join-Path $BACKEND 'run_server.py'))) {
    if (-not (Test-Path $f)) { throw "缺少必要文件: $f" }
}
Write-Ok '打包配置齐备: bol_server.spec / version_info.py / run_server.py'

# 0.4 PyInstaller 可用
python -c "import PyInstaller, sys; sys.stdout.write(PyInstaller.__version__)" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 不可用，请执行 pip install pyinstaller' }
Write-Ok 'PyInstaller 可用'

# 0.5 防杀软误报配置自检：这三项是误报率的主要影响因素，被改动会直接拉高风险
$specText = Get-Content $SPEC -Raw
Assert-Gate -Name 'spec 未启用 UPX 加壳（upx=False）' -Hint "在 $SPEC 的 EXE() 与 COLLECT() 中确保 upx=False；UPX 加壳是 PyInstaller 产物被误报的首要原因" -Test {
    ($specText -match 'upx\s*=\s*False') -and ($specText -notmatch 'upx\s*=\s*True')
}
Assert-Gate -Name 'spec 为 onedir 模式（存在 COLLECT）' -Hint 'onefile 单文件自解压行为与恶意软件高度相似，务必保持 onedir；请勿改回 --onefile' -Test {
    $specText -match 'COLLECT\s*\('
}
Assert-Gate -Name 'spec 未启用字节码加密（block_cipher = None）' -Hint '加密/混淆会显著提高启发式误报率，保持 block_cipher = None' -Test {
    $specText -match 'block_cipher\s*=\s*None'
}
Assert-Gate -Name 'spec 已嵌入版本信息资源（version=version_info.py）' -Hint '无版本信息的 exe 更易被判定为可疑程序；确认 EXE() 中 version 指向 version_info.py' -Test {
    $specText -match "version\s*=\s*str\(SPEC_DIR\s*/\s*'version_info\.py'\)"
}
$verText = Get-Content $VERINFO -Raw
Assert-Gate -Name '版本信息含公司与产品元数据' -Hint '在 version_info.py 中补全 CompanyName / FileDescription / ProductName / LegalCopyright' -Test {
    ($verText -match 'CompanyName') -and ($verText -match 'ProductName') -and ($verText -match 'LegalCopyright')
}

# ============================================================
# 步骤 1：前端构建 + 闸门 1
# ============================================================
if ($SkipFrontend) {
    Write-Step '步骤 1/5  前端构建（已跳过 -SkipFrontend）'
    if (-not (Test-Path (Join-Path $FE_DIST 'index.html'))) {
        throw "frontend\dist 不存在，无法跳过前端构建；请去掉 -SkipFrontend"
    }
}
else {
    Write-Step '步骤 1/5  前端构建（vite build）'
    if (-not (Test-Path (Join-Path $FRONTEND 'node_modules'))) {
        Write-Info '首次构建，安装前端依赖 npm install ...'
        Invoke-Native -Exe 'npm' -CmdArgs @('install', '--silent') -WorkDir $FRONTEND -TailLines 2 -FailMsg 'npm install 失败'
    }
    Invoke-Native -Exe 'npm' -CmdArgs @('run', 'build') -WorkDir $FRONTEND -TailLines 3 -FailMsg '前端构建失败，请检查上方 vite 报错（常见：源文件被杀软删除导致 UNRESOLVED_IMPORT）'
}

$feEntry = Get-EntryAsset (Join-Path $FE_DIST 'index.html')
Assert-Gate -Name '前端入口 JS 真实存在' -Hint "index.html 引用 $feEntry，但该文件不在 frontend\dist 中。极可能是被杀毒软件删除：请检查杀软隔离区，并把 frontend\dist 加入排除项后重新构建" -Test {
    $feEntry -and (Test-Path (Join-Path $FE_DIST $feEntry))
}
$feCount = (Get-ChildItem $FE_DIST -Recurse -File | Measure-Object).Count
Write-Ok "frontend\dist 完整：入口 $feEntry，共 $feCount 个文件"

# ============================================================
# 步骤 2：收集静态文件 + 闸门 2
# ============================================================
Write-Step '步骤 2/5  收集静态文件'
# --clear 必加：否则上次构建的旧 hash 文件会残留，index.html 与 assets 可能对不上
# -NoStaticClear：不删除既有 staticfiles 内容（只读核对/现场发布时使用），仍会覆盖写入同名文件
$csArgs = @('manage.py', 'collectstatic', '--noinput', '--settings=bol_platform.settings_prod')
if (-not $NoStaticClear) { $csArgs = @('manage.py', 'collectstatic', '--noinput', '--clear', '--settings=bol_platform.settings_prod') }
if ($NoStaticClear) { Write-Info 'collectstatic 未使用 --clear（不删除既有静态文件）' }
Invoke-Native -Exe 'python' -CmdArgs $csArgs -WorkDir $BACKEND -TailLines 2 -FailMsg 'collectstatic 失败'

$sfEntry = Get-EntryAsset (Join-Path $STATIC 'index.html')
Assert-Gate -Name 'staticfiles 入口 JS 与前端 dist 一致' -Hint "staticfiles 引用 $sfEntry，前端 dist 引用 $feEntry。不一致说明 collectstatic 收集了过期内容，请确认已使用 --clear" -Test {
    $sfEntry -and ($sfEntry -eq $feEntry) -and (Test-Path (Join-Path $STATIC $sfEntry))
}
$sfCount = (Get-ChildItem $STATIC -Recurse -File | Measure-Object).Count
# 组成校验（比固定总数阈值更可靠）：staticfiles 必须恰好等于
# 前端 dist + Django admin + DRF 三部分，多/少都说明收集不完整或混入陈旧文件。
# 注：Vite 8(rolldown) 产物约 60 个文件，故旧阈值 250 已失效，改为按组成核对。
$admCount = (Get-ChildItem (Join-Path $STATIC 'admin') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
$drfCount = (Get-ChildItem (Join-Path $STATIC 'rest_framework') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
$expectSf = $feCount + $admCount + $drfCount
Assert-Gate -Name "静态文件收集完整（$sfCount = 前端 $feCount + admin $admCount + DRF $drfCount）" -Hint "staticfiles 总数与三部分之和不一致，说明 collectstatic 未收全、混入陈旧文件或被杀软删除；若前端产物数量变化，请核对 frontend\dist 是否完整" -Test {
    ($sfCount -eq $expectSf) -and ($sfCount -ge 200) -and ($admCount -gt 100) -and ($drfCount -gt 20)
}

# ============================================================
# 步骤 3：PyInstaller 打包 + 闸门 3
# ============================================================
Write-Step '步骤 3/5  PyInstaller 打包（onedir，不加壳，不加密）'
Write-Info "输出目录: $DIST_ROOT"
Write-Info "中间目录: $WORK_ROOT"
Invoke-Native -Exe 'python' -CmdArgs @('-m', 'PyInstaller', 'bol_server.spec', '--noconfirm', '--distpath', $DIST_ROOT, '--workpath', $WORK_ROOT) -WorkDir $BACKEND -TailLines 3 -FailMsg 'PyInstaller 打包失败，请检查上方报错'

$EXE = Join-Path $DIST 'BOLServer.exe'
Assert-Gate -Name 'BOLServer.exe 已生成且体积合理' -Hint "未找到 $EXE 或体积异常。若刚生成即消失，几乎可确定被杀软实时查杀：请将 backend\dist 加入排除项后重打包" -Test {
    (Test-Path $EXE) -and ((Get-Item $EXE).Length -gt 5MB)
}
$exeMB = [math]::Round((Get-Item $EXE).Length / 1MB, 1)
Write-Ok "BOLServer.exe 生成成功（$exeMB MB）"

# ============================================================
# 步骤 4：装配部署文件 + 闸门 4
# ============================================================
Write-Step '步骤 4/5  装配部署文件'

# db_config.ini.example 随包发布；db_config.ini 默认不入包
# （其中 driver 与机器强相关，误带会导致目标机 IM002 → 接口全部 500）
$example = Join-Path $BACKEND 'db_config.ini.example'
if (Test-Path $example) {
    Copy-Item $example (Join-Path $DIST 'db_config.ini.example') -Force
    Write-Ok 'db_config.ini.example 已放入包内'
}
else {
    Write-Info '[警告] backend\db_config.ini.example 不存在，包内将缺少配置样例'
}

if ($IncludeDbConfig) {
    $localCfg = Join-Path $BACKEND 'db_config.ini'
    if (Test-Path $localCfg) {
        Copy-Item $localCfg (Join-Path $DIST 'db_config.ini') -Force
        $drvLine = Select-String -Path $localCfg -Pattern '^\s*driver\s*=\s*(.+)$' | Select-Object -First 1
        $drv = if ($drvLine) { $drvLine.Matches[0].Groups[1].Value.Trim() } else { '未知' }
        Write-Info "[注意] 已打入本机 db_config.ini，driver = $drv"
        Write-Info "       目标机器若未安装该驱动，接口将全部 500（IM002）。跨机部署请去掉 -IncludeDbConfig"
    }
}
else {
    $stale = Join-Path $DIST 'db_config.ini'
    if (Test-Path $stale) {
        Remove-Item $stale -Force
        Write-Info '已移除包内遗留的 db_config.ini（环境相关配置不随包分发，避免目标机驱动不匹配）'
    }
}

$distEntry = Get-EntryAsset (Join-Path $DIST_SF 'index.html')
New-DeployReadme -Path (Join-Path $DIST 'README_DEPLOY.txt') `
    -EntryAsset $distEntry `
    -SfCount (Get-ChildItem $DIST_SF -Recurse -File | Measure-Object).Count `
    -ExeSizeMB $exeMB
Write-Ok 'README_DEPLOY.txt 已按本次实际打包结果生成'

# PyInstaller 的 datas 会整体复制 migrations/management 目录，连带其中的
# __pycache__ 与 .pyc（含其他 Python 版本的历史残留）。这些属于开发残留，
# 既无运行时用途，也会让包内出现旧字节码，必须在入包前清除。
$pycDirs = @(Get-ChildItem $DIST -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue)
foreach ($d in $pycDirs) { Remove-Item $d.FullName -Recurse -Force -ErrorAction SilentlyContinue }
$pycLeft = @(Get-ChildItem $DIST -Recurse -File -Filter '*.pyc' -ErrorAction SilentlyContinue).Count
if ($pycDirs.Count -gt 0) { Write-Info "已清除包内 __pycache__ 目录 $($pycDirs.Count) 个" }
Assert-Gate -Name '包内无 __pycache__ / .pyc 开发残留' -Hint 'datas 整体复制 migrations/management 目录时会带入 __pycache__；确认清理步骤在 PyInstaller 之后、生成 ZIP 之前执行' -Test {
    $pycLeft -eq 0
}

Assert-Gate -Name '包内前端入口 JS 完整（防白屏）' -Hint "包内 index.html 引用 $distEntry 但文件缺失。这是本项目踩过的真实坑：杀软删除了 JS 产物，打包看似成功但部署后白屏" -Test {
    $distEntry -and (Test-Path (Join-Path $DIST_SF $distEntry))
}
Assert-Gate -Name '包内含 Python 运行时与 pyodbc 驱动' -Hint '缺少 python312.dll 或 pyodbc*.pyd 说明 spec 的 hiddenimports/binaries 被改动' -Test {
    (Test-Path (Join-Path $DIST '_internal\python312.dll')) -and
    ((Get-ChildItem (Join-Path $DIST '_internal') -Filter 'pyodbc*.pyd' -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
}
Assert-Gate -Name '包内含业务模块资源目录 _internal\apps' -Hint 'migrations 与 management commands 通过 datas 收集，缺失会导致启动或迁移失败' -Test {
    (Test-Path (Join-Path $DIST '_internal\apps'))
}

# ============================================================
# 步骤 5：生成 ZIP + 闸门 5
# ============================================================
if ($NoZip) {
    Write-Step '步骤 5/5  生成 ZIP（已跳过 -NoZip）'
}
else {
    Write-Step '步骤 5/5  生成部署 ZIP'
    New-DeployZip -SrcDir $DIST -ZipPath $ZIP_PATH -TopFolder $TOP
    $zipMB = [math]::Round((Get-Item $ZIP_PATH).Length / 1MB, 1)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zr = [System.IO.Compression.ZipFile]::OpenRead($ZIP_PATH)
    try {
        $entryCount = $zr.Entries.Count
        $backslash  = @($zr.Entries | Where-Object { $_.FullName -match '\\' }).Count
        $zipEntryJs = ($zr.Entries | Where-Object { $_.FullName -eq "$TOP/_internal/staticfiles/$distEntry" }).Length
        $zipExe     = ($zr.Entries | Where-Object { $_.FullName -eq "$TOP/BOLServer.exe" }).Length
        $cfgNames   = @($zr.Entries | Where-Object { $_.FullName -match "^$TOP/(db_config\.ini(\.example)?|README_DEPLOY\.txt)$" } |
                            ForEach-Object { $_.FullName })
    }
    finally { $zr.Dispose() }

    Assert-Gate -Name 'ZIP 路径规范（无反斜杠条目）' -Hint '部分解压工具对反斜杠路径处理不一致，必须统一正斜杠' -Test { $backslash -eq 0 }
    Assert-Gate -Name 'ZIP 内含入口 JS 且大小非零' -Hint "未找到 $TOP/_internal/staticfiles/$distEntry" -Test { $zipEntryJs -gt 100000 }
    Assert-Gate -Name 'ZIP 内含 BOLServer.exe 且大小一致' -Hint 'exe 未入包或大小异常' -Test { $zipExe -eq (Get-Item $EXE).Length }
    Write-Ok "ZIP 校验通过：$entryCount 条目 / $zipMB MB / 配置文件: $($cfgNames -join ', ')"
}

# ============================================================
# 完成汇总
# ============================================================
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  打包完成，5 道完整性闸门全部通过' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host "  程序目录 : $DIST"
if (-not $NoZip) { Write-Host "  部署压缩包: $ZIP_PATH" }
Write-Host "  前端入口 : $distEntry"
Write-Host "  静态文件 : $((Get-ChildItem $DIST_SF -Recurse -File | Measure-Object).Count) 个"
Write-Host ''
Write-Host '  [建议立即冒烟测试]' -ForegroundColor Yellow
Write-Host "    Start-Process '$DIST\BOLServer.exe' -WorkingDirectory '$DIST'"
Write-Host '    Invoke-WebRequest http://127.0.0.1:8090/ -UseBasicParsing'
Write-Host '    Invoke-RestMethod http://127.0.0.1:8090/api/auth/guest-login/ -Method POST'
Write-Host ''
Write-Host '  [交付前必做]' -ForegroundColor Yellow
Write-Host '    1. 用 VirusTotal 或本机杀软扫一遍 exe，确认未被标记'
Write-Host '    2. 把部署目录加入目标机器杀软排除项（详见《打包防杀软误报方法.md》第 4 节）'
Write-Host '    3. 已用公司代码签名证书签名的，跳过第 1 步'
Write-Host ''
