"""사장님 리포트(장면⑤) 전용 PCAF 품질 API — 정식 엔진(db/pcaf_quality.py) 래퍼.

은행 담당자용 `/borrowers/{id}/quality-assessments/{year}[/evaluate]`(api/routers/quality.py)는
조직경계(OrganizationalBoundary)가 미리 등록돼 있다는 전제로 설계됐다. 사장님 화면에서는
그 전제를 사용자가 신경 쓸 이유가 없으므로, 이 라우터가 조직경계 자동 생성(간이화 가정 —
db/organizational_boundary.py, 회계 검수 필요)과 최초 평가 자동 산정을 한 번에 처리한다.

- GET /owner/{company_id}/quality-report?year=  Scope1·2 PCAF 품질 후보 + 동종업계 벤치마크
- GET /owner/{company_id}/emission-detail       Scope 카드 상세보기 — 배출량을 구성한 전표 목록

여신 결정이 아니다(CLAUDE.md §9). status는 항상 draft 이상으로 올라가지 않으며,
bank_review_required가 항상 true다 — 은행 담당자 승인 전 자동 확정 없음.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from api.queries import get_distribution
from db.models import BorrowerEmissionInventory, Company, PcafQualityRule
from db.organizational_boundary import ensure_organizational_boundary
from db.pcaf import benchmark_against_industry
from db.pcaf_quality import default_reporting_year, save_quality_assessment_version, scope_emission_detail

router = APIRouter(prefix="/owner", tags=["owner-quality"])

_SCOPES = ("scope_1", "scope_2")


def _latest_inventory(
    session: Session, company_id: int, year: int, scope_group: str
) -> BorrowerEmissionInventory | None:
    return session.execute(
        select(BorrowerEmissionInventory)
        .where(
            BorrowerEmissionInventory.company_id == company_id,
            BorrowerEmissionInventory.reporting_year == year,
            BorrowerEmissionInventory.scope_group == scope_group,
        )
        .order_by(BorrowerEmissionInventory.version.desc())
    ).scalars().first()


def _serialize_scope(session: Session, inv: BorrowerEmissionInventory) -> dict:
    rule = (
        session.get(PcafQualityRule, inv.candidate_quality_rule_id)
        if inv.candidate_quality_rule_id
        else None
    )
    return {
        "scope_group": inv.scope_group,
        "emission_tco2e": inv.emission_tco2e,
        "candidate_score": inv.candidate_quality_score,
        "option_code": rule.option_code if rule else None,
        "activity_data_basis": rule.activity_data_basis if rule else None,
        "completeness_pct": inv.completeness_pct,
        "basis": inv.candidate_quality_basis_json or [],
        "limitations": inv.limitations_json or [],
        "status": inv.status,
        "version": inv.version,
        "bank_review_required": True,
    }


@router.get("/{company_id}/quality-report")
def owner_quality_report(
    company_id: int, year: int | None = None, session: Session = Depends(get_session)
):
    """사장님 리포트 화면 — Scope1·2 PCAF 품질 후보 + 동종업계 벤치마크.

    최초 조회 시 조직경계가 없으면 간이화 가정으로 자동 생성하고, 해당 연도 평가가
    한 번도 저장된 적 없으면 자동으로 1회 산정해 저장한다(은행 담당자용 evaluate와
    같은 저장 로직 재사용 — db/pcaf_quality.py::save_quality_assessment_version).
    이후 조회는 저장된 최신 버전을 그대로 반환한다 — 조회할 때마다 새 버전을
    만들지 않는다(승인된 결과를 덮어쓰지 않는 원칙과 같은 결).
    """
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"company_id={company_id} 없음")

    reporting_year = year or default_reporting_year(session, company_id)

    try:
        boundary = ensure_organizational_boundary(session, company_id, reporting_year)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    inventories: dict[str, BorrowerEmissionInventory] = {}
    for scope in _SCOPES:
        inv = _latest_inventory(session, company_id, reporting_year, scope)
        if inv is None:
            inv = save_quality_assessment_version(session, company_id, boundary, reporting_year, scope)
        inventories[scope] = inv
    session.commit()
    for inv in inventories.values():
        session.refresh(inv)

    dist1 = get_distribution(session, company.industry_code, 1)
    dist2 = get_distribution(session, company.industry_code, 2)
    e1 = inventories["scope_1"].emission_tco2e
    e2 = inventories["scope_2"].emission_tco2e
    total_emission = (e1 or 0) + (e2 or 0) if (e1 is not None or e2 is not None) else None
    benchmark = benchmark_against_industry(company, dist1, dist2, total_emission)

    return {
        "reporting_year": reporting_year,
        "scope_1": _serialize_scope(session, inventories["scope_1"]),
        "scope_2": _serialize_scope(session, inventories["scope_2"]),
        "benchmark": benchmark,
    }


@router.get("/{company_id}/emission-detail")
def owner_emission_detail(
    company_id: int,
    scope_group: Literal["scope_1", "scope_2"],
    year: int,
    session: Session = Depends(get_session),
):
    """Scope 카드를 펼쳤을 때 보여줄 전표 상세 — quality-report의 emission_tco2e를
    구성한 전표 목록(db/pcaf_quality.py::scope_emission_detail이 같은 필터를 써서
    합계가 항상 일치한다). 판정 근거(basis/limitations)는 여전히 은행 담당자용이라
    이 응답에도 포함하지 않는다.
    """
    return {
        "scope_group": scope_group,
        "reporting_year": year,
        "items": scope_emission_detail(session, company_id, year, scope_group),
    }
