# iM-Bridge FastAPI (백엔드) — build context 는 레포 루트
FROM python:3.12-slim

# pyc 컴파일 스킵(이미지에 안 남을 파일이라 무의미) + pip 출력 억제로 빌드 속도↑
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존성 먼저 (레이어 캐시) — requirements.txt 가 안 바뀌면 이 레이어 그대로 재사용
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# 앱 코드만 (db 패키지는 api 가 import)
# data/ 는 docker-compose.yml 이 이미 볼륨(./data:/app/data)으로 마운트하므로 여기서
# COPY 하지 않는다 — 이미지 안에 굽으면 볼륨과 내용이 중복되고, 회계가 Excel을
# 갱신할 때마다 이미지 재빌드가 필요해진다(볼륨이면 재시작만으로 반영됨).
COPY db ./db
COPY api ./api

EXPOSE 8000

# 컨테이너 자체 헬스체크 — /health 는 DB 를 건드리지 않는 liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
