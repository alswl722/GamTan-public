"""source_document_contract_type

전기고지서의 계약종별을 구조화된 컬럼으로 저장한다 — 소상공인 탄소중립포인트 트랙
(docs/small-business-green-supply-data-plan.md §7.1)의 판별 근거. 여태 "산업용 을" 같은
문구는 Voucher.item_description 자유텍스트에만 있어서 코드가 읽을 수 없었다.

contract_type은 고지서 원문 그대로("산업용(을) 고압A"), contract_type_class는 4종
정규화값(industrial|commercial|residential|unknown)이다. 정규화값에만 CHECK를 건다 —
원문 표기는 지역·계약별로 다양해서(§15.2 실물 확인 진행 중) 어휘를 못 닫는다.

둘 다 nullable이다: 이 revision 이전 레코드엔 값이 없고, 전기고지서가 아닌 문서
(세금계산서·가스고지서·마이데이터 KYB)는 애초에 해당 없음이다. 그래서 백필하지 않는다 —
전기고지서를 읽었는데 매핑에 실패한 경우만 명시적으로 'unknown'이 들어가고, null은
"해당 없음 또는 아직 안 읽음"을 뜻한다(§6.1 HITL 재확인 대상을 해당 없는 문서와 구분).

주의: 이 판별값(business_scale_hint)은 저장하지 않는다. 조회 시점에 이 컬럼에서 매번
계산하는 순수 함수로 만들어야 사업장이 계약종별을 바꿔도 마이그레이션 없이 갱신된다
(§5·§6.1). Company에 business_type 같은 저장형 컬럼을 추가하지 말 것.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0029'
down_revision: Union[str, Sequence[str], None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_documents', sa.Column('contract_type', sa.String(50), nullable=True))
    op.add_column('source_documents', sa.Column('contract_type_class', sa.String(20), nullable=True))
    op.create_check_constraint(
        'ck_source_documents_contract_type_class',
        'source_documents',
        "contract_type_class IS NULL OR contract_type_class IN "
        "('industrial', 'commercial', 'residential', 'unknown')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_source_documents_contract_type_class', 'source_documents', type_='check')
    op.drop_column('source_documents', 'contract_type_class')
    op.drop_column('source_documents', 'contract_type')
