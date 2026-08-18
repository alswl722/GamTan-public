"""PATCH /owner/{company_id}/fuel-types + get_coverage 결손 필터 검증.

핵심 회귀 조건: 연료 체크를 아직 안 한 기업(fuel_types_json=None)은 기존 결손
감지 동작(3~5월 가스 결손 등)이 그대로 유지돼야 한다 — 킬러씬이 깨지면 안 됨.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from api.queries import get_coverage
from db.models import Base, Company, Voucher

# get_coverage()는 이제 연도를 명시 안 하면 달력상 올해만 본다(실측 2026-08-17) —
# 결손 판정용 픽스처도 "올해" 전표여야 실제 동작과 같은 조건이 된다.
YEAR = datetime.now(timezone.utc).year


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
        )
        session.add(company)
        session.commit()
        # 전기만 1~12월 전부 있고, 가스·경유는 아예 없음(전부 결손) — 필터 유무 차이를 보기 쉽게.
        for m in range(1, 13):
            session.add(Voucher(
                company_id=company.id, source="kepco", year=YEAR, month=m,
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


def test_coverage_gaps_unfiltered_when_fuel_types_not_set(db):
    session, company_id = db
    coverage = get_coverage(session, company_id)
    fuels_with_gaps = {g["fuel"] for g in coverage["gaps"]}
    assert fuels_with_gaps == {"가스", "경유/유류"}


def test_patch_fuel_types_saves_and_returns_required_documents(db, client):
    _, company_id = db
    res = client.patch(
        f"/owner/{company_id}/fuel-types",
        json={"diesel": False, "gasoline": False, "city_gas": True, "lpg": "no", "electricity": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["fuel_types"]["city_gas"] is True
    assert body["required_documents"] == {
        "tax_invoice": "optional",
        "electric_bill": "required",
        "gas_bill": "required",
    }


def test_coverage_gaps_excludes_unchecked_fuel_after_patch(db, client):
    session, company_id = db
    client.patch(
        f"/owner/{company_id}/fuel-types",
        json={"diesel": False, "gasoline": False, "city_gas": False, "lpg": "no", "electricity": True},
    )
    session.expire_all()
    coverage = get_coverage(session, company_id)
    fuels_with_gaps = {g["fuel"] for g in coverage["gaps"]}
    # 도시가스·경유 둘 다 체크 안 했으니 결손이 있어도 알림 대상에서 빠진다.
    assert fuels_with_gaps == set()
