"""검증 3수치 중 '분류 정확도' — `기대_결과` 50건(사람 작성 정답지) 채점.

docs/verification-3metrics-plan.md §1이 정의한 대로 세 지표를 분리해서 계산한다.
정답지 자체를 순환논리 없는 근거로 쓰기 위해, 합성전표_300건.csv(룰 엔진이
스스로 라벨링한 강건성 표본)는 쓰지 않는다.

  1. Scope/연료 분류 정확도 — 자동확정(auto) 건만 별도, 전체 건도 별도 표기
  2. HITL 회부 정확도 — confusion matrix (정밀도/재현율, 재현율이 핵심 방어지표)
  3. 물량 추정 정확도 — expected_activity_amount가 있는 건만, 오차율

⚠️ 채점 로직은 반드시 `api.agent.tools`의 실제 프로덕션 함수(_rule_decision /
_llm_result_to_decision / _build_classification)를 그대로 호출한다 — 판정 로직을
스크립트에서 재구현하면(구 버전에서 그렇게 했다가) 계산 엔진의 review_required
역전(예: LPG는 confidence가 높아도 db/calc_engine.py가 최종적으로 review로
되돌림)을 놓쳐 존재하지 않는 회귀를 오탐하게 된다. Voucher는 DB에 커밋하지
않고 인메모리로만 만들어 순수 함수처럼 사용한다.

사용: python -m scripts.score_classification_accuracy
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from datetime import date, datetime

import openpyxl
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.agent.rules import get_rules
from api.agent.tools import CONFIDENCE_THRESHOLD, _build_classification, _llm_result_to_decision, _rule_decision
from db.calc_engine import index_emission_factors, index_unit_prices
from db.excel_loader import DEFAULT_XLSX, load_emission_factors, load_expected_results, load_unit_prices
from db.models import LlmCache, Voucher


def _load_voucher_dates(path: str = DEFAULT_XLSX) -> dict[str, dict]:
    """전표_샘플 시트에서 전표ID -> {year, month, quantity} (기대_결과와 조인용)."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["전표_샘플"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {h: i for i, h in enumerate(header)}
    out = {}
    for r in rows[1:]:
        if not any(r):
            continue
        vid = r[idx["전표ID"]]
        if not vid:
            continue
        raw_date = r[idx["날짜"]]
        if isinstance(raw_date, (date, datetime)):
            year, month = raw_date.year, raw_date.month
        elif isinstance(raw_date, str) and raw_date:
            parsed = datetime.strptime(raw_date.strip(), "%Y-%m-%d")
            year, month = parsed.year, parsed.month
        else:
            year, month = 2025, 1
        qty = r[idx["수량"]]
        out[str(vid).strip()] = {
            "year": year,
            "month": month,
            "quantity": float(qty) if qty is not None else None,
        }
    return out


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decide(session: Session, voucher: Voucher, rules: list[dict]) -> dict | None:
    """실제 파이프라인과 동일한 분기: 룰 확정 -> 캐시(llm_cache) 조회. 캐시 미스면 None."""
    decided, rule = _rule_decision(voucher)
    if decided is not None:
        return decided
    cached = session.execute(
        select(LlmCache).where(LlmCache.text_hash == _hash(voucher.item_description))
    ).scalar_one_or_none()
    if cached is None:
        return None
    return _llm_result_to_decision(cached.llm_response, rule_hint=rule)


def main() -> None:
    load_dotenv()
    rules = get_rules(DEFAULT_XLSX)
    expected_rows = load_expected_results()
    voucher_dates = _load_voucher_dates(DEFAULT_XLSX)
    price_index = index_unit_prices(load_unit_prices(DEFAULT_XLSX))
    factor_index = index_emission_factors(load_emission_factors(DEFAULT_XLSX))

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    scope_fuel_total = 0
    scope_fuel_correct = 0
    scope_fuel_correct_auto_only = 0
    auto_total = 0
    llm_miss_items = []

    hitl_confusion = Counter()  # (expected_bool, predicted_bool)

    qty_errors = []
    mismatches = []
    hitl_fn_detail = []

    with Session(engine) as session:
        for expected in expected_rows:
            vid = expected["voucher_id"]
            item = expected["item"]
            amount_krw = expected["amount_krw"] or 0
            dates = voucher_dates.get(vid, {"year": 2025, "month": 1, "quantity": None})

            voucher = Voucher(
                id=None,
                company_id=0,
                source="test",
                year=dates["year"],
                month=dates["month"],
                item_description=item,
                supply_amount_krw=amount_krw,
                raw_json={"quantity": dates["quantity"]} if dates["quantity"] else {},
            )

            decided = _decide(session, voucher, rules)
            if decided is None:
                llm_miss_items.append(item)
                continue

            # 실제 프로덕션 함수 그대로 호출 — 계산 엔진의 review_required 역전까지 반영됨.
            classification = _build_classification(voucher, decided, price_index, factor_index)

            status_auto = classification.status == "auto"

            # ── 지표 1: Scope/연료 분류 정확도 ──────────────────────────
            exp_scope = expected["scope"]
            exp_fuel = expected["fuel"]
            got_scope = classification.scope
            got_fuel = classification.fuel_type
            is_correct = (got_scope == exp_scope) and (
                exp_scope is None or (got_fuel or "").strip() == (exp_fuel or "").strip()
            )
            scope_fuel_total += 1
            if is_correct:
                scope_fuel_correct += 1
            else:
                mismatches.append(
                    dict(voucher_id=vid, item=item, expected=(exp_scope, exp_fuel), got=(got_scope, got_fuel), method=classification.method)
                )
            if status_auto:
                auto_total += 1
                if is_correct:
                    scope_fuel_correct_auto_only += 1

            # ── 지표 2: HITL 회부 confusion matrix ──────────────────────
            exp_hitl = bool(expected["needs_review"])
            got_hitl = not status_auto
            hitl_confusion[(exp_hitl, got_hitl)] += 1
            if exp_hitl and not got_hitl:
                hitl_fn_detail.append(
                    dict(voucher_id=vid, item=item, confidence=classification.confidence,
                         k_taxonomy=bool(classification.finance_lead_type))
                )

            # ── 지표 3: 물량 추정 정확도 (정답지에 활동량 있는 건만, 계산 성공 건만) ──
            exp_qty = expected["activity_amount"]
            if exp_qty is not None and classification.activity_amount is not None and not classification.calc_failure_reason:
                got_qty = classification.activity_amount
                if exp_qty:
                    err = abs(got_qty - exp_qty) / exp_qty
                    qty_errors.append((vid, item, exp_qty, got_qty, err))

    # ── 출력 ────────────────────────────────────────────────────────
    print(f"룰 엔진: {len(rules)}개 규칙 / 정답지: {len(expected_rows)}건\n")

    if llm_miss_items:
        print(f"⚠️ llm_cache 미스로 스킵된 건 {len(llm_miss_items)}개: {llm_miss_items}")
        print("   (먼저 scripts/score_gemini_call_ratio.py 사전조사로 캐시를 채워야 함)\n")

    print("=" * 60)
    print("1. Scope/연료 분류 정확도")
    print("=" * 60)
    if scope_fuel_total:
        print(f"  전체(자동확정+HITL 포함): {scope_fuel_correct}/{scope_fuel_total} "
              f"({scope_fuel_correct/scope_fuel_total:.1%})")
    if auto_total:
        print(f"  자동확정(auto)건만      : {scope_fuel_correct_auto_only}/{auto_total} "
              f"({scope_fuel_correct_auto_only/auto_total:.1%})")
    if mismatches:
        print(f"\n  오분류 {len(mismatches)}건:")
        for m in mismatches:
            print(f"    [{m['voucher_id']}/{m['method']}] {m['item']!r}: "
                  f"기대={m['expected']} 실제={m['got']}")

    print()
    print("=" * 60)
    print("2. HITL 회부 confusion matrix (기대, 실제)")
    print("=" * 60)
    tp = hitl_confusion[(True, True)]
    fn = hitl_confusion[(True, False)]
    fp = hitl_confusion[(False, True)]
    tn = hitl_confusion[(False, False)]
    print(f"  TP(HITL 기대·HITL 회부)     : {tp}")
    print(f"  FN(HITL 기대·자동확정됨)    : {fn}  ← 놓친 위험 건, 방어논리상 가장 중요")
    print(f"  FP(자동 기대·HITL 회부됨)   : {fp}")
    print(f"  TN(자동 기대·자동확정)      : {tn}")
    if tp + fn:
        print(f"  재현율(recall) = TP/(TP+FN) = {tp}/{tp+fn} = {tp/(tp+fn):.1%}")
    if tp + fp:
        print(f"  정밀도(precision) = TP/(TP+FP) = {tp}/{tp+fp} = {tp/(tp+fp):.1%}")
    if fn:
        k_tax_fn = sum(1 for d in hitl_fn_detail if d["k_taxonomy"])
        print(f"\n  FN {fn}건 중 K택소노미 리드(별도 채널, docs/owner-admin-flow-spec.md §5)"
              f" 성격: {k_tax_fn}건 — 배출량 HITL 큐가 아니라 리드 리스트로 이미 노출됨")
        for d in hitl_fn_detail:
            tag = "[K택소노미]" if d["k_taxonomy"] else "[일반]"
            print(f"    {tag} [{d['voucher_id']}] {d['item']!r} confidence={d['confidence']}")

    print()
    print("=" * 60)
    print("3. 물량 추정 정확도 (정답지에 활동량 있고 계산 성공한 건만)")
    print("=" * 60)
    if qty_errors:
        avg_err = sum(e[-1] for e in qty_errors) / len(qty_errors)
        print(f"  대상 {len(qty_errors)}건, 평균 오차율 {avg_err:.1%}")
        for vid, item, exp, got, err in qty_errors:
            flag = "  " if err < 0.05 else " ⚠"
            print(f"   {flag}[{vid}] {item!r}: 기대={exp} 실제={got} 오차={err:.1%}")
    else:
        print("  대상 없음")


if __name__ == "__main__":
    main()
