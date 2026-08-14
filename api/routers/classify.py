"""분류 API — 장면③ "AI 분류 + 근거"의 데이터 소스.

POST = 도구② 분류 파이프라인 실행("AI 분류 실행" 버튼이 호출).
GET  = 저장된 분류 결과 조회(재실행 없이 새로고침).
GET .../progress = 진행 중인 분류의 완료/전체 건수 폴링(프론트 원형 프로그레스).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.agent import progress
from api.agent.run_lock import company_run_lock
from api.agent.tools import classify_vouchers
from api.db import get_session
from api.queries import get_classifications, get_hitl_pending_count

router = APIRouter(prefix="/classify", tags=["classify"])


@router.post("/{company_id}")
def run_classification(company_id: int, session: Session = Depends(get_session)):
    """미분류 전표를 룰→Gemini 파이프라인으로 분류(이미 분류된 건은 스킵).

    같은 company 동시 실행은 409 — 중복 insert(unique 충돌) 방지.
    """
    with company_run_lock(company_id):
        summary = classify_vouchers(
            session,
            company_id,
            on_progress=lambda done, total: progress.tick(company_id, done, total),
        )
    return {
        **summary,
        "results": get_classifications(session, company_id),
        "hitl_pending_count": get_hitl_pending_count(session, company_id),
    }


@router.get("/{company_id}")
def list_classifications(company_id: int, session: Session = Depends(get_session)):
    """저장된 분류 결과 조회 — 담당자 확정 건 + HITL 대기 건수(상세는 비공개)."""
    return {
        "results": get_classifications(session, company_id),
        "hitl_pending_count": get_hitl_pending_count(session, company_id),
    }


@router.get("/progress/{company_id}")
def classify_progress(company_id: int):
    """진행 중인 분류의 {done, total, finished}. 폴링용(2초 권장)."""
    return progress.get(company_id)
