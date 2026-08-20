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
from db.document.document_ocr_extractor import (
    deskew_image_bytes,
    ocr_extract,
    ocr_retry_region,
    perspective_correct_image_bytes,
    probe_skew_deg,
)
from db.document.document_text_extractor import (
    DocumentParseError,
    DocumentTypeMismatchError,
    detect_document_type,  # noqa: F401 — 하위 호환용 재노출(과거 호출부가 여기서 import)
    extract_pdf_text,  # noqa: F401 — 하위 호환용 재노출
    find_supplier_name_best_effort,
    find_tax_invoice_date_crop_box,
    issue_date_str,
    parse_document_text,
    parse_tax_invoice_date_crop_rows,
    parse_tax_invoice_date_table,
    parse_tax_invoice_header,
    parse_tax_invoice_table_rows,
)

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"

# 완만하게 기울여 찍은 사진(예: 카메라를 비스듬히 든 경우)만 보정 대상으로 본다.
# 1.5도 미만은 보정할 필요 없는 노이즈 수준. 20도 초과는 촬영 각도가 아니라
# 문서 자체가 90도 등으로 회전됐을 가능성이 높아 손대지 않는다 — 이런 극단적
# 회전은 억지로 되돌리기보다 재촬영을 요구하는 게 맞다(2026-08-19 사용자 확인).
_MIN_CORRECTABLE_SKEW_DEG = 1.5
_MAX_CORRECTABLE_SKEW_DEG = 20.0


def _is_correctable_skew(skew_deg: float | None) -> bool:
    return skew_deg is not None and _MIN_CORRECTABLE_SKEW_DEG <= abs(skew_deg) <= _MAX_CORRECTABLE_SKEW_DEG


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
    session: Session,
    file_bytes: bytes,
    document_type: DocumentType | None = None,
    _deskewed: bool = False,
) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다.

    document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥 업로드" 경로다 —
    대조 없이 판별된 종류를 그대로 신뢰한다. 반환 dict에는 항상 "document_type"
    (실제 판별값)이 포함된다. session은 최후 수단(LLM 라우팅)의 llm_cache 조회·
    저장에만 쓰인다 — 앞 세 단계는 DB에 손대지 않는다.

    _deskewed는 내부 재귀 호출용(호출부가 직접 넘길 값 아님) — 완만한 기울기
    보정 재시도가 무한 반복되지 않게 막는 가드다."""
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
                if date_result is None:
                    # 실측 확인(2026-08-19): "작성"(년월일) 칸이 "공급가액·세액" 자릿수
                    # 칸과 다닥다닥 붙어 있어, 전체 페이지를 한 번에 인식하면 이 구간의
                    # 낱낱 숫자가 뭉개진다(감지모델 등급·리사이즈 한도를 올려도 재현 —
                    # 병목은 격자 밀도 자체). 그 구간만 원본 해상도로 크롭·확대해
                    # 재인식하는 2차 시도 — 크롭 대상이 없거나(헤더 자체를 못 찾음)
                    # 크롭해서 다시 읽어도 안 되면 조용히 포기하고 기존 폴백(품목행
                    # 좌표매칭 → LLM 최후수단)으로 넘어간다.
                    crop_box = find_tax_invoice_date_crop_box(ocr_result.boxes)
                    if crop_box is not None:
                        try:
                            crop_result = ocr_retry_region(file_bytes, crop_box)
                            # parse_tax_invoice_date_table이 아니라 크롭 전용 파서를 쓴다 —
                            # 이 크롭엔 "작성" 헤더 텍스트 자체가 안 남아있을 수 있어(실측
                            # 2026-08-19), 헤더 재탐색을 요구하면 값을 정확히 읽어도 실패한다.
                            date_result = parse_tax_invoice_date_crop_rows(crop_result.rows)
                        except DocumentParseError:
                            date_result = None
                if date_result is not None:
                    year, month, day = date_result
                    header = {
                        "supplier_name": find_supplier_name_best_effort(ocr_result.text),
                        "year": year,
                        "month": month,
                        "issue_date": issue_date_str(year, month, day),
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

    if not _deskewed and ocr_result is not None:
        # 여기까지 다 실패 — LLM을 부르기 전에 기하 보정을 마지막으로 시도한다.
        # 원근변환(perspective_correct_image_bytes)을 먼저 시도한다 — 실측
        # (2026-08-19→08-20, IMG_3875): 카메라 각도로 찍힌 사진은 단순 회전이
        # 아니라 사다리꼴 원근 왜곡이 낀 경우가 있어, 단순 회전 보정만으로는
        # 메인 엔진이 재측정해도 잔차 기울기가 절반만 없어지는 등 불완전했다.
        # 종이의 네 모서리를 찾아 homography로 펴면 회전·원근을 한 번에 없앤다.
        corrected_bytes = perspective_correct_image_bytes(file_bytes)
        if corrected_bytes is None:
            # 원근변환은 종이의 네 모서리(4점 다각형)를 못 찾으면 포기한다
            # (배경이 지저분하거나 대비가 약한 경우 등) — 그럴 때만 기존 단순
            # 회전 보정으로 폴백한다. ocr_result.skew_deg는 메인 엔진(unwarping
            # 켜짐)이 감지 *전에* 이미 상당 부분 펴버린 뒤의 잔차각이라 실제
            # 기울기보다 훨씬 작게 나오므로(실측: 14도짜리 사진이 -1.1도로 측정됨)
            # 여기서는 그 값을 믿지 않고 probe_skew_deg()로 원본을 다시 재서
            # 진짜 기울기를 구한다(비용이 드는 추가 인식 패스라 여기까지 온
            # 실패 케이스에서만 부른다).
            true_skew = probe_skew_deg(file_bytes)
            if _is_correctable_skew(true_skew):
                corrected_bytes = deskew_image_bytes(file_bytes, true_skew)
        if corrected_bytes is not None:
            # 문서를 먼저 똑바로 펴서 파이프라인 전체(이 함수)를 한 번 더 돈다 —
            # 보정해도 실패하면(DocumentParseError) 원본(왜곡된) 경로로 계속
            # 진행한다(밑져야 본전 — 덧대는 것뿐 원래 동작을 해치지 않음).
            try:
                return extract_document(session, corrected_bytes, document_type, _deskewed=True)
            except DocumentParseError:
                pass

    # 최후 수단 — 텍스트레이어·OCR·좌표매칭·기울기 보정 다 실패. LLM은 "어느 셀이
    # 어느 필드냐"만 판단하고, 값은 그 셀의 OCR 원문을 결정론적으로 재파싱해서
    # 얻는다(db/document_llm_router.py 상단 docstring 참고 — 환각이 숫자에 개입할
    # 경로 없음).
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
