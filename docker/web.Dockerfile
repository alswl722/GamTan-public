# iM-Bridge Next.js (프론트) — build context 는 레포 루트
# 와이어프레임 단계라 dev 모드로 구동 (핫리로드). 결선 배포 시 build/start 로 전환.
FROM node:20-slim

WORKDIR /app

# 의존성 먼저 (레이어 캐시) — package-lock.json 이 안 바뀌면 이 레이어 그대로 재사용.
# npm ci 는 install 과 달리 lock 파일을 그대로 신뢰해 트리 재계산을 안 하므로 더 빠르고,
# 캐시 마운트로 반복 빌드 시 다운로드 자체를 건너뛴다.
COPY web/package.json web/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# 앱 코드
COPY web ./

EXPOSE 3000

CMD ["npm", "run", "dev"]
