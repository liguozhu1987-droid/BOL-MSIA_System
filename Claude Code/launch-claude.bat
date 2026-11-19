@echo off
REM TRAE 终端 Claude Code 启动脚本

echo ========================================
echo Claude Code 启动器 (EdgeFn API)
echo ========================================
echo.

REM 设置 API 配置
set ANTHROPIC_BASE_URL=https://api.edgefn.net/v1
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=

echo [配置] API 端点: %ANTHROPIC_BASE_URL%
echo [配置] 模型: DeepSeek-V3.2
echo.
echo 正在启动 Claude Code...
echo.

REM 启动 Claude Code
npx @anthropic-ai/claude-code

pause
