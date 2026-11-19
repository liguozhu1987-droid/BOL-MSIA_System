/* ============================================================================
   06_merge_stg_to_user_proc.sql  —— Stg → 中央人员表 合并的存储过程版（生产入口）
   ----------------------------------------------------------------------------
   过程: dbo.usp_SSO_MergeStgToUser(@Execute, @BatchNo, @SampleMax, @StgWaitSeconds)
   作用: 与 05_merge_stg_to_user.sql 逻辑一致（归一化 → 拒绝集 → 5 道闸门 →
         MERGE → 停用 → 审计字段 → 事务 → SyncLog），但合并成单批、可参数化，
         供 SQL Server Agent 直接挂作业（配套 07_merge_job_setup.sql）。

   为什么要有这一版:
     - 05 是按 GO 分 7 批的“人读脚本”，只能人工在 SSMS 里整篇/分段跑；
       Agent 作业需要一个可重复调用的入口，且失败必须让作业显示失败。
     - 本过程内**不出现任何 GO**，变量与临时表在同一批内全程有效。

   两种模式:
     @Execute = 0（默认）干跑: 只读 Stg 与主表，算归一化/拒绝/闸门/预览；
                              唯一写入是往运行记录表 CN_AME_SSO_MergeRun 追加 1 行
                              （不写业务表、不写 SyncLog）；闸门不通过也不抛错，
                              用 gate_status='ABORT' 体现。
     @Execute = 1 实跑: 闸门不通过 → 落运行记录（ABORT）+ 写 ABORTED 日志后 THROW；
                        通过则在单事务内 MERGE，提交后落运行记录（OK）；
                        任何运行期错误 ROLLBACK + 落运行记录（ERROR）+ THROW。

   共用前置守卫（与模式无关，按下列顺序执行，命中即终止）:
     51007 外层事务 @@TRANCOUNT > 0   → 拒绝调用，不落行（否则记录会随外层回滚消失）
     51004 @BatchNo 超过 32 字符      → 不落行（超长值装不进 batch_no NVARCHAR(32)）
     51009 自动批次号同秒重复提交      → 不落行（防护见“0. 入参规范化”）
     51008 Stg 装载未稳定             → 落 1 行 ERROR + 写 SyncLog(ERROR) 后 THROW

   ★ 一次调用只落 1 行: 四条终止路径（干跑 / ABORT / 成功 / ERROR）互斥、无穿透。
     同一 batch_no 出现两行，只能是两次独立调用（自动批次号按秒生成），
     而不是一次调用内部插了两次；判读方法见文档 §13.7.8。

   运行记录（★ 2026-11-09 新增）:
     dbo.CN_AME_SSO_MergeRun —— 每次执行（干跑/实跑/中止/报错）都**只 INSERT 一行**，
     把过程返回的汇总原样落表，并带 run_id、run_at、run_by、host_name。
     与 CN_AME_SSO_SyncLog 的分工: SyncLog 记“成败与异常事件”，MergeRun 记“每次运行的
     明细数字”，同一事实不重复记（MergeRun 不写 status=OK/ERROR 事件，SyncLog 不写明细列）。

   返回: 单一结果集（1 行，就是刚插入的那条运行记录），
         列顺序: run_id 在最前，其后保持原有字段顺序，末尾追加 run_at / run_by / host_name。

   权限: 调用方只需 EXECUTE（见 07 的 GRANT 说明；同库同 dbo 所有者，走所有权链）。
         例外: 若运行记录表尚不存在且由过程自己建，则本次调用还需要 CREATE TABLE；
               先用 DBA 执行下面“第 0 节”建表，之后作业账号就只需 EXECUTE。

   执行前提（首次部署）:
     1) 05 的第 0 节已跑过（CN_AME_SSO_User.last_batch_no 已存在）。业务表 DDL 不由本过程
        负责（它只兜底建运行记录表），缺列时直接 THROW 51000 并提示去跑 05 第 0 节。
     2) 五张表已按 01_create_sso_tables.sql 建好。
   待现场核对项与 05 相同（P1–P7，见 05 文件头），本过程不重复列出。
   ============================================================================ */

USE CN_AME;
GO

SET ANSI_NULLS ON;
GO

SET QUOTED_IDENTIFIER ON;
GO


/* ============================================================================
   第 0 节  运行记录表（只需成功执行一次；过程内也有同样的一份兜底 DDL）
   ----------------------------------------------------------------------------
   命名理由: 与既有 CN_AME_SSO_ 前缀对齐，后缀 MergeRun 表示“一次合并运行的明细”，
             与 CN_AME_SSO_SyncLog（事件流水）区分开。
   写入约定: 只 INSERT，永不 UPDATE / DELETE（保留策略只能由管理员手工执行）。
   ========================================================================== */
IF OBJECT_ID(N'dbo.CN_AME_SSO_MergeRun', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CN_AME_SSO_MergeRun (
        run_id                  BIGINT IDENTITY(1,1) NOT NULL
                                CONSTRAINT PK_CN_AME_SSO_MergeRun PRIMARY KEY,
        batch_no                NVARCHAR(32)   NOT NULL,
        executed                BIT            NOT NULL,   /* 0=干跑，1=实跑 */
        gate_status             NVARCHAR(16)   NOT NULL,   /* OK / ABORT / ERROR */
        gate_reason             NVARCHAR(2000) NULL,
        stg_effective_rows      INT            NULL,
        rejected_rows           INT            NULL,
        disabled_rows_in_source INT            NULL,
        manual_protected        INT            NULL,
        would_insert            INT            NULL,
        would_update            INT            NULL,
        would_disable           INT            NULL,
        added                   INT            NULL,
        updated                 INT            NULL,
        disabled                INT            NULL,
        reactivated             INT            NULL,
        prev_success_rows       INT            NULL,
        computed_at             DATETIME2(0)   NOT NULL,   /* 本次计算的 UTC 时刻 */
        run_at                  DATETIME2(0)   NOT NULL
                                CONSTRAINT DF_CN_AME_SSO_MergeRun_run_at DEFAULT (SYSUTCDATETIME()),
        run_by                  NVARCHAR(128)  NULL
                                CONSTRAINT DF_CN_AME_SSO_MergeRun_run_by  DEFAULT (SUSER_SNAME()),
        host_name               NVARCHAR(128)  NULL
                                CONSTRAINT DF_CN_AME_SSO_MergeRun_host    DEFAULT (HOST_NAME()),
        reject_sample           NVARCHAR(MAX)  NULL        /* 分隔串: reason + 空格 + login，以 " | " 连接 */
    );

    CREATE INDEX IX_CN_AME_SSO_MergeRun_RunAt
        ON dbo.CN_AME_SSO_MergeRun (run_at);

    PRINT N'[DDL] 已创建 dbo.CN_AME_SSO_MergeRun';
END
ELSE
    PRINT N'[DDL] dbo.CN_AME_SSO_MergeRun 已存在，跳过';
GO


CREATE OR ALTER PROCEDURE dbo.usp_SSO_MergeStgToUser
    @Execute   BIT           = 0,     /* 0=干跑（默认）；1=实跑写库 */
    @BatchNo   NVARCHAR(32)  = NULL,  /* 空则过程内生成 yyyyMMdd-HHmmss（UTC） */
    @SampleMax INT           = 50,    /* 汇总里 reject_sample 最多列多少条 */
    @StgWaitSeconds INT      = 2      /* Stg 装载稳定性预检的采样间隔秒；0=关闭（见 0.2 节） */
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;   /* 运行期错误让事务整体回滚，不留半批数据 */

    /* ------------------------------------------------------------------
       变量声明（单批内一次声明，全流程复用）
       ------------------------------------------------------------------ */
    DECLARE @Now     DATETIME2(0) = SYSUTCDATETIME();
    DECLARE @Batch   NVARCHAR(32);
    DECLARE @run_id  BIGINT;   /* 本次运行记录在 CN_AME_SSO_MergeRun 中的主键 */
    DECLARE @BatchAuto  BIT = 0;  /* 1=批次号由过程按秒自动生成（用于同秒重复提交防护 51009） */
    DECLARE @StgWaitSec INT;      /* 规范化后的 Stg 预检采样间隔（秒）；0=关闭预检 */

    DECLARE @src_rows        INT;
    DECLARE @rejects         INT;
    DECLARE @disabled_rows   INT = 0;
    DECLARE @prev_rows       INT = NULL;
    DECLARE @manual_protected INT = 0;

    DECLARE @would_ins  INT = 0;
    DECLARE @would_upd  INT = 0;
    DECLARE @would_dis  INT = 0;

    DECLARE @collisions        INT = 0;
    DECLARE @dup_emp_central   INT = 0;

    DECLARE @gate_status  NVARCHAR(16)   = N'OK';
    DECLARE @gate_reason  NVARCHAR(2000) = NULL;
    DECLARE @reject_sample NVARCHAR(2000) = NULL;

    DECLARE @ins   INT = 0;
    DECLARE @upd   INT = 0;
    DECLARE @dis   INT = 0;
    DECLARE @react INT = 0;

    /* 闸门阈值：与 05 第 4 节一致，改阈值只改这两行 */
    DECLARE @RowDropAbortRatio   DECIMAL(5,2) = 0.30;
    DECLARE @DisabledAbortRatio  DECIMAL(5,2) = 0.10;

    /* ------------------------------------------------------------------
       0.0 外层事务检查（★ 2026-11-09 新增）
           为什么要有: 运行记录是本轮审计事实，但 INSERT 无法逃出调用方的事务。
           若调用方外层还有未提交事务（手工 BEGIN TRAN、或会话开了
           IMPLICIT_TRANSACTIONS），ABORT/ERROR 行会随外层 ROLLBACK 一起消失，
           等于“失败却查不到记录”。这里直接拒绝，杜绝该场景。
           事务外调用时 @@TRANCOUNT 为 0，本检查不产生任何开销。
       ------------------------------------------------------------------ */
    IF @@TRANCOUNT > 0
        THROW 51007, N'检测到外层事务（@@TRANCOUNT > 0）：请在事务外调用本过程，否则运行记录会随外层回滚消失。若会话开启了 IMPLICIT_TRANSACTIONS，请先 SET IMPLICIT_TRANSACTIONS OFF 再调用。', 1;

    /* ------------------------------------------------------------------
       0.1 运行记录表兜底建表（与文件顶部“第 0 节”是同一份 DDL）
           为什么放过程内: 首次部署时即使管理员忘了先跑第 0 节，过程也能跑通，
           满足“表缺失时也能首次执行”的要求。
           代价: 第一个调用者需要 CREATE TABLE 权限；表建好后作业账号只需 EXECUTE。
           两份 DDL 必须保持一致，改表结构时两处同步改。
       ------------------------------------------------------------------ */
    IF OBJECT_ID(N'dbo.CN_AME_SSO_MergeRun', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.CN_AME_SSO_MergeRun (
            run_id                  BIGINT IDENTITY(1,1) NOT NULL
                                    CONSTRAINT PK_CN_AME_SSO_MergeRun PRIMARY KEY,
            batch_no                NVARCHAR(32)   NOT NULL,
            executed                BIT            NOT NULL,   /* 0=干跑，1=实跑 */
            gate_status             NVARCHAR(16)   NOT NULL,   /* OK / ABORT / ERROR */
            gate_reason             NVARCHAR(2000) NULL,
            stg_effective_rows      INT            NULL,
            rejected_rows           INT            NULL,
            disabled_rows_in_source INT            NULL,
            manual_protected        INT            NULL,
            would_insert            INT            NULL,
            would_update            INT            NULL,
            would_disable           INT            NULL,
            added                   INT            NULL,
            updated                 INT            NULL,
            disabled                INT            NULL,
            reactivated             INT            NULL,
            prev_success_rows       INT            NULL,
            computed_at             DATETIME2(0)   NOT NULL,   /* 本次计算的 UTC 时刻 */
            run_at                  DATETIME2(0)   NOT NULL
                                    CONSTRAINT DF_CN_AME_SSO_MergeRun_run_at DEFAULT (SYSUTCDATETIME()),
            run_by                  NVARCHAR(128)  NULL
                                    CONSTRAINT DF_CN_AME_SSO_MergeRun_run_by  DEFAULT (SUSER_SNAME()),
            host_name               NVARCHAR(128)  NULL
                                    CONSTRAINT DF_CN_AME_SSO_MergeRun_host    DEFAULT (HOST_NAME()),
            reject_sample           NVARCHAR(MAX)  NULL        /* 分隔串: reason + 空格 + login，以 " | " 连接 */
        );

        CREATE INDEX IX_CN_AME_SSO_MergeRun_RunAt
            ON dbo.CN_AME_SSO_MergeRun (run_at);

        PRINT N'[DDL] 过程内已创建 dbo.CN_AME_SSO_MergeRun';
    END

    /* ------------------------------------------------------------------
       0. 入参规范化
       ------------------------------------------------------------------ */
    IF @SampleMax IS NULL OR @SampleMax < 1 SET @SampleMax = 50;

    /* Stg 预检间隔: NULL/负数 → 2 秒；上限 10 秒（防止拖慢作业；WAITFOR 用 hh:mm:ss 定长格式） */
    IF @StgWaitSeconds IS NULL OR @StgWaitSeconds < 0 SET @StgWaitSeconds = 2;
    IF @StgWaitSeconds > 10 SET @StgWaitSeconds = 10;
    SET @StgWaitSec = @StgWaitSeconds;

    SET @Batch = NULLIF(LTRIM(RTRIM(@BatchNo)), N'');
    IF @Batch IS NULL
    BEGIN
        SET @BatchAuto = 1;   /* 自动批次号只有秒级精度：同一秒的两次调用会撞同一批次号 */
        SET @Batch = CONVERT(CHAR(8),  @Now, 112) + N'-' +
                     REPLACE(CONVERT(CHAR(8), @Now, 108), N':', N'');
    END
    IF LEN(@Batch) > 32
        /* 参数级错误: 超长值本身装不进 batch_no NVARCHAR(32)，故这一条不落运行记录 */
        THROW 51004, N'@BatchNo 超长（最大 32 字符）。', 1;

    /* 同秒重复提交防护（★ 2026-11-09 新增）
       为什么要有: 自动批次号 = yyyyMMdd-HHmmss，精度只有秒。同一秒内的第二次调用
       （连按两次执行、手工与作业同时触发、SSMS 重复提交）会生成完全相同的 batch_no，
       表现为“两条记录 batch_no 与 run_at 同秒”，极易被误读成“一次调用插了两行”。
       这里按“本表是否已有该批次号”直接拒绝：参数级拒绝、不落行（见文档 §13.7.7），
       让重复提交在入口失败，而不是留下两行同批次记录。
       显式传入 @BatchNo 不受此限（允许 ABORT 后用同一批次号重试）。 */
    IF @BatchAuto = 1
       AND EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_MergeRun WHERE batch_no = @Batch)
        THROW 51009, N'同一秒内已存在相同批次号的运行记录，疑似重复提交（连按两次执行，或手工与作业同时触发）。请确认后重试；确需在同一秒内跑第二次，请显式传入不同的 @BatchNo。', 1;

    /* 前置: last_batch_no 必须已存在（业务表结构不由本过程负责，避免要求 ALTER 权限） */
    IF COL_LENGTH('dbo.CN_AME_SSO_User', 'last_batch_no') IS NULL
    BEGIN
        INSERT INTO dbo.CN_AME_SSO_MergeRun
            (batch_no, executed, gate_status, gate_reason, computed_at)
        VALUES (@Batch, @Execute, N'ERROR',
                N'缺少列 CN_AME_SSO_User.last_batch_no，未开始计算', @Now);
        SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

        THROW 51000, N'缺少列 CN_AME_SSO_User.last_batch_no。请先用 ytview/DBA 执行 05_merge_stg_to_user.sql 第 0 节（或手工 ALTER TABLE dbo.CN_AME_SSO_User ADD last_batch_no NVARCHAR(32) NULL）。', 1;
    END

    /* 批次号唯一性: 实跑时若该批次号已被用过，提交前自检会算错，直接拒绝 */
    IF @Execute = 1
       AND EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE last_batch_no = @Batch)
    BEGIN
        INSERT INTO dbo.CN_AME_SSO_MergeRun
            (batch_no, executed, gate_status, gate_reason, computed_at)
        VALUES (@Batch, 1, N'ERROR',
                N'该 @BatchNo 已被历史批次使用，未开始计算', @Now);
        SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

        THROW 51006, N'该 @BatchNo 已被历史批次使用，请换一个批次号（或留空让过程自动生成）。', 1;
    END

    /* ------------------------------------------------------------------
       0.2 Stg 装载稳定性预检（★ 2026-11-09 新增）
           为什么要有: LOAD 端（sync_ad_to_sso.ps1 的 Invoke-StageLoad）是
           “DELETE 全清 + SqlBulkCopy”，两步之间没有任何锁；本过程的
           sp_getapplock 只保护 MERGE 本身，挡不住 LOAD 的写入窗口。
           若在装载中途读到 Stg，会看到 0/1/部分行，随后被闸门 2 误判成
           “行数骤降”而 ABORT（实测 run_id=14 就是 stg_effective_rows=1、
           would_disable=2729；若不拦，这 2729 人会被真停用）。
           这里用“间隔采样两次，计数与 MAX(loaded_at) 完全一致”判定装载已结束；
           仍变化则明确报 51008 并落 1 行 ERROR，而不是拿半成品去做闸门判定。
           代价: 最多 3 轮 × @StgWaitSeconds（默认 2 秒，最长约 6 秒）。
           关闭: @StgWaitSeconds = 0（确知无装载时，例如人工演练）。
           边界: 这是“尽力而为”的判定，不构成锁 —— 仍应遵守“合并与装载不可
           并行”的运维约束（文档 §13.7.9）；装载恰在两次采样之间开始的情况，
           由闸门 1（0 行）兜住，不会误停用。
       ------------------------------------------------------------------ */
    IF @StgWaitSec > 0
    BEGIN
        DECLARE @stg_delay  CHAR(8) =
                CONVERT(CHAR(8), DATEADD(SECOND, @StgWaitSec, CAST('00:00:00' AS DATETIME)), 108);
        DECLARE @stg_cnt    INT, @stg_ts    DATETIME2(0);
        DECLARE @stg_cnt2   INT, @stg_ts2   DATETIME2(0);
        DECLARE @stg_try    INT = 0;
        DECLARE @stg_stable BIT = 0;

        WHILE @stg_try < 3 AND @stg_stable = 0
        BEGIN
            SET @stg_try += 1;

            SELECT @stg_cnt = COUNT(*), @stg_ts = MAX(s.loaded_at)
            FROM dbo.CN_AME_SSO_StgAdUser s;

            WAITFOR DELAY @stg_delay;

            SELECT @stg_cnt2 = COUNT(*), @stg_ts2 = MAX(s.loaded_at)
            FROM dbo.CN_AME_SSO_StgAdUser s;

            /* 行数与最新 loaded_at 都不变才算稳定；空表两侧同为 1900-01-01 也算稳定 */
            IF @stg_cnt = @stg_cnt2
               AND ISNULL(@stg_ts,  CONVERT(DATETIME2(0), '19000101')) =
                   ISNULL(@stg_ts2, CONVERT(DATETIME2(0), '19000101'))
                SET @stg_stable = 1;
        END

        IF @stg_stable = 0
        BEGIN
            INSERT INTO dbo.CN_AME_SSO_MergeRun
                (batch_no, executed, gate_status, gate_reason, computed_at)
            VALUES (@Batch, @Execute, N'ERROR',
                    LEFT(CONCAT(N'Stg 装载未稳定: 连续采样 ', @stg_try,
                                N' 轮行数/loaded_at 仍在变化（末次 ', @stg_cnt2,
                                N' 行），已拒绝合并'), 2000),
                    @Now);
            SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

            INSERT INTO dbo.CN_AME_SSO_SyncLog
                (phase, src_rows, added, updated, disabled, reactivated, status, message)
            VALUES (N'MERGE', NULL, 0, 0, 0, 0, N'ERROR',
                    LEFT(CONCAT(N'batch=', @Batch, N'; run_id=', @run_id,
                                N'; Stg 装载未稳定，未执行合并'), 2000));

            PRINT N'[预检失败] Stg 装载未稳定（' + CONVERT(NVARCHAR(10), @stg_try)
                  + N' 轮采样仍在变化），已记运行记录 run_id='
                  + CONVERT(NVARCHAR(20), @run_id) + N'，未执行合并。';
            THROW 51008, N'Stg 装载仍在进行（行数或 loaded_at 连续变化），已拒绝合并以避免读到半成品。请等 AD 名单 LOAD 结束后重跑；确知无装载时可传 @StgWaitSeconds = 0 关闭预检。', 1;
        END
        ELSE
            PRINT N'[预检] Stg 稳定: ' + CONVERT(NVARCHAR(20), @stg_cnt)
                  + N' 行（采样 ' + CONVERT(NVARCHAR(10), @stg_try) + N' 轮）。';
    END

    /* ------------------------------------------------------------------
       1. 归一化 + 拒绝集 + 去重（只读 Stg，不写业务表）
          口径: normalized = LOWER(LTRIM(RTRIM(去掉 "DOMAIN\" 前缀)))
          与 90_usermap_backfill.sql L12-L16、91 第 5 节一致
       ------------------------------------------------------------------ */
    IF OBJECT_ID(N'tempdb..#norm')   IS NOT NULL DROP TABLE #norm;
    IF OBJECT_ID(N'tempdb..#reject') IS NOT NULL DROP TABLE #reject;

    CREATE TABLE #norm (
        row_no         INT IDENTITY(1,1) PRIMARY KEY,
        employee_no    NVARCHAR(32)  NOT NULL,
        login_name     NVARCHAR(64)  NOT NULL,
        display_name   NVARCHAR(128) NULL,
        email          NVARCHAR(128) NULL,
        mobile         NVARCHAR(32)  NULL,
        dept_code      NVARCHAR(64)  NULL,
        dept_name      NVARCHAR(128) NULL,
        title          NVARCHAR(128) NULL,
        status         TINYINT       NOT NULL,
        ad_object_guid UNIQUEIDENTIFIER NULL,
        src_employee_no NVARCHAR(64) NULL,
        src_login_name  NVARCHAR(128) NULL
    );

    CREATE TABLE #reject (
        reason          NVARCHAR(64)  NOT NULL,
        key_value       NVARCHAR(256) NULL,
        src_employee_no NVARCHAR(64) NULL,
        src_login_name  NVARCHAR(128) NULL
    );

    /* 1.1 归一化后落入 #norm；登录名为空/超长、工号超长的不接收 */
    ;WITH base AS (
        SELECT
            LOWER(LTRIM(RTRIM(
                CASE WHEN CHARINDEX(N'\', ISNULL(s.employee_no, N'')) > 0
                     THEN SUBSTRING(s.employee_no, CHARINDEX(N'\', s.employee_no) + 1, 4000)
                     ELSE ISNULL(s.employee_no, N'') END)))              AS emp_norm,
            LOWER(LTRIM(RTRIM(
                CASE WHEN CHARINDEX(N'\', ISNULL(s.login_name, N'')) > 0
                     THEN SUBSTRING(s.login_name, CHARINDEX(N'\', s.login_name) + 1, 4000)
                     ELSE ISNULL(s.login_name, N'') END)))               AS login_norm,
            s.*
        FROM dbo.CN_AME_SSO_StgAdUser s
    )
    INSERT INTO #norm (employee_no, login_name, display_name, email, mobile,
                       dept_code, dept_name, title, status, ad_object_guid,
                       src_employee_no, src_login_name)
    SELECT
        /* 工号缺失时回落为登录名 —— 与 sync_ad_to_sso.ps1 的 12.3 修订口径一致 */
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
      AND LEN(b.login_norm) <= 64
      AND LEN(CASE WHEN b.emp_norm = N'' THEN b.login_norm ELSE b.emp_norm END) <= 32;

    /* 1.2 拒绝集: 登录名为空/超长（与 05 第 3.2 节一致） */
    INSERT INTO #reject (reason, key_value, src_employee_no, src_login_name)
    SELECT N'登录名为空或超长', NULL, s.employee_no, s.login_name
    FROM dbo.CN_AME_SSO_StgAdUser s
    WHERE LTRIM(RTRIM(ISNULL(s.login_name, N''))) = N''
       OR LEN(LOWER(LTRIM(RTRIM(
              CASE WHEN CHARINDEX(N'\', ISNULL(s.login_name, N'')) > 0
                   THEN SUBSTRING(s.login_name, CHARINDEX(N'\', s.login_name) + 1, 4000)
                   ELSE ISNULL(s.login_name, N'') END)))) > 64;

    /* 1.3 归一后重复: 同一工号或同一登录名多次
          保留规则（确定性）: 在职优先 → 字典序 → 原始行序 */
    DECLARE @dups TABLE (row_no INT PRIMARY KEY, reason NVARCHAR(64));

    ;WITH d AS (
        SELECT row_no,
               ROW_NUMBER() OVER (PARTITION BY employee_no ORDER BY status DESC, login_name, row_no) AS rn_emp,
               ROW_NUMBER() OVER (PARTITION BY login_name  ORDER BY status DESC, employee_no, row_no) AS rn_login
        FROM #norm
    )
    INSERT INTO @dups (row_no, reason)
    SELECT row_no, CASE WHEN rn_emp > 1 THEN N'工号重复' ELSE N'登录名重复' END
    FROM d WHERE rn_emp > 1 OR rn_login > 1;

    INSERT INTO #reject (reason, key_value, src_employee_no, src_login_name)
    SELECT d.reason, n.employee_no, n.src_employee_no, n.src_login_name
    FROM @dups d JOIN #norm n ON n.row_no = d.row_no;

    DELETE n FROM #norm n JOIN @dups d ON d.row_no = n.row_no;

    /* ------------------------------------------------------------------
       2. 统计与预览（干跑与实跑共用同一口径）
       ------------------------------------------------------------------ */
    SELECT @src_rows      = COUNT(*) FROM #norm;
    SELECT @rejects       = COUNT(*) FROM #reject;
    SELECT @disabled_rows = COUNT(*) FROM #norm WHERE status = 0;

    /* 上一次成功批次的源行数（闸门 2 的基准；LOAD/MERGE 同属名单来源） */
    SELECT @prev_rows = src_rows
    FROM (
        SELECT TOP 1 src_rows
        FROM dbo.CN_AME_SSO_SyncLog
        WHERE phase IN (N'MERGE', N'LOAD') AND status = N'OK'
          AND src_rows IS NOT NULL AND src_rows > 0
        ORDER BY id DESC
    ) t;

    SELECT @would_ins = COUNT(*)
    FROM #norm n
    WHERE NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User u
                      WHERE LOWER(LTRIM(RTRIM(u.employee_no))) = n.employee_no);

    SELECT @would_upd = COUNT(*)
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
         OR (n.ad_object_guid IS NOT NULL
             AND ISNULL(u.ad_object_guid, '00000000-0000-0000-0000-000000000000') <> n.ad_object_guid)
         );

    SELECT @would_dis = COUNT(*)
    FROM dbo.CN_AME_SSO_User u
    WHERE u.status = 1 AND u.source <> N'MANUAL'
      AND NOT EXISTS (SELECT 1 FROM #norm n
                      WHERE n.employee_no = LOWER(LTRIM(RTRIM(u.employee_no))));

    SELECT @manual_protected = COUNT(*)
    FROM dbo.CN_AME_SSO_User u
    WHERE u.source = N'MANUAL'
      AND NOT EXISTS (SELECT 1 FROM #norm n
                      WHERE n.employee_no = LOWER(LTRIM(RTRIM(u.employee_no))));

    /* 拒绝样本（受 @SampleMax 控制，供汇总里 reject_sample 展示） */
    SELECT @reject_sample = STRING_AGG(CONCAT(t.reason, N' ', ISNULL(t.src_login_name, N'')),
                                       N' | ')
                            WITHIN GROUP (ORDER BY t.reason, t.src_login_name)
    FROM (SELECT TOP (@SampleMax) reason, src_login_name
          FROM #reject ORDER BY reason, src_login_name) t;

    /* ------------------------------------------------------------------
       3. 五道闸门（与 05 第 4 节一致；不通过只置 gate_status，不抛错）
          说明: 闸门在事务之前执行，此时尚未写入任何业务数据，因此天然“无需回滚”；
                实跑模式由第 5 节负责写 ABORTED 日志 + THROW。
       ------------------------------------------------------------------ */
    IF @src_rows = 0
        SET @gate_reason = N'归一化后有效行为 0（登录名全空或全部重复）';

    IF @gate_reason IS NULL AND @prev_rows IS NOT NULL
       AND @src_rows < @prev_rows * (1 - @RowDropAbortRatio)
        SET @gate_reason = CONCAT(N'行数骤降: 本次 ', @src_rows, N' 行 vs 上次 ', @prev_rows,
                                  N' 行，超过 ', CONVERT(NVARCHAR(10), @RowDropAbortRatio * 100), N'% 阈值');

    IF @gate_reason IS NULL AND @src_rows > 0
       AND CAST(@disabled_rows AS DECIMAL(10,4)) / NULLIF(@src_rows, 0) > @DisabledAbortRatio
        SET @gate_reason = CONCAT(N'停用占比过高: ', @disabled_rows, N'/', @src_rows, N'，超过 ',
                                  CONVERT(NVARCHAR(10), @DisabledAbortRatio * 100), N'% 阈值');

    /* 闸门 4: 登录名撞人（两侧都 LOWER 比较，比 CS 库唯一键更严） */
    SELECT @collisions = COUNT(*)
    FROM #norm n
    JOIN dbo.CN_AME_SSO_User u ON LOWER(u.login_name) = n.login_name
    WHERE LOWER(LTRIM(RTRIM(u.employee_no))) <> n.employee_no;

    IF @gate_reason IS NULL AND @collisions > 0
        SET @gate_reason = CONCAT(N'登录名撞人 ', @collisions,
                                  N' 条: 名单登录名在中央表已存在、但工号不同，需人工裁决');

    /* 闸门 5: 中央表自身存在仅大小写不同的重复工号（_CS 库下 MERGE 会命中两行整体失败） */
    SELECT @dup_emp_central = COUNT(*)
    FROM (
        SELECT LOWER(LTRIM(RTRIM(employee_no))) AS k
        FROM dbo.CN_AME_SSO_User
        GROUP BY LOWER(LTRIM(RTRIM(employee_no)))
        HAVING COUNT(*) > 1
    ) d;

    IF @gate_reason IS NULL AND @dup_emp_central > 0
        SET @gate_reason = CONCAT(N'中央表存在仅大小写不同的重复工号 ', @dup_emp_central,
                                  N' 组，需人工裁决后再合并');

    IF @gate_reason IS NOT NULL SET @gate_status = N'ABORT';

    /* ------------------------------------------------------------------
       4. 干跑：只读业务表；唯一写入是运行记录表追加 1 行
       ------------------------------------------------------------------ */
    IF @Execute = 0
    BEGIN
        INSERT INTO dbo.CN_AME_SSO_MergeRun
            (batch_no, executed, gate_status, gate_reason,
             stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
             would_insert, would_update, would_disable,
             added, updated, disabled, reactivated,
             prev_success_rows, reject_sample, computed_at)
        VALUES
            (@Batch, 0, @gate_status, LEFT(ISNULL(@gate_reason, N''), 2000),
             @src_rows, @rejects, @disabled_rows, @manual_protected,
             @would_ins, @would_upd, @would_dis,
             0, 0, 0, 0,
             @prev_rows, LEFT(ISNULL(@reject_sample, N''), 2000), @Now);

        SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

        IF @gate_status <> N'OK'
            PRINT N'[干跑] 闸门结论 ABORT（实跑会被拦下）: ' + @gate_reason
                  + N'; 已记运行记录 run_id=' + CONVERT(NVARCHAR(20), @run_id);
        ELSE
            PRINT N'[干跑] 闸门通过，未改动业务表与 SyncLog；已记运行记录 run_id='
                  + CONVERT(NVARCHAR(20), @run_id) + N'。实跑请传 @Execute = 1。';

        SELECT
            run_id, batch_no, executed, gate_status, gate_reason,
            stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
            would_insert, would_update, would_disable,
            added, updated, disabled, reactivated,
            prev_success_rows, reject_sample, computed_at,
            run_at, run_by, host_name
        FROM dbo.CN_AME_SSO_MergeRun
        WHERE run_id = @run_id;

        RETURN;
    END

    /* ------------------------------------------------------------------
       5. 实跑：闸门不通过 → 写 ABORTED 日志 + THROW；通过 → 单事务写库
       ------------------------------------------------------------------ */
    IF @gate_status <> N'OK'
    BEGIN
        /* 中止也留一条运行记录，便于事后回答“今天为什么没合并” */
        INSERT INTO dbo.CN_AME_SSO_MergeRun
            (batch_no, executed, gate_status, gate_reason,
             stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
             would_insert, would_update, would_disable,
             added, updated, disabled, reactivated,
             prev_success_rows, reject_sample, computed_at)
        VALUES
            (@Batch, 1, N'ABORT', LEFT(ISNULL(@gate_reason, N''), 2000),
             @src_rows, @rejects, @disabled_rows, @manual_protected,
             @would_ins, @would_upd, @would_dis,
             0, 0, 0, 0,
             @prev_rows, LEFT(ISNULL(@reject_sample, N''), 2000), @Now);

        SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

        /* 事件流水仍写 SyncLog（MergeRun 只记数字，不重复记事件） */
        INSERT INTO dbo.CN_AME_SSO_SyncLog
            (phase, src_rows, added, updated, disabled, reactivated, status, message)
        VALUES (N'MERGE', @src_rows, 0, 0, 0, 0, N'ABORTED',
                LEFT(CONCAT(N'batch=', @Batch, N'; run_id=', @run_id, N'; ', @gate_reason), 2000));

        PRINT N'[中止] 闸门检查未通过，已记运行记录 run_id=' + CONVERT(NVARCHAR(20), @run_id)
              + N' 与 SyncLog(ABORTED)，未改动主表: ' + @gate_reason;
        THROW 51001, @gate_reason, 1;   /* 让 Agent 作业显示失败，而不是静默成功 */
    END

    BEGIN TRY
        BEGIN TRANSACTION;

        /* 5.1 应用锁: 同一时刻只允许一个合并批次（资源名与 05 相同，两版互斥） */
        DECLARE @lock_rc INT;
        EXEC @lock_rc = sp_getapplock
                @Resource    = N'CN_AME_SSO_User_MERGE',
                @LockMode    = N'Exclusive',
                @LockOwner   = N'Transaction',
                @LockTimeout = 0;
        IF @lock_rc < 0
            THROW 51002, N'另一个合并批次正在运行（未拿到 CN_AME_SSO_User_MERGE 锁），本次退出。', 1;

        /* 5.2 MERGE: 唯一实现口径
             - 匹配键 employee_no，两侧统一 LOWER(LTRIM(RTRIM())) 比较
             - 禁止改写 login_name（登录名变更走“停旧建新”）
             - source='MANUAL' 行不覆盖、不停用
             - 目标值用 COALESCE: 名单字段为空时不覆盖主表已有值 */
        DECLARE @out TABLE (action NVARCHAR(10), new_status TINYINT, old_status TINYINT);

        MERGE dbo.CN_AME_SSO_User AS t
        USING #norm AS s
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
                t.display_name   = COALESCE(s.display_name, t.display_name),
                t.email          = COALESCE(s.email,        t.email),
                t.mobile         = COALESCE(s.mobile,       t.mobile),
                t.dept_code      = COALESCE(s.dept_code,    t.dept_code),
                t.dept_name      = COALESCE(s.dept_name,    t.dept_name),
                t.title          = COALESCE(s.title,        t.title),
                t.status         = s.status,
                t.ad_object_guid = COALESCE(s.ad_object_guid, t.ad_object_guid),
                t.source         = N'AD',
                t.synced_at      = @Now,
                t.updated_at     = @Now,
                t.last_batch_no  = @Batch
                /* 故意不更新 login_name / kc_user_id */

        WHEN NOT MATCHED BY TARGET THEN
            INSERT (employee_no, login_name, display_name, email, mobile,
                    dept_code, dept_name, title, status, ad_object_guid,
                    source, pwd_set, synced_at, created_at, updated_at, last_batch_no)
            VALUES (s.employee_no, s.login_name, s.display_name, s.email, s.mobile,
                    s.dept_code, s.dept_name, s.title, s.status, s.ad_object_guid,
                    N'AD', 0, @Now, @Now, @Now, @Batch)

        /* 离职处置: 只停用不删除（保留 UserMap / PermLedger / KC 账号 / 日志） */
        WHEN NOT MATCHED BY SOURCE AND t.status = 1 AND t.source <> N'MANUAL' THEN
            UPDATE SET
                t.status         = 0,
                t.synced_at      = @Now,
                t.updated_at     = @Now,
                t.last_batch_no  = @Batch
        OUTPUT $action, inserted.status, deleted.status INTO @out;

        /* 5.3 结果统计 */
        SELECT @ins   = SUM(CASE WHEN action = N'INSERT' THEN 1 ELSE 0 END),
               @upd   = SUM(CASE WHEN action = N'UPDATE' AND new_status = 1 AND old_status = 1 THEN 1 ELSE 0 END),
               @dis   = SUM(CASE WHEN action = N'UPDATE' AND new_status = 0 THEN 1 ELSE 0 END),
               @react = SUM(CASE WHEN action = N'UPDATE' AND new_status = 1 AND old_status = 0 THEN 1 ELSE 0 END)
        FROM @out;

        /* 5.4 提交前自检: 本批次应写入的行数必须与预览一致（防预览后有人改 Stg） */
        DECLARE @touched INT =
            (SELECT COUNT(*) FROM dbo.CN_AME_SSO_User WHERE last_batch_no = @Batch);
        IF @touched <> @would_ins + @would_upd + @would_dis
            THROW 51003, N'提交前自检失败: 本批次预计影响行数与实际不一致（预览后有人改动了 Stg？），已回滚。', 1;

        /* 5.5 运行记录（OK）: 放在事务内，与 MERGE 同生共死（提交才可见，回滚即消失） */
        INSERT INTO dbo.CN_AME_SSO_MergeRun
            (batch_no, executed, gate_status, gate_reason,
             stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
             would_insert, would_update, would_disable,
             added, updated, disabled, reactivated,
             prev_success_rows, reject_sample, computed_at)
        VALUES
            (@Batch, 1, @gate_status, LEFT(ISNULL(@gate_reason, N''), 2000),
             @src_rows, @rejects, @disabled_rows, @manual_protected,
             @would_ins, @would_upd, @would_dis,
             ISNULL(@ins, 0), ISNULL(@upd, 0), ISNULL(@dis, 0), ISNULL(@react, 0),
             @prev_rows, LEFT(ISNULL(@reject_sample, N''), 2000), @Now);

        SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

        /* 5.6 审计日志（phase='MERGE'，与 ps1 同一张表，便于统一监控） */
        INSERT INTO dbo.CN_AME_SSO_SyncLog
            (phase, src_rows, added, updated, disabled, reactivated, status, message)
        VALUES (N'MERGE', @src_rows, ISNULL(@ins, 0), ISNULL(@upd, 0),
                ISNULL(@dis, 0), ISNULL(@react, 0), N'OK',
                LEFT(CONCAT(N'batch=', @Batch, N'; run_id=', @run_id, N'; 源行=', @src_rows,
                            N'; 拒绝=', @rejects, N'; 停用=', @disabled_rows,
                            N'; 明细见 User.last_batch_no'), 2000));

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

        DECLARE @err NVARCHAR(2048) = LEFT(ERROR_MESSAGE(), 2000);

        /* 失败记录写在事务外，否则会随回滚一起消失 */
        BEGIN TRY
            INSERT INTO dbo.CN_AME_SSO_MergeRun
                (batch_no, executed, gate_status, gate_reason,
                 stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
                 would_insert, would_update, would_disable,
                 added, updated, disabled, reactivated,
                 prev_success_rows, reject_sample, computed_at)
            VALUES
                (@Batch, 1, N'ERROR', LEFT(CONCAT(N'batch=', @Batch, N'; ', @err), 2000),
                 @src_rows, @rejects, @disabled_rows, @manual_protected,
                 @would_ins, @would_upd, @would_dis,
                 0, 0, 0, 0,
                 @prev_rows, LEFT(ISNULL(@reject_sample, N''), 2000), @Now);

            SET @run_id = CAST(SCOPE_IDENTITY() AS BIGINT);

            INSERT INTO dbo.CN_AME_SSO_SyncLog
                (phase, src_rows, added, updated, disabled, reactivated, status, message)
            VALUES (N'MERGE', @src_rows, 0, 0, 0, 0, N'ERROR',
                    LEFT(CONCAT(N'batch=', @Batch, N'; run_id=', @run_id, N'; ', @err), 2000));
        END TRY
        BEGIN CATCH
            PRINT N'[警告] 失败记录写入也失败了: ' + ERROR_MESSAGE();
        END CATCH

        PRINT N'[失败] 已整体回滚，主表未产生部分写入。原因: ' + @err;
        THROW;   /* 保住原始错误号/消息，让 Agent 作业历史能定位 */
    END CATCH

    /* ------------------------------------------------------------------
       6. 实跑汇总（单一结果集 = 刚才插入的那行运行记录）
       ------------------------------------------------------------------ */
    SELECT
        run_id, batch_no, executed, gate_status, gate_reason,
        stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
        would_insert, would_update, would_disable,
        added, updated, disabled, reactivated,
        prev_success_rows, reject_sample, computed_at,
        run_at, run_by, host_name
    FROM dbo.CN_AME_SSO_MergeRun
    WHERE run_id = @run_id;

    PRINT N'[完成] 已提交，运行记录 run_id=' + CONVERT(NVARCHAR(20), @run_id);
END
GO


/* ============================================================================
   附录 A  查历史与保留策略（全部为示例，按需手工执行；本文件不建任何定时清理）
   ----------------------------------------------------------------------------
   与 SyncLog 的分工:
     - CN_AME_SSO_MergeRun: 每次运行的**明细数字**（一行一次），含干跑与失败尝试
     - CN_AME_SSO_SyncLog : **成败与异常事件**（phase/status/message），供统一监控
     两者用 batch_no + run_at 关联；SyncLog.message 里带 run_id，可精确回溯。
   ========================================================================== */

/* A.1 最近 30 次运行（干跑与实跑都在，按时间倒序） ----------------------------
   表里存的是 UTC；显示与筛选用 AT TIME ZONE 转本地时区（不改变存储值）。
   写成两步是标准写法：先声明“这是 UTC”，再转到目标时区。
SELECT TOP 30
       run_id,
       CAST(((run_at     AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
       CAST(((computed_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS computed_at_local,
       batch_no, executed, gate_status,
       stg_effective_rows, rejected_rows, added, updated, disabled, reactivated,
       would_insert, would_update, would_disable, run_by, host_name
FROM dbo.CN_AME_SSO_MergeRun
ORDER BY run_id DESC;
*/

/* A.2 实跑趋势（近 30 天，看每天跑了几次、最后一次是哪个 run_id） --------------
   关注点: 人数（stg_effective_rows）与新增/停用是否平稳，是否出现一天跑多次（重复触发）
   注意: WHERE 里的 30 天仍按 UTC 与 SYSUTCDATETIME() 比（与存储口径一致、可用索引）；
         只有“按本地日期分组”才做时区转换。
SELECT CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATE) AS run_date_local,
       COUNT(*)     AS runs_per_day,
       MAX(run_id)  AS last_run_id
FROM dbo.CN_AME_SSO_MergeRun
WHERE executed = 1
  AND run_at >= DATEADD(DAY, -30, SYSUTCDATETIME())
GROUP BY CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATE)
ORDER BY run_date_local DESC;

-- 同上，把近 30 天实跑的明细按本地时间列出
SELECT m.run_id,
       CAST(((m.run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
       m.batch_no, m.gate_status, m.gate_reason,
       m.stg_effective_rows, m.added, m.updated, m.disabled, m.reactivated
FROM dbo.CN_AME_SSO_MergeRun m
WHERE m.executed = 1
  AND m.run_at >= DATEADD(DAY, -30, SYSUTCDATETIME())
ORDER BY m.run_id DESC;
*/

/* A.3 连续失败检测（最近 5 次实跑里有几次非 OK） -------------------------------
   判定口径: 只看 executed=1；gate_status<>'OK' 即失败（ABORT/ERROR 都算）
   一次失败多为数据问题，连续 3 次以上失败多半是流程/账号/数据源问题，应人工介入
SELECT COUNT(*) AS fails_in_last5,
       CASE WHEN COUNT(*) >= 3 THEN N'需人工介入' ELSE N'可观察' END AS verdict
FROM (SELECT TOP 5 gate_status
      FROM dbo.CN_AME_SSO_MergeRun
      WHERE executed = 1
      ORDER BY run_id DESC) t
WHERE gate_status <> N'OK';

-- 逐条看最近 10 次实跑，判断是“偶发”还是“连续”
SELECT TOP 10 run_id,
       CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
       gate_status, LEFT(gate_reason, 120) AS gate_reason
FROM dbo.CN_AME_SSO_MergeRun
WHERE executed = 1
ORDER BY run_id DESC;
*/

/* A.4 某次失败的具体原因（含拒绝样本） ----------------------------------------
SELECT run_id,
       CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
       batch_no, gate_status, gate_reason,
       stg_effective_rows, rejected_rows, reject_sample
FROM dbo.CN_AME_SSO_MergeRun
WHERE gate_status <> N'OK'
ORDER BY run_id DESC;
*/

/* A.5 保留策略（★ 可选，未设置任何定时任务，需管理员手工执行） -------------------
   为什么要清理: 每日 1~2 行，一年不到 1000 行，短期内不必清；但干跑调试会快速累积。
   清理前务必先备份或导出 CSV，本表是“运行审计”，删掉无法从别处恢复。

   方式一 按行数保留最近 N 条（推荐，不受时钟/时区影响）:
   -- 保留最近 2000 条，其余删除（分批删，避免长事务锁表）
   WHILE 1 = 1
   BEGIN
       DELETE TOP (500) FROM dbo.CN_AME_SSO_MergeRun
       WHERE run_id <= (SELECT MIN(run_id) FROM (
                            SELECT TOP (2000) run_id
                            FROM dbo.CN_AME_SSO_MergeRun
                            ORDER BY run_id DESC) k);
       IF @@ROWCOUNT = 0 BREAK;
   END

   方式二 按天保留（例如保留 180 天）:
   -- 分批删 180 天前的记录
   WHILE 1 = 1
   BEGIN
       DELETE TOP (500) FROM dbo.CN_AME_SSO_MergeRun
       WHERE run_at < DATEADD(DAY, -180, SYSUTCDATETIME());
       IF @@ROWCOUNT = 0 BREAK;
   END

   注意: 以上两条都写 run_at/computed_at 用 UTC，比较时也用 SYSUTCDATETIME()，
         不要混用本地时间 GETDATE()，否则会有 8 小时偏差（Asia/Shanghai）。
         本文件**不创建**清理作业；是否清理、保留多久由现场决定。
   ========================================================================== */

/* A.6 自验“一次调用只落 1 行”（★ 可整段取消注释执行；会清空运行记录，先备份） ------
   原理: 四条终止路径（干跑 / ABORT / 成功 / ERROR）互斥，一次调用只做一次闸门判定、
         只 INSERT 一行；清空后只跑一条 EXEC，表里必须恰好 1 行（无论 OK/ABORT/ERROR）。
   注意: 清空 MergeRun **不会**重置“行数骤降”的基准 —— 基准取自 CN_AME_SSO_SyncLog
         （phase IN ('MERGE','LOAD') AND status='OK' 的最近一条 src_rows）；
         想从零重试，必须一并处理 SyncLog 里的成功记录（见文档 §13.7.8）。

   -- 0) 先备份（可选，但推荐）
   SELECT * INTO dbo.CN_AME_SSO_MergeRun_bak_20261109 FROM dbo.CN_AME_SSO_MergeRun;

   -- 1) 清空（DELETE 不重置 identity，run_id 会继续递增；本表主键只用于标识）
   DELETE FROM dbo.CN_AME_SSO_MergeRun;

   -- 2) 只执行下面这一条，且只按一次 F5（不要整段连选执行）
   EXEC CN_AME.dbo.usp_SSO_MergeStgToUser @Execute = 1;

   -- 3) 期望恰好 1 行；若为 0 或 2 行，说明调用方式或代码版本与预期不符
   SELECT COUNT(*)      AS rows_after_one_exec,
          MIN(run_id)   AS run_id_min,
          MAX(run_id)   AS run_id_max,
          MIN(batch_no) AS batch_no_min,
          MAX(batch_no) AS batch_no_max
   FROM dbo.CN_AME_SSO_MergeRun;

   -- 4) 明细（应只此一行；run_by 可区分人工 ytview 与作业 sso_sync_svc）
   SELECT run_id, batch_no, executed, gate_status,
          CAST(((run_at AT TIME ZONE 'UTC') AT TIME ZONE 'China Standard Time') AS DATETIME2(0)) AS run_at_local,
          stg_effective_rows, would_disable,
          run_by, host_name
   FROM dbo.CN_AME_SSO_MergeRun
   ORDER BY run_id DESC;

   -- 5) 复原备份（可选；确认备份表存在后再执行）
   -- INSERT INTO dbo.CN_AME_SSO_MergeRun
   --     (batch_no, executed, gate_status, gate_reason,
   --      stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
   --      would_insert, would_update, would_disable, added, updated, disabled, reactivated,
   --      prev_success_rows, computed_at, run_at, run_by, host_name, reject_sample)
   -- SELECT batch_no, executed, gate_status, gate_reason,
   --      stg_effective_rows, rejected_rows, disabled_rows_in_source, manual_protected,
   --      would_insert, would_update, would_disable, added, updated, disabled, reactivated,
   --      prev_success_rows, computed_at, run_at, run_by, host_name, reject_sample
   -- FROM dbo.CN_AME_SSO_MergeRun_bak_20261109;
   -- DROP TABLE dbo.CN_AME_SSO_MergeRun_bak_20261109;
   ========================================================================== */

