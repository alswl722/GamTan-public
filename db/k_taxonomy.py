"""K택소노미·설비투자 리드 — 기존 룰 매칭 결과에 얹는 참조 테이블 (v1 §6 2주차).

회계 data/*.xlsx의 k_taxonomy_mapping 시트가 이미 기존 룰(R051~R058, R031, R032,
분류_기준표_확장 시트)과 linked_rule_id로 연결돼 있다 — 새 키워드 매칭 로직을
만들지 않는다. 이 모듈은 그 매핑을 rule_id → K택소노미 필드 딕셔너리로만 변환한다.

category='감축투자 후보'류 룰이 매칭됐을 때만 의미가 있고, 배출량 계산과는 무관하다
(원문: "배출량 계산 대상 아니나 녹색여신 참고"). finance_lead_type이 채워져도 이건
"리드"일 뿐 여신 결정이 아니다(CLAUDE.md §9) — 최종 승인은 승인요청 큐를 거친다.
"""
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.queries import get_coverage
from db.excel_loader import load_k_taxonomy_mapping
from db.models import Classification, Company, Voucher


@lru_cache(maxsize=1)
def _mapping_by_rule_id() -> dict[str, dict]:
    """rule_id → K택소노미 필드. 모듈 프로세스 생애 동안 1회만 Excel을 읽는다
    (load_classification_rules와 같은 캐시 없음 관례를 따르되, 이 매핑은 분류
    파이프라인에서 전표마다 호출되므로 캐시가 필요하다)."""
    rows = load_k_taxonomy_mapping()
    return {r["linked_rule_id"]: r for r in rows}


def k_taxonomy_fields_for_rule(rule_id: str | None) -> dict:
    """rule_id에 대응하는 K택소노미 필드를 반환. 매핑이 없으면 전부 None/False
    (해당 전표가 K택소노미·설비투자 대상이 아니라는 뜻 — 절대다수의 전표가 여기 해당).
    """
    if not rule_id:
        return _empty_fields()
    entry = _mapping_by_rule_id().get(rule_id)
    if entry is None:
        return _empty_fields()
    return {
        "k_taxonomy_candidate_type": entry["candidate_type"],
        "k_taxonomy_facility_type": entry["facility_type"],
        "finance_lead_type": entry["finance_lead_type"],
        "k_taxonomy_hitl_required": entry["hitl_required"],
    }


def _empty_fields() -> dict:
    return {
        "k_taxonomy_candidate_type": None,
        "k_taxonomy_facility_type": None,
        "finance_lead_type": None,
        "k_taxonomy_hitl_required": False,
    }


def k_taxonomy_leads(session: Session) -> list[dict]:
    """K택소노미·설비투자 리드 — finance_lead_type이 채워진 분류 건을 전 기업에서 모은다.

    관리자 화면(§13 "K택소노미 리드 리스트")용. 여신 결정이 아니라 안내 대상 목록일
    뿐이다(CLAUDE.md §9). 정렬은 데이터 완전성(결손 개수)만 사용한다 — 감축 실적·
    배출량 기반 순위는 금지한다(CLAUDE.md 원칙7). 담당자가 반려한 건(status='rejected')은
    신뢰할 수 없는 분류라 제외한다(다른 집계와 동일 규칙, db/pcaf.py::_after_measured 참고).
    """
    rows = session.execute(
        select(Classification, Voucher, Company)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .join(Company, Voucher.company_id == Company.id)
        .where(
            Classification.finance_lead_type.isnot(None),
            Classification.status != "rejected",
        )
        .order_by(Voucher.company_id, Classification.classified_at.desc())
    ).all()

    gap_count_by_company: dict[int, int] = {}
    leads = []
    for c, v, co in rows:
        if co.id not in gap_count_by_company:
            gap_count_by_company[co.id] = len(get_coverage(session, co.id)["gaps"])
        leads.append(
            {
                "company_id": co.id,
                "company_name": co.name,
                "industry_name": co.industry_name,
                "finance_lead_type": c.finance_lead_type,
                "k_taxonomy_candidate_type": c.k_taxonomy_candidate_type,
                "k_taxonomy_facility_type": c.k_taxonomy_facility_type,
                "k_taxonomy_hitl_required": c.k_taxonomy_hitl_required,
                "item_description": v.item_description,
                "voucher_month": v.month,
                "gap_count": gap_count_by_company[co.id],
            }
        )

    # 결손 적은(데이터 완전성 높은) 기업 우선 — 원칙7: 데이터 완전성만 정렬 기준.
    leads.sort(key=lambda lead: (lead["gap_count"], lead["company_id"]))
    return leads
