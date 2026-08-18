"""기업대출 금융배출량(귀속계수) — 산식 구현 (v1 Tier 3, docs/v1-plan.md §8,
docs/tasks.md).

⚠️ 착수 여부가 팀 결정 사항인 Tier 3 항목이다. `business_loan_exposures`
(대출잔액)는 은행 내부 여신 시스템 연동이 필요한 값이라(§8 "실서비스 데이터
획득 경로" 참고) 이 프로젝트가 직접 채울 수 없다 — 그래서 기후리스크
리포트(`GET /admin/climate-risk-report`)에 연결된 값은 **mock 대출잔액**
으로 계산한 예시일 뿐 실측이 아니다(`is_example: true` 플래그·"예시 데이터"
배지로 화면·PDF 양쪽에 명시). 산식 자체는 실측/mock 구분 없이 동일하게
동작한다 — 실제 대출잔액이 연동되면 mock 시딩 로직만 걷어내면 된다.

산식(불변):
  분모 = 총자본 + PCAF 방법론상 total debt
  IF 분모 <= 0: 계산 중단
  ELSE: 귀속계수 = 대출잔액 / 분모, 금융배출량 = 귀속계수 × 차주 배출량

db/calc_engine.py와 같은 원칙 — 결정론적 순수 함수, 계산 불가는 예외가
아니라 명시적 dict로 반환한다(LLM 산수 금지와 같은 결, 이 모듈도 재계산이
아니라 이미 있는 값을 곱할 뿐이다).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from db.models import BorrowerEmissionInventory, BorrowerFinancial, BusinessLoanExposure


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


def portfolio_financed_emissions_by_year(session: Session, portfolio_id: int) -> list[dict]:
    """포트폴리오 소속 대출 익스포저 전체를 연도별로 합산 — 기후리스크 리포트의
    "시계열 금융배출량" 입력.

    `compute_attribution_factor()`/`compute_financed_emission()`을 기업마다
    호출만 할 뿐 새 계산 로직은 없다. 재무정보(BorrowerFinancial)나 배출량
    인벤토리(BorrowerEmissionInventory)가 없는 기업은 자연스럽게 계산에서
    빠진다(개별 함수의 "계산 불가 시 None" 동작 그대로) — 억지로 0을 채우지
    않는다.

    반환: [{"year": int, "financed_emission_tco2e": float, "company_count": int}]
    company_count는 그 연도에 실제로 계산된(computed=True) 기업 수 — 데이터
    커버리지를 함께 보여줘 "몇 개 기업 기준 합산인지"를 투명하게 한다.
    """
    exposures = session.execute(
        select(BusinessLoanExposure).where(BusinessLoanExposure.portfolio_id == portfolio_id)
    ).scalars().all()

    by_year: dict[int, dict] = {}
    for exposure in exposures:
        year = exposure.reporting_date.year
        financial = session.execute(
            select(BorrowerFinancial)
            .where(BorrowerFinancial.company_id == exposure.company_id)
            .order_by(BorrowerFinancial.financial_year.desc())
        ).scalars().first()
        if financial is None:
            continue

        emission_rows = session.execute(
            select(BorrowerEmissionInventory).where(
                BorrowerEmissionInventory.company_id == exposure.company_id,
                BorrowerEmissionInventory.reporting_year == year,
            )
        ).scalars().all()
        emissions = [float(r.emission_tco2e) for r in emission_rows if r.emission_tco2e is not None]
        borrower_emission = sum(emissions) if emissions else None

        attribution = compute_attribution_factor(AttributionInput(
            outstanding_amount=float(exposure.outstanding_amount),
            total_equity=float(financial.total_equity or 0),
            total_debt=float(financial.total_debt or 0),
        ))
        result = compute_financed_emission(attribution["attribution_factor"], borrower_emission)
        if not result["computed"]:
            continue

        bucket = by_year.setdefault(year, {"total": 0.0, "company_count": 0})
        bucket["total"] += result["financed_emission_tco2e"]
        bucket["company_count"] += 1

    return [
        {
            "year": year,
            "financed_emission_tco2e": round(data["total"], 6),
            "company_count": data["company_count"],
        }
        for year, data in sorted(by_year.items())
    ]
