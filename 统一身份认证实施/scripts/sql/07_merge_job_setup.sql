/* ============================================================================
   07_merge_job_setup.sql  —— 合并存储过程的上线配套：授权 + SQL Server Agent 作业
   ----------------------------------------------------------------------------
   前置: 06_merge_stg_to_user_proc.sql 已成功创建 dbo.usp_SSO_MergeStgToUser。
   本文件做两件事:
     1) 给“作业运行账号”授 EXECUTE（只需要 EXECUTE，见下方说明）；
     2) 在 msdb 里建作业 SSO_Merge_StgToUser + 每日 02:00 的计划。
   注意: 本文件会**先删后建**同名作业与同名计划（可反复执行），
         但不会删除任何数据表，也不会执行合并本身。

   执行方式: 用有权限的账号（建作业需要 msdb 的 SQLAgentUserRole 或 sysadmin）
             在 SSMS 里整篇执行；第 1 段在 CN_AME，第 2 段在 msdb。
   ============================================================================ */

/* ============================================================================
   第 1 段  授权（在业务库 CN_AME 执行）
   --------------------------------------------------------------------------
   为什么只需要 EXECUTE:
     过程与五张表都属于 CN_AME.dbo，属主相同 → SQL Server 走“所有权链”，
     调用方只要有过程的 EXECUTE 权限，过程内部的 SELECT / INSERT / UPDATE
     都以属主（dbo）的权限执行，不需要另外授表级写权限。
     一旦把过程或表挪到别的 schema、或改由其它属主拥有，所有权链会断，
     那时才需要补 GRANT SELECT/INSERT/UPDATE ON dbo.CN_AME_SSO_User 等。

   ★ 把 @JobLogin 改成你实际的作业运行账号（通常就是 SQL Agent 作业所有者，
     默认是本段脚本的执行者；用 Windows 账号时写 'DOMAIN\user'）。
   ========================================================================== */
USE CN_AME;
GO

SET NOCOUNT ON;
GO

DECLARE @JobLogin sysname = N'sso_sync_svc';   /* ← 改这里：作业运行账号 */

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @JobLogin)
    THROW 51020, N'数据库 CN_AME 里不存在账号，请先建登录/用户，或改成本库已有账号（如 sso_sync_svc）。', 1;

IF OBJECT_ID(N'dbo.usp_SSO_MergeStgToUser', N'P') IS NULL
    THROW 51021, N'过程 dbo.usp_SSO_MergeStgToUser 不存在，请先执行 06_merge_stg_to_user_proc.sql。', 1;

EXEC (N'GRANT EXECUTE ON dbo.usp_SSO_MergeStgToUser TO [' + @JobLogin + N'];');

PRINT N'[授权] 已授 EXECUTE ON dbo.usp_SSO_MergeStgToUser TO ' + @JobLogin;
GO


/* ============================================================================
   第 2 段  创建作业与计划（在 msdb 执行）
   --------------------------------------------------------------------------
   作业结构:
     作业名   SSO_Merge_StgToUser
     步骤 1   EXEC dbo.usp_SSO_MergeStgToUser @Execute = 1;
     计划     SSO_Merge_Daily_0200，每日 02:00（SQL Agent 所在服务器的本地时间）
   失败行为:
     过程用 THROW 抛错 → 步骤失败 → 作业显示“失败”（不会静默算成功）。
     重试次数设为 0：合并失败通常是数据问题（闸门/脏数据），盲目重试无意义，
     应人工看 SyncLog 的 message 后再决定。
   ========================================================================== */
USE msdb;
GO

SET NOCOUNT ON;
GO

DECLARE @JobName      sysname = N'SSO_Merge_StgToUser';
DECLARE @JobOwner     sysname = N'sso_sync_svc';      /* ← 与第 1 段的 @JobLogin 保持一致 */
DECLARE @ScheduleName sysname = N'SSO_Merge_Daily_0200';

/* 2.1 清理同名对象（可反复执行；只删作业/计划，不动数据） */
IF EXISTS (SELECT 1 FROM msdb.dbo.sysjobs WHERE name = @JobName)
BEGIN
    EXEC msdb.dbo.sp_delete_job @job_name = @JobName, @delete_history = 0;
    PRINT N'[清理] 已删除旧的作业 ' + @JobName + N'（历史保留）';
END

IF EXISTS (SELECT 1 FROM msdb.dbo.sysschedules WHERE name = @ScheduleName)
BEGIN
    EXEC msdb.dbo.sp_delete_schedule @schedule_name = @ScheduleName, @force_delete = 1;
    PRINT N'[清理] 已删除旧计划 ' + @ScheduleName;
END

/* 2.2 建作业 */
EXEC msdb.dbo.sp_add_job
     @job_name              = @JobName,
     @enabled               = 1,
     @description           = N'每日把 CN_AME_SSO_StgAdUser 幂等合并进 CN_AME_SSO_User（调用 dbo.usp_SSO_MergeStgToUser）',
     @owner_login_name      = @JobOwner,
     @notify_level_eventlog = 2;      /* 2 = 仅失败时写 Windows 事件日志 */

/* 2.3 建步骤：整条命令只有一句 EXEC，失败靠 THROW 传到作业历史 */
EXEC msdb.dbo.sp_add_jobstep
     @job_name          = @JobName,
     @step_id           = 1,
     @step_name         = N'Merge Stg -> CN_AME_SSO_User',
     @subsystem         = N'TSQL',
     @command           = N'EXEC dbo.usp_SSO_MergeStgToUser @Execute = 1;',
     @database_name     = N'CN_AME',
     @server            = N'LOCAL',
     @on_success_action = 1,          /* 1 = 成功后退出（成功） */
     @on_success_step_id= 0,
     @on_fail_action    = 2,          /* 2 = 失败后退出（失败） */
     @on_fail_step_id   = 0,
     @retry_attempts    = 0,
     @retry_interval    = 0;

/* 2.4 建计划：默认每日 02:00（★ 只是占位默认值，正式频率待你确认离职失效时限后再定） */
EXEC msdb.dbo.sp_add_schedule
     @schedule_name         = @ScheduleName,
     @enabled               = 1,
     @freq_type             = 4,      /* 4 = 每日 */
     @freq_interval         = 1,
     @freq_subday_type      = 1,      /* 1 = 在指定时间执行一次 */
     @freq_subday_interval  = 0,
     @active_start_date     = 20261109,
     @active_end_date       = 99991231,
     @active_start_time     = 020000, /* 02:00:00，服务器本地时间 */
     @active_end_time       = 235959;

/* 2.5 计划挂到作业，并指定目标服务器（缺这一步作业不会跑） */
EXEC msdb.dbo.sp_attach_schedule
     @job_name      = @JobName,
     @schedule_name = @ScheduleName;

EXEC msdb.dbo.sp_add_jobserver
     @job_name    = @JobName,
     @server_name = N'(LOCAL)';

PRINT N'[完成] 作业 ' + @JobName + N' 已创建并挂上计划 ' + @ScheduleName + N'。';
GO


/* ============================================================================
   第 3 段  建完后的核对（只读）
   ========================================================================== */
USE msdb;
GO

SET NOCOUNT ON;
GO

PRINT N'--- 3.1 作业与步骤 ---';
SELECT j.name AS job_name, j.enabled, j.owner_sname, s.step_id, s.step_name,
       s.subsystem, s.database_name, s.command
FROM msdb.dbo.sysjobs j
JOIN msdb.dbo.sysjobsteps s ON s.job_id = j.job_id
WHERE j.name = N'SSO_Merge_StgToUser';

PRINT N'--- 3.2 计划与下次运行时间 ---';
SELECT j.name AS job_name, sc.name AS schedule_name, sc.enabled,
       sc.freq_type, sc.freq_interval, sc.freq_subday_type,
       sc.active_start_time, js.next_run_date, js.next_run_time
FROM msdb.dbo.sysjobs j
JOIN msdb.dbo.sysjobschedules js ON js.job_id = j.job_id
JOIN msdb.dbo.sysschedules  sc ON sc.schedule_id = js.schedule_id
WHERE j.name = N'SSO_Merge_StgToUser';

PRINT N'--- 3.3 最近一次执行结果（尚无执行时为 0 行） ---';
SELECT TOP 5 jh.step_id, jh.step_name, jh.run_status, jh.run_date, jh.run_time,
       jh.run_duration, LEFT(jh.message, 200) AS message
FROM msdb.dbo.sysjobhistory jh
JOIN msdb.dbo.sysjobs j ON j.job_id = jh.job_id
WHERE j.name = N'SSO_Merge_StgToUser'
ORDER BY jh.run_date DESC, jh.run_time DESC;
GO


/* ============================================================================
   附：日常调整写法（按需取消注释执行，不要替用户预先设定频率）
   --------------------------------------------------------------------------
   改频率（示例，按自己的失效时限口径再定）:
     -- 每 6 小时一次
     EXEC msdb.dbo.sp_update_schedule @name = N'SSO_Merge_Daily_0200',
          @freq_subday_type = 8, @freq_subday_interval = 6;   -- 8 = 小时
     -- 每周一 02:00
     EXEC msdb.dbo.sp_update_schedule @name = N'SSO_Merge_Daily_0200',
          @freq_type = 8, @freq_interval = 2, @active_start_time = 020000;  -- 8=每周,2=周一

   暂停 / 恢复作业:
     EXEC msdb.dbo.sp_update_job @job_name = N'SSO_Merge_StgToUser', @enabled = 0;  -- 暂停
     EXEC msdb.dbo.sp_update_job @job_name = N'SSO_Merge_StgToUser', @enabled = 1;  -- 恢复

   手工跑一次（等价于计划触发）:
     EXEC msdb.dbo.sp_start_job @job_name = N'SSO_Merge_StgToUser';

   只干跑（不写库）看汇总:
     EXEC CN_AME.dbo.usp_SSO_MergeStgToUser @Execute = 0, @SampleMax = 50;
   ============================================================================ */
