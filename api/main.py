"""iM-Bridge FastAPI 앱.

라우터: /mock(마이데이터), /trace(장면②), /classify(장면③), /pcaf(장면④),
/agent(오케스트레이터), /scenario(데모 전환), /company(시연 기업 조회),
/admin(관리자 대시보드 — 포트폴리오 집계·HITL 큐).
8월 확장 시 라우터를 추가로 꽂기만 한다.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.db import get_engine
from api.routers import admin, agent, classify, company, mock, pcaf, scenario, trace

app = FastAPI(title="iM-Bridge API", version="0.1.0")

# 로컬 dev(3000)/web 컨테이너(3010) + 배포 프론트(Vercel) 호출 허용.
# 배포 주소는 코드에 박지 않고 ALLOWED_ORIGINS 환경변수(콤마 구분)로 주입한다.
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        *_extra_origins,
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (기존 health 는 아래 그대로 유지)
app.include_router(mock.router)
app.include_router(trace.router)
app.include_router(classify.router)
app.include_router(pcaf.router)
app.include_router(agent.router)
app.include_router(scenario.router)
app.include_router(company.router)
app.include_router(admin.router)


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
