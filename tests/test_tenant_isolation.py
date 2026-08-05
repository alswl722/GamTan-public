"""v1 1주차 완료조건 — 다른 금융기관 리소스 접근을 차단하는 기본 테스트.

docs/v1-plan.md §3 "다른 금융기관 리소스 접근을 차단하는 기본 테스트가 통과한다"를 검증한다.
API 레벨 role 기반 권한 미들웨어는 4주차 범위이므로, 이번 주는 DB 제약(유니크·FK)과
쿼리 필터 수준의 격리만 확인한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Base, FinancialInstitution, InstitutionBorrower, Company, Portfolio


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_institution(session, tenant_key: str) -> FinancialInstitution:
    inst = FinancialInstitution(name=f"기관-{tenant_key}", reporting_currency="KRW", tenant_key=tenant_key)
    session.add(inst)
    session.commit()
    return inst


def _make_company(session, name: str) -> Company:
    company = Company(name=name, industry_code="C251", industry_name="구조용 금속제품 제조")
    session.add(company)
    session.commit()
    return company


def test_institution_borrower_unique_external_customer_id(db):
    """동일 기관 내 external_customer_id 중복은 거부된다."""
    inst = _make_institution(db, "bank-a")
    company = _make_company(db, "회사1")
    db.add(InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="cust-001", consent_status="active",
    ))
    db.commit()

    db.add(InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company.id,
        external_customer_id="cust-001", consent_status="active",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_institution_borrower_allows_same_external_id_different_institution(db):
    """다른 기관이면 동일 external_customer_id 값이 허용된다 (복합 유니크 검증)."""
    inst_a = _make_institution(db, "bank-a")
    inst_b = _make_institution(db, "bank-b")
    company = _make_company(db, "회사1")

    db.add(InstitutionBorrower(
        financial_institution_id=inst_a.id, company_id=company.id,
        external_customer_id="cust-shared", consent_status="active",
    ))
    db.commit()

    db.add(InstitutionBorrower(
        financial_institution_id=inst_b.id, company_id=company.id,
        external_customer_id="cust-shared", consent_status="active",
    ))
    db.commit()  # 예외 없이 성공해야 함

    count = db.query(InstitutionBorrower).filter_by(external_customer_id="cust-shared").count()
    assert count == 2


def test_query_filtered_by_institution_excludes_other_institution_portfolio(db):
    """기관 A 기준 쿼리가 기관 B의 포트폴리오를 반환하지 않는다."""
    inst_a = _make_institution(db, "bank-a")
    inst_b = _make_institution(db, "bank-b")

    db.add(Portfolio(
        financial_institution_id=inst_a.id, name="A 포트폴리오",
        reporting_year=2026, reporting_currency="KRW",
        scope_mode="supported_business_loans",
    ))
    db.add(Portfolio(
        financial_institution_id=inst_b.id, name="B 포트폴리오",
        reporting_year=2026, reporting_currency="KRW",
        scope_mode="supported_business_loans",
    ))
    db.commit()

    a_portfolios = db.query(Portfolio).filter_by(financial_institution_id=inst_a.id).all()
    assert len(a_portfolios) == 1
    assert a_portfolios[0].name == "A 포트폴리오"
    assert all(p.financial_institution_id == inst_a.id for p in a_portfolios)
