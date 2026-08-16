"""industry_distribution_worker_band

industry_distributions를 목업 4행(하드코딩 min/median/max)에서 한국에너지공단
에너지사용·온실가스배출량 통계-마이크로데이터(공공데이터포털) 기반 실데이터로
교체하면서(scripts/fetch_industry_distributions.py), 업종 안에서도 종사자 규모별로
배출량 편차가 커서(대기업 섞인 업종 전체 분포에 12명짜리 소부장 기업을 비교하면
왜곡됨) 규모 밴드를 별도 차원으로 저장할 필요가 생겼다 — 기획서 §4/§10에 이미
있던 "업종별 min/median/max 분포로 소기업 구간 보정" 계획의 실행.

worker_band: 소스 데이터의 종사자규모 밴드 문자열("5인 ~ 9인" 등)을 그대로 저장.
NULL은 전체 규모 통합(밴드 무관 풀링) — 좁은 밴드 표본이 부족할 때 조회 쪽
(api/queries.py::get_distribution)이 폴백으로 쓴다.
sample_size: 그 min/median/max 뒤에 몇 개 사업장이 있었는지 — 표본 투명성.

둘 다 nullable — 이 리비전 이전 레코드는 값이 없다(다만 같은 PR에서
seed_industry_distributions()가 재시딩되므로 실질적으로 구 목업 행은 남지 않음).

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('industry_distributions', sa.Column('worker_band', sa.String(30), nullable=True))
    op.add_column('industry_distributions', sa.Column('sample_size', sa.Integer(), nullable=True))
    op.create_index(
        'ix_industry_dist_code_scope_year_band',
        'industry_distributions',
        ['industry_code', 'scope', 'year', 'worker_band'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_industry_dist_code_scope_year_band', table_name='industry_distributions')
    op.drop_column('industry_distributions', 'sample_size')
    op.drop_column('industry_distributions', 'worker_band')
