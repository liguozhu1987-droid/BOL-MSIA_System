@echo off
REM Claude Code Router 启动脚本

echo ========================================
echo Claude Code Router 启动中...
echo ========================================
echo.

echo [配置]
echo   API 端点: https://api.edgefn.net/v1
echo   模型: DeepSeek-V3.2
echo   本地端口: 3456
echo.

echo 启动 CCR 服务...
npx claude-code-router

echo.
echo CCR 服务已启动
echo.
echo 现在可以运行 Claude Code：
echo   set ANTHROPIC_BASE_URL=http://localhost:3456
echo   npx @anthropic-ai/claude-code
echo.
pause
