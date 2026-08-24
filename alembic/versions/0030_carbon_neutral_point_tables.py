"""carbon_neutral_point_tables

소상공인 탄소중립포인트 트랙의 신청서 초안·가입 테이블
(docs/small-business-green-supply-data-plan.md §7.3, §7.4).

reduction_rate_pct는 퍼센트 단위이며(7.4 = 7.4%) 감탄의 자체 예상치다 — 공식 판정은
한국환경공단이 반기마다 별도 계산한다(CLAUDE.md §5 원칙10). 계산 불가는 0이 아니라
null이다(원칙7).

point_type 5종은 PR #112가 확인한 실제 신청서 서식의 인센티브 유형 그대로다
(상품권/현금/현금기부/그린카드포인트/기타). local_currency는 서식에 없는 비전 단계 값이라
제약에서 제외했다 — 도입되면 새 revision으로 넓힌다.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0030'
down_revision: Union[str, Sequence[str], None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'carbon_neutral_point_applications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('application_type', sa.String(20), nullable=False, server_default='business'),
        sa.Column('baseline_year', sa.Integer(), nullable=False),
        sa.Column('target_year', sa.Integer(), nullable=False),
        sa.Column('baseline_usage_json', sa.JSON()),
        sa.Column('target_usage_json', sa.JSON()),
        sa.Column('reduction_rate_pct', sa.Float()),
        sa.Column('eligible', sa.Boolean()),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('draft_document_url', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "application_type IN ('business', 'household')",
            name='ck_cnp_applications_application_type',
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected')",
            name='ck_cnp_applications_status',
        ),
    )
    op.create_index(
        'ix_cnp_applications_company',
        'carbon_neutral_point_applications',
        ['company_id'],
    )

    op.create_table(
        'carbon_neutral_point_enrollments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('enrolled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('enrolled_at', sa.DateTime(timezone=True)),
        sa.Column('point_type', sa.String(30)),
        sa.Column('source', sa.String(20), nullable=False, server_default='self_reported'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "point_type IS NULL OR point_type IN "
            "('gift_certificate', 'cash', 'cash_donation', 'green_card_point', 'other')",
            name='ck_cnp_enrollments_point_type',
        ),
        sa.CheckConstraint(
            "source IN ('self_reported', 'api_confirmed')",
            name='ck_cnp_enrollments_source',
        ),
    )
    op.create_index(
        'ix_cnp_enrollments_company',
        'carbon_neutral_point_enrollments',
        ['company_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_cnp_enrollments_company', table_name='carbon_neutral_point_enrollments')
    op.drop_table('carbon_neutral_point_enrollments')
    op.drop_index('ix_cnp_applications_company', table_name='carbon_neutral_point_applications')
    op.drop_table('carbon_neutral_point_applications')
