/* ============================================================
   91_usermap_integrity_checks.sql
   UserMap 上线前完整性校验（只读，不执行任何写入）

   背景: 两系统 OIDC 身份解析顺序为
          groups 准入 → CN_AME_SSO_UserMap(system_code + local_username)
          → 回落 preferred_username(=login_name) → 本地用户表 → 自动建档
   风险: UserMap 缺失且本地用户名与 login_name 拼写不一致时, 会按 login_name
          自动建一个重复的低权限账号 (BOL=VIEWER / MSIA=reviewee)。

   依赖: CN_AME 库（中央表），BOL 本地表在 CMC 库（需跨库读权限）。
   执行方式: SSMS / sqlcmd -i 91_usermap_integrity_checks.sql
   ============================================================ */
USE CN_AME;
GO

/* ---------- 0. 总量与系统分布 ---------- */
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) AS active_total,
       SUM(CASE WHEN pwd_set = 1 THEN 1 ELSE 0 END) AS pwd_set_total
FROM dbo.CN_AME_SSO_User;

SELECT system_code, COUNT(*) AS map_rows
FROM dbo.CN_AME_SSO_UserMap
GROUP BY system_code;
GO

/* ---------- 1. MSIA 真实用户覆盖情况 ----------
   预期: 13 名非测试用户 covered_by_login = 1 或 covered_by_empno = 1;
   测试账号 (lead_reviewer01/reviewer01/reviewee01) 不纳入, 可忽略。
   注意: 旧版 90 脚本只按 employee_no = LOWER(Username) 匹配;
         本查询同时按 login_name 与 employee_no 两条路径匹配, 避免工号≠用户名时漏判。
------------------------------------------------ */
SELECT
    m.Username                                  AS msia_username,
    LOWER(LTRIM(RTRIM(m.Username)))             AS expected_login_name,
    m.RealName, m.Email, m.Role, m.Status,
    CASE WHEN ul.id IS NULL THEN 0 ELSE 1 END   AS covered_by_login,
    CASE WHEN ue.id IS NULL THEN 0 ELSE 1 END   AS covered_by_empno,
    CASE WHEN mp.id IS NULL THEN 0 ELSE 1 END   AS covered_by_map,
    CASE WHEN ul.id IS NULL AND ue.id IS NULL AND mp.id IS NULL THEN 1 ELSE 0 END
                                                AS uncovered
FROM dbo.CN_AME_MISA_User m
LEFT JOIN dbo.CN_AME_SSO_User ul
       ON ul.login_name = LOWER(LTRIM(RTRIM(m.Username)))
LEFT JOIN dbo.CN_AME_SSO_User ue
       ON ue.employee_no = LOWER(LTRIM(RTRIM(m.Username)))
LEFT JOIN dbo.CN_AME_SSO_UserMap mp
       ON mp.system_code = 'msia' AND mp.local_username = m.Username
WHERE m.PasswordHash IS NOT NULL AND m.PasswordHash <> ''
ORDER BY uncovered DESC, m.Username;
GO

/* ---------- 2. BOL 员工覆盖情况 ----------
   预期: 7 名非游客员工 covered = 1; guest 不纳入。
   若账号无 CMC 读权限, 本节会报错, 换 sparePartRead 等有权限账号执行。
------------------------------------------------ */
SELECT
    e.username                                  AS bol_username,
    LOWER(LTRIM(RTRIM(e.username)))             AS expected_login_name,
    e.name, e.email, e.role, e.status,
    CASE WHEN ul.id IS NULL THEN 0 ELSE 1 END   AS covered_by_login,
    CASE WHEN ue.id IS NULL THEN 0 ELSE 1 END   AS covered_by_empno,
    CASE WHEN mp.id IS NULL THEN 0 ELSE 1 END   AS covered_by_map,
    CASE WHEN ul.id IS NULL AND ue.id IS NULL AND mp.id IS NULL THEN 1 ELSE 0 END
                                                AS uncovered
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
LEFT JOIN dbo.CN_AME_SSO_User ul
       ON ul.login_name = LOWER(LTRIM(RTRIM(e.username)))
LEFT JOIN dbo.CN_AME_SSO_User ue
       ON ue.employee_no = LOWER(LTRIM(RTRIM(e.username)))
LEFT JOIN dbo.CN_AME_SSO_UserMap mp
       ON mp.system_code = 'bol' AND mp.local_username = e.username
WHERE e.username <> 'guest'
ORDER BY uncovered DESC, e.username;
GO

/* ---------- 3. 必须人工回填的差集（uncovered = 1） ----------
   处理: 先在 CN_AME_SSO_User 补人, 再按 90 脚本 C 段模板登记 UserMap。
   不补的后果: 该用户首次 OIDC 登录会按 login_name 新建重复账号。
------------------------------------------------ */
-- 3.1 MSIA
SELECT m.Username, LOWER(LTRIM(RTRIM(m.Username))) AS expected_login_name, m.RealName
FROM dbo.CN_AME_MISA_User m
WHERE m.PasswordHash IS NOT NULL AND m.PasswordHash <> ''
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(m.Username)))
                     OR u.employee_no = LOWER(LTRIM(RTRIM(m.Username))))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'msia' AND mp.local_username = m.Username);
GO

-- 3.2 BOL
SELECT e.username, LOWER(LTRIM(RTRIM(e.username))) AS expected_login_name, e.name
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
WHERE e.username <> 'guest'
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(e.username)))
                     OR u.employee_no = LOWER(LTRIM(RTRIM(e.username))))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'bol' AND mp.local_username = e.username);
GO

/* ---------- 4. "重复账号"高危名单 ----------
   条件: 本地用户名与中央 login_name 拼写不同(忽略大小写), 且没有 UserMap 行。
   这类账号 OIDC 登录会命中不到本地用户 → 自动建档 → 出现两个账号。
   预期: 空。若不为空, 必须逐行登记 UserMap。
------------------------------------------------ */
SELECT 'msia' AS system_code, m.Username AS local_username,
       LOWER(LTRIM(RTRIM(m.Username))) AS local_lower
FROM dbo.CN_AME_MISA_User m
WHERE m.PasswordHash IS NOT NULL AND m.PasswordHash <> ''
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(m.Username))))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'msia' AND mp.local_username = m.Username)
UNION ALL
SELECT 'bol', e.username, LOWER(LTRIM(RTRIM(e.username)))
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
WHERE e.username <> 'guest'
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(e.username))))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'bol' AND mp.local_username = e.username);
GO

/* ---------- 4.2 大小写冲突名单（同一自然人有多个候选账号） ----------
   条件: 本地用户名仅大小写/首尾空白不同, 但库里存在多行 (排序规则为 CI 时可能
         已发生历史重复; 新库为 _CS_ 时也可能已经各自建过账号)。
   影响: 身份解析按忽略大小写比对, 同一人会命中任意一条, 权限/密码/令牌会分叉。
   处理: 逐条确认保留哪一条 (建议保留有 PasswordHash / 有业务数据的那条),
         确认后合并账号并在 UserMap 只登记一条。
   预期: 空。不为空必须人工裁决, 不要批量自动合并。
------------------------------------------------ */
SELECT 'msia' AS system_code,
       a.Username AS username_a,
       b.Username AS username_b,
       LOWER(LTRIM(RTRIM(a.Username))) AS normalized_login
FROM dbo.CN_AME_MISA_User a
JOIN dbo.CN_AME_MISA_User b
  ON LOWER(LTRIM(RTRIM(a.Username))) = LOWER(LTRIM(RTRIM(b.Username)))
 AND a.Id < b.Id
UNION ALL
SELECT 'bol',
       a.username,
       b.username,
       LOWER(LTRIM(RTRIM(a.username)))
FROM CMC.db_datawriter.CN_IE_BOL_Employee a
JOIN CMC.db_datawriter.CN_IE_BOL_Employee b
  ON LOWER(LTRIM(RTRIM(a.username))) = LOWER(LTRIM(RTRIM(b.username)))
 AND a.id < b.id
ORDER BY system_code, normalized_login;
GO

/* ---------- 4.3 中央表 vs 本地账号一对多（同一 login_name 命中多个本地账号） ----------
   条件: 归一化后的本地用户名命中中央 login_name, 且本地存在多行。
   与 4.2 的区别: 这里以中央表为基准, 能发现"大小写不同但都被视作同一人"的账号。
   预期: 空。
------------------------------------------------ */
SELECT 'msia' AS system_code, u.login_name,
       COUNT(*) AS local_accounts
FROM dbo.CN_AME_MISA_User m
JOIN dbo.CN_AME_SSO_User u
  ON u.login_name = LOWER(LTRIM(RTRIM(m.Username)))
GROUP BY u.login_name
HAVING COUNT(*) > 1
UNION ALL
SELECT 'bol', u.login_name, COUNT(*)
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
JOIN dbo.CN_AME_SSO_User u
  ON u.login_name = LOWER(LTRIM(RTRIM(e.username)))
WHERE e.username <> 'guest'
GROUP BY u.login_name
HAVING COUNT(*) > 1;
GO

/* ---------- 5. 用户名脏数据（域名前缀/邮箱形态/空白） ----------
   预期: 空。存在则先规范化再回填, 否则 UserMap 会按原样登记, Keycloak 侧对不上。
------------------------------------------------ */
SELECT 'msia' AS system_code, Username AS local_username FROM dbo.CN_AME_MISA_User
WHERE Username LIKE '%\%' OR Username LIKE '%@%' OR Username LIKE '% %'
UNION ALL
SELECT 'bol', username FROM CMC.db_datawriter.CN_IE_BOL_Employee
WHERE username LIKE '%\%' OR username LIKE '%@%' OR username LIKE '% %';
GO

/* ---------- 6. 中央表 login_name 大小写重复 ----------
   预期: 空 (UQ_CN_AME_SSO_User_Login 在 CI 排序规则下也会拦住, 此处显式复核)
------------------------------------------------ */
SELECT LOWER(login_name) AS login_lower, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY LOWER(login_name)
HAVING COUNT(*) > 1;
GO

/* ---------- 7. UserMap 自身一致性 ----------
   7.1 孤儿映射（指向不存在的中央用户）—— 预期空
   7.2 local_username 重复 —— 预期空（UQ 已约束）
   7.3 match_key 使用情况：代码只按 local_username 匹配, EMAIL/EMPNO 行不生效
------------------------------------------------ */
SELECT mp.* FROM dbo.CN_AME_SSO_UserMap mp
LEFT JOIN dbo.CN_AME_SSO_User u ON u.employee_no = mp.employee_no
WHERE u.employee_no IS NULL;

SELECT system_code, local_username, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_UserMap
GROUP BY system_code, local_username
HAVING COUNT(*) > 1;

SELECT match_key, COUNT(*) AS cnt FROM dbo.CN_AME_SSO_UserMap GROUP BY match_key;
GO

/* ---------- 8. 状态口径不一致（中央 vs 本地） ----------
   预期: 空。不一致会导致"Keycloak 能登、应用侧被停用"或反向问题。
------------------------------------------------ */
-- 8.1 MSIA：中央 status=0 但本地 Status 仍为启用
SELECT m.Username, m.Status AS local_status, u.status AS central_status
FROM dbo.CN_AME_MISA_User m
JOIN dbo.CN_AME_SSO_User u
  ON u.login_name = LOWER(LTRIM(RTRIM(m.Username)))
WHERE u.status = 0 AND m.Status = 1;

-- 8.2 BOL：中央 status=0 但本地仍 ACTIVE
SELECT e.username, e.status AS local_status, u.status AS central_status
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
JOIN dbo.CN_AME_SSO_User u
  ON u.login_name = LOWER(LTRIM(RTRIM(e.username)))
WHERE u.status = 0 AND e.status = 'ACTIVE';
GO

/* ---------- 9. AD 暂存表与中央表差集（若当日已导入） ----------
   预期: 仅"新入职/已离职"两类差异; 若大量缺失, 说明 LOAD 步骤没跑或名单过期。
   注意: 中央表 source='MANUAL' 的 13 条种子不在 AD 名单时也会出现在左侧, 属正常。
------------------------------------------------ */
SELECT s.employee_no, s.login_name, s.display_name, s.status AS ad_status,
       CASE WHEN u.id IS NULL THEN 'NOT_IN_CENTRAL' ELSE 'IN_CENTRAL' END AS flag
FROM dbo.CN_AME_SSO_StgAdUser s
LEFT JOIN dbo.CN_AME_SSO_User u
       ON u.employee_no = s.employee_no OR u.login_name = s.login_name
WHERE u.id IS NULL
ORDER BY flag, s.employee_no;

SELECT u.employee_no, u.login_name, u.source, u.status
FROM dbo.CN_AME_SSO_User u
WHERE u.source = 'AD'
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_StgAdUser s
                  WHERE s.employee_no = u.employee_no OR s.login_name = u.login_name);
GO

/* ============================================================
   10. 写入语句（需人工确认后执行）
   ------------------------------------------------------------------
   本文件 1-9 节全部只读; 以下语句已整段注释, 不会随脚本执行写入。
   仅当第 3/4.2/4.3 节查出问题、且人工逐条裁决后才可打开注释执行。
   禁止在本文件中添加 UPDATE / DELETE 业务表的语句。
   ------------------------------------------------------------------
   示例: 把某本地账号登记进 UserMap (先确认中央用户存在、且该账号未登记)
   ============================================================ */
/*
-- [需人工确认后执行]
INSERT INTO dbo.CN_AME_SSO_UserMap
    (employee_no, system_code, local_username, match_key, remark)
VALUES
    ('<中央employee_no>', '<msia|bol>', '<本地用户名>', 'USERNAME', N'<裁决说明>');
*/

/* ============================================================
   判读口径（上线前必须全部满足）
   1) 第 1/2 节 uncovered = 0（测试账号与 guest 除外）
   2) 第 3 节两个差集为空
   3) 第 4 节高危名单为空; 第 4.2/4.3 节大小写冲突名单为空
   4) 第 5/6/7 节为空
   5) 第 8 节为空, 或差异已由业务确认
   ============================================================ */
