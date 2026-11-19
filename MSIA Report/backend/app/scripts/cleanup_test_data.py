"""清理测试数据 - 正式部署前使用

保留:
- CN_AME_MISA_CheckItem          审核标准条款 (7档评分标准库)
- CN_AME_MSIA_PhaseReviewItem    阶段评审清单 (Report MSIA1~5 模板)
- CN_AME_MISA_User               用户 (HR 同步)
- CN_AME_MISA_SystemSetting      系统配置
- CN_AME_MISA_EscalationConfig   升级配置

清空 (测试业务数据):
- 评审分值/记录: ReviewRecord, HistoricScore, PhaseReviewMeta
- 问题记录:      Issue, IssueComment
- 上传附件:      Attachment (+ storage 目录文件)
- 其他:          RecordEntry, Notification, EmailLog, EscalationLog,
                 Phase, Project, UserSyncLog

用法 (在 backend 目录下):
    python -m app.scripts.cleanup_test_data            # 预览 (dry-run, 只统计)
    python -m app.scripts.cleanup_test_data --execute  # 实际执行清空
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine

# 清空顺序: 先子表后父表 (避免外键冲突)
TABLES_TO_CLEAN = [
    "CN_AME_MISA_IssueComment",
    "CN_AME_MISA_ReviewRecord",
    "CN_AME_MISA_Issue",
    "CN_AME_MISA_Attachment",
    "CN_AME_MISA_RecordEntry",
    "CN_AME_MISA_Notification",
    "CN_AME_MISA_EmailLog",
    "CN_AME_MISA_EscalationLog",
    "CN_AME_MISA_HistoricScore",
    "CN_AME_MISA_PhaseReviewMeta",
    "CN_AME_MISA_Phase",
    "CN_AME_MISA_Project",
    "CN_AME_MISA_UserSyncLog",
]

# 保留表 (仅统计展示, 不删除)
TABLES_TO_KEEP = [
    "CN_AME_MISA_CheckItem",
    "CN_AME_MSIA_PhaseReviewItem",
    "CN_AME_MISA_User",
    "CN_AME_MISA_SystemSetting",
    "CN_AME_MISA_EscalationConfig",
]


def count_rows(conn, table: str) -> int:
    """统计单表行数; 表不存在返回 -1"""
    try:
        return conn.execute(text(f"SELECT COUNT(*) FROM [{table}]")).scalar_one()
    except Exception:
        return -1


def reseed_identity(conn, table: str) -> bool:
    """重置自增列为 0 (新数据从 1 开始); 无权限时返回 False"""
    try:
        conn.execute(text(f"DBCC CHECKIDENT ('{table}', RESEED, 0)"))
        return True
    except Exception:
        return False


def clear_storage_files() -> int:
    """删除 storage 目录下的上传文件 (保留目录本身); 返回删除文件数"""
    storage = Path(__file__).resolve().parents[2] / "storage"
    if not storage.is_dir():
        return 0
    removed = 0
    for f in storage.rglob("*"):
        if f.is_file():
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    # 清理空子目录
    for d in sorted(storage.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


def main():
    parser = argparse.ArgumentParser(description="MSIA 测试数据清理")
    parser.add_argument("--execute", action="store_true", help="实际执行清空 (默认只预览)")
    args = parser.parse_args()

    with engine.begin() as conn:
        print("=" * 62)
        print("  MSIA 测试数据清理" + ("  [EXECUTE]" if args.execute else "  [DRY-RUN 预览]"))
        print("=" * 62)

        print("\n[保留] 审核标准条款 / 用户 / 配置:")
        for t in TABLES_TO_KEEP:
            n = count_rows(conn, t)
            print(f"  {t:<36} {n:>6} 行")

        print("\n[清空] 测试业务数据:")
        for t in TABLES_TO_CLEAN:
            n = count_rows(conn, t)
            print(f"  {t:<36} {n:>6} 行")

        if not args.execute:
            print("\n预览完成。确认无误后执行:")
            print("  python -m app.scripts.cleanup_test_data --execute")
            return

        print("\n开始清空...")
        total_deleted = 0
        for t in TABLES_TO_CLEAN:
            n = count_rows(conn, t)
            if n <= 0:
                print(f"  [SKIP] {t} (空)")
                continue
            conn.execute(text(f"DELETE FROM [{t}]"))
            total_deleted += n
            print(f"  [OK]   {t:<36} 已删除 {n} 行")

        print("\n重置自增列 (新数据 ID 从 1 开始):")
        for t in TABLES_TO_CLEAN:
            ok = reseed_identity(conn, t)
            print(f"  [{'OK' if ok else 'SKIP'}] {t}")

    removed = clear_storage_files()
    print(f"\n[OK] storage 上传文件已删除 {removed} 个")

    print("=" * 62)
    print(f"清理完成, 共删除 {total_deleted} 行测试数据。")
    print("=" * 62)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    main()
