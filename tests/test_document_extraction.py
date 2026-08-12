"""db/document_extraction.py — 실 추출 우선 + 합성 mock 폴백 검증."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from db.document_extraction import extract_document
from db.document_text_extractor import DocumentParseError

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


def test_same_file_bytes_produce_identical_result():
    """재현성 — 같은 파일을 다시 올려도 같은 합성값(데모 안정성)."""
    content = b"fake-tax-invoice-image-bytes"
    a = extract_document(content, "tax_invoice", year=2025, month=7)
    b = extract_document(content, "tax_invoice", year=2025, month=7)
    assert a == b


def test_electric_bill_includes_quantity_fields():
    result = extract_document(b"electric-bill", "electric_bill", year=2025, month=3)
    assert result["quantity_unit"] == "kWh"
    assert result["quantity"] > 0
    assert result["year"] == 2025 and result["month"] == 3


def test_gas_bill_includes_quantity_fields():
    result = extract_document(b"gas-bill", "gas_bill", year=2025, month=4)
    assert result["quantity_unit"] == "m3"
    assert result["quantity"] > 0


def test_tax_invoice_has_no_quantity_fields():
    """세금계산서는 물량이 안 찍혀 있는 경우가 대부분 — 금액÷단가 역산 경로를 타야 하므로
    quantity를 합성해 넣지 않는다(기존 계산 엔진 우선순위: 실측 > 금액÷단가)."""
    result = extract_document(b"tax-invoice", "tax_invoice", year=2025, month=7)
    assert "quantity" not in result
    assert result["supply_amount_krw"] > 0


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


def test_real_pdf_text_is_preferred_over_synthetic_even_with_year_month_given():
    """PDF에 진짜 날짜·금액이 있으면, 폴백용 year/month가 같이 주어져도 문서 내용을
    신뢰한다 — 사용자가 우연히 고른 달보다 문서 자체가 항상 더 정확하다."""
    pdf = _minimal_pdf([
        "전기요금 고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사업자등록번호: 000-00-00000",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    result = extract_document(pdf, "electric_bill", year=1999, month=1)
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
    assert result["quantity"] == 1234


def test_unparseable_pdf_without_fallback_year_month_raises():
    """PDF는 맞지만 알려진 형식이 아니고, 폴백용 year/month도 없으면 값을 지어내지
    않고 명확히 실패한다(실패 가시성 원칙)."""
    pdf = _minimal_pdf(["아무 문서", "관련 없는 내용"])
    with pytest.raises(DocumentParseError):
        extract_document(pdf, "electric_bill")


def test_unparseable_pdf_with_fallback_year_month_uses_synthetic():
    """같은 상황이라도 year/month가 주어지면(개발 편의) 합성 mock으로 통과한다."""
    pdf = _minimal_pdf(["아무 문서", "관련 없는 내용"])
    result = extract_document(pdf, "electric_bill", year=2025, month=9)
    assert result["year"] == 2025 and result["month"] == 9


def test_non_pdf_without_fallback_year_month_raises():
    with pytest.raises(DocumentParseError):
        extract_document(b"not a pdf at all", "tax_invoice")
