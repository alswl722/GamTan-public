"""db/document_extraction.py — 합성 mock 추출기 검증. 실제 OCR/로컬모델로 교체될
때까지 인터페이스(입출력 스키마)를 고정하는 게 이 테스트의 목적."""
from db.document_extraction import extract_document


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
