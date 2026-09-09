"""킬러씬 스모크 테스트 — demo 시나리오에서 결손 감지 + 이상치 자가검증이 실제로 발생하는지.

이상치 판별식·시나리오 구성이 바뀌어 킬러씬이 조용히 사라지는 회귀를 잡는다
(과거 사고: 업종 연중앙값÷12 비교식이 동절기 1월 도시가스를 항상 이상치 1순위로
올려 "지게차 증차 → 정상 판정" 장면이 어떤 시나리오에서도 나오지 않았음).

네트워크는 쓰지 않는다 — LLM 호출 지점 2곳(분류·이상치 판단)을 스텁으로 대체.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import api.agent.orchestrator as orch
import api.queries as queries
from db.init_db import (
    seed_emission_factors,
    seed_industry_distributions,
    seed_unit_prices,
)
from db.models import Base, Company, TraceLog
from db.scenarios import load_scenario


class _FixedDatetime(datetime):
    """get_coverage()가 "올해"로 인식할 기준시각을 2025년 말로 고정."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2025, 12, 31, 12, 0, tzinfo=tz)


@pytest.fixture(autouse=True)
def _freeze_coverage_year(monkeypatch):
    """get_coverage()는 연도를 생략하면 이제 달력상 올해만 본다(실측 2026-08-17)
    — 이 스모크 테스트는 2025년 고정 시나리오 데이터(db/scenarios.py, 회계 엑셀
    단가 연도와 맞물려 있어 임의로 못 바꿈)를 쓰므로, "올해"를 2025년으로 고정해
    기존 시나리오 동작을 그대로 재현한다."""
    monkeypatch.setattr(queries, "datetime", _FixedDatetime)


def _stub_llm_classify(text: str, amount: int, rule_hint=None) -> dict:
    """키워드 기반 완벽 분류 스텁 — LLM 대상(애매 표현) 건에 결정론적 응답.

    "가스/전기 아니면 무조건 경유"인 else 분기가 있어, R058(설비 유지보수비,
    db/scenarios.py의 공통 설비 신호 전표)처럼 세 연료 어디에도 안 걸리는
    문구가 LLM으로 위임되면 실제로는 scope=None(설비투자 불명확, 실측 확인
    api/agent/llm_classify.py)이어야 하는데 이 스텁만 "경유"로 오분류해
    _check_anomalies()의 Scope1 이상치 판정을 오염시켰다(2026-08-25 실측
    — 정상 시나리오에서 12월 경유 총량에 설비 전표 금액이 섞여 이상치로 잡힘).
    rule_hint로 "설비투자 불명확" 계열이 넘어오면 그 판단을 그대로 따른다."""
    if rule_hint is not None and rule_hint.get("category") in ("감축투자 후보", "설비투자 불명확"):
        scope, category, fuel = None, rule_hint["category"], "없음"
    elif "가스" in text or "LNG" in text or "난방유" not in text and "난방" in text:
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
    """demo 시나리오 = 킬러씬 A 전체: 결손 발견 + 7월 경유 이상치 자가검증.

    이상치 되묻기(docs/tasks.md) 도입 이후: LLM이 "정상"으로 1차 판단해도
    최종 확인은 사장님 몫이라 anomaly_check_status='pending'으로 남는다 —
    evidence 주석은 참고용이고, 트레이스 문구도 "확인 부탁드릴게요"로 바뀐다
    (예전처럼 AI가 단독으로 "걱정 안 하셔도 돼요"라고 확정하지 않음).
    """
    session, cid = db
    monkeypatch.setattr(orch, "_judge_anomaly_with_llm",
                        lambda items: (True, "지게차 2대 증차 문구 확인"))

    load_scenario(session, cid, "demo")
    result = orch.run_agent(session, cid)

    msgs = _messages(session, cid)
    assert "비어있네요" in msgs, f"결손 감지 스텝 없음: {msgs}"
    assert "7월 경유" in msgs and "왜 그런지 다시 확인해볼게요" in msgs, f"이상치 감지 스텝 없음: {msgs}"
    assert "사장님께도 확인 부탁드릴게요" in msgs, f"자가검증 1차판정 스텝 없음: {msgs}"
    assert result["mode"] == "llm"

    from db.models import Classification, Voucher
    pending = (
        session.query(Classification)
        .join(Voucher, Voucher.id == Classification.voucher_id)
        .filter(Voucher.company_id == cid, Voucher.month == 7, Classification.fuel_type == "경유")
        .all()
    )
    assert pending, "7월 경유 분류 행을 찾지 못함"
    assert all(c.anomaly_check_status == "pending" for c in pending), \
        "LLM이 정상 판단해도 사장님 확인 전까지는 pending으로 남아야 함"


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
    assert "사장님께도 확인 부탁드릴게요" not in msgs  # 판단한 척하지 않는다
    assert result["mode"] == "judge_failed"

    # judge_outcome="call_failed"가 detail에 남아, API 장애로 인한 실패와
    # LLM이 정상 응답했지만 사유를 못 찾은 "불명" 케이스가 로그상 구분된다.
    steps = session.query(TraceLog).filter(TraceLog.company_id == cid).all()
    failed_steps = [s for s in steps if (s.detail_json or {}).get("judge_outcome") == "call_failed"]
    assert len(failed_steps) == 1
    assert failed_steps[0].message == "다시 확인하다가 막혔어요. 제가 판단하지 않고 사장님이 직접 봐주셨으면 해요."


def test_judge_uncertain_is_distinguished_from_call_failure(db, monkeypatch):
    """LLM이 정상 응답했지만("불명") API 장애가 아닌 경우, judge_outcome이
    call_failed가 아니라 uncertain으로 구분되어 트레이스에 남아야 한다 —
    운영에서 장애율과 '설명 안 되는 이상치' 빈도를 다른 신호로 볼 수 있어야
    하기 때문."""
    session, cid = db
    monkeypatch.setattr(orch, "_judge_anomaly_with_llm", lambda items: (False, ""))

    load_scenario(session, cid, "demo")
    orch.run_agent(session, cid)

    steps = session.query(TraceLog).filter(TraceLog.company_id == cid).all()
    uncertain_steps = [s for s in steps if (s.detail_json or {}).get("judge_outcome") == "uncertain"]
    assert uncertain_steps, "불명 판정이 트레이스에 남지 않음"
