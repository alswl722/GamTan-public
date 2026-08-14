"""classification_calc_failure_reason

Classification.evidence에는 AI/룰 최초 판단 근거 뒤에 계산 실패 사유
(db/calc_engine.py의 _review()/CalcDataGap)와 담당자 조치 기록이 " | "로
계속 이어붙여지고 있었다. HITL 검토 화면에서 "판단 근거"와 "계산 실패
사유"가 한 문장처럼 뭉쳐 보이는 문제가 있어, 계산 실패 사유를 별도 컬럼
으로 분리한다. (담당자 조치는 여전히 evidence 뒤에 이어붙는다 — 감사
로그(review-log, audit-package)에서는 이미 원본/조치 구분 렌더링이
되고 있어 그대로 둔다.)

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('classifications', sa.Column('calc_failure_reason', sa.Text()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('classifications', 'calc_failure_reason')
