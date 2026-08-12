"""inventory_quality_basis

borrower_emission_inventories.candidate_quality_basis_json 컬럼을 추가한다.

PR #25 리뷰(CONFIRMED)에서 지적된 문제: POST /evaluate 가 계산한 판정 근거
(assessment["basis"])는 그 응답에만 실리고 DB에는 저장되지 않아, 이후 GET
요청에서는 항상 빈 배열이 반환됐다 — CLAUDE.md "모든 판단에 evidence를
저장한다" 원칙 위반. 이 컬럼에 basis를 영구 저장해 복구 가능하게 한다.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "borrower_emission_inventories",
        sa.Column("candidate_quality_basis_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("borrower_emission_inventories", "candidate_quality_basis_json")
