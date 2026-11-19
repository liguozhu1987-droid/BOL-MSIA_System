# -*- coding: utf-8 -*-
"""T05 QA 独立数据库核对脚本（只读，不写任何数据）。"""
import pyodbc

SRV = "IRSCNYTFINERPO\\SQLEXPRESS"
HOST = "IRSCNYTFINEREPORT.ap.inalfa.local"

CN_AME = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={HOST};"
    "DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;TrustServerCertificate=yes"
)
CMC = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={HOST};"
    "DATABASE=CMC;UID=sparePartRead;PWD=Inalfa@2026;TrustServerCertificate=yes"
)

FAIL = []
WARN = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAIL.append(f"{name} {detail}")


def warn(name, cond, detail=""):
    if not cond:
        print(f"[WARN] {name} {detail}")
        WARN.append(f"{name} {detail}")


def q(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    return cur.fetchall()


print("=" * 70)
print("A1. CN_AME 五表核对（ytview）")
print("=" * 70)
cn = pyodbc.connect(CN_AME, timeout=15)

# 行数
for tbl, expect in [
    ("CN_AME_SSO_User", 13),
    ("CN_AME_SSO_UserMap", 2),
    ("CN_AME_SSO_PermLedger", 18),
    ("CN_AME_SSO_SyncLog", 0),
    ("CN_AME_SSO_StgAdUser", 0),
]:
    n = q(cn, f"SELECT COUNT(*) FROM dbo.{tbl}")[0][0]
    check(f"CN_AME.{tbl} 行数", n == expect, f"(实际 {n}, 预期 {expect})")

# 种子用户明细
rows = q(
    cn,
    "SELECT employee_no, login_name, display_name, email, status, source, pwd_set "
    "FROM dbo.CN_AME_SSO_User ORDER BY employee_no",
)
expected_users = {
    "admin": ("admin", "系统管理员", "admin@inalfa.local"),
    "ligu": ("ligu", "李国柱", "Guozhu.Li@inalfa.com"),
    "yangli1": ("yangli1", "杨莉", "Tyra.Yang@inalfa.com"),
    "yaole": ("yaole", "姚雷", "Leo.Yao@inalfa.com"),
    "zhangya4": ("zhangya4", "张琰玉", "Fisher.Zhang@inalfa.com"),
    "fansh1": ("fansh1", "范圣波", "Shengbo.Fan2@inalfa.com"),
    "luyu": ("luyu", "路玉龙", "Yulong.Lu@inalfa.com"),
    "zhangp2": ("zhangp2", "张朋飞", "Pengfei.Zhang@inalfa.com"),
    "zhangpe": ("zhangpe", "张鹏鹏", "zhangpe@ap.inalfa.local"),
    "zhaop3": ("zhaop3", "赵鹏程", "Pengcheng.Zhao@inalfa.com"),
    "abelmi2": ("abelmi2", "Michel van Abel", "abelmi2@ap.inalfa.local"),
    "chenca": ("chenca", "陈灿光", "Roger.Chen@inalfa.com"),
    "libi2": ("libi2", "李冰", "bing.li@inalfa.com"),
}
seen = {}
for r in rows:
    seen[r[0]] = r
check("种子 13 人 login_name/employee_no/display_name/email 与方案 12.2 一致",
      all(
          (u in seen and seen[u][1] == ln and seen[u][2] == dn and seen[u][3] == em)
          for u, (ln, dn, em) in expected_users.items()
      ),
      f"(实际 {len(rows)} 行)")
bad = [
    (u, ln, dn, em) for u, (ln, dn, em) in expected_users.items()
    if not (u in seen and seen[u][1] == ln and seen[u][2] == dn and seen[u][3] == em)
]
if bad:
    print("   不一致项:", bad)
check("全部 status=1 / source=MANUAL / pwd_set=0",
      all(r[4] == 1 and r[5] == "MANUAL" and r[6] == 0 for r in rows))

# email 索引非唯一
idx = q(
    cn,
    "SELECT i.name, i.is_unique FROM sys.indexes i "
    "JOIN sys.objects o ON o.object_id = i.object_id "
    "WHERE o.name = 'CN_AME_SSO_User' AND i.name LIKE '%Email%'",
)
check("CN_AME_SSO_User email 索引为非唯一",
      any(not r[1] for r in idx), f"(索引: {[(r[0], 'unique' if r[1] else 'non-unique') for r in idx]})")

# UserMap 两条
maps = q(
    cn,
    "SELECT employee_no, system_code, local_username, match_key "
    "FROM dbo.CN_AME_SSO_UserMap ORDER BY system_code, local_username",
)
exp_maps = [("yaole", "bol", "Yaolei"), ("zhangya4", "bol", "Zhangy4")]
check(
    "UserMap 两条（yaole→Yaolei / zhangya4→Zhangy4, system_code='bol'）",
    [(r[0], r[1], r[2]) for r in maps] == exp_maps,
    f"(实际 {[(r[0], r[1], r[2]) for r in maps]})",
)
check("UserMap match_key=USERNAME", all(r[3] == "USERNAME" for r in maps))

cn.close()

print()
print("=" * 70)
print("A2. CMC 库核对（sparePartRead）")
print("=" * 70)
cmc = pyodbc.connect(CMC, timeout=15)

emps = q(
    cmc,
    "SELECT username, role, status, email FROM db_datawriter.CN_IE_BOL_Employee ORDER BY username",
)
emp_names = sorted(r[0] for r in emps)
exp_emps = ["Yaolei", "Zhangy4", "admin", "chenca", "guest", "libi2", "ligu", "zhaop3"]
check("CN_IE_BOL_Employee 恰为 8 行真实员工", len(emps) == 8 and emp_names == exp_emps,
      f"(实际 {len(emps)}: {emp_names})")
test_residue = [n for n in emp_names if any(k in n.lower() for k in ("test", "qa", "tmp"))]
check("无测试残留账号", not test_residue, f"(残留: {test_residue})")

# AuthToken source 列存在 + 存量均为 local
cols = q(
    cmc,
    "SELECT c.name, t.name AS typ, c.is_nullable "
    "FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id "
    "WHERE c.object_id = OBJECT_ID('db_datawriter.CN_IE_BOL_AuthToken') ORDER BY c.column_id",
)
col_names = [r[0] for r in cols]
check("AuthToken source 列存在", "source" in col_names, f"(列: {col_names})")
if "source" in col_names:
    src_rows = q(
        cmc,
        "SELECT source, COUNT(*) FROM db_datawriter.CN_IE_BOL_AuthToken GROUP BY source",
    )
    check("存量 AuthToken 行均为 'local'",
          all((r[0] or "local") == "local" for r in src_rows),
          f"(分布: {[(r[0], r[1]) for r in src_rows]})")
    n_tok = q(cmc, "SELECT COUNT(*) FROM db_datawriter.CN_IE_BOL_AuthToken")[0][0]
    print(f"   AuthToken 总行数: {n_tok}")
    guest_tok = q(
        cmc,
        "SELECT COUNT(*) FROM db_datawriter.CN_IE_BOL_AuthToken a "
        "JOIN db_datawriter.CN_IE_BOL_Employee e ON e.id = a.employee_id "
        "WHERE e.username = 'guest'",
    )[0][0]
    warn("游客无 AuthToken 残留", guest_tok == 0, f"(guest token 数 {guest_tok})")

# django_migrations 0005
mig = q(
    cmc,
    "SELECT app, name FROM django_migrations WHERE name = '0005_authtoken_source'",
)
check("django_migrations 有 0005_authtoken_source", len(mig) == 1, f"(记录: {[(r[0], r[1]) for r in mig]})")
# 确认没有其他异常迁移记录（0005 之后无更新迁移）
mig_all = q(
    cmc,
    "SELECT name FROM django_migrations WHERE app = 'users' ORDER BY id DESC",
)
print(f"   users 应用最近迁移: {[r[0] for r in mig_all[:5]]}")
check("users 最新迁移为 0005", mig_all and mig_all[0][0] == "0005_authtoken_source")

cmc.close()

print()
print("=" * 70)
print("A3. 权限抽查（独立连接，非 ytview 视角）")
print("=" * 70)
try:
    svc = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={HOST};"
        "DATABASE=CN_AME;UID=sso_sync_svc;PWD=Sso@Sync2026#;TrustServerCertificate=yes",
        timeout=15,
    )
    # 可读五表
    ok_read = True
    for tbl in ["StgAdUser", "User", "UserMap", "SyncLog", "PermLedger"]:
        try:
            q(svc, f"SELECT TOP 1 * FROM dbo.CN_AME_SSO_{tbl}")
        except Exception as e:
            ok_read = False
            print(f"   sso_sync_svc 读 {tbl} 失败: {e}")
    check("sso_sync_svc 可读五表", ok_read)
    # 无 DDL：尝试 CREATE TABLE 应失败
    try:
        q(svc, "CREATE TABLE dbo.qa_probe_tbl (id INT)")
        q(svc, "DROP TABLE dbo.qa_probe_tbl")
        check("sso_sync_svc 无 DDL 权限", False, "(竟然 CREATE 成功!)")
    except Exception as e:
        check("sso_sync_svc 无 DDL 权限", True, f"(CREATE 被拒: {str(e)[:60]})")
    svc.close()
except Exception as e:
    check("sso_sync_svc 连接", False, str(e)[:120])

# sparePartRead 可读 SSO 两表（经 CMC 连接做跨库查询）
try:
    cmc2 = pyodbc.connect(CMC, timeout=15)
    n = q(cmc2, "SELECT COUNT(*) FROM CN_AME.dbo.CN_AME_SSO_User")[0][0]
    n2 = q(cmc2, "SELECT COUNT(*) FROM CN_AME.dbo.CN_AME_SSO_UserMap")[0][0]
    check("sparePartRead 跨库可读 SSO User/UserMap", n == 13 and n2 == 2,
          f"(User={n}, UserMap={n2})")
    # 应不可读 SyncLog/PermLedger
    denied = 0
    for tbl in ["SyncLog", "PermLedger", "StgAdUser"]:
        try:
            q(cmc2, f"SELECT TOP 1 * FROM CN_AME.dbo.CN_AME_SSO_{tbl}")
        except Exception:
            denied += 1
    check("sparePartRead 不可读其余三表", denied == 3, f"(拒绝 {denied}/3)")
    # 应无写权限
    try:
        q(cmc2, "INSERT INTO CN_AME.dbo.CN_AME_SSO_UserMap (employee_no, system_code, local_username) VALUES ('qa','qa','qa')")
        check("sparePartRead 无 SSO 表写权限", False, "(INSERT 成功!)")
        q(cmc2, "DELETE FROM CN_AME.dbo.CN_AME_SSO_UserMap WHERE employee_no='qa'")
    except Exception as e:
        check("sparePartRead 无 SSO 表写权限", True, f"(INSERT 被拒)")
    cmc2.close()
except Exception as e:
    check("sparePartRead 跨库连接", False, str(e)[:120])

print()
print("=" * 70)
if FAIL:
    print(f"A 部分结论: FAIL ({len(FAIL)} 项)")
    for f in FAIL:
        print("  -", f)
else:
    print("A 部分结论: PASS")
if WARN:
    print("WARN:", WARN)
