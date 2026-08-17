"""classification_anomaly_check

이상치 되묻기(docs/tasks.md) — 에이전트가 코드로 판별한 이상치(평월 대비 N배
급증)를 사장님에게 "맞나요?" 확인받는다. 사장님은 숫자를 입력하지 않는다 —
예/아니오/모르겠어요 + 짧은 사유만 받는다. "아니요"·"모르겠어요"는 담당자
우선순위 알림(HITL 큐 배지)으로 이어진다.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('classifications', sa.Column('anomaly_check_status', sa.String(20), nullable=True))
    op.add_column('classifications', sa.Column('anomaly_check_reason', sa.Text(), nullable=True))
    op.add_column('classifications', sa.Column('anomaly_ratio', sa.Float(), nullable=True))
    op.create_check_constraint(
        'ck_classifications_anomaly_check_status',
        'classifications',
        "anomaly_check_status IS NULL OR anomaly_check_status IN "
        "('pending', 'confirmed_normal', 'disputed', 'unknown')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_classifications_anomaly_check_status', 'classifications', type_='check')
    op.drop_column('classifications', 'anomaly_ratio')
    op.drop_column('classifications', 'anomaly_check_reason')
    op.drop_column('classifications', 'anomaly_check_status')
