"""감사 대응 근거 패키지 — 기업·기간을 지정하면 trace_logs + classifications.evidence
+ 원본 전표를 시계열로 묶어 조회한다 (v1 Tier 2, owner-admin-flow-spec.md §8).

신규 계산 로직이나 신규 테이블은 없다 — 기존 3개 테이블(trace_logs, classifications,
vouchers)을 기업·기간 기준으로 조인·정렬만 한다. CSV 내보내기는 이 조회 결과를 그대로
직렬화한다(원자료 재검증용, PDF 서술형 감사보고서는 별도 범위).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Classification, TraceLog, Voucher


def build_audit_package(
    session: Session, company_id: int, year: int, month_from: int = 1, month_to: int = 12
) -> dict:
    """기업 1곳·연도·월 범위의 감사 근거를 시계열(entries)로 반환.

    entries는 두 소스를 합쳐 시각순 정렬한다:
    - vouchers + classifications(evidence 포함) — 전표별 판단 근거
    - trace_logs — 해당 기업의 에이전트 실행 이력(계획/관찰/행동)
    같은 기업의 서로 다른 성격의 기록을 억지로 한 스키마에 우겨넣지 않고,
    entry_type으로 구분해 그대로 노출한다(원자료 재검증이 목적이라 가공 최소화).
    """
    voucher_rows = session.execute(
        select(Voucher, Classification)
        .outerjoin(Classification, Classification.voucher_id == Voucher.id)
        .where(
            Voucher.company_id == company_id,
            Voucher.year == year,
            Voucher.month >= month_from,
            Voucher.month <= month_to,
        )
        .order_by(Voucher.year, Voucher.month, Voucher.id)
    ).all()

    voucher_entries = [
        {
            "entry_type": "voucher",
            "occurred_at": (v.issue_date or v.created_at).isoformat() if (v.issue_date or v.created_at) else None,
            "voucher_id": v.id,
            "year": v.year,
            "month": v.month,
            "item_description": v.item_description,
            "supply_amount_krw": float(v.supply_amount_krw) if v.supply_amount_krw is not None else None,
            "scope": c.scope if c else None,
            "fuel_type": c.fuel_type if c else None,
            "emission_co2e": c.emission_co2e if c else None,
            "status": c.status if c else None,
            "evidence": c.evidence if c else None,
        }
        for v, c in voucher_rows
    ]

    trace_rows = session.execute(
        select(TraceLog)
        .where(TraceLog.company_id == company_id)
        .order_by(TraceLog.created_at)
    ).scalars().all()

    trace_entries = [
        {
            "entry_type": "trace",
            "occurred_at": t.created_at.isoformat() if t.created_at else None,
            "session_id": t.session_id,
            "step_type": t.step_type,
            "tool_name": t.tool_name,
            "message": t.message,
        }
        for t in trace_rows
    ]

    entries = sorted(
        voucher_entries + trace_entries,
        key=lambda e: e["occurred_at"] or "",
    )

    return {
        "company_id": company_id,
        "year": year,
        "month_from": month_from,
        "month_to": month_to,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(entries),
        "entries": entries,
    }
