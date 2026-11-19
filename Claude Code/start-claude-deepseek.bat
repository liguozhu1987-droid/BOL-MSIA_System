@echo off
REM Claude Code + DeepSeek 快速启动脚本

echo ========================================
echo Claude Code + DeepSeek 配置工具
echo ========================================
echo.

REM 检查是否有 DeepSeek API Key
set /p API_KEY="请输入你的 DeepSeek API Key: "

if "%API_KEY%"=="" (
    echo 错误：API Key 不能为空！
    echo 请访问 https://platform.deepseek.com/ 获取 API Key
    pause
    exit /b 1
)

REM 创建 LiteLLM 配置文件
echo.
echo 创建 LiteLLM 配置文件...
echo model_list: > litellm_config.yaml
echo   - model_name: deepseek-chat >> litellm_config.yaml
echo     litellm_params: >> litellm_config.yaml
echo       model: deepseek/deepseek-chat-v3-0324 >> litellm_config.yaml
echo       api_key: "%API_KEY%" >> litellm_config.yaml
echo       api_base: "https://api.deepseek.com" >> litellm_config.yaml

echo.
echo LiteLLM 配置文件已创建：litellm_config.yaml
echo.

REM 启动 LiteLLM
echo 启动 LiteLLM 代理...
echo 请在新窗口中等待看到 "Uvicorn running on http://0.0.0.0:4000"
start cmd /k "litellm --config litellm_config.yaml"

echo.
set /p READY="LiteLLM 是否已启动？(按 Enter 继续，或输入 q 退出): "

if "%READY%"=="q" exit /b

REM 配置环境变量并启动 Claude Code
echo.
echo 配置 Claude Code 环境变量...
set ANTHROPIC_BASE_URL=http://localhost:4000
set ANTHROPIC_AUTH_TOKEN=anything
set ANTHROPIC_API_KEY=

echo.
echo 启动 Claude Code...
npx @anthropic-ai/claude-code --model deepseek-chat
