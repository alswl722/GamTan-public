"""POST /mock/{source}/{company_id} 라우터 검증 — hometax·kepco 기존 라우트와
충돌(catch-all이 먼저 매치)하지 않는지가 핵심 회귀 포인트."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company, FinancialInstitution, InstitutionBorrower, Voucher


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            revenue_krw=2_400_000_000,
        )
        session.add(company)
        session.commit()
        session.add(Voucher(
            company_id=company.id, source="hometax", year=2025, month=1,
            item_description="경유", supply_amount_krw=600000,
        ))
        inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
        session.add(inst)
        session.commit()
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id, company_id=company.id,
            external_customer_id="demo-company-1", consent_status="active",
        ))
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_hometax_route_still_resolves_to_voucher_source_not_mydata_catchall(db, client):
    """회귀: 새 catch-all(/{source}/{id})이 기존 /hometax/{id}를 가로채면 안 된다."""
    _, company_id = db
    res = client.post(f"/mock/hometax/{company_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "hometax"
    assert body["count"] == 1
    assert "vouchers" in body  # mydata 응답 형태(extracted)가 아니라 voucher mock 응답 형태


def test_kepco_route_still_resolves(db, client):
    _, company_id = db
    res = client.post(f"/mock/kepco/{company_id}")
    assert res.status_code == 200
    assert res.json()["source"] == "kepco"


def test_mydata_source_route_resolves(db, client):
    _, company_id = db
    res = client.post(f"/mock/business-registration/{company_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "business-registration"
    assert "extracted" in body


def test_unknown_mydata_source_returns_404(db, client):
    _, company_id = db
    res = client.post(f"/mock/not-a-real-source/{company_id}")
    assert res.status_code == 404
