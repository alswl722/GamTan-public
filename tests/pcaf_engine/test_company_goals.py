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
def test_create_emission_reduction_goal_snapshots_baseline_and_target(db, monkeypatch):
    session, cid = db
    # 시작월을 12월로 고정 — 기준 구간은 "설정월까지의 최근 12개월"이므로 12월에
    # 세우면 그 구간이 달력년도(1~12월)와 정확히 겹친다. 덕분에 아래 숫자 검증
    # (12개월치 = 1.2tCO2e)이 실행 시점(현재 몇 월인지)과 무관하게 재현된다.
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 12))
    _fill_scope_1_measured(session, cid)

    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=20)
    assert goal.goal_type == "emission_reduction"
    assert goal.baseline_reporting_year == YEAR
    assert goal.baseline_start_month == 12
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


def test_emission_reduction_progress_not_measured_without_prior_year_data(db):
    """비교 기준(작년 동월)이 아예 없으면 진행률을 만들 수 없다 — 0으로 나누거나 없는
    값을 지어내지 않고 measured=False로 내려보낸다(원칙7). 이 픽스처는 올해치만 채우고
    작년치가 없으므로 동월 대비가 성립하지 않는 경우다."""
    session, cid = db
    _fill_scope_1_measured(session, cid)
    create_emission_reduction_goal(session, cid, target_reduction_pct=20)

    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is False
    assert progress["achieved"] is False
    assert progress["progress_pct"] == 0.0
    assert progress["reduction_pct"] is None
    assert progress["status"] == "active"


# ── 동월 대비 진행률 (2026-08-25) ─────────────────────────────────────────────
def test_emission_reduction_progress_measured_by_year_over_year(db, monkeypatch):
    """경과 12개월이 다 차면 동월 대비는 "올해 1~12월 vs 작년 1~12월"이 되고, 그때
    감축률이 목표에 닿으면 달성으로 전환한다. 이 시점엔 current_value(지금 기준 최근
    12개월)와 경과 구간 합이 같은 값이라 "링 100%"와 "최근 1년 배출량 <= 목표 배출량"이
    같은 뜻이 된다."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 1))
    # 작년 1~12월 100kg씩 = 1.2tCO2e — 동월 대비의 비교 구간.
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=prev_year)
    # 올해 1~12월 50kg씩 = 0.6tCO2e — 경과 구간. 정확히 50% 감축.
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=50.0, year=YEAR)
    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=50)

    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 12))
    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is True
    assert progress["elapsed_months"] == 12
    assert progress["reduction_pct"] == pytest.approx(50.0)   # 1 - 0.6/1.2
    assert progress["progress_pct"] == pytest.approx(100.0)   # 감축률 50% / 목표 50%
    assert progress["current_value"] == pytest.approx(0.6)    # 지금 기준 최근 12개월
    assert progress["achieved"] is True
    assert progress["status"] == "achieved"

    session.refresh(goal)
    assert goal.status == "achieved"
    assert goal.achieved_at is not None


def test_emission_reduction_ring_fills_before_twelve_months_but_not_achieved(db, monkeypatch):
    """동월 대비의 핵심 이점 — 첫 달부터 링이 움직인다(예전엔 12개월 내내 0%로 죽어
    있었다, 사용자 지적 2026-08-25). 다만 석 달 잘한 걸로 "연간 10% 감축 달성" 배지를
    주면 거짓이므로 achieved는 경과 12개월이 다 찬 뒤에만 True다."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 1))
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=prev_year)
    for m in range(1, 4):  # 올해는 1~3월만, 절반으로 줄여서
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=50.0, year=YEAR)
    create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 3))
    progress = get_active_goal_progress(session, cid)
    assert progress["elapsed_months"] == 3
    assert progress["measured"] is True
    # 올해 1~3월 0.15 vs 작년 1~3월 0.3 → 50% 감축, 목표 10%의 5배라 링은 100%로 clamp.
    assert progress["reduction_pct"] == pytest.approx(50.0)
    assert progress["progress_pct"] == pytest.approx(100.0)
    # 링은 가득 찼어도 연간 감축 달성은 아니다 — 아직 3개월치뿐.
    assert progress["achieved"] is False
    assert progress["status"] == "active"


def test_emission_reduction_progress_reports_increase_as_negative(db, monkeypatch):
    """배출량이 늘면 reduction_pct는 음수로 그대로 내려간다 — 링은 0%로 눌리지만 화면이
    "지난해 같은 달보다 늘었어요"라고 사실대로 말할 수 있어야 한다(데이터가 없어서 0%인
    건지 성과가 없어서 0%인 건지 구분되게)."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 1))
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=prev_year)
    _add_voucher(session, cid, 1, "도시가스", quantity=100, scope=1, emission=120.0, year=YEAR)
    create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is True
    assert progress["elapsed_months"] == 1
    assert progress["reduction_pct"] == pytest.approx(-20.0)  # 1 - 0.12/0.1
    assert progress["progress_pct"] == 0.0                    # 음수는 0으로 눌림
    assert progress["achieved"] is False


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

    # 회귀 방지(실측 신고 2026-08-19, "목표가 자꾸 사라지네") — achieved로 넘어간
    # 뒤에도 다시 조회하면 여전히 이 목표가 나와야 한다. get_active_goal이
    # status=="active"만 보면 여기서 None이 되어 홈 화면이 "목표 설정" 프롬프트로
    # 되돌아간다(달성 배지가 계속 유지된다는 코드 의도와 반대).
    progress_again = get_active_goal_progress(session, cid)
    assert progress_again is not None
    assert progress_again["id"] == progress["id"]
    assert progress_again["status"] == "achieved"
    assert progress_again["achieved"] is True


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


def test_emission_reduction_progress_includes_monthly_emission_even_when_not_measured(db, monkeypatch):
    """같은 기준 윈도우 안(measured=False)이어도 월별 배출 데이터는 내려줘야 홈 박스가
    "활동 현황"을 보여줄 수 있다. 리포트 화면의 "월별 배출 추이"와 완전히 같은
    차트를 재사용하기로 해(사용자 요청, 2026-08-18) 같은 재료 함수
    (db/pcaf_engine/pcaf.py::monthly_by_fuel)를 그대로 쓴다 — 그래서 결손월을 잘라내지
    않고 항상 12개월 전부(연료별 분해 포함) 내려온다.

    now=(YEAR,12)로 맞춘 이유: 차트 구간이 "최근 1년"(_trailing_months)이라
    _fill_scope_1_measured가 채우는 1~12월과 정확히 겹치는 시점이 12월이다."""
    session, cid = db
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 12))
    _fill_scope_1_measured(session, cid)
    create_emission_reduction_goal(session, cid, target_reduction_pct=20)

    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is False
    assert len(progress["monthly_emission_detail"]) == 12
    # _fill_scope_1_measured는 1~12월 전부 100kg(=0.1tCO2e)씩 채운다 — 12개월 합계.
    assert sum(item["total_tco2e"] for item in progress["monthly_emission_detail"]) == pytest.approx(1.2)


def test_monthly_chart_shows_trailing_year_not_goal_window(db, monkeypatch):
    """홈 목표 카드의 월별 차트는 목표 윈도우(설정월부터 미래 12개월)가 아니라 "최근
    1년치"를 그린다 — 8월에 목표를 세웠을 때 x축이 "8,9,…,7"로 깔리고 8월 한 칸만
    막대가 있던 문제(사용자 지적, 2026-08-25). 지금이 8월이면 작년 9월~올해 8월이라
    x축은 9,10,11,12,1,…,8 순서여야 하고 과거 데이터가 실제로 잡혀야 한다."""
    session, cid = db
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 8))
    # 작년 9~12월 + 올해 1~8월 = 최근 1년치 12개월 전부 채움(각 100kg=0.1tCO2e).
    for m in range(9, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=YEAR - 1)
    for m in range(1, 9):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=YEAR)
    create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    progress = get_active_goal_progress(session, cid)
    detail = progress["monthly_emission_detail"]
    # x축 순서: 이번 달(8월)이 오른쪽 끝, 그 앞이 작년 9월부터 시간순.
    assert [item["month"] for item in detail] == [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8]
    # 12개월 전부 실제 데이터 — 미래 달 빈칸이 하나도 없어야 한다(예전 버그면 8월만 찼다).
    assert all(item["total_tco2e"] == pytest.approx(0.1) for item in detail)


# ── 롤링 12개월 윈도우 (달력년도 아님, 사용자 지적 2026-08-19) ─────────────────
def test_baseline_window_is_trailing_twelve_months_from_creation_month(db, monkeypatch):
    """8월에 목표를 세우면 기준값은 "작년 9~12월 + 올해 1~8월"(설정월까지의 최근 12개월)
    이어야 한다 — 달력년도도 아니고, 설정월부터 **미래** 12개월도 아니다.

    미래 방향이 왜 틀렸는지가 이 테스트의 요점(2026-08-25): 미래 구간엔 설정 시점에
    이번 달 데이터 하나만 존재할 수 있어 "연간 기준값"이 한 달치로 저장됐다."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 8))
    # 작년 1~8월은 기준 구간 밖 — 아무리 커도 기준값에 안 잡혀야 한다.
    for m in range(1, 9):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=999.0, year=prev_year)
    # 작년 9~12월 + 올해 1~8월 = 최근 12개월(기준 구간 안).
    for m in range(9, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=prev_year)
    for m in range(1, 9):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=YEAR)

    goal = create_emission_reduction_goal(session, cid, target_reduction_pct=10)
    assert goal.baseline_reporting_year == YEAR
    assert goal.baseline_start_month == 8  # 컬럼 의미는 "목표 시작월" 그대로
    # 12개월 * 100kg = 1.2tCO2e — 작년 1~8월의 999kg짜리는 안 잡힘.
    assert goal.baseline_value == pytest.approx(1.2)
    assert goal.target_value == pytest.approx(1.08)


def test_year_over_year_compares_exactly_the_same_calendar_months(db, monkeypatch):
    """동월 대비는 "1년 전 **같은 달들**"만 잡아야 한다 — 8월에 세운 목표를 10월에 보면
    경과 구간은 올해 8·9·10월, 비교 구간은 작년 8·9·10월이다. 작년의 나머지 달에 큰 값을
    넣어도 감축률이 흔들리지 않는지로 확인한다(연도 전체를 잘못 긁으면 바로 틀어진다)."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 8))
    # 작년 8·9·10월만 비교 구간 — 400kg씩 = 1.2tCO2e.
    for m in (8, 9, 10):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=400.0, year=prev_year)
    # 작년의 그 외 달은 비교 구간 밖 — 999kg이어도 안 잡혀야 한다.
    for m in (1, 2, 3, 4, 5, 6, 7, 11, 12):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=999.0, year=prev_year)
    # 올해 8·9·10월 = 경과 구간 — 300kg씩 = 0.9tCO2e라 정확히 25% 감축.
    # (kg 값을 크게 잡은 이유: _emission_in_months가 Scope별로 tCO2e 소수 2자리까지만
    #  남기므로 총량이 0.2대면 반올림 오차가 감축률에 그대로 번진다 — 0.225→0.23으로
    #  23.3%가 나왔다. 두 구간 합이 2자리에서 정확히 표현되는 값으로 맞춘다.)
    for m in (8, 9, 10):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=300.0, year=YEAR)
    create_emission_reduction_goal(session, cid, target_reduction_pct=25)

    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 10))
    progress = get_active_goal_progress(session, cid)
    assert progress["measured"] is True
    assert progress["elapsed_months"] == 3
    # 0.225 vs 0.3 → 25% 감축. 작년 나머지 달(999kg)이 섞였다면 이 값이 안 나온다.
    assert progress["reduction_pct"] == pytest.approx(25.0)
    assert progress["progress_pct"] == pytest.approx(100.0)
    assert progress["achieved"] is False  # 아직 3개월치


def test_elapsed_months_caps_at_twelve(db, monkeypatch):
    """목표를 세운 지 1년이 넘어도 비교 구간은 12개월로 고정된다 — 안 그러면 13개월치를
    "작년 같은 13개월"과 비교하게 되고, 같은 달이 두 번 들어가 월수가 어긋난다."""
    session, cid = db
    prev_year = YEAR - 1
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR, 1))
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=100.0, year=prev_year)
    for m in range(1, 13):
        _add_voucher(session, cid, m, "도시가스", quantity=100, scope=1, emission=50.0, year=YEAR)
    create_emission_reduction_goal(session, cid, target_reduction_pct=50)

    # 시작월(YEAR-1월)로부터 18개월 뒤 — 경과는 12로 잘려야 한다.
    monkeypatch.setattr("db.pcaf_engine.company_goals._now_year_month", lambda: (YEAR + 1, 6))
    progress = get_active_goal_progress(session, cid)
    assert progress["elapsed_months"] == 12


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


def test_new_goal_supersedes_already_achieved_goal(db):
    """achieved로 넘어간 목표는 status가 더 이상 "active"가 아니라서, 새 목표를
    만들 때 _supersede_active_goal이 status=="active"만 보면 achieved 목표를
    못 찾고 안 건드린 채 지나간다 — 그러면 achieved 1건 + 새 active 1건이 동시에
    "현재 목표"로 남아 get_active_goal(.first())이 어느 쪽을 돌려줄지 DB 행
    순서에 좌우되는 불안정한 상태가 된다. 새 목표 생성이 achieved 목표도 같이
    superseded로 정리하는지 확인."""
    session, cid = db
    _fill_scope_1_measured(session, cid)

    first = create_grade_upgrade_goal(session, cid, scope_group="scope_1")  # 이미 eligible → 즉시 achieved
    progress = get_active_goal_progress(session, cid)
    assert progress["status"] == "achieved"
    session.refresh(first)
    assert first.status == "achieved"

    second = create_emission_reduction_goal(session, cid, target_reduction_pct=10)

    session.refresh(first)
    assert first.status == "superseded"
    assert second.status == "active"

    progress = get_active_goal_progress(session, cid)
    assert progress["id"] == second.id
    assert progress["status"] == "active"


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
