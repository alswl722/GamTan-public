"""세금계산서 발행 알림 이메일(HTML) → 텍스트 추출.

세금계산서는 홈택스·빌36524·하이웍스 등에서 이메일 본문(HTML)이나 첨부 HTML로도
온다 — 시각적 표현이 없는 순수 텍스트 문서라 `db/document_ocr_extractor.py`(PaddleOCR)
대상이 아니다. 태그를 걷어내 보이는 텍스트만 뽑아 `db/document_text_extractor.py`의
기존 정규식 파서에 그대로 흘려보낸다(구조화 로직 재사용 — document_ocr_extractor.py와
같은 자리, CLAUDE.md §7 하이브리드 입력 원칙과 같은 결).

정규식으로 태그를 벗기지 않고 beautifulsoup4를 쓰는 이유: 실제 이메일 HTML은 중첩
태그·잘못 닫힌 태그·script/style 내용이 섞여 있어 regex 스트리핑은 스크립트 코드
등 본문 아닌 내용이 텍스트에 섞이는 사고가 나기 쉽다.
"""
from bs4 import BeautifulSoup

_ENCODINGS = ("utf-8", "cp949")  # cp949 — 국내 구형 메일 클라이언트 인코딩 대비


def looks_like_html(file_bytes: bytes) -> bool:
    """확장자에 의존하지 않고 바이트 내용으로 HTML 여부를 판별 — 업로드 파일명은
    신뢰하지 않는다(기존 PDF/이미지 매직바이트 판별과 같은 관례)."""
    head = file_bytes[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head


def extract_html_text(file_bytes: bytes) -> str | None:
    """HTML로 안 보이거나 디코드에 실패하면 None(db/document_text_extractor.py::
    extract_pdf_text와 같은 계약 — 호출부가 다른 경로를 계속 시도할 수 있게)."""
    if not looks_like_html(file_bytes):
        return None

    text = None
    for encoding in _ENCODINGS:
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    visible = soup.get_text("\n")
    lines = [line.strip() for line in visible.splitlines() if line.strip()]
    return "\n".join(lines) or None
