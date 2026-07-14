"""도구② 전반부 — 룰(키워드) 매칭 엔진.

`분류_기준표_확장` 시트의 50개 규칙으로 확정 케이스를 LLM 없이 분류한다
(CLAUDE.md §5-3: 룰 매칭 먼저 → 미매칭·애매 건만 LLM).
"""
from db.excel_loader import DEFAULT_XLSX, load_classification_rules

_RULES_CACHE: list[dict] | None = None


def get_rules(path: str = DEFAULT_XLSX) -> list[dict]:
    """정렬된 룰 리스트. 프로세스당 1회 로드해 캐싱(엑셀 변경은 재시작으로 반영)."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = load_classification_rules(path)
    return _RULES_CACHE


_EXCLUDING_ACTIONS = ("자동제외", "참고분류")


def match_rule(item_description: str, rules: list[dict] | None = None) -> dict | None:
    """품목명에 매치되는 규칙을 반환. 매치 없으면 None.

    매치 조건(규칙별): include_keywords 중 하나 이상 부분일치 AND
    exclude_keywords는 하나도 매치되지 않음(OR 리스트 — 회계 룰북이 각 항목을
    독립적 동의어로 작성했음을 `분류_기준표_확장` 전수 검증으로 확인함).

    안전장치: 여러 규칙이 동시에 매치되면(예: "지게차 정비비"가 R005(경유,
    자동분류)와 R033(수리비, 자동제외)에 둘 다 걸리는 경우) `자동제외`·`참고분류`
    매치를 우선한다 — Scope1/2로 잘못 산입하는 것이 잘못 제외하는 것보다 위험이
    크므로, 배출량 미산정 방향의 안전 실패를 택한다. `db/excel_loader.py`의
    `load_expected_results()` 40건 정답지로 이 우선순위 없이는 실패(지게차
    정비비가 경유 이동연소로 오분류)함을 확인했다.
    """
    text = item_description or ""
    matches = [
        rule
        for rule in (rules if rules is not None else get_rules())
        if any(kw in text for kw in rule["include_keywords"])
        and not any(kw in text for kw in rule["exclude_keywords"])
    ]
    if not matches:
        return None
    excluding = [r for r in matches if r["auto_action"] in _EXCLUDING_ACTIONS]
    return excluding[0] if excluding else matches[0]
