"""기후리스크 리포트 — 금감원 4단계 구조 (v1 Tier 2, owner-admin-flow-spec.md §6,
docs/tasks.md).

핵심 검증축:
  - portfolio_summary()를 재계산 없이 4단계(거버넌스/전략/리스크평가/공시) 틀로
    재배열한다 — 신규 계산 로직 없음.
  - 검증 오차율은 "산정 예정"으로, 시계열 금융배출량은 "예시 데이터(is_example)"
    로 명시된다 — 실측인 것처럼 보이지 않아야 한다.
  - format=pdf는 유효한 PDF 바이트를 반환한다.
"""
import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.models import Base, Classification, Company, FinancialInstitution, Voucher

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
        yield session, company.id
    engine.dispose()


@pytest.fixture()
def client(db):
    session, _ = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


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


def test_financed_emissions_marked_as_example(db, client):
    res = client.get("/admin/climate-risk-report")
    body = res.json()
    timeline = body["financed_emissions_timeline"]
    assert timeline["is_example"] is True
    assert len(timeline["years"]) == 3


def test_risk_assessment_reuses_portfolio_grade_distribution(db, client):
    """새 계산 없음 — portfolio_summary()가 낸 값 그대로여야 한다."""
    from db.pcaf import portfolio_summary

    session, _ = db
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
