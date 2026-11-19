/* ============================================================================
   04_flip_manual_source.sql —— 种子用户 source: 'MANUAL' → 'AD'
   ----------------------------------------------------------------------------
   背景：
     03_seed_users.sql 灌入的 13 个种子用户 source='MANUAL'。MERGE 规则：
       - source='MANUAL' 行永不更新、永不被停用、login_name 不被改写。
     决策（2026-11-03 用户确认）：种子用户转入 AD 同步生命周期，
     即资料随 AD 名单更新、离职自动停用。

   执行账号：ytview（CN_AME_SSO_User 已授 UPDATE）或 DBA。
   执行顺序（严禁跳步）：
     第 1 节预检 → 全部符合预期 → 第 2 节转换 → 第 3 节核对
     → 再跑 sync_ad_to_sso.ps1（-SkipKeycloakSync）→ 第 4 节核对 MERGE 结果。

   回退：
     UPDATE dbo.CN_AME_SSO_User SET source = 'MANUAL', updated_at = SYSUTCDATETIME()
     WHERE login_name IN ('lead_reviewer01','reviewer01','reviewee01', ...);  -- 按第 1.3 节快照填
   ========================================================================== */

/* ----------------------------------------------------------------------------
   第 1 节 预检（只读，不改数据。三项必须逐项确认）
   ---------------------------------------------------------------------------- */

-- 1.1 危险项：暂存登录名在中央表已存在、但工号不同。
--     若此处非 0 行，转换后 MERGE 的 INSERT 会撞 UQ_CN_AME_SSO_User_Login 直接报错，
--     必须先对齐工号（以 AD 为准 UPDATE 中央表 employee_no，或让 IT 修名单）。
SELECT s.login_name,
       s.employee_no AS stg_emp,
       u.employee_no AS central_emp,
       u.source,
       u.status
FROM dbo.CN_AME_SSO_StgAdUser s
JOIN dbo.CN_AME_SSO_User u
  ON u.login_name = s.login_name
WHERE u.employee_no <> s.employee_no;
-- 期望：0 行

-- 1.2 暂存行按工号命中中央表的情况（看 13 个种子用户被 AD 名单覆盖了多少）
SELECT u.source,
       u.status,
       COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_StgAdUser s
JOIN dbo.CN_AME_SSO_User u
  ON u.employee_no = s.employee_no
GROUP BY u.source, u.status;
-- 期望：source='MANUAL' 且 status=1 的 13 行全部出现（说明工号对得上）

-- 1.3 种子用户中【不在】暂存表的——转换后会被 MERGE 的
--     "NOT MATCHED BY SOURCE AND status=1 AND source<>'MANUAL'" 规则置为 status=0（停用）。
--     逐个人工确认：真实员工不在名单里 = 名单有问题，找 IT 补；
--     测试账号（lead_reviewer01/reviewer01/reviewee01）不在名单里 = 预期，正是"不纳入 SSO"的自动化执行。
SELECT u.login_name,
       u.display_name,
       u.status,
       u.source
FROM dbo.CN_AME_SSO_User u
LEFT JOIN dbo.CN_AME_SSO_StgAdUser s
  ON s.employee_no = u.employee_no
WHERE u.source = 'MANUAL'
  AND s.employee_no IS NULL
ORDER BY u.login_name;

-- 1.4 转换前快照（留存，供核对与回退）
SELECT employee_no, login_name, display_name, email, status, source, pwd_set
FROM dbo.CN_AME_SSO_User
WHERE source = 'MANUAL'
ORDER BY login_name;

/* ----------------------------------------------------------------------------
   第 2 节 转换（预检全部通过后执行；幂等，可重复执行）
   ---------------------------------------------------------------------------- */

-- 2.1 全量转换（用户 2026-11-03 决策口径：MANUAL 种子用户转 AD）
--     副作用预告：不在 AD 名单里的账号（预期是 3 个测试账号）会在下次 MERGE 被
--     置 status=0。这是"测试账号不纳入 SSO"的自动化执行，属预期行为。
--     例外：admin 是共享系统账号（各业务系统本地管理员），本就不在 AD 名单里，
--     一旦被转成 AD，06:00 的 MERGE 会把它当离职人员置 status=0。故显式排除。
UPDATE dbo.CN_AME_SSO_User
SET source = 'AD',
    updated_at = SYSUTCDATETIME()
WHERE source = 'MANUAL'
  AND employee_no NOT IN (N'admin');

SELECT @@ROWCOUNT AS flipped_rows;
-- 期望：12（13 个 MANUAL 减去 admin）

-- 2.2 变体（仅当决定保留测试账号为 MANUAL、不让它们被自动停用时使用，代替 2.1）：
-- UPDATE dbo.CN_AME_SSO_User
-- SET source = 'AD', updated_at = SYSUTCDATETIME()
-- WHERE source = 'MANUAL'
--   AND login_name NOT IN ('lead_reviewer01', 'reviewer01', 'reviewee01');

/* ----------------------------------------------------------------------------
   第 3 节 转换后核对
   ---------------------------------------------------------------------------- */

-- 3.1 全表 source/status 分布（此时应无 MANUAL 行；真实用户仍 status=1）
SELECT source, status, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY source, status
ORDER BY source, status;

/* ----------------------------------------------------------------------------
   第 4 节 MERGE 之后核对（跑完 sync_ad_to_sso.ps1 后执行）
   执行命令（Keycloak 未就绪，必须跳过串联）：
     .\sync_ad_to_sso.ps1 -Source table -TableSourceQuery "SELECT login_name AS userName, display_name AS realName, email, mobile, status AS enable, employee_no AS employeeNo FROM dbo.CN_AME_SSO_StgAdUser" -SkipKeycloakSync
   ---------------------------------------------------------------------------- */

-- 4.1 最近同步日志（看 LOAD/MERGE 的 OK/ABORTED 与增改停复计数）
SELECT TOP 20 id, phase, src_rows, added, updated, disabled, reactivated, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog
ORDER BY id DESC;

-- 4.2 MERGE 后全表状态（预期：11 个真实用户 source='AD' 且 status 以 AD 名单为准；
--     3 个测试账号 status=0；AD 名单新用户 INSERT 为 source='AD'）
SELECT source, status, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY source, status
ORDER BY source, status;

-- 4.3 原 13 个种子用户的最终状态：把 1.4 节快照中的 login_name 粘贴进 IN 列表逐个对照
--     （3 个测试账号已知名单先列出；其余 10 个从 1.4 节快照补）
SELECT login_name, display_name, status, source, synced_at
FROM dbo.CN_AME_SSO_User
WHERE login_name IN (
    'lead_reviewer01', 'reviewer01', 'reviewee01'
    -- , '...'  -- 其余 login_name 从 1.4 节快照粘贴到这里
)
ORDER BY login_name;
