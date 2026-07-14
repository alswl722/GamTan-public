"""에이전트 도구함 — 오케스트레이터가 골라 호출할 독립 함수들.

이번 슬라이스: 도구① 데이터 수집 · 도구④ 업종 벤치마킹.
시그니처를 여기서 고정하면, 다음 슬라이스의 오케스트레이터는 이 함수를 호출만 하면 된다.
(도구② 분류(Claude+캐시)·도구③ 계산·PCAF는 다음 슬라이스에서 이 파일에 추가.)
"""
from sqlalchemy.orm import Session

from api.queries import get_coverage, get_distribution, get_vouchers
from db.pcaf import company_pcaf_summary


def collect_vouchers(session: Session, company_id: int) -> dict:
    """도구① 데이터 수집 — 전표 목록 + 커버리지(결손 관찰 재료)를 함께 반환."""
    vouchers = get_vouchers(session, company_id)
    coverage = get_coverage(session, company_id)
    return {"count": len(vouchers), "vouchers": vouchers, "coverage": coverage}


def get_industry_distribution(session: Session, industry_code: str, scope: int) -> dict | None:
    """도구④ 업종 벤치마킹 — 동종 업종 배출량 분포(min/median/max)."""
    return get_distribution(session, industry_code, scope)


def calculate_pcaf(session: Session, company_id: int) -> dict:
    """도구③ 계산·PCAF — 저장된 분류 결과를 집계해 Before/After 등급·벤치마킹 반환.

    아이템별 결정론 계산(금액→물량→탄소량)은 도구②(classify_vouchers)가
    compute_emission 으로 이미 수행해 Classification 에 저장해 둔다. 이 도구는
    그 저장분을 읽어 PCAF 등급으로 집계만 한다 (읽기 전용).
    """
    return company_pcaf_summary(session, company_id)


# TODO(다음 슬라이스):
#   classify_vouchers(session, company_id) — 도구② 룰→캐시→Gemini, 저신뢰 HITL (개발자 A)
