"""Alembic 업그레이드·롤백·기존 데이터 보존 검증 (docs/borrower-pcaf-data-plan.md §14.7,
docs/v1-plan.md §3 1주차 완료조건: "기존 DB 데이터가 Alembic 마이그레이션 후 보존된다").

주의: revision 0005는 기존 테이블에 FK를 ALTER로 추가하므로 SQLite(batch mode 미지원)로는
검증할 수 없고 Postgres가 필요하다. 그렇다고 DATABASE_URL(공유 개발 DB)에 직접
upgrade/downgrade 사이클을 실행하면 안 된다 — Supabase pooler가 `?options=-csearch_path=...`
류의 세션 격리를 무시해 실제 운영 스키마에 DDL이 그대로 실행되는 사고가 있었다
(1주차 작업 중 발견, 데이터 유실은 없었으나 신규 테이블이 일시 삭제됨).

그래서 이 파일은 두 종류로 나눈다:
1. 파괴적이지 않은 읽기 전용 검증 — DATABASE_URL(공유 DB)에서 실행해도 안전, 항상 실행.
2. 완전한 upgrade/downgrade 사이클 검증 — TEST_DATABASE_URL(공유 DB와 별개인 전용
   테스트 DB) 이 명시적으로 설정된 경우에만 실행. 이 변수가 없으면 skip한다.
   TEST_DATABASE_URL 은 절대 DATABASE_URL과 같은 값으로 설정하지 말 것.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()  # conftest.py는 sys.path만 조정하므로 DATABASE_URL은 여기서 직접 로드

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

requires_database_url = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="실제 Postgres(DATABASE_URL)가 필요한 테스트",
)

_test_db_url = os.getenv("TEST_DATABASE_URL")
if _test_db_url and _test_db_url == os.getenv("DATABASE_URL"):
    # 공유 개발 DB에 파괴적 마이그레이션 사이클을 실행하는 사고를 방지하는 하드 가드.
    _test_db_url = None

requires_dedicated_test_db = pytest.mark.skipif(
    not _test_db_url,
    reason=(
        "TEST_DATABASE_URL(공유 DATABASE_URL과 별개인 전용 테스트 Postgres)이 "
        "설정된 경우에만 실행 — 파괴적 upgrade/downgrade 사이클 테스트"
    ),
)


def _alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "alembic"))
    # configparser는 %를 interpolation 문법으로 해석하므로 URL 인코딩된 값(%3D 등)이나
    # 비밀번호에 %가 섞인 경우 set_main_option을 거치면 깨진다 — attributes로 직접 전달.
    cfg.attributes["sqlalchemy.url"] = sqlalchemy_url
    return cfg


@requires_dedicated_test_db
def test_upgrade_from_empty_succeeds():
    """전용 테스트 Postgres(빈 DB)에서 alembic upgrade head 가 예외 없이 완료되고
    신규 11개 테이블이 생성된다."""
    cfg = _alembic_config(_test_db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(_test_db_url)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
    engine.dispose()
    expected_new_tables = {
        "financial_institutions", "institution_users", "institution_borrowers", "portfolios",
        "organizational_boundaries", "source_documents", "borrower_emission_inventories",
        "inventory_gas_emissions", "business_loan_exposures", "borrower_financials", "fx_rates",
    }
    assert expected_new_tables.issubset(tables)


@requires_dedicated_test_db
def test_downgrade_to_base_succeeds():
    """전용 테스트 Postgres에서 alembic downgrade base 까지 역순 실행 시
    신규 11개 테이블이 전부 제거된다."""
    cfg = _alembic_config(_test_db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(_test_db_url)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
    engine.dispose()
    removed_tables = {
        "financial_institutions", "institution_users", "institution_borrowers", "portfolios",
        "organizational_boundaries", "source_documents", "borrower_emission_inventories",
        "inventory_gas_emissions", "business_loan_exposures", "borrower_financials", "fx_rates",
    }
    assert removed_tables.isdisjoint(tables)


@requires_database_url
def test_current_head_matches_latest_revision():
    """공유 DATABASE_URL의 alembic_version이 최신 head(0009)와 일치하는지 확인한다.
    (읽기 전용 — 이 테스트는 DB를 변경하지 않는다)"""
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert current == "0009"


@requires_database_url
def test_models_match_database_no_drift():
    """db/models.py 와 실제 DB 스키마 사이에 drift가 없어야 한다 — 누군가 models.py만
    고치고 revision 생성을 깜빡하는 사고를 조기에 잡는다. (읽기 전용, alembic check와 동일 원리)"""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from db.models import Base

    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        migration_ctx = MigrationContext.configure(conn)
        diff = compare_metadata(migration_ctx, Base.metadata)
    engine.dispose()
    assert diff == [], f"models.py와 DB 사이에 미반영된 변경이 있습니다: {diff}"


@requires_database_url
def test_migration_preserves_existing_voucher_rows():
    """실제 Supabase DB에서 vouchers/classifications 행이 존재해야 한다
    (파괴적이지 않은 읽기 전용 스냅숏 비교 — 이 테스트는 DB를 변경하지 않는다)"""
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        voucher_count = conn.execute(text("SELECT COUNT(*) FROM vouchers")).scalar()
        classification_count = conn.execute(text("SELECT COUNT(*) FROM classifications")).scalar()
    assert voucher_count > 0, "기존 전표 데이터가 존재해야 함 (마이그레이션으로 유실되지 않았는지 확인 불가)"
    assert classification_count > 0


@requires_database_url
def test_backfill_assigns_default_institution_to_all_existing_vouchers():
    """0006 적용 후 기존 전표 전부가 NULL이 아닌 financial_institution_id 를 가진다.
    (읽기 전용 — 이 테스트는 DB를 변경하지 않는다)"""
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        null_count = conn.execute(
            text("SELECT COUNT(*) FROM vouchers WHERE financial_institution_id IS NULL")
        ).scalar()
    assert null_count == 0


@requires_dedicated_test_db
def test_legacy_table_drop_does_not_affect_new_portfolios_table():
    """drop_legacy_tables() 호출이 신규 portfolios 테이블 데이터에 영향을 주지 않는다
    ('portfolio_summaries'(레거시) vs 'portfolios'(신규) 네이밍 혼동 방지 안전망).
    전용 테스트 DB에서만 실행 — INSERT/DELETE를 수반하므로 공유 DB에서 실행하지 않는다."""
    from db.init_db import drop_legacy_tables

    cfg = _alembic_config(_test_db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(_test_db_url)
    marker_name = "legacy-drop-test-marker"

    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO financial_institutions (name, reporting_currency, tenant_key) "
                "VALUES (:name, 'KRW', :tenant_key)"
            ),
            {"name": "레거시 정리 테스트용", "tenant_key": marker_name},
        )
        conn.commit()
        institution_id = conn.execute(
            text("SELECT id FROM financial_institutions WHERE tenant_key = :tk"),
            {"tk": marker_name},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO portfolios "
                "(financial_institution_id, name, reporting_year, reporting_currency, scope_mode, status, version) "
                "VALUES (:fi, :name, 2026, 'KRW', 'supported_business_loans', 'draft', 1)"
            ),
            {"fi": institution_id, "name": marker_name},
        )
        conn.commit()

    drop_legacy_tables(engine)

    with engine.connect() as conn:
        remaining = conn.execute(
            text("SELECT COUNT(*) FROM portfolios WHERE name = :name"),
            {"name": marker_name},
        ).scalar()
    engine.dispose()
    assert remaining == 1, "drop_legacy_tables() 가 신규 portfolios 테이블 데이터를 건드리면 안 됨"
