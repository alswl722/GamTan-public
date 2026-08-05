"""baseline — 기존 8개 테이블(companies, vouchers, classifications,
emission_factors, unit_prices, trace_logs, llm_cache, industry_distributions)의
이력을 등록한다.

- 기존 Supabase DB(이미 db/init_db.py 의 create_all() 로 8개 테이블이 존재)에는
  `alembic stamp 0001` 로 적용한다 — DDL 미실행, 이력만 기록.
- 완전히 빈 DB(신규 로컬/테스트 환경)에서 `alembic upgrade head` 를 실행하는 경우를
  대비해, upgrade() 는 해당 8개 테이블이 없을 때만 생성한다.

주의: db/models.py 의 Voucher/Classification 클래스는 이미 v1 컬럼(financial_institution_id,
classification_method 등)을 포함하므로, 여기서 Base.metadata 를 그대로 create_all 하면
0005 가 추가하려는 컬럼과 중복 충돌한다. 그래서 이 baseline 은 v1 이전 시점의 컬럼만
별도 Table 객체로 명시적으로 정의해 생성한다 — models.py 변경과 무관하게 항상 안전하다.

Revision ID: 0001
Revises:
Create Date: 2026-08-05 16:07:50.287234

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """v1 이전 시점의 8개 테이블만 명시적으로 정의해 생성한다 (checkfirst — 이미 있으면 skip).
    실제 Supabase 배포는 stamp 로 적용되므로 이 경로를 타지 않는다."""
    bind = op.get_bind()
    metadata = sa.MetaData()

    sa.Table(
        "companies", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("industry_code", sa.String(20), nullable=False),
        sa.Column("industry_name", sa.String(100)),
        sa.Column("employee_count", sa.Integer),
        sa.Column("revenue_krw", sa.Numeric(20, 0)),
        sa.Column("region", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    sa.Table(
        "vouchers", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True)),
        sa.Column("year", sa.SmallInteger, nullable=False),
        sa.Column("month", sa.SmallInteger, nullable=False),
        sa.Column("supplier_name", sa.String(100)),
        sa.Column("item_description", sa.Text),
        sa.Column("supply_amount_krw", sa.Numeric(15, 0)),
        sa.Column("raw_json", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Index("ix_vouchers_company_year_month", "company_id", "year", "month"),
    )
    sa.Table(
        "classifications", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("voucher_id", sa.Integer, sa.ForeignKey("vouchers.id"), nullable=False, unique=True),
        sa.Column("scope", sa.SmallInteger),
        sa.Column("category", sa.String(50)),
        sa.Column("fuel_type", sa.String(50)),
        sa.Column("amount_krw", sa.Numeric(15, 0)),
        sa.Column("activity_amount", sa.Float),
        sa.Column("activity_unit", sa.String(20)),
        sa.Column("emission_co2e", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column("evidence", sa.Text),
        sa.Column("method", sa.String(10)),
        sa.Column("mixed_item", sa.Integer),
        sa.Column("status", sa.String(20)),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    sa.Table(
        "emission_factors", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fuel_type", sa.String(50), nullable=False),
        sa.Column("scope", sa.SmallInteger, nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("factor_co2", sa.Float, nullable=False),
        sa.Column("factor_ch4", sa.Float),
        sa.Column("factor_n2o", sa.Float),
        sa.Column("gwp_co2e", sa.Float),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Column("valid_from", sa.SmallInteger),
        sa.Column("valid_to", sa.SmallInteger),
    )
    sa.Table(
        "unit_prices", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fuel_type", sa.String(50), nullable=False),
        sa.Column("year", sa.SmallInteger, nullable=False),
        sa.Column("month", sa.SmallInteger, nullable=False),
        sa.Column("unit_price_krw", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Index("ix_unit_prices_fuel_year_month", "fuel_type", "year", "month"),
    )
    sa.Table(
        "trace_logs", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("step_type", sa.String(20), nullable=False),
        sa.Column("tool_name", sa.String(50)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("detail_json", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Index("ix_trace_session", "session_id"),
    )
    sa.Table(
        "llm_cache", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("text_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("item_description", sa.Text),
        sa.Column("llm_response", sa.JSON, nullable=False),
        sa.Column("hit_count", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    sa.Table(
        "industry_distributions", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("industry_code", sa.String(20), nullable=False),
        sa.Column("industry_name", sa.String(100)),
        sa.Column("scope", sa.SmallInteger, nullable=False),
        sa.Column("emission_min_co2e", sa.Float),
        sa.Column("emission_median_co2e", sa.Float),
        sa.Column("emission_median_per_employee", sa.Float),
        sa.Column("emission_max_co2e", sa.Float),
        sa.Column("revenue_basis_krw", sa.Numeric(20, 0)),
        sa.Column("year", sa.SmallInteger, nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Index("ix_industry_dist_code_year", "industry_code", "year"),
    )

    metadata.create_all(bind=bind, checkfirst=True)

    # metadata.create_all(checkfirst=True)는 테이블 단위로만 존재를 확인하므로,
    # unit_prices 테이블은 이미 있지만 ix_unit_prices_fuel_year_month 인덱스가 없는
    # 실제 Supabase 상태(v1 작업 착수 시점에 발견된 기존 드리프트)에서는 인덱스가
    # 생성되지 않는다. 인덱스만 별도로 checkfirst 생성해 drift를 해소한다.
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("unit_prices")}
    if "ix_unit_prices_fuel_year_month" not in existing_indexes:
        op.create_index(
            "ix_unit_prices_fuel_year_month", "unit_prices",
            ["fuel_type", "year", "month"],
        )


def downgrade() -> None:
    """baseline 테이블은 v1 이전부터 존재하던 운영 데이터이므로 downgrade 로 삭제하지 않는다."""
    pass
