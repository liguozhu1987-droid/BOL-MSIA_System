@echo off
REM Claude Code 启动脚本 - 番茄时钟任务
REM 请在 Windows 终端（CMD 或 PowerShell）中运行此脚本

echo ========================================
echo Claude Code 启动中...
echo ========================================
echo.

REM 设置 API 配置（EdgeFn DeepSeek）
set ANTHROPIC_BASE_URL=https://api.edgefn.net/v1
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=

echo [配置]
echo   API 端点: %ANTHROPIC_BASE_URL%
echo   模型: DeepSeek-V3.2
echo   认证方式: Bearer Token
echo.

REM 创建用户请求文件
echo 请帮我设计一个桌面番茄时钟 > user_request.txt

echo [状态] 正在启动 Claude Code...
echo.

REM 启动 Claude Code（跳过权限检查）
npx @anthropic-ai/claude-code --bare --dangerously-skip-permissions --model deepseek-v3 < user_request.txt

pause
