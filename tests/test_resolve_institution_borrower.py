"""api/queries.py::resolve_institution_borrower — v1 하이브리드 입력 파이프라인이
새로 만드는 vouchers/source_documents에 기관 귀속을 채울 때 쓰는 헬퍼 검증."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.queries import resolve_institution_borrower
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_resolves_backfilled_institution_borrower(db):
    inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
    company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
    db.add_all([inst, company])
    db.commit()

    ib = InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="demo-company-1", consent_status="active",
    )
    db.add(ib)
    db.commit()

    result = resolve_institution_borrower(db, company.id)
    assert result == (inst.id, ib.id)


def test_returns_none_when_company_not_backfilled(db):
    company = Company(name="미백필기업", industry_code="C251", industry_name="구조용 금속제품 제조")
    db.add(company)
    db.commit()

    assert resolve_institution_borrower(db, company.id) is None


def test_ignores_revoked_consent(db):
    """동의가 철회된 기업의 새 업로드가 그 기관 귀속으로 계속 쌓이면 안 된다."""
    inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
    company = Company(name="동의철회기업", industry_code="C251", industry_name="구조용 금속제품 제조")
    db.add_all([inst, company])
    db.commit()

    db.add(InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="revoked-company-1", consent_status="revoked",
    ))
    db.commit()

    assert resolve_institution_borrower(db, company.id) is None


def test_finds_active_consent_even_when_a_revoked_one_exists_first(db):
    """같은 기업이 예전에 동의 철회한 이력이 있어도, 이후 새로 active 동의를 한 게
    있으면 그걸 찾아야 한다(오래된 순 정렬이 철회 건을 우선 집어오지 않게)."""
    inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
    company = Company(name="재동의기업", industry_code="C251", industry_name="구조용 금속제품 제조")
    db.add_all([inst, company])
    db.commit()

    db.add(InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="revoked-first", consent_status="revoked",
    ))
    db.commit()
    active_ib = InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="active-second", consent_status="active",
    )
    db.add(active_ib)
    db.commit()

    assert resolve_institution_borrower(db, company.id) == (inst.id, active_ib.id)
