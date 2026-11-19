# Claude Code Router (CCR) 安装配置指南

## 安装状态

✅ **已安装**: `@musistudio/claude-code-router` (本地安装)
⏳ **待启动**: CCR 服务

## 配置文件

已创建配置文件: `.claude-code-router/config.json`

```json
{
  "HOST": "0.0.0.0",
  "PORT": 3456,
  "API_KEY": "sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19",
  "BASE_URL": "https://api.edgefn.net/v1",
  "MODEL": "DeepSeek-V3.2"
}
```

## 启动步骤

### 第一步：启动 CCR 服务

在终端中运行：

```bash
npx claude-code-router
```

或者双击运行 `start-ccr.bat`

服务将在 `http://localhost:3456` 启动

### 第二步：配置 Claude Code

在另一个终端中设置环境变量：

```bash
set ANTHROPIC_BASE_URL=http://localhost:3456
set ANTHROPIC_AUTH_TOKEN=sk-RIfE7nc3oI4woVeTA8A24e80E15b4e4d8c516855123b5b19
set ANTHROPIC_API_KEY=
```

### 第三步：启动 Claude Code

```bash
npx @anthropic-ai/claude-code --bare --dangerously-skip-permissions
```

## 快速启动脚本

已创建 `start-ccr.bat`，双击即可启动 CCR 服务。

## 验证连接

启动后，CCR 会显示：
- 本地服务地址: http://localhost:3456
- 代理目标: https://api.edgefn.net/v1
- 使用模型: DeepSeek-V3.2

## 故障排除

1. **端口被占用**: 修改配置文件中的 PORT
2. **API Key 错误**: 检查 config.json 中的 API_KEY
3. **连接失败**: 检查网络连接和 API 服务状态

## 文件列表

- `.claude-code-router/config.json` - CCR 配置文件
- `start-ccr.bat` - CCR 启动脚本
- `CCR_SETUP.md` - 本说明文档
