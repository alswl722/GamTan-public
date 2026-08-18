"""기업대출 금융배출량(귀속계수) 산식 검증 (v1 Tier 3, docs/v1-plan.md §8,
docs/tasks.md).

핵심 검증축:
  - 정상 케이스: 귀속계수 = 대출잔액/(총자본+총부채), 금융배출량 = 귀속계수×차주배출량.
  - 분모(총자본+총부채) <= 0이면 예외 없이 계산 중단(None)을 반환한다.
  - 차주 배출량이 None(미산정)이면 0으로 대입해 곱하지 않는다 — 결과도 None.
  - 순수 함수라 pydantic 검증(음수 입력 거부)만으로 충분 — DB 세션 불필요.
"""
import pytest
from pydantic import ValidationError

from db.pcaf_engine.financed_emissions import (
    AttributionInput,
    compute_attribution_factor,
    compute_financed_emission,
)


def test_attribution_factor_normal_case():
    inputs = AttributionInput(outstanding_amount=300_000_000, total_equity=200_000_000, total_debt=800_000_000)
    result = compute_attribution_factor(inputs)
    assert result["computed"] is True
    assert result["attribution_factor"] == pytest.approx(0.3)
    assert result["denominator"] == 1_000_000_000


def test_attribution_factor_zero_denominator_returns_none_not_exception():
    inputs = AttributionInput(outstanding_amount=100, total_equity=0, total_debt=0)
    result = compute_attribution_factor(inputs)
    assert result["computed"] is False
    assert result["attribution_factor"] is None
    assert "분모" in result["reason"]


def test_attribution_input_rejects_negative_values():
    with pytest.raises(ValidationError):
        AttributionInput(outstanding_amount=-1, total_equity=100, total_debt=100)


def test_financed_emission_normal_case():
    result = compute_financed_emission(attribution_factor=0.3, borrower_emission_tco2e=155.96)
    assert result["computed"] is True
    assert result["financed_emission_tco2e"] == pytest.approx(46.788)


def test_financed_emission_none_when_attribution_factor_missing():
    result = compute_financed_emission(attribution_factor=None, borrower_emission_tco2e=100.0)
    assert result["computed"] is False
    assert result["financed_emission_tco2e"] is None


def test_financed_emission_none_when_borrower_emission_not_calculated():
    """차주 배출량 미산정 시 0으로 대입하지 않는다 — CLAUDE.md 원칙과 동일."""
    result = compute_financed_emission(attribution_factor=0.5, borrower_emission_tco2e=None)
    assert result["computed"] is False
    assert result["financed_emission_tco2e"] is None
    assert "미산정" in result["reason"]


def test_end_to_end_chain_from_attribution_to_financed_emission():
    inputs = AttributionInput(outstanding_amount=300_000_000, total_equity=200_000_000, total_debt=800_000_000)
    attribution = compute_attribution_factor(inputs)
    result = compute_financed_emission(attribution["attribution_factor"], 155.96)
    assert result["computed"] is True
    assert result["financed_emission_tco2e"] == pytest.approx(155.96 * 0.3)
