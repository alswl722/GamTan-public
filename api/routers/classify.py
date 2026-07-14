"""분류 API — 장면③ "AI 분류 + 근거"의 데이터 소스.

POST = 도구② 분류 파이프라인 실행("AI 분류 실행" 버튼이 호출).
GET  = 저장된 분류 결과 조회(재실행 없이 새로고침).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.agent.tools import classify_vouchers
from api.db import get_session
from api.queries import get_classifications

router = APIRouter(prefix="/classify", tags=["classify"])


@router.post("/{company_id}")
def run_classification(company_id: int, session: Session = Depends(get_session)):
    """미분류 전표를 룰→Gemini 파이프라인으로 분류(이미 분류된 건은 스킵)."""
    summary = classify_vouchers(session, company_id)
    return {**summary, "results": get_classifications(session, company_id)}


@router.get("/{company_id}")
def list_classifications(company_id: int, session: Session = Depends(get_session)):
    """저장된 분류 결과 조회 (Scope1/2 확정 건 + HITL 대기 건)."""
    return {"results": get_classifications(session, company_id)}
