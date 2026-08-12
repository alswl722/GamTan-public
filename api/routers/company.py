"""기업 API — 프론트가 시연 기업 ID를 하드코딩하지 않고 조회하는 진입점.

DB를 새로 시드하면 autoincrement ID가 달라진다 — 프론트의 COMPANY_ID 상수는
그 순간 전 장면을 죽인다. 시연 기업(첫 번째 company)을 API로 노출해 해결.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_session
from db.models import Company

router = APIRouter(prefix="/company", tags=["company"])
companies_router = APIRouter(prefix="/companies", tags=["company"])


@router.get("")
def demo_company(session: Session = Depends(get_session)):
    """시연 기업 1행 — {id, name, industry_code, industry_name, region}.

    회사 선택 화면 도입 전부터 있던 하위호환 경로 — "첫 번째 기업"만 돌려주므로
    신규 코드는 GET /companies(목록)로 사용자가 직접 고르게 한다.
    """
    company = session.execute(
        select(Company).order_by(Company.id).limit(1)
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="등록된 기업이 없습니다 — DB 시드 필요")
    return {
        "id": company.id,
        "name": company.name,
        "industry_code": company.industry_code,
        "industry_name": company.industry_name,
        "region": company.region,
    }


@companies_router.get("")
def list_companies(session: Session = Depends(get_session)):
    """기업 목록 — 사장님 앱 메인 화면의 기업 선택기가 쓴다.

    계정 개념이 아직 없어(로그인 미도입) 사용자가 직접 자기 기업을 골라야 한다 —
    이 응답이 그 선택지 전체다.
    """
    companies = session.execute(select(Company).order_by(Company.id)).scalars().all()
    return {
        "companies": [
            {
                "id": c.id,
                "name": c.name,
                "industry_name": c.industry_name,
                "region": c.region,
            }
            for c in companies
        ]
    }
