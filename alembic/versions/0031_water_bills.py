"""water_bills

상수도 요금고지서 테이블 — 스키마만 준비하고 파싱 로직은 아직 만들지 않는다
(docs/small-business-green-supply-data-plan.md §7.2, develop-plan.md §2.5).

컬럼 3개(prev_reading / cur_reading / usage_m3)를 모두 두는 이유: 실제 고지서는 사용량이
아니라 계량기 누적 지침 2개로 표시되고 사용량은 따로 인쇄된다. 지침만 저장하면 계량기
교체·리셋 달에 cur - prev가 음수가 되고, 사용량만 저장하면 고지서 원문과 대조할 근거가
사라진다(CLAUDE.md 원칙5). 불일치가 나는 달은 값을 맞추지 말고 그대로 드러낸다.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0031'
down_revision: Union[str, Sequence[str], None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'water_bills',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('source_documents.id')),
        sa.Column('provider', sa.String(100)),
        sa.Column('customer_number', sa.String(50)),
        sa.Column('site_addr', sa.String(255)),
        sa.Column('period_start', sa.DateTime(timezone=True)),
        sa.Column('period_end', sa.DateTime(timezone=True)),
        sa.Column('prev_reading', sa.Float()),
        sa.Column('cur_reading', sa.Float()),
        sa.Column('usage_m3', sa.Float()),
        sa.Column('base_fee_krw', sa.Numeric(15, 0)),
        sa.Column('usage_fee_krw', sa.Numeric(15, 0)),
        sa.Column('sewage_fee_krw', sa.Numeric(15, 0)),
        sa.Column('water_utilization_fee_krw', sa.Numeric(15, 0)),
        sa.Column('billed_amount_krw', sa.Numeric(15, 0)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_water_bills_company', 'water_bills', ['company_id'])
    op.create_index('ix_water_bills_source_document', 'water_bills', ['source_document_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_water_bills_source_document', table_name='water_bills')
    op.drop_index('ix_water_bills_company', table_name='water_bills')
    op.drop_table('water_bills')
