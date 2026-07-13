# iM-Bridge FastAPI (백엔드) — build context 는 레포 루트
FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 (db 패키지는 api 가 import)
COPY db ./db
COPY api ./api
COPY data ./data # 회계 Excel (init_db·생성기가 읽음; 없으면 하드코딩 폴백)

EXPOSE 8000

# 컨테이너 자체 헬스체크 — /health 는 DB 를 건드리지 않는 liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
