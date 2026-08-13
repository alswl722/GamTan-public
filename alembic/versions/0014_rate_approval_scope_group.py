"""rate_approval_scope_group

우대금리 등급 상승 후보 판정을 구엔진(db/pcaf.py, Scope1+2 통합 1~5등급)에서 정식
엔진(db/pcaf_quality.py, PCAF Table 10.1-2, Scope별 독립 품질점수)으로 재정렬하며,
한 기업이 Scope1·Scope2 각각 독립적으로 등급 상승 후보일 수 있게 됐다. 이제 요청이
어느 Scope에 대한 것인지 스냅샷에 남겨야 하므로 rate_approval_requests에 컬럼을
추가한다. equipment_finance 요청과 이 리비전 이전 과거 스냅샷은 계속 null로 남는다
(생성 시점 스냅샷 보존 원칙 — db/models.py::RateApprovalRequest 참고).

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rate_approval_requests', sa.Column('scope_group', sa.String(20)))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('rate_approval_requests', 'scope_group')
