"""PCAF 데이터 품질 후보(db/pcaf_quality.py) 골든 케이스.

PCAF Standard Part A Third Edition, Table 10.1-2(Annex p.192) 원문 옵션 체계
(1a/1b/2a/2b/3a/3b/3c)를 기준으로 검증한다.

핵심 검증축:
  - 분류 신뢰도(HITL)와 PCAF 품질점수는 완전히 분리된 축이다(§6.1, §6.4).
  - 활동자료 근거(생산량 vs 매출 환산)에 따라 다른 옵션이 매칭된다.
  - 완전성(completeness_pct)과 품질 후보(candidate_score)는 서로 다른 필드·다른 계산 경로다.
  - Scope 1·2와 Scope 3는 원문상 같은 옵션 체계를 공유하되(별도 표 없음), 이 프로젝트가
    Scope 3 데이터를 아직 만들지 않아 결과가 갈린다 — 0으로 합산되지 않는다.
  - status는 항상 "candidate" — 자동 승인되지 않는다(CLAUDE.md §9).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.init_db import seed_pcaf_quality_rules
from db.models import (
    Base,
    Classification,
    Company,
    FinancialInstitution,
    OrganizationalBoundary,
    Voucher,
)
from db.pcaf_quality import (
    assess_borrower_emission_quality,
    assess_inventory_completeness,
    classify_activity_data_method,
)

YEAR = 2026


@pytest.fixture()
def db(tmp_path):
    # TestClient가 별도 스레드에서 같은 세션을 쓰므로(:memory:는 스레드 간 공유 불가)
    # 파일 DB로 연결을 공유한다 — tests/test_admin.py의 db 픽스처와 동일 패턴.
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_pcaf_quality_rules(session)
        company = Company(name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조")
        session.add(company)
        session.commit()
        yield session, company.id


def _add_voucher(session, cid, month, item, *, quantity=None, scope=1, status="auto"):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
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


# ── PCAF 시드 데이터 자체가 원문과 일치하는지 ────────────────────────────────
def test_seed_creates_seven_options_matching_table_10_1_2(db):
    """Table 10.1-2 원문의 7개 옵션(1a/1b/2a/2b/3a/3b/3c)이 정확한 점수로 적재된다."""
    from db.models import PcafQualityRule
    session, _ = db
    rules = {r.option_code: r for r in session.query(PcafQualityRule).all()}

    assert set(rules) == {"1a", "1b", "2a", "2b", "3a", "3b", "3c"}
    assert rules["1a"].quality_score == 1 and rules["1a"].activity_data_basis == "verified_emissions"
    assert rules["1b"].quality_score == 2 and rules["1b"].activity_data_basis == "unverified_emissions"
    assert rules["2a"].quality_score == 2 and rules["2a"].activity_data_basis == "energy_consumption"
    assert rules["2b"].quality_score == 3 and rules["2b"].activity_data_basis == "production"
    assert rules["3a"].quality_score == 4 and rules["3a"].activity_data_basis == "revenue"
    assert rules["3b"].quality_score == 5 and rules["3b"].activity_data_basis == "assets"
    assert rules["3c"].quality_score == 5 and rules["3c"].activity_data_basis == "asset_turnover_ratio"


def test_option_2a_does_not_apply_to_scope3(db):
    """원문 각주 208 — Option 2a(에너지 소비량)는 Scope 3에 적용 불가."""
    from db.models import PcafQualityRule
    session, _ = db
    rule_2a = session.query(PcafQualityRule).filter_by(option_code="2a").one()
    rule_2b = session.query(PcafQualityRule).filter_by(option_code="2b").one()
    assert rule_2a.applies_to_scope3 is False
    assert rule_2b.applies_to_scope3 is True


# ── classify_activity_data_method ───────────────────────────────────────────
def test_production_basis_when_voucher_has_measured_quantity(db):
    """전표에 실측 수량이 있으면 production(물리적 활동자료) — 2등급 고정 아님."""
    session, cid = db
    vid = _add_voucher(session, cid, 1, "도시가스", quantity=100)
    voucher = session.query(Voucher).filter_by(id=vid).one()
    classification = voucher.classification
    assert classify_activity_data_method(voucher, classification) == "production"


def test_revenue_basis_when_voucher_has_no_quantity(db):
    """수량 없이 금액만 있으면 revenue(경제자료 환산) — 3등급 고정이 아니라 근거 라벨일 뿐."""
    session, cid = db
    vid = _add_voucher(session, cid, 1, "유류대금")
    voucher = session.query(Voucher).filter_by(id=vid).one()
    classification = voucher.classification
    assert classify_activity_data_method(voucher, classification) == "revenue"


# ── assess_inventory_completeness ───────────────────────────────────────────
def test_completeness_pct_separate_from_candidate_score(db):
    """완전성(§6.3)과 품질 후보(§6.4)는 서로 다른 필드·경로 — 완전성 계산이 품질점수에 직접 곱해지지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    completeness = assess_inventory_completeness(session, cid, YEAR)
    quality = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")

    assert completeness.completeness_pct == quality["completeness_pct"]
    assert "candidate_score" not in completeness.__dict__
    assert quality["candidate_score"] is not None


def test_missing_months_reported_by_fuel(db):
    """일부 월만 채워진 경우 결손월이 연료별로 정확히 집계된다."""
    session, cid = db
    for m in (1, 2, 3):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    completeness = assess_inventory_completeness(session, cid, YEAR)
    assert completeness.missing_months["가스"] == list(range(4, 13))


# ── assess_borrower_emission_quality — 활동자료 근거별 옵션 매칭 ─────────────
def test_production_data_scores_higher_than_revenue_estimate(db):
    """생산량 기반(2b, Score 3)이 매출 환산(3a, Score 4)보다 높은 품질(작은 숫자)로 평가된다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    production_result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")

    company2 = Company(name="타사", industry_code="C251")
    session.add(company2)
    session.commit()
    for m in range(1, 13):
        _add_voucher(session, company2.id, m, "유류대금")
    revenue_result = assess_borrower_emission_quality(session, company2.id, YEAR, "scope_1_2")

    assert production_result["candidate_score"] < revenue_result["candidate_score"]
    assert production_result["option_code"] == "2b"
    assert production_result["candidate_score"] == 3
    assert revenue_result["option_code"] == "3a"
    assert revenue_result["candidate_score"] == 4


def test_mixed_data_within_year_uses_dominant_basis(db):
    """혼합 데이터 — 더 많이 쓰인 활동자료 근거를 대표값으로 매칭한다."""
    session, cid = db
    for m in range(1, 9):  # 8개월 production
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    for m in (9, 10, 11, 12):  # 4개월 revenue
        _add_voucher(session, cid, m, "유류대금")

    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")
    assert result["option_code"] == "2b"  # production이 다수


# ── HITL 분리 (§6.1) ─────────────────────────────────────────────────────────
def test_hitl_review_required_does_not_change_quality_score(db):
    """분류 신뢰도(status=review_required)가 있어도 PCAF 품질점수 계산 로직은 이를 참조하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, status="review_required")

    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")
    assert result["candidate_score"] is not None
    assert result["option_code"] == "2b"


# ── Scope 분리 ────────────────────────────────────────────────────────────────
def test_scope_1_2_and_scope_3_assessed_separately(db):
    """Scope 1·2와 Scope 3는 독립적으로 평가되며 서로 점수를 공유하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    s12 = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")
    s3 = assess_borrower_emission_quality(session, cid, YEAR, "scope_3")

    assert s12["scope_group"] == "scope_1_2"
    assert s3["scope_group"] == "scope_3"
    assert s12["candidate_score"] is not None
    assert s3["candidate_score"] is None  # 이 프로젝트가 Scope 3 데이터를 만들지 않음


def test_scope3_not_calculated_not_treated_as_zero(db):
    """Scope 3 미산정은 candidate_score=None 으로만 표시되고 0으로 합산되지 않는다."""
    session, cid = db
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_3")
    assert result["candidate_score"] is None
    assert result["candidate_score"] != 0
    assert result["limitations"]


# ── status 불변식 (CLAUDE.md §9) ─────────────────────────────────────────────
def test_status_always_candidate_never_auto_approved(db):
    """자동 산정 결과는 항상 candidate — 은행 담당자 승인 전에는 확정하지 않는다."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    for scope_group in ("scope_1_2", "scope_3"):
        result = assess_borrower_emission_quality(session, cid, YEAR, scope_group)
        assert result["status"] == "candidate"
        assert result["bank_review_required"] is True


def test_no_activity_data_yields_no_candidate_with_limitation(db):
    """분류가 아예 없으면 candidate_score=None + 명확한 사유를 반환(추정으로 채우지 않음)."""
    session, cid = db
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")
    assert result["candidate_score"] is None
    assert result["limitations"]


# ── build_quality_evidence ───────────────────────────────────────────────────
def test_quality_evidence_includes_rule_source_reference(db):
    """basis에 적용 옵션의 원문 근거(source_reference)가 포함된다 — 판정 근거 역추적 가능."""
    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)
    result = assess_borrower_emission_quality(session, cid, YEAR, "scope_1_2")
    assert any("Table 10.1-2" in b for b in result["basis"])
    assert any("2b" in b for b in result["basis"])


# ── API 라우터 (evaluate 저장·버전 체인) ──────────────────────────────────────
@pytest.fixture()
def api_client(db):
    from fastapi.testclient import TestClient
    from api.db import get_session
    from api.main import app

    session, cid = db
    inst = FinancialInstitution(name="테스트기관", reporting_currency="KRW", tenant_key="test-bank")
    session.add(inst)
    session.commit()
    boundary = OrganizationalBoundary(
        financial_institution_id=inst.id, company_id=cid, reporting_year=YEAR,
        boundary_type="operational_control", consolidation_scope="separate",
    )
    session.add(boundary)
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app), session, cid
    app.dependency_overrides.clear()


def test_evaluate_endpoint_persists_and_versions(api_client):
    """POST evaluate가 Scope 1·2 인벤토리 행을 저장하고, 재호출 시 버전이 증가한다."""
    client, session, cid = api_client

    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    res1 = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res1.status_code == 200, res1.text
    assessments1 = res1.json()["assessments"]
    assert {a["scope_group"] for a in assessments1} == {"scope_1", "scope_2"}
    assert all(a["version"] == 1 for a in assessments1)
    assert all(a["status"] == "draft" for a in assessments1)

    res2 = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
    assert res2.status_code == 200, res2.text
    assert all(a["version"] == 2 for a in res2.json()["assessments"])

    get_res = client.get(f"/borrowers/{cid}/quality-assessments/{YEAR}")
    assert get_res.status_code == 200
    assert all(a["version"] == 2 for a in get_res.json()["assessments"])


def test_evaluate_without_boundary_fails_clearly(db):
    """조직경계 미등록 시 목업으로 채우지 않고 409로 명확히 실패한다."""
    from fastapi.testclient import TestClient
    from api.db import get_session
    from api.main import app

    session, cid = db
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100)

    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    try:
        res = client.post(f"/borrowers/{cid}/quality-assessments/{YEAR}/evaluate")
        assert res.status_code == 409
    finally:
        app.dependency_overrides.clear()
