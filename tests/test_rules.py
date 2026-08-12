"""룰 엔진(api/agent/rules.py) 검증 — 정답지는 db/excel_loader.load_expected_results()."""
from api.agent.rules import match_rule
from db.excel_loader import load_classification_rules, load_expected_results

RULES = load_classification_rules()
EXPECTED = load_expected_results()


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
