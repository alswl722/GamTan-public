"""company_goals_baseline_start_month

배출량 감축 목표(emission_reduction)의 기준값을 "달력년도"가 아니라 "목표 설정
시점(달)부터 롤링 12개월"로 계산하기 위한 컬럼. 기본값 1은 의도적 — 이미 있는
행(달력년도 기준으로 만들어짐)은 baseline_start_month=1이 되어 "1월~12월" 원래
계산과 정확히 같아진다(적용 후에도 동작 안 바뀜). grade_upgrade 목표는 이 개념이
없어 그냥 1로 채워지고 실질적으로 안 쓰인다.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0028'
down_revision: Union[str, Sequence[str], None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'company_goals',
        sa.Column('baseline_start_month', sa.SmallInteger(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('company_goals', 'baseline_start_month')
