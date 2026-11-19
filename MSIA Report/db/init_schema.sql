/* ==========================================================================
   MSIA 审核管理系统 - 数据库建表脚本
   数据库: CN_AME
   命名规范: 所有系统表统一使用 CN_AME_MISA_***** 前缀
   主键: BIGINT IDENTITY
   时间: DATETIME2
   软删除: IsDeleted BIT
   ========================================================================== */

USE [CN_AME];
GO

/* --------------------------------------------------------------------------
   1. CN_AME_MISA_User 用户表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_User', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_User;
GO

CREATE TABLE dbo.CN_AME_MISA_User (
    Id                  BIGINT IDENTITY(1,1) NOT NULL,
    Username            NVARCHAR(100)  NOT NULL,
    DisplayName         NVARCHAR(100)  NULL,
    Email               NVARCHAR(200)  NULL,
    Phone               NVARCHAR(50)   NULL,
    Department          NVARCHAR(100)  NULL,
    PasswordHash        NVARCHAR(500)  NULL,
    PasswordUpdatedAt   DATETIME2      NULL,
    Role                NVARCHAR(50)   NOT NULL CONSTRAINT DF_MISA_User_Role DEFAULT N'reviewee',
    Status              TINYINT        NOT NULL CONSTRAINT DF_MISA_User_Status DEFAULT 1,
    HrSyncedAt          DATETIME2      NULL,
    IsDeleted           BIT            NOT NULL CONSTRAINT DF_MISA_User_IsDeleted DEFAULT 0,
    CreatedAt           DATETIME2      NOT NULL CONSTRAINT DF_MISA_User_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt           DATETIME2      NULL,
    CONSTRAINT PK_MISA_User PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT UX_MISA_User_Username UNIQUE NONCLUSTERED (Username)
);
GO

CREATE INDEX IX_MISA_User_Email      ON dbo.CN_AME_MISA_User (Email);
CREATE INDEX IX_MISA_User_Department ON dbo.CN_AME_MISA_User (Department);
CREATE INDEX IX_MISA_User_Status     ON dbo.CN_AME_MISA_User (Status);
GO

/* --------------------------------------------------------------------------
   2. CN_AME_MISA_UserSyncLog 用户同步日志表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_UserSyncLog', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_UserSyncLog;
GO

CREATE TABLE dbo.CN_AME_MISA_UserSyncLog (
    Id              BIGINT IDENTITY(1,1) NOT NULL,
    SyncBatchId     UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_MISA_SyncLog_Batch DEFAULT NEWID(),
    SyncStartedAt   DATETIME2      NOT NULL,
    SyncFinishedAt  DATETIME2      NULL,
    TotalRead       INT            NOT NULL CONSTRAINT DF_MISA_SyncLog_Read DEFAULT 0,
    TotalInserted   INT            NOT NULL CONSTRAINT DF_MISA_SyncLog_Inserted DEFAULT 0,
    TotalUpdated    INT            NOT NULL CONSTRAINT DF_MISA_SyncLog_Updated DEFAULT 0,
    TotalFailed     INT            NOT NULL CONSTRAINT DF_MISA_SyncLog_Failed DEFAULT 0,
    ErrorMessage    NVARCHAR(MAX)  NULL,
    Status          NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_SyncLog_Status DEFAULT N'success',
    CreatedAt       DATETIME2      NOT NULL CONSTRAINT DF_MISA_SyncLog_CreatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT PK_MISA_UserSyncLog PRIMARY KEY CLUSTERED (Id)
);
GO

CREATE INDEX IX_MISA_SyncLog_CreatedAt ON dbo.CN_AME_MISA_UserSyncLog (CreatedAt);
GO

/* --------------------------------------------------------------------------
   3. CN_AME_MISA_Project 项目表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_Project', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_Project;
GO

CREATE TABLE dbo.CN_AME_MISA_Project (
    Id              BIGINT IDENTITY(1,1) NOT NULL,
    Name            NVARCHAR(200)  NOT NULL,
    Code            NVARCHAR(50)   NOT NULL,
    Type            NVARCHAR(100)  NULL,
    CmcAme          NVARCHAR(100)  NULL,
    PlantMe         NVARCHAR(100)  NULL,
    InalfaKickoff   DATETIME2      NULL,
    SupplierKickoff DATETIME2      NULL,
    DesignFreeze    DATETIME2      NULL,
    Pvp             DATETIME2      NULL,
    InalfaSop       DATETIME2      NULL,
    Status          NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_Project_Status DEFAULT N'not_started',
    CreatedBy       BIGINT         NULL,
    IsDeleted       BIT            NOT NULL CONSTRAINT DF_MISA_Project_IsDeleted DEFAULT 0,
    CreatedAt       DATETIME2      NOT NULL CONSTRAINT DF_MISA_Project_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt       DATETIME2      NULL,
    CONSTRAINT PK_MISA_Project PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT UX_MISA_Project_Code UNIQUE NONCLUSTERED (Code),
    CONSTRAINT FK_MISA_Project_CreatedBy FOREIGN KEY (CreatedBy)
        REFERENCES dbo.CN_AME_MISA_User (Id)
);
GO

CREATE INDEX IX_MISA_Project_Status   ON dbo.CN_AME_MISA_Project (Status);
CREATE INDEX IX_MISA_Project_CreatedBy ON dbo.CN_AME_MISA_Project (CreatedBy);
GO

/* --------------------------------------------------------------------------
   4. CN_AME_MISA_Phase 阶段表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_Phase', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_Phase;
GO

CREATE TABLE dbo.CN_AME_MISA_Phase (
    Id                BIGINT IDENTITY(1,1) NOT NULL,
    ProjectId         BIGINT         NOT NULL,
    Code              NVARCHAR(20)   NOT NULL,
    Name              NVARCHAR(100)  NULL,
    TimingDescription NVARCHAR(500)  NULL,
    MainTargets       NVARCHAR(MAX)  NULL,
    Status            NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_Phase_Status DEFAULT N'not_started',
    LeadReviewerId    BIGINT         NULL,
    Score             DECIMAL(5,2)   NULL,
    CompletedAt       DATETIME2      NULL,
    CreatedAt         DATETIME2      NOT NULL CONSTRAINT DF_MISA_Phase_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt         DATETIME2      NULL,
    CONSTRAINT PK_MISA_Phase PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT FK_MISA_Phase_Project FOREIGN KEY (ProjectId)
        REFERENCES dbo.CN_AME_MISA_Project (Id),
    CONSTRAINT FK_MISA_Phase_LeadReviewer FOREIGN KEY (LeadReviewerId)
        REFERENCES dbo.CN_AME_MISA_User (Id)
);
GO

CREATE INDEX IX_MISA_Phase_ProjectId ON dbo.CN_AME_MISA_Phase (ProjectId);
CREATE INDEX IX_MISA_Phase_Code      ON dbo.CN_AME_MISA_Phase (Code);
GO

/* --------------------------------------------------------------------------
   5. CN_AME_MISA_CheckItem 检查项标准库表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_CheckItem', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_CheckItem;
GO

CREATE TABLE dbo.CN_AME_MISA_CheckItem (
    Id                  BIGINT IDENTITY(1,1) NOT NULL,
    PhaseCode           NVARCHAR(20)   NOT NULL,
    ItemNo              NVARCHAR(50)   NULL,
    Name                NVARCHAR(200)  NOT NULL,
    Request             NVARCHAR(MAX)  NULL,
    RequestDescription  NVARCHAR(MAX)  NULL,
    IsKeyItem           BIT            NOT NULL CONSTRAINT DF_MISA_CheckItem_IsKey DEFAULT 0,
    ReviewerRoles       NVARCHAR(200)  NULL,
    ReferenceDocuments  NVARCHAR(MAX)  NULL,
    ScoreScaleType      NVARCHAR(20)   NULL,
    ScoreOptions        NVARCHAR(MAX)  NULL,
    DefaultResultText   NVARCHAR(200)  NULL,
    Version             INT            NOT NULL CONSTRAINT DF_MISA_CheckItem_Version DEFAULT 1,
    Remarks             NVARCHAR(MAX)  NULL,
    IsDeleted           BIT            NOT NULL CONSTRAINT DF_MISA_CheckItem_IsDeleted DEFAULT 0,
    CreatedAt           DATETIME2      NOT NULL CONSTRAINT DF_MISA_CheckItem_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt           DATETIME2      NULL,
    CONSTRAINT PK_MISA_CheckItem PRIMARY KEY CLUSTERED (Id)
);
GO

CREATE INDEX IX_MISA_CheckItem_PhaseCode  ON dbo.CN_AME_MISA_CheckItem (PhaseCode);
CREATE INDEX IX_MISA_CheckItem_IsKeyItem  ON dbo.CN_AME_MISA_CheckItem (IsKeyItem);
CREATE INDEX IX_MISA_CheckItem_Version    ON dbo.CN_AME_MISA_CheckItem (Version);
GO

/* --------------------------------------------------------------------------
   6. CN_AME_MISA_ReviewRecord 审核记录表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_ReviewRecord', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_ReviewRecord;
GO

CREATE TABLE dbo.CN_AME_MISA_ReviewRecord (
    Id            BIGINT IDENTITY(1,1) NOT NULL,
    ProjectId     BIGINT         NOT NULL,
    PhaseId       BIGINT         NOT NULL,
    ItemId        BIGINT         NOT NULL,
    ReviewerId    BIGINT         NOT NULL,
    Score         DECIMAL(5,2)   NULL,
    ResultText    NVARCHAR(100)  NULL,
    Comments      NVARCHAR(MAX)  NULL,
    Status        NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_Review_Status DEFAULT N'draft',
    SubmittedAt   DATETIME2      NULL,
    ConfirmedAt   DATETIME2      NULL,
    ConfirmedBy   BIGINT         NULL,
    CreatedAt     DATETIME2      NOT NULL CONSTRAINT DF_MISA_Review_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt     DATETIME2      NULL,
    CONSTRAINT PK_MISA_ReviewRecord PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT FK_MISA_Review_Project  FOREIGN KEY (ProjectId)  REFERENCES dbo.CN_AME_MISA_Project (Id),
    CONSTRAINT FK_MISA_Review_Phase    FOREIGN KEY (PhaseId)    REFERENCES dbo.CN_AME_MISA_Phase (Id),
    CONSTRAINT FK_MISA_Review_Item     FOREIGN KEY (ItemId)     REFERENCES dbo.CN_AME_MISA_CheckItem (Id),
    CONSTRAINT FK_MISA_Review_Reviewer FOREIGN KEY (ReviewerId) REFERENCES dbo.CN_AME_MISA_User (Id),
    CONSTRAINT FK_MISA_Review_Confirmer FOREIGN KEY (ConfirmedBy) REFERENCES dbo.CN_AME_MISA_User (Id),
    CONSTRAINT UX_MISA_Review_Project_Phase_Item UNIQUE NONCLUSTERED (ProjectId, PhaseId, ItemId)
);
GO

CREATE INDEX IX_MISA_Review_ReviewerId ON dbo.CN_AME_MISA_ReviewRecord (ReviewerId);
CREATE INDEX IX_MISA_Review_Status     ON dbo.CN_AME_MISA_ReviewRecord (Status);
GO

/* --------------------------------------------------------------------------
   7. CN_AME_MISA_Issue 问题表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_Issue', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_Issue;
GO

CREATE TABLE dbo.CN_AME_MISA_Issue (
    Id                  BIGINT IDENTITY(1,1) NOT NULL,
    ProjectId           BIGINT         NOT NULL,
    PhaseId             BIGINT         NOT NULL,
    ItemId              BIGINT         NULL,
    IssueNo             NVARCHAR(50)   NOT NULL,
    Title               NVARCHAR(200)  NOT NULL,
    Description         NVARCHAR(MAX)  NULL,
    OwnerUserId         BIGINT         NULL,
    OwnerDepartment     NVARCHAR(100)  NULL,
    Priority            NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_Issue_Priority DEFAULT N'medium',
    DueDate             DATETIME2      NULL,
    Status              NVARCHAR(30)   NOT NULL CONSTRAINT DF_MISA_Issue_Status DEFAULT N'open',
    ClosingStatus       NVARCHAR(50)   NULL,
    VerificationComments NVARCHAR(MAX) NULL,
    VerifiedBy          BIGINT         NULL,
    VerifiedAt          DATETIME2      NULL,
    ClosedAt            DATETIME2      NULL,
    Remarks             NVARCHAR(MAX)  NULL,
    CreatedBy           BIGINT         NULL,
    IsDeleted           BIT            NOT NULL CONSTRAINT DF_MISA_Issue_IsDeleted DEFAULT 0,
    CreatedAt           DATETIME2      NOT NULL CONSTRAINT DF_MISA_Issue_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt           DATETIME2      NULL,
    CONSTRAINT PK_MISA_Issue PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT UX_MISA_Issue_IssueNo UNIQUE NONCLUSTERED (IssueNo),
    CONSTRAINT FK_MISA_Issue_Project   FOREIGN KEY (ProjectId)   REFERENCES dbo.CN_AME_MISA_Project (Id),
    CONSTRAINT FK_MISA_Issue_Phase     FOREIGN KEY (PhaseId)     REFERENCES dbo.CN_AME_MISA_Phase (Id),
    CONSTRAINT FK_MISA_Issue_Item      FOREIGN KEY (ItemId)      REFERENCES dbo.CN_AME_MISA_CheckItem (Id),
    CONSTRAINT FK_MISA_Issue_Owner     FOREIGN KEY (OwnerUserId) REFERENCES dbo.CN_AME_MISA_User (Id),
    CONSTRAINT FK_MISA_Issue_Verifier  FOREIGN KEY (VerifiedBy)  REFERENCES dbo.CN_AME_MISA_User (Id),
    CONSTRAINT FK_MISA_Issue_Creator   FOREIGN KEY (CreatedBy)   REFERENCES dbo.CN_AME_MISA_User (Id)
);
GO

CREATE INDEX IX_MISA_Issue_ProjectId    ON dbo.CN_AME_MISA_Issue (ProjectId);
CREATE INDEX IX_MISA_Issue_Status       ON dbo.CN_AME_MISA_Issue (Status);
CREATE INDEX IX_MISA_Issue_OwnerUserId  ON dbo.CN_AME_MISA_Issue (OwnerUserId);
CREATE INDEX IX_MISA_Issue_DueDate      ON dbo.CN_AME_MISA_Issue (DueDate);
CREATE INDEX IX_MISA_Issue_Priority     ON dbo.CN_AME_MISA_Issue (Priority);
GO

/* --------------------------------------------------------------------------
   8. CN_AME_MISA_Attachment 附件表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_Attachment', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_Attachment;
GO

CREATE TABLE dbo.CN_AME_MISA_Attachment (
    Id            BIGINT IDENTITY(1,1) NOT NULL,
    OwnerType     NVARCHAR(20)   NOT NULL,
    OwnerId       BIGINT         NOT NULL,
    FileName      NVARCHAR(200)  NOT NULL,
    StoredPath    NVARCHAR(500)  NOT NULL,
    FileExtension NVARCHAR(20)   NULL,
    FileSize      BIGINT         NOT NULL CONSTRAINT DF_MISA_Attachment_Size DEFAULT 0,
    MimeType      NVARCHAR(100)  NULL,
    UploadedBy    BIGINT         NULL,
    CreatedAt     DATETIME2      NOT NULL CONSTRAINT DF_MISA_Attachment_CreatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT PK_MISA_Attachment PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT FK_MISA_Attachment_Uploader FOREIGN KEY (UploadedBy)
        REFERENCES dbo.CN_AME_MISA_User (Id)
);
GO

CREATE INDEX IX_MISA_Attachment_Owner ON dbo.CN_AME_MISA_Attachment (OwnerType, OwnerId);
GO

/* --------------------------------------------------------------------------
   9. CN_AME_MISA_RecordEntry Record 汇总表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_RecordEntry', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_RecordEntry;
GO

CREATE TABLE dbo.CN_AME_MISA_RecordEntry (
    Id           BIGINT IDENTITY(1,1) NOT NULL,
    ProjectId    BIGINT         NOT NULL,
    PhaseId      BIGINT         NOT NULL,
    ItemId       BIGINT         NOT NULL,
    MsiaCode     NVARCHAR(20)   NULL,
    ItemName     NVARCHAR(200)  NULL,
    Request      NVARCHAR(MAX)  NULL,
    Result       NVARCHAR(100)  NULL,
    Comments     NVARCHAR(MAX)  NULL,
    IssueDueDate DATETIME2      NULL,
    IssueStatus  NVARCHAR(20)   NULL,
    Remarks      NVARCHAR(MAX)  NULL,
    CreatedAt    DATETIME2      NOT NULL CONSTRAINT DF_MISA_Record_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt    DATETIME2      NULL,
    CONSTRAINT PK_MISA_RecordEntry PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT FK_MISA_Record_Project FOREIGN KEY (ProjectId) REFERENCES dbo.CN_AME_MISA_Project (Id),
    CONSTRAINT FK_MISA_Record_Phase   FOREIGN KEY (PhaseId)   REFERENCES dbo.CN_AME_MISA_Phase (Id),
    CONSTRAINT FK_MISA_Record_Item    FOREIGN KEY (ItemId)    REFERENCES dbo.CN_AME_MISA_CheckItem (Id),
    CONSTRAINT UX_MISA_Record_Project_Phase_Item UNIQUE NONCLUSTERED (ProjectId, PhaseId, ItemId)
);
GO

CREATE INDEX IX_MISA_Record_ProjectId ON dbo.CN_AME_MISA_RecordEntry (ProjectId);
GO

/* --------------------------------------------------------------------------
   10. CN_AME_MISA_Notification 系统通知表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_Notification', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_Notification;
GO

CREATE TABLE dbo.CN_AME_MISA_Notification (
    Id        BIGINT IDENTITY(1,1) NOT NULL,
    UserId    BIGINT         NOT NULL,
    Title     NVARCHAR(200)  NULL,
    Content   NVARCHAR(MAX)  NULL,
    Type      NVARCHAR(30)   NULL,
    Status    NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_Noti_Status DEFAULT N'unread',
    Link      NVARCHAR(500)  NULL,
    CreatedAt DATETIME2      NOT NULL CONSTRAINT DF_MISA_Noti_CreatedAt DEFAULT SYSDATETIME(),
    ReadAt    DATETIME2      NULL,
    CONSTRAINT PK_MISA_Notification PRIMARY KEY CLUSTERED (Id),
    CONSTRAINT FK_MISA_Noti_User FOREIGN KEY (UserId)
        REFERENCES dbo.CN_AME_MISA_User (Id)
);
GO

CREATE INDEX IX_MISA_Notification_UserId_Status ON dbo.CN_AME_MISA_Notification (UserId, Status);
GO

/* --------------------------------------------------------------------------
   11. CN_AME_MISA_EmailLog 邮件日志表
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'dbo.CN_AME_MISA_EmailLog', N'U') IS NOT NULL
    DROP TABLE dbo.CN_AME_MISA_EmailLog;
GO

CREATE TABLE dbo.CN_AME_MISA_EmailLog (
    Id           BIGINT IDENTITY(1,1) NOT NULL,
    ToAddress    NVARCHAR(500)  NULL,
    CcAddress    NVARCHAR(500)  NULL,
    Subject      NVARCHAR(300)  NULL,
    Body         NVARCHAR(MAX)  NULL,
    TemplateKey  NVARCHAR(50)   NULL,
    RefType      NVARCHAR(30)   NULL,
    RefId        BIGINT         NULL,
    Status       NVARCHAR(20)   NOT NULL CONSTRAINT DF_MISA_EmailLog_Status DEFAULT N'queued',
    ErrorMessage NVARCHAR(MAX)  NULL,
    SentAt       DATETIME2      NULL,
    CreatedAt    DATETIME2      NOT NULL CONSTRAINT DF_MISA_EmailLog_CreatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT PK_MISA_EmailLog PRIMARY KEY CLUSTERED (Id)
);
GO

CREATE INDEX IX_MISA_EmailLog_Status ON dbo.CN_AME_MISA_EmailLog (Status);
CREATE INDEX IX_MISA_EmailLog_Ref    ON dbo.CN_AME_MISA_EmailLog (RefType, RefId);
GO

/* --------------------------------------------------------------------------
   12. UpdatedAt 触发器（通用：更新时自动写入 UpdatedAt）
   -------------------------------------------------------------------------- */
IF OBJECT_ID(N'tr_MISA_User_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_User_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_User_UpdatedAt ON dbo.CN_AME_MISA_User
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE u SET u.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_User u
    INNER JOIN inserted i ON u.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_Project_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_Project_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_Project_UpdatedAt ON dbo.CN_AME_MISA_Project
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_Project t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_Phase_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_Phase_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_Phase_UpdatedAt ON dbo.CN_AME_MISA_Phase
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_Phase t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_CheckItem_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_CheckItem_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_CheckItem_UpdatedAt ON dbo.CN_AME_MISA_CheckItem
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_CheckItem t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_Review_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_Review_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_Review_UpdatedAt ON dbo.CN_AME_MISA_ReviewRecord
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_ReviewRecord t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_Issue_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_Issue_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_Issue_UpdatedAt ON dbo.CN_AME_MISA_Issue
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_Issue t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

IF OBJECT_ID(N'tr_MISA_Record_UpdatedAt', N'TR') IS NOT NULL DROP TRIGGER tr_MISA_Record_UpdatedAt;
GO
CREATE TRIGGER tr_MISA_Record_UpdatedAt ON dbo.CN_AME_MISA_RecordEntry
AFTER UPDATE AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t SET t.UpdatedAt = SYSDATETIME()
    FROM dbo.CN_AME_MISA_RecordEntry t
    INNER JOIN inserted i ON t.Id = i.Id;
END;
GO

PRINT N'=== MSIA 审核管理系统数据库表结构创建完成 ===';
GO
