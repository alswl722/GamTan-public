"""에이전트 도구함 — 오케스트레이터가 골라 호출할 독립 함수들.

도구① 데이터 수집 · 도구② 전표 분류(룰→Gemini→캐시) · 도구③ 계산·PCAF ·
도구④ 업종 벤치마킹. 시그니처를 여기서 고정하면, 다음 슬라이스의
오케스트레이터는 이 함수를 호출만 하면 된다.
"""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.agent.llm_classify import (
    cache_get,
    cache_put,
    classify_with_llm_nocache,
    hash_item,
)
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
from db.k_taxonomy import k_taxonomy_fields_for_rule
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


def _rule_decision(voucher: Voucher) -> tuple[dict | None, dict | None]:
    """룰 매칭만 수행. (확정 결과 dict | None, rule) — 확정 아니면 LLM 필요."""
    rule = match_rule(voucher.item_description)
    if rule is not None and rule["auto_action"] in _SHORT_CIRCUIT_ACTIONS:
        confidence = _RULE_CONFIDENCE.get(rule["quality_grade"], 0.85)
        decided = {
            "scope": rule["scope"],
            "category": rule["category"],
            "fuel_type": rule["fuel_type"],
            "evidence": f"[{rule['rule_id']}] {rule['reasoning']}",
            "method": "rule",
            "mixed_item": rule["mixed_item"],
            "confidence": confidence,
            # K택소노미 매핑은 rule_id로만 연결된다(LLM 경로는 이 키가 없음 — 아래
            # _llm_result_to_decision 참고, K택소노미는 룰 매칭 키워드 세트로만 커버됨).
            "rule_id": rule["rule_id"],
        }
        return decided, rule
    return None, rule


def _build_classification(
    voucher: Voucher,
    decided: dict,
    price_index: dict,
    factor_index: dict,
) -> Classification:
    """분류 결과(룰 또는 LLM) → Classification + 결정론적 계산(도구③)까지 채워 반환."""
    amount = voucher.supply_amount_krw
    scope, category, fuel_type = decided["scope"], decided["category"], decided["fuel_type"]
    evidence = decided["evidence"]
    confidence = decided["confidence"]
    status = "auto" if confidence >= CONFIDENCE_THRESHOLD else "review_required"

    # K택소노미·설비투자 리드 — rule_id(룰 매칭 경로만)가 회계 매핑표(k_taxonomy_mapping)에
    # 있으면 채워진다. 배출량 계산과 무관, 여신 결정도 아니다(위 db/k_taxonomy.py 참고).
    k_taxonomy_fields = k_taxonomy_fields_for_rule(decided.get("rule_id"))

    classification = Classification(
        voucher_id=voucher.id,
        scope=scope,
        category=category,
        fuel_type=fuel_type,
        amount_krw=amount,  # LLM이 반환한 금액이 아니라 전표 원본 금액을 신뢰 (LLM 산수 금지 원칙)
        confidence=confidence,
        evidence=evidence,
        method=decided["method"],
        mixed_item=1 if decided["mixed_item"] else 0,
        status=status,
        # v1 §7.1 — 업로드/마이데이터 경로로 들어온 전표는 raw_json에 원본 문서 FK가 있다.
        source_document_id=(voucher.raw_json or {}).get("source_document_id"),
        **k_taxonomy_fields,
    )

    # 도구③ 계산 엔진 — 물량·탄소량은 결정론적 코드로만 산출 (db/calc_engine.py)
    # 활동량 산정 우선순위: 전표 실측 수량(raw_json) > 금액÷단가 추정 > 사람검토
    raw = voucher.raw_json or {}
    try:
        calc_input = ClassifiedItemInput(
            fuel_type=fuel_type or "",
            scope=scope,
            amount_krw=float(amount or 0),
            year=voucher.year,
            month=voucher.month,
            quantity=raw.get("quantity"),
            quantity_unit=raw.get("quantity_unit"),
        )
        result = compute_emission(calc_input, price_index, factor_index)
        classification.activity_amount = result["activity_amount"]
        classification.activity_unit = result["activity_unit"]
        classification.emission_co2e = result["emission_co2e"]
        # 회계 규칙상 사람검토 대상(LPG·전기/가스 사용량 미기재) → HITL
        # 계산 실패 사유는 evidence(판단 근거)와 섞지 않고 별도 컬럼에 저장한다.
        if result.get("needs_review"):
            classification.status = "review_required"
            classification.calc_failure_reason = result["reason"]
    except CalcDataGap as gap:
        # 계수는 있는데 해당 월 단가가 없는 진짜 데이터 갭 — 사람 검토로 이관
        classification.status = "review_required"
        classification.calc_failure_reason = str(gap)

    return classification


def _llm_result_to_decision(llm: dict) -> dict:
    """Gemini(또는 캐시) 응답 dict → _build_classification 이 먹는 결정 dict로 변환."""
    return {
        "scope": llm.get("scope"),
        "category": llm.get("category"),
        "fuel_type": llm.get("fuel_type"),
        "evidence": llm.get("evidence"),
        "method": "llm",
        "mixed_item": bool(llm.get("mixed_item")),
        "confidence": float(llm.get("confidence") or 0.0),
    }


_LLM_MAX_WORKERS = 6  # 동시 Gemini 호출 수 상한 — 무료 티어 QPS 보호용 (CLAUDE.md §5-4)


def classify_vouchers(
    session: Session,
    company_id: int,
    on_progress=None,
) -> dict:
    """도구② 전표 분류 — 룰 매칭 우선, 애매·미매칭 건만 Gemini 호출.

    이미 분류된 전표는 건너뛴다(재실행 안전). 분류 직후 도구③ 계산 엔진으로
    activity_amount/activity_unit/emission_co2e까지 채워 저장한다.

    캐시 미스로 실제 Gemini 호출이 필요한 건만 스레드풀로 병렬 처리한다
    (세션은 스레드 세이프하지 않으므로 네트워크 호출만 병렬화하고, DB 판정·
    커밋은 메인 스레드에서 순차로 수행 — CLAUDE.md §5-4 캐시 레이어와 병행).

    on_progress(done, total): 선택적 콜백 — 프론트 진행률 폴링용(장면②).
    """
    vouchers = _unclassified_vouchers(session, company_id)
    price_index = index_unit_prices(get_unit_prices(session))
    factor_index = index_emission_factors(get_emission_factors(session))
    total = len(vouchers)
    done = 0
    if on_progress:
        on_progress(0, total)  # 시작 즉시 리셋 — 이전 실행의 '완료 100%' 잔류 방지

    def _tick():
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total)

    # 1단계 — 룰 확정 건은 즉시 처리, 나머지는 캐시 조회(순차, DB IO라 빠름)까지만.
    pending: list[tuple[Voucher, dict | None, int, int]] = []  # (voucher, rule_hint, amount, index)
    created: list[Classification | None] = [None] * total
    for i, voucher in enumerate(vouchers):
        decided, rule = _rule_decision(voucher)
        if decided is not None:
            created[i] = _build_classification(voucher, decided, price_index, factor_index)
            _tick()
            continue
        amount = int(voucher.supply_amount_krw or 0)
        text_hash = hash_item(voucher.item_description)
        cached = cache_get(session, text_hash)
        if cached is not None:
            decided = _llm_result_to_decision(cached)
            created[i] = _build_classification(voucher, decided, price_index, factor_index)
            _tick()
        else:
            pending.append((voucher, rule, amount, i))

    # 2단계 — 캐시 미스인 것만 스레드풀로 병렬 Gemini 호출(세션 없이, 순수 네트워크).
    # 동일 품목 텍스트는 1회만 호출·1회만 캐시 저장 — 같은 배치에 '디젤유'가 2장 있을 때
    # cache_put 이 두 번 돌면 text_hash unique 충돌로 실행 전체가 죽는다.
    if pending:
        unique: dict[str, tuple[str, int, dict | None]] = {}  # hash -> (text, amount, rule_hint)
        for v, rule, amount, _i in pending:
            unique.setdefault(hash_item(v.item_description), (v.item_description, amount, rule))

        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=_LLM_MAX_WORKERS) as pool:
            futures = {
                pool.submit(classify_with_llm_nocache, text, amount, rule): h
                for h, (text, amount, rule) in unique.items()
            }
            for fut in futures:
                results[futures[fut]] = fut.result()

        for h, llm in results.items():
            # 성공 건만 캐시에 남김(실패 폴백은 다음 실행 때 재시도되도록 — 기존 정책 유지)
            if (llm.get("confidence") or 0) > 0 or llm.get("scope") is not None:
                text, _, _ = unique[h]
                cache_put(session, h, text, llm)

        for v, rule, amount, i in pending:
            llm = results[hash_item(v.item_description)]
            decided = _llm_result_to_decision(llm)
            created[i] = _build_classification(v, decided, price_index, factor_index)
            _tick()

    for c in created:
        session.add(c)
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
