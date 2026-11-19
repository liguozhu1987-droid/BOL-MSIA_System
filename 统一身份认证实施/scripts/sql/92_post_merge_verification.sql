/* ============================================================================
   92_post_merge_verification.sql  —— Stg → 主表 实跑之后的核对清单（全部只读）
   ----------------------------------------------------------------------------
   用途: 05_merge_stg_to_user.sql（或 sync_ad_to_sso.ps1 的 MERGE）实跑成功后，
         用这一个文件确认“数据到底进去了多少、谁被停用、有没有遗留异常”。
   安全: 全篇只有 SELECT，没有 INSERT/UPDATE/DELETE/MERGE，可整篇 F5 执行，
         也可逐段执行；不需要事务，不会改任何数据。
   前提: 已执行过第 0 节 DDL 的环境才有 last_batch_no 列；本文件不引用该列，
         因此新旧环境都能跑。
   ============================================================================ */

USE CN_AME;
GO

SET NOCOUNT ON;
GO


/* ----------------------------------------------------------------------------
   1. 主表总数（用途: 与 Stg 行数对账——主表应 ≈ Stg 人数 + MANUAL 例外行）
   -------------------------------------------------------------------------- */
PRINT N'--- 1. 主表总数 / 在职 / 停用 ---';
SELECT COUNT(*)                                        AS user_rows,
       SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END)     AS active_rows,
       SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END)     AS disabled_rows
FROM dbo.CN_AME_SSO_User;


/* ----------------------------------------------------------------------------
   2. 停用明细（用途: 逐行确认“被停用的人”是否都属于离职/名单外；
      上线初期出现的 lead_reviewer01 / reviewer01 / reviewee01 属预期测试账号）
   -------------------------------------------------------------------------- */
PRINT N'--- 2. 停用明细 ---';
SELECT employee_no, login_name, display_name, source, synced_at, updated_at
FROM dbo.CN_AME_SSO_User
WHERE status = 0
ORDER BY source, login_name;


/* ----------------------------------------------------------------------------
   3. source 分布（用途: 确认 AD / MANUAL 各多少行；MANUAL 为手工例外，
      同步既不覆盖也不停用，数量异常增大说明有人绕过流程手工建档）
   -------------------------------------------------------------------------- */
PRINT N'--- 3. source × status 分布 ---';
SELECT source, status, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY source, status
ORDER BY source, status;


/* ----------------------------------------------------------------------------
   4. SyncLog 最新记录（用途: 判断“这次到底跑没跑、成没成、增改停多少”；
      最近一次 phase=MERGE 应为 OK，若为 ABORTED 见 message 里的闸门原因）
   -------------------------------------------------------------------------- */
PRINT N'--- 4.1 最近 20 条同步日志（phase: LOAD / MERGE / KC / KC_EMERGENCY） ---';
SELECT TOP 20 id, phase, src_rows, added, updated, disabled, reactivated, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog
ORDER BY id DESC;

PRINT N'--- 4.2 最近一次 MERGE 的结论（status 期望 OK；ABORTED 表示闸门拦下未写库） ---';
SELECT TOP 1 id, src_rows, added, updated, disabled, reactivated, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog
WHERE phase = N'MERGE'
ORDER BY id DESC;


/* ----------------------------------------------------------------------------
   5. 仅大小写重复的工号（用途: 唯一键在 _CI 库下拦不住 LIGU/ligu 这类重复；
      非空结果必须人工裁决，否则下次 MERGE 会“同一行被多次更新”整体失败）
   -------------------------------------------------------------------------- */
PRINT N'--- 5. 仅大小写重复的工号（期望 0 组） ---';
SELECT LOWER(LTRIM(RTRIM(employee_no))) AS emp_key,
       COUNT(*)                         AS cnt,
       MIN(employee_no)                 AS emp_a,
       MAX(employee_no)                 AS emp_b
FROM dbo.CN_AME_SSO_User
GROUP BY LOWER(LTRIM(RTRIM(employee_no)))
HAVING COUNT(*) > 1;


/* ----------------------------------------------------------------------------
   6. 与 Stg 的差集（用途: stg_only 应接近 0——非 0 说明这批没合并完或该行被拒绝；
      central_only 应等于“停用人数”——都是名单外的人，不是漏合并）
   -------------------------------------------------------------------------- */
PRINT N'--- 6. 与 Stg 的差集（按归一后的登录名比较，期望 stg_only = 0） ---';
;WITH stg AS (
    SELECT LOWER(LTRIM(RTRIM(
               CASE WHEN CHARINDEX(N'\', ISNULL(login_name, N'')) > 0
                    THEN SUBSTRING(login_name, CHARINDEX(N'\', login_name) + 1, 4000)
                    ELSE ISNULL(login_name, N'') END))) AS login_norm
    FROM dbo.CN_AME_SSO_StgAdUser
)
SELECT
    (SELECT COUNT(*)
     FROM stg s
     WHERE s.login_norm <> N''
       AND NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                       WHERE LOWER(u.login_name) = s.login_norm))                AS stg_only,
    (SELECT COUNT(*)
     FROM dbo.CN_AME_SSO_User u
     WHERE u.status = 1 AND u.source <> N'MANUAL'
       AND NOT EXISTS (SELECT 1 FROM stg s WHERE s.login_norm = LOWER(u.login_name))) AS central_only_active;


/* ----------------------------------------------------------------------------
   7. pwd_set 现状（用途: 配合“首轮同步抽样核对”——修复后 pwd_set=1 的人数
      不应一次性暴涨到 1000+；批量导入的无密码用户应继续留在 pwd_set=0）
   -------------------------------------------------------------------------- */
PRINT N'--- 7. pwd_set 分布（期望: pwd_set=0 仍占绝大多数） ---';
SELECT pwd_set, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY pwd_set;

PRINT N'';
PRINT N'==================== 92 核对结束（未写入任何数据） ====================';
GO
