"""우대금리 상품 매칭 — 사장님 메인 화면(GET /owner/{id}/rate-candidate)이 쓰는
결정론적 매칭 함수.

db/pcaf_quality.py의 PCAF Scope별 데이터 품질 평가(assess_borrower_emission_quality)를
읽기만 한다. RateProduct 매칭도 등급 숫자 비교로만 하고 LLM은 호출하지 않는다(CLAUDE.md
원칙1과 같은 결 — 결정론적 코드만).

두 상태만 반환한다:
  - "eligible"    — 지금 등급으로 이미 자격을 충족하는 상품이 있음 (신규, 이전엔
                     이 상태를 표현할 데이터 자체가 없었다 — quality_upgrade_candidate는
                     "개선 후보"만 반환하고 이미 최고 등급이면 그냥 None이었다)
  - "upgrade_needed" — 아직 4등급 — 기존 quality_upgrade_candidate를 그대로 재사용하되
                     목표 등급에서 자격을 얻을 상품명을 benefit 문구에 덧붙인다.

자격·등급 상승을 보장하지 않는다는 문구(disclaimer_text)는 이 모듈이 아니라 호출부
라우터가 항상 동봉한다(db/rate_approvals.py::DISCLAIMER_TEXT, CLAUDE.md 원칙10).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.pcaf_engine.k_taxonomy import k_taxonomy_leads_for_company
from db.models import RateProduct
from db.pcaf_engine.pcaf_quality import (
    assess_borrower_emission_quality,
    default_reporting_year,
    quality_upgrade_candidate,
)

# db/pcaf_quality.py::_UPGRADE_SCOPES와 같은 값(모듈 내부 상수라 임포트하지 않고
# 이 모듈 안에서 독립적으로 유지 — _fuel_bucket 등과 같은 이 프로젝트의 기존 관례).
_UPGRADE_SCOPES = ("scope_1", "scope_2")


def _matching_products(session: Session, candidate_score: int, has_k_taxonomy_leads: bool) -> list[dict]:
    """candidate_score 이하(=이 등급 이상 고품질)를 요구하는 상품만 자격 충족.

    PCAF 품질점수는 1(최고)~5(최저) 순서형이라 "숫자가 작을수록 우수"다 —
    RateProduct.min_data_quality_score는 "이 점수까지는 인정"하는 하한선.

    requires_k_taxonomy_leads=True인 상품(예: K-택소노미 그린 SME 대출)은 PCAF
    등급만으로는 부족하다 — 그 상품의 실제 조건이 K-택소노미 적합 설비 투자
    증빙이라, 전표에서 그 근거(db/k_taxonomy.py 리드)가 실제로 확인돼야만
    매칭시킨다(2026-08-15, PCAF 등급만 보던 걸 실제 상품 조건에 맞게 분리).
    """
    rows = session.execute(
        select(RateProduct).where(RateProduct.min_data_quality_score >= candidate_score)
    ).scalars().all()
    return [
        {
            "product_name": p.product_name,
            "provider_name": p.provider_name,
            "rate_discount_pct": float(p.rate_discount_pct),
            "eligibility_description": p.eligibility_description,
            "source_reference": p.source_reference,
        }
        for p in rows
        if not p.requires_k_taxonomy_leads or has_k_taxonomy_leads
    ]


def rate_product_status_for_scope(
    session: Session, company_id: int, reporting_year: int, scope_group: str
) -> dict | None:
    """한 Scope의 우대금리 상품 자격 상태 — None이면 활동자료가 아예 없어 카드 자체가 없음.

    db/rate_approvals.py::create_rate_request가 "이미 대상" 상태에서도 요청을 만들 수
    있도록 이 함수를 재사용한다(사장님 화면의 목록 판정과 요청 생성이 같은 기준을 공유).
    """
    assessment = assess_borrower_emission_quality(session, company_id, reporting_year, scope_group)
    score = assessment["candidate_score"]
    if score is None:
        return None  # 활동자료 없음 — 기존과 동일하게 카드 자체가 없음

    has_k_taxonomy_leads = bool(k_taxonomy_leads_for_company(session, company_id))
    products = _matching_products(session, score, has_k_taxonomy_leads)
    if products:
        return {
            "scope_group": scope_group,
            "status": "eligible",
            "candidate_score": score,
            "products": products,
        }

    candidate = quality_upgrade_candidate(session, company_id, reporting_year, scope_group)
    if candidate is None:
        return None
    target_products = _matching_products(session, candidate["target_grade"], has_k_taxonomy_leads)
    benefit = candidate["benefit"]
    if target_products:
        names = ", ".join(p["product_name"] for p in target_products)
        benefit = f"{benefit} ({names} 우대금리 대상)"
    return {
        "scope_group": scope_group,
        "status": "upgrade_needed",
        "candidate_score": score,
        "current_grade": candidate["current_grade"],
        "target_grade": candidate["target_grade"],
        "missing": candidate["missing"],
        "missing_items": candidate["missing_items"],
        "benefit": benefit,
        "target_products": target_products,
    }


def rate_product_status_for_company(
    session: Session, company_id: int, reporting_year: int | None = None
) -> list[dict]:
    """기업의 Scope1·2 각각에 대해 우대금리 상품 자격 상태를 판정(0~2건).

    reporting_year 생략 시 default_reporting_year로 채운다 — 사장님 리포트·기존
    quality_upgrade_candidates_for_company와 같은 "그 기업의 최신 전표 연도" 기준 공유.
    """
    year = reporting_year if reporting_year is not None else default_reporting_year(session, company_id)
    results = []
    for scope_group in _UPGRADE_SCOPES:
        status = rate_product_status_for_scope(session, company_id, year, scope_group)
        if status is not None:
            results.append(status)
    return results
