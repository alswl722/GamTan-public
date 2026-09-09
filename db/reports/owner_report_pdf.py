"""사장님 탄소배출량 산정 결과서 PDF — 원청사 제출·공시용 (v1).

기획 방향(2026-08-14 논의): 지속가능경영보고서(E·S·G 전분야) 형식은 쓰지 않는다 —
이 프로젝트가 실제로 산정하는 건 Scope 1·2뿐이라(사회·지배구조 데이터 없음), 그
형식을 흉내내면 없는 근거를 있는 것처럼 보이게 만든다(CLAUDE.md 원칙10 — 과잉주장
금지). 대신 PCAF 방법론 문서·은행 확인서에 가까운 짧고 검증 가능한 "산정 결과서"로
간다 — 헤더, 요약, Scope별 세부, 산정 방법론 4개 섹션만 담는다(한계·Before/After
비교는 이번 버전에서 제외, 필요해지면 리포트 화면 쪽에 별도로 얹는다).

db/audit_report_pdf.py와 같은 구조·한글 폰트 패턴을 그대로 따른다 — 이 함수는 이미
계산된 값(quality-report API가 만든 값)을 받아 직렬화만 한다, 재계산하지 않는다
(LLM 산수 금지 원칙과 같은 결).

글자 깨짐 주의(2026-08-14 발견): reportlab 내장 CID 한글 폰트(HYGothic-Medium)는
가운데점(·)·파이프(|)·em dash(—) 같은 기호 글리프를 지원하지 않아 다른 글자로
깨져 보인다 — 이 파일 전체에서 구분자는 줄바꿈·콜론(:)·괄호·하이픈(-)만 쓴다
(전부 확인된 안전 글리프). 새 문구를 추가할 때도 이 규칙을 지킬 것.
"""
import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
_FONT = "HYGothic-Medium"

# web/app/globals.css의 --color-brand* 와 동일한 값(iM Mint) — 화면 UI와 같은 색으로
# 표 제목행·강조 텍스트를 칠한다.
_BRAND = colors.HexColor("#00c7a9")
_BRAND_INK = colors.HexColor("#00967f")
_BRAND_SOFT = colors.HexColor("#e3faf5")

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "im-symbol.png"
_LOGO_ASPECT = 96 / 183  # im-symbol.png 원본 183x96

_SCOPE_LABEL = {"scope_1": "Scope 1 (직접배출)", "scope_2": "Scope 2 (전력 간접배출)"}
_BASIS_LABEL = {"energy_consumption": "실측 수량 기반", "revenue": "매출액 환산 추정"}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName=_FONT, fontSize=17, leading=21,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=_FONT, fontSize=12.5, leading=16,
            spaceBefore=12, spaceAfter=6, textColor=_BRAND_INK,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName=_FONT, fontSize=9.5, leading=13,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName=_FONT, fontSize=8, leading=11,
            textColor=colors.HexColor("#666666"),
        ),
        "cell": ParagraphStyle("cell", fontName=_FONT, fontSize=8.5, leading=11),
        "info_label": ParagraphStyle(
            "info_label", fontName=_FONT, fontSize=8.5, leading=13, textColor=_BRAND_INK,
        ),
        "info_value": ParagraphStyle("info_value", fontName=_FONT, fontSize=9.5, leading=13),
    }


def _table_style(*, header_rows: int = 1) -> TableStyle:
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), _BRAND_INK),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


def _fmt_tco2e(value: float | None) -> str:
    return f"{value:,.3f} tCO2e" if value is not None else "산정 전"


def _fmt_missing(missing_months: dict[str, list[int]]) -> str:
    if not missing_months:
        return "결손 없음 (선택 연료 12개월 전부 확보)"
    parts = [
        f"{fuel} {len(months)}개월분({', '.join(f'{m}월' for m in months)})"
        for fuel, months in missing_months.items()
    ]
    return "결손: " + ", ".join(parts)


def _company_info_box(data: dict, styles: dict) -> Table:
    """기업명·업종·지역·상시종업원수·매출액·산정연도·발급기관·발급일을 라벨-값 표
    하나로 묶는다 — 이전엔 문장 하나에 가운데점(·)·파이프(|)로 이어 붙였는데, 그
    기호들이 내장 CID 폰트에서 깨져 보였을 뿐 아니라 정보 덩어리가 뭉쳐 있어 읽기도
    나빴다.

    필드 구성은 환경부 「온실가스 배출량 등 명세서」(녹색전환법 시행규칙 별지
    제11호 서식)의 "법인 총괄정보" 항목 중 감탄이 실제로 가진 값만 참고했다
    (2026-08-15) — 법인등록번호·대표자·담당자 연락처 등 이 프로젝트가 아예
    수집하지 않는 항목은 지어내지 않고 넣지 않는다."""
    company = data["company"]
    rows = [["기업명", company["name"]]]
    if company.get("industry_name"):
        rows.append(["업종", company["industry_name"]])
    if company.get("region"):
        rows.append(["지역", company["region"]])
    if company.get("employee_count"):
        rows.append(["상시종업원수", f"{company['employee_count']}명"])
    if company.get("revenue_krw"):
        rows.append(["매출액", f"{company['revenue_krw'] / 1_000_000:,.0f}백만원"])
    rows.extend([
        ["산정연도", f"{data['reporting_year']}년"],
        ["발급기관", "iM뱅크 감탄(GamTan)"],
        ["발급일", data["generated_at"]],
    ])

    table_rows = [
        [Paragraph(label, styles["info_label"]), Paragraph(value, styles["info_value"])]
        for label, value in rows
    ]
    table = Table(table_rows, colWidths=[28 * mm, 122 * mm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, _BRAND),
        ("BACKGROUND", (0, 0), (-1, -1), _BRAND_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _draw_letterhead(canvas, doc):
    """모든 페이지 좌상단에 iM 로고를 그린다 — SimpleDocTemplate의 흐르는 본문과
    별개로 고정 좌표에 그려야 해서(레터헤드 관례) 콜백으로 처리한다."""
    logo_w = 20 * mm
    logo_h = logo_w * _LOGO_ASPECT
    canvas.drawImage(
        str(_LOGO_PATH), doc.leftMargin, A4[1] - 14 * mm - logo_h,
        width=logo_w, height=logo_h, mask="auto",
    )


def build_owner_report_pdf(data: dict) -> bytes:
    """api/routers/owner_quality.py가 조립한 data를 받아 PDF 바이트를 반환한다.

    data shape:
      company: {name, industry_name, region}
      reporting_year: int
      generated_at: str (YYYY-MM-DD)
      scopes: {scope_1: {...}, scope_2: {...}} 각 값은
        emission_tco2e, candidate_score, activity_data_basis,
        completeness_pct, basis(list[str]), fuel_breakdown(list[dict]),
        missing_months(dict[str, list[int]])
    """
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=32 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    story = []

    scopes = data["scopes"]

    # 1. 헤더
    story.append(Paragraph("탄소배출량 산정 결과서", styles["title"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_company_info_box(data, styles))
    story.append(Spacer(1, 6 * mm))

    # 2. 요약
    story.append(Paragraph("요약", styles["h2"]))
    summary_rows = [["구분", "배출량", "PCAF 데이터 품질등급", "데이터 완전성"]]
    for scope_group in ("scope_1", "scope_2"):
        s = scopes[scope_group]
        grade = f"{s['candidate_score']}등급" if s["candidate_score"] is not None else "산정 전"
        completeness = f"{s['completeness_pct']}%" if s["completeness_pct"] is not None else "-"
        summary_rows.append([
            Paragraph(_SCOPE_LABEL[scope_group], styles["cell"]),
            Paragraph(_fmt_tco2e(s["emission_tco2e"]), styles["cell"]),
            Paragraph(grade, styles["cell"]),
            Paragraph(completeness, styles["cell"]),
        ])
    summary_table = Table(summary_rows, colWidths=[45 * mm, 40 * mm, 45 * mm, 30 * mm])
    summary_table.setStyle(_table_style())
    story.append(summary_table)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "본 결과서는 Scope 1(직접배출), Scope 2(전력 간접배출)만을 대상으로 합니다. "
        "공급망 등 Scope 3(기타 간접배출)은 산정 대상에 포함되지 않았습니다.",
        styles["small"],
    ))

    # 3. Scope별 세부
    story.append(Paragraph("Scope별 세부 내역", styles["h2"]))
    for scope_group in ("scope_1", "scope_2"):
        s = scopes[scope_group]
        story.append(Paragraph(_SCOPE_LABEL[scope_group], styles["body"]))
        fuel_rows = [["연료 종류", "배출량", "전표 건수"]]
        if s["fuel_breakdown"]:
            for row in s["fuel_breakdown"]:
                fuel_rows.append([
                    Paragraph(row["fuel_type"], styles["cell"]),
                    Paragraph(_fmt_tco2e(row["emission_tco2e"]), styles["cell"]),
                    Paragraph(f"{row['voucher_count']}건", styles["cell"]),
                ])
        else:
            fuel_rows.append([Paragraph("해당 연도 활동자료 없음", styles["cell"]), "", ""])
        fuel_table = Table(fuel_rows, colWidths=[55 * mm, 50 * mm, 30 * mm])
        fuel_table.setStyle(_table_style())
        story.append(fuel_table)
        story.append(Paragraph(_fmt_missing(s["missing_months"]), styles["small"]))
        story.append(Spacer(1, 4 * mm))

    # 4. 산정 방법론
    story.append(Paragraph("산정 방법론", styles["h2"]))
    story.append(Paragraph(
        "PCAF(Partnership for Carbon Accounting Financials) Standard Part A Third "
        "Edition의 데이터 품질 옵션 체계(Table 10.1-2)를 적용해 산정했습니다.",
        styles["body"],
    ))
    for scope_group in ("scope_1", "scope_2"):
        s = scopes[scope_group]
        story.append(Spacer(1, 2 * mm))
        basis_label = _BASIS_LABEL.get(s["activity_data_basis"], s["activity_data_basis"] or "-")
        story.append(Paragraph(f"{_SCOPE_LABEL[scope_group]}: {basis_label}", styles["body"]))
        for line in s["basis"]:
            story.append(Paragraph(f"- {line}", styles["small"]))

    doc.build(story, onFirstPage=_draw_letterhead, onLaterPages=_draw_letterhead)
    return buffer.getvalue()
