"""rate_product_requires_k_taxonomy

RateProduct에 requires_k_taxonomy_leads(Boolean, 기본 False)를 추가한다. "K-택소노미
그린 SME 대출"처럼 원 상품 자체가 K택소노미 적합 프로젝트 증빙을 요구하는 상품과,
ESG Grow-Up처럼 PCAF 등급만 보는 상품을 구분하기 위함 — db/rate_products.py의
매칭 로직이 이 플래그를 보고 db/k_taxonomy.py::k_taxonomy_leads_for_company() 결과를
추가로 확인한다.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "rate_products",
        sa.Column(
            "requires_k_taxonomy_leads",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("rate_products", "requires_k_taxonomy_leads")
