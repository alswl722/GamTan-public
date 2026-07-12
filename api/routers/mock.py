"""Mock 마이데이터 API — 장면① "연동 동의"의 수집 대상.

실서비스에선 한전 OPM·홈택스 연동이지만, 데모는 동일 스키마로 DB 전표를 반환한다.
POST = "동의하고 수집한다" 시맨틱 (프론트 버튼이 호출).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.db import get_session
from api.queries import get_vouchers

router = APIRouter(prefix="/mock", tags=["mock"])


@router.post("/hometax/{company_id}")
def collect_hometax(company_id: int, session: Session = Depends(get_session)):
    """홈택스 세금계산서 수집."""
    vouchers = get_vouchers(session, company_id, source="hometax")
    return {"source": "hometax", "count": len(vouchers), "vouchers": vouchers}


@router.post("/kepco/{company_id}")
def collect_kepco(company_id: int, session: Session = Depends(get_session)):
    """한전 전기요금 고지서 수집."""
    vouchers = get_vouchers(session, company_id, source="kepco")
    return {"source": "kepco", "count": len(vouchers), "vouchers": vouchers}
