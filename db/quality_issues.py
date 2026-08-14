"""업로드 반려·실패 이력 기록 (v1 Tier 2, owner-admin-flow-spec.md §7).

api/document_ingestion.py::ingest_uploaded_document()가 던지는 예외는 이전에
HTTP 응답으로만 전달되고 DB에는 아무 것도 남지 않았다 — 재현·통계 목적으로
그 실패 자체를 기록한다. 성공한 업로드는 SourceDocument로 이미 남으므로
여기 안 남는다.

⚠️ 관리자 대시보드의 "품질 이슈 로그"(GET /admin/quality-issues, 조회용
list_ingestion_failures)는 실무적으로 불필요하다고 판단해 제거했다 — 업로드
실패 원인(엑셀 형식 오류 등)은 은행 담당자가 아니라 개발/운영 쪽에서 다룰
정보였다. DocumentIngestionFailure 테이블과 이 기록 함수는 그대로 유지한다.
"""
from sqlalchemy.orm import Session

from db.models import DocumentIngestionFailure


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
