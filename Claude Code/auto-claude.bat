@echo off
REM Claude Code 启动并自动发送要求

echo ========================================
echo Claude Code 启动中...
echo ========================================
echo.

REM 设置 API 配置
set ANTHROPIC_BASE_URL=https://api.edgefn.net/v1
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=

echo 正在启动 Claude Code...
echo.

REM 创建包含用户要求的文件
echo 请帮我设计一个桌面番茄时钟 > user_request.txt

REM 启动 Claude Code 并自动输入要求
npx @anthropic-ai/claude-code --bare < user_request.txt

pause
