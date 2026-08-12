"""킬러씬 스모크 테스트 — demo 시나리오에서 결손 감지 + 이상치 자가검증이 실제로 발생하는지.

이상치 판별식·시나리오 구성이 바뀌어 킬러씬이 조용히 사라지는 회귀를 잡는다
(과거 사고: 업종 연중앙값÷12 비교식이 동절기 1월 도시가스를 항상 이상치 1순위로
올려 "지게차 증차 → 정상 판정" 장면이 어떤 시나리오에서도 나오지 않았음).

네트워크는 쓰지 않는다 — LLM 호출 지점 2곳(분류·이상치 판단)을 스텁으로 대체.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import api.agent.orchestrator as orch
from db.init_db import (
    seed_emission_factors,
    seed_industry_distributions,
    seed_unit_prices,
)
from db.models import Base, Company, TraceLog
from db.scenarios import load_scenario


def _stub_llm_classify(text: str, amount: int, rule_hint=None) -> dict:
    """키워드 기반 완벽 분류 스텁 — LLM 대상(애매 표현) 건에 결정론적 응답."""
    if "가스" in text or "LNG" in text or "난방유" not in text and "난방" in text:
        scope, category, fuel = 1, "고정연소", "도시가스"
    elif "전기" in text or "전력" in text or "한전" in text:
        scope, category, fuel = 2, "간접배출", "전기"
    else:
        scope, category, fuel = 1, "이동연소", "경유"
    return {
        "raw_text": text, "scope": scope, "category": category, "fuel_type": fuel,
        "amount_krw": amount, "mixed_item": False, "confidence": 0.9,
        "evidence": "테스트 스텁 분류",
    }


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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr("api.agent.tools.classify_with_llm_nocache", _stub_llm_classify)


def _messages(session: Session, company_id: int) -> str:
    rows = (
        session.query(TraceLog)
        .filter_by(company_id=company_id)
        .order_by(TraceLog.id)
        .all()
    )
    return " || ".join(r.message for r in rows)


def test_demo_scenario_shows_gap_and_self_verification(db, monkeypatch):
    """demo 시나리오 = 킬러씬 A 전체: 결손 발견 + 7월 경유 이상치 정상 판정."""
    session, cid = db
    monkeypatch.setattr(orch, "_judge_anomaly_with_llm",
                        lambda items: (True, "지게차 2대 증차 문구 확인"))

    load_scenario(session, cid, "demo")
    result = orch.run_agent(session, cid)

    msgs = _messages(session, cid)
    assert "비어있네요" in msgs, f"결손 감지 스텝 없음: {msgs}"
    assert "7월 경유" in msgs and "왜 그런지 다시 확인해볼게요" in msgs, f"이상치 감지 스텝 없음: {msgs}"
    assert "정상적인 사용이니 걱정 안 하셔도 돼요" in msgs, f"자가검증 정상 판정 스텝 없음: {msgs}"
    assert result["mode"] == "llm"


def test_normal_scenario_has_no_anomaly(db, monkeypatch):
    """normal 시나리오: 동절기 가스 계절성이 이상치로 오검출되지 않아야 한다."""
    session, cid = db
    monkeypatch.setattr(orch, "_judge_anomaly_with_llm",
                        lambda items: pytest.fail("이상치가 없어야 하는데 판단이 호출됨"))

    load_scenario(session, cid, "normal")
    orch.run_agent(session, cid)

    msgs = _messages(session, cid)
    assert "이상한 달은 없었어요" in msgs, f"정상 시나리오에 이상치: {msgs}"
    assert "왜 그런지 다시 확인해볼게요" not in msgs


def test_gap_in_non_gas_fuel_is_detected_and_notified(db):
    """결손 감지는 "가스" 하드코딩이 아니라 get_coverage()가 실제로 찾은 결손이면
    어떤 연료든 감지·알림돼야 한다(리뷰 지적사항 — 실제 업로드 데이터를 읽어야지
    가스만 보는 시나리오 전용 로직이면 안 됨). 도시가스 전표는 아예 없는 채로
    경유만 1·2월분만 넣어 3~12월 경유 결손을 만든다."""
    from db.models import Voucher

    session, cid = db
    company = session.get(Company, cid)
    company.fuel_types_json = {
        "electricity": False, "diesel": True, "gasoline": False,
        "city_gas": False, "lpg": "no",
    }
    for month in (1, 2):
        session.add(Voucher(
            company_id=cid, source="hometax", year=2025, month=month,
            supplier_name="구미석유", item_description="경유",
            supply_amount_krw=600_000, raw_json={"quantity": 400},
        ))
    session.commit()

    orch.run_agent(session, cid)

    msgs = _messages(session, cid)
    assert "경유/유류" in msgs and "비어있네요" in msgs, f"경유 결손이 감지 안 됨: {msgs}"
    assert "가스" not in msgs, f"가스 전표가 아예 없는데 가스 언급이 나옴(하드코딩 잔재 의심): {msgs}"
    assert "고지서가 아직 연동 안 됐어요" in msgs, f"사장 알림(notify_owner)이 안 나감: {msgs}"


def test_judge_failure_is_visible_not_hidden(db, monkeypatch):
    """실패 가시성: LLM 판단 불가 시 대체 판정 없이 '재검증 실패'가 트레이스에 남는다."""
    session, cid = db
    monkeypatch.setattr(orch, "_judge_anomaly_with_llm", lambda items: None)

    load_scenario(session, cid, "demo")
    result = orch.run_agent(session, cid)

    msgs = _messages(session, cid)
    assert "다시 확인하다가 막혔어요" in msgs, f"판단 실패가 트레이스에 없음: {msgs}"
    assert "정상적인 사용이니 걱정 안 하셔도 돼요" not in msgs  # 판단한 척하지 않는다
    assert result["mode"] == "judge_failed"
