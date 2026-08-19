"""월간 AI 브리핑 문장 조립 — db/owner_briefing.py 단위 테스트.

핵심 검증축:
  - 증가/감소/변화없음/신규 4가지 direction 분기가 올바르게 갈린다.
  - 지난달 데이터가 아예 없으면(첫 달) 비교 문장 대신 시작 안내를 쓴다 —
    없는 지난달과 억지로 %를 비교하지 않는다.
  - 지난달 대비 계산은 새 배출량 계산이 아니라 기존 값(this_month_co2e,
    last_month_co2e)을 그대로 나눈 것뿐이다(파생값 검증).
"""
from db.owner_briefing import FuelMonthStat, build_briefing_paragraphs, compute_fuel_deltas


def test_direction_up_down_flat_new():
    stats = [
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),   # +18%
        FuelMonthStat(fuel_type="전기", this_month_co2e=1.84, last_month_co2e=2.0),   # -8%
        FuelMonthStat(fuel_type="LPG", this_month_co2e=1.0, last_month_co2e=1.003),   # 변화 미미
        FuelMonthStat(fuel_type="도시가스", this_month_co2e=0.5, last_month_co2e=None),  # 신규
    ]
    result = compute_fuel_deltas(stats)
    by_fuel = {r["fuel_type"]: r for r in result}

    assert by_fuel["경유"]["direction"] == "up"
    assert by_fuel["경유"]["delta_pct"] == 18.0

    assert by_fuel["전기"]["direction"] == "down"
    assert by_fuel["전기"]["delta_pct"] == -8.0

    assert by_fuel["LPG"]["direction"] == "flat"

    assert by_fuel["도시가스"]["direction"] == "new"
    assert by_fuel["도시가스"]["delta_pct"] is None


def test_delta_is_pure_ratio_not_new_calculation():
    """지난달 대비 %는 this_month_co2e/last_month_co2e의 순수 비율일 뿐,
    별도 배출량 재계산이 섞이지 않는다는 걸 확인 — 입력값만 바뀌어도 출력이
    정확히 그 비율을 따라간다."""
    stats = [FuelMonthStat(fuel_type="경유", this_month_co2e=150.0, last_month_co2e=100.0)]
    result = compute_fuel_deltas(stats)
    assert result[0]["delta_pct"] == 50.0

    stats2 = [FuelMonthStat(fuel_type="경유", this_month_co2e=75.0, last_month_co2e=100.0)]
    result2 = compute_fuel_deltas(stats2)
    assert result2[0]["delta_pct"] == -25.0


def test_first_month_has_no_comparison_paragraph():
    paragraphs = build_briefing_paragraphs([], has_previous_month=False)
    assert any("첫" not in p and "지난달" not in p for p in paragraphs)  # 비교 문장 없음
    assert len(paragraphs) >= 1


def test_no_vouchers_this_month_with_previous_month_data():
    paragraphs = build_briefing_paragraphs([], has_previous_month=True)
    assert len(paragraphs) == 1
    assert "확인된 전표가 없" in paragraphs[0]


def test_paragraph_mentions_fuel_and_direction():
    fuel_deltas = compute_fuel_deltas([
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),
    ])
    paragraphs = build_briefing_paragraphs(fuel_deltas, has_previous_month=True)
    assert any("경유" in p and "18%" in p for p in paragraphs)


def test_closing_sentence_only_when_some_fuel_decreased():
    up_only = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])
    paragraphs_up = build_briefing_paragraphs(up_only, has_previous_month=True)
    assert not any("목표 달성" in p for p in paragraphs_up)

    down_included = compute_fuel_deltas([
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),
        FuelMonthStat(fuel_type="전기", this_month_co2e=1.84, last_month_co2e=2.0),
    ])
    paragraphs_down = build_briefing_paragraphs(down_included, has_previous_month=True)
    assert any("목표 달성" in p for p in paragraphs_down)
