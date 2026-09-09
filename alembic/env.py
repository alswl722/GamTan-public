import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

# repo 루트를 sys.path 에 넣어 `db` 패키지 import 가능하게 (tests/conftest.py와 동일 패턴)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 실제 접속 문자열은 .env 의 DATABASE_URL 에서 읽는다 (alembic.ini 에 하드코딩하지 않음, 커밋 금지 원칙).
# config.set_main_option()은 쓰지 않는다 — configparser가 URL 안의 %(예: URL 인코딩된
# %3D, 비밀번호의 %)를 interpolation 문법으로 오인해 깨진다. 대신 _get_url() 이 매번
# attributes(테스트가 주입한 URL) 또는 .env 값을 직접 반환해 create_engine에 넘긴다.
load_dotenv()


def _get_url() -> str:
    attr_url = config.attributes.get("sqlalchemy.url")
    if attr_url:
        return attr_url
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    raise RuntimeError("DATABASE_URL이 설정되지 않았습니다 (.env 확인)")

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# db/models.py 가 스키마의 유일한 진실 — autogenerate 가 이 metadata 와 실제 DB를 비교한다.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # 마이그레이션은 단발 연결이므로 pooling 불필요 (api/db.py의 pool_size=5는 API 런타임 전용)
    connectable = create_engine(_get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
