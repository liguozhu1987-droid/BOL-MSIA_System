# MSIA 审核管理系统需求与系统设计

## 1. 项目目标

构建一个基于浏览器访问的 `MSIA 审核管理系统`，目标是：

- 将 `MSIA Checklist` 中的审核标准、检查项、评分标准和参考文档数字化管理
- 支持五阶段审核执行：`MSIA1`、`MSIA2`、`MSIA3`、`MSIA4`、`MSIA5`
- 支持审核问题的发现、记录、跟踪与闭环管理
- 支持自动或半自动生成审核报告与 `Record` 汇总
- 提供系统内消息和邮件提醒功能
- 支持与现有邮件系统对接

## 2. 设计范围

### 2.1 包含内容

- 审核标准库：检查项、评分规则、参考标准、所属阶段、评审角色
- 评审执行：按阶段审核、选择评分、填写评论、上传证据
- 问题闭环：问题创建、责任分配、整改、验证、关闭
- 报告输出：标准 PDF Report、汇总 Record、阶段凭证导出
- 用户与权限：Lead Reviewer / Reviewer / Reviewee
- 通知机制：系统消息 + 邮件提醒

### 2.2 不包含内容

- PM 参与审核操作
- 移动端 App（仅浏览器访问）
- 外部 OIL 系统双向同步（可作为后续扩展需求）

## 3. 关键需求

### 3.1 用户角色及权限

| 角色 | 描述 | 权限 |
|---|---|---|
| Lead Reviewer | 审核主导者 | 创建项目、分配 Reviewer、审核完成、手动生成 Issue、验证关闭、导出报告、查看全部数据 |
| Reviewer | 评审执行者（CoE/IE/EOL/CE） | 执行阶段审核、填写评分、上传证据、提交 Review、查看负责人分配问题 |
| Reviewee | 被审核方 | 查看本项目审核结果、查看/响应 Issue、上传整改证据 |

### 3.2 项目管理

- 支持创建审核项目
- 项目基本信息：项目名称、项目编号、项目类型、CMC AME、Plant ME、Inalfa kick-off、Supplier kick-off、Design freeze、PVP、Inalfa SOP 等
- 每个项目可关联 5 个阶段 `MSIA1~MSIA5`
- 支持项目状态管理：`未开始`、`进行中`、`已完成`

### 3.3 审核标准库

- 按阶段存储检查项（Examples：1.1 PM project timing plan、1.2 AME process development timing plan、1.3 DFA (MAA) 等）
- 对应字段：
  - `阶段`：MSIA1 / MSIA2 / MSIA3 / MSIA4 / MSIA5
  - `编号`：如 1.1、1.2、2.1、2.2 等
  - `检查项名称`
  - `Request / Request Description`
  - `Key Item` 标识
  - `评审角色`：CoE / IE / EOL / CE / etc.
  - `参考标准`：文档引用、模板名称
  - `成熟度评分标准`
- 评分标准类型由检查项决定，系统严格按检查项关联的评分制限定可选值，常见类型包括：
  - 5-step：`0 / 0.25 / 0.5 / 0.75 / 1`
  - 4-step：`0 / 0.33 / 0.67 / 1`
  - 3-step：`0 / 0.5 / 1`
- 每个检查项存储 `满分说明`、`各分值定义`

### 3.4 审核执行

- 按阶段创建审核执行记录
- 每个阶段展示该阶段所有检查项及其状态
- Reviewer 在单条检查项上填写：
  - `评分`（从该检查项允许的评分值中选择）
  - `Comments`
  - `Evidence`（附件：图片、文档）
- 系统自动计算阶段得分：
  - 当前阶段已评分项得分 / 该阶段总项数
  - 支持计算阶段成熟度评分
- 对于关键项 `Key Item`，可在 UI 中高亮显示
- 审核完成后，Lead Reviewer 可执行“审核提交”或“阶段确认”操作

### 3.5 问题管理与闭环

#### 3.5.1 问题生成规则

- 评分不满分时，不自动生成 Issue
- 由 `Lead Reviewer` 针对任意检查项手动生成问题单
- 关键项未得满分时，支持自动建议生成高优先级 Issue

#### 3.5.2 Issue 结构

- `Issue ID`
- `所属项目`
- `所属阶段`
- `关联检查项`
- `问题描述`
- `责任部门/责任人`
- `整改截止日期`
- `当前状态`：`Open`、`In Progress`、`Pending Verification`、`Closed`
- `优先级`：可选 `High` / `Medium` / `Low`
- `创建者`
- `整改证据`
- `验证结果`
- `Issue Closing Status`
- `Remarks`
- `备注`

#### 3.5.3 问题状态流转

- `Open`：问题创建完成
- `In Progress`：整改责任人执行整改
- `Pending Verification`：整改提交后，等待 Lead Reviewer 验证
- `Closed`：Lead Reviewer 验证通过后关闭
- 状态变化时保留时间戳与操作人

#### 3.5.4 问题闭环规则

- `Reviewee` 或整改责任人提交整改证据，并可填写 `整改说明`
- `Lead Reviewer` 审核整改结果后，可选择 `通过` 或 `不通过`
- `通过` -> `Closed`
- `不通过` -> 继续 `In Progress`
- 系统自动根据截止日期生成超期预警

### 3.6 报告中心与输出

#### 3.6.1 Report

- 支持单阶段 `Report MSIA1~MSIA5` 输出
- PDF 导出仅包含 `Report MSIA<x>` 内容
- 报表样式尽量与 Excel 模板一致，包含：
  - 项目 Key Data
  - 阶段标题与 Timing
  - 审核结果和高风险备注
  - 每条检查项的已评估结果与Comments
- 允许导出标准格式 PDF，并支持 `PDF 模板/样式` 自定义

#### 3.6.2 Record 汇总

- 自动从各阶段 `Report` 汇总生成 `Record`
- 汇总字段至少包含：
  - `MSIA`
  - `Item`
  - `Request`
  - `Result`
  - `Comments`
  - `Issue Closing Dead Line`
  - `Issue Closing Status`
  - `Remarks`
- 实时自动汇总：当各阶段审核结果或问题状态变化时，Record 数据同步更新
- 可按项目导出 Excel/CSV

#### 3.6.3 仪表盘

- 项目审核进度
- 各阶段得分分布
- Issue 关闭率
- 超期问题数量
- 关键问题统计

### 3.7 通知与集成

- 系统内消息通知：
  - `Issue 创建`
  - `Issue 状态更新`
  - `整改提交`
  - `待验证`
  - `超期提醒`
- 邮件通知：
  - 发送给责任人和相关角色
  - 支持邮件内容模板
  - 支持抄送 Lead Reviewer
- 邮件系统集成建议：
  - 优先支持 SMTP/Exchange
  - 若已有企业邮箱网关，可对接当前邮件系统

## 4. 数据模型

### 4.1 实体定义

#### 4.1.1 Project

- project_id
- project_name
- project_code
- project_type
- cmc_ame
- plant_me
- inalfa_kickoff
- supplier_kickoff
- design_freeze
- pvp
- inalfa_sop
- status
- created_at
- updated_at

#### 4.1.2 Phase

- phase_id
- project_id
- phase_code (`MSIA1`, `MSIA2`, `MSIA3`, `MSIA4`, `MSIA5`)
- phase_name
- timing_description
- main_targets
- status
- score
- completed_at

#### 4.1.3 CheckItem

- item_id
- phase_code
- section_no (`1.1`, `1.2`, ...)
- name
- request
- is_key_item
- evaluator_roles
- reference_documents
- score_type (`5-step`, `4-step`, `3-step`)
- score_options (json)
- description
- remarks

#### 4.1.4 ReviewRecord

- review_id
- project_id
- phase_id
- item_id
- reviewer_id
- score
- comments
- evidence_urls
- created_at
- updated_at
- issue_id (optional)

#### 4.1.5 Issue

- issue_id
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
- evidence_urls
- verification_comments
- closing_status
- remarks
- created_by
- created_at
- updated_at

#### 4.1.6 User

- user_id
- name
- email
- role
- department
- active
- created_at
- updated_at

#### 4.1.7 Notification

- notification_id
- user_id
- type
- title
- content
- status (`Unread`, `Read`)
- created_at
- link_url

### 4.2 关系图

- Project 1:n Phase
- Phase 1:n ReviewRecord
- Phase 1:n Issue
- CheckItem 1:n ReviewRecord
- User 1:n ReviewRecord
- User 1:n Issue

## 5. 关键流程设计

### 5.1 项目与阶段创建

1. Lead Reviewer 创建项目并填写关键项目信息
2. 项目默认包含 5 个阶段
3. 每个阶段可设置 `Timing`、`Main targets`、`阶段状态`

### 5.2 审核执行流程

1. Reviewer 进入项目阶段
2. 从标准库选择检查项并执行评审
3. 对每条检查项填写 `评分`、`Comments`、`Evidence`
4. 系统自动汇总该阶段得分
5. Review 完成后，Lead Reviewer 审核阶段结果并确认

### 5.3 生成问题与闭环流程

1. Lead Reviewer 在阶段评审结果中选择“创建 Issue”
2. 指定责任人、整改截止日期、优先级等
3. Issue 状态从 `Open` 进入 `In Progress`
4. 整改责任人提交整改结果和证据
5. Lead Reviewer 将 Issue 标记 `Pending Verification`
6. Lead Reviewer 验证通过后关闭 Issue

### 5.4 报告输出流程

1. 审核阶段完成后，生成单阶段 `Report MSIA<x>`
2. 生成 `Record` 汇总表
3. 支持一键导出 `PDF Report MSIA<x>` 和 `Excel/CSV Record`

## 6. 报告与导出规范

### 6.1 PDF Report

- 单阶段 Report 支持 PDF 导出
- 导出内容包括：
  - 项目 Key Data
  - 阶段标题与 Timing
  - 审核结果、得分与高风险备注
  - 检查项列表、Result、Comments
- 支持导出时选择阶段或全部阶段

### 6.2 Record 汇总

- 自动从各阶段数据汇总
- 必须包含 `Issue Closing Dead Line`、`Issue Closing Status`、`Remarks`
- 支持 Excel/CSV 导出
- 支持按阶段和按 Issue 状态筛选导出

## 7. 系统架构与技术建议

### 7.1 推荐架构

- 前端：React / Vue / Angular 任一现代单页应用框架
- 后端：Node.js + Express / Python Django / Python Flask / .NET
- 数据存储：关系型数据库（MySQL、PostgreSQL、SQL Server）
- 文件存储：可本地存储文件、对象存储或数据库附件
- 消息：系统内消息 + 邮件服务

### 7.2 集成方案

- 邮件：SMTP / Exchange / 企业邮箱接口
- 如果后续需要，可扩展到 OA/IPD 系统、OIL 系统

### 7.3 安全与部署

- 采用登录认证，基于角色的访问控制
- 关键项目数据隔离：项目仅对参与者可见，或通过角色+项目权限控制
- 部署方式可先以内网 Web 应用方式实现，后续可迁移到云部署

## 8. 需求确认与待补充点

### 8.1 已确认点

- Web 系统
- 角色：Lead Reviewer / Reviewer / Reviewee
- PM 不参与操作
- 数据隔离可按项目/角色控制
- 评分严格按照检查项对应评分制
- 问题由 Lead Reviewer 手动生成
- 问题流转：`Open → In Progress → Pending Verification → Closed`
- Lead Reviewer 最终关闭 Issue
- 系统保留 `Issue Closing Dead Line` / `Issue Closing Status` / `Remarks`
- 通知方式：系统消息 + 邮件
- 支持一键导出 `PDF Report MSIA<x>`
- `Record` 自动汇总
- 支持邮件系统对接

### 8.2 需要进一步确认的点

- 是否需要额外角色：例如 `Admin`、`Manager`、`Plant ME 经理`、`AME 经理`
- 权限等级细化：是否需要 `仅查看` / `评审` / `审批` 更精细的权限
- 是否明确要求 `Project-level data isolation`：不同项目人员是否完全隔离
- 是否需要 `审核标准版本管理`（当前模板 Rev.F / 将来修订）
- 是否需要导入历史 Excel 审核数据
- 是否需要支持 `审核计划` 和 `阶段提醒` 功能

## 9. 下一步建议

1. 确认额外角色与权限体系
2. 确认数据隔离策略与项目可见性规则
3. 确定邮件系统对接方式（SMTP / Exchange / 企业邮箱 API）
4. 确定是否需要标准库版本管理与历史数据导入
5. 基于本设计，继续推进详细功能规格书与页面原型
