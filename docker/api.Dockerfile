# iM-Bridge FastAPI (백엔드) — build context 는 레포 루트
FROM python:3.12-slim

# pyc 컴파일 스킵(이미지에 안 남을 파일이라 무의미) + pip 출력 억제로 빌드 속도↑
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# PaddleOCR(opencv 경유)이 요구하는 시스템 라이브러리 — 이게 없으면 opencv import
# 시점에 "libGL.so.1: cannot open shared object file" 류로 실패한다(실측 확인).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libgomp1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 (레이어 캐시) — requirements.txt 가 안 바뀌면 이 레이어 그대로 재사용
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# PaddleOCR 한국어 모델 가중치를 빌드 시점에 한 번 받아 이미지에 굽는다 — 런타임에
# 매번 모델 호스트 접속이 필요 없게(결선장 네트워크 장애 리스크 차단, CLAUDE.md §10과
# 같은 결). 첫 배포 이후엔 이 레이어가 캐시돼 재빌드 시 다시 받지 않는다.
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='korean')"

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
