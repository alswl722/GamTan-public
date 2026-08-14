"""classification_sent_to_owner

담당자의 "확정(저장)"과 "사장님 전송"을 분리한다. 지금까지는 담당자가
confirm/edit로 확정(status: confirmed)하는 즉시 사장님 화면(장면③)에 그 건이
바로 노출됐다 — 검토가 아직 안 끝난 기업 배치가 건별로 조금씩 흘러들어가는
문제가 있었다.

sent_to_owner_at을 추가해, 확정은 순수 저장으로만 남기고, 담당자가 그 기업의
확정 건을 모아 "전송" 액션(POST /admin/companies/{id}/send-classifications)을
눌러야 그 시점의 confirmed 건 전체에 sent_to_owner_at이 채워지며 그제서야
get_classifications()에 나타난다.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'classifications',
        sa.Column('sent_to_owner_at', sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('classifications', 'sent_to_owner_at')
