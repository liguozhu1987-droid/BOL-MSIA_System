"""临时数据检查脚本"""
import pyodbc

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;'
    'DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;'
    'TrustServerCertificate=yes;'
)
cursor = conn.cursor()

print('=== Project PlantMe values ===')
cursor.execute('SELECT DISTINCT PlantMe FROM CN_AME_MISA_Project WHERE IsDeleted=0')
for r in cursor.fetchall():
    print(repr(r[0]))

print('\n=== Issue OwnerCompany values ===')
cursor.execute('SELECT DISTINCT OwnerCompany FROM CN_AME_MISA_Issue WHERE IsDeleted=0')
for r in cursor.fetchall():
    print(repr(r[0]))

print('\n=== Project Name + PlantMe ===')
cursor.execute('SELECT Id, Name, Code, PlantMe FROM CN_AME_MISA_Project WHERE IsDeleted=0')
for r in cursor.fetchall():
    print(f'Id={r[0]} Name={repr(r[1])} Code={r[2]} PlantMe={repr(r[3])}')

print('\n=== ReviewRecord with Score ===')
cursor.execute('SELECT TOP 10 ProjectId, Score, PhaseCode, ItemNo FROM CN_AME_MISA_ReviewRecord WHERE Score IS NOT NULL')
for r in cursor.fetchall():
    print(r)

print('\n=== Issue summary ===')
cursor.execute(
    "SELECT COUNT(*), "
    "SUM(CASE WHEN Status='closed' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN DueDate IS NOT NULL AND DueDate < GETUTCDATE() AND Status <> 'closed' THEN 1 ELSE 0 END) "
    "FROM CN_AME_MISA_Issue WHERE IsDeleted=0"
)
r = cursor.fetchone()
print(f'Total={r[0]} Closed={r[1]} Overdue={r[2]}')

print('\n=== Issue samples ===')
cursor.execute(
    'SELECT TOP 5 Id, IssueNo, Title, OwnerName, OwnerCompany, Severity, Status, DueDate, ProjectId '
    'FROM CN_AME_MISA_Issue WHERE IsDeleted=0'
)
for r in cursor.fetchall():
    print(r)

print('\n=== HRDB Plant mapping check ===')
cursor.execute(
    "SELECT DISTINCT location FROM OPENROWSET('SQLNCLI', "
    "'Server=IRSCNYTFINEREPORT.ap.inalfa.local;UID=ytview;PWD=Inalfa@2021;', "
    "'SELECT DISTINCT location FROM HRDB.dbo.CN_AME_lineDevelopment_orderBasicInfor')",
    timeout=10
)
for r in cursor.fetchall():
    print(repr(r[0]))

conn.close()
