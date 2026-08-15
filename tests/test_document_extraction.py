"""db/document_extraction.py — 텍스트 레이어→OCR(PaddleOCR, 100% 로컬) 3단계 라우팅 검증.

OCR 엔진 호출은 스텁으로 대체한다(무거운 모델 로딩 없이) — db.document_extraction의
`ocr_extract`를 monkeypatch한다(과거 `extract_via_vision` 자리를 대신함, Gemini 비전은
제거됨)."""
import io

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

import db.document_extraction as document_extraction
from db.document_extraction import extract_document
from db.document_ocr_extractor import OcrResult
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


def _stub_ocr(text: str, rows=None, confidence: float = 0.9):
    """db.document_extraction.ocr_extract를 이 OcrResult를 반환하도록 대체할 때 쓴다."""
    return OcrResult(text=text, rows=rows or [], confidence=confidence)


# ── 텍스트 레이어 경로 (변경 없음) ────────────────────────────────────────────

def test_real_pdf_text_is_extracted():
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
    result = extract_document(pdf, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
    assert result["quantity"] == 1234
    assert result["extraction_method"] == "text_layer"
    assert result["extraction_confidence"] is None


def test_extract_document_auto_detects_type_when_omitted():
    """document_type 생략("그냥 업로드")하면 텍스트에서 판별한 종류를 그대로
    신뢰하고 반환 dict의 document_type으로 알려준다."""
    pdf = _minimal_pdf([
        "도시가스 요금고지서",
        "고객명(사업장): 테스트기업 (경북 구미)",
        "사용월: 2025-04",
        "사용량(m³) 800",
        "청구금액(원) 800,000",
    ])
    result = extract_document(pdf)
    assert result["document_type"] == "gas_bill"
    assert result["year"] == 2025 and result["month"] == 4


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
    들어온 유류비 전표도 PCAF 2a(energy_consumption) 판정에 도달할 수 있어야 한다."""
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


# ── 슬롯 불일치는 OCR 재시도 없이 즉시 실패 ───────────────────────────────────

def test_wrong_document_type_raises_immediately_without_ocr_fallback(monkeypatch):
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
        extract_document(pdf, "tax_invoice")


# ── 텍스트 레이어 실패 → OCR 폴백 ─────────────────────────────────────────────

def test_unrecognized_format_falls_back_to_ocr(monkeypatch):
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
    result = extract_document(pdf, "tax_invoice")
    assert result["supplier_name"] == "구미에너지주유소"
    assert result["extraction_method"] == "ocr"
    assert result["extraction_confidence"] == pytest.approx(0.9)


def test_no_text_layer_falls_back_to_ocr(monkeypatch):
    """텍스트 레이어가 아예 없으면(비-PDF, 실 사진 등) 곧장 OCR 폴백을 탄다."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "전기요금 고지서\n청구월: 2025-03\n사용량(kWh) 500\n청구금액(원) 100,000"
        ),
    )
    result = extract_document(b"not a pdf at all", "electric_bill")
    assert result["year"] == 2025
    assert result["extraction_method"] == "ocr"


def test_field_parse_failure_on_recognized_title_falls_back_to_ocr(monkeypatch):
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
    result = extract_document(pdf, "tax_invoice")
    assert result["supplier_name"] == "구미석유"
    assert result["extraction_method"] == "ocr"


def test_ocr_fallback_failure_propagates():
    """OCR 폴백까지 실패하면(monkeypatch 없이 실제 rasterize_to_images가 못 알아보는
    바이트) 값을 지어내지 않고 DocumentParseError 그대로 던진다."""
    with pytest.raises(DocumentParseError):
        extract_document(b"not a pdf at all", "tax_invoice")


# ── 세금계산서 표(품목행) 좌표 기반 재시도 ────────────────────────────────────

def test_tax_invoice_table_row_fallback_when_linear_text_row_unmatched(monkeypatch):
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
    result = extract_document(b"fake jpeg bytes", "tax_invoice")
    assert result["document_type"] == "tax_invoice"
    assert result["item_description"] == "경유"
    assert result["supply_amount_krw"] == 420_833
    assert result["quantity"] == 301 and result["quantity_unit"] == "L"
    assert result["extraction_method"] == "ocr"


def test_tax_invoice_table_fallback_not_attempted_for_other_slots(monkeypatch):
    """document_type이 electric_bill/gas_bill로 지정된 경우엔 표 매칭을 시도하지
    않는다 — 세금계산서 전용 재시도."""
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr("알아볼 수 없는 텍스트", rows=[], confidence=0.5),
    )
    with pytest.raises(DocumentParseError):
        extract_document(b"fake jpeg bytes", "electric_bill")


# ── 관리비 고지서 (OCR 경로) ──────────────────────────────────────────────────

def test_management_fee_bill_via_ocr_returns_electric_bill_with_quality_flag(monkeypatch):
    monkeypatch.setattr(
        document_extraction, "ocr_extract",
        lambda file_bytes: _stub_ocr(
            "○○빌딩 관리비 고지서\n부과월: 2025-06\n전기료 187,000원", confidence=0.88
        ),
    )
    result = extract_document(b"fake jpeg bytes")  # "그냥 업로드"
    assert result["document_type"] == "electric_bill"
    assert result["quality_flag"] == "mgmt_fee_estimate"
    assert result["extraction_method"] == "ocr"
