"""document_upload_jobs

문서 업로드 백그라운드 처리 잡 테이블. POST /owner/{id}/documents/upload가 접수
즉시(파일 저장 + 이 레코드 생성) 202로 응답하고, 실제 OCR/추출은 BackgroundTasks로
넘어가 이 레코드를 done/failed로 갱신한다 — 사장님이 업로드 페이지에 계속 머물러
있지 않아도 되게 하기 위함(v1 2주차, 채팅 계획 참고, docs 미반영).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0027'
down_revision: Union[str, Sequence[str], None] = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_upload_jobs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('document_type_hint', sa.String(50)),
        sa.Column('mode', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='processing'),
        sa.Column('result_source_document_id', sa.Integer(), sa.ForeignKey('source_documents.id')),
        sa.Column('result_document_type', sa.String(50)),
        sa.Column('result_year', sa.SmallInteger()),
        sa.Column('result_month', sa.SmallInteger()),
        sa.Column('vouchers_created', sa.Integer()),
        sa.Column('skipped_rows', sa.Integer()),
        sa.Column('guidance_message', sa.Text()),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('processing', 'done', 'failed')",
            name='ck_document_upload_jobs_status',
        ),
    )
    op.create_index(
        'ix_document_upload_jobs_company_status',
        'document_upload_jobs',
        ['company_id', 'status'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_upload_jobs_company_status', table_name='document_upload_jobs')
    op.drop_table('document_upload_jobs')
