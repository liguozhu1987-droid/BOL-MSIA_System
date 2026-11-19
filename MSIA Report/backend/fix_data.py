"""修复 Project 乱码数据 + 模拟超期问题数据"""
import pyodbc
from datetime import datetime, timedelta

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;'
    'DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;'
    'TrustServerCertificate=yes;'
)
cursor = conn.cursor()

# 1. 修复 Project 乱码数据
print('=== 修复 Project 乱码数据 ===')
cursor.execute(
    "UPDATE CN_AME_MISA_Project SET Name=N'Mock Project - Test', PlantMe=N'SH' WHERE Id=1"
)
print(f'Updated {cursor.rowcount} project record(s)')

# 2. 模拟超期问题数据 (DueDate 在过去, Status 非 closed)
print('\n=== 模拟超期问题数据 ===')

now = datetime.utcnow()
overdue_issues = [
    # (IssueNo, Title, OwnerName, OwnerCompany, Severity, Status, DueDate, ProjectId, PhaseCode, Priority)
    ('ISS-20260813-001', 'Design freeze delayed - missing approvals', 'Zhang Longfei', 'SH', 'H', 'open',
     now - timedelta(days=5), 1, 'MSIA3', 'high'),
    ('ISS-20260813-002', 'PVP report not submitted', 'Fan Shengbo', 'SH', 'M', 'in_progress',
     now - timedelta(days=3), 1, 'MSIA4', 'medium'),
    ('ISS-20260813-003', 'Supplier kickoff meeting pending', 'Zhang Longfei', 'BJ', 'H', 'open',
     now - timedelta(days=7), 1, 'MSIA1', 'high'),
    ('ISS-20260813-004', 'Final buyoff plan missing signature', 'Fan Shengbo', 'GZ', 'L', 'open',
     now - timedelta(days=2), 1, 'MSIA5', 'low'),
    ('ISS-20260813-005', 'GRR data validation incomplete', 'Li Wei', 'WH', 'M', 'in_progress',
     now - timedelta(days=1), 1, 'MSIA4', 'medium'),
    ('ISS-20260813-006', 'Drawing release overdue', 'Wang Ming', 'CC', 'H', 'open',
     now - timedelta(days=10), 1, 'MSIA2', 'high'),
    # 一条已关闭的问题 (用于关闭率统计)
    ('ISS-20260813-007', 'Initial design review completed', 'Fan Shengbo', 'SH', 'L', 'closed',
     now - timedelta(days=15), 1, 'MSIA2', 'low'),
]

for issue in overdue_issues:
    cursor.execute(
        "INSERT INTO CN_AME_MISA_Issue "
        "(IssueNo, Title, OwnerName, OwnerCompany, Severity, Status, DueDate, ProjectId, PhaseCode, Priority, IsDeleted, CreatedAt, UpdatedAt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, GETUTCDATE(), GETUTCDATE())",
        issue
    )
print(f'Inserted {len(overdue_issues)} issue records')

# 3. 更新现有问题中 OwnerCompany 为 None 的记录
print('\n=== 更新现有问题的 OwnerCompany ===')
cursor.execute(
    "UPDATE CN_AME_MISA_Issue SET OwnerCompany='SH' WHERE OwnerCompany IS NULL AND IssueNo='ISS-20260812-001'"
)
print(f'Updated {cursor.rowcount} issue(s)')

conn.commit()

# 4. 验证数据
print('\n=== 验证 Project ===')
cursor.execute('SELECT Id, Name, PlantMe FROM CN_AME_MISA_Project WHERE IsDeleted=0')
for r in cursor.fetchall():
    print(f'  Id={r[0]} Name={r[1]} PlantMe={r[2]}')

print('\n=== 验证 Issue 统计 ===')
cursor.execute(
    "SELECT COUNT(*), "
    "SUM(CASE WHEN Status='closed' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN DueDate IS NOT NULL AND DueDate < GETUTCDATE() AND Status <> 'closed' THEN 1 ELSE 0 END) "
    "FROM CN_AME_MISA_Issue WHERE IsDeleted=0"
)
r = cursor.fetchone()
print(f'  Total={r[0]} Closed={r[1]} Overdue={r[2]}')

print('\n=== 验证 Issue by OwnerCompany ===')
cursor.execute(
    "SELECT OwnerCompany, COUNT(*), "
    "SUM(CASE WHEN Severity='H' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN Severity='M' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN Severity='L' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN Status='closed' THEN 1 ELSE 0 END) "
    "FROM CN_AME_MISA_Issue WHERE IsDeleted=0 GROUP BY OwnerCompany"
)
for r in cursor.fetchall():
    print(f'  Plant={r[0]} Total={r[1]} H={r[2]} M={r[3]} L={r[4]} Closed={r[5]}')

conn.close()
print('\nDone!')
