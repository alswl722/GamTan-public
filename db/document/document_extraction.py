"""문서 추출(OCR) — 텍스트 레이어/HTML 우선, 안 되면 PaddleOCR, 그마저 안 되면
LLM 필드 라우팅(최후 수단)까지 순서대로 시도.

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
   상단 주석 참고). OCR 자체가 글자를 하나도 못 찾아도(rows=[]) 여기서 예외를 밖으로
   흘리지 않고 4번(LLM)까지는 시도한다 — PaddleOCR이 놓친 걸 Gemini 비전이 구제할
   여지가 있다.
3. 위 두 경로가 다 실패하는 건 대개 "글자는 읽었는데 이 프로젝트가 아는 라벨
   단어·표 구조 어디에도 안 맞는" 경우다(예: "작성일자" 대신 "거래일", 처음 보는
   표 배치). 이럴 때 `db/document_llm_router.py`(Gemini)를 최후 수단으로 부른다 —
   **다만 LLM은 "어느 셀이 어느 필드냐"만 가리키고(라우팅), 실제 값은 항상 그 셀의
   OCR 원문을 2번과 동일한 결정론적 정규식으로 다시 파싱한다.** LLM 응답 스키마에
   숫자·날짜 값을 담는 필드 자체가 없어 값을 지어낼 경로가 없다 — CLAUDE.md 원칙1
   (LLM 산수 금지)·"환각이 숫자에 개입할 경로가 없다"는 방어 논리를 유지한 채
   서식·어휘 일반화 능력만 추가한 것.
4. 그마저 실패하면 값을 지어내지 않고 `DocumentParseError`(또는 `OcrEngineError`/
   `LlmRouterError`)로 명확히 실패한다(실패 가시성 원칙, CLAUDE.md §6) — 호출부
   (`api/document_ingestion.py`)가 422로 안내한다.

예외는 슬롯 불일치(`DocumentTypeMismatchError`, 예: 전기고지서를 세금계산서 칸에
업로드)뿐이다 — 문서 자체는 이미 제대로 판별됐으니 재시도해도 결론이 안 바뀌어
그 자리에서 바로 명확히 실패시킨다.

반환 dict에는 `extraction_method`(`text_layer` | `html_text` | `ocr` | `ocr_llm`)와
`extraction_confidence`(OCR·LLM 경로일 때만 신뢰도, 그 외 None)가 포함된다 —
`api/document_ingestion.py`가 `source_documents`에 그대로 영속화해 관리자가 "이
문서가 어떻게 읽혔는지"를 감사할 수 있게 한다(CLAUDE.md 원칙5).
"""
from sqlalchemy.orm import Session

from db.document.document_html_extractor import extract_html_text
from db.document.document_llm_router import route_fields
from db.document.document_ocr_extractor import ocr_extract
from db.document.document_text_extractor import (
    DocumentParseError,
    DocumentTypeMismatchError,
    detect_document_type,  # noqa: F401 — 하위 호환용 재노출(과거 호출부가 여기서 import)
    extract_pdf_text,  # noqa: F401 — 하위 호환용 재노출
    find_supplier_name_best_effort,
    parse_document_text,
    parse_tax_invoice_date_table,
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


def extract_document(
    session: Session, file_bytes: bytes, document_type: DocumentType | None = None
) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다.

    document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥 업로드" 경로다 —
    대조 없이 판별된 종류를 그대로 신뢰한다. 반환 dict에는 항상 "document_type"
    (실제 판별값)이 포함된다. session은 최후 수단(LLM 라우팅)의 llm_cache 조회·
    저장에만 쓰인다 — 앞 세 단계는 DB에 손대지 않는다.
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

    try:
        ocr_result = ocr_extract(file_bytes)
    except DocumentParseError:
        # PaddleOCR이 글자를 아예 못 찾음 — 좌표 기반 재시도도 할 게 없으니 곧장
        # LLM 최후 수단으로 넘어간다(rows=None). Gemini 비전이 PaddleOCR보다
        # 저화질·회전된 사진에 강할 가능성을 살린다.
        ocr_result = None

    if ocr_result is not None:
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
            if header is None:
                # 실측 확인(2026-08-16): 국세청 표준 세금계산서 서식은 "작성일자:" 콜론이
                # 아니라 헤더행/데이터행 표 구조라 위 콜론 기반 정규식이 아예 안 통한다 —
                # 좌표 기반으로 재시도(db/document_text_extractor.py::parse_tax_invoice_date_table).
                date_result = parse_tax_invoice_date_table(ocr_result.rows)
                if date_result is not None:
                    year, month, day = date_result
                    header = {
                        "supplier_name": find_supplier_name_best_effort(ocr_result.text),
                        "year": year,
                        "month": month,
                        "issue_date": f"{year:04d}-{month:02d}-{day:02d}",
                    }
            if header is not None:
                item = parse_tax_invoice_table_rows(ocr_result.rows)
                if item is not None:
                    parsed = {**header, **item, "document_type": "tax_invoice"}
                    return {
                        **parsed,
                        "extraction_method": "ocr",
                        "extraction_confidence": ocr_result.confidence,
                    }

    # 최후 수단 — 텍스트레이어·OCR·좌표매칭 다 실패. LLM은 "어느 셀이 어느
    # 필드냐"만 판단하고, 값은 그 셀의 OCR 원문을 결정론적으로 재파싱해서 얻는다
    # (db/document_llm_router.py 상단 docstring 참고 — 환각이 숫자에 개입할 경로 없음).
    try:
        parsed, confidence = route_fields(
            session, file_bytes, ocr_result.rows if ocr_result is not None else None, document_type
        )
        return {**parsed, "extraction_method": "ocr_llm", "extraction_confidence": confidence}
    except DocumentTypeMismatchError:
        raise
    except DocumentParseError:
        pass

    raise DocumentParseError("문서를 읽지 못했어요 — 더 선명하게 다시 올려 주세요")
