"""报告服务 - PDF / Excel 生成

- generate_report_pdf: 生成项目阶段审核报告 (PDF, reportlab)
- generate_record_excel: 生成项目审核记录表 (Excel, openpyxl)

通过 ReviewRecord.PlanId 查询评审记录, 关联 CheckItem 生成报告。
返回字节数据, 由 API 层包装为 StreamingResponse。
"""
import io
from collections import OrderedDict
from datetime import datetime
from typing import List, Optional

from loguru import logger
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.models.check_item import CheckItem
from app.models.issue import Issue
from app.models.review import ReviewRecord

# 中文字体回退: reportlab 内置 Helvetica 不支持中文, 这里尝试注册系统字体
_CN_FONT = "Helvetica"
try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for _candidate in (
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",    # 黑体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
    ):
        import os

        if os.path.exists(_candidate):
            pdfmetrics.registerFont(TTFont("CN", _candidate))
            _CN_FONT = "CN"
            break
except Exception:
    # 字体注册失败时回退默认字体 (中文可能显示为方框, 但不影响骨架结构)
    pass


class ReportService:
    """报告生成服务"""

    def generate_report_pdf(
        self,
        db: Session,
        plan_id: str,
        phase_code: Optional[str] = None,
    ) -> bytes:
        """生成项目阶段审核报告 PDF

        Args:
            db: 数据库会话
            plan_id: MSIA 计划 ID (HRDB)
            phase_code: 阶段代码 (MSIA1..MSIA5), 为空则包含全部阶段
        Returns:
            PDF 文件字节
        """
        query = (
            db.query(ReviewRecord, CheckItem)
            .join(CheckItem, ReviewRecord.ItemId == CheckItem.Id)
            .filter(ReviewRecord.PlanId == str(plan_id))
        )
        if phase_code:
            query = query.filter(ReviewRecord.PhaseCode == phase_code)
        rows = query.order_by(ReviewRecord.PhaseCode, CheckItem.ItemNo).all()

        if not rows:
            raise ValueError(f"未找到评审数据: plan_id={plan_id}, phase_code={phase_code}")

        # 按 PhaseCode 分组
        grouped: "OrderedDict[str, list]" = OrderedDict()
        for review, item in rows:
            code = review.PhaseCode or "UNKNOWN"
            grouped.setdefault(code, []).append((review, item))

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=f"MSIA 审核报告 - Plan {plan_id}",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CnTitle", parent=styles["Title"], fontName=_CN_FONT, fontSize=18, alignment=1,
        )
        subtitle_style = ParagraphStyle(
            "CnSubtitle", parent=styles["Normal"], fontName=_CN_FONT, fontSize=10, alignment=1,
        )
        h2_style = ParagraphStyle(
            "CnH2", parent=styles["Heading2"], fontName=_CN_FONT, fontSize=13,
        )
        body_style = ParagraphStyle(
            "CnBody", parent=styles["Normal"], fontName=_CN_FONT, fontSize=9,
        )

        elements: list = []
        elements.append(Paragraph("MSIA 审核报告", title_style))
        elements.append(Paragraph(f"Plan ID: {plan_id}", subtitle_style))
        elements.append(
            Paragraph(
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                subtitle_style,
            )
        )
        elements.append(Spacer(1, 8 * mm))

        for code, items in grouped.items():
            elements.append(Paragraph(f"{code}", h2_style))
            header = ["检查项", "评分", "结果", "评审意见", "状态"]
            table_rows = [header]
            for review, item in items:
                table_rows.append([
                    Paragraph(item.Name or "", body_style),
                    f"{float(review.Score) * 100:.1f}%" if review.Score is not None else "",
                    Paragraph(review.ResultText or "", body_style),
                    Paragraph(review.Comments or "", body_style),
                    review.Status,
                ])
            tbl = Table(table_rows, colWidths=[70 * mm, 20 * mm, 50 * mm, 60 * mm, 25 * mm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, -1), _CN_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            elements.append(tbl)
            elements.append(Spacer(1, 6 * mm))

        doc.build(elements)
        logger.info("生成报告 PDF: plan_id {} 阶段 {}", plan_id, phase_code)
        return buffer.getvalue()

    def generate_record_excel(
        self,
        db: Session,
        plan_id: str,
    ) -> bytes:
        """生成项目审核记录 Excel

        Args:
            db: 数据库会话
            plan_id: MSIA 计划 ID (HRDB)
        Returns:
            Excel 文件字节
        """
        rows = (
            db.query(ReviewRecord, CheckItem)
            .join(CheckItem, ReviewRecord.ItemId == CheckItem.Id)
            .filter(ReviewRecord.PlanId == str(plan_id))
            .order_by(ReviewRecord.PhaseCode, CheckItem.ItemNo)
            .all()
        )

        if not rows:
            raise ValueError(f"未找到评审数据: plan_id={plan_id}")

        wb = Workbook()
        ws = wb.active
        ws.title = "审核记录"

        headers = [
            "MSIA 阶段", "检查项编号", "检查项", "要求", "评分", "结果", "评审意见", "状态",
        ]
        ws.append(headers)

        # 表头样式
        header_fill = PatternFill("solid", fgColor="4472C4")
        header_font = Font(color="FFFFFF", bold=True)
        thin = Side(border_style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border

        for review, item in rows:
            ws.append([
                review.PhaseCode or "",
                item.ItemNo or "",
                item.Name or "",
                item.Request or "",
                f"{float(review.Score) * 100:.1f}%" if review.Score is not None else "",
                review.ResultText or "",
                review.Comments or "",
                review.Status or "",
            ])

        # 列宽
        widths = [14, 14, 32, 40, 10, 30, 30, 14]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # 数据行边框
        max_row = ws.max_row
        max_col = ws.max_column
        for row in ws.iter_rows(min_row=2, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="center", wrap_text=True)

        # 冻结表头
        ws.freeze_panes = "A2"

        buffer = io.BytesIO()
        wb.save(buffer)
        logger.info("生成记录 Excel: plan_id {}", plan_id)
        return buffer.getvalue()

    def get_overdue_issues(self, db: Session) -> List[Issue]:
        """获取所有符合统一逾期规则的问题。

        这里必须使用 issue_overdue 服务，而不是裸 DueDate 判断，避免不同入口口径不一致。
        """
        from app.services.issue_overdue import build_overdue_filter, get_naive_utc_now

        now = get_naive_utc_now()
        return (
            db.query(Issue)
            .filter(
                Issue.IsDeleted == False,  # noqa: E712
                *build_overdue_filter(now, db),
            )
            .all()
        )
