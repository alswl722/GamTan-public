# iM-Bridge Next.js (프론트) — build context 는 레포 루트
# 와이어프레임 단계라 dev 모드로 구동 (핫리로드). 결선 배포 시 build/start 로 전환.
FROM node:20-slim

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY web/package.json web/package-lock.json* ./
RUN npm install

# 앱 코드
COPY web ./

EXPOSE 3000

CMD ["npm", "run", "dev"]
