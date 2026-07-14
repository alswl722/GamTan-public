"""에이전트 API — 오케스트레이터 실행 트리거 (장면② 킬러씬 A).

POST = 에이전트 루프 1회 실행(도구 자율 호출 + trace_logs 기록).
결과 트레이스 조회는 기존 GET /trace/latest?company_id=... 재사용.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.agent.orchestrator import run_agent
from api.db import get_session

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run/{company_id}")
def run(company_id: int, session: Session = Depends(get_session)):
    """오케스트레이터 실행 → {session_id, mode(llm|fallback), step_count}."""
    return run_agent(session, company_id)
