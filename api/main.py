"""iM-Bridge FastAPI 앱 — v0.1 뼈대.

지금은 헬스체크만. 8월 확장 시 이 앱에 라우터(/mock/hometax, 분류,
오케스트레이터 등)를 추가한다 — 루프 코드 교체 없이 꽂기만.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.db import get_engine
from api.routers import mock, trace

app = FastAPI(title="iM-Bridge API", version="0.1.0")

# web 컨테이너/로컬 dev(3000) 에서의 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (기존 health 는 아래 그대로 유지)
app.include_router(mock.router)
app.include_router(trace.router)


@app.get("/health")
def health():
    """Liveness — DB 를 건드리지 않는다. Docker healthcheck 대상."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Readiness — Supabase 에 SELECT 1.

    무료 티어 자동 pause / 네트워크 장애를 조기에 드러낸다.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as exc:  # noqa: BLE001 — 헬스체크는 원인 문자열만 노출
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": "unavailable", "detail": str(exc)},
        )
