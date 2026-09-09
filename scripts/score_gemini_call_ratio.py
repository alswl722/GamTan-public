"""검증용 — 룰 매칭이 확정 못해 Gemini(LLM) 호출로 넘어갈 비율을 사전 추정.

실제 Gemini는 호출하지 않는다. `api/agent/tools.py::_rule_decision()`과 동일한
단축 판정 로직(_SHORT_CIRCUIT_ACTIONS)을 그대로 재사용해, 룰이 확정 짓는 건과
LLM으로 넘어가는 건을 나눈다. 대상은 두 소스:

  1. `기대_결과` 시트 50건 — 사람이 작성한 정답지 (docs/verification-3metrics-plan.md
     §1이 "순환논리 없는 근거"로 지목한 소스)
  2. `data/합성전표_300건.csv` 300건 — 룰 엔진 자체가 라벨링한 강건성 표본
     (순환논리 있음 — 룰 통과율이 곧 라벨링 방식이므로 여기선 참고용)

사용: python -m scripts.score_gemini_call_ratio
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from api.agent.rules import get_rules, match_rule
from db.excel_loader import DEFAULT_XLSX, load_expected_results

_SHORT_CIRCUIT_ACTIONS = ("자동분류", "자동제외", "참고분류")

SYNTH_CSV = Path("data/합성전표_300건.csv")


def _would_call_llm(item_description: str, rules: list[dict]) -> bool:
    """_rule_decision()과 동일 조건: 매치 없거나 auto_action이 단축 대상이 아니면 LLM행."""
    rule = match_rule(item_description, rules)
    if rule is None:
        return True
    return rule["auto_action"] not in _SHORT_CIRCUIT_ACTIONS


def score_expected_results(rules: list[dict]) -> dict:
    rows = load_expected_results()
    counter = Counter()
    llm_items = []
    for r in rows:
        item = r["item"]
        if _would_call_llm(item, rules):
            counter["llm"] += 1
            llm_items.append(item)
        else:
            counter["rule"] += 1
    return {"total": len(rows), "counter": counter, "llm_items": llm_items}


def score_synthetic_300(rules: list[dict]) -> dict:
    if not SYNTH_CSV.exists():
        return {"total": 0, "counter": Counter(), "llm_items": []}
    counter = Counter()
    llm_items = []
    with SYNTH_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for r in rows:
        item = r["item_description"]
        if _would_call_llm(item, rules):
            counter["llm"] += 1
            llm_items.append(item)
        else:
            counter["rule"] += 1
    return {"total": len(rows), "counter": counter, "llm_items": llm_items}


def _print_result(name: str, result: dict) -> None:
    total = result["total"]
    if total == 0:
        print(f"[{name}] 데이터 없음")
        return
    rule = result["counter"].get("rule", 0)
    llm = result["counter"].get("llm", 0)
    print(f"[{name}] 총 {total}건")
    print(f"  룰 확정  : {rule}건 ({rule/total:.1%})")
    print(f"  LLM 호출 : {llm}건 ({llm/total:.1%})")
    if result["llm_items"]:
        print("  LLM으로 넘어간 품목명 (중복 포함):")
        for item, cnt in Counter(result["llm_items"]).most_common():
            print(f"    - {item!r} x{cnt}")
    print()


def main() -> None:
    rules = get_rules(DEFAULT_XLSX)
    print(f"룰 엔진 로드: {len(rules)}개 규칙 ({DEFAULT_XLSX})\n")

    _print_result("기대_결과 50건 (사람 작성 정답지)", score_expected_results(rules))
    _print_result("합성전표_300건.csv (룰 자체 라벨링, 참고용)", score_synthetic_300(rules))


if __name__ == "__main__":
    main()
