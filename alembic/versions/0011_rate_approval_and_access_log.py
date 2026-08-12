"""rate_approval_and_access_log

관리자 플로우 2주차(docs/v1-plan.md §6): 우대금리·설비금융 승인요청 큐와
원본문서 접근 감사 로그를 신규 테이블로 추가한다.

- rate_approval_requests: 사장님이 만든 승인요청(기존 GET /admin/rate-candidates는
  읽기 전용 안내 목록일 뿐 요청 자체가 없었다). 승인/반려는 여신 결정이 아니라
  "안내 대상 확정" 수동 확인(CLAUDE.md §9).
- source_document_access_logs: 원본문서 열람 사실 자체의 기록. 기존 review-log는
  분류 확정/반려 조치 기록이라 열람 이벤트를 담지 못한다.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-12 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rate_approval_requests',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('request_type', sa.String(20), nullable=False, server_default='rate_upgrade'),
        sa.Column('current_grade', sa.SmallInteger()),
        sa.Column('target_grade', sa.SmallInteger()),
        sa.Column('missing_summary', sa.Text()),
        sa.Column('disclaimer_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('reviewed_by', sa.String(100)),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('review_note', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "request_type IN ('rate_upgrade', 'equipment_finance')",
            name='ck_rate_approval_requests_request_type',
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name='ck_rate_approval_requests_status',
        ),
    )
    op.create_index(
        'ix_rate_approval_requests_company', 'rate_approval_requests', ['company_id']
    )
    op.create_index(
        'ix_rate_approval_requests_status', 'rate_approval_requests', ['status']
    )

    op.create_table(
        'source_document_access_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('source_documents.id'), nullable=False),
        sa.Column('accessed_by', sa.String(100), nullable=False),
        sa.Column('accessed_at', sa.DateTime(timezone=True)),
    )
    op.create_index(
        'ix_source_document_access_logs_document',
        'source_document_access_logs',
        ['source_document_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_source_document_access_logs_document', table_name='source_document_access_logs')
    op.drop_table('source_document_access_logs')

    op.drop_index('ix_rate_approval_requests_status', table_name='rate_approval_requests')
    op.drop_index('ix_rate_approval_requests_company', table_name='rate_approval_requests')
    op.drop_table('rate_approval_requests')
