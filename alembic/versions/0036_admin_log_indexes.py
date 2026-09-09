"""admin_log_indexes

관리자 대시보드 로그성 조회 3종(trace_logs, classifications.reviewed_at,
source_document_access_logs)에 인덱스를 보강한다.

세 테이블 다 append-only로 계속 쌓이는 구조인데, 이걸 조회하는 엔드포인트
(/admin/traces, /admin/review-log, /admin/documents/access-log)가 매번
최신순 정렬 + 기간/기업 필터를 거는데도 정작 그 필터·정렬 컬럼에 인덱스가
없었다. review-log·access-log는 이미 서버사이드 페이지네이션이 있었지만
인덱스가 빠져 있었고, traces는 페이지네이션 자체가 없어 이번에 같이 도입한다
(별도 revision 아님 — 라우터 변경, DB 스키마 변경 아님).

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0036'
down_revision: Union[str, Sequence[str], None] = '0035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_trace_company_created", "trace_logs", ["company_id", "created_at"]
    )
    op.create_index(
        "ix_classification_reviewed_at", "classifications", ["reviewed_at"]
    )
    op.create_index(
        "ix_source_document_access_logs_accessed_at",
        "source_document_access_logs",
        ["accessed_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_source_document_access_logs_accessed_at",
        table_name="source_document_access_logs",
    )
    op.drop_index("ix_classification_reviewed_at", table_name="classifications")
    op.drop_index("ix_trace_company_created", table_name="trace_logs")
