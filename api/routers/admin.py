"""관리자 API — 은행 ESG·여신 담당자용 대시보드 데이터 소스.

- GET  /admin/portfolio                       포트폴리오 금융배출량 집계 + PCAF 등급 분포
- GET  /admin/hitl                            전 기업 HITL 검토 큐 (저신뢰 분류 건)
- PATCH /admin/classifications/{id}/confirm   담당자가 검토 후 확정 (보조수단성 원칙)

여신 결정·스코어링은 하지 않는다(CLAUDE.md §9). AI가 1차 스크리닝한 저신뢰 건을
사람이 최종 확정하는 HITL 마감만 담당 — 금융분야 AI 가이드라인의 보조수단성 구현.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db import get_session
from api.queries import get_hitl_queue
from db.models import Classification
from db.pcaf import portfolio_summary

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)):
    """거래 기업 전체의 Scope 1/2 합산 + PCAF 등급 분포 + 기업별 내역."""
    return portfolio_summary(session)


@router.get("/hitl")
def hitl_queue(session: Session = Depends(get_session)):
    """전 기업의 사람 검토 대기 건(status='review_required')."""
    return {"queue": get_hitl_queue(session)}


@router.patch("/classifications/{voucher_id}/confirm")
def confirm_classification(voucher_id: int, session: Session = Depends(get_session)):
    """담당자가 저신뢰 분류를 검토 후 확정 — status: review_required → confirmed.

    분류 내용(scope/category)은 그대로 두고 '사람이 확인했다'만 기록한다.
    AI가 값을 바꾸는 게 아니라 사람이 판정을 마감하는 것(보조수단성).
    """
    obj = session.query(Classification).filter_by(voucher_id=voucher_id).one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"voucher_id={voucher_id} 분류 없음")
    if obj.status != "review_required":
        raise HTTPException(
            status_code=409,
            detail=f"확정 불가 — 현재 상태 '{obj.status}' (검토필요 건만 확정 가능)",
        )
    obj.status = "confirmed"
    session.commit()
    return {"voucher_id": voucher_id, "status": obj.status}
