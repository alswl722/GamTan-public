"""조직경계(OrganizationalBoundary) 자동 생성 — 사장님 화면용 간이화 경로.

`db/pcaf_quality.py`의 은행 담당자용 평가 API는 조직경계가 미리 등록돼 있다는
전제로 설계됐다(§7.3, 은행이 차주의 조직범위·재무 연결범위를 검토·승인하는
정식 절차). 사장님 앱에서는 그 등록 절차를 사용자가 거칠 방법이 없으므로,
이 모듈이 간이화 가정으로 대신 채운다.

⚠️ 회계 검수 필요: boundary_type='operational_control', consolidation_scope='separate'를
기본값으로 자동 생성한다 — 이 프로젝트의 대상(대구·경북 소부장 2·3차 벤더)이 대부분
자회사·연결대상 없는 단일법인 소기업이라는 전제. 실제로 연결대상이 있는 차주가
생기면 이 가정은 깨지므로, 은행 담당자가 나중에 직접 등록/수정하는 정식 절차로
교체돼야 한다(v1-plan §13 노트 참고).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.queries import resolve_institution_borrower
from db.models import OrganizationalBoundary

_AUTO_DESCRIPTION = "자동 생성 — 간이화 가정(단일법인, 자회사 없음). 회계 검수 필요."


def ensure_organizational_boundary(
    session: Session, company_id: int, reporting_year: int
) -> OrganizationalBoundary:
    """해당 기업·보고연도의 조직경계를 반환 — 없으면 간이화 가정으로 생성한다.

    기존 레코드(은행 담당자가 정식 등록했을 수도 있는 레코드 포함)가 있으면
    그대로 반환하고 재생성하지 않는다 — 정식 등록이 이 자동 생성을 항상 이긴다.
    """
    existing = session.execute(
        select(OrganizationalBoundary)
        .where(
            OrganizationalBoundary.company_id == company_id,
            OrganizationalBoundary.reporting_year == reporting_year,
        )
        .order_by(OrganizationalBoundary.id.desc())
    ).scalars().first()
    if existing is not None:
        return existing

    resolved = resolve_institution_borrower(session, company_id)
    if resolved is None:
        raise ValueError(
            f"company_id={company_id} 기관 귀속(institution_borrowers) 미완료 — "
            "조직경계 자동 생성 불가"
        )
    financial_institution_id, _institution_borrower_id = resolved

    boundary = OrganizationalBoundary(
        financial_institution_id=financial_institution_id,
        company_id=company_id,
        reporting_year=reporting_year,
        boundary_type="operational_control",
        consolidation_scope="separate",
        description=_AUTO_DESCRIPTION,
    )
    session.add(boundary)
    session.commit()
    session.refresh(boundary)
    return boundary
