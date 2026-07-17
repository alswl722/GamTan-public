"""시나리오 API — 데모 데이터 전환(장면② 드롭다운).

POST = 대상 company의 전표를 시나리오 세트로 리셋·재적재(분류·트레이스도 초기화).
이후 POST /agent/run 으로 에이전트를 돌리면 상황별로 다른 판단을 관찰할 수 있다.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.agent.run_lock import company_run_lock
from api.db import get_session
from db.scenarios import list_scenarios, load_scenario

router = APIRouter(prefix="/scenario", tags=["scenario"])


@router.get("")
def scenarios():
    """선택 가능한 시나리오 목록."""
    return {"scenarios": list_scenarios()}


@router.post("/{name}/{company_id}")
def load(name: str, company_id: int, session: Session = Depends(get_session)):
    """시나리오를 company에 로드(기존 전표·분류·트레이스 리셋).

    분류·에이전트와 같은 락을 공유 — 실행 중인 세션의 트레이스를
    시나리오 전환이 지워버리지 않도록 동시 요청은 409.
    """
    with company_run_lock(company_id):
        try:
            return load_scenario(session, company_id, name)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
