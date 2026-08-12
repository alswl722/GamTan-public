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
