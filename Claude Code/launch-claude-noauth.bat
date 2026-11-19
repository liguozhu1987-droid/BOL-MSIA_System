@echo off
REM Claude Code 启动脚本 - 跳过登录版本

echo ========================================
echo Claude Code 启动器 (无需登录)
echo ========================================
echo.

REM 设置 API 配置（使用 DeepSeek）
set ANTHROPIC_BASE_URL=https://api.edgefn.net/v1
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=

echo [配置] API 端点: %ANTHROPIC_BASE_URL%
echo [配置] 模型: DeepSeek-V3.2
echo.

REM 启动 Claude Code（跳过登录模式）
echo 正在启动 Claude Code（使用 API Key 认证）...
echo.

npx @anthropic-ai/claude-code --bare

pause
