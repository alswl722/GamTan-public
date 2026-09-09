"""source_document_extraction_method

OCR 파이프라인을 Gemini 비전에서 PaddleOCR(100% 로컬) 처리로 전환하면서
(db/document_extraction.py), 어느 문서가 텍스트 레이어로 바로 읽혔는지·HTML에서
읽혔는지·OCR을 거쳤는지, OCR을 거쳤다면 신뢰도가 얼마였는지를 감사할 방법이
없었다 — extracted_json에 값은 있어도 "어떤 경로로 읽혔는지" 자체를 별도로 조회할
수 없었다. source_documents에 두 컬럼을 추가해 db/document_extraction.py의 반환값
(extraction_method, extraction_confidence)을 그대로 영속화한다(CLAUDE.md 원칙5
"모든 판단에 evidence 저장"에 대응 — 설명가능성).

nullable로 둔다 — 이 리비전 이전에 업로드된 source_documents 레코드는 값이 없다.
extraction_confidence는 OCR 경로일 때만 채워진다(텍스트 레이어/HTML은 결정론적
정규식 파싱이라 "신뢰도" 개념 자체가 없음).

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_documents', sa.Column('extraction_method', sa.String(20), nullable=True))
    op.add_column('source_documents', sa.Column('extraction_confidence', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('source_documents', 'extraction_confidence')
    op.drop_column('source_documents', 'extraction_method')
