"""报告 / 记录导出路由

项目记录 Excel 导出仍由本模块提供。
阶段审核报告已统一到 phase_reports.py 的模板格式接口; 旧阶段报告路径保留用于
兼容已部署客户端, 但明确返回 410, 避免产生与新版不同的报告结果。

- GET  /api/projects/{plan_id}/record                  获取项目记录条目 (JSON)
- GET  /api/projects/{plan_id}/report/{phase_code}     获取阶段报告数据 (JSON)
- GET  /api/projects/{plan_id}/export/report/{phase_code}?format=pdf
- GET  /api/projects/{plan_id}/export/record?format=excel
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.check_item import CheckItem
from app.models.review import ReviewRecord
from app.models.user import User
from app.services.report_service import ReportService

router = APIRouter(prefix="/api", tags=["报告与导出"])

_report_service = ReportService()


def _build_record_rows(db: Session, plan_id: str, phase_code: str | None = None):
    """查询评审记录 + 检查项, 返回 [(review, item), ...] 列表"""
    query = (
        db.query(ReviewRecord, CheckItem)
        .join(CheckItem, ReviewRecord.ItemId == CheckItem.Id)
        .filter(ReviewRecord.PlanId == str(plan_id))
    )
    if phase_code:
        query = query.filter(ReviewRecord.PhaseCode == phase_code)
    return query.order_by(ReviewRecord.PhaseCode, CheckItem.ItemNo).all()


@router.get("/projects/{plan_id}/record", summary="获取项目记录条目")
def get_record_entries(
    plan_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    rows = _build_record_rows(db, plan_id)
    records = [
        {
            "MsiaCode": review.PhaseCode,
            "ItemNo": item.ItemNo,
            "ItemName": item.Name,
            "Request": item.Request,
            "Result": review.ResultText,
            "Score": float(review.Score) if review.Score is not None else None,
            "Comments": review.Comments,
            "Status": review.Status,
        }
        for review, item in rows
    ]
    return {"project": plan_id, "records": records}


@router.get("/projects/{plan_id}/report/{phase_code}", summary="获取阶段报告数据", deprecated=True)
def get_phase_report(
    plan_id: str,
    phase_code: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=410,
        detail="旧阶段报告接口已废弃, 请使用 /api/projects/{plan_id}/phase-report/{phase_code}",
    )


@router.get("/projects/{plan_id}/export/report/{phase_code}", summary="导出阶段报告 (PDF)", deprecated=True)
def export_report_pdf(
    plan_id: str,
    phase_code: str,
    format: str = Query("pdf"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=410,
        detail="旧阶段报告下载接口已废弃, 请使用 /api/projects/{plan_id}/phase-report/{phase_code}/export",
    )


@router.get("/projects/{plan_id}/export/record", summary="导出项目记录 (Excel)")
def export_record_excel(
    plan_id: str,
    format: str = Query("excel"),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if format.lower() != "excel":
        raise HTTPException(status_code=400, detail="记录导出仅支持 excel 格式")
    try:
        excel_bytes = _report_service.generate_record_excel(db, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    filename = f"record_{plan_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
