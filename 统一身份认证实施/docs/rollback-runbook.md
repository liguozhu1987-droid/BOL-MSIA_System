# 回滚手册（Rollback Runbook）

> 依据《统一身份认证实施方案_MSIA与BOL系统.md》8.1 回滚方案列与 S7（break-glass 演练）。
> **核心原则**：Keycloak 与两系统改造全程"只做加法"——任何一步失败都能退回到改造前状态，
> 且**各系统本地账号体系原样保留**（不删号、不改哈希）。
> 回滚决策人：主理人；执行人：工程师；记录人：工程师（回滚过程写 CN_AME_SSO_SyncLog，phase='KC_EMERGENCY'）。

## 1. 回滚场景总览

| 场景 | 影响 | 回滚动作 | 预计耗时 |
|---|---|---|---|
| R-a Keycloak 服务故障 | 全体无法 SSO 登录 | 两系统打开本地登录开关 → break-glass 进入 → 修复 KC | 15 分钟 |
| R-b 同步链路异常/中央表被污染 | 建错号、错误停用 | 停计划任务 → MERGE 前快照恢复 → 重跑 | 30 分钟 |
| R-c OIDC 接入缺陷（单系统） | 该系统登录异常 | 该系统 OIDC 入口关掉（`oidc.enabled=false`），本地登录恢复 | 10 分钟 |
| R-d 切换后大面积问题（P4） | 两系统登录受阻 | 按 cutover-runbook.md 开关矩阵逐项改回 | 30 分钟 |
| R-e 数据库误操作（SSO 五表） | 中央表/对照表/台账损坏 | 每日备份恢复 CN_AME（仅 SSO 五表亦可 Drop 重建 + 灌种子） | 1 小时 |

## 2. R-a：Keycloak 故障（含 break-glass 本地通道）

1. **立即恢复登录能力**（不等 KC 修复）：
   - MSIA：`backend/config.ini` → `[security].local_login_enabled=true` → 重启后端；
   - BOL：`db_config.ini [auth]` → `LOCAL_AUTH_ENABLED=true` → 重启服务；
   - ⚠️ 本地密码自 P4 起已停用，多数用户没有可用本地密码——此时**只有 break-glass 账号能进系统**；
2. **break-glass 账号**（每系统 ≤2，台账 system_code='local-admin' 封存，密码物理封存）：
   - 仅用于应急进入系统处理紧急事务，不进统一身份体系、不日常使用；
3. **修复 KC**：查 `C:\keycloak\logs\keycloak.log` → 常见项：服务未起（NSSM 重启）、DB 连接（KC_DB_PASSWORD 环境变量）、证书/反代（TR12）；
4. **恢复单轨**：KC 修复验证后，按 cutover-runbook.md 重新执行开关。

## 3. R-b：同步链路异常 / 中央表污染

1. **停链路**：禁用计划任务 `SSO_AD_Import`（防继续污染）；
2. **评估污染范围**：`SELECT * FROM CN_AME_SSO_SyncLog ORDER BY id DESC` 定位最后一条 OK；
3. **恢复数据**（二选一）：
   - 方案 A（首选）：从当日凌晨的 CN_AME 完整备份中**仅恢复 SSO 五表**到污染前状态；
   - 方案 B：`DROP TABLE` 五表（仅 `CN_AME_SSO_` 前缀）→ 重跑 `01_create_sso_tables.sql` → `03_seed_users.sql` 灌种子（幂等）→ 通知各系统管理员按台账恢复角色；
4. **Keycloak 侧**：被错误停用的账号用 `disable_user_now.ps1` 的逆操作（中央表 status=1 → 下次 KC 同步自动复职 + 重发设密邮件）；被错误建号的账号在 KC 管理台删除；
5. **重跑链路**：手工执行 `sync_ad_to_sso.ps1` → 确认 SyncLog OK → 恢复计划任务；
6. 告警邮件通报全员处置结果。

## 4. R-c：单系统 OIDC 缺陷（最小爆炸半径回退）

| 系统 | 一键回退动作 |
|---|---|
| MSIA | `config.ini` `[oidc].enabled=false` → 重启后端 → OIDC 端点返回 503，前端回到本地登录按钮；`local_login_enabled` 确保为 `true` |
| BOL | `settings.py`/`db_config.ini` 关闭 OIDC 入口开关 → 前端回到本地登录 |

- 回退后该系统的统一登录暂停，用户用本地密码（双轨期）或 break-glass；
- 缺陷修复后按 T02/T03 交付物重新上线，重新进入双轨。

## 5. R-d：P4 切换后回退

1. 按 cutover-runbook.md 开关矩阵**逆序**改回：先 BOL（S6→S4）后 MSIA（S3→S1）；
2. BOL 旧本地令牌已删除（S7）——用户需重新本地登录一次（密码未删，本地账号体系完好）；
3. 48 小时观察稳定后，重新评估切换时机，二次切换前必须补齐首次失败的根因。

## 6. R-e：SSO 五表误操作恢复

```sql
-- 仅删 SSO 域自建表（严禁碰 CN_AME_MISA_* 等既有表）
DROP TABLE IF EXISTS dbo.CN_AME_SSO_PermLedger;
DROP TABLE IF EXISTS dbo.CN_AME_SSO_SyncLog;
DROP TABLE IF EXISTS dbo.CN_AME_SSO_UserMap;
DROP TABLE IF EXISTS dbo.CN_AME_SSO_User;
DROP TABLE IF EXISTS dbo.CN_AME_SSO_StgAdUser;
```
然后重跑 `01_create_sso_tables.sql` → `02_grants.sql` → `03_seed_users.sql`。
> `DROP TABLE IF EXISTS` 为幂等写法；权限对象（sso_sync_svc/sparePartRead）不受 DROP 影响，无需重建。

## 7. 演练要求（S7）

- 上线后 1 个月内至少完成 1 次 break-glass 演练：模拟 KC 停机 → 按 R-a 恢复本地通道 → 记录耗时与问题；
- 演练结果归档到本文档附录，未通过不得进入 P4 收尾。

## 8. 恢复演练（备份有效性，7.5 节）

- 每半年 1 次：新目录解压 Keycloak → 恢复 keycloak 库 → 起服务 → 验证登录；
- CN_AME 备份恢复抽检：确认 SSO 五表在既有备份作业范围内。
