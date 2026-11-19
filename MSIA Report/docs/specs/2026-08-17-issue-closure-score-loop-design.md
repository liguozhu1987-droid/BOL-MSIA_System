# 设计文档: 问题关闭与评分闭环加固

> 日期: 2026-08-17
> 状态: 已批准
> 范围: 后端 issues/workbench/reviews/score_control_service + 前端 Issues 页面

## 1. 背景与漏洞清单

代码审计发现 4 个闭环漏洞, 全部经代码核实属实:

| # | 漏洞 | 根因位置 |
|---|-----|---------|
| 1 | 关闭快照只在审批关闭路径触发, 其他直接关闭路径绕过快照 | issues.py `update_issue_status` / `verify_issue` / `update_issue` 均直接写 `Status="closed"` 且不调用 `snapshot_score_at_closure` |
| 2 | `ScoreAfterUpdate` 只回填一次 (`is_(None)` 硬过滤), 后续修正评分被静默吞掉 | score_control_service.py `backfill_score_after_update` |
| 3 | 无重开/回退重审机制, closed 后评分字段残留旧数据, 语义混乱 | issue.py 状态枚举只有 4 个值, 无 closed→open/in_progress 处理 |
| 4 | 评分与关闭审批无并发保护, snapshot/backfill 时序可能错位 | reviews.py `create_review`/`update_review` 无行锁 |

**额外发现**: `IssueUpdate` schema 含 `Status` 字段, `PUT /api/issues/{id}` 是第 4 个隐藏关闭入口。

## 2. 设计决策 (用户已确认)

| 决策点 | 选择 |
|-------|------|
| 重开后评分字段处理 | **A. 清零重置法**: ScoreAtClosure / ScoreAfterUpdate / ScoreUpdatedAt 全部置 NULL, 审计追溯靠评论历史 |
| ScoreAfterUpdate 更新策略 | **A. 始终取最新评分**: 去掉 `is_(None)` 过滤, 无条件覆盖, ScoreUpdatedAt 同步刷新 |
| 并发保护 | **A. 统一行锁法**: service 层 `with_for_update()`, 与 approve_closure 锁粒度一致 |
| 关闭入口统一化 | **A. 统一服务层函数**: `close_issue_with_snapshot()` 封装关闭四件事, 所有入口一律调用 |

## 3. 核心改动

### 3.1 score_control_service.py

新增两个统一函数:

```python
close_issue_with_snapshot(db, issue, *, operator=None, verification_comments=None, closing_status=None)
    # 原子完成: Status=closed + ClosedAt + VerifiedBy/At(如有operator)
    #          + 快照评分 + 清理 ClosureRequestedAt/By

reopen_issue_and_reset_scores(db, issue)
    # 清零重置: Status=in_progress + ClosedAt=NULL + 三评分字段=NULL
    #          + ClosureRequested*/Verified* 全部清空
```

修改 `backfill_score_after_update`:
- 删除 `Issue.ScoreAfterUpdate.is_(None)` 过滤 → 覆盖式回填最新评分
- 查询加 `.with_for_update()` 行锁 (service 层统一并发保护)
- 保留 ScoreAtClosure 仅空时补全逻辑

### 3.2 issues.py (4 个状态入口统一)

| 入口 | 改造 |
|-----|------|
| `PATCH /{id}/status` | 行锁; →closed 走统一函数; closed→其他走重开函数 |
| `POST /{id}/verify` | 同上 |
| `PUT /{id}` | 检测 Status 变化: →closed 走统一函数; closed→其他走重开函数; Status 从 payload 中排除避免盲写 |
| `POST /{id}/reopen` (新增) | admin/lead_reviewer; 行锁; 校验 closed; Reason 必填记入评论; 通知责任人 |

### 3.3 workbench.py approve_closure

批准分支的手写关闭四步替换为 `close_issue_with_snapshot(db, issue, operator=current, ...)`, 通知逻辑不动。

### 3.4 前端

- `api/issues.ts`: 新增 `reopenIssue(id, reason)`
- `Issues.tsx`: 已关闭问题行操作列显示「重开」按钮 (admin/lead_reviewer), 弹窗必填原因

## 4. 时序安全分析

```
approve_closure:  锁 Issue → 读 ReviewRecord 快照 → commit
reviews 写入:     写 ReviewRecord → commit → 锁 Issue → 回填 → commit
```

两个事务锁请求顺序一致 (Issue 行锁为汇聚点), ReviewRecord INSERT 在 READ COMMITTED 下不阻塞快照 SELECT, 无死锁环。

## 5. 验收标准

1. 任一入口 (审批/状态PATCH/verify/PUT) 关闭 → ScoreAtClosure 均有值 (无评分记录时为 NULL)
2. 关闭后第 1 次评分回填 ScoreAfterUpdate; 第 2 次评分覆盖为最新值, ScoreUpdatedAt 刷新
3. 重开后三字段为 NULL, 状态 in_progress, 可重新走完整闭环
4. 前端已关闭问题可重开 (需填原因), 评论历史可追溯
5. 并发评分+关闭不产生错位快照
