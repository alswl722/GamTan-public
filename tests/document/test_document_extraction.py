"""db/document_extraction.py — 텍스트 레이어→OCR(PaddleOCR, 100% 로컬)→LLM 최후
수단(라우팅) 4단계 라우팅 검증.

OCR 엔진 호출은 스텁으로 대체한다(무거운 모델 로딩 없이) — db.document_extraction의
`ocr_extract`를 monkeypatch한다. LLM 최후 수단(db/document_llm_router.py)은 이
파일이 쓰는 모든 픽스처가 실제 이미지 매직바이트가 아니라서(`_minimal_pdf`는
PDF, 나머지는 `b"fake jpeg bytes"` 같은 자리표시자) rasterize_to_images()에서
곧장 DocumentParseError로 끝나 네트워크 호출까지 가지 않는다 — session 픽스처는
그 경로(llm_cache 조회)가 죽지 않게 인메모리 DB만 붙여준다. LLM 라우팅 자체의
동작(캐시·값 재해석·신뢰도)은 tests/test_document_llm_router.py에서 별도 검증."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import db.document.document_extraction as document_extraction
from db.document.document_extraction import extract_document
from db.document.document_ocr_extractor import OcrResult
from db.document.document_text_extractor import DocumentParseError
from db.models import Base

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


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


def _stub_ocr(text: str, rows=None, confidence: float = 0.9, skew_deg: float | None = None):
    """db.document_extraction.ocr_extract를 이 OcrResult를 반환하도록 대체할 때 쓴다."""
    return OcrResult(text=text, rows=rows or [], confidence=confidence, skew_deg=skew_deg)


# ── 텍스트 레이어 경로 (변경 없음) ────────────────────────────────────────────

def test_real_pdf_text_is_extracted(session):
    """PDF 텍스트 레이어에서 문서 종류·날짜·금액·수량을 정규식으로 그대로 읽는다
    — 값을 지어내지 않는다(CLAUDE.md §6 실패 가시성 원칙)."""
    pdf = _minimal_pdf([
        "전기요금 고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사업자등록번호: 000-00-00000",
        "청구월: 2025-06 계약종별: 산업용(을) 고압A",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    result = extract_document(session, pdf, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
    assert result["quantity"] == 1234
    assert result["extraction_method"] == "text_layer"
    assert result["extraction_confidence"] is None


def test_extract_document_auto_detects_type_when_omitted(session):
    """document_type 생략("그냥 업로드")하면 텍스트에서 판별한 종류를 그대로
    신뢰하고 반환 dict의 document_type으로 알려준다."""
    pdf = _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사용월: 2025-04",
        "사용량(m³) 800",
        "청구금액(원) 800,000",
    ])
    result = extract_document(session, pdf)
    assert result["document_type"] == "gas_bill"
    assert result["year"] == 2025 and result["month"] == 4


def test_gas_bill_includes_quantity_fields(session):
    pdf = _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사용월: 2025-04",
        "사용량(m³) 800",
        "청구금액(원) 800,000",
    ])
    result = extract_document(session, pdf, "gas_bill")
    assert result["quantity_unit"] == "m3"
    assert result["quantity"] == 800


def test_tax_invoice_includes_quantity_when_printed(session):
    """품목 행에 수량+단위(예: "300L")가 찍혀 있으면 캡처한다 — 세금계산서 경로로
    들어온 유류비 전표도 PCAF 2a(energy_consumption) 판정에 도달할 수 있어야 한다."""
    pdf = _minimal_pdf([
        "전자세금계산서",
        "작성일자: 2025-07-10",
        "공급자: 구미석유",
        "경유 L 300L 1,400 420,000",
    ])
    result = extract_document(session, pdf, "tax_invoice")
    assert result["quantity"] == 300
    assert result["quantity_unit"] == "L"
    assert result["supply_amount_krw"] == 420_000


def test_tax_invoice_without_printed_quantity_omits_quantity_fields(session):
    """세금계산서는 물량이 안 찍혀 있는 경우("-" 등)가 더 흔하다 — 이때는 quantity를
    합성해 넣지 않고 기존 계산 엔진 우선순위(실측 > 금액÷단가)의 후자 경로를 탄다."""
    pdf = _minimal_pdf([
        "전자세금계산서",
        "작성일자: 2025-01-18",
        "공급자: 구미석유",
        "유류대금 - - 1,400 420,000",
    ])
    result = extract_document(session, pdf, "tax_invoice")
    assert result["item_description"] == "유류대금"
    assert "quantity" not in result
    assert result["supply_amount_krw"] == 420_000


# ── 슬롯 불일치는 OCR 재시도 없이 즉시 실패 ───────────────────────────────────

def test_wrong_document_type_raises_immediately_without_ocr_fallback(monkeypatch, session):
    """전기요금고지서를 세금계산서 칸에 올리는 등 알려진 서식인데 슬롯이 틀리면,
    OCR로 재시도해도 답이 바뀌지 않으므로 곧장 실패한다(OCR 호출 낭비 없음) —
    ocr_extract가 호출되지 않는 것까지 확인."""
    def _should_not_be_called(*a, **k):
        raise AssertionError("알려진 서식인데 슬롯만 틀린 경우엔 OCR 폴백을 타면 안 된다")

    monkeypatch.setattr(document_extraction, "ocr_extract", _should_not_be_called)

    pdf = _minimal_pdf([
        "전기요금 고지서",
        "청구월: 2025-06",
        "사용량(kWh) 1,234",
        "청구금액(원) 987,654",
    ])
    with pytest.raises(DocumentParseError, match="전기요금고지서"):
        extract_document(session, pdf, "tax_invoice")


# ── 텍스트 레이어 실패 → OCR 폴백 ─────────────────────────────────────────────

def test_unrecognized_format_falls_back_to_ocr(monkeypatch, session):
    """텍스트는 있지만 아예 모르는 서식(예: 국세청 표준 세금계산서)이면 OCR
    폴백을 탄다."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "전자세금계산서\n작성일자: 2025-01-11\n공급자: 구미에너지주유소\n"
            "경유 L 300L 1,400 460,617"
        ),
    )
    pdf = _minimal_pdf(["전 자 세 금 계 산 서", "작성일자 공급가액", "2025-01-11 460,617"])
    result = extract_document(session, pdf, "tax_invoice")
    assert result["supplier_name"] == "구미에너지주유소"
    assert result["extraction_method"] == "ocr"
    assert result["extraction_confidence"] == pytest.approx(0.9)


def test_no_text_layer_falls_back_to_ocr(monkeypatch, session):
    """텍스트 레이어가 아예 없으면(비-PDF, 실 사진 등) 곧장 OCR 폴백을 탄다."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "전기요금 고지서\n청구월: 2025-03\n사용량(kWh) 500\n청구금액(원) 100,000"
        ),
    )
    result = extract_document(session, b"not a pdf at all", "electric_bill")
    assert result["year"] == 2025
    assert result["extraction_method"] == "ocr"


def test_field_parse_failure_on_recognized_title_falls_back_to_ocr(monkeypatch, session):
    """제목은 알아봤지만(예: "전자세금계산서") 필드 레이아웃이 이 프로젝트 정규식
    전제와 달라 못 찾으면(작성일자 없음) OCR로 재시도한다 — 실제 홈택스/한전 PDF는
    제목은 같아도 필드 서식이 다를 수 있어, 텍스트 파싱 실패가 곧 "이 문서는 못
    읽는다"는 뜻이 아니다."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "전자세금계산서\n작성일자: 2025-07-10\n공급자: 구미석유\n경유 L 300L 1,400 420,000"
        ),
    )
    # "작성일자:" 라벨이 없어 _parse_tax_invoice_item_row/header 정규식이 못 찾는다
    # (필드 파싱 실패, 슬롯 불일치 아님).
    pdf = _minimal_pdf([
        "전자세금계산서",
        "발행일: 2025-07-10",
        "공급자: 구미석유",
        "경유 L 300L 1,400 420,000",
    ])
    result = extract_document(session, pdf, "tax_invoice")
    assert result["supplier_name"] == "구미석유"
    assert result["extraction_method"] == "ocr"


def test_ocr_fallback_failure_propagates(session):
    """OCR 폴백까지 실패하면(monkeypatch 없이 실제 rasterize_to_images가 못 알아보는
    바이트) 값을 지어내지 않고 DocumentParseError 그대로 던진다."""
    with pytest.raises(DocumentParseError):
        extract_document(session, b"not a pdf at all", "tax_invoice")


# ── 기하 보정 재시도(원근변환 우선, 단순 회전은 폴백) ─────────────────────────

def test_extract_document_prefers_perspective_correction_over_deskew(monkeypatch, session):
    """실측(2026-08-19→08-20, IMG_3875): 카메라 각도로 인한 사다리꼴 원근 왜곡은
    단순 회전으로 못 고친다 — perspective_correct_image_bytes(네 모서리 찾아
    homography)를 먼저 시도하고, 성공하면 probe_skew_deg·deskew_image_bytes는
    아예 안 부른다(호출 안 됐는지로 우선순위 확인)."""
    warped_bytes = b"warped-fake-bytes"
    tilted_result = _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.6)
    fixed_text = "전자세금계산서\n작성일자: 2025-05-08\n공급자: 칠곡주유소\n경유 L 35L 1,366 47,810"
    fixed_result = _stub_ocr(fixed_text, rows=[], confidence=0.9)

    def _fake_ocr_extract(file_bytes):
        if file_bytes == warped_bytes:
            return fixed_result
        return tilted_result

    calls = {"probe_skew_deg": 0, "deskew_image_bytes": 0}
    monkeypatch.setattr(document_extraction, "ocr_extract", _fake_ocr_extract)
    monkeypatch.setattr(document_extraction, "perspective_correct_image_bytes", lambda fb: warped_bytes)
    monkeypatch.setattr(
        document_extraction, "probe_skew_deg",
        lambda fb: calls.__setitem__("probe_skew_deg", calls["probe_skew_deg"] + 1) or 8.0,
    )
    monkeypatch.setattr(
        document_extraction, "deskew_image_bytes",
        lambda fb, skew: calls.__setitem__("deskew_image_bytes", calls["deskew_image_bytes"] + 1) or b"unused",
    )

    result = extract_document(session, b"fake jpeg bytes", "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 5
    assert calls["probe_skew_deg"] == 0
    assert calls["deskew_image_bytes"] == 0


def test_extract_document_falls_back_to_deskew_when_no_document_corners_found(monkeypatch, session):
    """perspective_correct_image_bytes가 네 모서리를 못 찾으면(None) 기존 단순
    회전 보정으로 폴백해야 한다."""
    deskewed_bytes = b"deskewed-fake-bytes"
    tilted_result = _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.6)
    fixed_text = "전자세금계산서\n작성일자: 2025-05-08\n공급자: 칠곡주유소\n경유 L 35L 1,366 47,810"
    fixed_result = _stub_ocr(fixed_text, rows=[], confidence=0.9)

    def _fake_ocr_extract(file_bytes):
        if file_bytes == deskewed_bytes:
            return fixed_result
        return tilted_result

    monkeypatch.setattr(document_extraction, "ocr_extract", _fake_ocr_extract)
    monkeypatch.setattr(document_extraction, "perspective_correct_image_bytes", lambda fb: None)
    monkeypatch.setattr(document_extraction, "probe_skew_deg", lambda fb: 8.0)
    monkeypatch.setattr(document_extraction, "deskew_image_bytes", lambda fb, skew: deskewed_bytes)

    result = extract_document(session, b"fake jpeg bytes", "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 5


def test_extract_document_retries_after_deskewing_correctable_tilt(monkeypatch, session):
    """실측(2026-08-19, 같은 세금계산서를 비스듬히 찍은 사진) — 텍스트 파싱·좌표
    매칭·크롭 재시도가 전부 실패한 뒤, probe_skew_deg()로 잰 완만한 기울기(1.5~20도)
    가 있으면 이미지를 반대로 돌려 파이프라인 전체를 한 번 더 돈다. 기울어진
    원본으로는 실패하던 파싱이 보정된 이미지에서는 성공해야 한다.

    probe_skew_deg는 메인 OCR pass가 돌려주는 (내부 원근보정으로 오염된)
    OcrResult.skew_deg가 아니라 별도로 원본을 다시 재는 함수라 따로 스텁한다
    (실측: unwarping 켜진 메인 엔진은 14도짜리 사진을 -1.1도로 잘못 잼)."""
    tilted_bytes = b"tilted-fake-bytes"
    deskewed_bytes = b"deskewed-fake-bytes"

    tilted_result = _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.6)
    fixed_text = "전자세금계산서\n작성일자: 2025-05-08\n공급자: 칠곡주유소\n경유 L 35L 1,366 47,810"
    fixed_result = _stub_ocr(fixed_text, rows=[], confidence=0.9)

    def _fake_ocr_extract(file_bytes):
        if file_bytes == tilted_bytes:
            return tilted_result
        if file_bytes == deskewed_bytes:
            return fixed_result
        raise AssertionError(f"unexpected file_bytes: {file_bytes!r}")

    monkeypatch.setattr(document_extraction, "ocr_extract", _fake_ocr_extract)
    monkeypatch.setattr(document_extraction, "probe_skew_deg", lambda fb: 8.0)
    monkeypatch.setattr(document_extraction, "deskew_image_bytes", lambda fb, skew: deskewed_bytes)

    result = extract_document(session, tilted_bytes, "tax_invoice")
    assert result["year"] == 2025 and result["month"] == 5
    assert result["supply_amount_krw"] == 47_810
    assert result["issue_date"] == "2025-05-08"


def test_extract_document_skips_deskew_when_skew_out_of_correctable_range(monkeypatch, session):
    """probe_skew_deg가 아예 없거나(None) 90도급으로 너무 크면(20도 초과) 보정을
    시도하지 않는다 — 극단적 회전은 재촬영을 요구하는 게 맞다(사용자 확인)."""
    calls = {"deskew": 0}
    monkeypatch.setattr(
        document_extraction, "deskew_image_bytes",
        lambda fb, skew: calls.__setitem__("deskew", calls["deskew"] + 1) or b"unused",
    )
    monkeypatch.setattr(document_extraction, "probe_skew_deg", lambda fb: 45.0)
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.5),
    )
    with pytest.raises(DocumentParseError):
        extract_document(session, b"fake jpeg bytes", "tax_invoice")
    assert calls["deskew"] == 0


def test_extract_document_falls_back_to_original_when_deskew_retry_still_fails(monkeypatch, session):
    """보정 시도 자체는 했지만 보정된 이미지도 결국 못 읽으면(DocumentParseError),
    원본 경로로 계속 진행한다 — 무한 재귀 없이 한 번만 재시도(재귀 호출에서는
    probe_skew_deg를 다시 안 부름)."""
    calls = {"ocr_extract": 0, "probe_skew_deg": 0}

    def _fake_ocr_extract(file_bytes):
        calls["ocr_extract"] += 1
        return _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.5)

    def _fake_probe(file_bytes):
        calls["probe_skew_deg"] += 1
        return 8.0

    monkeypatch.setattr(document_extraction, "ocr_extract", _fake_ocr_extract)
    monkeypatch.setattr(document_extraction, "probe_skew_deg", _fake_probe)
    monkeypatch.setattr(document_extraction, "deskew_image_bytes", lambda fb, skew: b"deskewed-bytes")

    with pytest.raises(DocumentParseError):
        extract_document(session, b"fake jpeg bytes", "tax_invoice")
    # 원본 1회 + 보정 재시도 1회 = 정확히 2번만 불려야 한다(무한 재귀 방지 확인).
    assert calls["ocr_extract"] == 2
    assert calls["probe_skew_deg"] == 1


# ── 세금계산서 표(품목행) 좌표 기반 재시도 ────────────────────────────────────

def test_tax_invoice_table_row_fallback_when_linear_text_row_unmatched(monkeypatch, session):
    """OCR 선형 재구성으로는 품목행을 못 찾아도(사진에서 컬럼이 어긋난 경우), 헤더
    행 좌표 기반 표 매칭(parse_tax_invoice_table_rows)으로 성공한다 — 실측 스파이크
    좌표를 그대로 재현."""
    linear_text = (
        "전자세금계산서\n작성일자: 2025-07-15\n공급자: 대성유류\n"
        "품목명 규격 수량 단가(원) 공급가액(원)\n"  # 헤더는 한 줄로 합쳐짐
        "경유\nL\n301L\n1,400\n420,833"  # 데이터 행은 컬럼이 어긋나 각자 다른 줄로 인식됨
    )
    rows = [
        [(0.0, 82.0, "품목명"), (129.0, 195.0, "규격"), (267.0, 336.0, "수량"),
         (404.0, 516.0, "단가(원)"), (581.0, 748.0, "공급가액(원)")],
        [(0.0, 55.0, "경유"), (125.0, 154.0, "L"), (266.0, 344.0, "301L"),
         (401.0, 490.0, "1,400"), (580.0, 704.0, "420,833")],
    ]
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(linear_text, rows=rows, confidence=0.93),
    )
    result = extract_document(session, b"fake jpeg bytes", "tax_invoice")
    assert result["document_type"] == "tax_invoice"
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 420_833
    assert result["quantity"] == 301 and result["quantity_unit"] == "L"
    assert result["extraction_method"] == "ocr"
    assert result["issue_date"] == "2025-07-15"


def test_tax_invoice_date_table_fallback_when_no_colon_label_at_all(monkeypatch, session):
    """실측(2026-08-16, 사용자 제공 합성 세금계산서 사진) — 국세청 표준 서식은
    "작성일자:" 콜론이 아예 없고 헤더행/데이터행 표 구조라, 선형 텍스트 기반
    parse_tax_invoice_header도 실패한다. 이때 날짜까지 좌표 기반
    (parse_tax_invoice_date_table)으로 찾아야 최종 성공한다 — 품목행 표와 날짜
    요약행 표가 둘 다 "공급가액" 컬럼을 가져도 서로 헷갈리지 않아야 함."""
    linear_text = (
        "전 자 세 금 계 산 서\n공급자 구미에너지주유소\n"
        "작성일자 공급가액 세액 비고\n2025-01-11 460, 617 46, 062\n"
        "품목 규격 수량 단가 공급가액 세액 비고\n경유 L 329 1,400 460,617 46,062"
    )
    rows = [
        [(0.0, 80.0, "작성일자"), (150.0, 220.0, "공급가액"), (280.0, 320.0, "세액"), (360.0, 400.0, "비고")],
        [(0.0, 90.0, "2025-01-11"), (150.0, 220.0, "460, 617"), (280.0, 320.0, "46, 062")],
        [(0.0, 60.0, "품목"), (129.0, 195.0, "규격"), (267.0, 336.0, "수량"),
         (404.0, 516.0, "단가"), (581.0, 748.0, "공급가액"), (760.0, 800.0, "세액")],
        [(0.0, 55.0, "경유"), (125.0, 154.0, "L"), (266.0, 344.0, "329"),
         (401.0, 490.0, "1,400"), (580.0, 704.0, "460,617"), (760.0, 800.0, "46,062")],
    ]
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(linear_text, rows=rows, confidence=0.95),
    )
    result = extract_document(session, b"fake jpeg bytes", "tax_invoice")
    assert result["document_type"] == "tax_invoice"
    assert result["year"] == 2025 and result["month"] == 1
    assert result["issue_date"] == "2025-01-11"
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 460_617
    assert result["extraction_method"] == "ocr"


def test_tax_invoice_table_fallback_not_attempted_for_other_slots(monkeypatch, session):
    """document_type이 electric_bill/gas_bill로 지정된 경우엔 표 매칭을 시도하지
    않는다 — 세금계산서 전용 재시도."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.5),
    )
    with pytest.raises(DocumentParseError):
        extract_document(session, b"fake jpeg bytes", "electric_bill")


# ── 관리비 고지서 (OCR 경로) ──────────────────────────────────────────────────

def test_management_fee_bill_via_ocr_returns_electric_bill_with_quality_flag(monkeypatch, session):
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "○○빌딩 관리비 고지서\n부과월: 2025-06\n전기료 187,000원", confidence=0.88
        ),
    )
    result = extract_document(session, b"fake jpeg bytes")  # "그냥 업로드"
    assert result["document_type"] == "electric_bill"
    assert result["quality_flag"] == "mgmt_fee_estimate"
    assert result["extraction_method"] == "ocr"
