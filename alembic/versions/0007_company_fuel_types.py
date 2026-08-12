"""company_fuel_types

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """사장님이 2단계(연료 유형 체크)에서 고른 값 저장 컬럼 — nullable, 기존 데이터 영향 없음."""
    op.add_column('companies', sa.Column('fuel_types_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'fuel_types_json')
