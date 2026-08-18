"""연료 유형 체크 → 업로드 문서 요구 상태 판정 (순수함수, DB 접근 없음).

사장님이 2단계(연료 유형 체크)에서 고른 값을 바탕으로 3단계(문서 업로드)에서
어떤 문서가 필수/선택/해당없음인지 결정한다. 규칙은 팀이 확정한 일반 규칙을
그대로 코드화한 것이다:

  - Scope1 연료(경유·휘발유·LPG) 중 하나라도 체크(LPG는 "예"·"잘 모르겠어요"
    포함) → 세금계산서 필수
  - 도시가스 체크 → 도시가스고지서 필수
  - 전기고지서는 항상 필수 (한전 마이데이터엔 kWh가 없어 고지서 업로드로만 확보 가능)
  - Scope1 연료가 하나도 없으면(예: "전기만") 세금계산서는 선택 —
    설비투자/K택소노미 리드 유인용으로 업로드를 권하되 강제하지 않는다
"""
from typing import Literal, TypedDict

LpgStatus = Literal["yes", "no", "unsure"]
DocumentStatus = Literal["required", "optional", "not_applicable"]
DocumentType = Literal["tax_invoice", "electric_bill", "gas_bill"]


class FuelTypes(TypedDict, total=False):
    diesel: bool
    gasoline: bool
    city_gas: bool
    lpg: LpgStatus
    electricity: bool  # 참고용 — 결과에 영향 없음(전기고지서는 항상 필수)


def required_documents(fuel_types: FuelTypes) -> dict[DocumentType, DocumentStatus]:
    """문서 종류별 요구 상태를 반환한다."""
    scope1_selected = bool(
        fuel_types.get("diesel")
        or fuel_types.get("gasoline")
        or fuel_types.get("lpg") in ("yes", "unsure")
    )
    city_gas_selected = bool(fuel_types.get("city_gas"))

    return {
        "tax_invoice": "required" if scope1_selected else "optional",
        "electric_bill": "required",
        "gas_bill": "required" if city_gas_selected else "not_applicable",
    }
