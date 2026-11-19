"""检查项路由 (MSIA 评审检查项定义)

接口前缀: /api/check-items
支持完整 CRUD: 列表(按阶段过滤) / 详情 / 新建 / 更新 / 删除(软删)
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_role
from app.models.check_item import CheckItem
from app.models.phase_review_item import PhaseReviewItem
from app.models.user import User

router = APIRouter(prefix="/api/check-items", tags=["检查项"])


# ============ Pydantic 模型 ============

class ScoreOptionIn(BaseModel):
    score: float
    label: str = ""
    desc: str = ""


class CheckItemCreate(BaseModel):
    PhaseCode: str = Field(..., max_length=20, description="阶段代码, 如 MSIA1")
    ItemNo: str = Field(..., max_length=50, description="条目编号")
    Name: str = Field(..., max_length=500, description="检查项名称")
    Request: str | None = Field(None, max_length=2000, description="评审要求")
    RequestDescription: str | None = None
    IsKeyItem: bool = False
    ReviewerRoles: str | None = Field(None, max_length=500, description="逗号分隔的角色串")
    ReferenceDocuments: str | None = None
    ScoreScaleType: str = Field("7-step", max_length=20)
    ScoreOptions: list[ScoreOptionIn] | None = None
    DefaultResultText: str | None = Field(None, max_length=1000)
    Remarks: str | None = None


class CheckItemUpdate(BaseModel):
    PhaseCode: str | None = Field(None, max_length=20)
    ItemNo: str | None = Field(None, max_length=50)
    Name: str | None = Field(None, max_length=500)
    Request: str | None = Field(None, max_length=2000)
    RequestDescription: str | None = None
    IsKeyItem: bool | None = None
    ReviewerRoles: str | None = Field(None, max_length=500)
    ReferenceDocuments: str | None = None
    ScoreScaleType: str | None = Field(None, max_length=20)
    ScoreOptions: list[ScoreOptionIn] | None = None
    DefaultResultText: str | None = Field(None, max_length=1000)
    Remarks: str | None = None
    # 启用/停用开关 (True=启用, False=停用, 停用后不进入项目评审打分场景)
    IsActive: bool | None = None


def _score_options_to_json(opts: list[ScoreOptionIn] | None) -> str | None:
    """将 ScoreOption 列表序列化为 JSON 字符串"""
    if opts is None:
        return None
    return json.dumps(
        [{"score": o.score, "label": o.label, "desc": o.desc} for o in opts],
        ensure_ascii=False,
    )


# ============ 与阶段评审清单 (PhaseReviewItem) 联动 ============

def _sync_phase_review_item(db: Session, check_item: CheckItem, deleted: bool = False) -> None:
    """审核标准条款联动同步到阶段评审清单

    - 新增/更新 CheckItem 时: 若无对应 PhaseReviewItem 则创建, 有则同步名称/要求/阶段
    - 删除 CheckItem (软删) 时: 对应 PhaseReviewItem 一并软删 (历史评审记录保留)
    """
    pri = db.query(PhaseReviewItem).filter(
        PhaseReviewItem.CheckItemId == check_item.Id,
        PhaseReviewItem.IsDeleted == False,  # noqa: E712
    ).first()

    if deleted:
        if pri:
            pri.IsDeleted = True
        return

    request_val = (check_item.Request or "")[:200] or None
    if pri is None:
        max_seq = (
            db.query(func.max(PhaseReviewItem.Seq))
            .filter(PhaseReviewItem.PhaseCode == check_item.PhaseCode)
            .scalar()
        ) or 0
        max_sort = (
            db.query(func.max(PhaseReviewItem.SortOrder))
            .filter(PhaseReviewItem.PhaseCode == check_item.PhaseCode)
            .scalar()
        ) or 0
        pri = PhaseReviewItem(
            PhaseCode=check_item.PhaseCode,
            CheckItemId=check_item.Id,
            Seq=max_seq + 1,
            SortOrder=max_sort + 1,
            ItemName=check_item.Name,
            Request=request_val,
        )
        db.add(pri)
    else:
        pri.PhaseCode = check_item.PhaseCode
        pri.ItemName = check_item.Name
        pri.Request = request_val


def _natural_itemno_key(item_no: str | None) -> list[tuple[int, int, str]]:
    """ItemNo 自然排序键: 数字段按数值比较, 非数字段按字符比较

    保证 1.1 < 1.2 < ... < 1.9 < 1.10 < 1.11 < 2.1 (普通字符串排序会有 1.10 < 1.2 的问题)
    无数字前缀的条目 (如 MSIA-0120) 排在同阶段数字编号条目之后
    """
    parts = re.split(r"(\d+)", item_no or "")
    key: list[tuple[int, int, str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part), ""))
        else:
            key.append((1, 0, part))
    return key


# ============ 路由 ============

@router.get("", summary="检查项列表 (可按 PhaseCode 过滤)")
def list_check_items(
    phase_code: str | None = Query(None, alias="phase_code", description="按阶段代码过滤, 如 MSIA1"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    query = db.query(CheckItem).filter(CheckItem.IsDeleted == False)  # noqa: E712
    if phase_code:
        query = query.filter(CheckItem.PhaseCode == phase_code)
    items = query.all()
    # 先按阶段, 阶段内按 ItemNo 自然升序 (1.1, 1.2, ..., 1.10, 2.1, ...)
    items.sort(key=lambda ci: (ci.PhaseCode, _natural_itemno_key(ci.ItemNo)))
    return items


@router.get("/{item_id}", summary="检查项详情")
def get_check_item(item_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    item = db.query(CheckItem).filter(CheckItem.Id == item_id, CheckItem.IsDeleted == False).first()  # noqa: E712
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    return item


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="新建检查项",
    dependencies=[Depends(require_role("admin"))],
)
def create_check_item(payload: CheckItemCreate, db: Session = Depends(get_db)):
    """新建检查项"""
    data = payload.model_dump(exclude_none=True)
    # ScoreOptions: list → JSON 字符串
    if "ScoreOptions" in data:
        data["ScoreOptions"] = _score_options_to_json(payload.ScoreOptions)
    item = CheckItem(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    # 联动: 同步创建阶段评审清单条目
    _sync_phase_review_item(db, item)
    db.commit()
    return item


@router.put(
    "/{item_id}",
    summary="更新检查项",
    dependencies=[Depends(require_role("admin"))],
)
def update_check_item(item_id: int, payload: CheckItemUpdate, db: Session = Depends(get_db)):
    item = db.query(CheckItem).filter(CheckItem.Id == item_id, CheckItem.IsDeleted == False).first()  # noqa: E712
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    data = payload.model_dump(exclude_unset=True)
    # ScoreOptions: list → JSON 字符串
    if "ScoreOptions" in data:
        data["ScoreOptions"] = _score_options_to_json(payload.ScoreOptions)
    for k, v in data.items():
        if hasattr(item, k):
            setattr(item, k, v)
    # 联动: 同步更新阶段评审清单条目
    _sync_phase_review_item(db, item)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/{item_id}",
    summary="删除检查项 (软删)",
    dependencies=[Depends(require_role("admin"))],
)
def delete_check_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(CheckItem).filter(CheckItem.Id == item_id, CheckItem.IsDeleted == False).first()  # noqa: E712
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    item.IsDeleted = True
    # 联动: 同步软删阶段评审清单条目 (历史评审记录保留)
    _sync_phase_review_item(db, item, deleted=True)
    db.commit()
    return {"message": "检查项已删除"}


class CheckItemToggleActive(BaseModel):
    """审核条款启用/停用开关 payload"""
    IsActive: bool = Field(..., description="True=启用, False=停用 (停用后不进入项目评审打分场景)")


@router.patch(
    "/{item_id}/active",
    summary="启用/停用检查项 (停用后不进入项目评审打分场景)",
    dependencies=[Depends(require_role("admin"))],
)
def toggle_check_item_active(item_id: int, payload: CheckItemToggleActive, db: Session = Depends(get_db)):
    """切换审核条款启用/停用状态:
    - 启用 (IsActive=True): 该条款在项目评审打分场景中显示
    - 停用 (IsActive=False): 该条款在项目评审打分场景中隐藏, 不进行评审
    历史评审记录与已存在问题保留, 仅影响后续打分场景的条款列表
    """
    item = db.query(CheckItem).filter(CheckItem.Id == item_id, CheckItem.IsDeleted == False).first()  # noqa: E712
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    item.IsActive = payload.IsActive
    db.commit()
    db.refresh(item)
    return item
