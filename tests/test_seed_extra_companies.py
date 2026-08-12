"""db/seed_mock.py::seed_extra_companies — 회사 선택 화면용 데모 기업 6곳 시드 검증."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, Company, FinancialInstitution, InstitutionBorrower
from db.seed_mock import _DEMO_TENANT_KEY, EXTRA_COMPANIES, seed_extra_companies


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_seeds_all_six_companies_with_active_institution_borrower(db):
    seed_extra_companies(db)

    companies = db.execute(select(Company)).scalars().all()
    assert len(companies) == len(EXTRA_COMPANIES)

    inst = db.execute(
        select(FinancialInstitution).where(FinancialInstitution.tenant_key == _DEMO_TENANT_KEY)
    ).scalar_one()

    borrowers = db.execute(select(InstitutionBorrower)).scalars().all()
    assert len(borrowers) == len(EXTRA_COMPANIES)
    assert all(b.financial_institution_id == inst.id for b in borrowers)
    assert all(b.consent_status == "active" for b in borrowers)
    assert {b.external_customer_id for b in borrowers} == {c["external_id"] for c in EXTRA_COMPANIES}


def test_seeding_twice_is_idempotent(db):
    seed_extra_companies(db)
    seed_extra_companies(db)

    assert db.execute(select(Company)).scalars().all().__len__() == len(EXTRA_COMPANIES)
    assert db.execute(select(InstitutionBorrower)).scalars().all().__len__() == len(EXTRA_COMPANIES)


def test_reuses_existing_financial_institution_if_present(db):
    """0006 백필이 이미 만들어둔 데모 기관이 있으면 새로 만들지 않고 재사용한다."""
    inst = FinancialInstitution(name="기존 기관", reporting_currency="KRW", tenant_key=_DEMO_TENANT_KEY)
    db.add(inst)
    db.commit()

    seed_extra_companies(db)

    institutions = db.execute(select(FinancialInstitution)).scalars().all()
    assert len(institutions) == 1
    assert institutions[0].name == "기존 기관"  # 새로 덮어쓰지 않음
