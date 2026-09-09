"""감사 대응 근거 패키지 — 서술형 PDF 감사보고서 (v1 Tier 2, owner-admin-flow-spec.md §8).

db/audit_package.py::build_audit_package()가 이미 만드는 시계열 데이터(entries)를
그대로 문서로 직렬화한다 — 새 계산·조회 로직 없음. CSV(원자료 재검증용)와 달리 PDF는
"이 기업의 배출량 판정 근거를 사람이 읽고 감사에 대응할 수 있는 형태"로 요약·정리한다.

한글 폰트 등록은 scripts/generate_upload_docs.py와 동일한 CID 폰트 패턴을 재사용한다
(별도 폰트 파일 배포 불필요, reportlab 내장 CID 폰트).
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
_FONT = "HYGothic-Medium"
_FONT_SERIF = "HYSMyeongJo-Medium"

_ENTRY_TYPE_LABEL = {"voucher": "전표", "trace": "에이전트 실행 이력"}
_STEP_TYPE_LABEL = {"계획": "계획", "관찰": "관찰", "행동": "행동"}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName=_FONT, fontSize=18, leading=22,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=_FONT, fontSize=13, leading=17,
            spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName=_FONT, fontSize=9.5, leading=13,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName=_FONT, fontSize=8, leading=11,
            textColor=colors.HexColor("#666666"),
        ),
        "cell": ParagraphStyle(
            "cell", fontName=_FONT, fontSize=8, leading=10,
        ),
        "cell_header": ParagraphStyle(
            "cell_header", fontName=_FONT, fontSize=8.5, leading=11,
            textColor=colors.white,
        ),
    }


def _summary_stats(entries: list[dict]) -> dict:
    """entries에서 재계산이 아니라 단순 카운트/합산만 한다 — 배출량 자체는
    db/pcaf_quality.py가 이미 계산해 저장한 값(voucher entry의 emission_co2e)을
    그대로 더할 뿐, 이 모듈에서 새로 계산하지 않는다(LLM 산수 금지 원칙과 같은 결
    — 이 모듈도 이미 계산된 값을 조립만 한다)."""
    vouchers = [e for e in entries if e["entry_type"] == "voucher"]
    traces = [e for e in entries if e["entry_type"] == "trace"]
    total_emission_kg = sum(v["emission_co2e"] for v in vouchers if v.get("emission_co2e") is not None)
    review_required = sum(1 for v in vouchers if v.get("status") == "review_required")
    return {
        "voucher_count": len(vouchers),
        "trace_count": len(traces),
        "total_emission_tco2e": round(total_emission_kg / 1000.0, 3),
        "review_required_count": review_required,
    }


def build_audit_report_pdf(package: dict, company_name: str) -> bytes:
    """db/audit_package.py::build_audit_package()의 반환값(package) + 기업명을 받아
    서술형 PDF 바이트를 반환한다. 이 함수는 package를 재해석하지 않는다 — 어떤 값도
    다시 계산하지 않고 그대로 표에 옮겨 적는다(원자료와 PDF 내용이 항상 일치해야
    감사 대응 문서로서 의미가 있다).
    """
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    story = []

    story.append(Paragraph("감탄 탄소배출량 감사 대응 근거 보고서", styles["title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"기업: {company_name} (company_id={package['company_id']}) &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"보고연도: {package['year']}년 {package['month_from']}~{package['month_to']}월 "
        f"&nbsp;&nbsp;|&nbsp;&nbsp; 생성일시: {package['generated_at']}",
        styles["small"],
    ))
    story.append(Spacer(1, 6 * mm))

    stats = _summary_stats(package["entries"])
    story.append(Paragraph("요약", styles["h2"]))
    summary_rows = [
        ["항목", "값"],
        ["전표 건수", f"{stats['voucher_count']}건"],
        ["담당자 검토 대기 건수", f"{stats['review_required_count']}건"],
        ["에이전트 실행 이력 건수", f"{stats['trace_count']}건"],
        ["집계 배출량(전표 합산, 미산정 제외)", f"{stats['total_emission_tco2e']} tCO2e"],
    ]
    summary_table = Table(summary_rows, colWidths=[70 * mm, 90 * mm])
    summary_table.setStyle(_table_style(header_rows=1))
    story.append(summary_table)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "※ 이 보고서는 은행 담당자의 안내 자료이며 여신 결정을 의미하지 않습니다. "
        "PCAF 등급·우대금리 자격은 별도 승인 절차를 거칩니다.",
        styles["small"],
    ))

    story.append(PageBreak())
    story.append(Paragraph("판단 근거 시계열", styles["h2"]))
    story.append(Paragraph(
        "전표별 분류 판단 근거(evidence)와 에이전트 실행 이력(계획·관찰·행동)을 "
        "시각순으로 나열합니다. 원자료 재검증용 CSV는 관리자 대시보드에서 별도로 "
        "내려받을 수 있습니다.",
        styles["body"],
    ))
    story.append(Spacer(1, 3 * mm))

    if not package["entries"]:
        story.append(Paragraph("해당 기간에 표시할 근거가 없습니다.", styles["body"]))
    else:
        rows = [["구분", "시각/월", "내용", "근거"]]
        for e in package["entries"]:
            rows.append(_entry_row(e, styles))
        table = Table(rows, colWidths=[20 * mm, 22 * mm, 70 * mm, 48 * mm], repeatRows=1)
        table.setStyle(_table_style(header_rows=1))
        story.append(table)

    doc.build(story)
    return buffer.getvalue()


def _entry_row(entry: dict, styles: dict) -> list:
    kind = _ENTRY_TYPE_LABEL.get(entry["entry_type"], entry["entry_type"])
    if entry["entry_type"] == "voucher":
        when = f"{entry['month']}월"
        content = (
            f"{entry['item_description'] or ''} "
            f"({entry['supply_amount_krw']:,.0f}원)" if entry.get("supply_amount_krw") is not None
            else entry.get("item_description") or ""
        )
        basis = entry.get("evidence") or "—"
    else:
        when = (entry.get("occurred_at") or "")[:16].replace("T", " ")
        step = _STEP_TYPE_LABEL.get(entry.get("step_type"), entry.get("step_type") or "")
        content = f"[{step}] {entry.get('tool_name') or ''}"
        basis = entry.get("message") or "—"
    return [
        Paragraph(kind, styles["cell"]),
        Paragraph(when, styles["cell"]),
        Paragraph(content, styles["cell"]),
        Paragraph(basis, styles["cell"]),
    ]


def _table_style(*, header_rows: int) -> TableStyle:
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#2f6f4f")),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
