/* ==========================================================================
   MSIA 审核管理系统 - 初始化数据脚本
   数据库: CN_AME
   内容: 默认管理员账号、邮件模板、示例检查项
   ========================================================================== */

USE [CN_AME];
GO

/* --------------------------------------------------------------------------
   1. 默认管理员账号
   密码: Admin@123 （bcrypt 哈希值，由后端首次启动时更新或手动执行）
   -------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_MISA_User WHERE Username = N'admin')
BEGIN
    INSERT INTO dbo.CN_AME_MISA_User
        (Username, DisplayName, Email, Role, Status, PasswordHash, PasswordUpdatedAt, IsDeleted, CreatedAt)
    VALUES
        (N'admin', N'系统管理员', N'admin@inalfa.local', N'admin', 1,
         N'$2b$12$placeholderWillBeReplacedByBackendOnFirstLogin',
         SYSDATETIME(), 0, SYSDATETIME());
    PRINT N'默认管理员账号 admin 已创建（首次登录需设置密码）';
END
GO

/* --------------------------------------------------------------------------
   2. 示例检查项标准库（MSIA1 - MSIA5 各若干条，Version 1）
   -------------------------------------------------------------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_MISA_CheckItem WHERE PhaseCode = N'MSIA1')
BEGIN
    INSERT INTO dbo.CN_AME_MISA_CheckItem
        (PhaseCode, ItemNo, Name, Request, IsKeyItem, ReviewerRoles, ScoreScaleType, ScoreOptions, Version, CreatedAt)
    VALUES
        (N'MSIA1', N'1.1', N'项目启动会议', N'确认项目启动会议已召开并记录纪要', 1, N'CoE;IE', N'5-step',
         N'[{"value":5,"label":"5 - Fully Compliant"},{"value":4,"label":"4 - Minor Gaps"},{"value":3,"label":"3 - Partially Compliant"},{"value":2,"label":"2 - Major Gaps"},{"value":1,"label":"1 - Non-Compliant"}]',
         1, SYSDATETIME()),
        (N'MSIA1', N'1.2', N'项目计划与里程碑', N'项目计划包含关键里程碑（kick-off, design freeze, PVP, SOP）', 1, N'CoE;IE;EOL', N'5-step',
         N'[{"value":5,"label":"5 - Fully Compliant"},{"value":4,"label":"4 - Minor Gaps"},{"value":3,"label":"3 - Partially Compliant"},{"value":2,"label":"2 - Major Gaps"},{"value":1,"label":"1 - Non-Compliant"}]',
         1, SYSDATETIME()),
        (N'MSIA1', N'1.3', N'团队组建', N'跨职能团队已组建并明确角色职责', 0, N'CoE', N'3-step',
         N'[{"value":3,"label":"3 - Compliant"},{"value":2,"label":"2 - Partially Compliant"},{"value":1,"label":"1 - Non-Compliant"}]',
         1, SYSDATETIME());
    PRINT N'MSIA1 检查项已初始化';
END
GO

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_MISA_CheckItem WHERE PhaseCode = N'MSIA2')
BEGIN
    INSERT INTO dbo.CN_AME_MISA_CheckItem
        (PhaseCode, ItemNo, Name, Request, IsKeyItem, ReviewerRoles, ScoreScaleType, ScoreOptions, Version, CreatedAt)
    VALUES
        (N'MSIA2', N'2.1', N'设计规范评审', N'设计规范已评审并获批', 1, N'IE;EOL;CE', N'5-step',
         N'[{"value":5,"label":"5 - Fully Compliant"},{"value":4,"label":"4 - Minor Gaps"},{"value":3,"label":"3 - Partially Compliant"},{"value":2,"label":"2 - Major Gaps"},{"value":1,"label":"1 - Non-Compliant"}]',
         1, SYSDATETIME()),
        (N'MSIA2', N'2.2', N'可制造性分析', N'已完成可制造性（DFM）分析', 1, N'IE;CE', N'4-step',
         N'[{"value":4,"label":"4 - Fully Compliant"},{"value":3,"label":"3 - Minor Gaps"},{"value":2,"label":"2 - Major Gaps"},{"value":1,"label":"1 - Non-Compliant"}]',
         1, SYSDATETIME());
    PRINT N'MSIA2 检查项已初始化';
END
GO

PRINT N'=== MSIA 初始化数据导入完成 ===';
GO
