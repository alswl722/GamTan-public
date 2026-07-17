"""계산 엔진 — 금액 → 물량 → 탄소량. 순수 함수, DB 세션 불필요.

프로젝트 방어논리의 심장: "LLM은 분류·추출만, 산수는 결정론적 코드."
LLM/룰이 뱉은 (scope, fuel_type, amount_krw)만 입력받아 물량과 배출량을
계산한다 — 환각이 숫자에 개입할 경로가 없다.

  activity_amount = amount_krw ÷ 월별단가        (물량: L, kWh, m³, kg)
  emission_co2e   = activity_amount × 배출계수    (단위: kgCO2e)

⚠️ 단위 계약: emission_co2e 는 **kgCO2e** 로 반환·저장한다 (골든셋 기대_결과와
   1:1). tCO2e 표시는 상위(PCAF 집계·프론트)에서 ÷1000 한다.

인덱스(price_index/factor_index)는 DB에서 읽은 UnitPrice/EmissionFactor 전량을
호출부가 넘긴다 — 이 모듈은 DB를 모른다 (순수성 유지, 단위테스트 용이).
"""
from pydantic import BaseModel, Field


class CalcDataGap(Exception):
    """계산 불가한 진짜 데이터 갭 — 계수는 있는데 해당 월 단가가 없는 경우.

    상위(classify_vouchers)가 이 예외를 잡아 status='review_required'(HITL)로
    돌린다. '연료 자체가 불명(센티넬)'인 경우와는 구분된다 — 후자는 예외가
    아니라 skipped=True 로 정상 반환한다.
    """


class ClassifiedItemInput(BaseModel):
    """계산 엔진 입력 — 분류 결과에서 넘어오는 필드만. 물량·환산 필드는 없다."""

    fuel_type: str
    scope: int | None = None          # 1 | 2 | 3 | None(제외)
    amount_krw: float = Field(ge=0)
    year: int
    month: int = Field(ge=1, le=12)
    quantity: float | None = None     # 전표에 적힌 실측 사용량 (있으면 1순위 = 실측)
    quantity_unit: str | None = None  # L | kWh | m3 등


def index_unit_prices(rows) -> dict:
    """UnitPrice 행들 → {(fuel_type, year, month): {price, unit}}.

    rows 는 dict(load_unit_prices 출력) 또는 ORM 객체(UnitPrice) 둘 다 허용.
    """
    idx: dict = {}
    for r in rows:
        fuel = _get(r, "fuel_type")
        year = _get(r, "year")
        month = _get(r, "month")
        price = _get(r, "unit_price_krw")
        if fuel is None or year is None or month is None or price is None:
            continue
        idx[(fuel, int(year), int(month))] = {
            "price": float(price),
            "unit": _get(r, "unit"),
        }
    return idx


def index_emission_factors(rows) -> dict:
    """EmissionFactor 행들 → {(fuel_type, scope): {gwp_co2e, unit}}.

    계수가 없거나(None/0) scope 없는 센티넬 행은 인덱스에서 제외한다 —
    조회 실패 = '이 연료는 계산 대상 아님(불명/제외)' 신호가 되도록.
    """
    idx: dict = {}
    for r in rows:
        fuel = _get(r, "fuel_type")
        scope = _get(r, "scope")
        gwp = _get(r, "gwp_co2e")
        if gwp is None:
            gwp = _get(r, "factor_co2")
        if fuel is None or scope is None or not gwp:
            continue
        idx[(fuel, int(scope))] = {
            "gwp_co2e": float(gwp),
            "unit": _get(r, "unit"),
        }
    return idx


# 회계 규칙(엑셀 노트): LPG는 프로판/부탄·단위(kg/L) 구분 문제로 MVP 자동계산 제외 → 사람검토
_LPG_FUELS = ("LPG", "LPG(프로판)", "LPG(부탄)")
# 전기·도시가스는 단가 역산보다 고지서 사용량 우선 → 수량 없으면 추정 대신 사람검토
_QUANTITY_ONLY = ("전기", "도시가스")
# "연료 종류를 특정 못 함" 센티넬 — 룰/LLM이 명시적으로 불명이라 표시한 경우.
# 이건 계산 대상 아님(정상 스킵)이지만, 아래 '진짜 연료명인데 계수 미등록'과는 구분한다.
_UNKNOWN_FUELS = ("불명", "연료종류 불명", "가스종류 불명", "없음", "산업가스", "")


def compute_emission(item: ClassifiedItemInput, price_index: dict, factor_index: dict) -> dict:
    """활동량 → 배출량(kgCO2e). 결정론적 순수 계산. 활동량 산정은 회계 노트의 우선순위:
       1순위 실측 수량(전표에 kWh/L/m³) → 그대로  2순위 금액÷월별단가 추정  3순위 사람검토.

    반환: {activity_amount, activity_unit, emission_co2e, skipped, reason, method, needs_review}
      - method: "measured"(실측·상위등급) | "spend"(추정) | "review" | None(제외)
      - needs_review=True → 상위에서 HITL(status=review_required)
    예외: CalcDataGap — 계수·연료 유효한데 해당 월 단가가 없는 진짜 갭.
    """
    # 1) 제외 — scope 없음(사무용품·식대 등)
    if item.scope is None:
        return _skip("scope 없음 — 탄소 산정 제외")

    # 2) LPG — 프로판/부탄·단위 구분 문제로 자동계산 제외 → 사람검토
    if item.fuel_type in _LPG_FUELS:
        return _review("LPG(프로판/부탄·단위 구분) 자동계산 제외 — 사람 검토 필요")

    # 3) 계수 인덱스에 없음 — 두 경우를 구분한다:
    #    (a) 연료 불명 센티넬(가스종류 불명 등) → 애초에 계산 대상 아님, 정상 스킵
    #    (b) 진짜 연료명인데 계수 미등록(등유·아세틸렌 등, 룰은 Scope1로 확정) →
    #        조용히 배출량 0으로 빠지면 "Scope1인데 배출 0" 유령 데이터가 됨. HITL로.
    factor = factor_index.get((item.fuel_type, item.scope))
    if factor is None:
        if item.fuel_type in _UNKNOWN_FUELS:
            return _skip(f"배출계수 없음 — 연료 불명({item.fuel_type})")
        return _review(
            f"배출계수 미등록 — '{item.fuel_type}' 계수를 회계 담당이 추가해야 함 (사람 검토)"
        )

    # 4) 1순위 — 실측 수량이 있으면 그대로 사용 (spend 추정보다 정확 = PCAF 상위등급)
    if item.quantity and item.quantity > 0:
        activity = round(float(item.quantity), 4)
        unit = item.quantity_unit or factor["unit"]
        method = "measured"
    elif item.fuel_type in _QUANTITY_ONLY:
        # 전기·도시가스는 금액 역산 안 함 → 수량 없으면 사람검토
        return _review(f"{item.fuel_type} 사용량 미기재 — 금액 역산 대신 사람 검토")
    else:
        # 2순위 — 휘발유·경유: 금액÷월별단가 추정
        price_entry = price_index.get((item.fuel_type, item.year, item.month))
        if price_entry is None or not price_entry.get("price"):
            raise CalcDataGap(f"단가 없음 — {item.fuel_type} {item.year}-{item.month:02d} (HITL 회부)")
        activity = round(item.amount_krw / price_entry["price"], 4)
        unit = factor["unit"] or price_entry.get("unit")
        method = "spend"

    emission = round(activity * factor["gwp_co2e"], 4)
    return {
        "activity_amount": activity,
        "activity_unit": unit,
        "emission_co2e": emission,   # kgCO2e
        "skipped": False,
        "reason": None,
        "method": method,
        "needs_review": False,
    }


def _skip(reason: str) -> dict:
    return {
        "activity_amount": 0.0, "activity_unit": None, "emission_co2e": 0.0,
        "skipped": True, "reason": reason, "method": None, "needs_review": False,
    }


def _review(reason: str) -> dict:
    """계산 불가·규칙상 사람검토 대상 — emission 0, HITL 플래그."""
    return {
        "activity_amount": 0.0, "activity_unit": None, "emission_co2e": 0.0,
        "skipped": True, "reason": reason, "method": "review", "needs_review": True,
    }


def _get(row, key):
    """dict 와 ORM 객체를 모두 지원하는 필드 접근."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)
