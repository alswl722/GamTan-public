"""문서 추출(OCR) — 텍스트 레이어/HTML 우선, 안 되면 PaddleOCR(100% 로컬)로 폴백.

`extract_document()`가 이 파이프라인의 유일한 진입점이다.

1. **텍스트 레이어/HTML** — `db/document_text_extractor.py::extract_pdf_text()`(pdfplumber,
   전체 페이지)나 `db/document_html_extractor.py::extract_html_text()`(세금계산서 발행
   이메일)로 텍스트가 뽑히면, 그 텍스트를 `db/document_text_extractor.py::
   parse_document_text()`로 정규식 파싱한다(무료·즉시·결정론적, 회계 담당 업로드
   서류·이메일 대다수가 이 경로로 끝난다).
2. **OCR** — 1번이 실패하면(텍스트 레이어 없음=사진·스캔본, 알려진 서식 아님, 필드
   파싱 실패) `db/document_ocr_extractor.py`(PaddleOCR)로 텍스트/좌표를 재구성해
   **같은 정규식 파서**에 다시 흘려보낸다. 세금계산서는 추가로 좌표 기반 표 매칭
   (`parse_tax_invoice_table_rows`)까지 시도한다 — 사진에서 품목 표 컬럼이 한 줄
   정규식으로는 안 맞을 수 있어서(실측 스파이크로 확인, `db/document_text_extractor.py`
   상단 주석 참고).
3. 그마저 실패하면 값을 지어내지 않고 `DocumentParseError`(또는 `OcrEngineError`)로
   명확히 실패한다(실패 가시성 원칙, CLAUDE.md §6) — 호출부(`api/document_ingestion.py`)
   가 422로 안내한다.

예외는 슬롯 불일치(`DocumentTypeMismatchError`, 예: 전기고지서를 세금계산서 칸에
업로드)뿐이다 — 문서 자체는 이미 제대로 판별됐으니 OCR로 재시도해도 결론이 안
바뀌어 그 자리에서 바로 명확히 실패시킨다.

**100% 로컬**: 이 파이프라인엔 LLM이 없다(Gemini 비전 폴백은 제거됨) — "환각이
숫자에 개입할 경로가 없다"는 방어 논리가 더 순수해진다. 대가로 PaddleOCR로도 못
읽는 극단적인 경우(심한 손글씨·저화질)는 자동 복구 없이 사장님 재업로드 안내로
간다.

반환 dict에는 `extraction_method`(`text_layer` | `html_text` | `ocr`)와
`extraction_confidence`(OCR 경로일 때만 PaddleOCR 평균 confidence, 그 외 None)가
포함된다 — `api/document_ingestion.py`가 `source_documents`에 그대로 영속화해
관리자가 "이 문서가 어떻게 읽혔는지"를 감사할 수 있게 한다(CLAUDE.md 원칙5).
"""
from db.document_html_extractor import extract_html_text
from db.document_ocr_extractor import ocr_extract
from db.document_text_extractor import (
    DocumentParseError,
    DocumentTypeMismatchError,
    detect_document_type,  # noqa: F401 — 하위 호환용 재노출(과거 호출부가 여기서 import)
    extract_pdf_text,  # noqa: F401 — 하위 호환용 재노출
    parse_document_text,
    parse_tax_invoice_header,
    parse_tax_invoice_table_rows,
)

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"


def _extract_deterministic_text(file_bytes: bytes) -> tuple[str | None, str]:
    """텍스트 레이어(PDF) 또는 HTML에서 텍스트를 뽑는다 — 못 뽑으면 (None, "")."""
    text = extract_pdf_text(file_bytes)
    if text is not None:
        return text, "text_layer"
    text = extract_html_text(file_bytes)
    if text is not None:
        return text, "html_text"
    return None, ""


def extract_document(file_bytes: bytes, document_type: DocumentType | None = None) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다.

    document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥 업로드" 경로다 —
    대조 없이 판별된 종류를 그대로 신뢰한다. 반환 dict에는 항상 "document_type"
    (실제 판별값)이 포함된다.
    """
    text, method = _extract_deterministic_text(file_bytes)
    if text is not None:
        try:
            parsed = parse_document_text(text, document_type)
            return {**parsed, "extraction_method": method, "extraction_confidence": None}
        except DocumentTypeMismatchError:
            raise
        except DocumentParseError:
            pass  # 필드 파싱 실패 — OCR로 재시도(실제 사진·다른 서식일 수 있음)

    ocr_result = ocr_extract(file_bytes)
    try:
        parsed = parse_document_text(ocr_result.text, document_type)
        return {**parsed, "extraction_method": "ocr", "extraction_confidence": ocr_result.confidence}
    except DocumentTypeMismatchError:
        raise
    except DocumentParseError:
        pass

    # 세금계산서 전용 표 기반 재시도 — 한 줄 정규식이 사진에서 컬럼 어긋남으로
    # 실패했을 수 있다(db/document_text_extractor.py::parse_tax_invoice_table_rows).
    if document_type is None or document_type == "tax_invoice":
        try:
            header = parse_tax_invoice_header(ocr_result.text)
        except DocumentParseError:
            header = None
        if header is not None:
            item = parse_tax_invoice_table_rows(ocr_result.rows)
            if item is not None:
                parsed = {**header, **item, "document_type": "tax_invoice"}
                return {
                    **parsed,
                    "extraction_method": "ocr",
                    "extraction_confidence": ocr_result.confidence,
                }

    raise DocumentParseError("문서를 읽지 못했어요 — 더 선명하게 다시 올려 주세요")
