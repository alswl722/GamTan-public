"""기후리스크 리포트 — 금감원 4단계 구조 (v1 Tier 2, owner-admin-flow-spec.md §6,
docs/tasks.md).

핵심 검증축:
  - portfolio_summary()를 재계산 없이 4단계(거버넌스/전략/리스크평가/공시) 틀로
    재배열한다 — 신규 계산 로직 없음.
  - 검증 오차율은 "산정 예정"으로, 시계열 금융배출량은 "예시 데이터(is_example)"
    로 명시된다 — 실측인 것처럼 보이지 않아야 한다.
  - 시계열 금융배출량은 시딩된 포트폴리오 대출 데이터가 있으면 실제 산식으로
    계산되고(db/pcaf_engine/financed_emissions.py), 없으면 빈 배열이다 —
    둘 다 정상 동작, 하드코딩 예시값이 아니다.
  - format=pdf는 유효한 PDF 바이트를 반환한다.
"""
from datetime import datetime, timezone

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import (
    Base,
    BorrowerEmissionInventory,
    BorrowerFinancial,
    BusinessLoanExposure,
    Classification,
    Company,
    FinancialInstitution,
    OrganizationalBoundary,
    Portfolio,
    Voucher,
)

YEAR = 2025


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        inst = FinancialInstitution(name="감탄 데모 금융기관", reporting_currency="KRW", tenant_key="demo-im-bank")
        session.add(inst)
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()

        v = Voucher(company_id=company.id, source="hometax", year=YEAR, month=7, item_description="경유", supply_amount_krw=100000)
        session.add(v)
        session.flush()
        session.add(Classification(
            voucher_id=v.id, scope=1, fuel_type="경유", amount_krw=100000,
            emission_co2e=500.0, confidence=0.9, method="rule", status="auto",
        ))
        session.commit()
        yield session, company.id, inst.id
    engine.dispose()


@pytest.fixture()
def client(db):
    session, _, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_financed_emissions_data(session, company_id, institution_id):
    """대출잔액·재무정보·배출량 인벤토리를 모두 갖춘 mock 시나리오 — 산식이
    실제로 계산되는 경로를 테스트한다."""
    boundary = OrganizationalBoundary(
        financial_institution_id=institution_id, company_id=company_id,
        reporting_year=YEAR, boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.flush()

    session.add(BorrowerFinancial(
        financial_institution_id=institution_id, company_id=company_id,
        financial_year=YEAR, as_of_date=datetime(YEAR, 12, 31, tzinfo=timezone.utc),
        currency="KRW", total_equity=200_000_000, total_debt=800_000_000,
    ))
    session.add(BorrowerEmissionInventory(
        financial_institution_id=institution_id, company_id=company_id,
        reporting_year=YEAR, organizational_boundary_id=boundary.id,
        scope_group="scope_1", emission_tco2e=100.0, status="approved",
    ))
    portfolio = Portfolio(
        financial_institution_id=institution_id, name="테스트 포트폴리오",
        reporting_year=YEAR, reporting_currency="KRW",
        scope_mode="supported_business_loans", status="draft",
    )
    session.add(portfolio)
    session.flush()
    session.add(BusinessLoanExposure(
        portfolio_id=portfolio.id, company_id=company_id,
        external_exposure_id="TEST-1", asset_class="business_loans_and_unlisted_equity",
        outstanding_amount=300_000_000, currency="KRW",
        reporting_date=datetime(YEAR, 12, 31, tzinfo=timezone.utc),
    ))
    session.commit()


def test_json_response_has_four_sections(db, client):
    res = client.get("/admin/climate-risk-report")
    assert res.status_code == 200
    body = res.json()
    assert "governance" in body
    assert "strategy" in body
    assert "risk_assessment" in body
    assert "disclosure" in body


def test_verification_error_rate_marked_pending(db, client):
    res = client.get("/admin/climate-risk-report")
    body = res.json()
    assert body["disclosure"]["verification_error_rate"]["status"] == "pending"


def test_financed_emissions_empty_when_no_portfolio_seeded(db, client):
    """대출 데이터가 전혀 없으면(이 fixture의 기본 상태) 빈 배열 — 하드코딩
    예시값으로 채워지지 않는다."""
    res = client.get("/admin/climate-risk-report")
    body = res.json()
    timeline = body["financed_emissions_timeline"]
    assert timeline["is_example"] is True
    assert timeline["years"] == []


def test_financed_emissions_computed_from_seeded_mock_data(db, client):
    """대출잔액·재무정보·배출량 인벤토리가 모두 있으면 산식으로 실제 계산된다
    — 3억/(2억+8억)=0.3, 0.3×100tCO2e=30tCO2e."""
    session, company_id, institution_id = db
    _seed_financed_emissions_data(session, company_id, institution_id)

    res = client.get("/admin/climate-risk-report")
    body = res.json()
    timeline = body["financed_emissions_timeline"]
    assert timeline["is_example"] is True
    assert len(timeline["years"]) == 1
    year_row = timeline["years"][0]
    assert year_row["year"] == YEAR
    assert year_row["financed_emission_tco2e"] == pytest.approx(30.0)
    assert year_row["company_count"] == 1


def test_risk_assessment_reuses_portfolio_grade_distribution(db, client):
    """새 계산 없음 — portfolio_summary()가 낸 값 그대로여야 한다."""
    from db.pcaf_engine.pcaf import portfolio_summary

    session, _, _ = db
    expected = portfolio_summary(session)

    res = client.get("/admin/climate-risk-report")
    body = res.json()
    # JSON 직렬화 과정에서 dict 키가 문자열로 바뀐다(FastAPI 기본 동작) — 키를
    # 맞춰서 비교한다. 값 자체는 재계산 없이 portfolio_summary() 그대로여야 한다.
    assert body["risk_assessment"]["grade_distribution"] == {
        str(k): v for k, v in expected["grade_distribution"].items()
    }
    assert body["strategy"]["company_count"] == expected["company_count"]


def test_pdf_format_returns_valid_pdf(db, client):
    res = client.get("/admin/climate-risk-report?format=pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"

    with pdfplumber.open(__import__("io").BytesIO(res.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "기후리스크" in text
    assert "산정 예정" in text
    assert "예시 값" in text or "예시 데이터" in text
