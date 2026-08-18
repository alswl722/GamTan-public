"""gov_support_programs

개인화된 정부 지원사업 매칭(docs/gov-support-matching-plan.md 정본) 저장소.
기업마당(bizinfo) API에서 배치로 수집한 지원사업 공고 캐시 — 기업별 매칭
결과는 저장하지 않고 매 조회 시 재계산한다(추천일 뿐 승인·확정 개념이
없어 원칙8 버전관리 대상이 아님).

embedding은 pgvector `Vector` 타입이 아니라 JSON(float 리스트)이다 — 이
프로젝트 테스트가 SQLite로 도는데 Vector 타입은 Postgres 전용이라 충돌해서,
공유 Postgres에 그대로 저장하되 코사인 유사도는 db/gov_support/matching.py가
Python으로 계산한다(문서 §5 정정, 2026-08-18).

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'gov_support_programs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source', sa.String(30), nullable=False, server_default='bizinfo'),
        sa.Column('external_id', sa.String(50), nullable=False),
        sa.Column('program_name', sa.String(200), nullable=False),
        sa.Column('category', sa.String(50)),
        sa.Column('agency_name', sa.String(100)),
        sa.Column('apply_start_date', sa.Date()),
        sa.Column('apply_end_date', sa.Date()),
        sa.Column('apply_period_raw', sa.String(100)),
        sa.Column('region_tags', sa.String(200)),
        sa.Column('detail_url', sa.String(500)),
        sa.Column('raw_text', sa.Text()),
        sa.Column('raw_text_hash', sa.String(64)),
        sa.Column('embedding', sa.JSON()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('fetched_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('source', 'external_id', name='uq_gov_support_source_external_id'),
    )
    op.create_index(
        'ix_gov_support_active_apply_end',
        'gov_support_programs',
        ['is_active', 'apply_end_date'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_gov_support_active_apply_end', table_name='gov_support_programs')
    op.drop_table('gov_support_programs')
