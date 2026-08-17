"""텍스트(PDF 텍스트 레이어·HTML·OCR 재구성 텍스트)에서 문서종류·날짜·금액·수량을
정규식으로 파싱한다 — 이 프로젝트의 유일한 구조화 로직.

`scripts/generate_upload_docs.py`가 만드는 문서는 스캔 이미지가 아니라 reportlab로
그린 텍스트 레이어 PDF다 — 그래서 `pdfplumber`로 전체 내용이 그대로 읽힌다. 실
서비스에서 사장님이 올리는 진짜 문서는 이 전제를 안 따른다(사진·스캔본은 텍스트
레이어 자체가 없고, 진짜 홈택스/한전 PDF는 텍스트 레이어가 있어도 필드 레이아웃이
다를 수 있다) — 이런 입력은 `db/document_ocr_extractor.py`(PaddleOCR, 100% 로컬)가
먼저 텍스트로 재구성한 뒤 **이 모듈의 같은 정규식 파서에 그대로 흘려보낸다**. 즉
텍스트 레이어 경로와 OCR 경로가 구조화 로직을 공유한다 — PaddleOCR은 픽셀→글자만
하고, "이게 세금계산서인지, 공급가액이 얼마인지" 판단은 항상 여기서 결정론적으로
한다(CLAUDE.md 원칙1 "LLM 산수 금지"와 같은 결 — 애초에 이 파이프라인엔 LLM이
없다).

OCR 재구성 텍스트는 합성 PDF 텍스트보다 훨씬 지저분하다(라벨 앞뒤 공백 편차, 값이
라벨과 다른 박스로 인식돼 붙어버리거나 떨어지는 경우 등 — 실측 스파이크에서 확인).
그래서 이 모듈의 정규식은 콜론 앞뒤 공백·라벨과 값 사이 공백을 관대하게 허용한다.

파싱 실패(형식이 다름·"판독 불가" 표시·필드 못 찾음)는 값을 지어내지 않고
`DocumentParseError`로 명확히 실패한다(실패 가시성 원칙, CLAUDE.md §6). OCR
경로까지 실패하면 더 이상 폴백이 없다(100% 로컬 결정 — Gemini 비전 폴백은 제거됨).
"""
import io
import re

import pdfplumber

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"

# OCR 표 재구성 결과 하나의 셀: (x_start, x_end, text). document_ocr_extractor.py가
# 좌표 클러스터링으로 만들어 이 모듈의 표 파서(parse_tax_invoice_table_rows)에 넘긴다.
OcrCell = tuple[float, float, str]
OcrRow = list[OcrCell]

DOCUMENT_TYPE_LABEL = {
    "tax_invoice": "세금계산서",
    "electric_bill": "전기요금고지서",
    "gas_bill": "도시가스고지서",
}

_TITLE_TO_DOCUMENT_TYPE = {
    "전자세금계산서": "tax_invoice",
    "전기요금 고지서": "electric_bill",
    # 실측(2026-08-15, 실제 한전 고지서 사진 확인): "OO월분 전기요금 청구서" /
    # "OO월분 전기요금 청구 및 영수증(고지서)" — "전기요금 고지서"라는 정확한
    # 문구는 실물에 없었다. "전기요금 청구"까지만 매칭해 두 실제 서식을 모두 커버.
    "전기요금 청구": "electric_bill",
    "도시가스 요금고지서": "gas_bill",
}

# 문서 앞부분 몇 줄까지를 "제목"으로 볼지 — 실제 문서는 로고·페이지번호 등이 제목보다
# 앞에 찍힐 수 있어 첫 줄만 보면 못 알아본다(완화 전엔 정확히 첫 줄만 봤음).
_TITLE_SEARCH_LINES = 5

_MANAGEMENT_FEE_TITLE_KEYWORD = "관리비"


def _strip_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _label_pattern(label: str) -> str:
    """라벨 리터럴 문자열 → 글자 사이 임의 공백을 허용하는 정규식 조각.

    실측 확인(2026-08-17, 실제 국세청 표준 세금계산서): 제목이 "전 자 세 금 계
    산 서"처럼 자간이 벌어져 렌더링됐고 OCR도 그대로 재구성했다 — 같은 디자인
    관례가 다른 라벨(청구월·작성일자 등)에도 쓰일 수 있어, 정규식에 라벨을 그냥
    박아넣는 모든 곳에 이 헬퍼를 쓴다. 문자 단위로 나눠 사이에 \\s*를 넣으므로
    괄호 등 정규식 특수문자가 섞인 라벨("사용량(kWh)")도 각 문자가 escape되어
    안전하게 그대로 쓸 수 있다."""
    return r"\s*".join(re.escape(ch) for ch in label)


# 실측 확인(2026-08-17, 실제 국세청 표준 세금계산서 사진): 제목이 "전 자 세 금 계
# 산 서"처럼 글자 사이가 벌어져 렌더링되고, OCR도 그 벌어진 간격을 그대로 인식한다
# (디자인상 자간 강조 — PDF 텍스트 레이어·OCR 둘 다 동일하게 영향받음). 공백을
# 지우고 비교해야 "전자세금계산서" 같은 공백 없는 키워드와 매칭된다.
_TITLE_TO_DOCUMENT_TYPE_NO_WS = {_strip_ws(title): doc_type for title, doc_type in _TITLE_TO_DOCUMENT_TYPE.items()}
_MANAGEMENT_FEE_TITLE_KEYWORD_NO_WS = _strip_ws(_MANAGEMENT_FEE_TITLE_KEYWORD)


class DocumentParseError(ValueError):
    """텍스트에서 필요한 정보를 읽어내지 못했을 때 — 값을 지어내지 않고 여기서 멈춘다."""


class DocumentTypeMismatchError(DocumentParseError):
    """호출자가 지정한 슬롯과 실제 문서종류가 다를 때만 쓰는 서브클래스 — 문서
    자체는 정상적으로 판별됐으니 OCR로 재시도해도 결론이 안 바뀐다(db/
    document_extraction.py가 이 서브클래스만 폴백 없이 즉시 실패시킨다). 그 외
    필드 파싱 실패(날짜·금액 못 찾음 등)는 그냥 DocumentParseError로 던져 OCR
    폴백 대상이 되게 한다."""


def extract_pdf_text(file_bytes: bytes) -> str | None:
    """PDF가 아니거나 텍스트 레이어가 없으면 None(실 사진·스캔본 등 — OCR 대상).
    모든 페이지를 순회해 개행으로 연결한다(실제 문서는 페이지 분리가 합성 데모와
    다를 수 있어 첫 페이지만 보면 놓치는 필드가 생길 수 있다)."""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                return None
            texts = [p.extract_text() for p in pdf.pages]
    except Exception:
        return None
    joined = "\n".join(t for t in texts if t)
    return joined or None


def detect_document_type(text: str) -> DocumentType | None:
    """앞 몇 줄(_TITLE_SEARCH_LINES) 안에서 알려진 제목 키워드를 찾아 문서종류를
    판별 — 못 알아보면 None. 첫 줄 정확히 일치가 아니라 "포함"으로 완화했다(실제
    문서는 제목이 정확히 첫 줄에, 다른 텍스트 없이 오지 않을 수 있다 — 여전히
    결정론적 키워드 매칭, LLM 아님. CLAUDE.md §5 원칙3과 같은 결).

    db/document_extraction.py가 이 함수로 먼저 "아예 모르는 서식인지"를 갈라
    첫 시도 경로(정규식 파싱 vs OCR 재시도)를 정한다. 슬롯이 지정됐는데 실제
    종류가 다르면(DocumentTypeMismatchError) OCR로 재시도해도 결론이 안
    바뀌므로 그대로 실패시키지만, 그 외 필드 파싱 실패는 OCR로 재시도한다.
    """
    stripped = text.strip()
    if not stripped:
        return None
    lines = stripped.splitlines()[:_TITLE_SEARCH_LINES]
    for line in lines:
        normalized = _strip_ws(line)
        for title, doc_type in _TITLE_TO_DOCUMENT_TYPE_NO_WS.items():
            if title in normalized:
                return doc_type
    return None


def _looks_like_management_fee_bill(text: str) -> bool:
    """관리비 고지서 규칙 기반 인식 — "관리비" 키워드가 앞부분에 있으면 참.

    관리비 고지서 자체는 한전이 발행한 게 아니라 부가세 공제 증빙이 안 된다
    (사용자 제공 도메인 자료 근거) — 그래도 안의 "전기료" 항목은 CLAUDE.md §6의
    결손 월 업종평균 임시보정과 같은 결로 추정치로 쓴다(§parse_management_fee_bill).
    """
    stripped = text.strip()
    if not stripped:
        return False
    lines = stripped.splitlines()[:_TITLE_SEARCH_LINES]
    return any(_MANAGEMENT_FEE_TITLE_KEYWORD_NO_WS in _strip_ws(line) for line in lines)


def _parse_amount(raw: str, *, field_label: str) -> int:
    """콤마 섞인 숫자 문자열 → int. "▨"·"판독 불가" 표시가 있으면 명확히 실패시킨다
    (저품질 스캔 시나리오 — 값을 지어내는 대신 재업로드를 요청해야 하는 케이스)."""
    cleaned = raw.strip()
    if "▨" in cleaned or "판독 불가" in cleaned:
        raise DocumentParseError(
            f"{field_label}을(를) 읽을 수 없는 파일이에요(화질 불량 등) — 다시 스캔해서 올려 주세요"
        )
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        raise DocumentParseError(f"{field_label} 형식을 인식하지 못했어요: {raw!r}")
    return int(digits)


def parse_amount_from_cell_text(text: str) -> int | None:
    """셀 원문에서 금액만 뽑는다(콤마·공백 편차 무시). 못 찾으면 None(예외 대신).

    db/document_llm_router.py 전용 공개 진입점 — LLM은 "어느 셀이 금액이냐"만
    가리키고, 실제 숫자는 항상 이 함수로 그 셀의 OCR 원문을 재파싱해서 얻는다
    (LLM이 반환한 숫자를 직접 신뢰하는 코드는 없다). `_parse_amount()`는 이
    모듈 밖에서 쓰라고 만든 게 아니라서 얇은 공개 래퍼를 둔다.
    """
    try:
        return _parse_amount(text, field_label="금액")
    except DocumentParseError:
        return None


def parse_year_month_from_cell_text(text: str) -> tuple[int, int] | None:
    """셀 원문에서 연/월만 뽑는다(일자는 있어도 무시 — 기존 파서들과 동일하게
    년/월까지만 쓴다). 구분자 앞뒤 공백은 `_DATE_SEP`과 동일하게 허용.

    db/document_llm_router.py 전용 공개 진입점 — parse_amount_from_cell_text와
    같은 이유(LLM 응답의 값이 아니라 셀 원문을 항상 재파싱).
    """
    m = re.search(rf"(\d{{4}}){_DATE_SEP}(\d{{2}})(?:{_DATE_SEP}\d{{2}})?", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# 알림톡류 문서(한전 사용량 알림 등)는 "예상 전기요금"/"예상 사용량"처럼 실제 라벨과
# 겉보기엔 비슷한 문구로 AI 예측치·추정치를 안내한다 — 실측(2026-08-17, 실제 한전
# 알림톡 캡처 확인). 이런 예측치를 실제 청구금액인 것처럼 계산에 쓰면 CLAUDE.md
# 원칙1·7(추정치를 실측처럼 합산하지 않는다)을 어기게 되므로, 라벨 바로 앞에 이
# 접두어가 붙어 있으면 값을 지어내지 않고 명확히 실패시킨다.
_FORECAST_PREFIX_KEYWORDS = ("예상", "예측", "추정")


def _line_value(text: str, label_pattern: str, *, field_label: str) -> str:
    # 라벨과 값 사이 공백은 0개 이상 허용(\s*) — OCR은 "사용량(kWh)1,234"처럼 라벨과
    # 값을 붙여서 인식하는 경우가 실측 스파이크에서 확인됐다(원래 \s+는 이 경우 매칭 실패).
    m = re.search(label_pattern + r"\s*(.+)", text)
    if not m:
        raise DocumentParseError(f"{field_label} 항목을 찾지 못했어요")
    prefix = text[max(0, m.start() - 10) : m.start()]
    if any(kw in prefix for kw in _FORECAST_PREFIX_KEYWORDS):
        raise DocumentParseError(
            f"실제 {field_label}이 아니라 예상·추정치로 보여요 — 정식 청구서로 다시 올려 주세요"
        )
    return m.group(1).strip()


def _parse_by_type(document_type: DocumentType, text: str) -> dict:
    if document_type == "electric_bill":
        return _parse_electric_bill(text)
    if document_type == "gas_bill":
        return _parse_gas_bill(text)
    if document_type == "tax_invoice":
        return _parse_tax_invoice(text)
    raise DocumentParseError(f"알 수 없는 문서종류: {document_type}")


def parse_document_text(text: str, expected_document_type: DocumentType | None = None) -> dict:
    """텍스트에서 문서종류·날짜·공급자·금액·수량을 뽑는다.

    expected_document_type이 주어졌는데 실제 내용이 다르면(엉뚱한 카드에 업로드)
    값을 억지로 맞추지 않고 명확히 실패시킨다. 생략(None)하면 대조 없이 판별된
    종류를 그대로 신뢰한다("그냥 업로드" — 어느 칸인지 모르고 올릴 때).

    반환 dict에는 항상 "document_type"(실제 판별값)이 포함된다 — 호출부가
    사용자가 지정 안 한 경우에도 실제 종류를 알 수 있어야 하기 때문.
    """
    if expected_document_type is not None:
        return _parse_with_known_slot(text, expected_document_type)
    return _parse_with_auto_detect(text)


def _parse_with_known_slot(text: str, expected_document_type: DocumentType) -> dict:
    """슬롯이 이미 정해졌으면(사장님이 "전기고지서" 칸에 업로드 등) 제목 문구 일치를
    요구하지 않고 그 종류 전용 필드 파서부터 바로 시도한다 — 실제 문서 제목이 이
    프로젝트가 아는 정확한 3개 문구("전자세금계산서"/"전기요금 고지서"/"도시가스
    요금고지서")와 다를 수 있다(예: "전기요금청구서", 띄어쓰기 편차, 로고·QR코드에
    밀려 앞 5줄 밖으로 나감). 슬롯을 이미 알려준 사용자에게 제목 일치까지 추가로
    요구하는 건 과도한 제약이다 — 필드(청구월·사용량·공급가액 등)만 찾으면 충분하다.

    필드까지 못 찾으면(정말 다른 서식이거나, 엉뚱한 칸에 업로드) 그때 제목으로
    "혹시 다른 종류로 보이는지" 확인해 더 정확한 안내를 준다.
    """
    try:
        result = _parse_by_type(expected_document_type, text)
        return {**result, "document_type": expected_document_type}
    except DocumentParseError:
        detected = detect_document_type(text)
        if detected is not None and detected != expected_document_type:
            raise DocumentTypeMismatchError(
                f"업로드하신 파일은 {DOCUMENT_TYPE_LABEL[detected]}로 보여요 — "
                f"{DOCUMENT_TYPE_LABEL[expected_document_type]} 칸에 다시 올려 주세요"
            )
        if _looks_like_management_fee_bill(text):
            if expected_document_type != "electric_bill":
                raise DocumentTypeMismatchError(
                    "관리비 고지서(전기료 항목 포함)로 보여요 — "
                    f"{DOCUMENT_TYPE_LABEL['electric_bill']} 칸에 다시 올려 주세요"
                )
            return parse_management_fee_bill(text)
        raise


def _parse_with_auto_detect(text: str) -> dict:
    """"그냥 업로드"(슬롯 미지정) — 어느 종류인지 알려줄 힌트가 없으므로 제목
    문구로 판별할 수밖에 없다(§_parse_with_known_slot과 달리 완화 대상 아님)."""
    detected = detect_document_type(text)
    if detected is None:
        if _looks_like_management_fee_bill(text):
            return parse_management_fee_bill(text)
        raise DocumentParseError("인식할 수 없는 문서 형식이에요")
    result = _parse_by_type(detected, text)
    return {**result, "document_type": detected}


# 실제 문서는 날짜 구분자가 하이픈만이 아닐 수 있다(점·슬래시) — OCR·실물 서식 편차 허용.
# 앞뒤 공백 허용 — 실측 확인(2026-08-17, 실제 국세청 표준 세금계산서 사진): 헤더
# 요약행("작성일자 공급가액 세액 비고" 아래 데이터행)의 날짜 셀이 OCR에서
# "2025- 02-11"처럼 구분자 뒤에 공백이 섞여 재구성됐다(같은 셀의 "333- 11- 22222"
# 등록번호, "420, 833" 금액에서도 동일 패턴 확인 — 이 문서 특유의 렌더링 간격).
# 원래 "[-./]"는 이 경우 매칭 실패.
_DATE_SEP = r"\s*[-./]\s*"


def _parse_electric_bill(text: str) -> dict:
    # 콜론 앞 공백 허용(\s*:) — "청구월 : 2025-06"처럼 OCR이 라벨과 콜론 사이에 공백을
    # 넣는 경우가 실측 스파이크에서 확인됐다(원래 "청구월:\s*"는 이 경우 매칭 실패).
    # 실측(2026-08-15, 실제 한전 고지서): "청구월:" 라벨 자체가 없고, 대신 제목 근처에
    # "2021년 12월분"처럼 청구월이 찍혀 있었다 — 그쪽도 함께 시도한다. "사용기간:
    # 10월22일~12월21일"처럼 청구월과 다른 달에 걸친 사용기간 범위는 있어도 청구월
    # 자체를 명시한 라벨은 없었다.
    date_m = re.search(
        rf"{_label_pattern('청구월')}\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}})", text
    ) or re.search(r"(\d{4})년\s*(\d{1,2})월분", text)
    if not date_m:
        raise DocumentParseError("청구월을 찾지 못했어요")
    # 실측: 실제 고지서는 "사용량(kWh)" 라벨을 못 찾을 수 있다(사용전력량이 비교
    # 그래프·계량기 지침 표 등 다른 형태로 들어있는 서식이 있었음) — 세금계산서
    # 물량 처리와 같은 원칙으로, 물량을 못 찾아도 금액만 있으면 파싱 자체는
    # 성공시키고(금액÷단가 환산 경로로 계산), quantity 필드는 그냥 안 넣는다.
    quantity = None
    try:
        quantity = _parse_amount(
            _line_value(text, _label_pattern("사용량(kWh)"), field_label="사용량"), field_label="사용량"
        )
    except DocumentParseError:
        pass
    # 실측: "청구금액(원)"이 아니라 "청구금액"(단위 없이) 바로 뒤에 금액이 온다
    # ("청구금액 9,240원") — "(원)"을 선택적으로 바꿔 둘 다 허용.
    amount = _parse_amount(
        _line_value(text, _label_pattern("청구금액") + f"(?:{_label_pattern('(원)')})?", field_label="청구금액"),
        field_label="청구금액",
    )
    result = {
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": amount,
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }
    if quantity is not None:
        result["quantity"] = quantity
        result["quantity_unit"] = "kWh"
    return result


def _parse_gas_bill(text: str) -> dict:
    date_m = re.search(rf"{_label_pattern('사용월')}\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}})", text)
    if not date_m:
        raise DocumentParseError("사용월을 찾지 못했어요")
    quantity = _parse_amount(
        _line_value(text, _label_pattern("사용량(m³)"), field_label="사용량"), field_label="사용량"
    )
    amount = _parse_amount(
        _line_value(text, _label_pattern("청구금액(원)"), field_label="청구금액"), field_label="청구금액"
    )
    return {
        "supplier_name": "도시가스",
        "item_description": "도시가스",
        "supply_amount_krw": amount,
        "quantity": quantity,
        "quantity_unit": "m3",
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }


def find_supplier_name_best_effort(text: str) -> str:
    """"공급자: OO" 콜론 형식을 찾아보되, 없으면 "알 수 없음" — 공급자는 계산에
    쓰이지 않는 표시용 필드라(CLAUDE.md 계산은 공급가액·수량만 본다) 못 찾아도
    문서 전체를 실패시키지 않는다. db/document_extraction.py가 날짜를
    parse_tax_invoice_date_table()(좌표 기반)로 찾은 경우에도 이 함수로 공급자를
    같이 채운다."""
    supplier_m = re.search(rf"{_label_pattern('공급자')}\s*:\s*(.+)", text)
    return supplier_m.group(1).strip() if supplier_m else "알 수 없음"


def parse_tax_invoice_header(text: str) -> dict:
    """세금계산서의 날짜·공급자만 뽑는다(품목행과 분리 — db/document_ocr_extractor.py의
    표 재구성 경로가 품목행은 좌표 기반 parse_tax_invoice_table_rows()로 따로 뽑고
    날짜·공급자는 이 함수로 공유해서 쓴다)."""
    date_m = re.search(
        rf"(?:{_label_pattern('작성일자')}|{_label_pattern('발급일자')})"
        rf"\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}}){_DATE_SEP}(\d{{2}})",
        text,
    )
    if not date_m:
        raise DocumentParseError("작성일자를 찾지 못했어요")
    return {
        "supplier_name": find_supplier_name_best_effort(text),
        "year": int(date_m.group(1)),
        "month": int(date_m.group(2)),
    }


def _parse_tax_invoice_item_row(text: str) -> dict:
    # 품목 행: "경유 L 301L 1,400 420,833" — 품목명, 규격, 수량+단위(예: "301L"), 단가(원),
    # 공급가액(원). 마지막 두 컬럼만 순수 숫자/콤마라 이 패턴으로 헤더 행("품목명 규격 ...
    # 공급가액(원)")과 구분된다(헤더는 괄호·한글이 섞여 있어 [\d,]+로 안 끝남). 한 줄
    # 문자열에 의존하는 방식이라 OCR 표 사진에는 안 통할 수 있다 — 그 경우
    # parse_tax_invoice_table_rows()(좌표 기반)를 대신 쓴다.
    row_m = re.search(r"^(\S+)\s+\S+\s+(\S+)\s+[\d,]+\s+([\d,]+)\s*$", text, re.MULTILINE)
    if not row_m:
        raise DocumentParseError("품목·공급가액 행을 찾지 못했어요")
    result = {
        "item_description": row_m.group(1).strip(),
        "supply_amount_krw": _parse_amount(row_m.group(3), field_label="공급가액"),
    }
    # 세금계산서는 물량이 안 찍힌 경우("-" 등)가 더 흔하다 — 이때는 quantity 필드
    # 자체를 안 넣어 기존 금액÷단가 환산 경로를 그대로 탄다.
    qty_m = re.match(r"^([\d,]+)(\D+)$", row_m.group(2))
    if qty_m:
        result["quantity"] = _parse_amount(qty_m.group(1), field_label="수량")
        result["quantity_unit"] = qty_m.group(2).strip()
    return result


def _parse_tax_invoice(text: str) -> dict:
    header = parse_tax_invoice_header(text)
    item_row = _parse_tax_invoice_item_row(text)
    return {**header, **item_row}


_TABLE_HEADER_ITEM_KEYWORDS = ("품목명", "품목")
_TABLE_HEADER_AMOUNT_KEYWORDS = ("공급가액",)
_TABLE_HEADER_SPEC_KEYWORDS = ("규격",)
_TABLE_HEADER_QTY_KEYWORDS = ("수량", "물량")
_TABLE_HEADER_DATE_KEYWORDS = ("작성일자", "발급일자")
_TABLE_COLUMN_MATCH_TOLERANCE = 10  # px, 컬럼 중심 좌표 매칭 여유


def _cell_for_column(row: OcrRow, col_range: tuple[float, float]) -> str | None:
    """행 안에서 주어진 컬럼 x범위 중심에 가장 가까운 셀 텍스트를 찾는다 —
    parse_tax_invoice_table_rows()·parse_tax_invoice_date_table()이 공유."""
    col_center = (col_range[0] + col_range[1]) / 2
    best_text, best_dist = None, None
    for x0, x1, text in row:
        if x0 - _TABLE_COLUMN_MATCH_TOLERANCE <= col_center <= x1 + _TABLE_COLUMN_MATCH_TOLERANCE:
            dist = abs((x0 + x1) / 2 - col_center)
            if best_dist is None or dist < best_dist:
                best_text, best_dist = text.strip(), dist
    return best_text


def parse_tax_invoice_date_table(rows: list[OcrRow]) -> tuple[int, int] | None:
    """세금계산서 날짜가 "작성일자:" 콜론 형식이 아니라 헤더행/데이터행 표 구조일
    때 좌표 기반으로 찾는다 — 실측 확인(2026-08-16, 사용자 제공 합성 세금계산서
    사진): 실제 국세청 표준 세금계산서 서식은 "작성일자·공급가액·세액·비고" 헤더
    행 아래 값이 오는 표라서, parse_tax_invoice_header()의 콜론 기반 정규식이
    통하지 않는다. parse_tax_invoice_table_rows()와 같은 헤더행 탐지 방식이지만
    "품목" 대신 "작성일자"/"발급일자"를 찾는다 — 같은 문서 안에 공급가액 컬럼을
    가진 표가 두 개(작성일자 요약행, 품목행) 있을 수 있어 헤더 판별 키워드를
    다르게 둔다(둘을 혼동하지 않음). 헤더나 값을 못 찾으면 None(예외 대신 —
    호출부가 다른 경로를 계속 시도할 수 있게)."""
    for i, row in enumerate(rows):
        date_col = next(
            (
                (x0, x1)
                for x0, x1, text in row
                if any(kw in _strip_ws(text) for kw in _TABLE_HEADER_DATE_KEYWORDS)
            ),
            None,
        )
        if date_col is None:
            continue
        for data_row in rows[i + 1 : i + 3]:  # 바로 아래 한두 행 안에서 값을 찾는다
            cell = _cell_for_column(data_row, date_col)
            if cell:
                m = re.search(rf"(\d{{4}}){_DATE_SEP}(\d{{2}}){_DATE_SEP}(\d{{2}})", cell)
                if m:
                    return int(m.group(1)), int(m.group(2))
        return None  # 헤더는 찾았는데 값을 못 찾으면 더 이상 시도 안 함
    return None


def parse_tax_invoice_table_rows(rows: list[OcrRow]) -> dict | None:
    """OCR 좌표 클러스터링 결과(행 단위 셀 리스트, db/document_ocr_extractor.py 생성)에서
    세금계산서 품목행을 찾는다.

    _parse_tax_invoice_item_row()(한 줄 문자열 정규식)가 사진에서 컬럼이 어긋나 실패할 때
    쓰는 좌표 기반 대안 — 헤더 행("품목명"·"공급가액" 셀)의 x좌표 범위를 컬럼 정의로 삼고,
    그 아래 데이터 행에서 같은 x범위에 있는 셀을 같은 컬럼값으로 매칭한다(표 컬럼이 얼마나
    잘렸든 셀 개수에 의존하지 않음). 헤더를 못 찾으면 None(예외 대신 — 호출부가 다른
    경로를 계속 시도할 수 있게).
    """
    header_cols: dict[str, tuple[float, float]] | None = None
    header_row_idx = -1
    for i, row in enumerate(rows):
        found: dict[str, tuple[float, float]] = {}
        for x0, x1, text in row:
            t = _strip_ws(text)
            if any(k in t for k in _TABLE_HEADER_ITEM_KEYWORDS):
                found["item_description"] = (x0, x1)
            elif any(k in t for k in _TABLE_HEADER_AMOUNT_KEYWORDS):
                found["supply_amount_krw"] = (x0, x1)
            elif any(k in t for k in _TABLE_HEADER_SPEC_KEYWORDS):
                found["spec"] = (x0, x1)
            elif any(k in t for k in _TABLE_HEADER_QTY_KEYWORDS):
                found["quantity"] = (x0, x1)
        if "item_description" in found and "supply_amount_krw" in found:
            header_cols, header_row_idx = found, i
            break
    if header_cols is None:
        return None

    for row in rows[header_row_idx + 1:]:
        item = _cell_for_column(row, header_cols["item_description"])
        amount_raw = _cell_for_column(row, header_cols["supply_amount_krw"])
        if not item or not amount_raw:
            continue
        result: dict = {
            "item_description": item,
            "supply_amount_krw": _parse_amount(amount_raw, field_label="공급가액"),
        }
        if "quantity" in header_cols:
            qty_raw = _cell_for_column(row, header_cols["quantity"])
            if qty_raw:
                qm = re.match(r"^([\d,]+)(\D*)$", qty_raw)
                if qm and qm.group(1):
                    result["quantity"] = _parse_amount(qm.group(1), field_label="수량")
                    if qm.group(2).strip():
                        result["quantity_unit"] = qm.group(2).strip()
        return result  # 첫 데이터 행만 사용 — _parse_tax_invoice_item_row()와 동일 정책
    return None


_MGMT_FEE_ELECTRIC_ITEM_PATTERN = re.compile(rf"{_label_pattern('전기료')}\s*[:\s]*([\d,]+)\s*원?")
MGMT_FEE_QUALITY_FLAG = "mgmt_fee_estimate"
_MGMT_FEE_GUIDANCE = (
    "전기료를 관리비 고지서에서 임시로 읽었어요 — 더 정확한 증빙을 원하시면 관리사무소에 "
    "사업자번호로 세금계산서 재발행을 요청해 주세요."
)


def _parse_management_fee_date(text: str) -> tuple[int, int]:
    for pattern in (
        rf"(\d{{4}}){_DATE_SEP}(\d{{1,2}})월?\s*분?",  # 2025-06, 2025.06분 등
        r"(\d{4})년\s*(\d{1,2})월",  # 2025년 6월분
    ):
        m = re.search(pattern, text)
        if m:
            return int(m.group(1)), int(m.group(2))
    raise DocumentParseError("관리비 고지서에서 청구월을 찾지 못했어요")


def parse_management_fee_bill(text: str) -> dict:
    """관리비 고지서 안의 전기료 항목을 electric_bill로 추출한다.

    관리비 고지서 자체는 한전이 발행한 게 아니라 부가세 공제 증빙이 안 되고, 안의
    전기료도 관리사무소가 안분·재산정한 간접값이라 1차 계량 데이터가 아니다(사용자
    제공 도메인 자료 근거) — 그래도 CLAUDE.md §6의 결손 월 업종평균 임시보정과 같은
    결로, 데이터 없음보다 나은 추정치로 쓰되 quality_flag로 낮은 신뢰도를 감사
    흔적에 남긴다. 실제 관리비 고지서 서식 샘플이 아직 없어 라벨 매칭은 잠정안이다
    (db/hometax_excel_parser.py 컬럼 별칭과 같은 사정 — 샘플 도착 시 교체).
    """
    m = _MGMT_FEE_ELECTRIC_ITEM_PATTERN.search(text)
    if not m:
        raise DocumentParseError(
            "관리비 고지서로 보여요 — 전기료 항목을 찾지 못했어요. 더 정확한 증빙을 "
            "원하시면 관리사무소에 사업자번호로 세금계산서 재발행을 요청해 주세요."
        )
    year, month = _parse_management_fee_date(text)
    return {
        "document_type": "electric_bill",
        "supplier_name": "관리사무소(관리비 고지서)",
        "item_description": "전기료 (관리비 안분 추정치)",
        "supply_amount_krw": _parse_amount(m.group(1), field_label="전기료"),
        "year": year,
        "month": month,
        "quality_flag": MGMT_FEE_QUALITY_FLAG,
        "guidance_message": _MGMT_FEE_GUIDANCE,
    }
