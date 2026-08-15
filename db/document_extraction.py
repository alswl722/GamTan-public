"""문서 추출(OCR) — 실 텍스트 추출 우선, 안 되면 Gemini 비전 폴백.

`extract_document()`가 이 파이프라인의 유일한 진입점이다. 회계 담당이 만든
업로드 서류(`data/업로드서류/`, `scripts/generate_upload_docs.py`)는 스캔 이미지가
아니라 텍스트 레이어가 있는 PDF라, `db/document_text_extractor.py`가 무료·즉시·
결정론적으로 읽는다(1순위, LLM 미호출) — 대다수 데모 업로드가 이 경로로 끝난다.

이 1순위가 실패하면 거의 항상 `db/document_vision_extractor.py`(Gemini 멀티모달)로
폴백한다:
  1. 텍스트 레이어가 아예 없음(실 사진·스캔본).
  2. 텍스트는 있지만 알려진 서식이 아님(예: 국세청 표준 세금계산서 — 이 프로젝트
     정규식 파서가 기대하는 레이아웃과 다른 진짜 문서).
  3. 제목은 알아봤지만 필드 파싱에 실패함(날짜·금액 등을 못 찾음) — "정규식이
     기대하는 정확한 레이아웃"은 이 프로젝트 합성 데이터(reportlab 텍스트 PDF)
     전제에서만 유효하다. 실 사용자가 올리는 진짜 홈택스/한전 PDF는 제목은
     같아도 필드 서식이 다를 수 있어, 텍스트 파싱이 실패해도 비전은 성공할 수
     있다(2026-08-15, 실 사용 시나리오 검토 중 발견 — 예전엔 이 경우도 재시도
     없이 바로 실패시켰다).

예외는 슬롯 불일치(DocumentTypeMismatchError, 예: 전기고지서를 세금계산서 칸에
업로드)뿐이다 — 문서 자체는 이미 제대로 판별됐으니 비전으로 재시도해도 결론이
안 바뀌어 그 자리에서 바로 명확히 실패시킨다(API 호출 낭비 없음).

과거엔 실 추출이 안 되는 파일을 해시 기반 합성값으로 폴백시켜 "개발 편의용
임의 파일 테스트"를 지원했으나, 이 폴백이 실제로는 파서가 제대로 동작하는지
아닌지를 가려 확인 불가능하게 만든다는 문제가 있어 제거했다(실 서식과 다른
진짜 문서도 조용히 가짜 값으로 대체되는 사고가 있었음). 비전 폴백까지 실패하면
예외 없이 항상 DocumentParseError(또는 그 서브클래스 VisionExtractionError)로
명확히 실패한다(실패 가시성 원칙, CLAUDE.md §6) — 호출부(api/document_ingestion.py)가
422로 안내한다.
"""
from db.document_text_extractor import (
    DocumentParseError,
    DocumentTypeMismatchError,
    detect_document_type,
    extract_pdf_text,
    parse_document_text,
)
from db.document_vision_extractor import extract_via_vision

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"


def extract_document(file_bytes: bytes, document_type: DocumentType | None = None) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다.

    document_type을 생략(None)하면 어느 칸인지 모르고 올린 "그냥 업로드" 경로다 —
    대조 없이 판별된 종류를 그대로 신뢰한다(db/document_text_extractor.py::
    parse_document_text, db/document_vision_extractor.py::extract_via_vision가
    이미 각자 판별 로직을 갖고 있어 이 함수는 그대로 통과시키기만 하면 된다).
    반환 dict에는 항상 "document_type"(실제 판별값)이 포함된다.

    1. PDF 텍스트 추출 → 알려진 서식이면 정규식 파싱을 시도한다(무료·즉시·결정론적).
       슬롯을 지정했는데 틀렸으면(예: 전기고지서를 세금계산서 칸에 업로드) 비전으로
       재시도해도 답이 바뀌지 않으므로 그 자리에서 바로 명확히 실패시킨다(API 호출
       낭비 없음) — 그 외 필드 파싱 실패(날짜·금액을 못 찾음 등)는 실제 문서가 이
       모듈의 정규식 전제와 다를 뿐일 수 있어 2번으로 넘어간다.
    2. 텍스트가 없거나(사진·스캔본) 아예 모르는 서식이거나, 1번에서 필드 파싱에
       실패했으면 Gemini 비전으로 재시도한다.
    3. 그마저 실패하면(또는 자동판별 모드에서 종류 자체를 못 알아보면) 값을 지어내지
       않고 DocumentParseError를 그대로 던진다.
    """
    text = extract_pdf_text(file_bytes)
    if text is not None and detect_document_type(text) is not None:
        try:
            return parse_document_text(text, document_type)
        except DocumentTypeMismatchError:
            raise
        except DocumentParseError:
            pass  # 필드 파싱 실패 — 비전으로 재시도(실제 문서일 수 있음, 위 docstring 참고)
    return extract_via_vision(file_bytes, document_type)
