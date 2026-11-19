# Claude Code + DeepSeek 配置指南

## 方法一：使用 LiteLLM 代理（推荐）

LiteLLM 可以将 OpenAI 格式的 DeepSeek API 转换为 Claude Code 可用的格式。

### 第一步：安装和配置 LiteLLM

1. 安装 LiteLLM：
```bash
npm install -g litellm
```

2. 创建配置文件 `litellm_config.yaml`：
```yaml
model_list:
  - model_name: deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat-v3-0324
      api_key: "your-deepseek-api-key"
      api_base: "https://api.deepseek.com"
```

3. 启动 LiteLLM 代理（默认在 http://localhost:4000）：
```bash
litellm
```

### 第二步：配置 Claude Code

在终端中设置环境变量：
```bash
export ANTHROPIC_BASE_URL="http://localhost:4000"
export ANTHROPIC_AUTH_TOKEN="anything"
export ANTHROPIC_API_KEY=""
```

### 第三步：运行 Claude Code
```bash
claude --model deepseek-chat
```

---

## 方法二：直接使用环境变量（如果 API 支持）

如果你的 DeepSeek API 端点支持 Anthropic 兼容格式：

```bash
export ANTHROPIC_BASE_URL="https://api.deepseek.com/v1"
export ANTHROPIC_AUTH_TOKEN="your-deepseek-api-key"
export ANTHROPIC_API_KEY=""
```

然后运行 Claude Code。

---

## 获取 DeepSeek API Key

1. 访问 [DeepSeek Platform](https://platform.deepseek.com/)
2. 注册并登录
3. 在 API Keys 页面创建新的 API Key
4. 将 API Key 填入配置文件

---

## 注意事项

- Claude Code 主要针对 Claude 模型优化，使用其他模型可能功能受限
- 部分工具调用功能可能在非 Claude 模型上表现不佳
- 建议先测试基础功能，再逐步使用高级功能
