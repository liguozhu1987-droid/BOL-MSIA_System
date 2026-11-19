# MSIA 审核管理系统 API 设计

## 1. 认证与用户

### POST /api/auth/login
请求体:
```json
{
  "username": "string",
  "password": "string"
}
```
响应:
```json
{
  "token": "string",
  "user": {
    "id": 1,
    "username": "user1",
    "display_name": "张三",
    "email": "user@example.com",
    "role": "lead_reviewer"
  }
}
```

### POST /api/auth/logout
响应:
```json
{ "success": true }
```

### GET /api/auth/me
响应:
```json
{
  "id": 1,
  "username": "user1",
  "display_name": "张三",
  "email": "user@example.com",
  "role": "lead_reviewer",
  "department": "CoE"
}
```

### GET /api/users
查询参数: `role`, `department`
响应:
```json
[ { "id": 1, "username": "user1", "display_name": "张三", "role": "reviewer" } ]
```

### GET /api/users/{id}
响应:
```json
{ "id": 1, "username": "user1", "display_name": "张三", "email": "user@example.com", "role": "reviewer" }
```

## 2. 项目管理

### GET /api/projects
查询参数: `status`, `project_code`, `name`
响应:
```json
[
  {
    "id": 1,
    "name": "Project A",
    "code": "PA-001",
    "type": "Retooling",
    "status": "in_progress",
    "cmc_ame": "AME1",
    "plant_me": "Plant1",
    "score": 87.5
  }
]
```

### POST /api/projects
请求体:
```json
{
  "name": "Project A",
  "code": "PA-001",
  "type": "Retooling",
  "cmc_ame": "AME1",
  "plant_me": "Plant1",
  "inalfa_kickoff": "2026-08-01",
  "supplier_kickoff": "2026-08-15",
  "design_freeze": "2026-09-01",
  "pvp": "PVP1",
  "inalfa_sop": "SOP1"
}
```
响应:
```json
{ "id": 1 }
```

### GET /api/projects/{id}
响应:
```json
{
  "id": 1,
  "name": "Project A",
  "code": "PA-001",
  "type": "Retooling",
  "cmc_ame": "AME1",
  "plant_me": "Plant1",
  "status": "in_progress",
  "phases": [ ... ]
}
```

### PUT /api/projects/{id}
请求体类似 POST
响应:
```json
{ "success": true }
```

## 3. 阶段管理

### GET /api/projects/{projectId}/phases
响应:
```json
[
  { "id": 1, "project_id": 1, "code": "MSIA1", "name": "MSIA1", "status": "pending", "score": 0 },
  ...
]
```

### GET /api/phases/{id}
响应:
```json
{
  "id": 1,
  "project_id": 1,
  "code": "MSIA1",
  "name": "MSIA1",
  "timing_description": "2 weeks before Gate B",
  "main_targets": "Ensure ...",
  "status": "in_progress",
  "score": 75.0
}
```

### PUT /api/phases/{id}
请求体:
```json
{ "status": "completed", "score": 88.5 }
```
响应:
```json
{ "success": true }
```

### POST /api/phases/{id}/confirm
请求体:
```json
{ "confirmed_by": 1, "comments": "Phase review confirmed." }
```
响应:
```json
{ "success": true }
```

## 4. 审核标准库

### GET /api/check-items
查询参数: `phase_code`, `reviewer_role`, `is_key_item`
响应:
```json
[
  {
    "id": 1,
    "phase_code": "MSIA1",
    "item_no": "1.1",
    "name": "PM project timing plan",
    "request": "...",
    "is_key_item": false,
    "reviewer_roles": ["CoE"],
    "reference_documents": "PM Master timing plan V8",
    "score_scale_type": "5-step",
    "score_options": [0, 0.25, 0.5, 0.75, 1]
  }
]
```

### GET /api/check-items/{id}
响应同上

### POST /api/check-items
请求体:
```json
{
  "phase_code": "MSIA1",
  "item_no": "1.10",
  "name": "New check item",
  "request": "...",
  "is_key_item": true,
  "reviewer_roles": ["IE"],
  "reference_documents": "Template X",
  "score_scale_type": "4-step",
  "score_options": [0, 0.33, 0.67, 1]
}
```
响应:
```json
{ "id": 101 }
```

### PUT /api/check-items/{id}
请求体同上

### DELETE /api/check-items/{id}
响应:
```json
{ "success": true }
```

## 5. 审核记录

### GET /api/projects/{projectId}/reviews
响应:
```json
[
  {
    "id": 1,
    "project_id": 1,
    "phase_id": 1,
    "item_id": 1,
    "reviewer_id": 2,
    "score": 0.75,
    "comments": "Needs improvement",
    "evidence_urls": ["/files/abc.pdf"],
    "status": "submitted"
  }
]
```

### GET /api/phases/{phaseId}/reviews
同上

### POST /api/reviews
请求体:
```json
{
  "project_id": 1,
  "phase_id": 1,
  "item_id": 1,
  "reviewer_id": 2,
  "score": 0.75,
  "comments": "Needs improvement",
  "evidence_urls": ["/files/abc.pdf"],
  "status": "submitted"
}
```
响应:
```json
{ "id": 1001 }
```

### PUT /api/reviews/{id}
请求体:
```json
{ "score": 1, "comments": "Confirmed", "status": "confirmed" }
```

### DELETE /api/reviews/{id}
响应:
```json
{ "success": true }
```

## 6. Issue 管理

### GET /api/issues
查询参数: `project_id`, `phase_id`, `status`, `owner_user_id`
响应:
```json
[
  {
    "id": 1,
    "project_id": 1,
    "phase_id": 1,
    "item_id": 1,
    "title": "PM timing plan incomplete",
    "description": "Milestones unclear",
    "owner_user_id": 3,
    "priority": "High",
    "due_date": "2026-08-15",
    "status": "Open",
    "closing_status": null,
    "remarks": "",
    "evidence_urls": ["/files/issue-1.pdf"]
  }
]
```

### GET /api/issues/{id}
响应同上

### POST /api/issues
请求体:
```json
{
  "project_id": 1,
  "phase_id": 1,
  "item_id": 1,
  "title": "PM timing plan incomplete",
  "description": "Milestones unclear",
  "owner_user_id": 3,
  "owner_department": "Plant ME",
  "priority": "High",
  "due_date": "2026-08-15",
  "status": "Open",
  "remarks": "",
  "evidence_urls": ["/files/issue-1.pdf"]
}
```
响应:
```json
{ "id": 5001 }
```

### PUT /api/issues/{id}
请求体:
```json
{
  "owner_user_id": 3,
  "priority": "High",
  "due_date": "2026-08-20",
  "remarks": "Updated deadline",
  "evidence_urls": ["/files/issue-1-update.pdf"]
}
```

### PATCH /api/issues/{id}/status
请求体:
```json
{ "status": "Pending Verification", "verification_comments": "整改已提交，请验证" }
```

### POST /api/issues/{id}/verify
请求体:
```json
{ "verified_by": 1, "verified": true, "closing_status": "Closed", "remarks": "Verified and closed" }
```

## 7. 报告与导出

### GET /api/projects/{projectId}/record
响应:
```json
[
  {
    "msia_code": "MSIA1",
    "item_name": "PM project timing plan",
    "request": "PM project timing plan",
    "result": "Reviewed",
    "comments": "OK",
    "issue_due_date": "2026-08-15",
    "issue_status": "Open",
    "remarks": "Needs update"
  }
]
```

### GET /api/projects/{projectId}/report/{phaseCode}
响应:
```json
{
  "project": { ... },
  "phase": { ... },
  "items": [ ... ],
  "high_risk_comments": "..."
}
```

### GET /api/projects/{projectId}/export/report/{phaseCode}?format=pdf
响应: PDF 文件流 / 下载链接

### GET /api/projects/{projectId}/export/record?format=excel
响应: Excel 文件流 / 下载链接

## 8. 通知

### GET /api/notifications
响应:
```json
[
  { "id": 1, "title": "Issue assigned", "content": "Issue #5001 assigned to you.", "status": "Unread", "link": "/issues/5001" }
]
```

### PATCH /api/notifications/{id}
请求体:
```json
{ "status": "Read" }
```

### POST /api/notifications/mark-read
请求体:
```json
{ "ids": [1,2,3] }
```

## 9. 附件上传

### POST /api/uploads
请求: `multipart/form-data`
字段: `file`
响应:
```json
{ "url": "/uploads/abc123.pdf", "filename": "abc123.pdf" }
```

### GET /api/uploads/{id}
响应: 文件下载

## 10. 权限检查

所有 API 均应经过权限验证：
- 只有 `Lead Reviewer` 可创建/关闭 Issue、确认阶段
- `Reviewer` 可填写审核记录并查看相关项目
- `Reviewee` 可查看项目状态、查看 Issue、提交整改证据
- 管理员可管理用户与标准库
