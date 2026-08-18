"""사장님 목표 설정(db/pcaf_engine/company_goals.py) 골든 케이스.

핵심 검증축:
  - 기업당 활성 목표는 최대 1개 — 새 목표를 만들면 기존 활성 목표는 superseded로
    전환된다(덮어쓰지 않음, CLAUDE.md 원칙8과 같은 결).
  - 등급 목표는 우대금리 상품 매칭과 같은 엔진을 쓴다 — 추천 목표와 정확히 일치할
    때만 target_product_name이 채워지고, 사용자가 다른 등급을 고르면 비운다(지어낸
    매칭 금지).
  - 감축 목표는 같은 보고연도 안에서는 비교 대상이 없다(measured=False) — 보고연도가
    넘어가야 실제로 비교한다(가짜 진행률 금지, 실패 가시성 원칙과 같은 결).
  - 목표 달성 조건을 만족하면 조회 시점에 status가 'achieved'로 전환되고 유지된다.
  - 등급 목표 진행률은 원칙10 비보장 문구(DISCLAIMER_TEXT)를 항상 동봉한다.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.db import get_session
from api.main import app
from db.init_db import seed_pcaf_quality_rules, seed_rate_products
from db.models import Base, Classification, Company, Voucher
from db.pcaf_engine.company_goals import (
    CompanyNotFoundError,
    DISCLAIMER_TEXT,
    GoalNotFoundError,
    InvalidTargetGradeError,
    NoActivityDataError,
    NoEmissionDataError,
    cancel_goal,
    create_emission_reduction_goal,
    create_grade_upgrade_goal,
    get_active_goal_progress,
)

YEAR = datetime.now(timezone.utc).year


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_pcaf_quality_rules(session)
        seed_rate_products(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
            fuel_types_json={"city_gas": True, "electricity": True},
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


def _add_voucher(session, cid, month, item, *, quantity, scope=1, emission=100.0, fuel_type="도시가스", year=YEAR):
    v = Voucher(
        company_id=cid, source="hometax", year=year, month=month,
        supplier_name="테스트", item_description=item,
        supply_amount_krw=100000,
        raw_json={"quantity": quantity} if quantity is not None else {},
    )
    session.add(v)
    session.flush()
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="고정연소", fuel_type=fuel_type,
        amount_krw=100000, emission_co2e=emission, confidence=0.9,
        evidence="테스트", method="rule", status="auto",
    ))
    session.commit()
    return v.id


def _fill_scope_1_measured(session, cid, *, year=YEAR):
    """12개월 실측 수량(energy_consumption, 2등급) — eligible 상태를 만든다."""
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, year=year)


def _fill_scope_1_revenue(session, cid, *, year=YEAR):
    """12개월 수량 없음(revenue, 4등급) — upgrade_needed 상태를 만든다."""
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=None, scope=1, year=year)


# ── 배출량 감축 목표 ──────────────────────────────────────────────────────────
def test_create_emission_reduction_goal_snapshots_baseline_and_target(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)

    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=20)
    assert goal.goal_type == "emission_reduction"
    assert goal.baseline_value == pytest.approx(1.2)  # 12개월 * 100kg / 1000
    assert goal.target_value == pytest.approx(1.2 * 0.8)
    assert goal.target_reduction_pct == 20
    assert goal.status == "active"


def test_create_emission_reduction_goal_fails_without_emission_data(db):
    session, cid = db
    with pytest.raises(NoEmissionDataError):
        create_emission_reduction_goal(session, cid, target_reduction_pct=20)


def test_create_emission_reduction_goal_rejects_out_of_range_pct(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)
    with pytest.raises(ValueError):
        create_emission_reduction_goal(session, cid, target_reduction_pct=0)
    with pytest.raises(ValueError):
        create_emission_reduction_goal(session, cid, target_reduction_pct=100)


def test_create_emission_reduction_goal_unknown_company_raises(db):
    session, _ = db
    with pytest.raises(CompanyNotFoundError):
        create_emission_reduction_goal(session, 99999, target_reduction_pct=20)


def test_emission_reduction_progress_not_measured_within_same_reporting_year(db):
    """같은 보고연도 안에서는 비교 대상이 없다 — 결손월이 채워질수록 총량이 느는 게
    정상이라 "감축" 판단 근거가 못 된다(가짜 진행률 금지)."""
    session, cid = db
    _fill_scope_1_measured(session, cid)
    create_emission_reduction_goal(session, cid, target_reduction_pct=20)

    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is False
    assert progress["achieved"] is False
    assert progress["progress_pct"] == 0.0
    assert progress["status"] == "active"


def test_emission_reduction_progress_measured_after_year_rollover(db, monkeypatch):
    """보고연도가 넘어가면 다음 해 총 배출량과 비교해 실제로 진행률을 계산한다."""
    session, cid = db
    _fill_scope_1_measured(session, cid)  # 12개월 * 100kg = 1.2 tCO2e (baseline)
    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=50)  # target 0.6

    next_year = YEAR + 1
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=50.0, year=next_year)

    monkeypatch.setattr("db.pcaf_engine.company_goals.default_reporting_year", lambda *a, **k: next_year)
    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is True
    assert progress["current_value"] == pytest.approx(0.6)  # 12 * 50kg / 1000
    assert progress["achieved"] is True
    assert progress["status"] == "achieved"

    session.refresh(goal)
    assert goal.status == "achieved"
    assert goal.achieved_at is not None


# ── 등급 상승(＋혜택) 목표 ────────────────────────────────────────────────────
def test_create_grade_upgrade_goal_upgrade_needed_uses_recommended_target_and_product(db):
    session, cid = db
    _fill_scope_1_revenue(session, cid)

    goal = create_grade_upgrade_goal(session, cid, scope_group="scope_1")
    assert goal.baseline_value == 4
    assert goal.target_value == 2
    assert goal.target_product_name == "ESG Grow-Up 특별대출"
    assert goal.status == "active"


def test_create_grade_upgrade_goal_eligible_creates_already_at_target(db):
    """이미 자격을 충족한 상태에서도 목표를 세울 수 있다 — baseline==target, 다음
    조회에서 바로 달성 처리된다."""
    session, cid = db
    _fill_scope_1_measured(session, cid)

    goal = create_grade_upgrade_goal(session, cid, scope_group="scope_1")
    assert goal.baseline_value == 2
    assert goal.target_value == 2
    assert goal.target_product_name == "ESG Grow-Up 특별대출"

    progress = get_active_goal_progress(session, cid)
    assert progress["achieved"] is True
    assert progress["status"] == "achieved"


def test_create_grade_upgrade_goal_custom_target_clears_product_name(db):
    """추천 목표와 다른 등급을 직접 고르면 그 등급에서 실제 자격이 열리는지 보장할 수
    없으므로 상품명을 비워둔다(지어낸 매칭 금지)."""
    session, cid = db
    _fill_scope_1_revenue(session, cid)

    goal = create_grade_upgrade_goal(session, cid, scope_group="scope_1", target_grade=3)
    assert goal.target_value == 3
    assert goal.target_product_name is None


def test_create_grade_upgrade_goal_rejects_target_worse_than_current(db):
    session, cid = db
    _fill_scope_1_revenue(session, cid)  # current_grade == 4
    with pytest.raises(InvalidTargetGradeError):
        create_grade_upgrade_goal(session, cid, scope_group="scope_1", target_grade=5)


def test_create_grade_upgrade_goal_fails_without_activity_data(db):
    session, cid = db
    with pytest.raises(NoActivityDataError):
        create_grade_upgrade_goal(session, cid, scope_group="scope_1")


def test_grade_upgrade_progress_includes_missing_items_and_disclaimer(db):
    session, cid = db
    _fill_scope_1_revenue(session, cid)
    create_grade_upgrade_goal(session, cid, scope_group="scope_1")

    progress = get_active_goal_progress(session, cid)
    assert progress["achieved"] is False
    assert progress["disclaimer_text"] == DISCLAIMER_TEXT
    assert isinstance(progress["missing_items"], list)


def test_grade_upgrade_progress_monthly_coverage_fills_gradually(db):
    """월별 커버리지 막대 — 홈 박스 링·바 차트가 그대로 쓰는 데이터. 이번 해 경과월 전부를
    결손 없이 채우면(단, 실측/매출환산이 섞여 아직 achieved는 아님) completeness 기준
    진행률이 100%여야 한다 — 등급 격차 기준이면 4등급 그대로라 계속 0%로 보이는 문제를
    완전성 기준으로 피한다. create_grade_upgrade_goal은 항상 "지금 이 시점"을 보고연도로
    쓰므로(default_reporting_year) 과거 연도가 아니라 이번 해 경과월로 채운다."""
    session, cid = db
    current_month = datetime.now(timezone.utc).month
    for m in range(1, current_month + 1):
        # 홀수 달은 매출환산(quantity=None)을 섞어 결손은 없지만 achieved는 아니게 만든다.
        quantity = None if m % 2 else 100
        _add_voucher(session, cid, m, "도시가스", quantity=quantity, scope=1)

    create_grade_upgrade_goal(session, cid, scope_group="scope_1")
    progress = get_active_goal_progress(session, cid)

    assert progress["achieved"] is False
    assert all(item["covered"] for item in progress["monthly_coverage"])
    assert len(progress["monthly_coverage"]) == current_month
    assert progress["progress_pct"] == 100.0


def test_grade_upgrade_progress_monthly_coverage_reflects_missing_months(db):
    session, cid = db
    current_month = datetime.now(timezone.utc).month
    for m in (1, 2, 3):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1)

    create_grade_upgrade_goal(session, cid, scope_group="scope_1")
    progress = get_active_goal_progress(session, cid)

    covered_months = {item["month"] for item in progress["monthly_coverage"] if item["covered"]}
    assert covered_months == {1, 2, 3}
    assert len(progress["monthly_coverage"]) == current_month
    assert progress["progress_pct"] == pytest.approx(3 / current_month * 100, abs=0.1)


def test_emission_reduction_progress_includes_monthly_emission_even_when_not_measured(db):
    """같은 보고연도 안(measured=False)이어도 월별 배출량 막대 데이터는 내려줘야
    홈 박스가 "활동 현황"을 보여줄 수 있다."""
    session, cid = db
    _fill_scope_1_measured(session, cid)
    create_emission_reduction_goal(session, cid, target_reduction_pct=20)

    progress = get_active_goal_progress(session, cid)
    current_month = datetime.now(timezone.utc).month
    assert progress["measured"] is False
    assert len(progress["monthly_emission"]) == current_month
    # _fill_scope_1_measured는 1~12월 전부 채우지만, 월별 막대는 "아직 안 온 달"을
    # 제외한 경과월까지만 집계한다(assess_inventory_completeness와 같은 규칙) —
    # 달마다 100kg=0.1tCO2e씩이므로 경과월 수 * 0.1이 합계가 된다.
    assert sum(item["emission_tco2e"] for item in progress["monthly_emission"]) == pytest.approx(
        current_month * 0.1
    )


# ── 활성 목표는 항상 1개 ──────────────────────────────────────────────────────
def test_new_goal_supersedes_existing_active_goal(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)

    first = create_emission_reduction_goal(session, cid, target_reduction_pct=10)
    second = create_grade_upgrade_goal(session, cid, scope_group="scope_1")

    session.refresh(first)
    assert first.status == "superseded"
    assert second.status == "active"

    progress = get_active_goal_progress(session, cid)
    assert progress["id"] == second.id


# ── 목표 없음 / 취소 ──────────────────────────────────────────────────────────
def test_get_active_goal_progress_returns_none_when_no_goal(db):
    session, cid = db
    assert get_active_goal_progress(session, cid) is None


def test_cancel_goal_marks_cancelled(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)
    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    cancelled = cancel_goal(session, cid, goal.id)
    assert cancelled.status == "cancelled"
    assert get_active_goal_progress(session, cid) is None


def test_cancel_goal_rejects_other_companys_goal(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)
    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    other = Company(name="타사", industry_code="C251")
    session.add(other)
    session.commit()

    with pytest.raises(GoalNotFoundError):
        cancel_goal(session, other.id, goal.id)


def test_cancel_goal_rejects_already_cancelled(db):
    session, cid = db
    _fill_scope_1_measured(session, cid)
    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=10)
    cancel_goal(session, cid, goal.id)

    with pytest.raises(ValueError):
        cancel_goal(session, cid, goal.id)


# ── API 라우터 ────────────────────────────────────────────────────────────────
def test_owner_goal_endpoint_returns_null_when_no_goal(db, client):
    session, cid = db
    res = client.get(f"/owner/{cid}/goal")
    assert res.status_code == 200
    assert res.json()["goal"] is None


def test_owner_create_emission_reduction_goal_via_api(db, client):
    session, cid = db
    _fill_scope_1_measured(session, cid)

    res = client.post(f"/owner/{cid}/goal", json={"goal_type": "emission_reduction", "target_reduction_pct": 20})
    assert res.status_code == 200, res.text
    goal = res.json()["goal"]
    assert goal["goal_type"] == "emission_reduction"
    assert goal["target_reduction_pct"] == 20
    assert goal["measured"] is False


def test_owner_create_emission_reduction_goal_missing_pct_returns_422(db, client):
    session, cid = db
    res = client.post(f"/owner/{cid}/goal", json={"goal_type": "emission_reduction"})
    assert res.status_code == 422


def test_owner_create_grade_upgrade_goal_via_api(db, client):
    session, cid = db
    _fill_scope_1_revenue(session, cid)

    res = client.post(f"/owner/{cid}/goal", json={"goal_type": "grade_upgrade", "scope_group": "scope_1"})
    assert res.status_code == 200, res.text
    goal = res.json()["goal"]
    assert goal["goal_type"] == "grade_upgrade"
    assert goal["target_value"] == 2
    assert goal["target_product_name"] == "ESG Grow-Up 특별대출"


def test_owner_create_grade_upgrade_goal_missing_scope_returns_422(db, client):
    session, cid = db
    res = client.post(f"/owner/{cid}/goal", json={"goal_type": "grade_upgrade"})
    assert res.status_code == 422


def test_owner_create_goal_no_activity_data_returns_422(db, client):
    session, cid = db
    res = client.post(f"/owner/{cid}/goal", json={"goal_type": "grade_upgrade", "scope_group": "scope_1"})
    assert res.status_code == 422


def test_owner_cancel_goal_via_api(db, client):
    session, cid = db
    _fill_scope_1_measured(session, cid)
    create_res = client.post(
        f"/owner/{cid}/goal", json={"goal_type": "emission_reduction", "target_reduction_pct": 10}
    )
    goal_id = create_res.json()["goal"]["id"]

    res = client.post(f"/owner/{cid}/goal/{goal_id}/cancel")
    assert res.status_code == 200, res.text
    assert res.json()["cancelled"] is True

    follow_up = client.get(f"/owner/{cid}/goal")
    assert follow_up.json()["goal"] is None


def test_owner_cancel_unknown_goal_returns_404(db, client):
    session, cid = db
    res = client.post(f"/owner/{cid}/goal/99999/cancel")
    assert res.status_code == 404
