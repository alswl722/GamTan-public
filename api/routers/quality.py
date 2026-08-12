"""PCAF 품질평가 API — Business Loans and Unlisted Equity 데이터 품질 후보.

기존 /pcaf/{company_id}(장면④ Before/After)는 그대로 유지한다. 이 라우터는
새 스키마(BorrowerEmissionInventory, PcafQualityRule) 기반의 병행 경로다
(docs/borrower-pcaf-data-plan.md §10.2, §13).

- GET  /borrowers/{company_id}/quality-assessments/{year}            최신 인벤토리 조회
- POST /borrowers/{company_id}/quality-assessments/{year}/evaluate   재산정 + 새 버전 저장

여신 결정은 하지 않는다(CLAUDE.md §9). status는 항상 candidate — 은행 담당자 승인
전에는 자동 확정하지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from db.models import BorrowerEmissionInventory, Company, OrganizationalBoundary, PcafQualityRule
from db.pcaf_quality import assess_borrower_emission_quality

router = APIRouter(prefix="/borrowers", tags=["quality"])

# db/pcaf_quality.assess_borrower_emission_quality는 Scope 1과 Scope 2를 각각
# 독립적으로 평가한다(PR #25 리뷰 CONFIRMED 수정 — 이전에는 "scope_1_2" 하나로
# 합쳐 평가한 뒤 두 인벤토리 행에 동일 값을 복사해 넣었고, 그 결과 서로 다른
# 배출원(전기 vs 가스·경유)의 activity_basis가 서로의 점수를 오염시켰다).
_INVENTORY_SCOPES_FOR_SCOPE_1_2 = ("scope_1", "scope_2")


def _require_company(session: Session, company_id: int) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"company_id={company_id} 없음")
    return company


def _latest_boundary(session: Session, company_id: int, year: int) -> OrganizationalBoundary:
    """평가 저장에 필요한 조직경계 — 없으면 목업으로 만들지 않고 명확히 실패시킨다
    (CLAUDE.md 실패 가시성 원칙). 조직경계 등록은 이 라우터의 책임 밖이다."""
    boundary = session.execute(
        select(OrganizationalBoundary)
        .where(
            OrganizationalBoundary.company_id == company_id,
            OrganizationalBoundary.reporting_year == year,
        )
        .order_by(OrganizationalBoundary.id.desc())
    ).scalars().first()
    if boundary is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"company_id={company_id} reporting_year={year} 조직경계(organizational_boundaries) "
                "미등록 — 품질평가 저장 전 조직경계를 먼저 등록해야 합니다."
            ),
        )
    return boundary


def _latest_inventories(session: Session, company_id: int, year: int) -> list[BorrowerEmissionInventory]:
    """Scope 1·2 인벤토리 행(스코프별 최신 버전만) 조회."""
    result = []
    for scope in _INVENTORY_SCOPES_FOR_SCOPE_1_2:
        row = session.execute(
            select(BorrowerEmissionInventory)
            .where(
                BorrowerEmissionInventory.company_id == company_id,
                BorrowerEmissionInventory.reporting_year == year,
                BorrowerEmissionInventory.scope_group == scope,
            )
            .order_by(BorrowerEmissionInventory.version.desc())
        ).scalars().first()
        if row is not None:
            result.append(row)
    return result


@router.get("/{company_id}/quality-assessments/{year}")
def get_quality_assessment(company_id: int, year: int, session: Session = Depends(get_session)):
    """저장된 최신 Scope 1·2 품질 후보(BorrowerEmissionInventory, 스코프별 각 1행) 조회. 없으면 404."""
    _require_company(session, company_id)
    inventories = _latest_inventories(session, company_id, year)
    if not inventories:
        raise HTTPException(
            status_code=404,
            detail=f"company_id={company_id} reporting_year={year} 품질평가 없음 — evaluate 먼저 실행",
        )
    return {"assessments": [_serialize(inv) for inv in inventories]}


@router.post("/{company_id}/quality-assessments/{year}/evaluate")
def evaluate_quality_assessment(company_id: int, year: int, session: Session = Depends(get_session)):
    """품질 후보 재산정 — Scope 1·2를 각각 독립적으로 평가해 새 버전으로 저장
    (기존 최신 행이 있으면 supersedes 로 연결).

    Scope 1(가스·경유/유류)과 Scope 2(전기)는 배출원이 서로 달라 activity_basis
    구성비도 다를 수 있으므로 db/pcaf_quality.assess_borrower_emission_quality를
    스코프별로 따로 호출한다(PR #25 리뷰 CONFIRMED 수정).
    승인된(status='approved') 인벤토리도 덮어쓰지 않고 새 버전을 만든다(CLAUDE.md
    "승인된 결과는 덮어쓰지 않고 새 버전으로 재산정").

    적어도 한 Scope가 산정 가능해야 저장한다 — 둘 다 산정 불가면 422로 명확히 실패시킨다
    (CLAUDE.md 실패 가시성 원칙, 목업으로 채우지 않는다).
    """
    _require_company(session, company_id)
    boundary = _latest_boundary(session, company_id, year)

    assessments = {
        scope: assess_borrower_emission_quality(session, company_id, year, scope)
        for scope in _INVENTORY_SCOPES_FOR_SCOPE_1_2
    }
    if all(a["candidate_score"] is None for a in assessments.values()):
        limitations = [msg for a in assessments.values() for msg in a["limitations"]]
        raise HTTPException(
            status_code=422,
            detail="; ".join(limitations) or "품질 후보를 산정할 수 없습니다",
        )

    saved = []
    for scope, assessment in assessments.items():
        rule_id = None
        if assessment["option_code"]:
            rule = session.execute(
                select(PcafQualityRule).where(PcafQualityRule.option_code == assessment["option_code"])
            ).scalar_one_or_none()
            rule_id = rule.id if rule else None

        previous = session.execute(
            select(BorrowerEmissionInventory)
            .where(
                BorrowerEmissionInventory.company_id == company_id,
                BorrowerEmissionInventory.reporting_year == year,
                BorrowerEmissionInventory.scope_group == scope,
            )
            .order_by(BorrowerEmissionInventory.version.desc())
        ).scalars().first()

        inventory = BorrowerEmissionInventory(
            financial_institution_id=boundary.financial_institution_id,
            company_id=company_id,
            reporting_year=year,
            organizational_boundary_id=boundary.id,
            scope_group=scope,
            completeness_pct=assessment["completeness_pct"],
            candidate_quality_score=assessment["candidate_score"],
            candidate_quality_rule_id=rule_id,
            candidate_quality_basis_json=assessment["basis"],
            limitations_json=assessment["limitations"],
            status="draft",
            version=(previous.version + 1) if previous else 1,
            supersedes_inventory_id=previous.id if previous else None,
        )
        session.add(inventory)
        saved.append(inventory)

    session.commit()
    return {"assessments": [_serialize(inv) for inv in saved]}


def _serialize(inventory: BorrowerEmissionInventory) -> dict:
    return {
        "company_id": inventory.company_id,
        "reporting_year": inventory.reporting_year,
        "scope_group": inventory.scope_group,
        "candidate_score": inventory.candidate_quality_score,
        "status": inventory.status,
        "rule_id": inventory.candidate_quality_rule_id,
        "basis": inventory.candidate_quality_basis_json or [],
        "limitations": inventory.limitations_json or [],
        "completeness_pct": inventory.completeness_pct,
        "bank_review_required": True,
        "version": inventory.version,
    }
