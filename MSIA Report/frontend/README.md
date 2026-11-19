# MSIA 审核管理系统（前端）

基于 React 18 + TypeScript + Vite + Ant Design 5 构建的 MSIA 审核管理系统前端骨架。

## 技术栈

- React 18 + TypeScript 5
- Vite 5（构建工具）
- Ant Design 5（UI 组件库）
- React Router 6（路由）
- Zustand（状态管理）
- Axios（HTTP 客户端）
- ECharts（图表）
- dayjs（日期处理）

## 设计风格

- 浅蓝简约科技风
- 主色：`#1677FF`
- 背景色：`#F5F7FA`
- 辅助蓝：`#E6F4FF`
- 缺失数据统一显示为空字符串，不使用占位默认值

## 目录结构

```
frontend/
├── src/
│   ├── api/            # 接口封装（client / auth / projects / issues / notifications）
│   ├── components/     # 通用组件（AuthRoute 鉴权路由）
│   ├── layouts/        # 布局（MainLayout 主框架）
│   ├── pages/          # 页面（Login / Dashboard / Projects 等）
│   ├── router/         # 路由配置
│   ├── store/          # Zustand 状态（auth）
│   ├── utils/          # 工具函数（format）
│   ├── App.tsx
│   ├── main.tsx
│   └── theme.ts        # Ant Design 主题
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

## 环境要求

- Node.js >= 18
- npm >= 9（或 pnpm / yarn）

## 安装依赖

```bash
npm install
```

## 开发模式启动

```bash
npm run dev
```

启动后默认访问地址：<http://localhost:5173>

开发环境下，所有 `/api` 请求会被代理转发到后端服务 `http://localhost:8000`。

## 构建生产包

```bash
npm run build
```

构建产物输出到 `dist/` 目录。

## 本地预览生产包

```bash
npm run preview
```

## 后端接口约定

所有接口前缀为 `/api`，需要在响应中返回如下结构（具体由后端实现）：

- `POST /api/auth/login`：登录，返回 `{ token, user }`
- `POST /api/auth/logout`：登出
- `GET /api/auth/me`：获取当前用户信息
- `GET /api/projects`：项目列表
- `GET /api/issues`：问题列表
- `GET /api/notifications`：通知列表

请求头会自动携带 `Authorization: Bearer <token>`，响应 401 时自动跳转登录页。
