@echo off
REM 快速启动 Claude Code

echo ========================================
echo Claude Code 启动器
echo ========================================
echo.

REM 检查 API Key
if not exist "api_key.txt" (
    echo 错误：请先在 api_key.txt 文件中输入你的 API Key
    pause
    exit /b
)

set /p USER_API_KEY=<api_key.txt

if "%USER_API_KEY%"=="" (
    echo 错误：API Key 不能为空！
    echo 请在 api_key.txt 文件中输入你的 API Key
    pause
    exit /b
)

if "%USER_API_KEY%"=="YOUR_API_KEY_HERE" (
    echo 错误：请在 api_key.txt 文件中替换 YOUR_API_KEY_HERE 为你的实际 API Key
    pause
    exit /b
)

echo [1/3] 创建 LiteLLM 配置文件...
(
echo model_list:
echo   - model_name: deepseek-v3
echo     litellm_params:
echo       model: openai/deepseek-v3.2
echo       api_key: "%USER_API_KEY%"
echo       api_base: "https://api.edgefn.net/v1"
) > litellm_config_edgefn.yaml

echo LiteLLM 配置已创建
echo.

echo [2/3] 启动 LiteLLM 代理...
start cmd /k "litellm --config litellm_config_edgefn.yaml"

echo 等待 LiteLLM 启动（15秒）...
timeout /t 15 /nobreak > nul
echo.

echo [3/3] 启动 Claude Code...
echo.

set ANTHROPIC_BASE_URL=http://localhost:4000
set ANTHROPIC_AUTH_TOKEN=anything
set ANTHROPIC_API_KEY=

npx @anthropic-ai/claude-code --model deepseek-v3

pause
