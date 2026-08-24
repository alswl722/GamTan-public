"""소상공인 탄소중립포인트 트랙 — 판별·자격 판정.

정본: docs/small-business-green-supply-data-plan.md §5·§6.1(판별), §6.2(자격).

이 모듈의 함수는 전부 **조회 시점에 계산하는 함수**다. 판별 결과를 테이블에 저장하지
않는다 — data-plan §5의 설계 의도를 그대로 따른다. 사업장이 계약종별을 바꾸면(사무실을
일반용으로 새로 계약하는 등) 마이그레이션 없이 다음 조회에서 자동으로 바뀌어야 하기
때문이다. `Company`나 신규 테이블에 `business_type` 같은 저장형 컬럼을 만들지 말 것.
"""
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import SourceDocument

BusinessScaleHint = Literal["제조업/산업체", "소상공인/상업시설", "미확인"]

# 프론트(web/lib/carbon-point-fixture.ts::BusinessScaleHint)와 문자열까지 같아야 한다 —
# API 응답이 이 값을 그대로 나르고 화면 분기가 문자열 비교로 이뤄진다.
HINT_INDUSTRIAL: BusinessScaleHint = "제조업/산업체"
HINT_COMMERCIAL: BusinessScaleHint = "소상공인/상업시설"
HINT_UNKNOWN: BusinessScaleHint = "미확인"

_CLASS_TO_HINT: dict[str, BusinessScaleHint] = {
    "industrial": HINT_INDUSTRIAL,
    # 주택용도 "소상공인/상업시설"로 본다 — 제도상 대상이 가정용·상업용 전기이고(§6.2),
    # 사업장이 주택용 계약을 쓰는 경우(주택 겸용 점포 등)도 산업용이 아니라는 점에서
    # 판별 목적상 같은 편에 선다. 개인참여 vs 법인참여 구분은 별개 축이며 아직 열린
    # 질문이다(develop-plan §2.6) — 그 결정이 나면 이 매핑이 아니라 축이 하나 늘어난다.
    "commercial": HINT_COMMERCIAL,
    "residential": HINT_COMMERCIAL,
}


def business_scale_hint(session: Session, company_id: int) -> BusinessScaleHint:
    """기업의 최근 전기고지서 계약종별로 사업 규모를 추정한다(저장하지 않음).

    "최근"의 기준은 `(year, month)` 내림차순 — 같은 달에 여러 장이 있으면 나중에 적재된
    것(id 큰 것)을 쓴다. 계약종별을 못 읽은 문서(`contract_type_class`가 null)는 건너뛰고
    더 예전 문서를 본다: 최신 한 장이 파싱 실패했다고 판별을 포기하면, 직전 달에 멀쩡히
    읽은 값이 있는데도 "미확인"으로 떨어진다.

    "미확인"을 반환하는 경우는 둘이고 호출부에서 구분할 필요는 없다(둘 다 §6.1 HITL
    재확인 대상):
      - 전기고지서가 아예 없다(신규 온보딩 직후)
      - 있지만 계약종별을 읽지 못했거나 4종에 안 맞는 계약이다(`unknown`)
    """
    stmt = (
        select(SourceDocument.contract_type_class)
        .where(SourceDocument.company_id == company_id)
        .where(SourceDocument.document_type == "electric_bill")
        .where(SourceDocument.contract_type_class.isnot(None))
        .order_by(
            SourceDocument.year.desc().nullslast(),
            SourceDocument.month.desc().nullslast(),
            SourceDocument.id.desc(),
        )
    )
    for (contract_type_class,) in session.execute(stmt):
        hint = _CLASS_TO_HINT.get(contract_type_class)
        if hint is not None:
            return hint
    return HINT_UNKNOWN
