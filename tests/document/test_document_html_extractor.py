"""db/document_html_extractor.py — 세금계산서 이메일(HTML) 텍스트 추출 검증."""
from db.document.document_html_extractor import extract_html_text, looks_like_html
from db.document.document_text_extractor import parse_document_text


def test_looks_like_html_detects_doctype():
    assert looks_like_html(b"<!DOCTYPE html><html><body>hi</body></html>") is True


def test_looks_like_html_rejects_pdf_bytes():
    assert looks_like_html(b"%PDF-1.4\n...") is False


def test_looks_like_html_rejects_plain_text():
    assert looks_like_html(b"just some text, no markup here") is False


def test_extract_html_text_strips_tags_and_script_style():
    html = """
    <!DOCTYPE html>
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <script>console.log("should not appear");</script>
        <h1>전자세금계산서</h1>
        <p>공급자: 구미에너지주유소</p>
        <p>작성일자: 2025-02-11</p>
        <table>
          <tr><td>품목명</td><td>규격</td><td>수량</td><td>단가(원)</td><td>공급가액(원)</td></tr>
          <tr><td>경유</td><td>L</td><td>301L</td><td>1,400</td><td>420,833</td></tr>
        </table>
      </body>
    </html>
    """.encode("utf-8")
    text = extract_html_text(html)
    assert text is not None
    assert "console.log" not in text
    assert "color: red" not in text
    assert "전자세금계산서" in text
    assert "구미에너지주유소" in text


def test_extract_html_text_non_html_returns_none():
    assert extract_html_text(b"%PDF-1.4\n...") is None


def test_extract_html_text_feeds_into_existing_regex_parser():
    """정규식 파서 재사용 확인 — HTML에서 뽑은 텍스트가 그대로 parse_document_text를 통과한다."""
    html = """
    <html><body>
      <div>전기요금 고지서</div>
      <div>청구월: 2025-06</div>
      <div>사용량(kWh) 1,234</div>
      <div>청구금액(원) 987,654</div>
    </body></html>
    """.encode("utf-8")
    text = extract_html_text(html)
    result = parse_document_text(text, "electric_bill")
    assert result["year"] == 2025 and result["month"] == 6
    assert result["supply_amount_krw"] == 987_654
