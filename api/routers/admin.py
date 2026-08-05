"""관리자 API — 은행 ESG·여신 담당자용 대시보드 데이터 소스.

- GET   /admin/portfolio                      포트폴리오 금융배출량 집계 + PCAF 등급 분포
- GET   /admin/hitl                           전 기업 담당자 검토 큐 (저신뢰 분류 건)
- PATCH /admin/classifications/{id}/confirm   그대로 확정
- PATCH /admin/classifications/{id}           분류 수정 후 확정 (담당자 교정)
- PATCH /admin/classifications/{id}/reject    반려 — 집계에서 제외
- GET   /admin/traces                         에이전트 실행 이력 목록 (드릴다운은 /trace/{sid})
- GET   /admin/alerts                         이상 신호 알림 (여신 리스크 조기 경보)

여신 결정·스코어링은 하지 않는다(CLAUDE.md §9). AI가 1차 스크리닝한 저신뢰 건을
사람이 최종 확정하는 HITL 마감만 담당 — 금융분야 AI 가이드라인의 보조수단성 구현.
모든 담당자 조치는 evidence 에 감사 로그로 남긴다(설명가능성 원칙).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.db import get_session
from api.queries import get_emission_factors, get_hitl_queue, get_unit_prices
from db.alerts import detect_alerts
from db.calc_engine import CalcDataGap, ClassifiedItemInput, compute_emission, \
    index_emission_factors, index_unit_prices
from db.models import Classification, Company, TraceLog, Voucher
from db.pcaf import portfolio_summary

router = APIRouter(prefix="/admin", tags=["admin"])


class ClassificationEdit(BaseModel):
    """담당자 교정 입력 — 분류 필드만. 금액·물량은 담당자가 못 바꾼다(전표가 원본)."""

    scope: int | None = None
    category: str | None = None
    fuel_type: str | None = None


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)):
    """거래 기업 전체의 Scope 1/2 합산 + PCAF 등급 분포 + 기업별 내역."""
    return portfolio_summary(session)


@router.get("/hitl")
def hitl_queue(session: Session = Depends(get_session)):
    """전 기업의 담당자 검토 대기 건(status='review_required')."""
    return {"queue": get_hitl_queue(session)}


@router.get("/alerts")
def alerts(session: Session = Depends(get_session)):
    """이상 신호 알림 — 전 기업 배출량 추세 급변·데이터 공백을 스캔(결정론적 계산).

    급등/급감 판정은 코드가 배수로 계산하고, 여신 결정은 하지 않는다(CLAUDE.md §9).
    담당자가 조짐을 먼저 인지하도록 안내하는 조기 경보일 뿐이다.
    """
    return {"alerts": detect_alerts(session)}


def _load_reviewable(session: Session, voucher_id: int) -> Classification:
    """검토 대기 상태의 분류를 가져온다 — 아니면 404/409."""
    obj = session.query(Classification).filter_by(voucher_id=voucher_id).one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"voucher_id={voucher_id} 분류 없음")
    if obj.status != "review_required":
        raise HTTPException(
            status_code=409,
            detail=f"처리 불가 — 현재 상태 '{obj.status}' (검토필요 건만 가능)",
        )
    return obj


def _append_evidence(obj: Classification, note: str) -> None:
    """판단 근거에 담당자 조치를 덧붙인다 — 원본 근거를 지우지 않는다(감사 추적)."""
    obj.evidence = f"{obj.evidence or ''} | {note}".lstrip(" |")


@router.patch("/classifications/{voucher_id}/confirm")
def confirm_classification(voucher_id: int, session: Session = Depends(get_session)):
    """수정 없이 확정 — status: review_required → confirmed.

    분류 내용(scope/category)은 그대로 두고 '사람이 확인했다'만 기록한다.
    AI가 값을 바꾸는 게 아니라 사람이 판정을 마감하는 것(보조수단성).
    """
    obj = _load_reviewable(session, voucher_id)
    obj.status = "confirmed"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(obj, "담당자 확정(수정 없음)")
    session.commit()
    return {"voucher_id": voucher_id, "status": obj.status}


@router.patch("/classifications/{voucher_id}")
def edit_classification(
    voucher_id: int,
    edit: ClassificationEdit,
    session: Session = Depends(get_session),
):
    """담당자가 분류를 교정한 뒤 확정 — AI 1차 판정을 사람이 덮어쓴다.

    바뀐 필드는 evidence 에 '무엇을 무엇으로' 남기고, 연료·scope 가 바뀌면
    배출량을 재계산한다. 계산은 기존 결정론적 엔진(compute_emission)만 사용 —
    LLM 산수 금지 원칙 유지.
    """
    obj = _load_reviewable(session, voucher_id)

    changes = []
    if edit.scope is not None and edit.scope != obj.scope:
        changes.append(f"Scope {obj.scope}→{edit.scope}")
        obj.scope = edit.scope
    if edit.category is not None and edit.category != obj.category:
        changes.append(f"카테고리 {obj.category}→{edit.category}")
        obj.category = edit.category
    if edit.fuel_type is not None and edit.fuel_type != obj.fuel_type:
        changes.append(f"연료 {obj.fuel_type}→{edit.fuel_type}")
        obj.fuel_type = edit.fuel_type

    recalculated = _recalculate(session, obj)

    obj.status = "confirmed"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(
        obj,
        f"담당자 수정: {', '.join(changes)}" if changes else "담당자 확정(수정 없음)",
    )
    session.commit()
    return {
        "voucher_id": voucher_id,
        "status": obj.status,
        "changes": changes,
        "recalculated": recalculated,
        "emission_co2e": obj.emission_co2e,
    }


def _recalculate(session: Session, obj: Classification) -> bool:
    """교정된 분류로 배출량 재계산. 계산 불가(단가 없음/연료 불명)면 0으로 두고 False."""
    voucher = session.get(Voucher, obj.voucher_id)
    if voucher is None or not obj.fuel_type:
        return False
    raw = voucher.raw_json or {}
    try:
        item = ClassifiedItemInput(
            fuel_type=obj.fuel_type,
            scope=obj.scope,
            amount_krw=float(obj.amount_krw or voucher.supply_amount_krw or 0),
            year=int(voucher.year),
            month=int(voucher.month),
            quantity=raw.get("quantity"),
            quantity_unit=raw.get("quantity_unit"),
        )
        result = compute_emission(
            item,
            index_unit_prices(get_unit_prices(session)),
            index_emission_factors(get_emission_factors(session)),
        )
    except (CalcDataGap, ValueError):
        # 담당자 교정 결과가 계산 불가여도 확정은 유지 — 숫자만 비운다(추정 금지)
        obj.activity_amount = None
        obj.activity_unit = None
        obj.emission_co2e = 0.0
        return False

    if result.get("skipped") or result.get("needs_review"):
        obj.activity_amount = None
        obj.activity_unit = None
        obj.emission_co2e = 0.0
        return False

    obj.activity_amount = result.get("activity_amount")
    obj.activity_unit = result.get("activity_unit")
    obj.emission_co2e = result.get("emission_co2e") or 0.0
    return True


@router.patch("/classifications/{voucher_id}/reject")
def reject_classification(voucher_id: int, session: Session = Depends(get_session)):
    """반려 — 분류를 신뢰할 수 없다는 판정. status='rejected' 로 집계에서 제외한다.

    값을 지우지 않고 상태만 바꾼다(원본 보존 = 감사 가능).
    """
    obj = _load_reviewable(session, voucher_id)
    obj.status = "rejected"
    obj.reviewed_at = datetime.now(timezone.utc)
    _append_evidence(obj, "담당자 반려 — 분류 신뢰 불가, 집계 제외")
    session.commit()
    return {"voucher_id": voucher_id, "status": obj.status}


# 실행 이력 메시지에서 결과 배지를 뽑는 규칙 — 트레이스 문구와 1:1로 맞춰둔다.
_BADGE_RULES = (
    ("결손 발견", "결손 발견"),
    ("이상치 의심", "이상치"),
    ("재검증 실패", "재검증 실패"),
)


@router.get("/traces")
def trace_runs(session: Session = Depends(get_session)):
    """에이전트 실행 이력 목록 — session_id 단위로 묶어 최신순.

    드릴다운(스텝 타임라인)은 기존 GET /trace/{session_id} 를 그대로 쓴다.
    """
    rows = session.execute(
        select(
            TraceLog.session_id,
            TraceLog.company_id,
            Company.name,
            func.min(TraceLog.created_at).label("ran_at"),
            func.count(TraceLog.id).label("step_count"),
        )
        .join(Company, Company.id == TraceLog.company_id)
        .group_by(TraceLog.session_id, TraceLog.company_id, Company.name)
        .order_by(func.min(TraceLog.created_at).desc())
    ).all()

    runs = []
    for sid, company_id, company_name, ran_at, step_count in rows:
        messages = session.execute(
            select(TraceLog.message).where(TraceLog.session_id == sid)
        ).scalars().all()
        blob = " ".join(m or "" for m in messages)

        badges = [label for needle, label in _BADGE_RULES if needle in blob]
        # 실행 중단은 오케스트레이터가 예외 시 남기는 문구 — 그 외는 완료로 본다
        failed = "실행 중단" in blob
        if not badges and not failed:
            badges = ["정상"]

        runs.append({
            "session_id": sid,
            "company_id": company_id,
            "company_name": company_name,
            "ran_at": ran_at.isoformat() if ran_at else None,
            "step_count": int(step_count),
            "status": "실패" if failed else "완료",
            "result_badges": badges,
        })
    return {"runs": runs}
