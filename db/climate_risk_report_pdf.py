"""기후리스크 리포트 — 금감원 「기후리스크 관리 지침서」 4단계 구조 PDF
(v1 Tier 2, owner-admin-flow-spec.md §6, docs/tasks.md).

db/pcaf.py::portfolio_summary()가 이미 집계한 값을 4단계(거버넌스·전략·
리스크평가·공시) 틀로 재배열한다 — 새 계산·조회 로직 없음(감사 대응 근거
패키지 PDF와 같은 원칙: "이 모듈은 재계산하지 않는다").

검증 오차율(분류 정확도·트랙A MAPE·트랙B 실물대조 오차)과 시계열
금융배출량은 실제 데이터가 없다(전자는 회계 담당 미착수, 후자는 은행 내부
여신 시스템 연동이 필요해 business_loan_exposures가 0건) — 화면과 동일하게
"산정 예정"/"예시 데이터"로 명시하고 실측인 것처럼 꾸미지 않는다(CLAUDE.md
§6 실패 가시성 원칙과 같은 결).

한글 폰트 등록은 db/audit_report_pdf.py와 동일한 CID 폰트 패턴을 재사용한다.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
_FONT = "HYGothic-Medium"

# 시계열 금융배출량 — 대출잔액(business_loan_exposures) 연동 전까지 산식
# 검증용 예시값. 실제 데이터가 아님을 화면·PDF 양쪽에 동일하게 명시한다.
EXAMPLE_FINANCED_EMISSIONS_TIMELINE = [
    {"year": 2024, "grade_label": "5.0등급(추정)"},
    {"year": 2025, "grade_label": "3.2등급"},
    {"year": 2026, "grade_label": "2.4등급"},
]


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
        "warn": ParagraphStyle(
            "warn", parent=base["BodyText"], fontName=_FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#7a4fd9"),
        ),
        "cell": ParagraphStyle("cell", fontName=_FONT, fontSize=8.5, leading=11),
    }


def _table_style(*, header_rows: int = 1) -> TableStyle:
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


def build_climate_risk_report_pdf(portfolio: dict, institution_name: str) -> bytes:
    """portfolio_summary() 반환값 + 기관명을 받아 4단계 구조 PDF 바이트를 반환한다.

    portfolio의 어떤 값도 재계산하지 않는다 — 그대로 표에 옮겨 적는다.
    """
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    story = []

    story.append(Paragraph("기후리스크 관리 현황 보고서", styles["title"]))
    story.append(Spacer(1, 6 * mm))

    # ① 거버넌스 — 고정 텍스트 + 기관 정보(신규 계산 없음)
    story.append(Paragraph("① 거버넌스", styles["h2"]))
    story.append(Paragraph(
        f"{institution_name}은 이사회 산하 여신·ESG팀이 기후리스크 관리를 담당하며, "
        "포트폴리오 단위 PCAF 데이터 품질 현황을 정기 보고한다.",
        styles["body"],
    ))

    # ② 전략 — company_pcaf_summary / portfolio_summary Before-After
    story.append(Paragraph("② 전략", styles["h2"]))
    rows = [
        ["항목", "값"],
        ["거래 기업 수", f"{portfolio['company_count']}개사"],
        ["도입 전 기준선(추정)", "전 기업 5등급(매출·업종 통계 대입)"],
        ["도입 후(실측 반영)", f"배출가중 평균 {portfolio['avg_grade']}등급" if portfolio.get("avg_grade") else "산정 불가"],
    ]
    t = Table(rows, colWidths=[70 * mm, 90 * mm])
    t.setStyle(_table_style())
    story.append(t)

    # ③ 리스크평가 — portfolio_summary().grade_distribution
    story.append(Paragraph("③ 리스크평가 — 포트폴리오 등급 분포", styles["h2"]))
    grade_rows = [["PCAF 등급", "기업 수"]]
    for g in range(1, 6):
        grade_rows.append([f"{g}등급", f"{portfolio['grade_distribution'].get(g, 0)}개사"])
    t = Table(grade_rows, colWidths=[70 * mm, 90 * mm])
    t.setStyle(_table_style())
    story.append(t)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "※ 지역/업종 집중도 상세는 관리자 대시보드 '기업' 탭에서 조회할 수 있습니다.",
        styles["small"],
    ))

    # ④ 공시 — 데이터 품질 커버리지 + HITL 처리 현황 + 검증 오차율(산정 예정)
    story.append(Paragraph("④ 공시", styles["h2"]))
    disclosure_rows = [
        ["항목", "값"],
        ["실측 데이터 커버리지", f"{portfolio['measured_coverage_pct']}%"],
        ["담당자 검토 대기(HITL)", f"{portfolio['hitl_total']}건"],
        ["오늘 검토 완료", f"{portfolio['reviewed_today']}건"],
    ]
    t = Table(disclosure_rows, colWidths=[70 * mm, 90 * mm])
    t.setStyle(_table_style())
    story.append(t)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "검증 오차율(분류 정확도 · 트랙A MAPE · 트랙B 실물대조 오차) — 산정 예정. "
        "회계 담당의 검증 수치 확정 이후 이 섹션에 반영됩니다.",
        styles["warn"],
    ))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("시계열 금융배출량 (포트폴리오 전체 추이) — 예시 데이터", styles["h2"]))
    fin_rows = [["연도", "예시 등급"]]
    for row in EXAMPLE_FINANCED_EMISSIONS_TIMELINE:
        fin_rows.append([str(row["year"]), row["grade_label"]])
    t = Table(fin_rows, colWidths=[70 * mm, 90 * mm])
    t.setStyle(_table_style())
    story.append(t)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "※ 이 보고서는 은행 담당자의 내부 안내 자료이며 여신 결정을 의미하지 않습니다.",
        styles["small"],
    ))

    doc.build(story)
    return buffer.getvalue()
