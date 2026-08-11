"""business_loan_exposures 의 (portfolio_id, external_exposure_id) 유니크 제약 검증
(docs/v1-plan.md §3 순서4 검증항목: "중복 익스포저 유니크 제약")."""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Base, Company, FinancialInstitution, Portfolio, BusinessLoanExposure


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_portfolio(session, tenant_key: str) -> Portfolio:
    inst = FinancialInstitution(name=f"기관-{tenant_key}", reporting_currency="KRW", tenant_key=tenant_key)
    session.add(inst)
    session.commit()
    portfolio = Portfolio(
        financial_institution_id=inst.id, name="포트폴리오", reporting_year=2026,
        reporting_currency="KRW", scope_mode="supported_business_loans",
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def test_duplicate_external_exposure_id_same_portfolio_rejected(db):
    portfolio = _make_portfolio(db, "bank-a")
    company = Company(name="회사1", industry_code="C251")
    db.add(company)
    db.commit()

    db.add(BusinessLoanExposure(
        portfolio_id=portfolio.id, company_id=company.id,
        external_exposure_id="loan-001", asset_class="business_loans_and_unlisted_equity",
        outstanding_amount=100_000_000, currency="KRW",
        reporting_date=datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc),
    ))
    db.commit()

    db.add(BusinessLoanExposure(
        portfolio_id=portfolio.id, company_id=company.id,
        external_exposure_id="loan-001", asset_class="business_loans_and_unlisted_equity",
        outstanding_amount=50_000_000, currency="KRW",
        reporting_date=datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_same_external_exposure_id_different_portfolio_allowed(db):
    portfolio_a = _make_portfolio(db, "bank-a")
    portfolio_b = _make_portfolio(db, "bank-b")
    company = Company(name="회사1", industry_code="C251")
    db.add(company)
    db.commit()

    db.add(BusinessLoanExposure(
        portfolio_id=portfolio_a.id, company_id=company.id,
        external_exposure_id="loan-shared", asset_class="business_loans_and_unlisted_equity",
        outstanding_amount=100_000_000, currency="KRW",
        reporting_date=datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc),
    ))
    db.add(BusinessLoanExposure(
        portfolio_id=portfolio_b.id, company_id=company.id,
        external_exposure_id="loan-shared", asset_class="business_loans_and_unlisted_equity",
        outstanding_amount=200_000_000, currency="KRW",
        reporting_date=datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc),
    ))
    db.commit()  # 예외 없이 성공해야 함

    count = db.query(BusinessLoanExposure).filter_by(external_exposure_id="loan-shared").count()
    assert count == 2
