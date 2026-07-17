"""llm_cache 사전 적재 — 시연 전 1회 실행해 "동일 전표 → 동일 응답" 상태를 만든다.

캐시는 실패 은폐가 아니라 정식 기능(비용·재현성, CLAUDE.md §5-4)이다:
시연 중 라이브 실행이 매번 같은 분류 결과를 보여주도록 사전 호출로 채운다.
적재 실패는 그대로 출력한다 — 실패한 항목은 시연 때 라이브 호출을 타게 되며,
그것도 실패하면 화면에 HITL(검토 필요)로 정직하게 표시된다.

사용:  .venv/bin/python scripts/warm_cache.py          # 전 시나리오 대상
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.agent.llm_classify import cache_get, classify_with_llm, hash_item
from api.agent.rules import match_rule
from db.scenarios import SCENARIOS
from db.synth_generator import generate

load_dotenv()

# tools._rule_decision 과 동일 기준 — 룰이 확정하는 건 LLM(캐시)을 타지 않는다
_SHORT_CIRCUIT_ACTIONS = ("자동분류", "자동제외", "참고분류")


def collect_llm_targets() -> dict[str, int]:
    """전 시나리오 전표 중 룰이 확정 못 하는(=LLM 경로) 유니크 텍스트 → 대표 금액."""
    targets: dict[str, int] = {}
    for name, sc in SCENARIOS.items():
        records = generate(sc["config"])
        just = sc.get("justify")
        for r in records:
            if just and r["month"] == just["month"] and r["label"]["fuel"] == just["fuel"]:
                r["item_description"] = just["text"]
        for r in records:
            text = r["item_description"]
            rule = match_rule(text)
            if rule is not None and rule["auto_action"] in _SHORT_CIRCUIT_ACTIONS:
                continue
            targets.setdefault(text, r["supply_amount_krw"])
    return targets


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("[!] GEMINI_API_KEY 미설정 — 적재 불가 (.env 확인)")
        return 1

    engine = create_engine(os.getenv("DATABASE_URL"))
    targets = collect_llm_targets()
    print(f"[i] LLM 경로 유니크 텍스트 {len(targets)}건")

    hit = new = failed = 0
    with Session(engine) as session:
        for text, amount in targets.items():
            if cache_get(session, hash_item(text)) is not None:
                hit += 1
                print(f"  [HIT ] {text}")
                continue
            result = classify_with_llm(session, text, amount)  # 성공 시 내부에서 캐시 저장
            if (result.get("confidence") or 0) > 0 or result.get("scope") is not None:
                new += 1
                print(f"  [NEW ] {text} → scope={result.get('scope')} conf={result.get('confidence')}")
            else:
                failed += 1
                print(f"  [FAIL] {text} → {result.get('evidence')}")

    print(f"\n[완료] 기존 {hit} · 신규 {new} · 실패 {failed}")
    if failed:
        print("[!] 실패 건은 캐시에 저장되지 않음 — 재실행하거나 시연 때 라이브 호출/HITL 경로로 감")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
