"""PCAF API — 장면④ Before/After + 벤치마킹의 데이터 소스.

저장된 분류 결과를 집계해 PCAF 데이터 품질 등급을 반환한다 (읽기 전용).
분류(도구②)가 아직 안 돌았으면 after=None 으로 내려보내 프론트가 안내한다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.agent.tools import calculate_pcaf
from api.db import get_session

router = APIRouter(prefix="/pcaf", tags=["pcaf"])


@router.get("/{company_id}")
def pcaf(company_id: int, year: int | None = None, session: Session = Depends(get_session)):
    """기업의 PCAF Before/After 등급·배출량·동종 벤치마킹.

    year는 after.monthly(월별 추이 차트)에만 적용된다 — 생략하면 이 구 엔진의
    기존 동작(전체 연도 합산)을 그대로 유지한다(db/pcaf.py::_after_measured 참고).
    """
    try:
        return calculate_pcaf(session, company_id, year=year)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
