"""FastAPI 应用入口

职责:
- 创建 FastAPI 实例 (标题 / 版本)
- 注册 CORS 中间件
- 挂载聚合路由
- 启动时: 建表 (可选) + 启动 APScheduler
- 关闭时: 停止 APScheduler
- 若存在前端 dist 目录, 则挂载静态文件到 "/"
"""
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.router import api_router
from app.core.config import settings
from app.scheduler.scheduler import shutdown_scheduler, start_scheduler


def _get_base_dir() -> str:
    """获取程序基础目录

    - PyInstaller 冻结环境: 可执行程序所在目录
    - 开发环境: backend 目录
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动与关闭钩子"""
    logger.info("MSIA 审核管理系统启动中...")
    # 启动调度器
    try:
        start_scheduler()
    except Exception:
        logger.exception("调度器启动失败")

    # 可选: 开发环境自动建表 (生产建议关闭, 改用迁移)
    if os.environ.get("MSIA_AUTO_CREATE_TABLES", "0") == "1":
        try:
            from app.db.session import create_tables

            create_tables()
            logger.info("数据库表已创建 (auto)")
        except Exception:
            logger.exception("自动建表失败")

    # 初始化系统默认配置 (SystemSetting 表, 首次启动或新增配置项时自动补充)
    try:
        from app.db.session import SessionLocal
        from app.services.system_config_service import init_default_settings

        with SessionLocal() as db:
            inserted = init_default_settings(db)
            if inserted > 0:
                logger.info("[启动] 系统默认配置初始化完成, 新增 {} 项", inserted)
    except Exception:
        logger.exception("[启动] 系统默认配置初始化失败")

    # 启动时检查用户表是否为空, 若空则触发一次 HR 用户同步
    try:
        from app.db.session import SessionLocal
        from app.models.user import User
        from app.services.user_sync import UserSyncService

        db = SessionLocal()
        try:
            user_count = db.query(User).filter(User.IsDeleted == False).count()  # noqa: E712
            if user_count == 0:
                logger.info("用户表为空, 启动初始 HR 用户同步...")
                sync_service = UserSyncService(settings)
                result = sync_service.sync_from_hr(db)
                logger.info(
                    "初始用户同步完成: 读取 {} 新增 {} 更新 {} 失败 {}",
                    result.total_read, result.total_inserted,
                    result.total_updated, result.total_failed,
                )
            else:
                logger.info("用户表已有 {} 个用户, 跳过初始同步", user_count)
        finally:
            db.close()
    except Exception:
        logger.exception("启动用户同步失败")

    logger.info("应用就绪, 监听 {}:{}", settings.APP_HOST, settings.APP_PORT)
    yield
    logger.info("应用关闭中...")
    shutdown_scheduler()
    logger.info("应用已关闭")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(
        title="MSIA 审核管理系统",
        description="Inalfa MSIA 审核管理后端 API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由
    app.include_router(api_router)

    # 前端资源缓存策略:
    # - /assets/ 下的 js/css 带 content-hash, 可长期强缓存
    # - index.html 及其他 public 文件必须每次回源校验 (no-cache),
    #   否则发版后浏览器继续用旧 index.html → 加载旧 JS → 新修复不生效
    @app.middleware("http")
    async def cache_control_middleware(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        elif not path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # 健康检查
    @app.get("/api/health", tags=["系统"], summary="健康检查")
    def health():
        return {"status": "ok", "service": "MSIA 审核管理系统", "version": "1.0.0"}

    # 挂载前端静态文件
    # 查找顺序:
    #   1. PyInstaller _MEIPASS 内嵌的 dist (打包后)
    #   2. 可执行程序同目录的 dist (部署后)
    #   3. 当前工作目录的 static / dist (开发环境)
    base_dir = _get_base_dir()
    candidate_dirs = []

    # PyInstaller 冻结环境: 内嵌资源目录
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate_dirs.append(os.path.join(sys._MEIPASS, "dist"))
        candidate_dirs.append(os.path.join(sys._MEIPASS, "static"))

    # 可执行程序同目录
    candidate_dirs.append(os.path.join(base_dir, "dist"))
    candidate_dirs.append(os.path.join(base_dir, "static"))

    # 当前工作目录 (开发环境)
    candidate_dirs.append(os.path.join(os.getcwd(), "dist"))
    candidate_dirs.append(os.path.join(os.getcwd(), "static"))

    target_dir = None
    for d in candidate_dirs:
        if os.path.isdir(d):
            target_dir = d
            break

    if target_dir:
        index_html = os.path.join(target_dir, "index.html")

        # 挂载前端静态资源目录 (js/css/图片等)
        # 单独挂载 /assets 而非整个 /, 避免与 catch-all 路由冲突
        assets_dir = os.path.join(target_dir, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # SPA catch-all: 所有非 API 请求都返回 index.html, 由前端路由接管
        # 这样 /login, /projects, /dashboard 等前端路由不会返回 404
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str, request: Request):
            # 排除 API 请求 (已在 api_router 中定义, 不会走到这里)
            if full_path.startswith("api/"):
                return JSONResponse(
                    {"detail": "Not Found"},
                    status_code=404,
                )

            # 尝试返回对应的静态文件 (如 favicon.ico, logo.png 等)
            file_path = os.path.join(target_dir, full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)

            # 其他路径返回 index.html, 交给前端 React Router 处理
            if os.path.isfile(index_html):
                return FileResponse(index_html)

            return JSONResponse(
                {"detail": "Frontend not built. index.html not found."},
                status_code=404,
            )

        logger.info("已挂载前端静态文件: {}", target_dir)

    return app


app = create_app()
