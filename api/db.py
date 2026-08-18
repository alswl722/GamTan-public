"""공용 SQLAlchemy 엔진 + 세션 의존성.

CLAUDE.md 규칙:
- Supabase Session 모드 풀러 + pool_size=3, pool_pre_ping=True (풀러 한도 15 대비 동시 개발 인원 여유 확보 위해 5→3 축소)
- 접속 문자열은 .env 의 DATABASE_URL (커밋 금지)
이후 라우터들이 get_session 을 Depends 로 재사용한다.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# DATABASE_URL 이 없어도 앱 자체는 뜨도록(엔진 lazy 생성) — /health 는 DB 없이 응답.
_engine = None
_SessionLocal = None


def get_engine():
    """엔진 싱글턴. DATABASE_URL 미설정 시 명확한 에러."""
    global _engine, _SessionLocal
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 이 설정되지 않았습니다 (.env 확인)")
        _engine = create_engine(
            DATABASE_URL,
            pool_size=3,
            pool_pre_ping=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)
    return _engine


def get_session():
    """FastAPI 의존성: 요청 스코프 세션."""
    get_engine()
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def new_session() -> Session:
    """요청 스코프 밖(BackgroundTasks 등)에서 쓰는 독립 세션 — 호출부가 직접 close한다.

    get_session()은 제너레이터라 응답이 나가는 순간 세션이 닫혀 백그라운드
    작업에서 재사용할 수 없다(api/document_ingestion.py::process_upload_job).
    """
    get_engine()
    return _SessionLocal()
