"""backfill_default_institution — 데이터 전용 revision. 스키마 변경 없음.

데모는 단일 가상 금융기관 시나리오(CLAUDE.md 기준 시연 기업 '○○정밀' 1곳)이므로:
1. financial_institutions 에 데모 금융기관 1행 시드 (이미 있으면 재사용)
2. 기존 companies 전체를 institution_borrowers 로 1:1 백필 (consent_status=active — 데모는 이미 동의 완료 가정)
3. 기존 vouchers 전체에 financial_institution_id/institution_borrower_id 채움

전부 `WHERE ... IS NULL` / `NOT EXISTS` 로 멱등하게 작성 — Supabase pause 후 재시도해도 안전하다.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-05 16:15:36.031656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEMO_TENANT_KEY = "demo-im-bank"
DEMO_INSTITUTION_NAME = "감탄 데모 금융기관"


def upgrade() -> None:
    """데이터 백필만 수행. DDL 변경 없음."""
    conn = op.get_bind()

    # 1) 데모 금융기관 1행 시드 (멱등 — tenant_key 유니크 제약을 활용해 이미 있으면 skip)
    conn.execute(
        sa.text(
            """
            INSERT INTO financial_institutions (name, reporting_currency, tenant_key, created_at)
            SELECT :name, 'KRW', :tenant_key, now()
            WHERE NOT EXISTS (
                SELECT 1 FROM financial_institutions WHERE tenant_key = :tenant_key
            )
            """
        ),
        {"name": DEMO_INSTITUTION_NAME, "tenant_key": DEMO_TENANT_KEY},
    )
    institution_id = conn.execute(
        sa.text("SELECT id FROM financial_institutions WHERE tenant_key = :tenant_key"),
        {"tenant_key": DEMO_TENANT_KEY},
    ).scalar_one()

    # 2) 기존 companies 전체를 institution_borrowers 로 백필 (멱등 — 기관+external_customer_id 유니크 제약)
    conn.execute(
        sa.text(
            """
            INSERT INTO institution_borrowers
                (financial_institution_id, company_id, external_customer_id,
                 consent_status, consent_started_at, created_at)
            SELECT :institution_id, c.id, 'demo-company-' || c.id,
                   'active', now(), now()
            FROM companies c
            WHERE NOT EXISTS (
                SELECT 1 FROM institution_borrowers ib
                WHERE ib.financial_institution_id = :institution_id
                  AND ib.company_id = c.id
            )
            """
        ),
        {"institution_id": institution_id},
    )

    # 3) 기존 vouchers 전체에 financial_institution_id/institution_borrower_id 채움
    #    (financial_institution_id IS NULL 인 행만 대상 — 재실행 시 이미 채워진 행은 건드리지 않음)
    conn.execute(
        sa.text(
            """
            UPDATE vouchers v
            SET financial_institution_id = :institution_id,
                institution_borrower_id = ib.id
            FROM institution_borrowers ib
            WHERE ib.financial_institution_id = :institution_id
              AND ib.company_id = v.company_id
              AND v.financial_institution_id IS NULL
            """
        ),
        {"institution_id": institution_id},
    )


def downgrade() -> None:
    """백필한 값만 되돌린다. 스키마(컬럼)는 0005가 관리하므로 여기서는 건드리지 않는다."""
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE vouchers
            SET financial_institution_id = NULL,
                institution_borrower_id = NULL
            WHERE financial_institution_id = (
                SELECT id FROM financial_institutions WHERE tenant_key = :tenant_key
            )
            """
        ),
        {"tenant_key": DEMO_TENANT_KEY},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM institution_borrowers
            WHERE financial_institution_id = (
                SELECT id FROM financial_institutions WHERE tenant_key = :tenant_key
            )
            """
        ),
        {"tenant_key": DEMO_TENANT_KEY},
    )
    conn.execute(
        sa.text("DELETE FROM financial_institutions WHERE tenant_key = :tenant_key"),
        {"tenant_key": DEMO_TENANT_KEY},
    )
