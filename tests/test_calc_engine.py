"""계산 엔진 골든셋 검증 — 기대_결과(I001~)가 오라클.

회계 노트의 활동량 산정 우선순위를 검증한다:
  1순위 실측 수량(전표에 kWh/L/m³) → 그대로 (배출량 = 수량 × 배출계수, 골든과 정확 일치)
  2순위 금액 ÷ 월별단가 추정
  3순위 사람검토 — 전기·도시가스 수량 미기재, LPG(프로판/부탄 단위 구분)

"환각이 숫자에 개입할 경로가 없다" — 활동량은 실측 or 결정론적 환산, 배출량은 순수 곱셈.
"""
import pytest

from db.calc_engine import (
    CalcDataGap,
    ClassifiedItemInput,
    compute_emission,
    index_emission_factors,
    index_unit_prices,
)
from db.excel_loader import (
    load_emission_factors,
    load_expected_results,
    load_unit_prices,
)

YEAR = 2025  # 회계 엑셀(월별단가·전표) 연도


@pytest.fixture(scope="module")
def factor_index():
    return index_emission_factors(load_emission_factors())


@pytest.fixture(scope="module")
def price_index():
    return index_unit_prices(load_unit_prices(year=YEAR))


@pytest.fixture(scope="module")
def golden():
    return load_expected_results()


def _measured(row):
    """전표 실측 수량(=골든 활동량)을 실은 입력."""
    return ClassifiedItemInput(
        fuel_type=row["fuel"], scope=row["scope"], amount_krw=row["amount_krw"],
        year=YEAR, month=1, quantity=row["activity_amount"], quantity_unit=row["unit"],
    )


def _computable(row, factor_index):
    return row["scope"] is not None and (row["fuel"], row["scope"]) in factor_index


# ── 골든셋 로드 ──────────────────────────────────────────────────
def test_golden_loads(golden):
    assert len(golden) == 41
    assert golden[0]["voucher_id"] == "I001"


# ── 킬러 데모 행: 실측 수량 → 정확히 일치 ────────────────────────
def test_i001_measured_exact(golden, price_index, factor_index):
    """'지게차 경유 외 1종' 실측 500L × 2.616 = 1308.0 kgCO2e (정확)."""
    row = next(r for r in golden if r["voucher_id"] == "I001")
    res = compute_emission(_measured(row), price_index, factor_index)
    assert res["method"] == "measured"
    assert res["activity_amount"] == 500.0
    assert res["emission_co2e"] == 1308.0


# ── 1순위 실측 경로: 골든과 정확 일치 (LPG·제외·HITL 제외) ───────
def test_measured_matches_golden_exact(golden, price_index, factor_index):
    rows = [
        r for r in golden
        if _computable(r, factor_index) and r["fuel"] != "LPG"
        and r["activity_amount"] and r["expected_kgco2e"] and not r["needs_review"]
    ]
    assert len(rows) >= 20, "전기·경유·도시가스·휘발유 실측 행이 있어야"
    for row in rows:
        res = compute_emission(_measured(row), price_index, factor_index)
        assert res["method"] == "measured"
        # 실측 수량 × 배출계수 = 골든 예상배출량 (반올림 오차 허용)
        assert abs(res["emission_co2e"] - row["expected_kgco2e"]) < 0.5, (
            f"{row['voucher_id']}({row['fuel']}): 엔진 {res['emission_co2e']} vs 골든 {row['expected_kgco2e']}"
        )


# ── 제외/연료 불명 → skip + 배출량 0 ────────────────────────────
def test_skip_rows_emit_zero(golden, price_index, factor_index):
    for row in golden:
        if _computable(row, factor_index) or row["fuel"] == "LPG":
            continue  # 계산 가능 or LPG(별도) 는 여기서 제외
        res = compute_emission(_measured(row), price_index, factor_index)
        assert res["skipped"] is True
        assert res["emission_co2e"] == 0.0


# ── LPG → 사람검토 (자동계산 제외, 회계 규칙) ───────────────────
def test_lpg_review(golden, price_index, factor_index):
    lpg = [r for r in golden if r["fuel"] == "LPG"]
    assert lpg, "LPG 행이 있어야"
    for row in lpg:
        res = compute_emission(_measured(row), price_index, factor_index)
        assert res["needs_review"] is True   # 골든도 HITL=True
        assert res["emission_co2e"] == 0.0


# ── 전기·도시가스 수량 미기재 → 사람검토 (금액 역산 안 함) ──────
def test_quantity_only_without_qty_reviews(price_index, factor_index):
    for fuel, scope in (("전기", 2), ("도시가스", 1)):
        item = ClassifiedItemInput(fuel_type=fuel, scope=scope, amount_krw=1_000_000, year=YEAR, month=3)
        res = compute_emission(item, price_index, factor_index)
        assert res["needs_review"] is True
        assert res["emission_co2e"] == 0.0


# ── 2순위 추정 경로: 경유·휘발유는 수량 없으면 금액÷월별단가 ────
def test_spend_fallback_diesel(price_index, factor_index):
    item = ClassifiedItemInput(fuel_type="경유", scope=1, amount_krw=700_000, year=YEAR, month=7)
    res = compute_emission(item, price_index, factor_index)
    assert res["method"] == "spend"
    assert res["emission_co2e"] > 0


# ── 결정론 ──────────────────────────────────────────────────────
def test_deterministic(golden, price_index, factor_index):
    row = next(r for r in golden if r["voucher_id"] == "I001")
    assert compute_emission(_measured(row), price_index, factor_index) == \
        compute_emission(_measured(row), price_index, factor_index)


# ── 진짜 데이터 갭: 경유 수량 없고 단가 인덱스 비면 CalcDataGap ──
def test_data_gap_raises(factor_index):
    item = ClassifiedItemInput(fuel_type="경유", scope=1, amount_krw=500_000, year=YEAR, month=6)
    with pytest.raises(CalcDataGap):
        compute_emission(item, price_index={}, factor_index=factor_index)


# ── 입력 검증 ───────────────────────────────────────────────────
def test_input_validation():
    with pytest.raises(Exception):
        ClassifiedItemInput(fuel_type="경유", scope=1, amount_krw=100, year=YEAR, month=13)
    with pytest.raises(Exception):
        ClassifiedItemInput(fuel_type="경유", scope=1, amount_krw=-1, year=YEAR, month=1)
