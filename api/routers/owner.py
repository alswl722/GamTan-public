"""사장님 전용 API — /owner 4장면이 쓰는 자기 기업 데이터 조회.

- GET /owner/alerts/{company_id}   자기 기업의 이상 신호 알림

GET /admin/alerts(은행 담당자용 포트폴리오 전체)와 같은 판정 로직
(db/alerts.py::detect_alerts)을 재사용하되 자기 기업으로만 필터한다 —
은행이 먼저 알고 사장은 모르는 구도를 만들지 않기 위함(CLAUDE.md §9,
"하지 말 것" — 알림은 항상 사장에게 먼저).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.db import get_session
from db.alerts import detect_alerts

router = APIRouter(prefix="/owner", tags=["owner"])


@router.get("/alerts/{company_id}")
def owner_alerts(company_id: int, session: Session = Depends(get_session)):
    """자기 기업의 이상 신호 알림만 — 여신 결정과 무관, 안내 문구일 뿐(CLAUDE.md §9)."""
    return {"alerts": detect_alerts(session, company_id=company_id)}
