"""에이전트 API — 오케스트레이터 실행 트리거 (장면② 킬러씬 A).

POST = 에이전트 루프 1회 실행(도구 자율 호출 + trace_logs 기록).
결과 트레이스 조회는 기존 GET /trace/latest?company_id=... 재사용.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.agent.orchestrator import run_agent
from api.agent.run_lock import company_run_lock
from api.db import get_session

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run/{company_id}")
def run(company_id: int, session: Session = Depends(get_session)):
    """오케스트레이터 실행 → {session_id, mode(llm|judge_failed), step_count}.

    같은 company 동시 실행은 409 — 더블클릭이 unique 충돌 500으로 터지지 않게.
    """
    with company_run_lock(company_id):
        try:
            return run_agent(session, company_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
