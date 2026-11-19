# MSIA 审核管理系统详细功能规格与系统设计

## 1. 项目概述

本系统面向制造系统实施审核（MSIA）全生命周期管理，实现五阶段评审标准化、问题闭环管理、报告导出、系统内消息与邮件通知。

目标用户：
- Lead Reviewer
- Reviewer（CoE / IE / EOL / CE）
- Reviewee

核心目标：
- 审核标准结构化：从 Excel Checklist 转化为系统标准库
- 审核执行数字化：按阶段、按检查项评分与评论
- 问题闭环管理：Issue 创建、整改、验证、关闭
- 报告自动化：PDF Report、Record 汇总
- 通知提醒：系统消息 + 邮件

## 2. 关键业务流程

### 2.1 项目与阶段管理

#### 2.1.1 创建项目

- Lead Reviewer 创建项目，填写关键信息：
  - 项目名称、项目编号、项目类型
  - CMC AME、Plant ME
  - Inalfa kick-off、Supplier kick-off、Design freeze、PVP、Inalfa SOP
  - Project status（未开始 / 进行中 / 已完成）
- 系统自动生成 5 个阶段：MSIA1 ~ MSIA5
- 每阶段绑定默认审核标准库项

#### 2.1.2 阶段配置

- Lead Reviewer 可设置阶段状态、审核时间窗口、阶段负责人
- 每阶段显示：
  - 阶段名称
  - Timing 说明
  - Main targets
  - 当前得分
  - 审核执行进度

### 2.2 审核执行流程

#### 2.2.1 进入阶段

- Reviewer 打开阶段审核页面，系统展示该阶段所有检查项
- 支持筛选：
  - 关键项
  - 评审角色
  - 评分状态

#### 2.2.2 填写评审结果

每条检查项展示以下信息：
- 编号
- 检查项名称
- Request / Request Description
- Key Item 标识
- 评审角色
- 参考标准
- 可选评分值
- 评分说明

Reviewer 操作：
- 选择评分值（严格限定于该检查项的评分制）
- 填写 Comments
- 上传 Evidence（附件、图片、文件）
- 标记问题建议（可选，最终由 Lead Reviewer 决定是否建 Issue）

#### 2.2.3 阶段评分与提交

- 系统实时计算阶段得分，展示已评估项占比与平均得分
- Reviewer 提交阶段审核结果后，状态变更为“待 Lead Reviewer 审核”
- Lead Reviewer 可以复核并确认阶段结果

### 2.3 问题闭环管理

#### 2.3.1 问题创建

- Lead Reviewer 可针对任意检查项创建 Issue
- 建议系统将“不满分项”作为创建 Issue 的快速入口，但不自动生成
- 如果是关键项且评分 < 1.0，则系统提示“建议创建高优先级 Issue”

#### 2.3.2 Issue 必填字段

- Issue 标题
- 所属项目
- 所属阶段
- 关联检查项
- 问题描述
- 责任人 / 责任部门
- 整改截止日期
- 优先级
- 状态：Open / In Progress / Pending Verification / Closed
- Issue Closing Status
- Remarks
- 关联证据

#### 2.3.3 问题状态流转

- `Open`：问题建立
- `In Progress`：整改责任人执行整改并上传证据
- `Pending Verification`：整改提交后等待 Lead Reviewer 验证
- `Closed`：Lead Reviewer 验证通过

#### 2.3.4 关闭规则

- 责任人提交整改证据后，状态进入 `Pending Verification`
- Lead Reviewer 审核整改结果，可选择“通过/不通过”
- 通过后闭环，闭环时间、验证人、备注记录
- 不通过后返回 `In Progress`

### 2.4 报告与导出

#### 2.4.1 Report 生成

- 单阶段 `Report MSIA<x>` 由系统自动生成
- 报告包含：
  - 项目 Key Data
  - 阶段信息（Timing / Main targets）
  - 高风险评论
  - 检查项列表、Result、Comments
  - 已上传证据列表

#### 2.4.2 PDF 导出

- 一键导出标准格式 PDF
- 导出对象：单阶段 `Report MSIA<x>`
- 输出格式应尽量靠近 Excel 模板结构，包含数据与标题
- 导出时可选择单个阶段或多阶段合并导出（可选）

#### 2.4.3 Record 汇总

- 自动从各阶段审核结果、Issue 状态汇总生成 Record
- Record 字段：
  - MSIA
  - Item
  - Request
  - Result
  - Comments
  - Issue Closing Dead Line
  - Issue Closing Status
  - Remarks
- 当阶段结果或 Issue 状态变更时，Record 实时更新
- 支持导出 Excel / CSV

### 2.5 通知与邮件

- 事件触发：
  - Issue 创建
  - Issue 分配
  - Issue 状态更新
  - 整改提交
  - 待验证提醒
  - 超期提醒
- 通知方式：
  - 系统内消息
  - 邮件通知
- 邮件内容支持模板，内容包含：项目、Issue 编号、阶段、状态、截止日期、责任人
- 支持邮件抄送 Lead Reviewer

## 3. 页面的详细设计

### 3.1 登录页

- 用户邮箱 / 登录名
- 密码
- 忘记密码（若后续实现）

### 3.2 首页仪表盘

模块：
- 我的审核任务
- 项目进度概览
- 问题闭环状态
- 超期问题
- 阶段得分趋势

### 3.3 项目列表页

字段：
- 项目编号
- 项目名称
- 项目类型
- 阶段完成状态
- 当前得分
- 负责人
- 操作：查看 / 编辑 / 进入阶段 / 导出报告

### 3.4 项目详情页

包含：
- 项目 Key Data
- 5 个阶段卡片
- 各阶段当前得分与状态
- 快速入口：进入阶段、导出 Report、查看 Record

### 3.5 阶段审核页

结构：
- 阶段信息卡片
- 检查项表格
- 表格字段：编号 / 检查项 / Key Item / Request / 评分 / Comments / Evidence / 操作
- 支持批量评分、保存草稿
- 评分控件严格按照检查项评分制显示可选值
- 右侧状态面板：阶段得分、已评审数、待评审数、问题建议

### 3.6 Issue 管理页

字段：
- Issue ID
- 项目
- 阶段
- 关联检查项
- 标题
- 状态
- 责任人
- 优先级
- 截止日期
- 更新记录
- 操作：编辑 / 上传证据 / 提交整改 / 标记验证 / 关闭

### 3.7 Record 汇总页

内容：
- 自动汇总各阶段审核结果
- 筛选条件：项目、阶段、Issue 状态、关键项、责任人
- 列表字段与导出按钮

### 3.8 报表导出页

功能：
- 选择阶段 Report
- 选择导出格式：PDF / Excel / CSV
- 生成并下载

## 4. 数据模型详细定义

### 4.1 基础表

#### User

- id
- username
- display_name
- email
- role (`lead_reviewer`, `reviewer`, `reviewee`, `admin`)
- department
- status
- created_at
- updated_at

#### Project

- id
- name
- code
- type
- cmc_ame
- plant_me
- inalfa_kickoff
- supplier_kickoff
- design_freeze
- pvp
- inalfa_sop
- status
- created_by
- created_at
- updated_at

#### Phase

- id
- project_id
- code (`MSIA1`..`MSIA5`)
- name
- timing_description
- main_targets
- status
- score
- completed_at
- created_at
- updated_at

#### CheckItem

- id
- phase_code
- item_no
- name
- request
- is_key_item
- reviewer_roles
- reference_documents
- score_scale_type (`5-step`,`4-step`,`3-step`,`custom`)
- score_options (json)
- default_result_text
- remarks
- created_at
- updated_at

#### ReviewRecord

- id
- project_id
- phase_id
- item_id
- reviewer_id
- score
- comments
- evidence_urls (json)
- status (`draft`,`submitted`,`confirmed`)
- created_at
- updated_at

#### Issue

- id
- project_id
- phase_id
- item_id
- title
- description
- owner_user_id
- owner_department
- priority
- due_date
- status
- closing_status
- remarks
- evidence_urls (json)
- verification_comments
- created_by
- created_at
- updated_at

#### RecordEntry

- id
- project_id
- phase_id
- item_id
- msia_code
- item_name
- request
- result
- comments
- issue_due_date
- issue_status
- remarks
- created_at
- updated_at

#### Notification

- id
- user_id
- title
- content
- type
- status
- link
- created_at
- updated_at

### 4.2 关系说明

- `Project` 1:n `Phase`
- `Phase` 1:n `ReviewRecord`
- `Phase` 1:n `Issue`
- `CheckItem` 1:n `ReviewRecord`
- `CheckItem` 1:n `Issue`
- `User` 1:n `ReviewRecord`
- `User` 1:n `Issue`
- `Project` 1:n `RecordEntry`

## 5. API 设计与接口列表

### 5.1 认证与用户

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/users`
- `GET /api/users/{id}`

### 5.2 项目管理

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `PUT /api/projects/{id}`
- `DELETE /api/projects/{id}`

### 5.3 阶段管理

- `GET /api/projects/{projectId}/phases`
- `GET /api/phases/{id}`
- `PUT /api/phases/{id}`
- `POST /api/phases/{id}/confirm`

### 5.4 审核标准库

- `GET /api/check-items`
- `GET /api/check-items/{id}`
- `POST /api/check-items`
- `PUT /api/check-items/{id}`
- `DELETE /api/check-items/{id}`

### 5.5 审核记录

- `GET /api/projects/{projectId}/reviews`
- `GET /api/phases/{phaseId}/reviews`
- `POST /api/reviews`
- `PUT /api/reviews/{id}`
- `DELETE /api/reviews/{id}`

### 5.6 Issue 管理

- `GET /api/issues`
- `GET /api/issues/{id}`
- `POST /api/issues`
- `PUT /api/issues/{id}`
- `PATCH /api/issues/{id}/status`
- `POST /api/issues/{id}/verify`

### 5.7 报告与导出

- `GET /api/projects/{projectId}/record`
- `GET /api/projects/{projectId}/report/{phaseCode}`
- `GET /api/projects/{projectId}/export/report/{phaseCode}?format=pdf`
- `GET /api/projects/{projectId}/export/record?format=excel`

### 5.8 通知

- `GET /api/notifications`
- `PATCH /api/notifications/{id}`
- `POST /api/notifications/mark-read`

## 6. 报表与导出规则

### 6.1 Report MSIA 模板映射

根据 Excel 附件，单阶段 Report 结构包括：
- 项目 Key Data 区域
- MSIA No.
- Project name / Project No. / Project type
- Milestone 信息
- High-risk comments
- 检查项清单与 `Result` / `Comments`

### 6.2 Record 自动汇总规则

- `MSIA`：阶段编码
- `Item`：检查项名称
- `Request`：检查项要求
- `Result`：当前评审结果
- `Comments`：评审备注
- `Issue Closing Dead Line`：如果关联 Issue，则使用 Issue 最晚整改日期
- `Issue Closing Status`：Issue 当前状态
- `Remarks`：Lead Reviewer / Reviewee 可填写的说明字段

### 6.3 PDF 导出内容规范

- 保留 Stage 标题与页眉
- 显示项目关键信息
- 逐项展示检查项、评分、结果与备注
- 允许包含高风险评论区

## 7. 技术架构建议

### 7.1 前端

- React / Vue / Angular
- UI 框架建议：Ant Design / Element Plus / MUI
- 文件上传与预览组件
- 数据表格与筛选
- PDF 导出可用 `jsPDF` 或后端渲染

### 7.2 后端

- Node.js + Express / NestJS
- Python Django / Flask
- .NET Core
- 采用 REST API 设计
- 身份认证建议 JWT / Session
- 邮件服务接口支持 SMTP / Exchange

### 7.3 数据库

- MySQL / PostgreSQL / SQL Server
- 支持事务与关系约束
- 框架 ORM：Sequelize / TypeORM / SQLAlchemy / Entity Framework

### 7.4 文件存储

- 证据文件可存数据库路径或对象存储
- 附件单独存储，保持元数据

### 7.5 部署建议

- 初期可部署为内网 Web 应用
- 后续可迁移到云内网混合部署
- 支持 HTTPS
- 根据公司运维要求支持 AD/SSO（可扩展）

## 8. 非功能需求

### 8.1 可用性

- 系统易用、界面清晰
- 审核项、问题项可快速筛选
- 报告导出一键完成

### 8.2 性能

- 支持数十个项目、数百条审核项
- 查询、导出响应时间合理

### 8.3 安全

- 基于角色访问控制
- 项目数据按权限隔离
- 文件上传限类型与大小

### 8.4 可扩展性

- 支持后续新增阶段
- 支持审核标准版本管理
- 支持与企业邮箱、OA、IPD 系统对接

## 9. 需要确认的细节

- 是否要补充 `Admin` / `Manager` / `Plant ME 经理` / `AME 经理` 等角色
- 项目数据隔离是否要求“人员仅能看到自己参与的项目”
- 是否需要支持 `审核标准版本管理`
- 是否需要支持历史 Excel 数据导入
- 是否需要支持 `邮件模板编辑` 与 `抄送规则`

---

> 当前文档基于附件 `MSIA Checklist` 结构和您已确认的需求。若您同意，可继续推进：
> 1) 功能规格书细化 2) 页面原型 3) 开发迭代计划 4) 需求评审清单
