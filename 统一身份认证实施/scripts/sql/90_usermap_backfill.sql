/* ============================================================
   90_usermap_backfill.sql
   跨系统账号对照表（CN_AME_SSO_UserMap）回填模板与对账查询（T01/T05 共用）

   用途:
   1) 新系统接入/存量盘点时，把"系统本地用户名 ≠ 中央 login_name"的账号登记进对照表;
   2) 对账查询: 找出 MSIA/BOL 存量真实用户中尚未覆盖的账号（R5: 对不上的不接入，人工裁决）。

   匹配约定（方案文档 9 共享约定）:
   groups 准入校验 → CN_AME_SSO_UserMap(system_code) → 回落 preferred_username → 本地用户表 → 自动建档

   归一化口径（本脚本所有匹配都用同一套，避免"工号/姓名/大小写/空白/域前缀"漏判）:
     normalized_login = LOWER(LTRIM(RTRIM(去掉 DOMAIN\ 前缀后的本地用户名)))
   双路径匹配:
     路径 1: 中央表 login_name  = normalized_login
     路径 2: 中央表 employee_no = normalized_login（工号登录的场景）

   安全性:
   - 本脚本默认全部只读（SELECT），不 DELETE、不 UPDATE 任何业务表;
   - 唯一需要写入的是 C 段 INSERT 模板，已整段注释，标注"需人工确认后执行"。
   ============================================================ */
USE CN_AME;
GO

/* ============================================================
   A. 对账查询 1：MSIA 真实用户（PasswordHash 非空）与中央表/对照表的覆盖情况
   预期: 13 名非测试用户全部 covered = 1；测试账号 covered = 0 属正常（不纳入 SSO）
   ============================================================ */
SELECT
    m.Username                          AS msia_username,
    LOWER(LTRIM(RTRIM(
        CASE WHEN CHARINDEX('\', m.Username) > 0
             THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
             ELSE m.Username END)))     AS normalized_login,
    m.RealName,
    m.Email,
    m.Role,
    m.Status,
    CASE WHEN ul.id IS NULL THEN 0 ELSE 1 END AS covered_by_login,
    CASE WHEN ue.id IS NULL THEN 0 ELSE 1 END AS covered_by_empno,
    CASE WHEN mp.id IS NULL THEN 0 ELSE 1 END AS covered_by_map
FROM dbo.CN_AME_MISA_User m
LEFT JOIN dbo.CN_AME_SSO_User ul
       ON ul.login_name = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', m.Username) > 0
                   THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                   ELSE m.Username END)))
LEFT JOIN dbo.CN_AME_SSO_User ue
       ON ue.employee_no = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', m.Username) > 0
                   THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                   ELSE m.Username END)))
LEFT JOIN dbo.CN_AME_SSO_UserMap mp
       ON mp.system_code = 'msia'
      AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', m.Username) > 0
                   THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                   ELSE m.Username END)))
WHERE m.PasswordHash IS NOT NULL AND m.PasswordHash <> ''
ORDER BY covered_by_map, covered_by_login, m.Username;
GO

/* ============================================================
   B. 对账查询 2：BOL 员工与中央表/对照表的覆盖情况
   注意: BOL 表在 CMC 库 db_datawriter schema 下，本查询需在有 CMC 读权限的
   账号上执行（如 sparePartRead），并把库名改为三段名:
     CMC.db_datawriter.CN_IE_BOL_Employee
   预期: 7 名非游客员工 covered = 1；guest covered = 0 属正常（游客通道保留，不入 SSO）
   ============================================================ */
SELECT
    e.username                          AS bol_username,
    LOWER(LTRIM(RTRIM(
        CASE WHEN CHARINDEX('\', e.username) > 0
             THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
             ELSE e.username END)))     AS normalized_login,
    e.name                              AS bol_name,
    e.email                             AS bol_email,
    e.role                              AS bol_role,
    e.status                            AS bol_status,
    CASE WHEN ul.id IS NULL THEN 0 ELSE 1 END AS covered_by_login,
    CASE WHEN ue.id IS NULL THEN 0 ELSE 1 END AS covered_by_empno,
    CASE WHEN mp.id IS NULL THEN 0 ELSE 1 END AS covered_by_map
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
LEFT JOIN dbo.CN_AME_SSO_User ul
       ON ul.login_name = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', e.username) > 0
                   THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                   ELSE e.username END)))
LEFT JOIN dbo.CN_AME_SSO_User ue
       ON ue.employee_no = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', e.username) > 0
                   THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                   ELSE e.username END)))
LEFT JOIN dbo.CN_AME_SSO_UserMap mp
       ON mp.system_code = 'bol'
      AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX('\', e.username) > 0
                   THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                   ELSE e.username END)))
WHERE e.username <> 'guest'
ORDER BY covered_by_map, covered_by_login, e.username;
GO

/* ============================================================
   C. 回填模板（需人工确认后执行）
   ------------------------------------------------------------------
   以下 INSERT 已整段注释: 不会随脚本执行产生任何写入。
   执行前必须:
     1) 先跑 A/B 段确认该账号确实 uncovered;
     2) 用 A/B 段输出的 normalized_login 填 <本地用户名>;
     3) 确认 <中央employee_no> 在 CN_AME_SSO_User 中存在;
     4) 逐条人工确认再把注释打开执行 (脚本本身幂等, UQ(system_code, local_username) 保护)。
   ------------------------------------------------------------------
   典型场景: 某员工 MSIA 用工号登录、BOL 用姓名拼音登录，两处都要显式登记。
   ============================================================ */
/*
-- [需人工确认后执行] MSIA
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap
               WHERE system_code = 'msia'
                 AND LOWER(LTRIM(RTRIM(local_username))) = LOWER(LTRIM(RTRIM('<本地用户名>')))
    AND EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = '<中央employee_no>')
INSERT INTO dbo.CN_AME_SSO_UserMap
    (employee_no, system_code, local_username, match_key, remark)
VALUES
    ('<中央employee_no>', 'msia', '<本地用户名>', 'USERNAME', N'<不一致原因说明>');

-- [需人工确认后执行] BOL
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap
               WHERE system_code = 'bol'
                 AND LOWER(LTRIM(RTRIM(local_username))) = LOWER(LTRIM(RTRIM('<本地用户名>')))
    AND EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = '<中央employee_no>')
INSERT INTO dbo.CN_AME_SSO_UserMap
    (employee_no, system_code, local_username, match_key, remark)
VALUES
    ('<中央employee_no>', 'bol', '<本地用户名>', 'USERNAME', N'<不一致原因说明>');
*/

/* ============================================================
   D. 已登记对照表总览（人工裁决清单）
   ============================================================ */
SELECT
    mp.system_code,
    mp.local_username,
    LOWER(LTRIM(RTRIM(mp.local_username))) AS normalized_login,
    mp.employee_no,
    u.login_name,
    u.display_name,
    mp.match_key,
    mp.remark
FROM dbo.CN_AME_SSO_UserMap mp
LEFT JOIN dbo.CN_AME_SSO_User u ON u.employee_no = mp.employee_no
ORDER BY mp.system_code, mp.local_username;
GO

/* ============================================================
   E. 孤儿数据检查（对照表指向不存在的中央用户 / 重复 local_username）
   预期两查询均为空
   ============================================================ */
SELECT mp.* FROM dbo.CN_AME_SSO_UserMap mp
LEFT JOIN dbo.CN_AME_SSO_User u ON u.employee_no = mp.employee_no
WHERE u.employee_no IS NULL;

SELECT system_code, local_username, COUNT(*) AS dup_cnt
FROM dbo.CN_AME_SSO_UserMap
GROUP BY system_code, local_username
HAVING COUNT(*) > 1;
GO

/* ============================================================
   F. 未覆盖清单（上线前必须逐条处理）
   输出: 双路径 (login_name / employee_no) 与对照表均未命中的本地账号。
   处理: 按 C 段模板登记 UserMap, 或修正本地用户名后再登记。
   ============================================================ */
-- F.1 MSIA 未覆盖
SELECT 'msia' AS system_code,
       m.Username AS local_username,
       LOWER(LTRIM(RTRIM(
           CASE WHEN CHARINDEX('\', m.Username) > 0
                THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                ELSE m.Username END))) AS normalized_login,
       m.RealName AS display_name
FROM dbo.CN_AME_MISA_User m
WHERE m.PasswordHash IS NOT NULL AND m.PasswordHash <> ''
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', m.Username) > 0
                                THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                                ELSE m.Username END)))
                     OR u.employee_no = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', m.Username) > 0
                                THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                                ELSE m.Username END)))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'msia'
                    AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', m.Username) > 0
                                THEN SUBSTRING(m.Username, CHARINDEX('\', m.Username) + 1, LEN(m.Username))
                                ELSE m.Username END)))
UNION ALL
-- F.2 BOL 未覆盖
SELECT 'bol',
       e.username,
       LOWER(LTRIM(RTRIM(
           CASE WHEN CHARINDEX('\', e.username) > 0
                THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                ELSE e.username END))),
       e.name
FROM CMC.db_datawriter.CN_IE_BOL_Employee e
WHERE e.username <> 'guest'
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE u.login_name = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', e.username) > 0
                                THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                                ELSE e.username END)))
                     OR u.employee_no = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', e.username) > 0
                                THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                                ELSE e.username END)))
  AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap mp
                  WHERE mp.system_code = 'bol'
                    AND LOWER(LTRIM(RTRIM(mp.local_username))) = LOWER(LTRIM(RTRIM(
                           CASE WHEN CHARINDEX('\', e.username) > 0
                                THEN SUBSTRING(e.username, CHARINDEX('\', e.username) + 1, LEN(e.username))
                                ELSE e.username END)))
ORDER BY system_code, local_username;
GO

/* ============================================================
   G. 回滚说明（本脚本自身无需回滚）
   - A/B/D/E/F 全部为只读 SELECT;
   - C 段的 INSERT 如需回滚, 只能按主键/唯一键逐条 DELETE 刚插入的行,
     且必须人工确认后执行 (本脚本不提供自动回滚语句, 避免误删存量映射):
       -- [需人工确认后执行]
       -- DELETE FROM dbo.CN_AME_SSO_UserMap
       -- WHERE system_code = '<msia|bol>'
       --   AND local_username = '<刚插入的本地用户名>';
   ============================================================ */
