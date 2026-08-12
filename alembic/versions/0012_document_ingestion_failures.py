"""document_ingestion_failures

업로드 반려·실패 이력 테이블 추가 (v1 Tier 2 "품질 이슈 로그",
owner-admin-flow-spec.md §7). api/document_ingestion.py가 던지는 예외를
관리자가 조회 가능하게 기록한다 — 이전에는 HTTP 응답으로만 실패가 전달되고
DB에는 아무 것도 안 남았다.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-12 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_ingestion_failures',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id')),
        sa.Column('document_type', sa.String(50)),
        sa.Column('original_filename', sa.String(255)),
        sa.Column('failure_reason', sa.String(30), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "failure_reason IN ('duplicate', 'missing_institution', 'excel_format', 'parse_error')",
            name='ck_document_ingestion_failures_reason',
        ),
    )
    op.create_index(
        'ix_document_ingestion_failures_company',
        'document_ingestion_failures',
        ['company_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_ingestion_failures_company', table_name='document_ingestion_failures')
    op.drop_table('document_ingestion_failures')
