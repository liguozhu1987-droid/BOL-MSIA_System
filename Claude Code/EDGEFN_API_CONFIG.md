# Claude Code + EdgeFn (DeepSeek) API 配置指南

## API 信息

- **API 端点**: https://api.edgefn.net/v1
- **模型**: DeepSeek-V3.2
- **认证方式**: Bearer Token

## 配置方法

### 方式一：使用 LiteLLM 代理（推荐）

由于 Claude Code 原生使用 Anthropic API，而 EdgeFn 使用 OpenAI 兼容格式，建议使用 LiteLLM 作为中间代理。

#### 步骤 1：创建 LiteLLM 配置文件 `litellm_config_edgefn.yaml`

```yaml
model_list:
  - model_name: deepseek-v3
    litellm_params:
      model: openai/deepseek-v3.2
      api_key: "YOUR_API_KEY_HERE"
      api_base: "https://api.edgefn.net/v1"
```

**重要**：将 `YOUR_API_KEY_HERE` 替换为你从 EdgeFn 获取的实际 API Key。

#### 步骤 2：启动 LiteLLM

```bash
litellm --config litellm_config_edgefn.yaml
```

#### 步骤 3：配置 Claude Code 环境变量

```bash
export ANTHROPIC_BASE_URL="http://localhost:4000"
export ANTHROPIC_AUTH_TOKEN="anything"
export ANTHROPIC_API_KEY=""
```

#### 步骤 4：启动 Claude Code

```bash
npx @anthropic-ai/claude-code --model deepseek-v3
```

---

### 方式二：直接配置环境变量

如果你想直接连接（可能不支持所有功能）：

```bash
# 设置 API 端点
export ANTHROPIC_BASE_URL="https://api.edgefn.net/v1"

# 设置你的 API Key（Bearer Token）
export ANTHROPIC_AUTH_TOKEN="YOUR_API_KEY_HERE"

# 清空原有 API Key
export ANTHROPIC_API_KEY=""
```

然后运行：
```bash
npx @anthropic-ai/claude-code
```

---

## 获取 API Key 的位置

根据你提供的示例代码，EdgeFn API 使用 **Authorization Bearer Token** 认证方式：

```python
headers = {
    "Authorization": "Bearer {YOUR_API_KEY}",
    "Content-Type": "application/json"
}
```

**在哪里输入密钥**：

1. **方式一**：在配置文件中输入
   - 打开 `litellm_config_edgefn.yaml` 文件
   - 将 `"YOUR_API_KEY_HERE"` 替换为你的实际 API Key

2. **方式二**：通过环境变量设置
   ```bash
   export ANTHROPIC_AUTH_TOKEN="你的实际API密钥"
   ```

3. **方式三**：创建环境配置文件 `.env`
   ```bash
   EDGEFN_API_KEY=你的实际API密钥
   ```

## 快速启动脚本

我已创建 `start-claude-edgefn.bat`，使用步骤：

1. 双击运行 `start-claude-edgefn.bat`
2. 输入你的 EdgeFn API Key
3. 等待 LiteLLM 启动
4. Claude Code 将自动启动

## 测试连接

安装配置完成后，可以运行以下命令测试：

```bash
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer anything" \
  -d '{
    "model": "deepseek-v3",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## 注意事项

- Claude Code 主要针对 Claude 模型优化
- DeepSeek 模型可能不支持部分 Claude Code 高级功能
- 建议先测试基础功能（读取文件、执行命令等）
- 确保 API Key 安全，不要泄露给他人
