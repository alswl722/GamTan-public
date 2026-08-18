"""회귀 테스트 — 룰 엔진이 "연료 종류 불명"으로 이미 판단한 케이스는 LLM
프롬프트가 그 판단을 그대로 따르도록 강하게 지시해야 한다(2026-08-18 실측 발견).

배경: R018("공장 가스비" 등, category="가스종류 불명")처럼 룰이 애초에 연료를
특정할 수 없다고 판단한 케이스도, 기존 프롬프트는 "참고만 하고 다르게 답해도
된다"고 LLM에 재량을 줘서 confidence 0.8~0.9로 도시가스/불명 등을 자체
확정해버렸다 — 정답지(기대_결과 50건)와 어긋나는 오분류로 실측 발견.
category에 "불명"이 포함된 rule_hint는 별도 문구로 강하게 지시하도록
api/agent/llm_classify.py::_build_prompt를 수정했다.
"""
from api.agent.llm_classify import _build_prompt


def test_unknown_category_hint_forbids_free_guessing():
    """category에 "불명"이 포함된 룰 힌트는 "임의로 추정하지 말라"는 문구와
    회계 룰의 불명 표기(category)를 그대로 쓰라는 지시가 프롬프트에 있어야 한다."""
    rule_hint = {
        "rule_id": "R018",
        "scope": None,
        "category": "가스종류 불명",
        "fuel_type": "가스",
        "reasoning": "가스 종류 확인 필요",
    }
    prompt = _build_prompt("공장 가스비", 270_000, rule_hint)
    assert "임의로 추정하지 말고" in prompt
    assert '"가스종류 불명"' in prompt


def test_normal_hint_still_allows_llm_override():
    """category가 불명 계열이 아닌 일반 룰 힌트(예: R006류)는 기존처럼 LLM이
    더 정확히 판단하면 다르게 답해도 된다는 재량 문구를 유지한다 — 회귀 방지."""
    rule_hint = {
        "rule_id": "R006",
        "scope": 1,
        "category": "이동연소",
        "fuel_type": "경유",
        "reasoning": "차량 연료는 이동연소",
    }
    prompt = _build_prompt("차량 유지비", 100_000, rule_hint)
    assert "다르게 답해도 된다" in prompt
    assert "임의로 추정하지 말고" not in prompt


def test_no_hint_produces_plain_prompt():
    """rule_hint가 없으면(룰 매칭 자체가 안 된 완전 미매칭 텍스트) 힌트 문구가
    아예 없어야 한다 — 회귀 방지."""
    prompt = _build_prompt("알 수 없는 품목", 50_000, None)
    assert "참고(룰 엔진" not in prompt
