"""K택소노미·설비투자 리드 — 기존 룰 매칭 결과에 얹는 참조 테이블 (v1 §6 2주차).

회계 data/*.xlsx의 k_taxonomy_mapping 시트가 이미 기존 룰(R051~R058, R031, R032,
분류_기준표_확장 시트)과 linked_rule_id로 연결돼 있다 — 새 키워드 매칭 로직을
만들지 않는다. 이 모듈은 그 매핑을 rule_id → K택소노미 필드 딕셔너리로만 변환한다.

category='감축투자 후보'류 룰이 매칭됐을 때만 의미가 있고, 배출량 계산과는 무관하다
(원문: "배출량 계산 대상 아니나 녹색여신 참고"). finance_lead_type이 채워져도 이건
"리드"일 뿐 여신 결정이 아니다(CLAUDE.md §9) — 최종 승인은 승인요청 큐를 거친다.
"""
from functools import lru_cache

from db.excel_loader import load_k_taxonomy_mapping


@lru_cache(maxsize=1)
def _mapping_by_rule_id() -> dict[str, dict]:
    """rule_id → K택소노미 필드. 모듈 프로세스 생애 동안 1회만 Excel을 읽는다
    (load_classification_rules와 같은 캐시 없음 관례를 따르되, 이 매핑은 분류
    파이프라인에서 전표마다 호출되므로 캐시가 필요하다)."""
    rows = load_k_taxonomy_mapping()
    return {r["linked_rule_id"]: r for r in rows}


def k_taxonomy_fields_for_rule(rule_id: str | None) -> dict:
    """rule_id에 대응하는 K택소노미 필드를 반환. 매핑이 없으면 전부 None/False
    (해당 전표가 K택소노미·설비투자 대상이 아니라는 뜻 — 절대다수의 전표가 여기 해당).
    """
    if not rule_id:
        return _empty_fields()
    entry = _mapping_by_rule_id().get(rule_id)
    if entry is None:
        return _empty_fields()
    return {
        "k_taxonomy_candidate_type": entry["candidate_type"],
        "k_taxonomy_facility_type": entry["facility_type"],
        "finance_lead_type": entry["finance_lead_type"],
        "k_taxonomy_hitl_required": entry["hitl_required"],
    }


def _empty_fields() -> dict:
    return {
        "k_taxonomy_candidate_type": None,
        "k_taxonomy_facility_type": None,
        "finance_lead_type": None,
        "k_taxonomy_hitl_required": False,
    }
