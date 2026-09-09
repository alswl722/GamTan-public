"""source_document_month_and_voucher_fk

"데이터 업로드" 탭(문서종류 × 월 그리드, 파일 목록·삭제)을 만들려면 "이 달에 이
문서종류 파일이 있는가"를 직접 쿼리할 수 있어야 하는데, 지금 스키마로는 안 된다:

- source_documents에 연·월 컬럼이 없다(document_date/period_start/period_end는
  있지만 api/document_ingestion.py가 실제로는 채우지 않아 항상 null).
- vouchers에도 source_document_id FK가 없다 — raw_json에 문자열로만 박혀 있어
  인덱스 조회가 안 된다(Classification.source_document_id는 FK로 있지만 분류
  이후에나 채워짐).

이 리비전은 두 컬럼을 추가하고, 기존 데이터를 raw_json에서 백필한다.

vouchers.source_document_id 백필: raw_json->>'source_document_id'에서 채운다.
source_documents.year/month 백필: 그 문서에 연결된 voucher들의 연·월이 전부
같을 때만 채운다(OCR 업로드는 항상 단일 월이라 이 조건을 만족 — 엑셀 대량
업로드처럼 한 문서가 여러 달에 걸치면 null로 남는다. 알려진 제약이며 이번
스코프에서 감수한다 — 그런 문서는 그리드 특정 칸에는 안 나타나지만 데이터
자체는 그대로 있다).

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_documents', sa.Column('year', sa.SmallInteger()))
    op.add_column('source_documents', sa.Column('month', sa.SmallInteger()))
    op.create_index(
        'ix_source_documents_type_year_month',
        'source_documents',
        ['company_id', 'document_type', 'year', 'month'],
    )

    op.add_column(
        'vouchers',
        sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('source_documents.id')),
    )
    op.create_index('ix_vouchers_source_document', 'vouchers', ['source_document_id'])

    # 백필 1: vouchers.source_document_id ← raw_json->>'source_document_id'
    # (raw_json은 json 타입이라 jsonb 전용 존재연산자 `?`를 못 쓴다 — ->>는 json도 지원)
    op.execute("""
        UPDATE vouchers
        SET source_document_id = (raw_json->>'source_document_id')::integer
        WHERE raw_json->>'source_document_id' IS NOT NULL
          AND source_document_id IS NULL
    """)

    # 백필 2: source_documents.year/month ← 연결된 voucher들의 연·월(전부 같을 때만)
    op.execute("""
        UPDATE source_documents sd
        SET year = v.only_year, month = v.only_month
        FROM (
            SELECT source_document_id,
                   MIN(year) AS only_year, MAX(year) AS max_year,
                   MIN(month) AS only_month, MAX(month) AS max_month
            FROM vouchers
            WHERE source_document_id IS NOT NULL
            GROUP BY source_document_id
        ) v
        WHERE sd.id = v.source_document_id
          AND v.only_year = v.max_year
          AND v.only_month = v.max_month
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_vouchers_source_document', table_name='vouchers')
    op.drop_column('vouchers', 'source_document_id')

    op.drop_index('ix_source_documents_type_year_month', table_name='source_documents')
    op.drop_column('source_documents', 'month')
    op.drop_column('source_documents', 'year')
