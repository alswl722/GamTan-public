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
COPY db ./db
COPY api ./api

# 회계 Excel(배출계수·룰)·마이데이터 mock CSV·PDF 서식 — db/excel_loader.py,
# db/mydata_csv_source.py, db/reports/cnp_application_pdf.py가 런타임에 직접
# 읽는다. 로컬 docker-compose는 볼륨(./data:/app/data)으로 덮어써서 회계가
# Excel을 갱신하면 재시작만으로 반영되지만, Render 등 볼륨 마운트가 없는
# 배포 환경에선 이미지 안에 구워둔 파일만 존재한다 — 안 구우면 첫 분류
# 요청 시점에 파일을 못 찾아 실패한다. data/uploads(사용자 업로드
# 런타임 상태)·data/fixtures(52MB, 로컬 시연·검증 전용)는 이미지에 불필요하고
# uploads는 오히려 재배포마다 초기화되면 안 되는 상태라 COPY 대상에서 뺀다.
COPY data/감탄_데이터준비_샘플.xlsx ./data/감탄_데이터준비_샘플.xlsx
COPY data/industry_distributions.xlsx ./data/industry_distributions.xlsx
COPY data/마이데이터_연동자료_전체기업.csv ./data/마이데이터_연동자료_전체기업.csv
COPY data/forms ./data/forms

EXPOSE 8000

# 컨테이너 자체 헬스체크 — /health 는 DB 를 건드리지 않는 liveness
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
