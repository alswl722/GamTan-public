"""db/document_text_extractor.py — PDF 텍스트에서 문서종류·날짜·금액·수량을
정규식으로 파싱하는 실 추출기 검증. 값을 지어내지 않는지가 핵심축."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from db.document_text_extractor import (
    DocumentParseError,
    DocumentTypeMismatchError,
    extract_pdf_text,
    parse_document_text,
    parse_tax_invoice_table_rows,
)

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_extract_pdf_text_returns_none_for_non_pdf_bytes():
    assert extract_pdf_text(b"not a pdf") is None


def test_extract_pdf_text_reads_real_pdf():
    text = extract_pdf_text(_pdf(["안녕하세요"]))
    assert text is not None
    assert "안녕하세요" in text


def test_electric_bill_parses_date_amount_quantity():
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-01 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 4,477",
        "청구금액(원) 5,491,807",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result == {
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": 5_491_807,
        "quantity": 4477,
        "quantity_unit": "kWh",
        "year": 2025,
        "month": 1,
        "document_type": "electric_bill",
    }


def test_parse_document_text_without_expected_type_auto_detects():
    """expected_document_type 생략("그냥 업로드")하면 대조 없이 판별된 종류를
    그대로 신뢰하고 반환 dict의 document_type으로 알려준다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text)
    assert result["document_type"] == "electric_bill"
    assert result["year"] == 2025 and result["month"] == 6


def test_gas_bill_parses_date_amount_quantity():
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사용월: 2025-03   용도: 산업용",
        "사용량(m³) 800",
        "청구금액(원) 900,000",
    ]))
    result = parse_document_text(text, "gas_bill")
    assert result["year"] == 2025 and result["month"] == 3
    assert result["quantity"] == 800
    assert result["supply_amount_krw"] == 900_000


def test_tax_invoice_parses_item_amount_and_quantity_from_table_row():
    """수량+단위가 붙은 컬럼("301L")도 이제 캡처한다 — 세금계산서 경로로 들어오는
    유류비 전표도 PCAF 2a(energy_consumption) 판정에 도달할 수 있어야 한다."""
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미에너지주유소",
        "작성일자: 2025-02-11",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "경유 L 301L 1,400 420,833",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["supplier_name"] == "구미에너지주유소"
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 420_833
    assert result["year"] == 2025 and result["month"] == 2
    assert result["quantity"] == 301
    assert result["quantity_unit"] == "L"


def test_tax_invoice_without_printed_quantity_omits_quantity_fields():
    """세금계산서는 물량이 안 찍힌 경우("-" 등)가 더 흔하다 — 이때는 quantity를
    합성해 넣지 않고 기존 금액÷단가 환산 경로를 그대로 탄다."""
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미석유",
        "작성일자: 2025-01-18",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "유류대금 외1종 - 1,400 420,000",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 420_000


def test_degraded_scan_amount_masked_raises_instead_of_faking_value():
    """저품질 스캔 시나리오 — 금액이 ▨로 가려져 있으면 0이나 추정치를 만들지 않고
    명확히 실패한다(실패 가시성 원칙)."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-02 계약종별: 산업용(을) 고압A",
        "사용량(kWh) ▨▨▨ (판독 불가)",
        "청구금액(원) ▨,▨▨▨,▨▨▨ (판독 불가)",
    ]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


def test_wrong_document_type_slot_is_rejected_not_silently_relabeled():
    """도시가스고지서 파일을 전기요금고지서 칸에 올리면, 도시가스 데이터를 전기요금인
    척 반환하지 않고 명확히 실패시킨다."""
    text = extract_pdf_text(_pdf([
        "도시가스 요금고지서",
        "사용월: 2025-01   용도: 산업용",
        "사용량(m³) 800",
        "청구금액(원) 900,000",
    ]))
    with pytest.raises(DocumentParseError, match="전기요금고지서"):
        parse_document_text(text, "electric_bill")


def test_unrecognized_document_raises():
    text = extract_pdf_text(_pdf(["아무 문서", "관련 없는 내용"]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


# ── 실측 스파이크로 확인된 OCR 편차 강건화 ─────────────────────────────────────

def test_extract_pdf_text_reads_all_pages():
    """1페이지만 읽던 것을 전체 페이지로 확장 — 필드가 2페이지에 있어도 놓치지 않는다."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    c.drawString(50, 700, "전기요금 고지서")
    c.drawString(50, 680, "청구월: 2025-06 계약종별: 산업용(을) 고압A")
    c.showPage()
    c.setFont("HYGothic-Medium", 11)
    c.drawString(50, 700, "사용량(kWh) 1,234")
    c.drawString(50, 680, "청구금액(원) 987,654")
    c.save()

    text = extract_pdf_text(buf.getvalue())
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654


def test_detect_document_type_tolerates_title_not_on_first_line():
    """실제 문서는 로고·페이지번호 등이 제목보다 앞에 올 수 있다 — 첫 줄 정확히
    일치가 아니라 앞 5줄 안에서 찾는다."""
    text = extract_pdf_text(_pdf([
        "(주)테스트유틸리티",
        "전기요금 고지서",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_electric_bill_tolerates_space_before_colon():
    """실측 스파이크: OCR이 "청구월 : 2025-06"처럼 라벨과 콜론 사이에 공백을 넣는
    경우가 확인됐다 — 기존 정규식(청구월:\\s*)은 이 경우 매칭 실패였다."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월 : 2025-06 계약종별 : 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_electric_bill_tolerates_label_glued_to_value():
    """실측 스파이크: OCR이 "사용량(kWh)1,234"처럼 라벨과 값 사이 공백 없이 인식하는
    경우가 확인됐다 — 기존 \\s+ 는 매칭 실패, \\s*로 완화."""
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "사용량(kWh)1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["quantity"] == 1234


def test_electric_bill_tolerates_dot_date_separator():
    text = extract_pdf_text(_pdf([
        "전기요금 고지서",
        "청구월: 2025.06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6


def test_slotted_upload_does_not_require_exact_title_phrase():
    """슬롯이 이미 정해졌으면(예: electric_bill 칸에 업로드) 제목이 이 프로젝트가 아는
    정확한 3개 문구("전기요금 고지서" 등)와 달라도(실제 문서는 "전기요금청구서" 같은
    다른 표현일 수 있다) 필드(청구월·사용량·청구금액)만 있으면 파싱된다 — 제목
    일치는 슬롯 미지정("그냥 업로드") 경로에서만 필요하다."""
    text = extract_pdf_text(_pdf([
        "한국전력공사 전기요금청구서",  # 이 프로젝트가 아는 정확한 문구가 아님
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ]))
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["document_type"] == "electric_bill"


def test_slotted_upload_without_title_or_fields_still_fails_clearly():
    """슬롯을 알아도 필드 자체가 없으면(정말 다른 문서) 값을 지어내지 않고 명확히
    실패한다 — 제목 게이트를 뺀 게 아무 문서나 통과시킨다는 뜻은 아니다."""
    text = extract_pdf_text(_pdf(["아무 문서", "관련 없는 내용"]))
    with pytest.raises(DocumentParseError):
        parse_document_text(text, "electric_bill")


def test_tax_invoice_accepts_issue_date_label_synonym():
    text = extract_pdf_text(_pdf([
        "전자세금계산서",
        "공급자: 구미에너지주유소",
        "발급일자: 2025-02-11",
        "품목명 규격 수량 단가(원) 공급가액(원)",
        "경유 L 301L 1,400 420,833",
    ]))
    result = parse_document_text(text, "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 2


# ── 관리비 고지서 ────────────────────────────────────────────────────────────

def test_management_fee_bill_extracts_electric_item_with_quality_flag():
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "일반관리비 320,000",
        "전기료 187,000원",
        "청소비 90,000",
    ]))
    result = parse_document_text(text)  # "그냥 업로드" — 슬롯 지정 없음
    assert result["document_type"] == "electric_bill"
    assert result["supply_amount_krw"] == 187_000
    assert result["year"] == 2025 and result["month"] == 6
    assert result["quality_flag"] == "mgmt_fee_estimate"
    assert "재발행" in result["guidance_message"]


def test_management_fee_bill_in_wrong_slot_is_rejected():
    """관리비 고지서를 세금계산서 칸에 올리면 전기고지서 칸으로 안내하며 명확히 실패."""
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "전기료 187,000원",
    ]))
    with pytest.raises(DocumentTypeMismatchError, match="전기요금고지서"):
        parse_document_text(text, "tax_invoice")


def test_management_fee_bill_without_electric_line_item_raises():
    text = extract_pdf_text(_pdf([
        "○○빌딩 관리비 고지서",
        "부과월: 2025-06",
        "일반관리비 320,000",
    ]))
    with pytest.raises(DocumentParseError, match="관리비 고지서"):
        parse_document_text(text)


# ── OCR 좌표 기반 표 재구성 (parse_tax_invoice_table_rows) ──────────────────────

def test_parse_tax_invoice_table_rows_matches_columns_by_x_position():
    """실측 스파이크에서 확인된 실제 좌표(품목명·규격·수량·단가(원)·공급가액(원)
    헤더 아래 경유/L/301L/1,400/420,833 데이터 행)를 그대로 재현."""
    rows = [
        [(0.0, 82.0, "품목명"), (129.0, 195.0, "규격"), (267.0, 336.0, "수량"),
         (404.0, 516.0, "단가(원)"), (581.0, 748.0, "공급가액(원)")],
        [(0.0, 55.0, "경유"), (125.0, 154.0, "L"), (266.0, 344.0, "301L"),
         (401.0, 490.0, "1,400"), (580.0, 704.0, "420,833")],
    ]
    result = parse_tax_invoice_table_rows(rows)
    assert result == {
        "item_description": "경유",
        "supply_amount_krw": 420_833,
        "quantity": 301,
        "quantity_unit": "L",
    }


def test_parse_tax_invoice_table_rows_without_header_returns_none():
    """헤더 행을 못 찾으면 예외 대신 None — 호출부가 다른 경로를 계속 시도할 수 있게."""
    rows = [[(0.0, 55.0, "경유"), (580.0, 704.0, "420,833")]]
    assert parse_tax_invoice_table_rows(rows) is None
