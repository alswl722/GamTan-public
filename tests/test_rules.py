"""룰 엔진(api/agent/rules.py) 검증 — 정답지는 db/excel_loader.load_expected_results()."""
from api.agent.rules import match_rule
from db.excel_loader import (
    _split_keyword_groups,
    load_classification_rules,
    load_expected_results,
)

RULES = load_classification_rules()
EXPECTED = load_expected_results()


def _rule(rule_id, include, exclude=(), auto_action="자동분류", scope=1, fuel_type="경유"):
    """AND-그룹 매칭 단위 테스트용 최소 룰 딕셔너리(실제 시트는 안 건드림)."""
    return dict(
        rule_id=rule_id,
        priority=1,
        include_keywords=include,
        exclude_keywords=list(exclude),
        scope=scope,
        category=None,
        fuel_type=fuel_type,
        auto_action=auto_action,
        needs_review=False,
        mixed_item=False,
        quality_grade="B",
        reasoning="",
        example="",
    )


# I050은 회계 확인 필요(task.md 참고) — I001("지게차 경유 외 1종")과 품목명·금액이
# 완전히 동일한 "중복 업로드 문서" 검증용 케이스라, 룰 엔진 입력(품목 텍스트)만으로는
# 원리적으로 구분 불가능하다(같은 텍스트는 같은 룰에 매칭되는 게 결정론적 룰 엔진의
# 정상 동작 — CLAUDE.md "동일 전표 텍스트 → 동일 응답" 원칙과도 부합). 중복 판정은
# source_documents.file_hash UQ 제약(§14, docs/db-schema.md)이 전담하는 영역이라
# 이 파일(룰 매칭 단위 테스트)의 검증 대상이 아니다.
_RULE_ENGINE_OUT_OF_SCOPE_IDS = {"I050"}


def _cases():
    for row in EXPECTED:
        if row["voucher_id"] in _RULE_ENGINE_OUT_OF_SCOPE_IDS:
            continue
        yield row


def test_expected_results_has_rows():
    assert len(EXPECTED) == 50


def test_auto_classified_rows_match_expected_scope_and_fuel():
    """auto_action='자동분류'로 확정되는 매치는 LLM/HITL을 안 타므로 오분류가
    바로 잘못된 배출량으로 이어진다 — scope·fuel 이 기대_결과와 정확히 일치해야 함."""
    for row in _cases():
        m = match_rule(row["item"], RULES)
        if m is None or m["auto_action"] != "자동분류":
            continue
        assert m["scope"] == row["scope"], f"{row['voucher_id']} {row['item']!r}: scope {m['scope']} != {row['scope']}"
        if row["fuel"]:
            assert m["fuel_type"] == row["fuel"], f"{row['voucher_id']} {row['item']!r}: fuel {m['fuel_type']} != {row['fuel']}"


def test_excluded_rows_match_expected_no_scope():
    """auto_action='자동제외'/'참고분류'는 Scope1/2 미산정 — 기대_결과도 scope=None(제외)이어야 함."""
    for row in _cases():
        m = match_rule(row["item"], RULES)
        if m is None or m["auto_action"] not in ("자동제외", "참고분류"):
            continue
        assert row["scope"] is None, f"{row['voucher_id']} {row['item']!r}: 제외 매치인데 기대_결과 scope={row['scope']}"


def test_forklift_maintenance_is_excluded_not_diesel():
    """회귀 테스트: '지게차 정비비'는 R005(경유,자동분류)와 R033(수리비,자동제외)에
    동시 매치되는데, 안전 우선(제외 우선) 로직 없이는 경유로 오분류됐었다."""
    m = match_rule("지게차 정비비", RULES)
    assert m is not None
    assert m["auto_action"] == "자동제외"
    assert m["scope"] is None


# --- AND-그룹 매칭(세미콜론 표기) 단위 테스트 ---
# 실제 시트를 안 건드리고 합성 룰로 엔진 동작만 검증한다.


def test_split_keyword_groups_flat_when_no_semicolon():
    """세미콜론 없으면 그룹 1개짜리 리스트 — 기존 flat OR 리스트와 매치 결과 동일."""
    assert _split_keyword_groups("납품차, 화물차, 경유, 주유") == [
        ["납품차", "화물차", "경유", "주유"]
    ]


def test_split_keyword_groups_semicolon_splits_and_groups():
    """세미콜론으로 AND-그룹 구분, 그룹 내부는 기존처럼 쉼표로 OR."""
    assert _split_keyword_groups("납품차,화물차;경유,주유") == [
        ["납품차", "화물차"],
        ["경유", "주유"],
    ]


def test_split_keyword_groups_empty_and_none():
    assert _split_keyword_groups(None) == []
    assert _split_keyword_groups("") == []


def test_and_group_rule_requires_all_groups():
    """AND-그룹 룰(device;fuel)은 두 그룹 모두 매치해야 하고, 한쪽만 있으면 안 걸린다.

    R006(합성 버전) 재현: 실제 시트 수정 전에는 '차량'이 flat OR 키워드라
    "영업용 차량 보험료" 같은 무관한 표현도 사람검토 없이 경유/Scope1로
    확정됐다 — AND-그룹으로 나누면 연료 신호(경유·주유)가 없는 텍스트는
    더 이상 매치되지 않는다.
    """
    rule = _rule(
        "TEST-AND",
        include=[["차량"], ["경유", "주유"]],
    )
    assert match_rule("영업용 차량 보험료", [rule]) is None
    assert match_rule("영업용 차량 경유 주유비", [rule]) is not None


def test_and_group_rule_matches_when_all_groups_present():
    """기기명 + 연료명이 함께 있으면 AND-그룹으로도 정상 매치된다."""
    rule = _rule(
        "TEST-AND-2",
        include=[["컴프레서", "압축기"], ["전력", "전기료"]],
    )
    m = match_rule("컴프레서 전기료 3월분", [rule])
    assert m is not None and m["rule_id"] == "TEST-AND-2"
    # 기기명만 있고 연료 신호 없으면 매치 안 됨(임대료·구매 등 무관 맥락 방지)
    assert match_rule("컴프레서 임대료", [rule]) is None
