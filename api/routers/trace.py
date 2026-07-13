"""트레이스 API — 장면② 트레이스 뷰의 데이터 소스.

에이전트 실행의 [계획]/[관찰]/[행동] 로그를 시간순으로 반환한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from db.models import TraceLog

router = APIRouter(prefix="/trace", tags=["trace"])


def _serialize(rows: list[TraceLog]) -> list[dict]:
    return [
        {
            "id": r.id,
            "step_type": r.step_type,       # 계획 | 관찰 | 행동
            "tool_name": r.tool_name,
            "message": r.message,
            "detail_json": r.detail_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# /latest 를 /{session_id} 보다 먼저 선언 — 라우트 매칭 우선순위 확보.
@router.get("/latest")
def latest(company_id: int = Query(...), session: Session = Depends(get_session)):
    """해당 기업의 가장 최근 실행(session_id)의 트레이스. 데모 실사용 경로."""
    last = (
        session.execute(
            select(TraceLog)
            .where(TraceLog.company_id == company_id)
            .order_by(TraceLog.created_at.desc(), TraceLog.id.desc())
        )
        .scalars()
        .first()
    )
    if not last:
        return {"session_id": None, "steps": []}
    rows = (
        session.execute(
            select(TraceLog)
            .where(TraceLog.session_id == last.session_id)
            .order_by(TraceLog.created_at, TraceLog.id)
        )
        .scalars()
        .all()
    )
    return {"session_id": last.session_id, "steps": _serialize(rows)}


@router.get("/{session_id}")
def by_session(session_id: str, session: Session = Depends(get_session)):
    """특정 실행(session_id)의 트레이스."""
    rows = (
        session.execute(
            select(TraceLog)
            .where(TraceLog.session_id == session_id)
            .order_by(TraceLog.created_at, TraceLog.id)
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="해당 session_id의 트레이스가 없습니다")
    return {"session_id": session_id, "steps": _serialize(rows)}
