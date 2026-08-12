"""upload_dedup_constraints

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """앱 레벨 SELECT-then-INSERT 중복 체크는 동시 업로드(더블클릭·재시도) 레이스를
    못 막는다 — DB 제약으로 최종 방어선을 둔다.

    source_documents: 같은 기업이 같은 파일(file_hash)을 두 번 적재 못하게.
    borrower_financials: version까지 포함해 같은 (기업,연도,버전) 중복 행만 막고,
    재산정으로 새 버전을 만드는 기존 설계(§8.5)는 그대로 허용한다.
    """
    op.create_unique_constraint(
        'uq_source_documents_company_file_hash',
        'source_documents',
        ['company_id', 'file_hash'],
    )
    op.create_unique_constraint(
        'uq_borrower_financials_company_year_version',
        'borrower_financials',
        ['company_id', 'financial_year', 'version'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_borrower_financials_company_year_version', 'borrower_financials', type_='unique')
    op.drop_constraint('uq_source_documents_company_file_hash', 'source_documents', type_='unique')
