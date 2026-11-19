/* ============================================================================
   05_merge_stg_to_user.sql  —— AD 名单暂存表 → 中央人员表 的自动化合并脚本
   ----------------------------------------------------------------------------
   作用: 把 dbo.CN_AME_SSO_StgAdUser 的当日 AD 名单，幂等合并进
         dbo.CN_AME_SSO_User（中央人员唯一事实来源）。
   产物: 一份可重复执行、失败整体回滚、带批次号与执行日志的 T-SQL 实现。

   设计依据（仓库内既有口径，不新造规则）:
     - 合并规则原文: 统一身份认证实施方案_MSIA与BOL系统.md 第 4.3 节（L343-L380）
     - 已有 PowerShell 内嵌实现: scripts/powershell/sync_ad_to_sso.ps1
       Invoke-MergeCentralUser（L426-L483），本脚本是其 T-SQL 独立化版本
     - 危险项预检口径: scripts/sql/04_flip_manual_source.sql 第 1.1 节（L24-L36）
     - 大小写/归一化口径: scripts/sql/90_usermap_backfill.sql（L12-L16）、
       scripts/sql/91_usermap_integrity_checks.sql 第 4.2/6 节

   ----------------------------------------------------------------------------
   执行方式（先读这一段，能省掉 90% 的报错）
   ----------------------------------------------------------------------------
   方式 A（推荐）整篇执行: SSMS 打开本文件，直接按 F5（不要只选中某几行）。
       全部节在一次会话内连续执行，变量与临时表全程有效，最后停在“第 5 节 预览”，
       你看完结果再把第 6 节的 @Execute 改成 1 按 F5 执行第 6 节。

   方式 B 分段执行: 从第 3 节开始，每节都是独立批处理（GO 分隔），可以单独选中执行。
       必须同时满足:
         (1) 同一个 SSMS 窗口 / 同一条连接，不要关窗口、不要重连
             —— #norm / #reject / #plan 是临时表，只在本会话存活；
         (2) 按 3 → 4 → 5 → 6 的顺序跑，不能跳节；
         (3) 重跑第 3 节会重建 #norm 并清掉旧 #plan，之后必须重新跑 4 → 5 → 6。
       违反时脚本会主动报“未找到 #norm / #plan …”，不会再出现难懂的
       “Must declare the scalar variable”，见第 11 节。

   执行账号: 第 0 节需 ALTER 权限（ytview 或 DBA）；第 1 节起用 sso_sync_svc 亦可。

   ----------------------------------------------------------------------------
   ★ 待现场核对项（仓库 DDL 与实际生产库可能不一致，执行前必须先跑第 2 节）
   ----------------------------------------------------------------------------
     [P1] 生产库 CN_AME 是否存在列 CN_AME_SSO_User.last_batch_no
          → 本脚本第 0 节会自动补建；若生产不允许新增列，则把脚本里所有
            last_batch_no 相关 3 处赋值删掉（不影响合并结果，只丢批次追溯）。
     [P2] 生产库排序规则（CI 还是 CS）—— 直接决定“大小写重复”会不会自动被唯一键拦住
          → 第 2.1 节查询 SELECT collation_name FROM sys.databases WHERE name='CN_AME'
     [P3] 约束 UQ_CN_AME_SSO_User_Login / UQ_CN_AME_SSO_User_EmpNo 是否真实存在
          → 第 2.2 节查询；若生产缺少这两个唯一约束，本脚本的冲突闸门就是唯一防线，
            必须保留，不得图省事注释掉。
     [P4] StgAdUser 是否有唯一约束（仓库 DDL 只有普通索引 IX_..._EmpNo，无唯一约束）
          → 第 2.3 节查询；无唯一约束时，若 Stg 被人工/其它程序灌入重复工号，
            MERGE 会报 “同一行被多次更新” 而整体失败，本脚本已用去重层规避。
     [P5] AD 名单里 employeeNo 到底是真工号，还是等于登录名
          → 第 2.5 节查询 Stg 的 employee_no 与 login_name 是否恒等；
            这决定了 13 条种子会不会与 AD 名单“对不上人”（见第 4 节闸门 4）。
     [P6] ad_object_guid 是否恒为 NULL（现有 PowerShell 灌数固定写 DBNull）
          → 第 2.6 节查询；恒为 NULL 表示“工号复用防护”当前未启用。
     [P7] 计划任务 SSO_AD_Import 是否存在并每日执行，本机用
          schtasks /query /tn "SSO_AD_Import" 查看（见配套文档第 7 节）。
   ============================================================================ */

USE CN_AME;
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;   /* 任何运行期错误都让事务整体回滚，不留半批数据 */
GO

/* ============================================================================
   第 0 节  审计列补齐（只需成功执行一次；之后每次自动跳过）
   --------------------------------------------------------------------------
   新增 last_batch_no：记录该行最后被哪一个批次改写，便于回溯“谁把这行停用了”。
   created_at / updated_at / source / synced_at 四列仓库 DDL 已存在，不重复新增：
     03_seed_users.sql + 01_create_sso_tables.sql 中已定义
   ========================================================================== */
IF COL_LENGTH('dbo.CN_AME_SSO_User', 'last_batch_no') IS NULL
BEGIN
    ALTER TABLE dbo.CN_AME_SSO_User ADD last_batch_no NVARCHAR(32) NULL;
    PRINT N'[DDL] 已新增列 dbo.CN_AME_SSO_User.last_batch_no';
END
ELSE
    PRINT N'[DDL] last_batch_no 已存在，跳过';
GO


/* ============================================================================
   第 1 节  执行方式说明 + 前置列检查（本节没有任何参数）
   --------------------------------------------------------------------------
   ★ 本节不含 DECLARE。@Execute 这个唯一开关放在第 6 节，因为只有第 6 节会写库。
     第 5 节永远是只读预览，改它不会写数据。
   ========================================================================== */
IF COL_LENGTH('dbo.CN_AME_SSO_User', 'last_batch_no') IS NULL
    THROW 51000, N'缺少列 CN_AME_SSO_User.last_batch_no。请先用 ytview/DBA 执行本文件第 0 节。', 1;

PRINT N'==================== 05_merge_stg_to_user 开始 ====================';
GO


/* ============================================================================
   第 2 节  只读前置核查（每项都打印实际值；期望值写在注释里，不满足先别继续）
   --------------------------------------------------------------------------
   本节可单独执行，不依赖任何前置节。
   ========================================================================== */
PRINT N'';
PRINT N'--- 2.1 库排序规则（CS 表示区分大小写，CI 表示不区分） ---';
SELECT name, collation_name, compatibility_level
FROM sys.databases WHERE name = N'CN_AME';

PRINT N'--- 2.2 CN_AME_SSO_User 唯一约束与索引（期望: EmpNo/Login 两个 UNIQUE） ---';
SELECT i.name AS index_name, i.is_unique, i.type_desc,
       c.name AS key_column
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c        ON c.object_id  = i.object_id AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(N'dbo.CN_AME_SSO_User') AND ic.is_included_column = 0
ORDER BY i.name, ic.key_ordinal;

PRINT N'--- 2.3 CN_AME_SSO_StgAdUser 索引（期望: 无 UNIQUE；若生产有唯一键更好） ---';
SELECT i.name AS index_name, i.is_unique, i.type_desc
FROM sys.indexes i
WHERE i.object_id = OBJECT_ID(N'dbo.CN_AME_SSO_StgAdUser') AND i.type > 0;

PRINT N'--- 2.4 四表行数（Stg 是每日快照；User 是累计主表，两者本来就不等长） ---';
SELECT
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_StgAdUser) AS stg_rows,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User)      AS user_rows,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_UserMap)   AS map_rows,
    (SELECT COUNT(*) FROM dbo.CN_AME_SSO_PermLedger) AS perm_rows;

PRINT N'--- 2.5 Stg 的工号是否等于登录名（决定种子用户能否对上人） ---';
SELECT
    COUNT(*)                                              AS total,
    SUM(CASE WHEN employee_no = login_name THEN 1 ELSE 0 END) AS empno_eq_login,
    SUM(CASE WHEN CHARINDEX(N'\', login_name) > 0 THEN 1 ELSE 0 END) AS login_has_domain
FROM dbo.CN_AME_SSO_StgAdUser;

PRINT N'--- 2.6 Stg 的 ad_object_guid 是否有值（全空表示工号复用防护未启用） ---';
SELECT COUNT(*) AS total,
       SUM(CASE WHEN ad_object_guid IS NOT NULL THEN 1 ELSE 0 END) AS guid_filled
FROM dbo.CN_AME_SSO_StgAdUser;

PRINT N'--- 2.7 最近 20 条同步日志（关键: 有没有 phase=MERGE 且 status=OK 的行） ---';
SELECT TOP 20 id, phase, src_rows, added, updated, disabled, reactivated, status, message, run_at
FROM dbo.CN_AME_SSO_SyncLog
ORDER BY id DESC;

PRINT N'--- 2.8 当前 13 条的来源分布（MANUAL 表示 04 脚本还没执行） ---';
SELECT source, status, COUNT(*) AS cnt
FROM dbo.CN_AME_SSO_User
GROUP BY source, status
ORDER BY source, status;

PRINT N'--- 2.9 本次登录账号对三张表的权限（期望: User=INSERT/UPDATE/SELECT） ---';
SELECT p.permission_name, p.state_desc, o.name AS object_name
FROM sys.database_permissions p
JOIN sys.objects o ON o.object_id = p.major_id
WHERE p.grantee_principal_id = DATABASE_PRINCIPAL_ID()
  AND o.name LIKE N'CN_AME_SSO_%'
ORDER BY o.name, p.permission_name;
GO


/* ============================================================================
   第 3 节  归一化 + 去重 + 拒绝集（只读 Stg，不写任何业务表）
   --------------------------------------------------------------------------
   ★ 本节自包含，可单独执行；产出的 #norm / #reject 供第 4/5/6 节使用。
     重跑本节会先 DROP 再重建，并清掉旧 #plan（防止拿旧预览数字去提交）。
   归一化口径（与 90_usermap_backfill.sql L12-L16、91 第 5 节保持一致）:
     normalized = LOWER(LTRIM(RTRIM(去掉 "DOMAIN\" 前缀)))
   必须归一的原因（三条，均为仓库内已发生的事实）:
     1) AD 常见 DOMAIN\ligu 形式；Keycloak username 不支持反斜杠，
        不剥离会直接建出 "domain\ligu" 这种无法登录的账号。
     2) SQL Server 唯一约束是否拦得住 Zhangy4 / zhangy4 取决于库排序规则
        （[P2]），CS 库下两者是两行 → 同一人两个账号。归一后只可能落一行。
     3) Keycloak 侧 username 查找走 exact=true，大小写不一致就查不到旧账号，
        每次同步都会“新建”，形成重复号。BOL 的 Yaolei 与 MSIA 的 yaole
        就是仓库里已记录的真实案例（03_seed_users.sql L131-L145）。
   ========================================================================== */
IF OBJECT_ID(N'tempdb..#norm')   IS NOT NULL DROP TABLE #norm;
IF OBJECT_ID(N'tempdb..#reject') IS NOT NULL DROP TABLE #reject;
IF OBJECT_ID(N'tempdb..#plan')   IS NOT NULL DROP TABLE #plan;

CREATE TABLE #norm (
    row_no        INT IDENTITY(1,1) PRIMARY KEY,
    employee_no   NVARCHAR(32)  NOT NULL,
    login_name    NVARCHAR(64)  NOT NULL,
    display_name  NVARCHAR(128) NULL,
    email         NVARCHAR(128) NULL,
    mobile        NVARCHAR(32)  NULL,
    dept_code     NVARCHAR(64)  NULL,
    dept_name     NVARCHAR(128) NULL,
    title         NVARCHAR(128) NULL,
    status        TINYINT       NOT NULL,
    ad_object_guid UNIQUEIDENTIFIER NULL,
    src_employee_no NVARCHAR(64) NULL,
    src_login_name  NVARCHAR(128) NULL
);

CREATE TABLE #reject (
    reason        NVARCHAR(64)  NOT NULL,
    key_value     NVARCHAR(256) NULL,
    src_employee_no NVARCHAR(64) NULL,
    src_login_name  NVARCHAR(128) NULL
);

/* 3.1 归一化后落入 #norm；登录名为空的整行拒绝（不能建成 Keycloak 账号） */
;WITH base AS (
    SELECT
        /* 工号：去域前缀 → LOWER → 去首尾空格 */
        LOWER(LTRIM(RTRIM(
            CASE WHEN CHARINDEX(N'\', ISNULL(s.employee_no, N'')) > 0
                 THEN SUBSTRING(s.employee_no, CHARINDEX(N'\', s.employee_no) + 1, 4000)
                 ELSE ISNULL(s.employee_no, N'') END)))                AS emp_norm,
        /* 登录名：同上 */
        LOWER(LTRIM(RTRIM(
            CASE WHEN CHARINDEX(N'\', ISNULL(s.login_name, N'')) > 0
                 THEN SUBSTRING(s.login_name, CHARINDEX(N'\', s.login_name) + 1, 4000)
                 ELSE ISNULL(s.login_name, N'') END)))                 AS login_norm,
        s.*
    FROM dbo.CN_AME_SSO_StgAdUser s
)
INSERT INTO #norm (employee_no, login_name, display_name, email, mobile,
                   dept_code, dept_name, title, status, ad_object_guid,
                   src_employee_no, src_login_name)
SELECT
    /* 工号缺失时回落为登录名 —— 与 sync_ad_to_sso.ps1 的 12.3 修订口径一致（L321-L324） */
    CASE WHEN b.emp_norm = N'' THEN b.login_norm ELSE b.emp_norm END,
    b.login_norm,
    NULLIF(LTRIM(RTRIM(b.display_name)), N''),
    NULLIF(LTRIM(RTRIM(b.email)), N''),
    NULLIF(LTRIM(RTRIM(b.mobile)), N''),
    NULLIF(LTRIM(RTRIM(b.dept_code)), N''),
    NULLIF(LTRIM(RTRIM(b.dept_name)), N''),
    NULLIF(LTRIM(RTRIM(b.title)), N''),
    CASE WHEN b.status = 0 THEN 0 ELSE 1 END,
    b.ad_object_guid,
    b.employee_no,
    b.login_name
FROM base b
WHERE b.login_norm <> N''
  AND LEN(b.login_norm)     <= 64     /* 系统边界校验：超长会静默截断成两个人 */
  AND LEN(CASE WHEN b.emp_norm = N'' THEN b.login_norm ELSE b.emp_norm END) <= 32;

/* 3.2 记录被丢弃的行，便于人工找 IT 修名单
      （括号层级: LEN( LOWER( LTRIM( RTRIM( CASE…END ) ) ) ) —— 共 4 层） */
INSERT INTO #reject (reason, key_value, src_employee_no, src_login_name)
SELECT N'登录名为空或超长', NULL, s.employee_no, s.login_name
FROM dbo.CN_AME_SSO_StgAdUser s
WHERE LTRIM(RTRIM(ISNULL(s.login_name, N''))) = N''
   OR LEN(LOWER(LTRIM(RTRIM(
          CASE WHEN CHARINDEX(N'\', ISNULL(s.login_name, N'')) > 0
               THEN SUBSTRING(s.login_name, CHARINDEX(N'\', s.login_name) + 1, 4000)
               ELSE ISNULL(s.login_name, N'') END)))) > 64;

/* 3.3 归一后重复：同一工号或同一登录名出现多次
      保留规则（确定性，不随机）: 在职优先 → 工号字典序 → 原始行序
      （口径是“宁可留下在职的那条”，避免把在职员工当重复丢掉） */
DECLARE @dups TABLE (row_no INT PRIMARY KEY, reason NVARCHAR(64));

;WITH d AS (
    SELECT row_no,
           ROW_NUMBER() OVER (PARTITION BY employee_no ORDER BY status DESC, login_name, row_no) AS rn_emp,
           ROW_NUMBER() OVER (PARTITION BY login_name ORDER BY status DESC, employee_no, row_no) AS rn_login
    FROM #norm
)
INSERT INTO @dups (row_no, reason)
SELECT row_no, CASE WHEN rn_emp > 1 THEN N'工号重复' ELSE N'登录名重复' END
FROM d WHERE rn_emp > 1 OR rn_login > 1;

INSERT INTO #reject (reason, key_value, src_employee_no, src_login_name)
SELECT d.reason, n.employee_no, n.src_employee_no, n.src_login_name
FROM @dups d JOIN #norm n ON n.row_no = d.row_no;

DELETE n FROM #norm n JOIN @dups d ON d.row_no = n.row_no;

/* 3.4 本节结束时的自检输出（第 4/5 节会各自重新统计，不依赖这几个变量） */
SELECT (SELECT COUNT(*) FROM #norm)   AS stg_effective_rows,
       (SELECT COUNT(*) FROM #reject) AS rejected_rows;
GO


/* ============================================================================
   第 4 节  闸门检查（任一不通过 → 中止，且不写任何业务数据）
   --------------------------------------------------------------------------
   ★ 本节自包含（只依赖第 3 节的 #norm / #reject）。
   闸门 1: 归一后有效行为 0
   闸门 2: 行数骤降 > 30%（对比上一次成功批次的 src_rows）
   闸门 3: 停用占比 > 10%
   闸门 4: 登录名撞人 —— Stg 的登录名在中央表已存在、但工号不同
           （这正是 04_flip_manual_source.sql L24-L36 标为“危险项”的场景:
             直接 MERGE 会撞 UQ_CN_AME_SSO_User_Login 让整条语句报错回滚，
             结果就是“Stg 一千多条、主表一条没进”）
   闸门 5: 中央表自身存在仅大小写不同的重复工号
   ========================================================================== */
DECLARE @RowDropAbortRatio  DECIMAL(5,2) = 0.30;   /* 改阈值只需改本节 */
DECLARE @DisabledAbortRatio DECIMAL(5,2) = 0.10;
DECLARE @SampleMax          INT          = 50;     /* 只影响打印条数 */

DECLARE @Now   DATETIME2(0) = SYSUTCDATETIME();
DECLARE @Batch NVARCHAR(32) =
        CONVERT(CHAR(8),  @Now, 112) + N'-' +
        REPLACE(CONVERT(CHAR(8), @Now, 108), N':', N'');

DECLARE @src_rows INT, @rejects INT;
DECLARE @prev_rows INT = NULL;
DECLARE @disabled_rows INT = 0;
DECLARE @collisions INT = 0;
DECLARE @dup_emp_central INT = 0;
DECLARE @abort_reason NVARCHAR(2000) = NULL;

/* 前置守卫：把“找不到临时表”翻译成能照做的提示 */
IF OBJECT_ID(N'tempdb..#norm') IS NULL
    THROW 51010, N'未找到临时表 #norm。临时表只在同一会话有效：请在同一 SSMS 窗口按 3 → 4 → 5 → 6 顺序执行，不要关窗口或重连。', 1;

SELECT @src_rows = COUNT(*) FROM #norm;
SELECT @rejects  = COUNT(*) FROM #reject;

IF @src_rows = 0
    SET @abort_reason = N'归一化后有效行为 0（登录名全空或全部重复）';

/* 闸门 2: 与上次成功批次的源行数比较 */
SELECT @prev_rows = src_rows
FROM (
    SELECT TOP 1 src_rows
    FROM dbo.CN_AME_SSO_SyncLog
    WHERE phase IN (N'MERGE', N'LOAD') AND status = N'OK' AND src_rows IS NOT NULL AND src_rows > 0
    ORDER BY id DESC
) t;

IF @abort_reason IS NULL AND @prev_rows IS NOT NULL
   AND @src_rows < @prev_rows * (1 - @RowDropAbortRatio)
    SET @abort_reason = CONCAT(N'行数骤降: 本次 ', @src_rows, N' 行 vs 上次 ', @prev_rows,
                               N' 行，超过 ', CONVERT(NVARCHAR(10), @RowDropAbortRatio * 100), N'% 阈值');

/* 闸门 3: 停用占比 */
SELECT @disabled_rows = COUNT(*) FROM #norm WHERE status = 0;
IF @abort_reason IS NULL AND @src_rows > 0
   AND CAST(@disabled_rows AS DECIMAL(10,4)) / @src_rows > @DisabledAbortRatio
    SET @abort_reason = CONCAT(N'停用占比过高: ', @disabled_rows, N'/', @src_rows, N'，超过 ',
                               CONVERT(NVARCHAR(10), @DisabledAbortRatio * 100), N'% 阈值');

/* 闸门 4: 登录名撞人（两侧都用 LOWER 比较，比 CS 库的唯一键更严） */
SELECT @collisions = COUNT(*)
FROM #norm n
JOIN dbo.CN_AME_SSO_User u ON LOWER(u.login_name) = n.login_name
WHERE LOWER(LTRIM(RTRIM(u.employee_no))) <> n.employee_no;

IF @abort_reason IS NULL AND @collisions > 0
    SET @abort_reason = CONCAT(N'登录名撞人 ', @collisions,
                               N' 条: 名单里的登录名在中央表已存在、但工号不同。见下方明细，需人工裁决');

/* 闸门 5: 中央表自身存在仅大小写不同的重复工号（只有 _CS 排序规则下才可能出现）。
   一旦存在，下面按 LOWER 匹配的 MERGE 会命中两行，报“同一行被多次更新”后整体失败。
   这是历史遗留数据问题，必须人工裁决，不能自动合并。 */
SELECT @dup_emp_central = COUNT(*)
FROM (
    SELECT LOWER(LTRIM(RTRIM(employee_no))) AS k
    FROM dbo.CN_AME_SSO_User
    GROUP BY LOWER(LTRIM(RTRIM(employee_no)))
    HAVING COUNT(*) > 1
) d;

IF @abort_reason IS NULL AND @dup_emp_central > 0
    SET @abort_reason = CONCAT(N'中央表存在仅大小写不同的重复工号 ', @dup_emp_central,
                               N' 组，需人工裁决后再合并（同类大小写问题的查询口径见 91_usermap_integrity_checks.sql 第 6 节）');

IF @abort_reason IS NOT NULL
BEGIN
    PRINT N'';
    PRINT N'[中止] 闸门检查未通过: ' + @abort_reason;

    IF @collisions > 0
    BEGIN
        PRINT N'--- 撞人明细（三选一处理: ①让 IT 修 AD 名单工号；②以 AD 为准把中央表 employee_no 对齐；③确认是同一人后由 DBA 手工合并） ---';
        SELECT TOP (@SampleMax)
               n.login_name, n.employee_no AS stg_emp, u.employee_no AS central_emp,
               u.source, u.status, u.created_at
        FROM #norm n
        JOIN dbo.CN_AME_SSO_User u ON LOWER(u.login_name) = n.login_name
        WHERE LOWER(LTRIM(RTRIM(u.employee_no))) <> n.employee_no
        ORDER BY n.login_name;
    END

    IF @rejects > 0
    BEGIN
        PRINT N'--- 被拒绝行明细 ---';
        SELECT TOP (@SampleMax) reason, key_value, src_employee_no, src_login_name
        FROM #reject ORDER BY reason, src_login_name;
    END

    /* 中止也写一条日志，便于事后判断“今天为什么没合并” */
    INSERT INTO dbo.CN_AME_SSO_SyncLog (phase, src_rows, added, updated, disabled, reactivated, status, message)
    VALUES (N'MERGE', @src_rows, 0, 0, 0, 0, N'ABORTED', LEFT(CONCAT(N'batch=', @Batch, N'; ', @abort_reason), 2000));

    THROW 51001, @abort_reason, 1;
END

PRINT N'';
PRINT N'[闸门] 全部通过。有效行=' + CONVERT(NVARCHAR(20), @src_rows)
      + N'，拒绝行=' + CONVERT(NVARCHAR(20), @rejects)
      + N'，停用标记=' + CONVERT(NVARCHAR(20), @disabled_rows);
GO


/* ============================================================================
   第 5 节  预览（永远只读，不写任何业务数据）
   --------------------------------------------------------------------------
   ★ 本节自包含（只依赖第 3 节的 #norm / #reject），可单独执行，也可反复执行。
     结果会写入 #plan，供第 6 节的“提交前自检”使用（保证预览与实跑同一口径）。
   ========================================================================== */
DECLARE @SampleMax INT = 50;   /* 只影响打印条数，与第 4 节无关 */

DECLARE @src_rows INT, @rejects INT, @prev_rows INT;
DECLARE @disabled_rows INT = 0;
DECLARE @will_ins INT, @will_upd INT, @will_dis INT, @will_manual INT;

IF OBJECT_ID(N'tempdb..#norm') IS NULL
    THROW 51010, N'未找到临时表 #norm。临时表只在同一会话有效：请在同一 SSMS 窗口按 3 → 4 → 5 → 6 顺序执行，不要关窗口或重连。', 1;

IF OBJECT_ID(N'tempdb..#plan') IS NOT NULL DROP TABLE #plan;

SELECT @src_rows = COUNT(*) FROM #norm;
SELECT @rejects  = COUNT(*) FROM #reject;
SELECT @disabled_rows = COUNT(*) FROM #norm WHERE status = 0;

SELECT @prev_rows = src_rows
FROM (
    SELECT TOP 1 src_rows
    FROM dbo.CN_AME_SSO_SyncLog
    WHERE phase IN (N'MERGE', N'LOAD') AND status = N'OK' AND src_rows IS NOT NULL AND src_rows > 0
    ORDER BY id DESC
) t;

SELECT @will_ins = COUNT(*)
FROM #norm n
WHERE NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                  WHERE LOWER(LTRIM(RTRIM(u.employee_no))) = n.employee_no);

SELECT @will_upd = COUNT(*)
FROM #norm n
JOIN dbo.CN_AME_SSO_User u ON LOWER(LTRIM(RTRIM(u.employee_no))) = n.employee_no
WHERE u.source <> N'MANUAL'
  AND (
        ISNULL(u.display_name, N'') <> ISNULL(COALESCE(n.display_name, u.display_name), N'')
     OR ISNULL(u.email, N'')        <> ISNULL(COALESCE(n.email,        u.email), N'')
     OR ISNULL(u.mobile, N'')       <> ISNULL(COALESCE(n.mobile,       u.mobile), N'')
     OR ISNULL(u.dept_code, N'')    <> ISNULL(COALESCE(n.dept_code,    u.dept_code), N'')
     OR ISNULL(u.dept_name, N'')    <> ISNULL(COALESCE(n.dept_name,    u.dept_name), N'')
     OR ISNULL(u.title, N'')        <> ISNULL(COALESCE(n.title,        u.title), N'')
     OR u.status <> n.status
     OR (n.ad_object_guid IS NOT NULL AND ISNULL(u.ad_object_guid, '00000000-0000-0000-0000-000000000000')
                                              <> n.ad_object_guid)
     );

/* 将被停用 = 主表在职且非 MANUAL，但不在本次名单里 */
SELECT @will_dis = COUNT(*)
FROM dbo.CN_AME_SSO_User u
WHERE u.status = 1 AND u.source <> N'MANUAL'
  AND NOT EXISTS (SELECT 1 FROM #norm n WHERE n.employee_no = LOWER(LTRIM(RTRIM(u.employee_no))));

/* 保留不动 = MANUAL 行（AD 同步永不覆盖、永不自动停用） */
SELECT @will_manual = COUNT(*)
FROM dbo.CN_AME_SSO_User u
WHERE u.source = N'MANUAL'
  AND NOT EXISTS (SELECT 1 FROM #norm n WHERE n.employee_no = LOWER(LTRIM(RTRIM(u.employee_no))));

CREATE TABLE #plan (
    computed_at   DATETIME2(0) NOT NULL,
    src_rows      INT NOT NULL,
    rejected_rows INT NOT NULL,
    disabled_rows INT NOT NULL,
    prev_rows     INT NULL,
    will_ins      INT NOT NULL,
    will_upd      INT NOT NULL,
    will_dis      INT NOT NULL,
    will_manual   INT NOT NULL
);

INSERT INTO #plan (computed_at, src_rows, rejected_rows, disabled_rows, prev_rows,
                   will_ins, will_upd, will_dis, will_manual)
VALUES (SYSUTCDATETIME(), @src_rows, @rejects, @disabled_rows, @prev_rows,
        @will_ins, @will_upd, @will_dis, @will_manual);

PRINT N'';
PRINT N'--- 5.1 合并预览 ---';
SELECT computed_at, src_rows AS stg_effective_rows, will_ins AS would_insert,
       will_upd AS would_update, will_dis AS would_disable,
       will_manual AS manual_protected, rejected_rows, prev_rows AS prev_success_rows
FROM #plan;

PRINT N'--- 5.2 将被停用的账号（上线前必须逐行业务确认；测试账号属预期） ---';
SELECT TOP (@SampleMax) u.login_name, u.display_name, u.employee_no, u.source, u.synced_at
FROM dbo.CN_AME_SSO_User u
WHERE u.status = 1 AND u.source <> N'MANUAL'
  AND NOT EXISTS (SELECT 1 FROM #norm n WHERE n.employee_no = LOWER(LTRIM(RTRIM(u.employee_no))))
ORDER BY u.login_name;

IF @rejects > 0
BEGIN
    PRINT N'--- 5.3 被拒绝行（不会进主表，需 IT 修名单后重跑第 3 节） ---';
    SELECT TOP (@SampleMax) reason, key_value, src_employee_no, src_login_name
    FROM #reject ORDER BY reason, src_login_name;
END

PRINT N'';
PRINT N'==================== 预览结束（未写入任何数据） ====================';
PRINT N'确认 5.2 的停用名单与 5.1 的计数无误后，把第 6 节的 @Execute 改为 1 再执行第 6 节。';
GO


/* ============================================================================
   第 6 节  正式合并（单事务；失败整体回滚；并发互斥）
   --------------------------------------------------------------------------
   ★ 唯一的执行开关在本节: @Execute = 0 时本节只打印提示并退出，不连库写。
     本节依赖第 3 节的 #norm / #reject 与第 5 节的 #plan（预览数字用于提交前自检），
     所以必须按 3 → 5 → 6 的顺序执行。
   幂等性: 以 employee_no 为匹配键、以归一后的值为目标值，重复执行结果一致。
   事务边界: 抢锁 → 开始事务 → MERGE → 校验 → 写 SyncLog → 提交；
             任一步出错整批回滚，不会出现“进了一半”的中间态。
   ========================================================================== */
DECLARE @Execute BIT = 0;      /* ← 0=不执行；确认预览无误后改成 1 */

DECLARE @Now   DATETIME2(0) = SYSUTCDATETIME();
DECLARE @Batch NVARCHAR(32) =
        CONVERT(CHAR(8),  @Now, 112) + N'-' +
        REPLACE(CONVERT(CHAR(8), @Now, 108), N':', N'');

DECLARE @src_rows INT, @rejects INT, @disabled_rows INT;
DECLARE @will_ins INT, @will_upd INT, @will_dis INT;
DECLARE @ins INT = 0, @upd INT = 0, @dis INT = 0, @react INT = 0;

IF OBJECT_ID(N'tempdb..#norm') IS NULL
    THROW 51010, N'未找到临时表 #norm。临时表只在同一会话有效：请在同一 SSMS 窗口按 3 → 4 → 5 → 6 顺序执行，不要关窗口或重连。', 1;

IF OBJECT_ID(N'tempdb..#plan') IS NULL
    THROW 51011, N'未找到临时表 #plan。请先执行第 5 节（预览会算出预期影响行数，本节的提交前自检要用它），再执行本节。', 1;

SELECT @will_ins = will_ins, @will_upd = will_upd, @will_dis = will_dis,
       @src_rows = src_rows, @rejects = rejected_rows, @disabled_rows = disabled_rows
FROM #plan;

SELECT @rejects = COUNT(*) FROM #reject;

IF @Execute = 0
BEGIN
    PRINT N'';
    PRINT N'==================== 第 6 节未执行（@Execute = 0）====================';
    PRINT N'预览数字: 有效行=' + CONVERT(NVARCHAR(20), @src_rows)
          + N'，将新增=' + CONVERT(NVARCHAR(20), @will_ins)
          + N'，将更新=' + CONVERT(NVARCHAR(20), @will_upd)
          + N'，将停用=' + CONVERT(NVARCHAR(20), @will_dis)
          + N'，拒绝=' + CONVERT(NVARCHAR(20), @rejects);
    PRINT N'确认无误后把本节的 @Execute 改为 1，再执行本节。';
    RETURN;
END

PRINT N'批次号: ' + @Batch + N'   模式: 正式执行';

BEGIN TRY
    BEGIN TRANSACTION;

    /* 6.1 抢占应用锁（同一时刻只允许一个合并批次） */
    DECLARE @lock_rc INT;
    EXEC @lock_rc = sp_getapplock
            @Resource    = N'CN_AME_SSO_User_MERGE',
            @LockMode    = N'Exclusive',
            @LockOwner   = N'Transaction',
            @LockTimeout = 0;
    IF @lock_rc < 0
        THROW 51002, N'另一个合并批次正在运行（未拿到 CN_AME_SSO_User_MERGE 锁），本次退出。', 1;

    /* 6.2 MERGE：唯一实现口径
         - 匹配键 employee_no
         - 禁止改写 login_name（变更走“停旧建新”）
         - source='MANUAL' 行不覆盖、不停用
         - 目标值用 COALESCE：名单里某字段为空时不覆盖主表已有值（含邮箱策略） */
    DECLARE @out TABLE (action NVARCHAR(10), new_status TINYINT, old_status TINYINT);

    MERGE dbo.CN_AME_SSO_User AS t
    USING #norm AS s
       /* 匹配键用工号，且两侧统一归一后比较: 生产为 _CS 排序规则时，
          t 里若存成 'LIGU'、s 里是 'ligu'，精确比较会不命中 → 误判为新人，
          进而在 CS 库下绕过唯一键建出第二个账号（本项目已踩过的坑）。 */
       ON LOWER(LTRIM(RTRIM(t.employee_no))) = s.employee_no
    WHEN MATCHED AND (
            ISNULL(t.display_name, N'') <> ISNULL(COALESCE(s.display_name, t.display_name), N'')
         OR ISNULL(t.email, N'')        <> ISNULL(COALESCE(s.email,        t.email), N'')
         OR ISNULL(t.mobile, N'')       <> ISNULL(COALESCE(s.mobile,       t.mobile), N'')
         OR ISNULL(t.dept_code, N'')    <> ISNULL(COALESCE(s.dept_code,    t.dept_code), N'')
         OR ISNULL(t.dept_name, N'')    <> ISNULL(COALESCE(s.dept_name,    t.dept_name), N'')
         OR ISNULL(t.title, N'')        <> ISNULL(COALESCE(s.title,        t.title), N'')
         OR t.status <> s.status
         OR (s.ad_object_guid IS NOT NULL
             AND ISNULL(t.ad_object_guid, '00000000-0000-0000-0000-000000000000') <> s.ad_object_guid)
         )
       AND t.source <> N'MANUAL'
    THEN UPDATE SET
            t.display_name = COALESCE(s.display_name, t.display_name),
            t.email        = COALESCE(s.email,        t.email),
            t.mobile       = COALESCE(s.mobile,       t.mobile),
            t.dept_code    = COALESCE(s.dept_code,    t.dept_code),
            t.dept_name    = COALESCE(s.dept_name,    t.dept_name),
            t.title        = COALESCE(s.title,        t.title),
            t.status       = s.status,
            t.ad_object_guid = COALESCE(s.ad_object_guid, t.ad_object_guid),
            t.source       = N'AD',
            t.synced_at    = @Now,
            t.updated_at   = @Now,
            t.last_batch_no = @Batch
            /* 故意不更新 login_name / kc_user_id：登录名变更走“停旧建新” */

    WHEN NOT MATCHED BY TARGET THEN
        INSERT (employee_no, login_name, display_name, email, mobile,
                dept_code, dept_name, title, status, ad_object_guid,
                source, pwd_set, synced_at, created_at, updated_at, last_batch_no)
        VALUES (s.employee_no, s.login_name, s.display_name, s.email, s.mobile,
                s.dept_code, s.dept_name, s.title, s.status, s.ad_object_guid,
                N'AD', 0, @Now, @Now, @Now, @Batch)

    /* 离职处置: 只停用不删除（保留历史关联: UserMap、PermLedger、KC 账号、日志） */
    WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> N'MANUAL' THEN
        UPDATE SET
            t.status        = 0,
            t.synced_at     = @Now,
            t.updated_at    = @Now,
            t.last_batch_no = @Batch
    OUTPUT $action, inserted.status, deleted.status INTO @out;

    /* 6.3 结果统计 */
    SELECT @ins   = SUM(CASE WHEN action = N'INSERT' THEN 1 ELSE 0 END),
           @upd   = SUM(CASE WHEN action = N'UPDATE' AND new_status = 1 AND old_status = 1 THEN 1 ELSE 0 END),
           @dis   = SUM(CASE WHEN action = N'UPDATE' AND new_status = 0 THEN 1 ELSE 0 END),
           @react = SUM(CASE WHEN action = N'UPDATE' AND new_status = 1 AND old_status = 0 THEN 1 ELSE 0 END)
    FROM @out;

    /* 6.4 提交前自检: 本批次应写入的行数必须与预览一致（防止中途被人改 Stg） */
    DECLARE @touched INT = (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE last_batch_no = @Batch);
    IF @touched <> @will_ins + @will_upd + @will_dis
        THROW 51003, N'提交前自检失败: 本批次预计影响行数与实际不一致（预览后有人改动了 Stg？），已回滚。', 1;

    /* 6.5 审计日志（phase='MERGE'，与 ps1 同一套日志表，便于统一监控 SQL） */
    INSERT INTO dbo.CN_AME_SSO_SyncLog
        (phase, src_rows, added, updated, disabled, reactivated, status, message)
    VALUES (N'MERGE', @src_rows, ISNULL(@ins, 0), ISNULL(@upd, 0), ISNULL(@dis, 0), ISNULL(@react, 0), N'OK',
            LEFT(CONCAT(N'batch=', @Batch, N'; 源行=', @src_rows, N'; 拒绝=', @rejects,
                        N'; 停用=', @disabled_rows, N'; 明细见 User.last_batch_no'), 2000));

    COMMIT TRANSACTION;

    PRINT N'';
    PRINT N'--- 6.6 合并完成 ---';
    SELECT @Batch AS batch_no, @src_rows AS stg_effective_rows,
           ISNULL(@ins, 0) AS added, ISNULL(@upd, 0) AS updated,
           ISNULL(@dis, 0) AS disabled, ISNULL(@react, 0) AS reactivated,
           @rejects AS rejected_rows;

    SELECT source, status, COUNT(*) AS cnt
    FROM dbo.CN_AME_SSO_User
    GROUP BY source, status
    ORDER BY source, status;

    PRINT N'==================== 正式合并结束（已提交） ====================';
    PRINT N'下一步: 跑 scripts/powershell/sync_sso_to_keycloak.ps1 把新增用户同步到 Keycloak。';
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

    DECLARE @err NVARCHAR(2048) = LEFT(ERROR_MESSAGE(), 2000);

    /* 失败日志必须写在事务外，否则会随回滚一起消失 */
    BEGIN TRY
        INSERT INTO dbo.CN_AME_SSO_SyncLog
            (phase, src_rows, added, updated, disabled, reactivated, status, message)
        VALUES (N'MERGE', @src_rows, 0, 0, 0, 0, N'ERROR',
                LEFT(CONCAT(N'batch=', @Batch, N'; ', @err), 2000));
    END TRY
    BEGIN CATCH
        PRINT N'[警告] 失败日志写入也失败了: ' + ERROR_MESSAGE();
    END CATCH

    PRINT N'[失败] 已整体回滚，主表未产生任何部分写入。原因: ' + @err;
    THROW;
END CATCH
GO
