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


def _rule_matches(text: str, rule: dict) -> bool:
    """`include_keywords`(AND-그룹 리스트) 전 그룹에서 최소 하나씩 부분일치 AND
    `exclude_keywords`는 하나도 매치되지 않아야 규칙이 매치된다.

    include_keywords는 `db/excel_loader.py::_split_keyword_groups()`가 만든
    `list[list[str]]` — 그룹 간 AND, 그룹 내부 OR. 세미콜론 없이 작성된 룰은
    그룹이 1개뿐이라 기존 flat OR 리스트와 매치 결과가 동일하다(하위호환).
    """
    groups = rule["include_keywords"]
    if not groups:
        return False
    if any(kw in text for kw in rule["exclude_keywords"]):
        return False
    return all(any(kw in text for kw in group) for group in groups)


def match_rule(item_description: str, rules: list[dict] | None = None) -> dict | None:
    """품목명에 매치되는 규칙을 반환. 매치 없으면 None. 매치 판정은 `_rule_matches()`.

    include_keywords는 룰마다 두 가지 의도가 섞여 있다 — ①동의어 OR(예: R001의
    "한국전력"/"한전"/"전기요금") ②기기명+연료명 AND(예: R006 "차량 연료는
    이동연소" — "차량"만으로는 안 되고 연료 키워드도 함께 있어야 함). 시트에서
    세미콜론(`;`)으로 그룹을 나눈 룰은 그룹 간 AND로 해석되고, 세미콜론이 없는
    룰(순수 동의어 룰 다수)은 기존과 동일하게 flat OR로 해석된다 — 이 구분이
    없던 시절엔 R006이 "차량 렌트료"·"영업용 차량 보험료" 같은 무관한 표현에도
    검토 없이(needs_review=False) Scope1 경유로 자동 확정됐음을 실측으로 확인한
    뒤 이 AND-그룹 표기를 도입했다.

    안전장치: 여러 규칙이 동시에 매치되면(예: "지게차 정비비"가 R005(경유,
    자동분류)와 R033(수리비, 자동제외)에 둘 다 걸리는 경우) `자동제외`·`참고분류`
    매치를 우선한다 — Scope1/2로 잘못 산입하는 것이 잘못 제외하는 것보다 위험이
    크므로, 배출량 미산정 방향의 안전 실패를 택한다. `db/excel_loader.py`의
    `load_expected_results()` 정답지로 이 우선순위 없이는 실패(지게차
    정비비가 경유 이동연소로 오분류)함을 확인했다.
    """
    text = item_description or ""
    all_rules = rules if rules is not None else get_rules()
    matches = [rule for rule in all_rules if _rule_matches(text, rule)]
    if not matches:
        return None
    excluding = [r for r in matches if r["auto_action"] in _EXCLUDING_ACTIONS]
    return excluding[0] if excluding else matches[0]
