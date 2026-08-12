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

# PcafQualityRule.scope_group("scope_1_2")은 품질규칙 매칭 단위이고,
# BorrowerEmissionInventory.scope_group(scope_1|scope_2|scope_3, §7.4 CHECK 제약)은
# 인벤토리 저장 단위다 — 서로 다른 값 도메인이므로 저장 시 Scope 1·2 두 행으로 나눈다.
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
    """품질 후보 재산정 — Scope 1·2 각각 새 버전으로 저장(기존 최신 행이 있으면 supersedes 로 연결).

    PcafQualityRule.scope_group("scope_1_2")은 품질규칙 매칭 단위이고,
    BorrowerEmissionInventory.scope_group(scope_1|scope_2)은 인벤토리 저장 단위라
    동일 평가 결과를 두 스코프 행에 나눠 저장한다.
    승인된(status='approved') 인벤토리도 덮어쓰지 않고 새 버전을 만든다(CLAUDE.md
    "승인된 결과는 덮어쓰지 않고 새 버전으로 재산정").
    """
    _require_company(session, company_id)
    boundary = _latest_boundary(session, company_id, year)

    assessment = assess_borrower_emission_quality(session, company_id, year, "scope_1_2")
    if assessment["candidate_score"] is None:
        raise HTTPException(
            status_code=422,
            detail="; ".join(assessment["limitations"]) or "품질 후보를 산정할 수 없습니다",
        )

    rule_id = None
    if assessment["option_code"]:
        rule = session.execute(
            select(PcafQualityRule).where(PcafQualityRule.option_code == assessment["option_code"])
        ).scalar_one_or_none()
        rule_id = rule.id if rule else None

    saved = []
    for scope in _INVENTORY_SCOPES_FOR_SCOPE_1_2:
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
            limitations_json=assessment["limitations"],
            status="draft",
            version=(previous.version + 1) if previous else 1,
            supersedes_inventory_id=previous.id if previous else None,
        )
        session.add(inventory)
        saved.append(inventory)

    session.commit()
    return {"assessments": [_serialize(inv, basis=assessment["basis"]) for inv in saved]}


def _serialize(inventory: BorrowerEmissionInventory, basis: list[str] | None = None) -> dict:
    return {
        "company_id": inventory.company_id,
        "reporting_year": inventory.reporting_year,
        "scope_group": inventory.scope_group,
        "candidate_score": inventory.candidate_quality_score,
        "status": inventory.status,
        "rule_id": inventory.candidate_quality_rule_id,
        "basis": basis or [],
        "limitations": inventory.limitations_json or [],
        "completeness_pct": inventory.completeness_pct,
        "bank_review_required": True,
        "version": inventory.version,
    }
