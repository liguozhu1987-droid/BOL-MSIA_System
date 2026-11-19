# Claude Code 自动启动脚本

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Claude Code 正在启动..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 设置环境变量
$env:ANTHROPIC_BASE_URL = "https://api.edgefn.net/v1"
$env:ANTHROPIC_AUTH_TOKEN = "sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19"
$env:ANTHROPIC_API_KEY = ""

Write-Host "[配置]" -ForegroundColor Green
Write-Host "  API 端点: $env:ANTHROPIC_BASE_URL" -ForegroundColor White
Write-Host "  模型: DeepSeek-V3.2" -ForegroundColor White
Write-Host ""

Write-Host "正在启动 Claude Code..." -ForegroundColor Yellow
Write-Host ""

# 启动 Claude Code（使用 -p 参数进行非交互模式）
# 用户的要求
$request = "请帮我设计一个桌面番茄时钟"

# 使用 npx 启动 Claude Code 并传入请求
$process = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npx @anthropic-ai/claude-code --bare -p `"$request`"" -NoNewWindow -PassThru

Write-Host "Claude Code 已启动，正在处理你的请求..." -ForegroundColor Green
Write-Host ""
Write-Host "请在弹出的终端窗口中查看 Claude Code 的响应" -ForegroundColor Cyan
Write-Host ""

# 等待一段时间让 Claude Code 运行
Start-Sleep -Seconds 5

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Claude Code 正在运行中..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "提示：" -ForegroundColor Yellow
Write-Host "  - Claude Code 会在终端中显示响应" -ForegroundColor White
Write-Host "  - 你可以随时在终端中输入更多命令" -ForegroundColor White
Write-Host "  - 完成后关闭终端即可退出" -ForegroundColor White
Write-Host ""
