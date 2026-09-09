"""감축 실천 ToDo 계산 레이어(db/pcaf_engine/reduction_actions.py) 골든 케이스.

정본: docs/reduction-todo-plan.md.

핵심 검증축:
  - 2층(설비 신호): R058("설비 유지보수비") 매칭 건이 evidence 접두사로 정확히
    식별된다 — Classification에 rule_id 컬럼이 없으므로 이 파싱이 유일한 식별 경로.
  - 2층: k_taxonomy_facility_type이 채워진 건(예: R053 전동지게차)이 facility_types에
    잡힌다.
  - 2층: LLM 경로(method == "llm")는 R058 형식이 아니므로 노후설비 신호에서 제외된다.
  - 2층: 반려(status == "rejected") 건은 신호에서 제외된다(k_taxonomy_leads()와
    동일 원칙).
  - 3층(기준부하): 연료별 최근 최저 tCO2e 달을 정확히 찾는다. 활동이 없던 달(0)은
    기준부하 후보에서 제외된다(원칙7 — 미산정을 0으로 착각하지 않음).
  - 3층: 이미 기준부하 이하로 쓰고 있으면 목표를 만들지 않는다(개선 여지 없는
    연료를 목표로 들이밀지 않음).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.tools import classify_vouchers
from db.init_db import seed_emission_factors, seed_industry_distributions, seed_unit_prices
from db.models import Base, Classification, Company, Voucher
from db.pcaf_engine.reduction_actions import (
    FALLBACK_TIPS,
    aging_equipment_signal,
    baseline_load_by_fuel,
    facility_signals,
    reduction_target_for_fuel,
)

YEAR = 2025


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_emission_factors(session)
        seed_unit_prices(session)
        seed_industry_distributions(session)
        company = Company(
            name="○○정밀", industry_code="C251", industry_name="구조용 금속제품 제조",
            employee_count=12, revenue_krw=2_400_000_000, region="경북 구미시",
        )
        session.add(company)
        session.commit()
        yield session, company.id


def _add_voucher(session, cid, item, *, month=1, amount=1_000_000):
    v = Voucher(
        company_id=cid, source="hometax", year=YEAR, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=amount,
    )
    session.add(v)
    session.commit()
    return v.id


# ── 2층: 설비 신호 ────────────────────────────────────────────────────────

def test_aging_equipment_signal_detects_r058(db):
    """R058 매칭 품목("공조설비 유지보수비", 엑셀 예시 문구 그대로)은 auto_action이
    "사람검토"라 룰 경로가 아니라 항상 LLM으로 위임된다(_SHORT_CIRCUIT_ACTIONS에
    "사람검토"가 없음) — method는 "llm", evidence는 LLM 문장 뒤에 "(참고: R058)"
    접미사가 붙는 형태다(실측 확인, 2026-08-25)."""
    session, cid = db
    vid = _add_voucher(session, cid, "공조설비 유지보수비")
    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.method == "llm"
    assert "(참고: R058)" in c.evidence
    assert aging_equipment_signal(session, cid) is True


def test_aging_equipment_signal_false_without_r058(db):
    """R058이 아닌 일반 전표만 있으면 노후설비 신호가 없다."""
    session, cid = db
    vid = _add_voucher(session, cid, "한국전력 전기요금")
    classify_vouchers(session, cid)

    assert aging_equipment_signal(session, cid) is False


def test_aging_equipment_signal_excludes_rejected(db):
    """R058 매칭 건이라도 담당자가 반려(status=rejected)했으면 신호에서 빠진다."""
    session, cid = db
    vid = _add_voucher(session, cid, "공조설비 유지보수비")
    classify_vouchers(session, cid)
    c = session.query(Classification).filter_by(voucher_id=vid).one()
    c.status = "rejected"
    session.commit()

    assert aging_equipment_signal(session, cid) is False


def test_facility_signals_collects_k_taxonomy_types(db):
    """전동지게차(R053) 품목이 facility_types에 잡힌다 — 새 매칭이 아니라 기존
    k_taxonomy_facility_type 컬럼을 원시 조회만 한다."""
    session, cid = db
    vid = _add_voucher(session, cid, "전동지게차 리스료")
    classify_vouchers(session, cid)

    signals = facility_signals(session, cid)
    assert "전동지게차" in signals["facility_types"]


def test_facility_signals_combines_with_aging_equipment(db):
    """설비 신호와 노후설비 신호가 한 응답에 같이 나온다."""
    session, cid = db
    v1 = _add_voucher(session, cid, "전동지게차 리스료", month=1)
    v2 = _add_voucher(session, cid, "공조설비 유지보수비", month=2)
    classify_vouchers(session, cid)

    signals = facility_signals(session, cid)
    assert "전동지게차" in signals["facility_types"]
    assert signals["aging_equipment"] is True


def test_facility_signals_empty_for_bill_only_company(db):
    """세금계산서 없이 고지서만 있는 기업은 설비 신호가 비어있다 — 이건 버그가
    아니라 의도된 한계다(docs/reduction-todo-plan.md §5.2 "액션이 줄어드는 게
    맞다")."""
    session, cid = db
    vid = _add_voucher(session, cid, "한국전력 전기요금")
    classify_vouchers(session, cid)

    signals = facility_signals(session, cid)
    assert signals["facility_types"] == []
    assert signals["aging_equipment"] is False


# ── 3층: 기준부하 추정 ──────────────────────────────────────────────────
#
# 여기서는 실제 룰/LLM 분류 파이프라인(classify_vouchers)을 거치지 않고
# Classification을 직접 만든다 — 3층은 emission_co2e 집계 로직만 검증하면
# 되고, 전기 사용량 미기재로 인한 계산 실패(CLAUDE.md §7 — 금액만으로 kWh
# 역산 불가) 같은 계산 엔진의 세부사항은 이 테스트의 관심사가 아니다
# (tests/pcaf_engine/test_company_goals.py의 기존 관례와 동일 패턴).

def _add_classified_voucher(session, cid, *, month, fuel_type, emission_kg, year=YEAR):
    v = Voucher(
        company_id=cid, source="hometax", year=year, month=month,
        supplier_name="테스트", item_description=f"{fuel_type} 전표",
        supply_amount_krw=100_000,
    )
    session.add(v)
    session.flush()
    scope = 2 if fuel_type == "전기" else 1
    session.add(Classification(
        voucher_id=v.id, scope=scope, category="테스트", fuel_type=fuel_type,
        amount_krw=100_000, emission_co2e=emission_kg, confidence=0.9,
        evidence="test", method="rule", status="auto",
    ))
    session.commit()
    return v.id


def test_baseline_load_finds_lowest_active_month(db):
    """전기 사용량이 3개월에 걸쳐 다르면, 0이 아닌 달 중 가장 낮은 달이
    기준부하가 된다."""
    session, cid = db
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=3000.0)
    _add_classified_voucher(session, cid, month=2, fuel_type="전기", emission_kg=1000.0)  # 최저
    _add_classified_voucher(session, cid, month=3, fuel_type="전기", emission_kg=2000.0)

    baseline = baseline_load_by_fuel(session, cid)
    assert "전기" in baseline
    assert baseline["전기"]["baseline_month"] == 2
    assert baseline["전기"]["current_month"] == 3  # monthly_by_fuel 반환 순서상 마지막


def test_baseline_load_excludes_zero_months(db):
    """활동이 없던 달(0)은 기준부하 후보에서 제외된다 — 미산정을 0으로 착각해
    "0으로 줄이세요"라는 목표를 만들지 않는다(원칙7)."""
    session, cid = db
    # 1월만 전표가 있고 2~3월은 데이터 자체가 없음(0으로 채워짐, monthly_by_fuel 관례)
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=2000.0)

    baseline = baseline_load_by_fuel(session, cid, months=[(YEAR, 1), (YEAR, 2), (YEAR, 3)])
    assert baseline["전기"]["baseline_month"] == 1  # 유일한 활동월


def test_baseline_load_omits_fuel_with_no_activity(db):
    """전 구간 활동이 없는 연료는 결과에 아예 없다."""
    session, cid = db
    _add_classified_voucher(session, cid, month=1, fuel_type="전기", emission_kg=1000.0)

    baseline = baseline_load_by_fuel(session, cid)
    assert "가스" not in baseline
    assert "경유/유류" not in baseline


def test_reduction_target_none_when_already_at_baseline():
    """현재값이 기준부하와 같거나 낮으면(이미 최선을 다하고 있음) 목표를 만들지
    않는다."""
    assert reduction_target_for_fuel(baseline_tco2e=1.0, current_tco2e=1.0) is None
    assert reduction_target_for_fuel(baseline_tco2e=1.0, current_tco2e=0.5) is None


def test_reduction_target_computes_gap():
    """현재값이 기준부하보다 높으면 그 차이만큼 절감 목표를 계산한다."""
    target = reduction_target_for_fuel(baseline_tco2e=1.0, current_tco2e=2.0)
    assert target is not None
    assert target["potential_reduction_tco2e"] == 1.0
    assert target["reduction_pct"] == 50.0


# ── 폴백 참고 팁 ──────────────────────────────────────────────────────────

def test_fallback_tips_have_no_verify_metric_by_design():
    """폴백 팁은 검증 불가능해 카탈로그 정식 액션 스키마(verify_metric 필수)에
    들어갈 수 없다는 걸 데이터 형태로도 확인한다 — 'verify_metric' 키 자체가
    없어야 한다."""
    assert len(FALLBACK_TIPS) == 3
    for tip in FALLBACK_TIPS:
        assert "verify_metric" not in tip
        assert "id" in tip and "label" in tip and "note" in tip
