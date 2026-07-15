"""공용 DB 조회 헬퍼 — Mock API·에이전트 도구·trace 라우터가 공통 재사용.

여기 모아두면 "전표/분포를 DB에서 꺼내는" 로직이 한 곳에만 존재한다.
"""
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from db.models import Classification, Voucher, IndustryDistribution, EmissionFactor, UnitPrice


# 커버리지 매트릭스용 — 품목 텍스트를 연료 대분류로 러프하게 묶는다.
# (정밀 분류는 도구②(LLM)가 하고, 여기선 결손 감지용 대분류만.)
def _fuel_class(item: str) -> str:
    t = item or ""
    if "전기" in t:
        return "전기"
    if "가스" in t or "LNG" in t:
        return "가스"
    if any(k in t for k in ("경유", "유류", "난방유", "휘발유", "지게차")):
        return "경유/유류"
    return "기타"


def _voucher_dict(v: Voucher) -> dict:
    return {
        "voucher_id": v.id,
        "source": v.source,
        "year": v.year,
        "month": v.month,
        "issue_date": v.issue_date.isoformat() if v.issue_date else None,
        "supplier_name": v.supplier_name,
        "item_description": v.item_description,
        "supply_amount_krw": int(v.supply_amount_krw) if v.supply_amount_krw is not None else None,
    }


def get_vouchers(session: Session, company_id: int, source: str | None = None) -> list[dict]:
    stmt = select(Voucher).where(Voucher.company_id == company_id)
    if source:
        stmt = stmt.where(Voucher.source == source)
    stmt = stmt.order_by(Voucher.month, Voucher.issue_date)
    rows = session.execute(stmt).scalars().all()
    return [_voucher_dict(v) for v in rows]


def get_coverage(session: Session, company_id: int) -> dict:
    """월(1~12) × 연료 대분류 존재 여부 매트릭스 + 결손 목록.

    에이전트가 "3~5월 가스가 0건이네?"를 스스로 관찰하는 재료.
    """
    vouchers = get_vouchers(session, company_id)
    fuels = ["전기", "가스", "경유/유류"]
    matrix = {f: {m: 0 for m in range(1, 13)} for f in fuels}
    for v in vouchers:
        fc = _fuel_class(v["item_description"])
        if fc in matrix:
            matrix[fc][v["month"]] += 1

    gaps = []
    for f in fuels:
        missing = [m for m in range(1, 13) if matrix[f][m] == 0]
        if missing:
            gaps.append({"fuel": f, "missing_months": missing})
    return {"matrix": matrix, "gaps": gaps}


def get_emission_factors(session: Session) -> list[EmissionFactor]:
    """배출계수 전량 — 계산 엔진 index_emission_factors 입력 (테이블 작음)."""
    return session.execute(select(EmissionFactor)).scalars().all()


def get_unit_prices(session: Session) -> list[UnitPrice]:
    """환산단가 전량(연료×12개월) — 계산 엔진 index_unit_prices 입력."""
    return session.execute(select(UnitPrice)).scalars().all()


def get_classifications(session: Session, company_id: int) -> list[dict]:
    """장면③(AI 분류+근거)용 — Scope 1/2 확정 건 + HITL 대기 건만 반환.

    정렬: 사람 검토가 필요한 HITL 건을 최상단에 먼저 보여주고, 그 다음은 월·발행일순.
    (제외/참고분류는 감사·집계 목적으로 DB엔 남아있지만 이 화면에는 안 보여줌)
    """
    hitl_first = case((Classification.status == "review_required", 0), else_=1)
    stmt = (
        select(Classification, Voucher)
        .join(Voucher, Classification.voucher_id == Voucher.id)
        .where(Voucher.company_id == company_id)
        .where((Classification.scope.in_((1, 2))) | (Classification.status == "review_required"))
        .order_by(hitl_first, Voucher.month, Voucher.issue_date)
    )
    rows = session.execute(stmt).all()
    return [
        {
            "voucher_id": v.id,
            "raw": v.item_description,
            "scope": c.scope,
            "category": c.category,
            "fuel": c.fuel_type,
            "amount_krw": int(c.amount_krw) if c.amount_krw is not None else None,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "method": c.method,
            "hitl": c.status == "review_required",
        }
        for c, v in rows
    ]


def get_distribution(session: Session, industry_code: str, scope: int) -> dict | None:
    stmt = select(IndustryDistribution).where(
        IndustryDistribution.industry_code == industry_code,
        IndustryDistribution.scope == scope,
    )
    d = session.execute(stmt).scalars().first()
    if not d:
        return None
    return {
        "industry_code": d.industry_code,
        "industry_name": d.industry_name,
        "scope": d.scope,
        "min": d.emission_min_co2e,
        "median": d.emission_median_co2e,
        "max": d.emission_max_co2e,
        "median_per_employee": d.emission_median_per_employee,
        "year": d.year,
        "source": d.source,
    }
