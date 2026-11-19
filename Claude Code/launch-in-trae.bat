@echo off
REM TRAE 终端 Claude Code 启动脚本

echo ========================================
echo Claude Code 启动中...
echo ========================================
echo.

REM 设置 API 配置
set ANTHROPIC_BASE_URL=https://api.edgefn.net/v1
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=

echo [配置]
echo   API 端点: %ANTHROPIC_BASE_URL%
echo   模型: DeepSeek-V3.2
echo.

echo 正在启动 Claude Code...
echo.

REM 启动 Claude Code（交互模式）
npx @anthropic-ai/claude-code --bare --dangerously-skip-permissions

echo.
echo Claude Code 已关闭
pause
