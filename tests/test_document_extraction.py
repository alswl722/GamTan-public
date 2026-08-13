"""db/document_extraction.py — 실 PDF 텍스트 추출 검증 (합성 mock 없음)."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from db.document_extraction import extract_document
from db.document_text_extractor import DocumentParseError

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def _minimal_pdf(lines: list[str]) -> bytes:
    """테스트 전용 — reportlab 폰트 리소스(HYGothic 등) 없이 최소 텍스트 PDF를 만든다.
    scripts/generate_upload_docs.py와 폰트만 다를 뿐 pdfplumber가 읽는 텍스트 레이어
    구조는 동일하다."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYGothic-Medium", 11)
    y = 700
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_real_pdf_text_is_extracted():
    """PDF 텍스트 레이어에서 문서 종류·날짜·금액·수량을 정규식으로 그대로 읽는다
    — 값을 지어내지 않는다(합성 mock 제거, CLAUDE.md §6 실패 가시성 원칙)."""
    pdf = _minimal_pdf([
        "전기요금 고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사업자등록번호: 000-00-00000",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    result = extract_document(pdf, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
    assert result["quantity"] == 1234


def test_gas_bill_includes_quantity_fields():
    pdf = _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사용월: 2025-04",
        "사용량(m³) 800",
        "청구금액(원) 800,000",
    ])
    result = extract_document(pdf, "gas_bill")
    assert result["quantity_unit"] == "m3"
    assert result["quantity"] == 800


def test_tax_invoice_has_no_quantity_fields():
    """세금계산서는 물량이 안 찍혀 있는 경우가 대부분 — 금액÷단가 역산 경로를 타야 하므로
    quantity를 합성해 넣지 않는다(기존 계산 엔진 우선순위: 실측 > 금액÷단가)."""
    pdf = _minimal_pdf([
        "전자세금계산서",
        "작성일자: 2025-07-10",
        "공급자: 구미석유",
        "경유 L 300L 1,400 420,000",
    ])
    result = extract_document(pdf, "tax_invoice")
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 420_000


def test_unparseable_pdf_raises():
    """PDF는 맞지만 알려진 형식이 아니면 값을 지어내지 않고 명확히 실패한다
    (실패 가시성 원칙 — 합성 mock 폴백 없음)."""
    pdf = _minimal_pdf(["아무 문서", "관련 없는 내용"])
    with pytest.raises(DocumentParseError):
        extract_document(pdf, "electric_bill")


def test_non_pdf_raises():
    with pytest.raises(DocumentParseError):
        extract_document(b"not a pdf at all", "tax_invoice")


def test_wrong_document_type_raises_with_helpful_message():
    """전기요금고지서를 세금계산서 칸에 올리는 등 엉뚱한 칸에 업로드하면
    값을 억지로 맞추지 않고 어떤 문서인지 알려주며 실패한다."""
    pdf = _minimal_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    with pytest.raises(DocumentParseError, match="전기요금고지서"):
        extract_document(pdf, "tax_invoice")
