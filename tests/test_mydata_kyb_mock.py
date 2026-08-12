"""api/mydata_kyb_mock.py — 마이데이터 5종(KYB·재무) mock 수집 검증."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.document_ingestion import MissingInstitutionAttributionError
from api.mydata_kyb_mock import collect_mydata
from db.models import Base, BorrowerFinancial, Company, FinancialInstitution, InstitutionBorrower, SourceDocument


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            revenue_krw=2_400_000_000,
        )
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def db_with_institution(db):
    session, company_id = db
    inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
    session.add(inst)
    session.commit()
    ib = InstitutionBorrower(
        financial_institution_id=inst.id, company_id=company_id,
        external_customer_id="demo-company-1", consent_status="active",
    )
    session.add(ib)
    session.commit()
    return session, company_id, ib.id


def test_unbackfilled_company_raises_clear_error(db):
    session, company_id = db
    with pytest.raises(MissingInstitutionAttributionError):
        collect_mydata(session, company_id, "business-registration")


def test_unknown_source_raises_value_error(db_with_institution):
    session, company_id, _ = db_with_institution
    with pytest.raises(ValueError):
        collect_mydata(session, company_id, "not-a-real-source")


def test_business_registration_creates_source_document_and_updates_external_id(db_with_institution):
    session, company_id, ib_id = db_with_institution
    result = collect_mydata(session, company_id, "business-registration")
    assert result["already_collected"] is False
    assert "business_registration_no" in result["extracted"]

    docs = session.execute(select(SourceDocument)).scalars().all()
    assert len(docs) == 1
    assert docs[0].document_type == "business_registration"
    assert docs[0].source_system == "mydata:business-registration"

    ib = session.get(InstitutionBorrower, ib_id)
    assert ib.external_customer_id.startswith("biz-")


def test_kyb_collection_is_idempotent(db_with_institution):
    session, company_id, _ = db_with_institution
    first = collect_mydata(session, company_id, "sme-certificate")
    second = collect_mydata(session, company_id, "sme-certificate")
    assert first["already_collected"] is False
    assert second["already_collected"] is True
    assert second["extracted"] == first["extracted"]

    docs = session.execute(select(SourceDocument)).scalars().all()
    assert len(docs) == 1


def test_financial_statement_creates_borrower_financials_row(db_with_institution):
    session, company_id, _ = db_with_institution
    result = collect_mydata(session, company_id, "financial-statement")
    assert result["already_collected"] is False

    rows = session.execute(select(BorrowerFinancial)).scalars().all()
    assert len(rows) == 1
    assert rows[0].company_id == company_id
    assert rows[0].currency == "KRW"
    assert float(rows[0].total_equity) > 0
    assert float(rows[0].total_debt) > 0


def test_financial_statement_collection_is_idempotent(db_with_institution):
    session, company_id, _ = db_with_institution
    collect_mydata(session, company_id, "financial-statement")
    second = collect_mydata(session, company_id, "financial-statement")
    assert second["already_collected"] is True

    rows = session.execute(select(BorrowerFinancial)).scalars().all()
    assert len(rows) == 1


def test_kepco_payment_history_has_no_kwh_field(db_with_institution):
    """검토 섹션 정정사항 회귀 방지 — 마이데이터 전기납부내역엔 kWh가 없어야 한다."""
    session, company_id, _ = db_with_institution
    result = collect_mydata(session, company_id, "kepco-payment-history")
    payments = result["extracted"]["payments"]
    assert len(payments) == 12
    assert all("paid_amount_krw" in p and "kwh" not in p and "quantity" not in p for p in payments)
