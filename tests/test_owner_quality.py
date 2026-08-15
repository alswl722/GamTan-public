"""사장님 리포트용 PCAF 정식 엔진 래퍼(api/routers/owner_quality.py) 골든 케이스.

핵심 검증축:
  - 조직경계가 없으면 간이화 가정(operational_control/separate)으로 자동 생성된다
    (db/organizational_boundary.py — 회계 검수 필요 플래그가 붙은 임시 정책).
  - 기관 귀속(institution_borrowers) 자체가 없으면 자동 생성도 못 하고 422로
    명확히 실패한다(CLAUDE.md 실패 가시성 원칙).
  - 최초 조회 시 평가가 자동 산정·저장되고, 재조회는 같은 버전을 반환한다(매번
    새 버전을 만들지 않음).
  - 벤치마크(동종업계 대비)는 Scope1+2 합계로 계산된다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.init_db import seed_industry_distributions, seed_pcaf_quality_rules
from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    InstitutionBorrower,
    OrganizationalBoundary,
    Voucher,
)
from db.organizational_boundary import ensure_organizational_boundary

YEAR = 2026


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_pcaf_quality_rules(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_500_000_000,
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_institution_borrower(session, cid, *, consent_status="active"):
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    ib = InstitutionBorrower(
        financial_institution_id=inst.id, company_id=cid,
        external_customer_id=f"cust-{cid}", consent_status=consent_status,
    )
    session.add(ib)
    session.commit()
    return inst.id


def _add_voucher(session, cid, month, item, *, quantity=100, scope=1, status="auto"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000, raw_json={"quantity": quantity},
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type="도시가스",
        amount_krw=100000, emission_co2e=500.0, confidence=0.9,
        evidence="테스트", method="rule", status=status,
    ))
    session.commit()
    return v.id


# ── ensure_organizational_boundary 순수 로직 ──────────────────────────────────
def test_ensure_boundary_creates_with_simplified_defaults_when_missing(db):
    session, cid = db
    inst_id = _add_institution_borrower(session, cid)

    boundary = ensure_organizational_boundary(session, cid, YEAR)

    assert boundary.company_id == cid
    assert boundary.reporting_year == YEAR
    assert boundary.financial_institution_id == inst_id
    assert boundary.boundary_type == "operational_control"
    assert boundary.consolidation_scope == "separate"
    assert "회계 검수" in (boundary.description or "")


def test_ensure_boundary_returns_existing_without_duplicating(db):
    """기존 레코드(은행 담당자가 정식 등록한 것 포함)가 있으면 그대로 반환한다."""
    session, cid = db
    inst_id = _add_institution_borrower(session, cid)
    existing = OrganizationalBoundary(
        financial_institution_id=inst_id, company_id=cid, reporting_year=YEAR,
        boundary_type="financial_control", consolidation_scope="consolidated",
    )
    session.add(existing)
    session.commit()

    boundary = ensure_organizational_boundary(session, cid, YEAR)

    assert boundary.id == existing.id
    assert boundary.boundary_type == "financial_control"  # 자동생성 기본값으로 덮어쓰지 않음

    count = session.query(OrganizationalBoundary).filter_by(company_id=cid, reporting_year=YEAR).count()
    assert count == 1


def test_ensure_boundary_fails_clearly_without_institution_borrower(db):
    """기관 귀속이 아예 없으면 목업으로 채우지 않고 명확히 실패한다(실패 가시성 원칙)."""
    session, cid = db
    with pytest.raises(ValueError, match="기관 귀속"):
        ensure_organizational_boundary(session, cid, YEAR)


# ── GET /owner/{id}/quality-report API ────────────────────────────────────────
@pytest.fixture()
def api_client(db):
    from fastapi.testclient import TestClient
    from api.db import get_session
    from api.main import app

    session, cid = db
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app), session, cid
    app.dependency_overrides.clear()


def test_quality_report_auto_provisions_boundary_and_first_version(api_client):
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스")

    res = client.get(f"/owner/{cid}/quality-report?year={YEAR}")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["reporting_year"] == YEAR
    assert body["scope_1"]["version"] == 1
    assert body["scope_1"]["bank_review_required"] is True
    assert body["scope_1"]["status"] == "draft"
    assert body["scope_2"]["version"] == 1
    # 조직경계가 실제로 생성됐는지
    assert session.query(OrganizationalBoundary).filter_by(company_id=cid, reporting_year=YEAR).count() == 1


def test_quality_report_defaults_to_latest_year_with_data_not_calendar_year(api_client):
    """year 파라미터를 생략하면 달력상 올해가 아니라 그 기업 전표가 실제로 있는
    가장 최근 연도를 기본값으로 쓴다 — 결산 데이터가 항상 "올해"일 필요는 없고,
    "올해"로 고정하면 데이터가 전부 과거 연도인 기업은 리포트가 늘 텅 비어 보인다."""
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    past_year = YEAR - 1  # 달력상 "올해"(YEAR)와 다른 연도임을 명확히 하기 위해
    for m in range(1, 13):
        v = Voucher(
            company_id=cid, source="hometax", year=past_year, month=m,
            supplier_name="테스트", item_description="도시가스",
            supply_amount_krw=100000, raw_json={"quantity": 100},
        )
        session.add(v)
        session.flush()
        session.add(Classification(
            voucher_id=v.id, scope=1, category="고정연소", fuel_type="도시가스",
            amount_krw=100000, emission_co2e=500.0, confidence=0.9,
            evidence="테스트", method="rule", status="auto",
        ))
    session.commit()

    res = client.get(f"/owner/{cid}/quality-report")  # year 생략
    body = res.json()

    assert body["reporting_year"] == past_year
    assert body["scope_1"]["emission_tco2e"] is not None


def test_quality_report_reuses_saved_version_on_repeat_calls(api_client):
    """재조회는 저장된 최신 버전을 그대로 반환한다 — 조회할 때마다 새 버전을 안 만든다."""
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스")

    res1 = client.get(f"/owner/{cid}/quality-report?year={YEAR}")
    res2 = client.get(f"/owner/{cid}/quality-report?year={YEAR}")

    assert res1.json()["scope_1"]["version"] == 1
    assert res2.json()["scope_1"]["version"] == 1


def test_quality_report_benchmark_uses_scope1_plus_scope2_total(api_client):
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", scope=1)
        _add_voucher(session, cid, m, "전기요금", scope=2)

    res = client.get(f"/owner/{cid}/quality-report?year={YEAR}")
    body = res.json()

    expected_total = body["scope_1"]["emission_tco2e"] + body["scope_2"]["emission_tco2e"]
    assert body["benchmark"]["value"] == pytest.approx(expected_total, abs=0.01)


def test_quality_report_fails_clearly_when_institution_borrower_missing(api_client):
    """기관 귀속이 없으면(마이데이터 동의 전) 자동 생성 자체가 불가 — 422로 명확히 실패."""
    client, session, cid = api_client

    res = client.get(f"/owner/{cid}/quality-report?year={YEAR}")
    assert res.status_code == 422


def test_quality_report_404_for_unknown_company(api_client):
    client, session, cid = api_client
    res = client.get(f"/owner/99999/quality-report?year={YEAR}")
    assert res.status_code == 404


# ── GET /owner/{id}/emission-detail — Scope 카드 상세보기 ──────────────────────
def test_emission_detail_matches_quality_report_total(api_client):
    """상세 목록 항목들의 emission_co2e 합이 quality-report의 emission_tco2e와 일치한다
    — 카드에 보이는 숫자와 펼쳤을 때 보이는 전표 목록이 항상 맞아야 함."""
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", scope=1)

    report = client.get(f"/owner/{cid}/quality-report?year={YEAR}").json()
    res = client.get(f"/owner/{cid}/emission-detail?scope_group=scope_1&year={YEAR}")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["scope_group"] == "scope_1"
    assert body["reporting_year"] == YEAR
    assert len(body["items"]) == 12
    detail_sum_tco2e = round(sum(item["emission_co2e"] for item in body["items"]) / 1000.0, 2)
    assert detail_sum_tco2e == report["scope_1"]["emission_tco2e"]


def test_emission_detail_empty_for_scope_without_data(api_client):
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", scope=1)

    res = client.get(f"/owner/{cid}/emission-detail?scope_group=scope_2&year={YEAR}")
    assert res.status_code == 200
    assert res.json()["items"] == []


# ── GET /owner/{id}/reporting-years (연도 선택기) ──────────────────────────────
def test_reporting_years_lists_all_years_with_vouchers_newest_first(api_client):
    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스")
    for m in range(1, 13):
        v = Voucher(
            company_id=cid, source="hometax", year=YEAR - 1, month=m,
            supplier_name="테스트", item_description="도시가스",
            supply_amount_krw=100000, raw_json={"quantity": 100},
        )
        session.add(v)
    session.commit()

    res = client.get(f"/owner/{cid}/reporting-years")
    assert res.status_code == 200
    assert res.json()["years"] == [YEAR, YEAR - 1]


def test_reporting_years_empty_when_no_vouchers(api_client):
    client, session, cid = api_client
    res = client.get(f"/owner/{cid}/reporting-years")
    assert res.status_code == 200
    assert res.json()["years"] == []


def test_reporting_years_404_for_unknown_company(api_client):
    client, _, _ = api_client
    res = client.get("/owner/999999/reporting-years")
    assert res.status_code == 404


# ── format=pdf (탄소배출량 산정 결과서, db/owner_report_pdf.py) ──────────────────
def test_quality_report_pdf_returns_valid_pdf_bytes(api_client):
    """format=pdf는 새 계산 없이 같은 산정값을 PDF로 내려준다 — 회사명·연료별
    내역·PCAF 등급이 실제로 렌더링됐는지 pdfplumber로 텍스트까지 확인한다
    (admin.py의 audit-package PDF 테스트와 같은 검증 깊이)."""
    import io

    import pdfplumber

    client, session, cid = api_client
    _add_institution_borrower(session, cid)
    # 도시가스만 선택 — 안 쓰는 연료(경유/유류)까지 결손 후보로 잡히면 약한 고리
    # 원칙(db/pcaf_quality.py)에 따라 4등급으로 떨어져 이 테스트의 "실측 → 2등급"
    # 전제가 깨진다(db/rate_products.py 테스트 픽스처와 같은 이유로 명시).
    session.get(Company, cid).fuel_types_json = {"city_gas": True, "electricity": True}
    session.commit()
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스")

    res = client.get(f"/owner/{cid}/quality-report?year={YEAR}&format=pdf")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert f"gamtan_report_{YEAR}.pdf" in res.headers["content-disposition"]
    assert res.content[:4] == b"%PDF"

    with pdfplumber.open(io.BytesIO(res.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "○○정밀" in text
    assert "탄소배출량 산정 결과서" in text
    assert "도시가스" in text
    assert "2등급" in text  # 12개월 전부 실측 → energy_consumption(2등급)
    assert "Scope 3" in text  # 산정 범위에서 제외된다는 안내 문구
    assert "12명" in text  # employee_count — 환경부 별지 제11호 서식의 상시종업원수 항목 참고
    assert "2,500백만원" in text  # revenue_krw — 같은 서식의 매출액(백만원) 항목 참고
