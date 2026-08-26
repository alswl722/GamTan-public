"""reduction_todo_rerank_cache

감축 실천 ToDo 순서 재배치(db/pcaf_engine/reduction_todo.py::_llm_rerank_todos)의
캐시 테이블. 홈 화면 카드(ReductionTodoCard)가 열릴 때마다 같은 입력 조합으로
Gemini를 다시 호출하고 있던 것을 막는다(2026-08-26 사용자 지적 — "홈화면 들어올
때마다 재계산 되잖아").

기존 llm_cache를 재사용하지 않는 이유: llm_cache는 "전표 텍스트 해시 → 분류
응답" 전용으로 text_hash가 유니크 키다. 순서 재배치는 입력이 텍스트 한 줄이
아니라 (기업, todos 후보 id 집합, 연료별 배출량 요약) 조합이라, 그대로 밀어
넣으면 text_hash·item_description 두 컬럼의 의미가 어긋난다(db/models.py::
ReductionTodoRerankCache 주석 참고).

cache_key는 company_id + 정렬된 todos id 목록 + fuel_summary를 해시한 값이다
— 새 전표가 들어와 배출량이 바뀌거나 설비 신호 구성이 바뀌면 키 자체가
달라져 자동으로 무효화된다. 별도 만료(TTL) 컬럼을 두지 않는다.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0034'
down_revision: Union[str, Sequence[str], None] = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'reduction_todo_rerank_cache',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('cache_key', sa.String(64), nullable=False, unique=True),
        sa.Column('ordered_ids', sa.JSON(), nullable=False),
        sa.Column('hit_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('last_used_at', sa.DateTime(timezone=True)),
    )
    op.create_index(
        'ix_reduction_todo_rerank_cache_company',
        'reduction_todo_rerank_cache',
        ['company_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_reduction_todo_rerank_cache_company', table_name='reduction_todo_rerank_cache')
    op.drop_table('reduction_todo_rerank_cache')
