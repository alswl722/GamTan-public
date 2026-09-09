"""월간 AI 브리핑 문장 조립 — db/owner_briefing.py 단위 테스트.

핵심 검증축:
  - 증가/감소/변화없음/신규 4가지 direction 분기가 올바르게 갈린다.
  - 지난달 데이터가 아예 없으면(첫 달) 비교 문장 대신 시작 안내를 쓴다 —
    없는 지난달과 억지로 %를 비교하지 않는다.
  - 지난달 대비 계산은 새 배출량 계산이 아니라 기존 값(this_month_co2e,
    last_month_co2e)을 그대로 나눈 것뿐이다(파생값 검증).
  - get_briefing_paragraphs(): LLM 성공 시 캐시에 기록되고, 같은 입력이면
    재호출 없이 캐시를 재사용한다(db/gov_support/evidence.py와 동일 패턴).
    LLM 실패 시 템플릿으로 폴백하고, 폴백 여부는 generated_by로 구분된다
    (실패를 감추지 않음). 저수준 generate_briefing_paragraphs_llm을
    monkeypatch로 갈아끼워 실제 네트워크 호출 없이 검증한다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db import owner_briefing
from db.models import Base, LlmCache
from db.owner_briefing import (
    FuelMonthStat,
    build_briefing_paragraphs,
    compute_fuel_deltas,
    get_briefing_paragraphs,
    validate_briefing_numbers,
)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


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


def test_get_briefing_paragraphs_uses_llm_when_available(session, monkeypatch):
    monkeypatch.setattr(
        owner_briefing, "generate_briefing_paragraphs_llm",
        lambda deltas, has_previous_month: ["우디가 만든 문장이에요."],
    )
    fuel_deltas = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])

    paragraphs, generated_by = get_briefing_paragraphs(session, fuel_deltas, has_previous_month=True)

    assert generated_by == "llm"
    assert paragraphs == ["우디가 만든 문장이에요."]


def test_get_briefing_paragraphs_falls_back_to_template_on_llm_failure(session, monkeypatch):
    monkeypatch.setattr(
        owner_briefing, "generate_briefing_paragraphs_llm",
        lambda deltas, has_previous_month: None,  # API 오류·키 없음 등 실패 시그니처
    )
    fuel_deltas = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])

    paragraphs, generated_by = get_briefing_paragraphs(session, fuel_deltas, has_previous_month=True)

    assert generated_by == "template"
    assert paragraphs == build_briefing_paragraphs(fuel_deltas, has_previous_month=True)


def test_get_briefing_paragraphs_caches_llm_result(session, monkeypatch):
    calls = []

    def _fake_llm(deltas, has_previous_month):
        calls.append(deltas)
        return ["첫 호출 결과"]

    monkeypatch.setattr(owner_briefing, "generate_briefing_paragraphs_llm", _fake_llm)
    fuel_deltas = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])

    first_paragraphs, first_source = get_briefing_paragraphs(session, fuel_deltas, has_previous_month=True)
    second_paragraphs, second_source = get_briefing_paragraphs(session, fuel_deltas, has_previous_month=True)

    assert first_source == "llm"
    assert second_source == "llm_cache"
    assert first_paragraphs == second_paragraphs == ["첫 호출 결과"]
    assert len(calls) == 1  # 두 번째 호출은 캐시 적중, LLM 재호출 없음
    assert session.query(LlmCache).count() == 1


def test_validate_briefing_numbers_accepts_numbers_from_fuel_deltas():
    fuel_deltas = compute_fuel_deltas([
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),
    ])
    # delta_pct == 18.0, this_month_co2e == 2.36, last_month_co2e == 2.0
    paragraphs = ["경유 사용량이 지난달보다 18% 늘었어요. 이번 달 2.36톤, 지난달 2톤이었어요."]
    assert validate_briefing_numbers(paragraphs, fuel_deltas) is True


def test_validate_briefing_numbers_rejects_hallucinated_number():
    fuel_deltas = compute_fuel_deltas([
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),
    ])
    # 25%는 실제 delta_pct(18.0)와 무관하게 LLM이 지어낸 숫자
    paragraphs = ["경유 사용량이 지난달보다 25% 늘었어요."]
    assert validate_briefing_numbers(paragraphs, fuel_deltas) is False


def test_validate_briefing_numbers_ignores_non_numeric_text():
    fuel_deltas = compute_fuel_deltas([
        FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0),
    ])
    paragraphs = ["아래에서 이번 달 숫자들을 자세히 볼 수 있어요."]
    assert validate_briefing_numbers(paragraphs, fuel_deltas) is True


def test_generate_briefing_paragraphs_llm_rejects_hallucinated_number(monkeypatch):
    """LLM이 JSON 스키마는 지켰지만 존재하지 않는 숫자(환각)를 문장에 섞어
    반환하면, generate_briefing_paragraphs_llm이 사후 검증에서 걸러 None을
    반환해야 한다 — 프롬프트 지시("숫자를 그대로만 인용")를 믿지 않고
    코드가 최종 관문 역할을 한다는 걸 실제 호출 경로로 확인."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    class _FakeResponse:
        text = json.dumps({"paragraphs": ["경유 사용량이 지난달보다 25% 늘었어요."]})  # 실제 delta_pct(18.0)와 다른 값

    class _FakeModels:
        def generate_content(self, **kwargs):
            return _FakeResponse()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = _FakeModels()

    monkeypatch.setattr(owner_briefing.genai, "Client", _FakeClient)

    fuel_deltas = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])
    result = owner_briefing.generate_briefing_paragraphs_llm(fuel_deltas, has_previous_month=True)
    assert result is None


def test_generate_briefing_paragraphs_llm_accepts_valid_number(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    class _FakeResponse:
        text = json.dumps({"paragraphs": ["경유 사용량이 지난달보다 18% 늘었어요."]})  # 실제 delta_pct와 일치

    class _FakeModels:
        def generate_content(self, **kwargs):
            return _FakeResponse()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = _FakeModels()

    monkeypatch.setattr(owner_briefing.genai, "Client", _FakeClient)

    fuel_deltas = compute_fuel_deltas([FuelMonthStat(fuel_type="경유", this_month_co2e=2.36, last_month_co2e=2.0)])
    result = owner_briefing.generate_briefing_paragraphs_llm(fuel_deltas, has_previous_month=True)
    assert result == ["경유 사용량이 지난달보다 18% 늘었어요."]


def test_get_briefing_paragraphs_does_not_call_llm_for_first_month(session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        owner_briefing, "generate_briefing_paragraphs_llm",
        lambda deltas, has_previous_month: calls.append(1) or ["안 불려야 함"],
    )

    paragraphs, generated_by = get_briefing_paragraphs(session, [], has_previous_month=False)

    assert generated_by == "template"
    assert calls == []  # 비교할 지난달이 없으면 LLM에 물을 내용 자체가 없음
