"""pcaf_quality_rules

PCAF Standard Part A Third Edition, Table 10.1-2(Business loans and unlisted
equity 데이터 품질표, Annex p.192)의 원문 옵션 체계(1a/1b/2a/2b/3a/3b/3c)를
그대로 옮긴 신규 테이블. borrower_emission_inventories.candidate_quality_rule_id
에 FK 를 건다(기존 데모 데이터에 이 컬럼을 채운 행이 없으므로 즉시 제약 추가 가능).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-12 00:00:00.000000

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
    """Upgrade schema."""
    op.create_table('pcaf_quality_rules',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('standard_version', sa.String(length=50), nullable=False),
    sa.Column('asset_class', sa.String(length=50), nullable=False),
    sa.Column('option_code', sa.String(length=10), nullable=False),
    sa.Column('quality_score', sa.SmallInteger(), nullable=False),
    sa.Column('activity_data_basis', sa.String(length=30), nullable=False),
    sa.Column('applies_to_scope3', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_reference', sa.Text(), nullable=False),
    sa.Column('valid_from', sa.SmallInteger(), nullable=True),
    sa.Column('valid_to', sa.SmallInteger(), nullable=True),
    sa.CheckConstraint(
        "activity_data_basis IN ('verified_emissions', 'unverified_emissions', "
        "'energy_consumption', 'production', 'revenue', 'assets', 'asset_turnover_ratio')",
        name='ck_pcaf_quality_rules_activity_data_basis'),
    sa.CheckConstraint("quality_score BETWEEN 1 AND 5", name='ck_pcaf_quality_rules_quality_score'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('option_code')
    )
    op.create_index('ix_pcaf_quality_rules_asset_class', 'pcaf_quality_rules', ['asset_class'], unique=False)

    with op.batch_alter_table('borrower_emission_inventories', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_inventories_candidate_quality_rule_id',
            'pcaf_quality_rules', ['candidate_quality_rule_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('borrower_emission_inventories', schema=None) as batch_op:
        batch_op.drop_constraint('fk_inventories_candidate_quality_rule_id', type_='foreignkey')

    op.drop_index('ix_pcaf_quality_rules_asset_class', table_name='pcaf_quality_rules')
    op.drop_table('pcaf_quality_rules')
