# 双轨 → 单轨切换操作手册（Cutover Runbook）

> 依据《统一身份认证实施方案_MSIA与BOL系统.md》8.1 P4 阶段。
> 适用范围：MSIA Report 与 BOL 管理系统从"本地登录 + OIDC 双轨"切换到"仅 Keycloak 单轨"。
> **总原则：只做加法、开关化、每一步可回退**；切换操作两人执行（一人操作一人复核）。

## 1. 切换前置条件（全部满足才进入切换窗口）

| # | 条件 | 验证方式 |
|---|---|---|
| C1 | 同步连续 5 个工作日 OK | `SELECT phase, status, MAX(run_at) FROM CN_AME_SSO_SyncLog GROUP BY phase, status` |
| C2 | 13 名种子用户全部 pwd_set=1 且可登录 Keycloak | `SELECT COUNT(*) FROM CN_AME_SSO_User WHERE pwd_set = 1` = 13 |
| C3 | 对照表对账无孤儿、无重复 | 90_usermap_backfill.sql D/E 节查询为空 |
| C4 | 上线 4 周内 ≥90% 登录走 Keycloak（S6） | Keycloak User events 登录统计 + 两系统本地登录日志 |
| C5 | break-glass 本地管理员账号已封存（每系统 ≤2） | 台账 system_code='local-admin' 记录在案 |
| C6 | 回滚手册已演练至少 1 次 | rollback-runbook.md 演练记录签字 |
| C7 | MSIA JWT 密钥已更换为随机 64 字符（TR7） | 配置核对，旧密钥已销毁 |
| C8 | BOL AuthToken.source 列已上线，source='local' 存量已可识别 | T04 交付物核对 |

## 2. 开关矩阵（切换的唯一操作面）

| 系统 | 配置项 | 位置 | 双轨期值 | 单轨值 | 切换后效果 |
|---|---|---|---|---|---|
| MSIA | `[oidc].enabled` | `backend/config.ini` | `true` | `true`（不变） | OIDC 入口保留 |
| MSIA | `[security].local_login_enabled` | `backend/config.ini` | `true` | **`false`** | 本地账密登录 403"请使用统一登录" |
| MSIA | `[security].hr_sync_enabled` | `backend/config.ini` | `true` | **`false`** | 停 HRDB 来源，用户资料改由中央表派生（T04 `sso_user_sync`） |
| MSIA | 重置/改密端点 | `app/api/users.py` | 可用 | **403** | 密码生命周期归 Keycloak |
| BOL | `LOCAL_AUTH_ENABLED` | `settings.py` / `db_config.ini [auth]` | `true` | **`false`** | LoginView 本地通道 403 |
| BOL | `SELF_REGISTRATION_ENABLED` | 同上 | `false`（P4 初已关） | `false`（不变） | 自助注册保持关闭 |
| BOL | `PASSWORD_SELF_SERVICE_ENABLED` | 同上 | `true` | **`false`** | 改密/忘记密码 403 |
| BOL | `SSO_STATUS_SYNC_HOURS` | 同上 | `1` | `1`（不变） | 状态回写持续运行 |

> 切换窗口内**只改上表加粗的四项**，其余一律不动。每项改动前后各做一次冒烟验证。

## 3. 切换步骤（建议周五 17:00 后低峰窗口，预留 2 小时）

### 3.1 切换前（T-1 天）
1. 通知全员：切换时间、影响（本地密码将失效，统一用 Keycloak 密码）、求助渠道；
2. 冻结台账变更（切换窗口内不授新权）；
3. 备份：`kc.bat export` + CN_AME 库完整备份 + 两系统配置包各留一份。

### 3.2 切换日步骤
| 步 | 操作 | 验证 | 回退点 |
|---|---|---|---|
| S1 | MSIA：`local_login_enabled=false` | 本地登录返回 403；OIDC 登录正常 | 改回 `true` 即恢复 |
| S2 | MSIA：冒烟——1 名 admin + 1 名 reviewee 走 OIDC 全链路（登录→业务页→登出） | 通过 | S1 |
| S3 | MSIA：`hr_sync_enabled=false` | 观察 1 个同步周期，确认用户资料仍从中央表派生正常 | 改回 `true` 即恢复 HRDB 来源 |
| S4 | BOL：`LOCAL_AUTH_ENABLED=false` | 本地登录 403；OIDC 登录正常 | 改回 `true` |
| S5 | BOL：冒烟——ADMIN + VIEWER + ENGINEER 各 1 名走 OIDC 全链路 | 通过 | S4 |
| S6 | BOL：`PASSWORD_SELF_SERVICE_ENABLED=false` | 改密/忘记密码 403 | 改回 `true` |
| S7 | BOL：作废旧本地令牌 `DELETE FROM CN_IE_BOL_AuthToken WHERE source='local'`（T04 提供脚本） | 存量本地 Token 失效；OIDC 签发的 Token 不受影响 | 无需回退（用户重新登录即可） |

> **S7 运维口径**：切换日删除 `source='local'` 只作废旧本地令牌；`sync_sso_status` 每小时以中央表状态为准。若在 BOL 后台/数据库手工把员工置为 `INACTIVE`，下次同步会按中央表覆盖；`ACTIVE` Token 复活仅在中央表仍为 `status=1` 时发生，属预期复职，不是禁用绕过。
| S8 | 两系统同步关闭"重置密码"前端入口显隐（P1，配置开关） | 管理页无该入口 | 改配置恢复 |

### 3.3 切换后 48 小时观察
1. 每日健康检查（health_check.ps1）连跑 2 天无告警；
2. 监控 OIDC 登录成功率（Keycloak events）与两系统业务异常；
3. 收集用户反馈，重点：设密邮件到达、登录跳转、权限正确性；
4. 48 小时无 P1 级问题 → 切换完成，进入运维态。

## 4. 切换期应急联络

| 角色 | 职责 |
|---|---|
| 主理人 | 切换决策、回退决策 |
| 工程师（T02/T03 责任人） | 开关操作、冒烟验证 |
| IT | AD 名单、DNS/反代、SMTP |
| 业务管理员（每系统 ≤2 人） | break-glass 本地通道 |

## 5. 切换完成标志（P4 收尾）

- 两系统 `local_login_enabled=false` / `LOCAL_AUTH_ENABLED=false` 生效且稳定 4 周；
- S6 达成：≥90% 真实登录走 Keycloak；
- 台账季度对账制度生效（首次对账安排在切换完成后首个季度末）。
