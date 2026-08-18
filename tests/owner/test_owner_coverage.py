"""GET /owner/{company_id}/coverage — 업로드 화면 결손 넛지 카드용 엔드포인트."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company, Voucher


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        session.add(Voucher(
            company_id=company.id, source="kepco", year=2025, month=1,
            item_description="전기요금", supply_amount_krw=1_000_000,
        ))
        session.commit()
        yield session, company.id


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_coverage_endpoint_returns_matrix_and_gaps(db, client):
    _, company_id = db
    res = client.get(f"/owner/{company_id}/coverage")
    assert res.status_code == 200
    body = res.json()
    assert "matrix" in body and "gaps" in body
    fuels_with_gaps = {g["fuel"] for g in body["gaps"]}
    # 1월 전기만 있고 나머지 11개월은 전기도 결손, 가스·경유는 전량 결손.
    assert fuels_with_gaps == {"전기", "가스", "경유/유류"}
