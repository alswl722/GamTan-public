"""기업대출 금융배출량(귀속계수) — 산식 구현 (v1 Tier 3, docs/v1-plan.md §8,
docs/tasks.md).

⚠️ 착수 여부가 팀 결정 사항인 Tier 3 항목이다. 이번 스코프는 **산식만
구현·검증**한다 — `business_loan_exposures`(대출잔액)가 0건이라 실측 계산은
아직 불가능하다(은행 내부 여신 시스템 연동 필요, 이 모듈이 채울 수 없는
데이터). 그래서 이 모듈은 프로덕션 엔드포인트에 자동으로 연결하지 않는다
— mock 대출잔액을 넣어야만 값이 나오고, 그 값을 실측처럼 노출하면 안 된다.

산식(불변):
  분모 = 총자본 + PCAF 방법론상 total debt
  IF 분모 <= 0: 계산 중단
  ELSE: 귀속계수 = 대출잔액 / 분모, 금융배출량 = 귀속계수 × 차주 배출량

db/calc_engine.py와 같은 원칙 — 결정론적 순수 함수, 계산 불가는 예외가
아니라 명시적 dict로 반환한다(LLM 산수 금지와 같은 결, 이 모듈도 재계산이
아니라 이미 있는 값을 곱할 뿐이다).
"""
from pydantic import BaseModel, Field


class AttributionInput(BaseModel):
    """귀속계수 계산 입력. 대출잔액·총자본·총부채 전부 0 이상이어야 한다
    (음수 재무정보는 데이터 오류이지 계산 대상이 아니다)."""

    outstanding_amount: float = Field(ge=0)
    total_equity: float = Field(ge=0)
    total_debt: float = Field(ge=0)


def compute_attribution_factor(inputs: AttributionInput) -> dict:
    """귀속계수 = 대출잔액 / (총자본 + 총부채).

    분모(총자본+총부채)가 0 이하면 계산할 수 없다 — 예외를 던지지 않고
    계산 불가를 명시적으로 반환한다(db/calc_engine.py::_review와 같은 패턴,
    상위 호출부가 review_required로 돌릴 수 있게).
    """
    denominator = inputs.total_equity + inputs.total_debt
    if denominator <= 0:
        return {
            "attribution_factor": None,
            "denominator": denominator,
            "computed": False,
            "reason": "분모(총자본+총부채)가 0 이하 — 계산 불가",
        }
    factor = inputs.outstanding_amount / denominator
    return {
        "attribution_factor": round(factor, 6),
        "denominator": denominator,
        "computed": True,
        "reason": None,
    }


def compute_financed_emission(
    attribution_factor: float | None, borrower_emission_tco2e: float | None
) -> dict:
    """금융배출량 = 귀속계수 × 차주 배출량.

    둘 중 하나라도 None이면 곱셈 자체를 하지 않는다 — 차주 배출량이
    미산정(Scope 미확정)인데 0으로 대입해 곱하면 "계산됐지만 사실은
    미산정"인 값이 만들어진다. CLAUDE.md 원칙 "미산정 Scope는 0으로
    합산하지 않는다"를 금융배출량에도 그대로 적용한다.
    """
    if attribution_factor is None:
        return {
            "financed_emission_tco2e": None,
            "computed": False,
            "reason": "귀속계수 미계산 — 분모 없음",
        }
    if borrower_emission_tco2e is None:
        return {
            "financed_emission_tco2e": None,
            "computed": False,
            "reason": "차주 배출량 미산정 — 0으로 대입하지 않음",
        }
    return {
        "financed_emission_tco2e": round(attribution_factor * borrower_emission_tco2e, 6),
        "computed": True,
        "reason": None,
    }
