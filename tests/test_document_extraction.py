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


def test_tax_invoice_includes_quantity_when_printed():
    """품목 행에 수량+단위(예: "300L")가 찍혀 있으면 캡처한다 — 세금계산서 경로로
    들어온 유류비 전표도 PCAF 2a(energy_consumption) 판정에 도달할 수 있어야 한다
    (db/document_text_extractor.py::_parse_tax_invoice)."""
    pdf = _minimal_pdf([
        "전자세금계산서",
        "작성일자: 2025-07-10",
        "공급자: 구미석유",
        "경유 L 300L 1,400 420,000",
    ])
    result = extract_document(pdf, "tax_invoice")
    assert result["quantity"] == 300
    assert result["quantity_unit"] == "L"
    assert result["supply_amount_krw"] == 420_000


def test_tax_invoice_without_printed_quantity_omits_quantity_fields():
    """세금계산서는 물량이 안 찍혀 있는 경우("-" 등)가 더 흔하다 — 이때는 quantity를
    합성해 넣지 않고 기존 계산 엔진 우선순위(실측 > 금액÷단가)의 후자 경로를 탄다."""
    pdf = _minimal_pdf([
        "전자세금계산서",
        "작성일자: 2025-01-18",
        "공급자: 구미석유",
        "유류대금 외1종 - 1,400 420,000",
    ])
    result = extract_document(pdf, "tax_invoice")
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 420_000


def test_wrong_document_type_raises_immediately_without_vision_fallback(monkeypatch):
    """전기요금고지서를 세금계산서 칸에 올리는 등 알려진 서식인데 슬롯이 틀리면,
    비전으로 재시도해도 답이 바뀌지 않으므로 곧장 실패한다(API 호출 낭비 없음) —
    extract_via_vision이 호출되지 않는 것까지 확인."""
    import db.document_extraction as document_extraction

    def _should_not_be_called(*a, **k):
        raise AssertionError("알려진 서식인데 슬롯만 틀린 경우엔 비전 폴백을 타면 안 된다")

    monkeypatch.setattr(document_extraction, "extract_via_vision", _should_not_be_called)

    pdf = _minimal_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    with pytest.raises(DocumentParseError, match="전기요금고지서"):
        extract_document(pdf, "tax_invoice")


def test_unrecognized_format_falls_back_to_vision(monkeypatch):
    """텍스트는 있지만 아예 모르는 서식(예: 국세청 표준 세금계산서)이면 비전
    폴백을 탄다 — 합성 mock을 없앤 뒤 실제로 발견된 문제(구미정밀 현실 세금계산서)."""
    import db.document_extraction as document_extraction

    monkeypatch.setattr(
        document_extraction, "extract_via_vision",
        lambda file_bytes, document_type: {
            "supplier_name": "구미에너지주유소", "item_description": "경유",
            "supply_amount_krw": 460_617, "year": 2025, "month": 1,
        },
    )
    pdf = _minimal_pdf(["전 자 세 금 계 산 서", "작성일자 공급가액", "2025-01-11 460,617"])
    result = extract_document(pdf, "tax_invoice")
    assert result["supplier_name"] == "구미에너지주유소"


def test_no_text_layer_falls_back_to_vision(monkeypatch):
    """텍스트 레이어가 아예 없으면(비-PDF, 실 사진 등) 곧장 비전 폴백을 탄다."""
    import db.document_extraction as document_extraction

    monkeypatch.setattr(
        document_extraction, "extract_via_vision",
        lambda file_bytes, document_type: {
            "supplier_name": "한국전력공사", "item_description": "전기요금",
            "supply_amount_krw": 100_000, "year": 2025, "month": 3,
        },
    )
    result = extract_document(b"not a pdf at all", "electric_bill")
    assert result["year"] == 2025


def test_vision_fallback_failure_propagates():
    """비전 폴백까지 실패하면(monkeypatch 없이 실제 _detect_mime_type이 못 알아보는
    바이트) 값을 지어내지 않고 DocumentParseError 그대로 던진다."""
    with pytest.raises(DocumentParseError):
        extract_document(b"not a pdf at all", "tax_invoice")
