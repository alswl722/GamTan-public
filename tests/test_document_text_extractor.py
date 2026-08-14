"""db/document_text_extractor.py — PDF 텍스트에서 문서종류·날짜·금액·수량을
정규식으로 파싱하는 실 추출기 검증. 값을 지어내지 않는지가 핵심축."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from db.document_text_extractor import (
    DocumentParseError,
    extract_pdf_text,
    parse_document_text,
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
