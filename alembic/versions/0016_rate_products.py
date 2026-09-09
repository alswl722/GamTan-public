"""rate_products

우대금리 대상 안내 카드를 리포트에서 사장님 메인 화면(/owner)으로 옮기며, "이미 대상"
상태를 표현할 데이터가 없던 문제를 고친다 — 지금까지는 db/pcaf_quality.py::
quality_upgrade_candidate가 "4등급→2등급 개선 후보"만 만들고, 이미 최고 등급(2등급)인
기업은 카드 자체가 없었다.

rate_products: 실제 상품을 참고한 참조 테이블(PcafQualityRule과 동일 패턴 — 코드가 원
소스, db/init_db.py::seed_rate_products가 채운다). 첫 시드는 iM뱅크 실제 상품 "ESG
Grow-Up 특별대출"의 환경(E) 단독 우대금리 조건(중진공 ESG 심층진단 E분야 3등급 이상 →
0.30%p)을 참고한다 — 감탄의 PCAF 데이터 등급이 그 증빙을 대신할 수 있다는 서사.

rate_approval_requests.matched_product_name: 어떤 상품에 매칭돼 요청이 만들어졌는지
스냅샷(FK 아님 — current_grade/target_grade와 같은 원칙, 상품 조건이 나중에 바뀌어도
과거 요청 기록은 그대로 보존).

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'rate_products',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('provider_name', sa.String(100), nullable=False),
        sa.Column('min_data_quality_score', sa.SmallInteger(), nullable=False),
        sa.Column('rate_discount_pct', sa.Numeric(4, 2), nullable=False),
        sa.Column('eligibility_description', sa.Text(), nullable=False),
        sa.Column('source_reference', sa.Text(), nullable=False),
        sa.Column('disclaimer_note', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "min_data_quality_score BETWEEN 1 AND 5",
            name='ck_rate_products_min_data_quality_score',
        ),
    )
    op.add_column(
        'rate_approval_requests', sa.Column('matched_product_name', sa.String(200))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('rate_approval_requests', 'matched_product_name')
    op.drop_table('rate_products')
