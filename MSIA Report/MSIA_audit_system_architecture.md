# MSIA 审核管理系统架构设计

## 1. 架构概述

该系统采用典型的三层架构：
- 前端：浏览器单页应用（SPA）
- 后端：RESTful API 服务
- 数据层：关系型数据库与文件存储

目标是确保审核数据、问题闭环、报告导出、通知功能的可维护性、可扩展性和安全性。 

## 2. 组件设计

### 2.1 前端组件

#### 技术建议
- 框架：React / Vue / Angular
- UI 框架：Ant Design / Element Plus / MUI
- 状态管理：Redux / Pinia / Vuex
- PDF 导出：jsPDF / pdfmake / html2canvas
- 路由：React Router / Vue Router

#### 模块
- 登录页面
- 仪表盘
- 项目列表与项目详情
- 阶段审核页面
- 检查项评分页
- Issue 管理页
- Record 汇总页
- 报表导出页
- 系统消息中心

### 2.2 后端组件

#### 技术建议
- Node.js + Express / NestJS
- Python Django / Flask
- .NET Core

#### 模块
- 认证授权模块
- 项目管理模块
- 阶段管理模块
- 审核标准与检查项模块
- 审核记录模块
- Issue 闭环模块
- Report/Record 导出模块
- 通知与邮件模块
- 文件上传模块

### 2.3 数据层

#### 建议数据库
- MySQL
- PostgreSQL
- SQL Server

#### 附件存储
- 文件系统存储
- 对象存储（S3 兼容）
- 数据库存储路径 + 元数据

### 2.4 通知层

- 系统消息存储于数据库
- 邮件发送使用 SMTP / Exchange
- 未来可扩展为企业微信 / 钉钉 / OA

## 3. 数据流与交互

### 3.1 审核执行数据流

1. Reviewer 访问阶段审核页
2. 前端请求后端 `GET /api/phases/{id}/check-items`
3. 后端返回阶段检查项与当前评分状态
4. Reviewer 提交评分：`POST /api/reviews`
5. 后端保存评分记录，更新阶段完成率与得分
6. 若需要创建 Issue，Lead Reviewer 调用 `POST /api/issues`
7. 系统发送通知与邮件

### 3.2 Issue 闭环数据流

1. Lead Reviewer 创建 Issue
2. 后端保存 Issue，状态 `Open`
3. 通知责任人
4. 责任人提交整改证据：`PUT /api/issues/{id}`
5. 状态改为 `Pending Verification`
6. Lead Reviewer 验证并关闭 Issue：`PATCH /api/issues/{id}/status`
7. Record 自动汇总更新

### 3.3 报告与导出数据流

1. 用户选择导出阶段报告
2. 前端调用 `GET /api/projects/{projectId}/export/report/{phaseCode}?format=pdf`
3. 后端读取项目、阶段、审核项、Issue 状态
4. 生成 PDF 并返回下载链接

## 4. 模块详细设计

### 4.1 项目管理模块

功能：
- 创建/编辑/删除项目
- 管理项目阶段
- 维护项目 Key Data
- 控制项目可见性

API：
- `GET /api/projects`
- `POST /api/projects`
- `PUT /api/projects/{id}`
- `GET /api/projects/{id}/phases`

### 4.2 审核标准库模块

功能：
- 管理检查项与评分规则
- 支持阶段内检查项绑定
- 支持 Key Item 和评审角色标注
- 支持评分选项配置

API：
- `GET /api/check-items?phase=MSIA1`
- `POST /api/check-items`
- `PUT /api/check-items/{id}`

### 4.3 审核执行模块

功能：
- 记录评分与评论
- 限制评分值
- 计算阶段得分
- 保存 Evidence 附件

API：
- `GET /api/phases/{phaseId}/reviews`
- `POST /api/reviews`
- `PUT /api/reviews/{id}`

### 4.4 Issue 闭环模块

功能：
- 创建设计问题单
- 责任人分配与整改
- 状态流转与验证
- 超期预警

API：
- `GET /api/issues`
- `POST /api/issues`
- `PATCH /api/issues/{id}/status`
- `POST /api/issues/{id}/verify`

### 4.5 报告导出模块

功能：
- 生成阶段 Report PDF
- 生成 Record 汇总
- 支持 Excel/CSV 导出

API：
- `GET /api/projects/{projectId}/report/{phaseCode}`
- `GET /api/projects/{projectId}/export/record?format=excel`

### 4.6 通知模块

功能：
- 记录系统消息
- 标记已读
- 邮件发送与模板

API：
- `GET /api/notifications`
- `PATCH /api/notifications/{id}`
- `POST /api/notifications/mark-read`

## 5. 权限与安全设计

### 5.1 用户角色

- Lead Reviewer
- Reviewer
- Reviewee
- Admin（建议用于系统运维与角色管理）

### 5.2 访问控制

- 基于角色控制 API 访问
- 项目数据权限：
  - 仅可查看参与项目或被分配项目的用户
  - 仅 Lead Reviewer 可创建 Issue 并关闭
  - Reviewee 仅可查看 Issue 并提交整改

### 5.3 审计与日志

- 保存关键操作日志：登录、项目创建、阶段确认、Issue 状态变更、导出报告
- 日志可用于审计和问题排查

## 6. 部署建议

### 6.1 环境规划

- 开发环境
- 测试环境
- 生产环境

### 6.2 部署方式

- 采用内网 Web 应用部署
- 支持 HTTPS
- 若有企业 AD/SSO，可后续升级

### 6.3 备份与容灾

- 数据库定期备份
- 附件文件存储备份
- 邮件通知服务可配置重试机制

## 7. 可扩展性与后续迭代

### 7.1 审核标准版本管理

- 支持检查项版本控制
- 支持为新项目选择标准版本

### 7.2 外部系统对接

- 邮件系统
- OA / IPD 系统
- 未来可扩展与 OIL 系统同步

### 7.3 数据导入功能

- 支持历史 Excel 数据导入
- 支持项目、阶段、评分、Issue 数据批量导入

## 8. 备用方案与技术选型

### 8.1 若优先快速交付

- 前端：React + Ant Design
- 后端：Node.js + Express
- 数据库：MySQL
- 报告：后端生成 PDF

### 8.2 若需要企业级可维护性

- 前端：Vue 3 + Element Plus
- 后端：NestJS / Django
- 数据库：PostgreSQL
- 通知：SMTP / 企业邮箱

---

> 本架构文档与前述需求文档配套，可作为后续开发与评审的基础依据。