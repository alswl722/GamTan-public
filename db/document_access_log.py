"""원본문서 접근 감사 로그 (v1 §6 2주차).

관리자가 원본 증빙(SourceDocument)을 열람할 때마다 기록한다. 기존
GET /admin/review-log(db/models.py::Classification.evidence 누적)는 "분류를
확정/반려했다"는 조치 기록이지 "문서를 열어봤다"는 열람 기록이 아니다 —
열람은 조치가 아니라 접근이라 별도 테이블(SourceDocumentAccessLog)로 남긴다.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import SourceDocument, SourceDocumentAccessLog


def record_access(session: Session, source_document_id: int, accessed_by: str) -> SourceDocumentAccessLog:
    """열람 1건을 기록한다. 문서 존재 여부는 호출부(라우터)가 먼저 확인한다."""
    log = SourceDocumentAccessLog(source_document_id=source_document_id, accessed_by=accessed_by)
    session.add(log)
    session.commit()
    return log


def access_history(session: Session, source_document_id: int) -> list[SourceDocumentAccessLog]:
    stmt = (
        select(SourceDocumentAccessLog)
        .where(SourceDocumentAccessLog.source_document_id == source_document_id)
        .order_by(SourceDocumentAccessLog.accessed_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


def recent_access_log(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    company_name: str | None = None,
) -> dict:
    """관리자 대시보드 전체 열람 이력 — 최근 순, 문서·기업 정보 조인.

    company_name을 넘기면 기업명 부분일치(대소문자 무시)로 필터한다. total은
    필터 적용 후 전체 건수 — 프론트가 "N건 중 M~K" 페이지 표시에 쓴다.
    """
    from db.models import Company

    base = (
        select(SourceDocumentAccessLog, SourceDocument, Company)
        .join(SourceDocument, SourceDocumentAccessLog.source_document_id == SourceDocument.id)
        .join(Company, SourceDocument.company_id == Company.id)
    )
    if company_name:
        base = base.where(Company.name.ilike(f"%{company_name}%"))

    total = session.execute(
        select(func.count()).select_from(
            base.with_only_columns(SourceDocumentAccessLog.id).subquery()
        )
    ).scalar_one()

    stmt = (
        base.order_by(SourceDocumentAccessLog.accessed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.execute(stmt).all()
    return {
        "entries": [
            {
                "log_id": log.id,
                "source_document_id": doc.id,
                "company_name": company.name,
                "document_type": doc.document_type,
                "original_filename": doc.original_filename,
                "accessed_by": log.accessed_by,
                "accessed_at": log.accessed_at.isoformat() if log.accessed_at else None,
            }
            for log, doc, company in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
