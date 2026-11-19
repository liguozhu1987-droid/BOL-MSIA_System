/* ============================================================
   01_create_sso_tables.sql
   统一身份认证 SSO 域建表脚本（T01）
   目标: IRSCNYTFINEREPORT.ap.inalfa.local / CN_AME 库
   执行账号: ytview（实测具备 sysadmin，DDL 无阻碍；若换普通账号需 DDL 权限）
   特性: 幂等可重复执行（表已存在则整段跳过）
   时间列统一 UTC(SYSUTCDATETIME), 展示层转本地时区
   依据: 《统一身份认证实施方案_MSIA与BOL系统.md》4.2 节
   执行方式: SSMS / sqlcmd -i 01_create_sso_tables.sql
   ============================================================ */
USE CN_AME;
GO

/* ---------- 1. AD 名单暂存表（每日 TRUNCATE 重灌） ---------- */
IF OBJECT_ID(N'dbo.CN_AME_SSO_StgAdUser', N'U') IS NULL
BEGIN
CREATE TABLE dbo.CN_AME_SSO_StgAdUser (
    employee_no    NVARCHAR(32)      NOT NULL,               -- 工号（跨系统稳定主键；AD 无工号时 = login_name）
    login_name     NVARCHAR(64)      NULL,                   -- 登录名（=AD 域账号, 全小写）
    display_name   NVARCHAR(128)     NULL,                   -- 中文姓名
    email          NVARCHAR(128)     NULL,                   -- 企业邮箱（设密/找回依赖）
    mobile         NVARCHAR(32)      NULL,
    dept_code      NVARCHAR(64)      NULL,
    dept_name      NVARCHAR(128)     NULL,
    title          NVARCHAR(128)     NULL,
    status         TINYINT           NOT NULL DEFAULT 1,     -- 1=在职 0=离职停用（名单标记）
    ad_object_guid UNIQUEIDENTIFIER  NULL,                   -- 防工号复用误合并（当前名单无此列，留空）
    loaded_at      DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_CN_AME_SSO_StgAdUser_EmpNo ON dbo.CN_AME_SSO_StgAdUser (employee_no);
END
GO

/* ---------- 2. 中央人员表（唯一人员事实来源） ---------- */
IF OBJECT_ID(N'dbo.CN_AME_SSO_User', N'U') IS NULL
BEGIN
CREATE TABLE dbo.CN_AME_SSO_User (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CN_AME_SSO_User PRIMARY KEY,
    employee_no    NVARCHAR(32)      NOT NULL,
    login_name     NVARCHAR(64)      NOT NULL,               -- Keycloak username, 一旦确定不改
    display_name   NVARCHAR(128)     NULL,
    email          NVARCHAR(128)     NULL,
    mobile         NVARCHAR(32)      NULL,
    dept_code      NVARCHAR(64)      NULL,
    dept_name      NVARCHAR(128)     NULL,
    title          NVARCHAR(128)     NULL,
    status         TINYINT           NOT NULL DEFAULT 1,     -- 1=在职 0=停用（永不物理删除）
    ad_object_guid UNIQUEIDENTIFIER  NULL,
    source         NVARCHAR(16)      NOT NULL DEFAULT N'AD', -- AD=同步 / MANUAL=例外手工（种子数据用 MANUAL，防被 AD 同步覆盖）
    pwd_set        BIT               NOT NULL DEFAULT 0,     -- 已在 Keycloak 完成首次设密
    kc_user_id     NVARCHAR(64)      NULL,                   -- Keycloak 用户 ID 缓存(同步脚本回写)
    synced_at      DATETIME2(0)      NULL,                   -- 最近 AD 合并时间（新鲜度监控依据）
    created_at     DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at     DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_CN_AME_SSO_User_Status CHECK (status IN (0,1)),
    CONSTRAINT CK_CN_AME_SSO_User_Source CHECK (source IN (N'AD', N'MANUAL'))
);

ALTER TABLE dbo.CN_AME_SSO_User ADD CONSTRAINT UQ_CN_AME_SSO_User_EmpNo  UNIQUE (employee_no);
ALTER TABLE dbo.CN_AME_SSO_User ADD CONSTRAINT UQ_CN_AME_SSO_User_Login  UNIQUE (login_name);
CREATE UNIQUE INDEX UX_CN_AME_SSO_User_Guid ON dbo.CN_AME_SSO_User (ad_object_guid)
    WHERE ad_object_guid IS NOT NULL;
-- 2026-11-02 调整（用户确认"邮箱暂不用管理"）：email 不再作为受管身份属性，
-- 唯一索引降级为普通索引，允许空/重复（realm 侧同步关闭 Duplicate emails 检查）
CREATE INDEX IX_CN_AME_SSO_User_Email ON dbo.CN_AME_SSO_User (email)
    WHERE email IS NOT NULL;
CREATE UNIQUE INDEX UX_CN_AME_SSO_User_KcId  ON dbo.CN_AME_SSO_User (kc_user_id)
    WHERE kc_user_id IS NOT NULL;
CREATE INDEX IX_CN_AME_SSO_User_Status   ON dbo.CN_AME_SSO_User (status);
CREATE INDEX IX_CN_AME_SSO_User_DeptCode ON dbo.CN_AME_SSO_User (dept_code);
CREATE INDEX IX_CN_AME_SSO_User_SyncedAt ON dbo.CN_AME_SSO_User (synced_at);
END
GO

/* ---------- 3. 跨系统账号对照表（存量用户名 ≠ AD 登录名时用） ---------- */
IF OBJECT_ID(N'dbo.CN_AME_SSO_UserMap', N'U') IS NULL
BEGIN
CREATE TABLE dbo.CN_AME_SSO_UserMap (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CN_AME_SSO_UserMap PRIMARY KEY,
    employee_no    NVARCHAR(32)      NOT NULL,               -- 关联 CN_AME_SSO_User.employee_no
    system_code    NVARCHAR(32)      NOT NULL,               -- 'msia' / 'bol'（与台账同一套编码）
    local_username NVARCHAR(128)     NOT NULL,               -- 该系统已有登录名
    match_key      NVARCHAR(16)      NOT NULL DEFAULT N'USERNAME',  -- USERNAME/EMAIL/EMPNO
    remark         NVARCHAR(200)     NULL,
    created_at     DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at     DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_CN_AME_SSO_UserMap_Key CHECK (match_key IN (N'USERNAME', N'EMAIL', N'EMPNO')),
    CONSTRAINT UQ_CN_AME_SSO_UserMap_SysLocal UNIQUE (system_code, local_username)
);
CREATE INDEX IX_CN_AME_SSO_UserMap_Emp ON dbo.CN_AME_SSO_UserMap (employee_no, system_code);
END
GO

/* ---------- 4. 同步日志表（两类同步共用, phase 区分） ---------- */
IF OBJECT_ID(N'dbo.CN_AME_SSO_SyncLog', N'U') IS NULL
BEGIN
CREATE TABLE dbo.CN_AME_SSO_SyncLog (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CN_AME_SSO_SyncLog PRIMARY KEY,
    phase          NVARCHAR(16)      NOT NULL,   -- LOAD/MERGE/KC/KC_EMERGENCY
    run_at         DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME(),
    src_rows       INT               NULL,
    added          INT               NULL,
    updated        INT               NULL,
    disabled       INT               NULL,
    reactivated    INT               NULL,
    status         NVARCHAR(16)      NOT NULL,   -- OK / ABORTED / ERROR
    message        NVARCHAR(2000)    NULL
);
CREATE INDEX IX_CN_AME_SSO_SyncLog_RunAt ON dbo.CN_AME_SSO_SyncLog (run_at DESC, phase);
END
GO

/* ---------- 5. 权限台账表（谁-哪个系统-什么角色-谁授的） ---------- */
IF OBJECT_ID(N'dbo.CN_AME_SSO_PermLedger', N'U') IS NULL
BEGIN
CREATE TABLE dbo.CN_AME_SSO_PermLedger (
    id             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CN_AME_SSO_PermLedger PRIMARY KEY,
    employee_no    NVARCHAR(32)      NOT NULL,
    system_code    NVARCHAR(32)      NOT NULL,   -- 'msia' / 'bol' / 'keycloak-admin' / 'local-admin'
    role_name      NVARCHAR(64)      NOT NULL,   -- 系统内角色文本（admin/reviewer/IE/MGR...）
    granted_by     NVARCHAR(64)      NOT NULL,
    granted_at     DATE              NOT NULL DEFAULT CAST(SYSUTCDATETIME() AS DATE),
    revoked_at     DATE              NULL,       -- NULL=仍有效
    remark         NVARCHAR(200)     NULL,
    created_at     DATETIME2(0)      NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_CN_AME_SSO_PermLedger_Emp ON dbo.CN_AME_SSO_PermLedger (employee_no);
CREATE INDEX IX_CN_AME_SSO_PermLedger_Sys ON dbo.CN_AME_SSO_PermLedger (system_code, revoked_at);
END
GO

/* ---------- 建表后自查（应各返回 1） ---------- */
SELECT name AS table_name FROM sys.tables
WHERE name IN ('CN_AME_SSO_StgAdUser','CN_AME_SSO_User','CN_AME_SSO_UserMap',
               'CN_AME_SSO_SyncLog','CN_AME_SSO_PermLedger')
ORDER BY name;
GO
