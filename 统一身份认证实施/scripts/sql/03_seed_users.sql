/* ============================================================
   03_seed_users.sql
   SSO 种子数据灌数脚本（T01，L1 种子：两系统真实用户并集）
   数据来源（2026-11-02 实测，已二次核对）:
   - MSIA: CN_AME.dbo.CN_AME_MISA_User WHERE PasswordHash 非空（14 行，含 3 个 status=0 测试账号）
   - BOL : CMC.db_datawriter.CN_IE_BOL_Employee（8 行，含 guest 游客，不入 SSO）
   去重口径: yaole(MSIA) 与 Yaolei(BOL) 同为姚雷 → 合并为一条(login_name 小写 yaole);
             zhangya4(MSIA) 与 Zhangy4(BOL) 同为张琰玉 → 合并为一条(zhangya4)。
   共 13 人。测试账号 lead_reviewer01/reviewer01/reviewee01 不纳入（用户已确认）。
   邮箱口径（2026-11-02 调整：邮箱暂不用管理）:
   - 用两系统实测真实邮箱，MSIA 优先，BOL 仅补 chenca/libi2 两个 BOL 独有账号；
   - zhaop3 在 BOL 无邮箱，取 MSIA 实测 Pengcheng.Zhao@inalfa.com（并集口径）；
   - email 列允许空/重复（唯一索引已于同日降级为普通索引 IX_，realm 侧关闭
     Duplicate emails 检查）；无邮箱用户走控制台代设密兜底（见 realm-setup.md）。
   特性: 幂等（先查后插，employee_no/login_name 命中即跳过）
   ============================================================ */
USE CN_AME;
GO

/* ---------- 0. 灌数前查重（预期全部为 0） ---------- */
SELECT COUNT(*) AS existing_users FROM dbo.CN_AME_SSO_User;
SELECT COUNT(*) AS existing_maps  FROM dbo.CN_AME_SSO_UserMap;
SELECT COUNT(*) AS existing_perms FROM dbo.CN_AME_SSO_PermLedger;
GO

/* ============================================================
   1. CN_AME_SSO_User：13 人种子
   source='MANUAL'（手工盘点种子，MERGE 时不覆盖、不被未来 AD 同步改写）
   status=1（在职；注: MSIA 本地 yaole 行 status=0，中央表按 BOL 在职口径置 1，
             已在实施报告中记录，待业务确认）
   pwd_set=0（尚未在 Keycloak 设密）
   ============================================================ */

/* admin —— MSIA/BOL 双系统管理员（系统账号，无自然人姓名） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'admin')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('admin', 'admin', N'系统管理员', 'admin@inalfa.local', 1, 'MANUAL', 0);

/* ligu 李国柱 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'ligu')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('ligu', 'ligu', N'李国柱', 'Guozhu.Li@inalfa.com', 1, 'MANUAL', 0);

/* yangli1 杨莉 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'yangli1')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('yangli1', 'yangli1', N'杨莉', 'Tyra.Yang@inalfa.com', 1, 'MANUAL', 0);

/* yaole 姚雷（MSIA 用户名 yaole / BOL 用户名 Yaolei，对照表见下） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'yaole')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('yaole', 'yaole', N'姚雷', 'Leo.Yao@inalfa.com', 1, 'MANUAL', 0);

/* zhangya4 张琰玉（MSIA zhangya4 / BOL Zhangy4，对照表见下） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'zhangya4')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('zhangya4', 'zhangya4', N'张琰玉', 'Fisher.Zhang@inalfa.com', 1, 'MANUAL', 0);

/* fansh1 范圣波 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'fansh1')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('fansh1', 'fansh1', N'范圣波', 'Shengbo.Fan2@inalfa.com', 1, 'MANUAL', 0);

/* luyu 路玉龙 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'luyu')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('luyu', 'luyu', N'路玉龙', 'Yulong.Lu@inalfa.com', 1, 'MANUAL', 0);

/* zhangp2 张朋飞 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'zhangp2')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('zhangp2', 'zhangp2', N'张朋飞', 'Pengfei.Zhang@inalfa.com', 1, 'MANUAL', 0);

/* zhangpe 张鹏鹏 */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'zhangpe')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('zhangpe', 'zhangpe', N'张鹏鹏', 'zhangpe@ap.inalfa.local', 1, 'MANUAL', 0);

/* zhaop3 赵鹏程（BOL 本地无邮箱，取 MSIA 实测邮箱） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'zhaop3')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('zhaop3', 'zhaop3', N'赵鹏程', 'Pengcheng.Zhao@inalfa.com', 1, 'MANUAL', 0);

/* abelmi2 Michel van Abel */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'abelmi2')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('abelmi2', 'abelmi2', N'Michel van Abel', 'abelmi2@ap.inalfa.local', 1, 'MANUAL', 0);

/* chenca 陈灿光（仅 BOL 有账号，邮箱取自 BOL 实测） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'chenca')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('chenca', 'chenca', N'陈灿光', 'Roger.Chen@inalfa.com', 1, 'MANUAL', 0);

/* libi2 李冰（仅 BOL 有账号，邮箱取自 BOL 实测） */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_User WHERE employee_no = 'libi2')
INSERT INTO dbo.CN_AME_SSO_User
    (employee_no, login_name, display_name, email, status, source, pwd_set)
VALUES
    ('libi2', 'libi2', N'李冰', 'bing.li@inalfa.com', 1, 'MANUAL', 0);
GO

/* ============================================================
   2. CN_AME_SSO_UserMap：BOL 存量用户名 ≠ 中央 login_name 的对照
   （MSIA 侧用户名与 login_name 一致，回落逻辑即可命中，无需建行）
   ============================================================ */

/* 姚雷: MSIA=yaole(小写) / BOL=Yaolei(首字母大写) */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap
               WHERE system_code = 'bol' AND local_username = 'Yaolei')
INSERT INTO dbo.CN_AME_SSO_UserMap
    (employee_no, system_code, local_username, match_key, remark)
VALUES
    ('yaole', 'bol', 'Yaolei', 'USERNAME', N'MSIA用户名yaole与BOL用户名Yaolei大小写/拼写不一致（实测案例）');

/* 张琰玉: MSIA=zhangya4(小写) / BOL=Zhangy4(首字母大写) */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_UserMap
               WHERE system_code = 'bol' AND local_username = 'Zhangy4')
INSERT INTO dbo.CN_AME_SSO_UserMap
    (employee_no, system_code, local_username, match_key, remark)
VALUES
    ('zhangya4', 'bol', 'Zhangy4', 'USERNAME', N'MSIA用户名zhangya4与BOL用户名Zhangy4大小写不一致（实测案例）');
GO

/* ============================================================
   3. CN_AME_SSO_PermLedger：权限台账首批（每人每系统一行）
   MSIA 角色来源: CN_AME_MISA_User 实测（PasswordHash 非空的 11 名非测试用户）
   BOL  角色来源: CN_IE_BOL_Employee 实测（7 人，guest 游客不入台账）
   ============================================================ */

/* ---------- 3.1 MSIA 台账（11 行） ---------- */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'admin' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('admin', 'msia', 'admin', 'initial-migration', N'MSIA 实测角色 admin');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'ligu' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('ligu', 'msia', 'admin', 'initial-migration', N'MSIA 实测角色 admin');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'yangli1' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('yangli1', 'msia', 'admin', 'initial-migration', N'MSIA 实测角色 admin');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'yaole' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('yaole', 'msia', 'admin', 'initial-migration', N'MSIA 实测角色 admin（注意: MSIA 本地行 status=0，待业务确认是否恢复）');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhangya4' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhangya4', 'msia', 'lead_reviewer', 'initial-migration', N'MSIA 实测角色 lead_reviewer');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'fansh1' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('fansh1', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'luyu' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('luyu', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhangp2' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhangp2', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhangpe' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhangpe', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhaop3' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhaop3', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'abelmi2' AND system_code = 'msia' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('abelmi2', 'msia', 'reviewee', 'initial-migration', N'MSIA 实测角色 reviewee');
GO

/* ---------- 3.2 BOL 台账（7 行；employee_no 用中央表主键，不用 BOL 本地名） ---------- */
IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'admin' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('admin', 'bol', 'ADMIN', 'initial-migration', N'BOL 实测角色 ADMIN');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'ligu' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('ligu', 'bol', 'VIEWER', 'initial-migration', N'BOL 实测角色 VIEWER');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'chenca' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('chenca', 'bol', 'VIEWER', 'initial-migration', N'BOL 实测角色 VIEWER');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'libi2' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('libi2', 'bol', 'VIEWER', 'initial-migration', N'BOL 实测角色 VIEWER');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'yaole' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('yaole', 'bol', 'ADMIN', 'initial-migration', N'BOL 实测 Yaolei=ADMIN（对照表映射）');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhangya4' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhangya4', 'bol', 'ADMIN', 'initial-migration', N'BOL 实测 Zhangy4=ADMIN（对照表映射）');

IF NOT EXISTS (SELECT 1 FROM dbo.CN_AME_SSO_PermLedger
               WHERE employee_no = 'zhaop3' AND system_code = 'bol' AND revoked_at IS NULL)
INSERT INTO dbo.CN_AME_SSO_PermLedger (employee_no, system_code, role_name, granted_by, remark)
VALUES ('zhaop3', 'bol', 'ENGINEER', 'initial-migration', N'BOL 实测角色 ENGINEER（must_change_password=1；BOL 本地无邮箱，中央表用 MSIA 邮箱）');
GO

/* ============================================================
   4. 灌数后自查（预期: User=13, UserMap=2, PermLedger=18, SyncLog=0）
   ============================================================ */
SELECT COUNT(*) AS user_count   FROM dbo.CN_AME_SSO_User;
SELECT COUNT(*) AS map_count    FROM dbo.CN_AME_SSO_UserMap;
SELECT COUNT(*) AS perm_count   FROM dbo.CN_AME_SSO_PermLedger;
SELECT COUNT(*) AS synclog_count FROM dbo.CN_AME_SSO_SyncLog;
GO

/* 明细核对（人工过目） */
SELECT employee_no, login_name, display_name, email, status, source, pwd_set
FROM dbo.CN_AME_SSO_User ORDER BY employee_no;
SELECT system_code, local_username, employee_no FROM dbo.CN_AME_SSO_UserMap ORDER BY system_code, local_username;
SELECT system_code, employee_no, role_name FROM dbo.CN_AME_SSO_PermLedger
WHERE revoked_at IS NULL ORDER BY system_code, employee_no;
GO
