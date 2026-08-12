"""api/routers/company.py — GET /company, GET /companies 검증."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Company


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_companies_list_empty_when_no_company_seeded(client):
    res = client.get("/companies")
    assert res.status_code == 200
    assert res.json()["companies"] == []


def test_companies_list_returns_all_companies_in_id_order(db, client):
    db.add_all([
        Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조", region="경북 구미시"),
        Company(name="구미정밀", industry_code="C259", industry_name="기타 금속가공제품 제조", region="경북 구미"),
    ])
    db.commit()

    res = client.get("/companies")
    assert res.status_code == 200
    names = [c["name"] for c in res.json()["companies"]]
    assert names == ["○○정밀", "구미정밀"]


def test_demo_company_endpoint_still_returns_first_company(db, client):
    """회사 선택기 도입 전부터 있던 하위호환 경로 회귀 방지."""
    db.add_all([
        Company(name="○○정밀", industry_code="C251"),
        Company(name="구미정밀", industry_code="C259"),
    ])
    db.commit()

    res = client.get("/company")
    assert res.status_code == 200
    assert res.json()["name"] == "○○정밀"
