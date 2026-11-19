# Claude Code + DeepSeek 配置指南

## 步骤 1：获取 DeepSeek API Key

1. 访问 [DeepSeek Platform](https://platform.deepseek.com/)
2. 注册并登录账号
3. 在 "API Keys" 页面创建新的 API Key
4. 复制并保存你的 API Key（请妥善保管，不要泄露）

## 步骤 2：安装 LiteLLM（以管理员身份运行）

在 PowerShell 或 CMD 中以管理员身份运行以下命令：

```bash
# 如果有权限问题，使用 --user 参数
pip install --user litellm

# 或者使用 conda
conda install litellm -c conda-forge
```

## 步骤 3：创建 LiteLLM 配置文件

在工作目录创建文件 `litellm_config.yaml`：

```yaml
model_list:
  - model_name: deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat-v3-0324
      api_key: "your-deepseek-api-key-here"
      api_base: "https://api.deepseek.com"
```

**重要**：将 `your-deepseek-api-key-here` 替换为你实际的 DeepSeek API Key。

## 步骤 4：启动 LiteLLM 代理

在终端中运行：

```bash
litellm
```

LiteLLM 将在 `http://localhost:4000` 启动代理服务。

## 步骤 5：配置 Claude Code 环境变量

打开一个新的终端窗口，设置环境变量：

```bash
# Windows PowerShell
$env:ANTHROPIC_BASE_URL = "http://localhost:4000"
$env:ANTHROPIC_AUTH_TOKEN = "anything"
$env:ANTHROPIC_API_KEY = ""

# 或者在 Windows CMD
set ANTHROPIC_BASE_URL=http://localhost:4000
set ANTHROPIC_AUTH_TOKEN=anything
set ANTHROPIC_API_KEY=
```

## 步骤 6：运行 Claude Code

```bash
npx @anthropic-ai/claude-code --model deepseek-chat
```

## 快速启动脚本

创建一个批处理文件 `start-claude-deepseek.bat`：

```batch
@echo off
echo Starting LiteLLM Proxy...
start cmd /k "litellm"

echo Waiting for LiteLLM to start...
timeout /t 5 /nobreak > nul

echo Configuring Claude Code to use DeepSeek via LiteLLM...
set ANTHROPIC_BASE_URL=http://localhost:4000
set ANTHROPIC_AUTH_TOKEN=anything
set ANTHROPIC_API_KEY=

echo Starting Claude Code...
npx @anthropic-ai/claude-code --model deepseek-chat
```

## 注意事项

- Claude Code 主要针对 Claude 模型优化，使用 DeepSeek 可能功能受限
- 部分工具调用功能可能在非 Claude 模型上表现不佳
- 建议先测试基础功能，再逐步使用高级功能
- 确保 LiteLLM 代理保持运行状态

## 故障排除

1. **连接错误**：确保 LiteLLM 正在运行且端口 4000 未被占用
2. **API 错误**：检查 DeepSeek API Key 是否正确
3. **模型不支持**：尝试不同的 DeepSeek 模型（如 deepseek-coder）

## 获取帮助

- LiteLLM 文档：https://docs.litellm.ai/
- DeepSeek API 文档：https://platform.deepseek.com/docs
- Claude Code 文档：https://docs.claude.com/
