"""db/document_vision_extractor.py — Gemini 비전 폴백 검증.

네트워크는 쓰지 않는다 — _call_gemini_vision을 스텁으로 대체
(tests/test_orchestrator_smoke.py의 LLM 스텁 패턴과 동일).
"""
import pytest

import db.document_vision_extractor as vision
from db.document_text_extractor import DocumentParseError
from db.document_vision_extractor import (
    VisionExtractionError,
    _detect_mime_type,
    extract_via_vision,
)

_PDF_MAGIC = b"%PDF-1.4\n..."
_JPEG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF..."
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n\x00\x00..."


def _ok_result(**overrides) -> dict:
    base = {
        "document_type": "electric_bill",
        "year": 2025,
        "month": 6,
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": 987_654,
        "quantity": 1234,
        "quantity_unit": "kWh",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


# ── _detect_mime_type ────────────────────────────────────────────────────────
def test_detect_mime_type_pdf():
    assert _detect_mime_type(_PDF_MAGIC) == "application/pdf"


def test_detect_mime_type_jpeg():
    assert _detect_mime_type(_JPEG_MAGIC) == "image/jpeg"


def test_detect_mime_type_png():
    assert _detect_mime_type(_PNG_MAGIC) == "image/png"


def test_detect_mime_type_unknown_raises():
    with pytest.raises(DocumentParseError):
        _detect_mime_type(b"not a known file format at all")


# ── extract_via_vision ───────────────────────────────────────────────────────
def test_extract_via_vision_success(monkeypatch):
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result())

    result = extract_via_vision(_JPEG_MAGIC, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
    assert result["quantity"] == 1234
    assert result["quantity_unit"] == "kWh"


def test_extract_via_vision_omits_quantity_when_not_read(monkeypatch):
    """세금계산서 등 quantity가 안 찍힌 문서는 quantity/quantity_unit 필드 자체가 없어야
    한다(합성해서 넣지 않음 — db/document_text_extractor.py의 기존 규칙과 동일)."""
    monkeypatch.setattr(
        vision, "_call_gemini_vision",
        lambda *a, **k: _ok_result(
            document_type="tax_invoice", quantity=None, quantity_unit=None,
            item_description="경유", supply_amount_krw=420_000,
        ),
    )
    result = extract_via_vision(_JPEG_MAGIC, "tax_invoice")
    assert "quantity" not in result
    assert "quantity_unit" not in result


def test_extract_via_vision_auto_detects_document_type_when_expected_omitted(monkeypatch):
    """expected_document_type 생략("그냥 업로드")하면 대조 없이 Gemini가 판별한
    종류를 그대로 신뢰하고 반환 dict의 document_type으로 알려준다."""
    monkeypatch.setattr(
        vision, "_call_gemini_vision",
        lambda *a, **k: _ok_result(document_type="gas_bill", quantity=800, quantity_unit="m3"),
    )
    result = extract_via_vision(_JPEG_MAGIC)
    assert result["document_type"] == "gas_bill"
    assert result["year"] == 2025 and result["month"] == 6


def test_extract_via_vision_auto_detect_unknown_type_raises(monkeypatch):
    """자동판별 모드에서 Gemini가 종류를 못 알아보면("unknown") 추정으로 채우지
    않고 명확히 실패한다 — 사장님이 직접 종류를 골라 다시 올려야 한다."""
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result(document_type="unknown"))
    with pytest.raises(DocumentParseError, match="판별하지 못했어요"):
        extract_via_vision(_JPEG_MAGIC)


def test_extract_via_vision_wrong_document_type_raises(monkeypatch):
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result(document_type="gas_bill"))
    with pytest.raises(DocumentParseError, match="도시가스고지서"):
        extract_via_vision(_JPEG_MAGIC, "electric_bill")


def test_extract_via_vision_low_confidence_raises(monkeypatch):
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result(confidence=0.2))
    with pytest.raises(DocumentParseError):
        extract_via_vision(_JPEG_MAGIC, "electric_bill")


def test_extract_via_vision_missing_date_raises(monkeypatch):
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result(year=None, month=None))
    with pytest.raises(DocumentParseError):
        extract_via_vision(_JPEG_MAGIC, "electric_bill")


def test_extract_via_vision_missing_amount_raises(monkeypatch):
    monkeypatch.setattr(vision, "_call_gemini_vision", lambda *a, **k: _ok_result(supply_amount_krw=None))
    with pytest.raises(DocumentParseError):
        extract_via_vision(_JPEG_MAGIC, "electric_bill")


def test_extract_via_vision_api_failure_raises_vision_extraction_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("API 호출 실패(타임아웃)")

    monkeypatch.setattr(vision, "_call_gemini_vision", _boom)
    with pytest.raises(VisionExtractionError):
        extract_via_vision(_JPEG_MAGIC, "electric_bill")


def test_extract_via_vision_retries_once_then_succeeds(monkeypatch):
    """최초 시도가 실패해도 1회 재시도로 성공하면 값을 그대로 반환한다."""
    calls = {"count": 0}

    def _fail_once_then_succeed(*a, **k):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("일시적 오류")
        return _ok_result()

    monkeypatch.setattr(vision, "_call_gemini_vision", _fail_once_then_succeed)
    result = extract_via_vision(_JPEG_MAGIC, "electric_bill")
    assert calls["count"] == 2
    assert result["supply_amount_krw"] == 987_654


def test_vision_extraction_error_is_a_document_parse_error():
    """기존 except DocumentParseError 블록(api/routers/owner.py)이 그대로 잡을 수 있어야 한다."""
    assert issubclass(VisionExtractionError, DocumentParseError)
