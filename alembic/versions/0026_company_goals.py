"""company_goals

사장님 목표 설정 — 5단계 위저드 완료 후 홈 화면 박스가 목표 카드로 바뀔 때 쓰는
스냅숏 테이블. goal_type 2종(emission_reduction|grade_upgrade), 기업당 활성 목표는
최대 1개(새 목표 생성 시 기존 활성 목표는 superseded로 전환, 원칙8과 같은 결).
진행률·체크리스트는 저장하지 않고 조회 시점마다 재계산한다(db/pcaf_engine/company_goals.py).

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0026'
down_revision: Union[str, Sequence[str], None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'company_goals',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('goal_type', sa.String(30), nullable=False),
        sa.Column('scope_group', sa.String(10)),
        sa.Column('baseline_reporting_year', sa.Integer(), nullable=False),
        sa.Column('baseline_value', sa.Float(), nullable=False),
        sa.Column('target_value', sa.Float(), nullable=False),
        sa.Column('target_reduction_pct', sa.Float()),
        sa.Column('target_product_name', sa.String(200)),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('achieved_at', sa.DateTime(timezone=True)),
        sa.Column('superseded_by_goal_id', sa.Integer(), sa.ForeignKey('company_goals.id')),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "goal_type IN ('emission_reduction', 'grade_upgrade')",
            name='ck_company_goals_goal_type',
        ),
        sa.CheckConstraint(
            "status IN ('active', 'achieved', 'cancelled', 'superseded')",
            name='ck_company_goals_status',
        ),
    )
    op.create_index(
        'ix_company_goals_company_status',
        'company_goals',
        ['company_id', 'status'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_company_goals_company_status', table_name='company_goals')
    op.drop_table('company_goals')
