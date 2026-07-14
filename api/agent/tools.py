"""에이전트 도구함 — 오케스트레이터가 골라 호출할 독립 함수들.

도구① 데이터 수집 · 도구② 전표 분류(룰→Gemini→캐시) · 도구③ 계산·PCAF ·
도구④ 업종 벤치마킹. 시그니처를 여기서 고정하면, 다음 슬라이스의
오케스트레이터는 이 함수를 호출만 하면 된다.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.agent.llm_classify import classify_with_llm
from api.agent.rules import match_rule
from api.queries import (
    get_coverage,
    get_distribution,
    get_emission_factors,
    get_unit_prices,
    get_vouchers,
)
from db.calc_engine import (
    CalcDataGap,
    ClassifiedItemInput,
    compute_emission,
    index_emission_factors,
    index_unit_prices,
)
from db.models import Classification, Voucher
from db.pcaf import company_pcaf_summary

# LLM confidence 임계값 — 미달 시 HITL(review_required)로 이관 (CLAUDE.md §5-3)
CONFIDENCE_THRESHOLD = 0.7

# 룰 매칭(자동분류/자동제외/참고분류) 확정 건의 confidence — 회계 룰북의
# `기본 데이터품질`(A~E) 등급을 신뢰도로 환산. LLM 경로가 아니라 룰 자체가
# 확신하는 케이스이므로 전부 임계값 이상으로 시작한다.
_RULE_CONFIDENCE = {"A": 0.97, "A/B": 0.93, "B": 0.90, "C": 0.75, "E": 0.95}
_SHORT_CIRCUIT_ACTIONS = ("자동분류", "자동제외", "참고분류")


def collect_vouchers(session: Session, company_id: int) -> dict:
    """도구① 데이터 수집 — 전표 목록 + 커버리지(결손 관찰 재료)를 함께 반환."""
    vouchers = get_vouchers(session, company_id)
    coverage = get_coverage(session, company_id)
    return {"count": len(vouchers), "vouchers": vouchers, "coverage": coverage}


def get_industry_distribution(session: Session, industry_code: str, scope: int) -> dict | None:
    """도구④ 업종 벤치마킹 — 동종 업종 배출량 분포(min/median/max)."""
    return get_distribution(session, industry_code, scope)


def calculate_pcaf(session: Session, company_id: int) -> dict:
    """도구③ 후반부 — 저장된 분류 결과를 집계해 PCAF Before/After·벤치마킹 반환.

    아이템별 결정론 계산(금액→물량→탄소량)은 classify_vouchers 가 이미
    compute_emission 으로 수행해 Classification 에 저장해 둔다. 이 함수는
    그 저장분을 읽어 등급으로 집계만 한다(읽기 전용).
    """
    return company_pcaf_summary(session, company_id)


def _unclassified_vouchers(session: Session, company_id: int) -> list[Voucher]:
    already = select(Classification.voucher_id)
    stmt = (
        select(Voucher)
        .where(Voucher.company_id == company_id)
        .where(Voucher.id.notin_(already))
        .order_by(Voucher.month, Voucher.issue_date)
    )
    return session.execute(stmt).scalars().all()


def _classify_one(
    session: Session,
    voucher: Voucher,
    price_index: dict,
    factor_index: dict,
) -> Classification:
    rule = match_rule(voucher.item_description)
    amount = voucher.supply_amount_krw

    if rule is not None and rule["auto_action"] in _SHORT_CIRCUIT_ACTIONS:
        confidence = _RULE_CONFIDENCE.get(rule["quality_grade"], 0.85)
        scope, category, fuel_type = rule["scope"], rule["category"], rule["fuel_type"]
        evidence = f"[{rule['rule_id']}] {rule['reasoning']}"
        method = "rule"
        mixed_item = rule["mixed_item"]
        status = "auto"
    else:
        # 검토후분류/사람검토로 매치됐거나(rule_hint로 힌트만 제공) 아예 미매칭 → LLM
        llm = classify_with_llm(session, voucher.item_description, int(amount or 0), rule_hint=rule)
        confidence = float(llm.get("confidence") or 0.0)
        scope, category, fuel_type = llm.get("scope"), llm.get("category"), llm.get("fuel_type")
        evidence = llm.get("evidence")
        method = "llm"
        mixed_item = bool(llm.get("mixed_item"))
        status = "auto" if confidence >= CONFIDENCE_THRESHOLD else "review_required"

    classification = Classification(
        voucher_id=voucher.id,
        scope=scope,
        category=category,
        fuel_type=fuel_type,
        amount_krw=amount,  # LLM이 반환한 금액이 아니라 전표 원본 금액을 신뢰 (LLM 산수 금지 원칙)
        confidence=confidence,
        evidence=evidence,
        method=method,
        mixed_item=1 if mixed_item else 0,
        status=status,
    )

    # 도구③ 계산 엔진 — 물량·탄소량은 결정론적 코드로만 산출 (db/calc_engine.py)
    try:
        calc_input = ClassifiedItemInput(
            fuel_type=fuel_type or "",
            scope=scope,
            amount_krw=float(amount or 0),
            year=voucher.year,
            month=voucher.month,
        )
        result = compute_emission(calc_input, price_index, factor_index)
        classification.activity_amount = result["activity_amount"]
        classification.activity_unit = result["activity_unit"]
        classification.emission_co2e = result["emission_co2e"]
    except CalcDataGap as gap:
        # 계수는 있는데 해당 월 단가가 없는 진짜 데이터 갭 — 사람 검토로 이관
        classification.status = "review_required"
        classification.evidence = f"{evidence} | 계산 불가: {gap}"

    return classification


def classify_vouchers(session: Session, company_id: int) -> dict:
    """도구② 전표 분류 — 룰 매칭 우선, 애매·미매칭 건만 Gemini 호출.

    이미 분류된 전표는 건너뛴다(재실행 안전). 분류 직후 도구③ 계산 엔진으로
    activity_amount/activity_unit/emission_co2e까지 채워 저장한다.
    """
    vouchers = _unclassified_vouchers(session, company_id)
    price_index = index_unit_prices(get_unit_prices(session))
    factor_index = index_emission_factors(get_emission_factors(session))

    created: list[Classification] = []
    for voucher in vouchers:
        classification = _classify_one(session, voucher, price_index, factor_index)
        session.add(classification)
        created.append(classification)
    session.commit()

    return {
        "processed": len(created),
        "auto": sum(1 for c in created if c.status == "auto"),
        "review_required": sum(1 for c in created if c.status == "review_required"),
        "by_method": {
            "rule": sum(1 for c in created if c.method == "rule"),
            "llm": sum(1 for c in created if c.method == "llm"),
        },
    }
