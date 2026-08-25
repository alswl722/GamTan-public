"""감축률 산정 — 골든셋 대조 + 신규 가입자 예외 + 정산 주기.

회계 확인 기준(2026-08-24): 매월 각각이 아니라 **6개월 정산 구간 단위**로 판정하고,
과거 2년치가 없는 신규 가입자는 1년치 평균으로 대체한다.

아직 미확정인 축은 기준값 산출 전략이다(같은 구간 2년 평균 vs 24개월 전체 평균) — 둘 다
파라미터로 지원하므로 양쪽에 테스트를 붙여 확정 시 기본값만 바꾸면 되게 한다.
"""
import csv

import pytest

from db.carbon_neutral_point import (
    SETTLEMENT_MONTHS,
    MonthlyUsage,
    compute_reduction_rate,
    settlement_period,
)

GOLDEN = "data/fixtures/electricity_bills/S001/_reduction_expected.csv"


def _load(company: str) -> list[MonthlyUsage]:
    path = f"data/fixtures/electricity_bills/{company}/_manifest.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        year, month = r["billing_month"].split("-")
        out.append(MonthlyUsage(int(year), int(month), float(r["usage_kwh"])))
    return out


# ── 골든셋 대조 ────────────────────────────────────────────────────────────


def test_matches_golden_set_same_period_strategy():
    """S001 2026년 상반기 — 골든셋의 `avg_prior_2yr_kwh`(같은 달 2년 평균)와 같은 결의
    구간 비교. 골든셋은 월별 값이라 구간 합계와 직접 비교되지 않으므로, 구간을 이루는
    각 달의 기준값 합이 골든셋 월별 기준값의 합과 일치하는지로 검증한다."""
    golden = {r["year_month"]: r for r in csv.DictReader(open(GOLDEN, encoding="utf-8-sig"))}
    monthly = _load("S001")

    result = compute_reduction_rate(monthly, 2026, 1, strategy="same_period_avg")

    expected_baseline = sum(
        float(golden[f"2026-{m:02d}"]["avg_prior_2yr_kwh"]) for m in range(1, SETTLEMENT_MONTHS + 1)
    )
    expected_target = sum(
        float(golden[f"2026-{m:02d}"]["usage_kwh"]) for m in range(1, SETTLEMENT_MONTHS + 1)
    )
    assert result.baseline_usage_kwh == pytest.approx(expected_baseline)
    assert result.target_usage_kwh == pytest.approx(expected_target)
    assert result.reduction_rate_pct == pytest.approx(6.74, abs=0.01)
    assert result.eligible is True
    assert result.used_newcomer_fallback is False
    assert result.baseline_months_used == SETTLEMENT_MONTHS * 2


def test_strategy_choice_changes_incentive_tier():
    """두 전략이 자격은 같지만 **인센티브 구간을 가른다** — 확정 전까지 기본값을 함부로
    바꾸면 사장님에게 틀린 금액을 안내하게 된다(same_period 6.74% = 20,000P 구간,
    all_months 11.37% = 40,000P 구간)."""
    monthly = _load("S001")
    same = compute_reduction_rate(monthly, 2026, 1, strategy="same_period_avg")
    lump = compute_reduction_rate(monthly, 2026, 1, strategy="all_months_avg")

    assert same.reduction_rate_pct == pytest.approx(6.74, abs=0.01)
    assert lump.reduction_rate_pct == pytest.approx(11.37, abs=0.01)
    assert same.eligible and lump.eligible
    # 계절성 왜곡 방향 — 비수기 구간이라 전체 평균 비교가 더 후하게 나온다
    assert lump.reduction_rate_pct > same.reduction_rate_pct


def test_s002_is_not_eligible_under_either_strategy():
    """S002는 감축 미달 대조군이다 — 자격 판정이 무조건 통과시키는 버그를 잡기 위해
    준비된 fixture이므로, 어느 산식으로도 eligible=False여야 한다."""
    monthly = _load("S002")
    for strategy in ("same_period_avg", "all_months_avg"):
        r = compute_reduction_rate(monthly, 2026, 1, strategy=strategy)
        assert r.eligible is False, f"{strategy}에서 통과해버렸다: {r.reduction_rate_pct}%"


# ── 신규 가입자 예외 ───────────────────────────────────────────────────────


def test_newcomer_falls_back_to_one_year():
    """과거 2년치가 없으면 1년치로 대체한다 — 누락하면 신규 온보딩 기업이 전부 계산
    불가가 된다."""
    monthly = [MonthlyUsage(2025, m, 100.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 90.0) for m in range(1, 7)]

    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.used_newcomer_fallback is True
    assert r.baseline_months_used == SETTLEMENT_MONTHS
    assert r.reduction_rate_pct == pytest.approx(10.0)
    assert r.eligible is True


def test_prefers_two_years_when_available():
    monthly = [MonthlyUsage(y, m, 100.0) for y in (2024, 2025) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 90.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.used_newcomer_fallback is False
    assert r.baseline_months_used == SETTLEMENT_MONTHS * 2


def test_no_history_is_not_zero_reduction():
    """비교할 과거가 없으면 감축률 0%가 아니라 None이다(원칙7)."""
    monthly = [MonthlyUsage(2026, m, 90.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct is None
    assert r.eligible is False
    assert "과거 사용량" in r.reason


# ── 미확인 달 처리 ─────────────────────────────────────────────────────────


def test_unknown_month_blocks_calculation_instead_of_counting_as_zero():
    """구간에 미확인(None) 달이 있으면 계산하지 않는다 — 0으로 채우거나 있는 달만
    더하면 월수가 안 맞아 감축률이 부풀려진다."""
    monthly = [MonthlyUsage(2025, m, 100.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 90.0) for m in range(1, 6)]
    monthly.append(MonthlyUsage(2026, 6, None))     # 6월 미확인

    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct is None
    assert "감축년도" in r.reason


def test_missing_baseline_month_blocks_calculation():
    monthly = [MonthlyUsage(2025, m, 100.0) for m in range(1, 13) if m != 3]  # 기준 3월 결손
    monthly += [MonthlyUsage(2026, m, 90.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct is None


def test_zero_baseline_does_not_divide_by_zero():
    monthly = [MonthlyUsage(2025, m, 0.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 90.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct is None
    assert "0" in r.reason


def test_usage_increase_gives_negative_rate_not_eligible():
    """사용량이 늘면 음수 감축률이다 — 0으로 깎지 않는다(사실을 그대로 보여준다)."""
    monthly = [MonthlyUsage(2025, m, 100.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 120.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct == pytest.approx(-20.0)
    assert r.eligible is False


def test_threshold_is_inclusive():
    """정확히 5%면 자격 충족(>= 5)."""
    monthly = [MonthlyUsage(2025, m, 100.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 95.0) for m in range(1, 7)]
    r = compute_reduction_rate(monthly, 2026, 1)
    assert r.reduction_rate_pct == pytest.approx(5.0)
    assert r.eligible is True


def test_window_crosses_year_boundary():
    """정산 구간이 연말을 넘어가도 (예: 2025-10~2026-03) 기준 구간도 같이 넘어간다."""
    monthly = [MonthlyUsage(y, m, 100.0) for y in (2023, 2024) for m in range(1, 13)]
    monthly += [MonthlyUsage(2025, m, 100.0) for m in range(1, 13)]
    monthly += [MonthlyUsage(2026, m, 80.0) for m in range(1, 4)]
    r = compute_reduction_rate(monthly, 2025, 10)
    assert r.target_usage_kwh == pytest.approx(100 * 3 + 80 * 3)


# ── 정산 주기 ──────────────────────────────────────────────────────────────


def test_settlement_starts_month_after_enrollment():
    """가입한 달은 이미 지난 사용량이라 제외하고 다음 달부터 집계한다."""
    p = settlement_period(2026, 3)
    assert (p.start_year, p.start_month) == (2026, 4)
    assert (p.end_year, p.end_month) == (2026, 9)
    # 9월에 구간이 끝나면 그 이후 첫 지급월은 12월
    assert (p.payout_year, p.payout_month) == (2026, 12)


def test_settlement_payout_rolls_into_next_year():
    p = settlement_period(2026, 8)
    assert (p.start_year, p.start_month) == (2026, 9)
    assert (p.end_year, p.end_month) == (2027, 2)
    assert (p.payout_year, p.payout_month) == (2027, 6)


def test_settlement_enrollment_in_december_rolls_over():
    p = settlement_period(2026, 12)
    assert (p.start_year, p.start_month) == (2027, 1)
    assert (p.end_year, p.end_month) == (2027, 6)


def test_settlement_fixed_half_mode_aligns_to_calendar_half():
    """미확정 대안 해석 — 전 기업이 같은 달력 반기를 쓴다."""
    p = settlement_period(2026, 3, mode="fixed_half")
    assert (p.start_year, p.start_month) == (2026, 1)
    assert (p.end_year, p.end_month) == (2026, 6)
