"""borrower_emission_inventories 의 승인·버전 필드 검증 (docs/v1-plan.md §3 순서3 검증항목).

핵심: Scope 3 미산정은 0이 아니라 null + scope3_status 로 저장된다는 정본 원칙
(docs/borrower-pcaf-data-plan.md §7.4)을 실제 스키마 레벨에서 확인한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Base, Company, FinancialInstitution, OrganizationalBoundary, BorrowerEmissionInventory


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_institution(session) -> FinancialInstitution:
    inst = FinancialInstitution(name="기관", reporting_currency="KRW", tenant_key="bank-a")
    session.add(inst)
    session.commit()
    return inst


def _make_boundary(session, company_id: int, institution_id: int) -> OrganizationalBoundary:
    boundary = OrganizationalBoundary(
        financial_institution_id=institution_id,
        company_id=company_id, reporting_year=2026,
        boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.commit()
    return boundary


def test_inventory_status_check_constraint_rejects_invalid_value(db):
    inst = _make_institution(db)
    company = Company(name="회사1", industry_code="C251")
    db.add(company)
    db.commit()
    boundary = _make_boundary(db, company.id, inst.id)

    db.add(BorrowerEmissionInventory(
        financial_institution_id=inst.id,
        company_id=company.id, reporting_year=2026,
        organizational_boundary_id=boundary.id,
        scope_group="scope_1", status="invalid_value",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_superseded_inventory_links_to_new_version(db):
    """version=2 행이 supersedes_inventory_id 로 version=1 행을 가리키는 자기참조 FK가 동작한다."""
    inst = _make_institution(db)
    company = Company(name="회사1", industry_code="C251")
    db.add(company)
    db.commit()
    boundary = _make_boundary(db, company.id, inst.id)

    v1 = BorrowerEmissionInventory(
        financial_institution_id=inst.id,
        company_id=company.id, reporting_year=2026,
        organizational_boundary_id=boundary.id,
        scope_group="scope_1", status="approved", version=1,
        emission_tco2e=12.5,
    )
    db.add(v1)
    db.commit()

    v2 = BorrowerEmissionInventory(
        financial_institution_id=inst.id,
        company_id=company.id, reporting_year=2026,
        organizational_boundary_id=boundary.id,
        scope_group="scope_1", status="draft", version=2,
        supersedes_inventory_id=v1.id,
        emission_tco2e=13.1,
    )
    db.add(v2)
    db.commit()

    assert v2.supersedes_inventory_id == v1.id
    reloaded = db.query(BorrowerEmissionInventory).filter_by(version=2).one()
    assert reloaded.supersedes_inventory_id == v1.id


def test_emission_tco2e_nullable_for_unreported_scope3(db):
    """emission_tco2e=None + scope3_status='not_calculated' 조합이 저장·조회 가능해야 한다
    (미산정을 0으로 강제 저장하지 않는다는 정본 원칙 검증)."""
    inst = _make_institution(db)
    company = Company(name="회사1", industry_code="C251")
    db.add(company)
    db.commit()
    boundary = _make_boundary(db, company.id, inst.id)

    inv = BorrowerEmissionInventory(
        financial_institution_id=inst.id,
        company_id=company.id, reporting_year=2026,
        organizational_boundary_id=boundary.id,
        scope_group="scope_3", scope3_status="not_calculated",
        emission_tco2e=None,
    )
    db.add(inv)
    db.commit()

    reloaded = db.query(BorrowerEmissionInventory).filter_by(scope_group="scope_3").one()
    assert reloaded.emission_tco2e is None
    assert reloaded.scope3_status == "not_calculated"
