"""MSIA 审核管理系统 - 启动入口

用途:
- 开发环境: python run.py
- PyInstaller 打包后: msia_server.exe

功能:
1. 添加项目路径到 sys.path (确保 app 包可导入)
2. 创建 storage 目录 (如不存在)
3. 启动 uvicorn 服务 (从 config.ini / .env 读取 host 和 port)
"""
import os
import sys
from pathlib import Path


def _setup_encoding():
    """修复 Windows 控制台编码, 确保中文正常输出"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _setup_paths():
    """设置 Python 模块搜索路径"""
    if getattr(sys, "frozen", False):
        # PyInstaller 冻结环境: _MEIPASS 已在 sys.path 中
        base_dir = Path(sys.executable).parent
    else:
        # 开发环境: backend 目录
        base_dir = Path(__file__).resolve().parent

    # 确保 storage 目录存在
    storage_path = base_dir / "storage"
    storage_path.mkdir(exist_ok=True)

    # 确保工作目录正确
    os.chdir(str(base_dir))


def main():
    """启动 MSIA 审核管理系统"""
    _setup_encoding()
    _setup_paths()

    # 延迟导入, 确保 sys.path 已设置
    from app.core.config import settings

    host = settings.APP_HOST
    port = settings.APP_PORT

    print("=" * 60)
    print("  MSIA Audit Management System")
    print("=" * 60)
    print(f"  Listen:  http://{host}:{port}")
    db_info = settings.DATABASE_URL.split("@")[-1].split("/")[0] if "@" in settings.DATABASE_URL else "(not configured)"
    print(f"  DB:      {db_info}")
    print(f"  Storage: {settings.STORAGE_PATH}")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    # 启动 uvicorn
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=1,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
