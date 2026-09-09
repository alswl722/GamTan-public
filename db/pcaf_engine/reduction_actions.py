"""감축 실천 ToDo — 홈 화면 "이번주 할 일" 카드의 계산 레이어.

정본: docs/reduction-todo-plan.md. 이 문서의 3층 설계를 그대로 구현한다.

LLM은 이 모듈에 전혀 관여하지 않는다(CLAUDE.md §5 원칙1). 목표·방법은 전부
결정론적 계산과 룰 매칭이며, 문장 다듬기(2차 스코프)조차 이 모듈의 산출값을
그대로 받아 순서·톤만 바꿀 뿐 숫자를 새로 만들지 않는다.

1층(어느 연료를 볼지)은 이 모듈에 없다 — 기존 `api/queries.py::get_distribution()`을
호출부(라우터)가 그대로 재사용한다.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, Voucher
from db.pcaf_engine.pcaf import monthly_by_fuel

# ── 2층: 설비 신호 ────────────────────────────────────────────────────────
#
# 새 매칭 로직이 아니다 — 이미 매 전표마다 도는 룰 엔진(api/agent/rules.py::
# match_rule())의 결과를 읽기만 한다(docs/reduction-todo-plan.md §4).
#
# R058("설비 유지보수비", k_taxonomy_mapping에 매핑 없음 → finance_lead_type
# null이라 은행 리드 목록에서 조용히 빠짐)을 "노후 설비 의심" 신호로 재해석하는
# 것이 이 모듈의 유일한 신규 판단이다.
#
# ⚠️ R058의 auto_action이 "사람검토"라 api/agent/tools.py::_SHORT_CIRCUIT_ACTIONS
# (자동분류|자동제외|참고분류)에 안 들어간다 — 즉 R058이 매칭돼도 룰 경로로
# 확정되지 않고 **항상 LLM으로 위임된다**(_rule_decision()이 rule_hint로만
# 넘김). 그래서 "[R058] ..." 접두사 포맷(_rule_decision 89행, 룰 경로 전용)이
# 아니라, LLM 경로의 _llm_result_to_decision()(tools.py:192)이 붙이는
# `evidence = f"{llm_reason} — 분류 규칙상 사람검토 필요(참고: R058)"` 접미사로
# 식별해야 한다(실측 확인, 2026-08-25 — GEMINI_API_KEY 없이 직접 실행해
# method="llm", evidence 끝에 "(참고: R058)"이 붙는 걸 확인했다. 최초 설계
# 초안은 "[R058]" 접두사 룰 경로를 전제했으나 틀렸다). LLM이 만드는 앞부분
# 문장은 매번 달라질 수 있어 `like("%...%")`로 부분일치 검색한다.
_AGING_EQUIPMENT_MARKER = "(참고: R058)"


def aging_equipment_signal(session: Session, company_id: int) -> bool:
    """이 기업에 "노후 설비 의심"(R058 매칭) 전표가 하나라도 있으면 True.

    반려된 분류는 신뢰할 수 없어 제외한다(k_taxonomy_leads()와 동일 원칙,
    db/pcaf_engine/k_taxonomy.py 참고). R058은 항상 LLM 경로로 가므로
    method 필터는 두지 않는다(위 주석 참고).
    """
    stmt = (
        select(Classification.id)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Classification.status != "rejected",
            Classification.evidence.like(f"%{_AGING_EQUIPMENT_MARKER}%"),
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def facility_signals(session: Session, company_id: int) -> dict:
    """이 기업의 설비 신호 요약 — 2층의 전체 출력.

    k_taxonomy_facility_type은 기존 db/pcaf_engine/k_taxonomy.py가 이미 채운
    컬럼을 원시 조회만 한다(k_taxonomy_leads_for_company()는 은행 리드 화면
    전용이라 건드리지 않는다 — 같은 컬럼을 다른 목적으로 재조회하는 것뿐).

    반환: {"facility_types": [...], "aging_equipment": bool}
    facility_types는 중복 제거된 k_taxonomy_facility_type 리스트(예:
    ["전동지게차", "히트펌프"]) — 순서는 무의미하므로 정렬해 반환한다.
    """
    stmt = (
        select(Classification.k_taxonomy_facility_type)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Classification.k_taxonomy_facility_type.isnot(None),
            Classification.status != "rejected",
        )
        .distinct()
    )
    facility_types = sorted(row[0] for row in session.execute(stmt).all())
    return {
        "facility_types": facility_types,
        "aging_equipment": aging_equipment_signal(session, company_id),
    }


# ── 3층: 기준부하 추정 ──────────────────────────────────────────────────
#
# "이 기업이 이미 보여준 적 있는 최선의 달"을 목표 기준선으로 삼는다. 외부
# 카탈로그 없이 그 기업 자신의 실측치만으로 개인화된 목표를 만든다(원칙1과
# 정합 — 계산은 이 함수뿐, LLM은 관여하지 않음).
#
# 반드시 "추정"으로 표기해야 한다(docs/reduction-todo-plan.md §5.3) — 월 단위
# 최저값은 일회성 저사용월(예: 휴업)일 수 있어 확정치가 아니다(CLAUDE.md §5
# 원칙10과 같은 결).


def baseline_load_by_fuel(session: Session, company_id: int, *, months: list[tuple[int, int]] | None = None) -> dict:
    """연료 대분류(전기/가스/경유·유류)별 최근 기준부하(월별 최저 tCO2e)와
    현재값(가장 최근 달)을 함께 반환.

    months를 주지 않으면 monthly_by_fuel()의 기본 동작(달력 전체 기간 합산)을
    그대로 따른다 — 호출부가 db/pcaf_engine/company_goals.py::_trailing_months()
    와 같은 패턴으로 "최근 12개월" 윈도우를 만들어 넘기는 게 정상 사용법이다
    (이 함수 자체는 윈도우를 만들지 않는다 — 단일 책임 유지).

    0을 기준부하로 착각하지 않도록, 실제 활동이 있던 달(total_tco2e > 0)만
    최저값 후보로 본다. 전 구간 활동이 없는 연료는 결과에서 아예 뺀다
    (원칙7 — 미산정을 0으로 합산하지 않는다).

    반환: {fuel_bucket: {"baseline_tco2e": float, "baseline_month": int,
                          "current_tco2e": float, "current_month": int}}
    """
    rows = monthly_by_fuel(session, company_id, months=months)
    if not rows:
        return {}

    by_fuel_series: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        for fuel, value in row["by_fuel"].items():
            by_fuel_series.setdefault(fuel, []).append((row["month"], value))

    result = {}
    for fuel, series in by_fuel_series.items():
        active = [(m, v) for m, v in series if v > 0]
        if not active:
            continue
        baseline_month, baseline_value = min(active, key=lambda pair: pair[1])
        current_month, current_value = series[-1]  # monthly_by_fuel 반환 순서 = 시간순, 마지막이 최신
        result[fuel] = {
            "baseline_tco2e": baseline_value,
            "baseline_month": baseline_month,
            "current_tco2e": current_value,
            "current_month": current_month,
        }
    return result


def reduction_target_for_fuel(baseline_tco2e: float, current_tco2e: float) -> dict | None:
    """기준부하 대비 감축 목표를 계산. 이미 기준부하 이하로 쓰고 있으면(개선
    여지 없음) None — "이미 최선을 다하고 있는 연료"까지 목표로 들이밀지
    않는다.

    반환: {"potential_reduction_tco2e": float, "reduction_pct": float}
    """
    if current_tco2e <= baseline_tco2e:
        return None
    potential = round(current_tco2e - baseline_tco2e, 3)
    pct = round((potential / current_tco2e) * 100, 1) if current_tco2e > 0 else 0.0
    return {"potential_reduction_tco2e": potential, "reduction_pct": pct}


# ── 폴백: 검증 불가 참고 팁 (카탈로그 정식 액션 아님) ─────────────────────
#
# 2층 신호가 없는 기업(고지서만 있어 세금계산서 품목 매칭이 안 되는 경우)을
# 위한 최소 폴백. verify_metric이 없어 카탈로그 정식 액션(§2 안전장치)에는
# 못 들어간다 — "참고 팁"으로 분리해 체크리스트가 아닌 별도 섹션에 둔다
# (docs/reduction-todo-plan.md §6). 출처: 탄소중립포인트제 공식 사이트
# 실사이트 확인(2026-08-25) — 가정용 8개 항목 중 사업장에도 적용 가능한 3개만
# 채택.
#
# 2026-08-26: note에 있던 절약 예상값(kgCO2e·원)을 제거했다 — "절약 예상값
# 보여줄 생각 없음" 사용자 확정 지시. 이 수치는 애초에 "가정 기준 참고치"라고
# 스스로 표기했던 것으로, 사업장(이 카드의 사용자)에는 적용 근거가 없어
# 원칙10(확정치처럼 표기 금지)에도 걸리는 이중 문제였다 — 단순 표기 변경이
# 아니라 애초에 이 카드에 들어오면 안 됐던 수치를 뺀 것.
#
# 같은 날, tip_standby_power의 "대기전력은 전체 사용 전력의 약 10%를
# 차지해요" 부연 설명도 마저 제거했다 — 사용자 지시("이런 부연설명 없어도
# 돼", 공기압축기 note와 동일한 판단). label 한 줄만으로 todo가 완결되게
# 한다 — note는 필요할 때만 붙이는 선택 보강이지 필수가 아니다.
FALLBACK_TIPS = [
    {
        "id": "tip_temperature",
        "label": "냉난방 온도 1도 조정",
        "note": None,
    },
    {
        "id": "tip_lighting",
        "label": "절전형 조명으로 교체",
        "note": None,
    },
    {
        "id": "tip_standby_power",
        "label": "대기전력 차단",
        "note": None,
    },
]
