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
import calendar
import io
import logging
import re
from datetime import date

import pdfplumber

from db.document.contract_type import normalize_contract_type_class


# Chrome headless가 만든 일부 한글 PDF는 각 내장 폰트의 FontDescriptor에
# FontBBox를 넣지 않는다. pdfminer는 이 경우 안전하게 (0, 0, 0, 0)을 쓰면서도
# 폰트마다 같은 WARNING을 남긴다. 알려진 비치명 메시지만 정확히 거르고, 다른
# pdfminer 폰트 경고는 그대로 노출해 실제 파싱 문제를 숨기지 않는다.
_MISSING_FONT_BBOX_WARNING = (
    "Could not get FontBBox from font descriptor because "
    "None cannot be parsed as 4 floats"
)


class _MissingFontBBoxWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != _MISSING_FONT_BBOX_WARNING


logging.getLogger("pdfminer.pdffont").addFilter(_MissingFontBBoxWarningFilter())

DocumentType = str  # "tax_invoice" | "electric_bill" | "gas_bill"

# OCR 표 재구성 결과 하나의 셀: (x_start, x_end, text). document_ocr_extractor.py가
# 좌표 클러스터링으로 만들어 이 모듈의 표 파서(parse_tax_invoice_table_rows)에 넘긴다.
OcrCell = tuple[float, float, str]
OcrRow = list[OcrCell]

DOCUMENT_TYPE_LABEL = {
    "tax_invoice": "세금계산서",
    "water_bill": "상수도요금고지서",
    "electric_bill": "전기요금고지서",
    "gas_bill": "도시가스고지서",
}

_TITLE_TO_DOCUMENT_TYPE = {
    "전자세금계산서": "tax_invoice",
    # 실측(2026-08-18, data/fixtures/tax_invoices — 별지 제11호 국세청 표준 수기
    # 세금계산서): 제목이 "전자" 없이 "세 금 계 산 서"로만 찍힌다. "전자세금계산서"는
    # 이미 이 문자열을 포함하므로 아래 항목 하나로 두 서식 모두 커버된다.
    "세금계산서": "tax_invoice",
    "전기요금 고지서": "electric_bill",
    # 실측(2026-08-15, 실제 한전 고지서 사진 확인): "OO월분 전기요금 청구서" /
    # "OO월분 전기요금 청구 및 영수증(고지서)" — "전기요금 고지서"라는 정확한
    # 문구는 실물에 없었다. "전기요금 청구"까지만 매칭해 두 실제 서식을 모두 커버.
    "전기요금 청구": "electric_bill",
    "도시가스 요금고지서": "gas_bill",
    # 상수도 — 제목만 인식하고 파싱은 아직 없다(§2.5 범위 밖). 인식은 해두는 게 맞다:
    # 어휘에 없으면 수도고지서가 electric_bill로 오분류될 여지가 생기고, 그러면 수도
    # 사용량이 kWh 자리에 섞여 감축률을 오염시킨다. 인식만 해두면 _parse_by_type이
    # "아직 지원 안 함"으로 명확히 실패한다(실패 가시성 — CLAUDE.md §6).
    # 실물 제목은 "상하수도 요금 고지서"이고 공백 제거 부분일치라 "상수도요금"까지 같이
    # 덮으려면 두 항목이 필요하다("상하수도"에는 "상수도"가 부분문자열로 없다).
    "상하수도요금": "water_bill",
    "상수도요금": "water_bill",
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


def issue_date_str(year: int, month: int, day: int) -> str:
    """세금계산서처럼 정확한 일자가 문서에 찍혀 있는 경우 — ISO 문자열로.
    유효하지 않은 날짜(OCR 오독 등으로 day=31인데 2월인 경우 등)는 예외를
    던지지 않고 그 달의 마지막 날로 보정한다 — year/month는 이미 신뢰하고
    쓰고 있으니(날짜 파싱 실패로 문서 전체를 재업로드시키는 대신), day만
    문서가 속한 달 안으로 클램프."""
    day = min(day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def month_end_issue_date_str(year: int, month: int) -> str:
    """전기·도시가스 고지서처럼 원래 "그 달 청구서"라는 개념만 있고 특정 일자가
    없는 문서는 말일로 issue_date를 채운다(2026-08-19 사용자 확인) — "그달 청구서"
    라는 의미가 캘린더에서도 자연스럽게 전달되고, 월말 정산 관례와도 맞는다."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day).isoformat()


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


def parse_customer_number_from_cell_text(text: str) -> str | None:
    """셀 원문에서 고객번호(숫자·하이픈)만 뽑는다. 못 찾으면 None.

    db/document_llm_router.py 전용 공개 진입점 — parse_amount_from_cell_text와 같은 이유
    (LLM이 고른 셀의 원문을 항상 재파싱하고, LLM이 반환한 값을 직접 쓰지 않는다).
    라벨이 셀에 같이 들어온 경우("고객번호 0355-7712-90")도 숫자 부분만 남는다.
    """
    hit = _CUSTOMER_NUMBER_RE.search(text or "")
    return hit.group(1) if hit else None


def parse_year_month_from_cell_text(text: str) -> tuple[int, int, int | None] | None:
    """셀 원문에서 연/월(+가능하면 일)을 뽑는다. 구분자 앞뒤 공백은 `_DATE_SEP`과
    동일하게 허용.

    db/document_llm_router.py 전용 공개 진입점 — parse_amount_from_cell_text와
    같은 이유(LLM 응답의 값이 아니라 셀 원문을 항상 재파싱).

    실측(2026-08-17, 실제 한전 "전기요금청구 및 영수증"): 이 문서엔 -./로 구분된
    날짜가 단 한 군데도 없고 전부 "2021년 1월"/"2021년 01월 06일"처럼 년/월(/일)
    한글 구분자만 쓰였다 — LLM이 정확한 날짜 셀을 가리켜도 재파싱이 실패해 문서
    전체가 거부됐다. _parse_management_fee_date가 이미 쓰던 2번째 패턴과 동일하게
    년/월 표기도 시도한다.

    반환의 3번째 값(day)은 셀에 일자가 없으면 None — 예전엔 일자를 캡처해도
    버렸다(2026-08-19 실측: 탄소 캘린더가 항상 비어 보이는 원인 중 하나로 발견).
    호출부(document_llm_router.py)가 day=None이면 말일로 issue_date를 채운다."""
    m = re.search(rf"(\d{{4}}){_DATE_SEP}(\d{{2}})(?:{_DATE_SEP}(\d{{2}}))?", text)
    if m:
        day = int(m.group(3)) if m.group(3) else None
        return int(m.group(1)), int(m.group(2)), day
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?", text)
    if m:
        day = int(m.group(3)) if m.group(3) else None
        return int(m.group(1)), int(m.group(2)), day
    return None


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


_MONEY_WITH_UNIT_RE = re.compile(r"(\d[\d,]*)\s*원")
_MONEY_BARE_RE = re.compile(r"(\d[\d,]*)")


def _amount_near_label(text: str, label: str, *, field_label: str) -> str:
    """금액 라벨 주변에서 금액 토큰을 찾는다 — 라벨과 값이 같은 줄에 없는 서식 대응.

    버그 수정(2026-08-24): 종전엔 `_line_value`로 "라벨 뒤 아무 텍스트"를 잡고
    `_parse_amount`가 숫자만 걸러냈다. 그런데 실제 전기고지서 서식은 pdfplumber 추출에서
    금액이 라벨보다 **앞줄**에 온다:

        부가가치세 및 전력기금 14,616 원
        197,316 원              ← 값
        이번달 청구금액          ← 라벨
        납기일: 2024-02-25 · 미납 시 연체료가 부과될 수 있습니다

    그래서 라벨 다음 줄인 납기일 줄이 값으로 잡히고, `_parse_amount`가 숫자만 남겨
    `20240225`를 금액으로 저장했다. 공유 DB에 이렇게 오염된 전표가 7건 있었다
    (`20,260,825` = 2026-08-25). 모든 전기고지서 fixture(C001·S001·S002)가 같은
    레이아웃이라 텍스트 레이어 경로를 타는 모든 업로드가 영향을 받았다.

    탐색 순서 — 실제 서식 두 종류를 모두 커버하되 날짜를 금액으로 오인하지 않는다:
      1. 라벨 뒤 같은 줄 ("청구금액 9,240원", "청구금액(원) 1,234" — 실물 고지서 서식)
      2. 라벨 앞 같은 줄 ("197,316 원 이번달 청구금액")
      3. 바로 앞 줄 (위 fixture 서식)
    2·3순위는 **"원" 단위가 붙은 토큰만** 인정한다 — 단위 없는 숫자까지 허용하면
    사용량(kWh)·계약전력 같은 인접 수치를 금액으로 집어올 수 있다. 1순위는 기존 동작을
    유지하기 위해 단위 없는 숫자도 허용한다(라벨 바로 뒤라 오인 위험이 낮다).
    """
    lines = text.split("\n")
    label_re = re.compile(_label_pattern(label))
    for i, line in enumerate(lines):
        m = label_re.search(line)
        if m is None:
            continue
        if any(kw in line[: m.start()] for kw in _FORECAST_PREFIX_KEYWORDS):
            raise DocumentParseError(
                f"실제 {field_label}이 아니라 예상·추정치로 보여요 — 정식 청구서로 다시 올려 주세요"
            )
        after = line[m.end():]
        hit = _MONEY_WITH_UNIT_RE.search(after) or _MONEY_BARE_RE.search(after)
        if hit:
            return hit.group(1)
        hit = _MONEY_WITH_UNIT_RE.search(line[: m.start()])
        if hit:
            return hit.group(1)
        if i > 0:
            hit = _MONEY_WITH_UNIT_RE.search(lines[i - 1])
            if hit:
                return hit.group(1)
    raise DocumentParseError(f"{field_label} 항목을 찾지 못했어요")


# 계약종별 값 — "일반용(을)", "산업용(을) 고압A", "주택용전력"처럼 한글 어절 + 괄호·영숫자.
# 다음 라벨(고객번호·사용기간 등)까지 삼키지 않으려면 값의 모양을 제한해야 한다: 실측
# 서식이 "고객번호 0355-7712-90 계약종별 일반용(을)"처럼 한 줄에 라벨-값 쌍을 여러 개
# 늘어놓기 때문이다(줄 끝까지 잡으면 뒷 라벨이 값에 붙는다).
_CONTRACT_TYPE_VALUE_RE = re.compile(r"([가-힣]+(?:\([가-힣]\))?(?:\s*[A-Za-z0-9]+)?)")
# 고객번호 — 숫자와 하이픈만. "0355-7712-90" 같은 한전 표기.
_CUSTOMER_NUMBER_RE = re.compile(r"(\d[\d-]*\d)")


def _optional_token_after_label(text: str, label: str, value_re: re.Pattern) -> str | None:
    """라벨 뒤에서 `value_re` 모양의 토큰만 뽑는다. 없으면 None.

    계약종별·고객번호처럼 **나중에 추가된 보조 필드**용이다. 금액·날짜는 없으면 그 문서로
    할 수 있는 게 없어 DocumentParseError가 맞지만, 이 두 필드는 없어도 배출량 계산이
    그대로 되므로 기존 업로드를 회귀시키면 안 된다(사용량 quantity 처리와 같은 원칙).

    줄 끝까지 잡지 않고 값 모양으로 끊는 이유: 실제 서식이 한 줄에 라벨-값 쌍을 여러 개
    늘어놓는다("고객번호 0355-7712-90 계약종별 일반용(을)"). 줄 단위로 잡으면 고객번호에
    "0355-7712-90 계약종별 일반용(을)"이 통째로 들어간다(2026-08-24 실측).

    라벨이 있어도 값 모양이 안 맞으면 None을 준다 — 판별은 "미확인"으로 흘러 HITL 재확인
    대상이 되고, 값을 지어내지 않는다(실패 가시성).
    """
    # 라벨 뒤 구분자(콜론)를 라벨 쪽에서 먹는다. 이게 없으면 값이 ": 산업용(을) 고압A"로
    # 시작해 value_re.match()가 0번 위치에서 콜론에 걸려 전부 실패한다 — 실제로 구미정밀
    # 전기고지서("청구월: 2025-01 계약종별: 산업용(을) 고압A")가 이 때문에 계약종별·고객번호
    # 둘 다 못 읽혀 business_scale_hint가 "미확인"으로 떨어져 있었다(2026-08-25 실측).
    # S001·S002 fixture는 공백 구분("계약종별 일반용(을)")이라 이 결함이 안 드러났다.
    # 전각 콜론(：)도 함께 받는다 — OCR이 한글 문서에서 실제로 뱉는 문자다.
    label_re = re.compile(_label_pattern(label) + r"\s*[:：]?")
    for line in text.split("\n"):
        m = label_re.search(line)
        if m is None:
            continue
        hit = value_re.match(line[m.end():].strip())
        if hit:
            return hit.group(1).strip()
    return None


def _parse_by_type(document_type: DocumentType, text: str) -> dict:
    if document_type == "electric_bill":
        return _parse_electric_bill(text)
    if document_type == "gas_bill":
        return _parse_gas_bill(text)
    if document_type == "tax_invoice":
        return _parse_tax_invoice(text)
    if document_type == "water_bill":
        # 어휘·테이블(water_bills, 0031)은 있지만 파서가 아직 없다. 내부 문구
        # ("알 수 없는 문서종류")로 떨어지면 사장님에게 버그처럼 보이므로 상태를
        # 그대로 알린다 — 없는 기능을 되는 척하지 않는다(data-plan §3.3).
        raise DocumentParseError(
            "상수도요금고지서는 아직 읽지 못해요 — 전기요금고지서만 올려 주세요"
        )
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
    # 실측(2026-08-17, "전기요금청구 및 영수증" 서식): "분" 없이 "OO고객님의 2021년
    # 1월"처럼만 찍힌 경우도 있었다 — "분"을 필수로 요구하면 이런 서식은 전부 실패
    # 한다. 선택적으로 바꿔 둘 다 커버한다.
    date_m = re.search(
        rf"{_label_pattern('청구월')}\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}})", text
    ) or re.search(r"(\d{4})년\s*(\d{1,2})월분?", text)
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
        # 실측: "사용량(kWh)" 인라인 라벨 대신 "당월 사용량 | 전월 사용량 | 전월 대비 |
        # 계약전력" 표 헤더 뒤에 값 행("2,450 kWh | 2,400 kWh | ...")이 따로 오는
        # 서식도 있다(한전 고지서 "사용량 내역" 표 — 라벨과 값이 같은 줄에 붙어있지
        # 않음). "당월 사용량" 헤더 뒤 첫 "숫자 kWh" 토큰을 값으로 삼는다 — 헤더 행
        # 자체엔 숫자가 없으므로 값 행의 첫 kWh 수치까지 건너뛰게 된다.
        # 실측(2026-08-18, 같은 fixture의 JPG 경로만 PaddleOCR로 재구성 시): "당월
        # 사용량"이 "당월사용량"처럼 띄어쓰기 없이 붙어 나왔다 — 라벨 리터럴에 공백을
        # 그대로 넣으면 _label_pattern이 그 자리에서만 공백을 필수로 요구해(다른 글자
        # 사이는 \s*로 선택적인데, 리터럴 공백 문자 자체는 최소 1개를 강제) 오히려 이
        # 붙어 나온 경우를 못 잡았다. 라벨에서 공백을 빼 그 위치도 다른 글자 사이와
        # 똑같이 선택적(\s*)이 되게 한다 — "당월 사용량"·"당월사용량" 둘 다 매칭.
        table_m = re.search(
            _label_pattern("당월사용량") + r"[\s\S]{0,200}?(\d[\d,]*)\s*kWh", text
        )
        if table_m:
            quantity = _parse_amount(table_m.group(1), field_label="사용량")
    # 실측: "청구금액(원)"이 아니라 "청구금액"(단위 없이) 바로 뒤에 금액이 온다
    # ("청구금액 9,240원") — "(원)"을 선택적으로 바꿔 둘 다 허용.
    amount = _parse_amount(
        _amount_near_label(text, "청구금액", field_label="청구금액"),
        field_label="청구금액",
    )
    bill_year, bill_month = int(date_m.group(1)), int(date_m.group(2))
    result = {
        "supplier_name": "한국전력공사",
        "item_description": "전기요금 (산업용 을)",
        "supply_amount_krw": amount,
        "year": bill_year,
        "month": bill_month,
        # 전기고지서는 "그 달 청구서"일 뿐 특정 일자가 없다 — 말일로 채운다
        # (2026-08-19 사용자 확인, month_end_issue_date_str 참고).
        "issue_date": month_end_issue_date_str(bill_year, bill_month),
    }
    # 계약종별·고객번호 — 소상공인 탄소중립포인트 트랙용(data-plan.md §7.1, §6.3).
    # 둘 다 못 찾아도 파싱은 성공시킨다: 금액·날짜가 멀쩡한 문서를 이 두 필드 때문에
    # 거부하면 기존 업로드가 회귀한다(사용량 처리와 같은 원칙).
    #
    # 위 item_description이 항상 고정 문구 "전기요금 (산업용 을)"인 점에 주의 —
    # 그건 파서 기본값이지 계약종별이 아니다. 그래서 계약종별을 별도로 읽는다.
    # 이 값을 item_description으로 대체하려 하지 말 것(전 기업이 산업용으로 보인다).
    contract_type = _optional_token_after_label(text, "계약종별", _CONTRACT_TYPE_VALUE_RE)
    if contract_type is not None:
        result["contract_type"] = contract_type
        result["contract_type_class"] = normalize_contract_type_class(contract_type)
    customer_number = _optional_token_after_label(text, "고객번호", _CUSTOMER_NUMBER_RE)
    if customer_number is not None:
        result["customer_number"] = customer_number
    if quantity is not None:
        result["quantity"] = quantity
        result["quantity_unit"] = "kWh"
    elif "kWh" in text:
        # "사용량 자체가 없는 서식"과 "있는데 정규식이 못 읽은 경우"는 그대로 두면
        # 둘 다 quantity=None으로 똑같이 보여 구분이 안 된다 — 후자는 파서 결함이지
        # 진짜 데이터 갭이 아니므로, 텍스트에 kWh 흔적이 있는데도 못 뽑았으면 다르게
        # 표시한다(관리비 고지서 quality_flag와 같은 결). calc_engine의 HITL "계산
        # 실패 사유"는 순수 함수 경계상 문서 원문을 모르므로 그대로 두고, 대신
        # source_documents.verification_status·업로드 응답 guidance_message로
        # "이건 데이터 갭이 아니라 파서 버그일 수 있다"는 감사 흔적을 남긴다.
        result["quality_flag"] = USAGE_UNRECOGNIZED_QUALITY_FLAG
        result["guidance_message"] = _USAGE_UNRECOGNIZED_GUIDANCE
    return result


def _parse_gas_bill(text: str) -> dict:
    # 전기요금 고지서에서 실측으로 확인된 것과 같은 종류의 편차를 도시가스 고지서도
    # 겪을 가능성이 높다고 보고 선제 적용한다(도시가스 실물 샘플은 아직 미확보 —
    # docs/document-ocr-taxonomy.md 참고, 그래서 세 군데 모두 "선택"처럼 완화하되
    # 기존 라벨 매칭도 그대로 유지해 실측 전 추측으로 기존 동작을 깨지 않는다).
    date_m = re.search(
        rf"{_label_pattern('사용월')}\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}})", text
    ) or re.search(r"(\d{4})년\s*(\d{1,2})월분?", text)
    if not date_m:
        raise DocumentParseError("사용월을 찾지 못했어요")
    # 전기요금과 같은 원칙 — 사용량 라벨을 못 찾아도 물량 없이 파싱 자체는 성공시킨다
    # (계산 엔진이 어차피 전기·도시가스는 수량 없으면 금액 역산 대신 사람검토로
    # 보낸다 — db/calc_engine.py::_QUANTITY_ONLY). 못 찾았다고 문서 전체를 거부하면
    # 날짜·금액은 멀쩡히 읽었는데도 재업로드를 요구하게 된다.
    quantity = None
    try:
        quantity = _parse_amount(
            _line_value(text, _label_pattern("사용량(m³)"), field_label="사용량"), field_label="사용량"
        )
    except DocumentParseError:
        pass
    amount = _parse_amount(
        _amount_near_label(text, "청구금액", field_label="청구금액"),
        field_label="청구금액",
    )
    bill_year, bill_month = int(date_m.group(1)), int(date_m.group(2))
    result = {
        "supplier_name": "도시가스",
        "item_description": "도시가스",
        "supply_amount_krw": amount,
        "year": bill_year,
        "month": bill_month,
        # 도시가스 고지서도 전기고지서와 동일하게 말일로 채운다.
        "issue_date": month_end_issue_date_str(bill_year, bill_month),
    }
    if quantity is not None:
        result["quantity"] = quantity
        result["quantity_unit"] = "m3"
    return result


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
    날짜·공급자는 이 함수로 공유해서 쓴다).

    "작성일자"는 연·월·일까지 정규식이 이미 캡처하는데, 예전엔 year/month만 쓰고
    day를 버려 issue_date가 항상 null로 남는 버그가 있었다(2026-08-19 실측 —
    탄소 캘린더에 날짜별 이벤트가 하나도 안 뜨는 원인으로 발견). day도 결과에
    담아 호출부(api/document_ingestion.py)가 Voucher.issue_date를 정확히
    채울 수 있게 한다."""
    date_m = re.search(
        rf"(?:{_label_pattern('작성일자')}|{_label_pattern('발급일자')})"
        rf"\s*:\s*(\d{{4}}){_DATE_SEP}(\d{{2}}){_DATE_SEP}(\d{{2}})",
        text,
    )
    if date_m:
        year, month, day = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
    else:
        # 실측(2026-08-18, data/fixtures/tax_invoices — 별지 제11호 국세청 표준
        # 수기 세금계산서): "작성일자:" 콜론이 아니라 "작성" 헤더 행 아래 데이터행에
        # 연(2자리)·월·일이 공백으로 구분돼 찍힌다("작 성 공급가액 세액 비고" 다음
        # 줄 "25 1 8 백 십 억 ..."). 뒤따르는 자릿값 라벨("백"·"십"...)은 금액
        # 자릿수에 따라 위치가 달라져(실측 확인) 앵커로 못 쓰므로, 다음 줄 맨 앞
        # 숫자 3개(연·월·일)만 읽는다.
        table_date_m = re.search(
            rf"{_label_pattern('작성')}[^\n]*\n\s*(\d{{1,2}})\s+(\d{{1,2}})\s+(\d{{1,2}})\b",
            text,
        )
        if not table_date_m:
            raise DocumentParseError("작성일자를 찾지 못했어요")
        year = 2000 + int(table_date_m.group(1))
        month = int(table_date_m.group(2))
        day = int(table_date_m.group(3))
    return {
        "supplier_name": find_supplier_name_best_effort(text),
        "year": year,
        "month": month,
        # 버그 수정(2026-08-19): 두 분기 모두 정규식이 일(day)까지 이미 캡처하는데
        # 여태 dict에 안 넣어서 버렸다 — api/document_ingestion.py::_parse_issue_date가
        # 기대하는 "issue_date" 키가 OCR 업로드 경로에선 항상 None이라 Voucher.
        # issue_date가 통째로 비어 있었다(엑셀 업로드 경로는 parse_hometax_excel이
        # 별도로 issue_date를 채워 이 버그의 영향을 안 받았음).
        "issue_date": issue_date_str(year, month, day),
    }


# 규격(2번째 컬럼) 자리에 한글 음절이 있으면 실제 규격값이 아니라 품목명이 공백
# 때문에 잘못 잘려 들어온 것으로 본다 — 실제 규격은 "-"·빈값·영문 단위 코드가
# 대부분이라("EA", 모델코드 등) 완성형 한글 단어가 나오는 경우는 거의 없다.
_HANGUL_SYLLABLE = re.compile(r"[가-힣]")


# 실측(2026-08-18, data/fixtures/tax_invoices — 별지 제11호 국세청 표준 수기
# 세금계산서): 품목행이 "월 일 품목 규격 수량 단가 공급가액 세액 [비고]" 9칼럼이다
# (예: "1 8 경유 지게차용 100 1,421 142,100 14,210 지게차 연료"). 규격에 "지게차용"
# 처럼 정상적인 한글 단어가 들어가므로 아래 구형 5토큰 포맷 전용 _HANGUL_SYLLABLE
# 방어 로직은 적용하지 않는다 — 대신 앞뒤 숫자 앵커(월·일·수량·단가·공급가액·세액)
# 로 칼럼 위치가 이미 확정되어 모호함이 없다. 토큰 구분에 \s+ 대신 [ \t]+를 써서
# 줄바꿈을 건너뛰어 다른 행과 잘못 이어붙는 걸 막는다.
_OFFICIAL_FORM_ITEM_ROW_RE = re.compile(
    r"^\d{1,2}[ \t]+\d{1,2}[ \t]+(\S+)[ \t]+(\S+)[ \t]+([\d,]+|-)[ \t]+(?:[\d,]+|-)[ \t]+([\d,]+)[ \t]+[\d,]+(?:[ \t]+.*)?$",
    re.MULTILINE,
)


def _parse_tax_invoice_item_row(text: str) -> dict:
    """품목행 파싱 — 두 서식을 순서대로 시도한다.

    1) 별지 제11호 서식(위 _OFFICIAL_FORM_ITEM_ROW_RE, 지금의 기준 fixture).
       수량에 단위(L 등)가 안 찍혀 있어 quantity만 채우고 quantity_unit은
       비워 둔다 — db/calc_engine.py::compute_emission의
       `item.quantity_unit or factor["unit"]`가 배출계수 테이블 단위로 자동
       보완하므로 여기서 단위를 지어낼 필요가 없다(CLAUDE.md 원칙1).
    2) 구형 5토큰 한 줄 포맷(scripts/generate_upload_docs.py 등, 아래 기존 로직).
    """
    official_m = _OFFICIAL_FORM_ITEM_ROW_RE.search(text)
    if official_m:
        result = {
            "item_description": official_m.group(1).strip(),
            "supply_amount_krw": _parse_amount(official_m.group(4), field_label="공급가액"),
        }
        if official_m.group(3) != "-":
            result["quantity"] = _parse_amount(official_m.group(3), field_label="수량")
        return result

    # 품목 행: "경유 L 301L 1,400 420,833" — 품목명, 규격, 수량+단위(예: "301L"), 단가(원),
    # 공급가액(원). 마지막 두 컬럼만 순수 숫자/콤마라 이 패턴으로 헤더 행("품목명 규격 ...
    # 공급가액(원)")과 구분된다(헤더는 괄호·한글이 섞여 있어 [\d,]+로 안 끝난다). 한 줄
    # 문자열에 의존하는 방식이라 OCR 표 사진에는 안 통할 수 있다 — 그 경우
    # parse_tax_invoice_table_rows()(좌표 기반)를 대신 쓴다.
    #
    # 실측(2026-08-17, 기존 테스트 픽스처로 재현): 품목명이 "유류대금 외1종"처럼
    # 공백을 포함하면 이 정규식은 공백 앞까지만("유류대금") 캡처하고 나머지("외1종")를
    # 규격 컬럼으로 흘려보낸다 — 에러 없이 조용히 성공해서 발견이 늦었다. "동절기
    # 난방유"였다면 실제 연료 키워드("난방유")가 통째로 사라져 분류 오류로 이어질
    # 수 있었다. 정규식만으로는 공백이 품목명 내부 띄어쓰기인지 컬럼 구분인지 구별할
    # 수 없어(좌표 정보가 없는 텍스트 레이어 경로 특유의 한계) 확실히 못 나눌 바엔
    # 명확히 실패시켜 OCR 좌표매칭·LLM 라우터(둘 다 셀 단위라 이 모호함이 없음)로
    # 넘긴다 — 틀린 값을 조용히 저장하는 것보다 실패 가시성이 우선.
    row_m = re.search(r"^(\S+)\s+(\S+)\s+(\S+)\s+[\d,]+\s+([\d,]+)\s*$", text, re.MULTILINE)
    if not row_m:
        raise DocumentParseError("품목·공급가액 행을 찾지 못했어요")
    if _HANGUL_SYLLABLE.search(row_m.group(2)):
        raise DocumentParseError("품목명에 공백이 있어 한 줄로는 정확히 못 나눴어요")
    result = {
        "item_description": row_m.group(1).strip(),
        "supply_amount_krw": _parse_amount(row_m.group(4), field_label="공급가액"),
    }
    # 세금계산서는 물량이 안 찍힌 경우("-" 등)가 더 흔하다 — 이때는 quantity 필드
    # 자체를 안 넣어 기존 금액÷단가 환산 경로를 그대로 탄다.
    qty_m = re.match(r"^([\d,]+)(\D+)$", row_m.group(3))
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
# "작성"만: 별지 제11호 서식은 헤더 셀이 "작성일자"가 아니라 "작성" 2글자뿐이다
# (실측 2026-08-18, data/fixtures/tax_invoices) — 안전망으로 추가.
_TABLE_HEADER_DATE_KEYWORDS = ("작성일자", "발급일자", "작성")
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


_SHORT_NUMBER_RE = re.compile(r"^\d{1,2}$")


def _find_split_date_in_row(row: OcrRow, left_bound: float, right_bound: float) -> tuple[int, int, int] | None:
    """연(2자리)·월·일이 한 셀이 아니라 칸마다 따로 찍힌 표(실측 2026-08-18, 별지
    제11호 국세청 표준 세금계산서 사진 — "작성" 헤더 밑에 "25 | 5 | 8"이 각각
    독립된 박스로 인쇄됨)에서 좌표 기반으로 찾는다. parse_tax_invoice_header()의
    텍스트 기반 폴백("작성" 다음 줄 맨 앞 숫자 3개)과 같은 발상을 OCR 좌표 셀에
    적용한 버전 — date_col과 그다음 헤더 컬럼(공급가액 등) 사이 구간에서 순수
    숫자 1~2자리 셀만 x좌표 순으로 모아 연·월로 쓴다.

    일(day)은 세 번째 후보가 있고 월과의 x간격이 연-월 간격의 3배 이내일 때만
    쓴다 — 실측(2026-08-19, ocr_retry_region() 크롭 재인식 결과)에서 세 번째
    숫자가 실제로는 한참 떨어진 금액 자릿수(예: 세액 칸의 낱자리)였던 사례가
    있었다. 신뢰 못 할 값을 day로 잘못 주워 쓰느니 1일로 둔다(issue_date_str가
    어차피 유효 범위로 클램프하므로 문서 전체를 실패시키는 것보다 낫다)."""
    candidates = sorted(
        (x0, text.strip())
        for x0, x1, text in row
        if left_bound - _TABLE_COLUMN_MATCH_TOLERANCE <= x0 < right_bound
        and _SHORT_NUMBER_RE.match(text.strip())
    )
    if len(candidates) < 2:
        return None
    year_x, year_raw = candidates[0]
    month_x, month_raw = candidates[1]
    day = 1
    if len(candidates) >= 3:
        day_x, day_raw = candidates[2]
        year_month_gap = month_x - year_x
        if year_month_gap > 0 and (day_x - month_x) <= year_month_gap * 3:
            day = int(day_raw)
    return 2000 + int(year_raw), int(month_raw), day


def parse_tax_invoice_date_crop_rows(rows: list[OcrRow]) -> tuple[int, int, int] | None:
    """find_tax_invoice_date_crop_box()로 잘라낸 크롭의 OCR 결과 전용 날짜 파서.

    parse_tax_invoice_date_table()과 달리 "작성"/"작성일자" 헤더 키워드를 크롭
    안에서 다시 찾지 않는다 — 실측(2026-08-19) 확인: 이 크롭은 애초에 헤더를 이미
    찾은 뒤(find_tax_invoice_date_crop_box)에만 만들어지는데, 크롭 상단 경계
    바로 위에서 헤더 텍스트 자체가 잘리거나 이 작은 이미지 안에서는 재인식되지
    않는 경우가 있었다 — 값(연/월/일 분리 칸)은 confidence 0.98+로 정확히
    읽었는데도 헤더 재탐색을 요구하면 매번 실패했다. 크롭 자체가 이미 날짜
    영역으로 좁혀져 있다는 전제 하에, 각 행에서 곧바로 4자리 연도 한 셀 또는
    2자리 연도 분리 셀(_find_split_date_in_row)을 순서대로 시도한다."""
    for row in rows:
        for _x0, _x1, text in row:
            m = re.search(rf"(\d{{4}}){_DATE_SEP}(\d{{2}}){_DATE_SEP}(\d{{2}})", text)
            if m:
                return int(m.group(1)), int(m.group(2)), int(m.group(3))
        split = _find_split_date_in_row(row, 0.0, float("inf"))
        if split is not None:
            return split
    return None


def parse_tax_invoice_date_table(rows: list[OcrRow]) -> tuple[int, int, int] | None:
    """세금계산서 날짜가 "작성일자:" 콜론 형식이 아니라 헤더행/데이터행 표 구조일
    때 좌표 기반으로 찾는다 — 실측 확인(2026-08-16, 사용자 제공 합성 세금계산서
    사진): 실제 국세청 표준 세금계산서 서식은 "작성일자·공급가액·세액·비고" 헤더
    행 아래 값이 오는 표라서, parse_tax_invoice_header()의 콜론 기반 정규식이
    통하지 않는다. parse_tax_invoice_table_rows()와 같은 헤더행 탐지 방식이지만
    "품목" 대신 "작성일자"/"발급일자"를 찾는다 — 같은 문서 안에 공급가액 컬럼을
    가진 표가 두 개(작성일자 요약행, 품목행) 있을 수 있어 헤더 판별 키워드를
    다르게 둔다(둘을 혼동하지 않음). 헤더나 값을 못 찾으면 None(예외 대신 —
    호출부가 다른 경로를 계속 시도할 수 있게).

    반환은 (year, month, day) — 예전엔 day를 버리고 (year, month)만
    반환해 issue_date가 항상 null로 남는 버그가 있었다(2026-08-19 실측).

    4자리 연도 한 셀(예: "2025-01-11") 매칭이 실패하면 _find_split_date_in_row로
    2자리 연도·칸별 분리 서식도 시도한다(실측 2026-08-18 — 별지 제11호 서식은
    연·월·일이 각각 별도 칸)."""
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
        # 연/월/일 분리 칸 탐색 범위의 오른쪽 경계 — 같은 헤더행에서 date_col
        # 오른쪽에 있는 다음 컬럼(공급가액 등) 시작 x좌표까지만 본다.
        next_col_starts = [x0 for x0, _x1, _text in row if x0 > date_col[1]]
        right_bound = min(next_col_starts) if next_col_starts else float("inf")
        for data_row in rows[i + 1 : i + 3]:  # 바로 아래 한두 행 안에서 값을 찾는다
            cell = _cell_for_column(data_row, date_col)
            if cell:
                m = re.search(rf"(\d{{4}}){_DATE_SEP}(\d{{2}}){_DATE_SEP}(\d{{2}})", cell)
                if m:
                    # 버그 수정(2026-08-19): 일(day)까지 캡처해놓고 여태 버렸다 — 아래
                    # parse_tax_invoice_header()와 같은 결.
                    return int(m.group(1)), int(m.group(2)), int(m.group(3))
            split = _find_split_date_in_row(data_row, date_col[0], right_bound)
            if split is not None:
                return split
        return None  # 헤더는 찾았는데 값을 못 찾으면 더 이상 시도 안 함
    return None


def find_tax_invoice_date_crop_box(
    boxes: list[tuple[float, float, float, float, str]],
) -> tuple[float, float, float, float] | None:
    """작성/작성일자/발급일자 헤더 박스 좌표로, 날짜 값이 있을 것으로 예상되는 영역의
    (x0, y0, x1, y1)를 원본 이미지 픽셀 좌표계로 계산한다 — db/document_ocr_extractor.py
    ::ocr_retry_region()에 넘길 크롭 박스를 만드는 용도(실측 2026-08-19: 전체 페이지
    인식에서 이 헤더 밑 격자 숫자가 뭉개져 parse_tax_invoice_date_table()이 값을 못
    찾을 때만 부르는 2차 시도).

    boxes는 클러스터링 전 원시 박스 목록(db.document_ocr_extractor.OcrResult.boxes,
    (x0, x1, y0, y1, text) 튜플). 헤더를 못 찾으면 None(예외 대신 — 호출부가 크롭
    재시도 자체를 건너뛸 수 있게).

    가로 오른쪽 경계는 같은 행(헤더와 y범위가 겹치는)에 있는 다음 컬럼 헤더
    ("공급가액" 등)의 시작 x좌표로 잡는다 — parse_tax_invoice_date_table()의
    right_bound 계산과 같은 원칙. 고정 배율(예전엔 헤더 행 높이의 40배)은
    문서마다 컬럼 폭이 달라 너무 넓어질 수 있다 — 실측(2026-08-20)으로 실제
    사고가 남: "작성" 칸 값이 뭉개져 못 읽히자, 크롭이 한참 오른쪽 "세액" 칸까지
    걸쳐 있던 탓에 그 칸의 낱자리 숫자("7"/"8")를 연/월로 잘못 주워 "2007년
    8월"이라는 조용한 오답을 냈다(금액은 맞고 날짜만 틀려 실패로도 안 걸림 —
    CLAUDE.md 실패 가시성 원칙 위반). 같은 행에서 다음 컬럼 헤더를 못 찾으면
    (표 구조가 달라 헤더 텍스트 인식이 아예 안 된 경우 등) 헤더 행 높이의 15배로
    폴백한다(예전 40배보다 훨씬 보수적 — 실측: 진짜 날짜 값은 크롭 시작점에서
    row_height의 1.8배 이내에 있었다).

    세로는 헤더 행 높이의 절반 위, 1.5배 아래까지만 본다 — 실측(2026-08-19)으로 여백을
    더 넓혀(2~4배) 봤더니 오히려 바로 아래 있는 품목행 표까지 크롭에 딸려 들어와,
    server 감지 모델이 크고 깨끗한 품목행 텍스트에 밀려 정작 찾는 작은 날짜 숫자를
    더 못 찾는 역효과가 났다. 이 서식은 "작성" 요약행과 "품목" 표 헤더가 세로로
    빽빽하게 붙어 있어(별지 제11호 서식 특징) 여백을 넓힐수록 손해라는 뜻 — 1.5배가
    실측으로 "25"/"5"/"8"을 confidence 0.98+로 정확히 찾아낸 값."""
    header = next(
        (b for b in boxes if any(kw in _strip_ws(b[4]) for kw in _TABLE_HEADER_DATE_KEYWORDS)),
        None,
    )
    if header is None:
        return None
    hx0, _hx1, hy0, hy1, _text = header
    row_height = max(hy1 - hy0, 1.0)

    def _same_row(b) -> bool:
        b_center = (b[2] + b[3]) / 2
        h_center = (hy0 + hy1) / 2
        return abs(b_center - h_center) <= row_height

    next_col_starts = [
        b[0]
        for b in boxes
        if b[0] > hx0 and _same_row(b) and any(kw in _strip_ws(b[4]) for kw in _TABLE_HEADER_AMOUNT_KEYWORDS)
    ]
    x1 = min(next_col_starts) if next_col_starts else hx0 + row_height * 15.0

    x0 = max(0.0, hx0 - row_height)
    y0 = max(0.0, hy0 - row_height * 0.5)
    y1 = hy1 + row_height * 1.5
    return (x0, y0, x1, y1)


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


USAGE_UNRECOGNIZED_QUALITY_FLAG = "usage_unrecognized"
_USAGE_UNRECOGNIZED_GUIDANCE = (
    "고지서에 사용량(kWh) 표시가 있는 것 같은데 자동으로 읽지 못했어요 — "
    "개발팀이 서식을 확인해야 해요."
)

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
