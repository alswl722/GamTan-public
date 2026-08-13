"""사장님 리포트 K택소노미 안내 API(GET /owner/{id}/k-taxonomy-leads) 골든 케이스.

핵심 검증축:
  - 리드가 있으면 설비 단위로 묶여서 반환된다(db/k_taxonomy.py::k_taxonomy_leads_for_company).
  - 리드가 없는 기업(대다수)은 빈 배열이 정상 응답이다 — 실패가 아니다.
  - POST /owner/{id}/rate-requests의 equipment_finance 경로가 missing_summary를
    그대로 저장하고, 관리자 승인요청 큐에도 그대로 노출된다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.tools import classify_vouchers
from api.db import get_session
from api.main import app
from db.init_db import seed_emission_factors, seed_industry_distributions, seed_unit_prices
from db.models import Base, Company, Voucher

YEAR = 2025


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_voucher(session, cid, item, *, month=1):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=1_000_000,
    )
    session.add(v)
    session.commit()
    return v.id


def test_k_taxonomy_leads_endpoint_returns_grouped_leads(db, client):
    session, cid = db
    _add_voucher(session, cid, "태양광 설비 설치")
    classify_vouchers(session, cid)

    res = client.get(f"/owner/{cid}/k-taxonomy-leads")
    assert res.status_code == 200, res.text
    leads = res.json()["leads"]
    assert len(leads) == 1
    assert leads[0]["k_taxonomy_facility_type"] == "태양광 설비"
    assert leads[0]["hint"]


def test_k_taxonomy_leads_endpoint_empty_for_company_without_leads(db, client):
    """대다수 기업의 정상 상태 — 일반 연료만 있으면 빈 배열, 실패가 아니다."""
    session, cid = db
    _add_voucher(session, cid, "도시가스 요금")
    classify_vouchers(session, cid)

    res = client.get(f"/owner/{cid}/k-taxonomy-leads")
    assert res.status_code == 200
    assert res.json()["leads"] == []


def test_equipment_finance_request_from_lead_reaches_admin_queue(db, client):
    """K택소노미 리드 카드의 "설비금융 안내 요청" 버튼이 실제로 승인요청 큐에
    missing_summary와 함께 나타난다(엔드투엔드)."""
    session, cid = db
    _add_voucher(session, cid, "태양광 설비 설치")
    classify_vouchers(session, cid)

    leads = client.get(f"/owner/{cid}/k-taxonomy-leads").json()["leads"]
    lead = leads[0]
    summary = f"{lead['k_taxonomy_facility_type']} · {lead['item_description']}"

    post_res = client.post(
        f"/owner/{cid}/rate-requests",
        json={"request_type": "equipment_finance", "missing_summary": summary},
    )
    assert post_res.status_code == 200, post_res.text
    assert post_res.json()["missing_summary"] == summary

    admin_res = client.get("/admin/rate-requests")
    entry = next(r for r in admin_res.json()["requests"] if r["id"] == post_res.json()["id"])
    assert entry["missing_summary"] == summary
    assert entry["request_type"] == "equipment_finance"
