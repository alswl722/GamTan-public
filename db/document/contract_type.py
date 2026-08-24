"""전기요금 고지서의 계약종별 → 정규화 클래스.

정본: docs/small-business-green-supply-data-plan.md §7.1, §6.1.

소상공인 탄소중립포인트(에너지 분야)는 **가정용·상업용 전기만 대상**이고 산업용 전기를
쓰는 제조공장은 원천 제외된다(§6.2). 그 판별의 유일한 근거가 고지서의 계약종별이라,
원문 문자열을 4종으로 정규화해 `source_documents.contract_type_class`에 저장한다.

설계 메모 — 왜 부분일치인가:
    실물 표기가 제도 문서의 명칭과 정확히 일치하지 않는다. 확인된 것만 해도
    `일반용(을)`(S001 fixture), `주택용전력`(실물 고지서 OCR, 2026-08-17 업로드분)처럼
    접미사·괄호·공백이 제각각이다. data-plan §6.1이 적어둔 `IN (주택용, 일반용, ...)`
    완전일치 목록으로는 `주택용전력`을 놓친다. 그래서 공백을 제거한 뒤 핵심 어절
    (산업용/일반용/주택용)의 **부분일치**로 판정한다.

    §15.2("실제 한전 고지서 표기 확인")가 아직 안 끝났으므로 이 매핑은 확정이 아니다.
    실물 표기가 더 확인되면 아래 표만 늘린다.

모르는 표기는 지어내지 않고 "unknown"으로 둔다 — 농사용·교육용·심야전력·가로등처럼
4종에 안 맞는 실제 계약종별이 존재하고, 이들을 억지로 commercial로 밀어 넣으면 자격이
없는 사업자에게 신청 안내가 가게 된다. unknown은 §6.1의 HITL 재확인 요청으로 이어진다.
"""
import re
from typing import Literal

ContractTypeClass = Literal["industrial", "commercial", "residential", "unknown"]

# 판정 순서가 있는 표 — 앞에서부터 먼저 맞는 것을 쓴다. 지금은 어절이 서로 겹치지
# 않아 순서가 결과를 바꾸지 않지만, 표기가 늘어나면(예: "산업용일반") 순서가 의미를
# 갖게 되므로 리스트로 둔다.
_CONTRACT_TYPE_KEYWORDS: tuple[tuple[str, ContractTypeClass], ...] = (
    ("산업용", "industrial"),
    ("일반용", "commercial"),
    ("주택용", "residential"),
)

_WS_RE = re.compile(r"\s+")


def normalize_contract_type_class(raw: str | None) -> ContractTypeClass:
    """계약종별 원문 → industrial | commercial | residential | unknown.

    >>> normalize_contract_type_class("산업용(을) 고압A")
    'industrial'
    >>> normalize_contract_type_class("일반용(을)")
    'commercial'
    >>> normalize_contract_type_class("주택용전력")
    'residential'
    >>> normalize_contract_type_class("농사용(을)")
    'unknown'
    >>> normalize_contract_type_class(None)
    'unknown'
    """
    if not raw:
        return "unknown"
    compact = _WS_RE.sub("", raw)
    for keyword, cls in _CONTRACT_TYPE_KEYWORDS:
        if keyword in compact:
            return cls
    return "unknown"
