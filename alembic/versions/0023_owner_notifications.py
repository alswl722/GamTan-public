"""owner_notifications

담당자가 확정 건을 사장님 화면에 "전송"(POST /admin/companies/{id}/
send-classifications)해도 사장님이 그걸 알 방법이 없었다 — 리포트 화면을
스스로 새로고침해야만 반영된 값을 보는 구조. docs/v1-plan.md §6-2 "확정
전송 → 사장님 알림"(docs/tasks.md가 상세 계획 정본)의 저장소.

별도 푸시 인프라 없이 DB 레코드 하나로 알림을 표현한다 — 사장님 화면이
폴링(10~15초, SceneTrace.tsx와 동일 패턴)으로 조회한다. Supabase Realtime은
CLAUDE.md상 허용된 경로지만 이 프로젝트에서 한 번도 쓰인 적 없는 새
인프라(@supabase/* 미설치)라 채택하지 않았다.

payload는 표시 문구를 다시 조립할 수 있는 원자료(예: sent_count)를 담는다 —
message 자체에도 이미 완성 문구가 들어가지만, 나중에 문구 포맷을 바꿔도
과거 알림을 다시 렌더링할 수 있게 원자료를 같이 남긴다.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'owner_notifications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('type', sa.String(30), nullable=False, server_default='classification_sent'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('read_at', sa.DateTime(timezone=True)),
    )
    op.create_index(
        'ix_owner_notifications_company_unread',
        'owner_notifications',
        ['company_id', 'read_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_owner_notifications_company_unread', table_name='owner_notifications')
    op.drop_table('owner_notifications')
