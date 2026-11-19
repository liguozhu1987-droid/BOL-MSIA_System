/* ============================================================
   02_grants.sql
   SSO 账号创建与授权脚本（T01）
   目标: IRSCNYTFINEREPORT.ap.inalfa.local
   依据: 《统一身份认证实施方案_MSIA与BOL系统.md》4.4 账号权限矩阵

   实测结论（2026-11-02，ytview 执行）:
   - CN_AME containment_desc = NONE → contained database user 不可用，
     必须走 CREATE LOGIN(服务器级) + CREATE USER(库内) 两段式。
   - ytview 实测为 sysadmin + securityadmin，故 LOGIN/USER/跨库授权均可直接执行。
   - 若换由无 sysadmin 权限的 DBA 账号执行，第 1、3 节中标注 [需DBA] 的
     语句需 DBA 手动执行，第 2 节（表级授权）库内 db_owner 即可完成。

   口令策略: Sso@Sync2026# 满足复杂度（大写+小写+数字+特殊字符, 长度12）。
   生产启用后应立即在 credentials.xml（DPAPI）中登记，脚本不落明文。
   ============================================================ */

/* ---------- 0. 前置检查：containment 与现存账号 ---------- */
USE CN_AME;
GO
SELECT name AS db_name, containment_desc FROM sys.databases WHERE name = 'CN_AME';
SELECT name AS existing_login FROM sys.server_principals WHERE name = 'sso_sync_svc';
SELECT name AS existing_db_user FROM sys.database_principals WHERE name = 'sso_sync_svc';
GO

/* ============================================================
   1. 创建同步专用账号 sso_sync_svc
   （containment=NONE，contained user 语法会报错 15517，此处仅注释留档）
   ------------------------------------------------------------
   -- 若 CN_AME 为 PARTIAL containment 可用（当前 NONE，不适用）:
   -- CREATE USER sso_sync_svc WITH PASSWORD = 'Sso@Sync2026#';
   ============================================================ */

/* 1.1 服务器级登录名 [需DBA条件: securityadmin/sysadmin；ytview 实测可执行] */
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'sso_sync_svc')
BEGIN
    CREATE LOGIN sso_sync_svc
        WITH PASSWORD = 'Sso@Sync2026#',
             CHECK_POLICY = ON,               -- 强制 Windows 口令策略
             CHECK_EXPIRATION = OFF,          -- 服务账号不宜过期
             DEFAULT_DATABASE = CN_AME;
    PRINT 'CREATE LOGIN sso_sync_svc: OK';
END
ELSE
    PRINT 'LOGIN sso_sync_svc 已存在，跳过';
GO

/* 1.2 库内用户映射 */
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'sso_sync_svc')
BEGIN
    CREATE USER sso_sync_svc FOR LOGIN sso_sync_svc WITH DEFAULT_SCHEMA = dbo;
    PRINT 'CREATE USER sso_sync_svc: OK';
END
ELSE
    PRINT 'USER sso_sync_svc 已存在，跳过';
GO

/* ============================================================
   2. 表级授权（仅五张 SSO 表，不给整库；库内 db_owner 即可执行）
   ============================================================ */
USE CN_AME;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.CN_AME_SSO_StgAdUser TO sso_sync_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.CN_AME_SSO_User     TO sso_sync_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.CN_AME_SSO_UserMap   TO sso_sync_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.CN_AME_SSO_SyncLog   TO sso_sync_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.CN_AME_SSO_PermLedger TO sso_sync_svc;
-- 显式拒绝库级 DDL 与元数据查看，权限面最小化（DDL 仍属 ytview）
-- 注意: 数据库级权限无 DROP（DROP 仅对象级），此处拒绝 ALTER/VIEW DEFINITION/CREATE TABLE
DENY ALTER, VIEW DEFINITION, CREATE TABLE ON DATABASE::CN_AME TO sso_sync_svc;
GO

/* ============================================================
   3. BOL 跨库只读授权（TR4：BOL 的 CMC 账号读 CN_AME 两张表）
   BOL 生产连接账号 sparePartRead（CMC 库）需在 CN_AME 建同登录用户并授权。
   [需DBA条件: 在 CN_AME 建跨库 USER 需 sysadmin/securityadmin；
    ytview 实测为 sysadmin，已直接执行成功]
   ============================================================ */
USE CN_AME;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'sparePartRead')
BEGIN
    CREATE USER sparePartRead FOR LOGIN sparePartRead WITH DEFAULT_SCHEMA = dbo;
    PRINT 'CREATE USER sparePartRead (CN_AME): OK';
END
ELSE
    PRINT 'USER sparePartRead (CN_AME) 已存在，跳过';
GO
GRANT SELECT ON dbo.CN_AME_SSO_User   TO sparePartRead;
GRANT SELECT ON dbo.CN_AME_SSO_UserMap TO sparePartRead;
GO

/* ============================================================
   4. MSIA 侧说明（无需授权动作）:
   MSIA 运行账号即 ytview，与建表账号同一，对五表天然具备读写权限。
   ============================================================ */

/* ---------- 5. 授权后自查 ---------- */
USE CN_AME;
GO
SELECT
    dp.name AS db_user,
    o.name AS object_name,
    permission_name
FROM sys.database_permissions p
JOIN sys.database_principals dp ON dp.principal_id = p.grantee_principal_id
JOIN sys.objects o ON o.object_id = p.major_id
WHERE dp.name IN ('sso_sync_svc', 'sparePartRead')
ORDER BY dp.name, o.name, permission_name;
GO
