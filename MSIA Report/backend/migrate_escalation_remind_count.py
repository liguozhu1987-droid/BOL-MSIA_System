"""为 CN_AME_MISA_EscalationLog 表添加 RemindCount 列 (第 N 次提醒计数)"""
import pyodbc

CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=IRSCNYTFINEREPORT.ap.inalfa.local;"
    "DATABASE=CN_AME;UID=ytview;PWD=Inalfa@2021;"
    "TrustServerCertificate=yes;"
)


def main():
    conn = pyodbc.connect(CONN)
    cur = conn.cursor()

    # 检查列是否存在
    cur.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'CN_AME_MISA_EscalationLog'
        AND COLUMN_NAME = 'RemindCount'
    """)
    if cur.fetchone():
        print("列 RemindCount 已存在, 跳过创建")
    else:
        cur.execute("""
            ALTER TABLE CN_AME_MISA_EscalationLog
            ADD RemindCount INT NULL
        """)
        conn.commit()
        print("已添加列 RemindCount")

    # 历史日志回填为第 1 次
    cur.execute("""
        UPDATE CN_AME_MISA_EscalationLog
        SET RemindCount = 1
        WHERE RemindCount IS NULL
    """)
    updated = cur.rowcount
    conn.commit()
    print(f"历史日志回填 RemindCount=1: {updated} 行")

    conn.close()


if __name__ == "__main__":
    main()
