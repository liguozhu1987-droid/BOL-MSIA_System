"""为 CN_AME_MISA_Issue 表添加 OwnerUserName 列"""
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
        WHERE TABLE_NAME = 'CN_AME_MISA_Issue'
        AND COLUMN_NAME = 'OwnerUserName'
    """)
    if cur.fetchone():
        print("列 OwnerUserName 已存在, 跳过创建")
    else:
        # 添加列
        cur.execute("""
            ALTER TABLE CN_AME_MISA_Issue
            ADD OwnerUserName NVARCHAR(100) NULL
        """)
        # 创建索引
        cur.execute("""
            CREATE INDEX IX_MISA_CN_AME_MISA_Issue_OwnerUserName
            ON CN_AME_MISA_Issue(OwnerUserName)
        """)
        conn.commit()
        print("已添加列 OwnerUserName 并创建索引")

    conn.close()


if __name__ == "__main__":
    main()
