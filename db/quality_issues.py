"""품질 이슈 로그 — 업로드 반려·실패 이력 (v1 Tier 2, owner-admin-flow-spec.md §7).

api/document_ingestion.py::ingest_uploaded_document()가 던지는 예외는 이전에
HTTP 응답으로만 전달되고 DB에는 아무 것도 남지 않았다 — 관리자가 열람 전용으로
"왜, 얼마나 자주 업로드가 실패하는지" 확인할 방법이 없었다. 이 모듈은 그 실패
자체를 기록·조회한다. 성공한 업로드는 SourceDocument로 이미 남으므로 여기 안 남는다.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Company, DocumentIngestionFailure

_FAILURE_REASON_LABEL = {
    "duplicate": "중복 업로드",
    "missing_institution": "기관 귀속 미완료",
    "excel_format": "엑셀 형식 오류",
    "parse_error": "PDF 판독 실패",
}


def record_ingestion_failure(
    session: Session,
    company_id: int,
    *,
    document_type: str | None,
    original_filename: str | None,
    failure_reason: str,
    detail: str,
) -> DocumentIngestionFailure:
    """업로드 실패 1건을 기록한다. 호출부(라우터)의 except 블록에서 호출."""
    record = DocumentIngestionFailure(
        company_id=company_id,
        document_type=document_type,
        original_filename=original_filename,
        failure_reason=failure_reason,
        detail=detail,
    )
    session.add(record)
    session.commit()
    return record


def list_ingestion_failures(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    company_name: str | None = None,
) -> dict:
    """관리자 대시보드 "품질 이슈 로그"(열람 전용) — 최근 순, 기업명 조인.

    company_name을 넘기면 기업명 부분일치(대소문자 무시)로 필터한다. total은
    필터 적용 후 전체 건수 — 프론트가 "N건 중 M~K" 페이지 표시에 쓴다.
    """
    base = select(DocumentIngestionFailure, Company).join(
        Company, DocumentIngestionFailure.company_id == Company.id
    )
    if company_name:
        base = base.where(Company.name.ilike(f"%{company_name}%"))

    total = session.execute(
        select(func.count()).select_from(base.with_only_columns(DocumentIngestionFailure.id).subquery())
    ).scalar_one()

    stmt = (
        base.order_by(DocumentIngestionFailure.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.execute(stmt).all()
    return {
        "issues": [
            {
                "id": f.id,
                "company_id": f.company_id,
                "company_name": company.name,
                "document_type": f.document_type,
                "original_filename": f.original_filename,
                "failure_reason": f.failure_reason,
                "failure_reason_label": _FAILURE_REASON_LABEL.get(f.failure_reason, f.failure_reason),
                "detail": f.detail,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f, company in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
