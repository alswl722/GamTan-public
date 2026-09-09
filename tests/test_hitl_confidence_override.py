"""회귀 테스트 — 회계 룰 시트가 "사람검토필요"로 명시한 건이 confidence 계산에서
무시되고 자동확정되던 버그(2026-08-18 실측으로 발견).

배경: `분류_기준표_확장` 시트의 needs_review=True인 룰(예: R018 "공장 가스비",
R058 "공조설비 유지보수비")이 30개 있었는데, 등급→confidence 환산표
(_RULE_CONFIDENCE, C=0.75 등)가 전부 임계값(0.7)을 넘어 그대로 자동확정되고
있었다. 정답지(기대_결과 50건) 채점 스크립트(scripts/score_classification_
accuracy.py)로 HITL 회부 재현율을 실측하다가 발견 — K택소노미 리드로 이미
노출되는 룰(finance_lead_type 有)은 제외하고, 그 외 needs_review=True 룰은
confidence를 임계값 미만으로 강제 하향하도록 api/agent/tools.py를 수정했다.

두 경로 모두 회귀를 막는다:
  1. 룰이 직접 확정하는 경로(_rule_decision) — R058처럼 auto_action이 "참고분류"
     이지만 K택소노미 매핑이 없는 경우
  2. 룰 매칭 실패 후 LLM으로 넘어가는 경로(_llm_result_to_decision) — LLM이
     rule_hint를 무시하고 confidence 1.0을 주더라도 강제 하향돼야 함
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import api.agent.tools as tools
from api.agent.tools import CONFIDENCE_THRESHOLD, classify_vouchers
from db.init_db import seed_emission_factors, seed_industry_distributions, seed_unit_prices
from db.models import Base, Classification, Company, Voucher


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
        company_id=cid, source="hometax", year=2025, month=month,
        supplier_name="테스트", item_description=item, supply_amount_krw=amount,
    )
    session.add(v)
    session.commit()
    return v.id


def test_rule_confirmed_needs_review_item_is_hitl_not_auto(db):
    """R058(공조설비 유지보수비, auto_action=사람검토·needs_review=True·K택소노미
    매핑 없음)은 룰 매칭이 실패해 LLM으로 넘어가야 정상 — LLM이 아무 confidence를
    줘도 rule_hint의 needs_review가 강제로 review_required로 되돌린다."""
    session, cid = db
    vid = _add_voucher(session, cid, "공조설비 유지보수비")

    def _stub(text, amount, rule_hint=None):
        # 회계 룰이 애매하다고 명시했는데도 LLM이 자체 확신을 높게 줄 수 있음(실측 사례).
        return {"scope": None, "category": "일반비용", "fuel_type": "없음",
                "amount_krw": amount, "mixed_item": False, "confidence": 1.0,
                "evidence": "설비 수리로 판단, 탄소 산정 제외"}

    original = tools.classify_with_llm_nocache
    tools.classify_with_llm_nocache = _stub
    try:
        classify_vouchers(session, cid)
    finally:
        tools.classify_with_llm_nocache = original

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.status == "review_required"
    assert c.confidence < CONFIDENCE_THRESHOLD


def test_k_taxonomy_lead_with_needs_review_stays_auto(db):
    """R051(태양광, needs_review=True지만 finance_lead_type 有 — 리드 리스트로
    이미 노출됨)은 이번 수정 대상이 아니다. HITL 큐가 아니라 별도 채널
    (docs/owner-admin-flow-spec.md §5)로 사람에게 보이므로 자동확정 그대로 둔다."""
    session, cid = db
    vid = _add_voucher(session, cid, "태양광 설비 설치")

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=vid).one()
    assert c.status == "auto"
    assert c.finance_lead_type == "녹색여신 후보"


def test_normal_rule_confirmed_item_unaffected(db):
    """needs_review=False인 일반 룰(전기요금 등)은 이번 수정으로 동작이 바뀌지
    않는다 — confidence·status 회귀 방지. 실측 사용량을 함께 줘야 계산 엔진이
    "사용량 미기재"로 별도 review 처리하지 않아, 이번 confidence 수정만 단독으로
    검증된다."""
    session, cid = db
    v = Voucher(
        company_id=cid, source="hometax", year=2025, month=1,
        supplier_name="테스트", item_description="공장 전기요금", supply_amount_krw=1_000_000,
        raw_json={"quantity": 3500, "quantity_unit": "kWh"},
    )
    session.add(v)
    session.commit()

    classify_vouchers(session, cid)

    c = session.query(Classification).filter_by(voucher_id=v.id).one()
    assert c.status == "auto"
    assert c.scope == 2
    assert c.fuel_type == "전기"
