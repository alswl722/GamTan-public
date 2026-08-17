"""db/document_llm_router.py — OCR·좌표 매칭까지 다 실패했을 때만 붙는 LLM 최후
수단(필드 라우팅) 검증.

핵심 검증축 — LLM 응답에 "값"이 있어도 그걸 쓰지 않는다는 걸 증명하는 것:
  - route_fields()의 최종 반환값은 LLM이 가리킨 cell_id로 OCR 원문을 다시 찾아
    기존 결정론적 파서(parse_amount_from_cell_text 등)로 재파싱한 값이어야 한다.
  - LLM 응답 스키마 자체에 금액·날짜 값을 담는 필드가 없다(_build_schema에 그런
    필드가 없음) — 이 테스트 파일의 가짜 응답도 절대 값을 직접 넣지 않고 항상
    cell_id 참조만 준다(실제 API 계약을 그대로 재현).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import db.document_llm_router as router
from db.document_text_extractor import DocumentParseError, DocumentTypeMismatchError
from db.models import Base


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture(autouse=True)
def _no_real_rasterize(monkeypatch):
    """실제 이미지 디코딩(PyMuPDF 등) 없이 테스트 — images 값 자체는 _call_gemini가
    (매 테스트에서 개별적으로 monkeypatch됨) 안 쓰므로 자리표시자면 충분하다."""
    monkeypatch.setattr(router, "rasterize_to_images", lambda file_bytes: ["fake-image"])


# 테스트 전용 OCR 셀 목록 — 세금계산서 요약행에 날짜 후보가 두 개(작성일자·유효기간)
# 있는 상황을 재현. _flatten_cells와 동일한 순서로 펼치면:
# 0:작성일자 1:유효기간 2:공급가액(헤더) 3:2025-02-11 4:2025-03-01 5:420,833(요약값)
# 6:품목(헤더) 7:공급가액(헤더) 8:경유 9:420,833(품목행 값)
ROWS = [
    [(0.0, 80.0, "작성일자"), (150.0, 220.0, "유효기간"), (280.0, 340.0, "공급가액")],
    [(0.0, 90.0, "2025-02-11"), (150.0, 220.0, "2025-03-01"), (280.0, 340.0, "420,833")],
    [(0.0, 60.0, "품목"), (280.0, 340.0, "공급가액")],
    [(0.0, 55.0, "경유"), (280.0, 340.0, "420,833")],
]


def _gemini_response(**overrides) -> dict:
    base = {
        "document_type": "tax_invoice",
        "date_cell_id": "3",       # "2025-02-11" (작성일자) — "2025-03-01"(유효기간, id=4)이 아님
        "amount_cell_id": "9",     # 품목행의 공급가액
        "item_cell_id": "8",       # "경유"
        "quantity_cell_id": None,
        "supplier_cell_id": None,
        "confidence": 0.9,
        "evidence": "작성일자 라벨 아래 값과 품목행의 공급가액을 선택함",
    }
    base.update(overrides)
    return base


def test_route_fields_never_trusts_llm_value_always_reparsed_from_ocr_text(monkeypatch):
    """핵심 안전장치 — LLM 응답 스키마엔 값 필드가 아예 없으므로, 최종 값은 항상
    cell_id가 가리키는 OCR 원문을 재파싱한 결과와 정확히 일치해야 한다."""
    monkeypatch.setattr(router, "_call_gemini", lambda images, cells, doc_type: _gemini_response())

    parsed, confidence = router.route_fields(_session(), b"fake-bytes-1", ROWS, "tax_invoice")

    assert parsed["year"] == 2025 and parsed["month"] == 2  # 유효기간(3월)이 아니라 작성일자(2월)
    assert parsed["supply_amount_krw"] == 420_833
    assert parsed["item_description"] == "경유"
    assert parsed["document_type"] == "tax_invoice"
    assert confidence == pytest.approx(0.9)


def test_route_fields_picks_correct_date_among_two_candidates_via_label(monkeypatch):
    """OCR이 날짜를 두 개(작성일자·유효기간) 내놔도, LLM이 라벨 문맥으로 올바른
    쪽을 가리키면 그 값만 채택된다 — 다른 쪽(유효기간) 값은 어디에도 안 쓰인다."""
    monkeypatch.setattr(router, "_call_gemini", lambda images, cells, doc_type: _gemini_response())
    parsed, _ = router.route_fields(_session(), b"fake-bytes-2", ROWS, "tax_invoice")
    assert (parsed["year"], parsed["month"]) == (2025, 2)


def test_route_fields_rejects_cell_id_outside_this_documents_list(monkeypatch):
    """모델이 enum 제약을 어기고 존재하지 않는 cell_id를 가리켜도(드문 경우),
    서버 쪽 이중 검증이 걸러내 그 필드는 null 취급된다 — 결국 날짜를 못 채워 실패."""
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda images, cells, doc_type: _gemini_response(date_cell_id="9999"),
    )
    with pytest.raises(DocumentParseError, match="날짜"):
        router.route_fields(_session(), b"fake-bytes-3", ROWS, "tax_invoice")


def test_route_fields_low_confidence_fails_even_with_valid_cells(monkeypatch):
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda images, cells, doc_type: _gemini_response(confidence=0.3),
    )
    with pytest.raises(DocumentParseError):
        router.route_fields(_session(), b"fake-bytes-4", ROWS, "tax_invoice")


def test_route_fields_document_type_mismatch(monkeypatch):
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda images, cells, doc_type: _gemini_response(document_type="electric_bill"),
    )
    with pytest.raises(DocumentTypeMismatchError):
        router.route_fields(_session(), b"fake-bytes-5", ROWS, "tax_invoice")


def test_route_fields_auto_detect_trusts_llm_document_type(monkeypatch):
    """슬롯 미지정("그냥 업로드")이면 LLM이 판별한 종류를 그대로 신뢰한다."""
    monkeypatch.setattr(router, "_call_gemini", lambda images, cells, doc_type: _gemini_response())
    parsed, _ = router.route_fields(_session(), b"fake-bytes-6", ROWS, None)
    assert parsed["document_type"] == "tax_invoice"


def test_route_fields_auto_detect_unknown_type_fails(monkeypatch):
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda images, cells, doc_type: _gemini_response(document_type="unknown"),
    )
    with pytest.raises(DocumentParseError):
        router.route_fields(_session(), b"fake-bytes-7", ROWS, None)


def test_route_fields_caches_by_file_hash(monkeypatch):
    """동일 file_bytes 재호출 시 캐시 히트 — Gemini 재호출 없음(비용·재현성)."""
    call_count = {"n": 0}

    def _counting_call(images, cells, doc_type):
        call_count["n"] += 1
        return _gemini_response()

    monkeypatch.setattr(router, "_call_gemini", _counting_call)
    session = _session()

    router.route_fields(session, b"same-bytes", ROWS, "tax_invoice")
    router.route_fields(session, b"same-bytes", ROWS, "tax_invoice")

    assert call_count["n"] == 1


def test_route_fields_api_failure_after_retries_raises_router_error(monkeypatch):
    def _always_fail(images, cells, doc_type):
        raise RuntimeError("API 오류(테스트)")

    monkeypatch.setattr(router, "_call_gemini", _always_fail)
    with pytest.raises(DocumentParseError):
        router.route_fields(_session(), b"fake-bytes-8", ROWS, "tax_invoice")


def test_route_fields_handles_empty_rows_by_attempting_image_only(monkeypatch):
    """PaddleOCR이 아예 글자를 못 찾은 경우(rows=None) — 셀이 없으니 LLM이 아무
    것도 못 가리켜 결국 실패하지만, 예외 없이 여기까지는 시도돼야 한다."""
    monkeypatch.setattr(
        router, "_call_gemini",
        lambda images, cells, doc_type: _gemini_response(date_cell_id=None, amount_cell_id=None, item_cell_id=None),
    )
    with pytest.raises(DocumentParseError):
        router.route_fields(_session(), b"fake-bytes-9", None, "tax_invoice")
