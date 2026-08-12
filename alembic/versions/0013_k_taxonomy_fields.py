"""k_taxonomy_fields

classifications 테이블에 K택소노미·설비투자 리드 필드를 추가한다 (v1 §6 2주차,
docs/v1-plan.md §6 2주차 A 항목). 회계 data/*.xlsx의 k_taxonomy_mapping 시트가
이미 기존 룰(R051~R058, R031, R032, 분류_기준표_확장 시트)과 linked_rule_id로
연결돼 있어, 새 매칭 로직 없이 기존 룰 매칭 결과에 이 필드들을 얹기만 한다.

finance_lead_type이 채워져도 이건 "리드"일 뿐 여신 결정이 아니다(CLAUDE.md §9).

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-12 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('classifications', sa.Column('k_taxonomy_candidate_type', sa.String(50)))
    op.add_column('classifications', sa.Column('k_taxonomy_facility_type', sa.String(50)))
    op.add_column('classifications', sa.Column('finance_lead_type', sa.String(50)))
    op.add_column(
        'classifications',
        sa.Column('k_taxonomy_hitl_required', sa.Boolean(), server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('classifications', 'k_taxonomy_hitl_required')
    op.drop_column('classifications', 'finance_lead_type')
    op.drop_column('classifications', 'k_taxonomy_facility_type')
    op.drop_column('classifications', 'k_taxonomy_candidate_type')
