"""문서 추출(OCR) — 실제 PDF 텍스트 추출만 수행한다(합성 mock 폴백 없음).

`extract_document()`가 이 파이프라인의 유일한 진입점이다. 회계 담당이 만든
업로드 서류(`data/업로드서류/`, `scripts/generate_upload_docs.py`)는 스캔 이미지가
아니라 텍스트 레이어가 있는 PDF라, `db/document_text_extractor.py`가 실제 내용을
그대로 읽는다(OCR·비전 모델 불필요 — 실 사진·스캔본 OCR은 별도 범위, 그때 가서
`db/document_text_extractor.py::extract_pdf_text()` 내부만 교체하면 된다).

과거엔 실 추출이 안 되는 파일을 해시 기반 합성값으로 폴백시켜 "개발 편의용
임의 파일 테스트"를 지원했으나, 이 폴백이 실제로는 파서가 제대로 동작하는지
아닌지를 가려 확인 불가능하게 만든다는 문제가 있어 제거했다(실 서식과 다른
진짜 문서도 조용히 가짜 값으로 대체되는 사고가 있었음). 이제 실 추출이 안 되면
예외 없이 항상 DocumentParseError로 명확히 실패한다(실패 가시성 원칙,
CLAUDE.md §6) — 호출부(api/document_ingestion.py)가 422로 안내한다.
"""
from db.document_text_extractor import DocumentParseError, extract_pdf_text, parse_document_text

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"


def extract_document(file_bytes: bytes, document_type: DocumentType) -> dict:
    """문서에서 실제로 날짜·금액을 읽어낸다.

    PDF 텍스트 추출 → 파싱 실패(PDF가 아니거나 알려진 형식이 아님)하면 값을
    지어내지 않고 DocumentParseError를 그대로 던진다.
    """
    text = extract_pdf_text(file_bytes)
    if text is None:
        raise DocumentParseError(
            "문서에서 텍스트를 읽어내지 못했어요 — PDF 형식의 자료를 올려 주세요"
        )
    return parse_document_text(text, document_type)
