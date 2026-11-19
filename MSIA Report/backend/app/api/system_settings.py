"""系统设置路由

提供管理员可配置的运行时设置 API:
- GET  /api/system-settings/notification-mode  查询当前通知模式
- PUT  /api/system-settings/notification-mode  更新通知模式 (test / production)
- GET  /api/system-settings                    查询全部系统设置 (平铺列表)
- GET  /api/system-settings/grouped            按功能模块分组查询
- PUT  /api/system-settings/batch              批量更新配置
- POST /api/system-settings/init               初始化默认配置 (首次启动调用)

权限: 仅 admin 可访问

设计说明:
- 设置持久化到 CN_AME_MISA_SystemSetting 表 (键值对, 按 Module 分组)
- 修改后立即生效 (业务代码每次调用时实时读取数据库)
- 数据库无记录时, 回退到 config.ini 中的默认值
- 配置项元数据 (默认值/类型/模块/描述) 定义在 system_config_service.py
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_role
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.system_config_service import SETTING_DEFINITIONS, init_default_settings

router = APIRouter(prefix="/api/system-settings", tags=["系统设置"])


# ============ 响应模型 ============

class NotificationModeOut(BaseModel):
    """通知模式响应"""
    mode: str = Field(..., description="通知模式: test=测试模式, production=生产模式")
    test_recipients: str = Field(..., description="测试模式下的邮件接收地址 (逗号分隔)")
    is_test_mode: bool = Field(..., description="是否为测试模式")
    description: str = Field("", description="当前模式说明")


class NotificationModeUpdate(BaseModel):
    """通知模式更新请求"""
    mode: str = Field(..., description="通知模式: test 或 production")
    test_recipients: Optional[str] = Field(
        None, description="测试模式下的邮件接收地址 (逗号分隔, 多个用英文逗号分隔)"
    )


class SystemSettingOut(BaseModel):
    """单个系统设置"""
    key: str
    value: Optional[str]
    display_name: Optional[str]
    description: Optional[str]
    module: Optional[str] = None
    value_type: Optional[str] = None
    sort_order: Optional[int] = None
    updated_at: Optional[str]
    updated_by: Optional[int]


class SettingGroupOut(BaseModel):
    """按功能模块分组的设置"""
    module: str
    module_name: str
    settings: List[SystemSettingOut]


class BatchUpdateItem(BaseModel):
    """批量更新单项"""
    key: str
    value: str


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""
    items: List[BatchUpdateItem]


class BatchUpdateResult(BaseModel):
    """批量更新结果"""
    updated: int
    skipped: int


# ============ 模块显示名称映射 ============
_MODULE_NAMES = {
    "notification": "通知模式",
    "smtp": "SMTP 邮件服务器",
    "issue_closure": "问题逾期判定",
    "maintenance_scan": "未维护问题扫描",
    "escalation": "问题升级扫描",
    "system": "系统全局配置",
}


# ============ 内部辅助 ============

def _get_setting(db: Session, key: str) -> Optional[SystemSetting]:
    return db.query(SystemSetting).filter(SystemSetting.SettingKey == key).first()


def _upsert_setting(
    db: Session,
    key: str,
    value: str,
    updated_by: Optional[int] = None,
) -> SystemSetting:
    """插入或更新设置 (upsert), 自动补充元数据"""
    row = _get_setting(db, key)
    meta = SETTING_DEFINITIONS.get(key, {})
    if row:
        row.SettingValue = value
        row.UpdatedBy = updated_by
        # 补充元数据 (兼容旧数据)
        if not row.Module and meta.get("module"):
            row.Module = meta["module"]
        if not row.ValueType:
            row.ValueType = meta.get("value_type", "string")
        if row.SortOrder is None:
            row.SortOrder = meta.get("sort_order", 0)
        if not row.DisplayName and meta.get("display_name"):
            row.DisplayName = meta["display_name"]
        if not row.Description and meta.get("description"):
            row.Description = meta["description"]
    else:
        row = SystemSetting(
            SettingKey=key,
            SettingValue=value,
            DisplayName=meta.get("display_name"),
            Description=meta.get("description"),
            Module=meta.get("module"),
            ValueType=meta.get("value_type", "string"),
            SortOrder=meta.get("sort_order", 0),
            UpdatedBy=updated_by,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _row_to_out(row: SystemSetting) -> SystemSettingOut:
    """ORM 行转响应模型"""
    return SystemSettingOut(
        key=row.SettingKey,
        value=row.SettingValue,
        display_name=row.DisplayName,
        description=row.Description,
        module=row.Module,
        value_type=row.ValueType,
        sort_order=row.SortOrder,
        updated_at=row.UpdatedAt.strftime("%Y-%m-%d %H:%M:%S") if row.UpdatedAt else None,
        updated_by=row.UpdatedBy,
    )


# ============ API ============

@router.get(
    "/notification-mode",
    response_model=NotificationModeOut,
    summary="查询当前通知模式",
)
def get_notification_mode(
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """查询当前通知模式

    优先级: 数据库 SystemSetting > config.ini 默认值
    """
    from app.services.system_config_service import get_string

    mode = (get_string(db, "notification_mode") or "production").strip().lower()
    test_recipients = get_string(db, "notification_test_recipients") or ""

    is_test = (mode == "test")
    description = (
        "测试模式: 所有通知邮件将发送到测试邮箱, 不会发送给真实责任人"
        if is_test
        else "生产模式: 通知邮件将发送给真实责任人/升级经理"
    )

    return NotificationModeOut(
        mode=mode,
        test_recipients=test_recipients,
        is_test_mode=is_test,
        description=description,
    )


@router.put(
    "/notification-mode",
    response_model=NotificationModeOut,
    summary="更新通知模式 (仅管理员)",
)
def update_notification_mode(
    payload: NotificationModeUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """更新通知模式

    - mode: test / production
    - test_recipients: 测试模式下的邮件接收地址 (可选, 仅在 mode=test 时使用)
    """
    mode = (payload.mode or "").strip().lower()
    if mode not in ("test", "production"):
        raise HTTPException(status_code=400, detail="mode 必须为 test 或 production")

    _upsert_setting(db, "notification_mode", mode, updated_by=current.Id)

    if payload.test_recipients is not None:
        _upsert_setting(
            db,
            "notification_test_recipients",
            payload.test_recipients.strip(),
            updated_by=current.Id,
        )

    if mode == "test":
        from app.services.system_config_service import get_string
        recipients_value = get_string(db, "notification_test_recipients") or ""
        if not recipients_value:
            logger.warning(
                "管理员 {} 切换到测试模式, 但未配置测试邮箱, 邮件将无法发送",
                current.Username,
            )

    logger.info(
        "管理员 {} 更新通知模式: mode={} (user_id={})",
        current.Username, mode, current.Id,
    )

    return get_notification_mode(db=db, current=current)


@router.get(
    "",
    response_model=List[SystemSettingOut],
    summary="查询全部系统设置 (仅管理员)",
)
def list_system_settings(
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """查询全部系统设置 (平铺列表)"""
    rows = (
        db.query(SystemSetting)
        .order_by(SystemSetting.Module.asc(), SystemSetting.SortOrder.asc(), SystemSetting.SettingKey.asc())
        .all()
    )
    return [_row_to_out(row) for row in rows]


@router.get(
    "/grouped",
    response_model=List[SettingGroupOut],
    summary="按功能模块分组查询系统设置 (仅管理员)",
)
def list_settings_grouped(
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """按功能模块分组查询系统设置

    返回结构: [{module, module_name, settings: [...]}]
    每个模块内的设置按 SortOrder 排序。
    """
    rows = (
        db.query(SystemSetting)
        .order_by(SystemSetting.Module.asc(), SystemSetting.SortOrder.asc(), SystemSetting.SettingKey.asc())
        .all()
    )

    # 按 Module 分组
    groups: dict[str, list[SystemSetting]] = {}
    for row in rows:
        module = row.Module or "other"
        groups.setdefault(module, []).append(row)

    result: list[SettingGroupOut] = []
    for module, settings in groups.items():
        result.append(SettingGroupOut(
            module=module,
            module_name=_MODULE_NAMES.get(module, module),
            settings=[_row_to_out(r) for r in settings],
        ))

    return result


@router.put(
    "/batch",
    response_model=BatchUpdateResult,
    summary="批量更新系统设置 (仅管理员)",
)
def batch_update_settings(
    payload: BatchUpdateRequest,
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """批量更新系统设置

    - 仅允许更新 SETTING_DEFINITIONS 中已定义的配置项 (白名单)
    - 修改后立即生效, 业务代码下次读取时自动应用新值
    """
    updated = 0
    skipped = 0

    for item in payload.items:
        # 白名单校验: 只允许更新已定义的配置项
        if item.key not in SETTING_DEFINITIONS:
            skipped += 1
            logger.warning("[系统配置] 跳过未定义的配置项: {}", item.key)
            continue

        _upsert_setting(db, item.key, item.value, updated_by=current.Id)
        updated += 1
        logger.info(
            "管理员 {} 更新配置: {} = {} (user_id={})",
            current.Username, item.key, item.value, current.Id,
        )

    return BatchUpdateResult(updated=updated, skipped=skipped)


@router.post(
    "/init",
    summary="初始化默认配置 (仅管理员)",
)
def init_settings(
    db: Session = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    """初始化默认配置

    将 SETTING_DEFINITIONS 中定义的所有配置项写入数据库 (已存在的跳过或补充元数据)。
    通常在系统首次部署或升级后手动调用一次。
    """
    count = init_default_settings(db)
    return {"message": f"初始化完成, 新增 {count} 项配置", "inserted": count}
