"""迁移: 将 ReviewRecord 和 Issue 表的文本字段从 VARCHAR 改为 NVARCHAR

修复中文乱码问题 (?????) - 将 Text -> UnicodeText, String -> Unicode
"""
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import engine  # noqa: E402


# 需要迁移的表和列: (表名, 列名, 新类型)
MIGRATIONS = [
    # User 表 - 中文相关字段
    ("CN_AME_MISA_User", "DisplayName", "NVARCHAR(200)"),
    ("CN_AME_MISA_User", "Department", "NVARCHAR(200)"),
    # UserSyncLog 表
    ("CN_AME_MISA_UserSyncLog", "ErrorMessage", "NVARCHAR(2000)"),
    # ReviewRecord 表
    ("CN_AME_MISA_ReviewRecord", "ResultText", "NVARCHAR(1000)"),
    ("CN_AME_MISA_ReviewRecord", "Comments", "NVARCHAR(MAX)"),
    # Issue 表
    ("CN_AME_MISA_Issue", "Title", "NVARCHAR(500)"),
    ("CN_AME_MISA_Issue", "Description", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_Issue", "OwnerName", "NVARCHAR(100)"),
    ("CN_AME_MISA_Issue", "OwnerDepartment", "NVARCHAR(200)"),
    ("CN_AME_MISA_Issue", "ClosingStatus", "NVARCHAR(200)"),
    ("CN_AME_MISA_Issue", "VerificationComments", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_Issue", "Remarks", "NVARCHAR(MAX)"),
    # IssueComment 表 (整表迁移)
    ("CN_AME_MISA_IssueComment", "AuthorName", "NVARCHAR(200)"),
    ("CN_AME_MISA_IssueComment", "Content", "NVARCHAR(MAX)"),
    # Project 表
    ("CN_AME_MISA_Project", "Name", "NVARCHAR(255)"),
    ("CN_AME_MISA_Project", "Type", "NVARCHAR(100)"),
    ("CN_AME_MISA_Project", "CmcAme", "NVARCHAR(255)"),
    ("CN_AME_MISA_Project", "PlantMe", "NVARCHAR(255)"),
    # Phase 表
    ("CN_AME_MISA_Phase", "Name", "NVARCHAR(200)"),
    ("CN_AME_MISA_Phase", "TimingDescription", "NVARCHAR(1000)"),
    ("CN_AME_MISA_Phase", "MainTargets", "NVARCHAR(2000)"),
    # CheckItem 表 (中文字段最多)
    ("CN_AME_MISA_CheckItem", "Name", "NVARCHAR(500)"),
    ("CN_AME_MISA_CheckItem", "Request", "NVARCHAR(2000)"),
    ("CN_AME_MISA_CheckItem", "RequestDescription", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_CheckItem", "ReferenceDocuments", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_CheckItem", "ScoreOptions", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_CheckItem", "DefaultResultText", "NVARCHAR(1000)"),
    ("CN_AME_MISA_CheckItem", "Remarks", "NVARCHAR(MAX)"),
    # PhaseReviewItem 表 (注意表名是 MSIA 不是 MISA)
    ("CN_AME_MSIA_PhaseReviewItem", "ItemName", "NVARCHAR(500)"),
    ("CN_AME_MSIA_PhaseReviewItem", "Request", "NVARCHAR(200)"),
    ("CN_AME_MSIA_PhaseReviewItem", "DefaultResultText", "NVARCHAR(1000)"),
    # Attachment 表
    ("CN_AME_MISA_Attachment", "FileName", "NVARCHAR(500)"),
    # EmailLog 表
    ("CN_AME_MISA_EmailLog", "Subject", "NVARCHAR(500)"),
    ("CN_AME_MISA_EmailLog", "Body", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_EmailLog", "ErrorMessage", "NVARCHAR(2000)"),
    # Notification 表
    ("CN_AME_MISA_Notification", "Title", "NVARCHAR(255)"),
    ("CN_AME_MISA_Notification", "Content", "NVARCHAR(MAX)"),
    # RecordEntry 表
    ("CN_AME_MISA_RecordEntry", "ItemName", "NVARCHAR(500)"),
    ("CN_AME_MISA_RecordEntry", "Request", "NVARCHAR(2000)"),
    ("CN_AME_MISA_RecordEntry", "Result", "NVARCHAR(1000)"),
    ("CN_AME_MISA_RecordEntry", "Comments", "NVARCHAR(MAX)"),
    ("CN_AME_MISA_RecordEntry", "Remarks", "NVARCHAR(MAX)"),
]


def migrate() -> None:
    print("[migrate] 开始: 将文本字段从 VARCHAR 改为 NVARCHAR (修复中文乱码)")
    with engine.begin() as conn:
        for table_name, column_name, new_type in MIGRATIONS:
            # 检查当前列类型
            result = conn.execute(
                text(
                    "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table_name, "c": column_name},
            )
            current_type = result.scalar()
            print(f"[migrate] {table_name}.{column_name}: 当前类型={current_type}")

            # 如果已经是 NVARCHAR/NTEXT, 跳过
            if current_type and current_type.lower() in ("nvarchar", "ntext"):
                print(f"[migrate]   跳过: 已经是 Unicode 类型")
                continue

            # 修改列类型
            sql = f"ALTER TABLE [{table_name}] ALTER COLUMN [{column_name}] {new_type}"
            print(f"[migrate]   执行: {sql}")
            try:
                conn.execute(text(sql))
                print(f"[migrate]   成功")
            except Exception as e:
                print(f"[migrate]   失败: {e}")
                # 继续执行其他迁移

    print("[migrate] 迁移完成")


if __name__ == "__main__":
    migrate()
