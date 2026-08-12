"""company_fuel_types

companies.fuel_types_json 을 정식 마이그레이션으로 반영한다. 이 컬럼은 이미
운영 DB에 존재했으나(원인 불명 — git 이력·이전 revision 어디에도 기록 없음)
db/models.py 와 alembic 이력에 누락되어 있던 drift였다. 컬럼 자체는 유지하고
이번 revision으로 스키마 이력에 정식 편입한다(§3 원칙8 — 기업이 직접 체크한
연료 유형, 체크 안 한 연료는 결손 알림 대상에서 제외).

운영 DB에 이미 컬럼이 있는 상태에서 재실행해도 안전하도록 IF NOT EXISTS 로 작성한다.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS fuel_types_json JSON")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS fuel_types_json")
