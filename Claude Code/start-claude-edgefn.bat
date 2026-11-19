@echo off
REM Claude Code + EdgeFn API 快速启动脚本

echo ========================================
echo Claude Code + EdgeFn (DeepSeek) 配置工具
echo ========================================
echo.

REM 检查是否有 EdgeFn API Key
set /p API_KEY="请输入你的 EdgeFn API Key: "

if "%API_KEY%"=="" (
    echo 错误：API Key 不能为空！
    echo 请从 EdgeFn 平台获取 API Key
    pause
    exit /b 1
)

REM 创建 LiteLLM 配置文件
echo.
echo 创建 LiteLLM 配置文件...
(
echo model_list:
echo   - model_name: deepseek-v3
echo     litellm_params:
echo       model: openai/deepseek-v3.2
echo       api_key: "%API_KEY%"
echo       api_base: "https://api.edgefn.net/v1"
) > litellm_config_edgefn.yaml

echo.
echo LiteLLM 配置文件已创建：litellm_config_edgefn.yaml
echo.

REM 检查 LiteLLM 是否已安装
echo 检查 LiteLLM 安装状态...
pip show litellm >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo 警告：LiteLLM 未安装！
    echo 请以管理员身份运行以下命令安装：
    echo   pip install --user litellm
    echo.
    set /p CONTINUE="是否继续？(y/n): "
    if /i not "%CONTINUE%"=="y" exit /b
)

REM 启动 LiteLLM
echo.
echo 启动 LiteLLM 代理...
echo 请在新窗口中等待看到 "Uvicorn running on http://0.0.0.0:4000"
start cmd /k "litellm --config litellm_config_edgefn.yaml"

echo.
echo ========================================
echo 重要：请在新窗口中确认 LiteLLM 已成功启动
echo 应该显示：Uvicorn running on http://0.0.0.0:4000
echo ========================================
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
echo.
echo ========================================
echo 使用说明：
echo - Claude Code 将使用 DeepSeek-V3.2 模型
echo - 所有请求通过 LiteLLM 代理转发到 EdgeFn API
echo - 如果遇到问题，检查 LiteLLM 窗口是否有错误
echo ========================================
echo.

npx @anthropic-ai/claude-code --model deepseek-v3

pause
