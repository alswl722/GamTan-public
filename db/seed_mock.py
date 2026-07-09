"""목업 시나리오 데이터 — ○○정밀 (금속가공 2차 벤더, 직원 12명)
데모 시나리오: 2024년 12개월치 전표 (3~5월 가스 결손, 7월 경유 이상치)
"""
import os
import sys
import uuid
from datetime import datetime, timezone, date
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Company, Voucher, TraceLog, Classification

load_dotenv()


DEMO_COMPANY = dict(
    name="○○정밀",
    industry_code="C251",
    industry_name="구조용 금속제품 제조",
    employee_count=12,
    revenue_krw=2_400_000_000,  # 24억
    region="경북 구미시",
)

# 2024년 12개월치 전표 템플릿
# 3~5월 가스 전표 의도적 결손 (데모 킬러씬 A)
# 7월 경유 이상치: 지게차 2대 증차로 경유 사용량 급증
VOUCHERS = [
    # ─── 1월 ───
    {"source": "kepco", "year": 2024, "month": 1, "issue_date": date(2024, 1, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_420_000},
    {"source": "hometax", "year": 2024, "month": 1, "issue_date": date(2024, 1, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 난방)",
     "supply_amount_krw": 1_240_000},
    {"source": "hometax", "year": 2024, "month": 1, "issue_date": date(2024, 1, 18),
     "supplier_name": "구미석유", "item_description": "경유 외 1종",
     "supply_amount_krw": 654_000},
    # ─── 2월 ───
    {"source": "kepco", "year": 2024, "month": 2, "issue_date": date(2024, 2, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_180_000},
    {"source": "hometax", "year": 2024, "month": 2, "issue_date": date(2024, 2, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스 요금",
     "supply_amount_krw": 1_150_000},
    {"source": "hometax", "year": 2024, "month": 2, "issue_date": date(2024, 2, 15),
     "supplier_name": "구미석유", "item_description": "유류대금",
     "supply_amount_krw": 612_000},
    # ─── 3월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2024, "month": 3, "issue_date": date(2024, 3, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_560_000},
    # 도시가스 3월 전표 없음 (에이전트가 감지해야 함)
    {"source": "hometax", "year": 2024, "month": 3, "issue_date": date(2024, 3, 17),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 589_000},
    # ─── 4월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2024, "month": 4, "issue_date": date(2024, 4, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_210_000},
    # 도시가스 4월 전표 없음
    {"source": "hometax", "year": 2024, "month": 4, "issue_date": date(2024, 4, 16),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 601_000},
    # ─── 5월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2024, "month": 5, "issue_date": date(2024, 5, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_390_000},
    # 도시가스 5월 전표 없음
    {"source": "hometax", "year": 2024, "month": 5, "issue_date": date(2024, 5, 14),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 628_000},
    # ─── 6월 ───
    {"source": "kepco", "year": 2024, "month": 6, "issue_date": date(2024, 6, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_710_000},
    {"source": "hometax", "year": 2024, "month": 6, "issue_date": date(2024, 6, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 480_000},
    {"source": "hometax", "year": 2024, "month": 6, "issue_date": date(2024, 6, 12),
     "supplier_name": "구미석유", "item_description": "경유 외 1종",
     "supply_amount_krw": 643_000},
    # ─── 7월 — 경유 이상치! (지게차 2대 증차) ───
    {"source": "kepco", "year": 2024, "month": 7, "issue_date": date(2024, 7, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 4_120_000},
    {"source": "hometax", "year": 2024, "month": 7, "issue_date": date(2024, 7, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 390_000},
    # 경유 금액이 평월의 약 3.2배 — 지게차 증차로 정상
    {"source": "hometax", "year": 2024, "month": 7, "issue_date": date(2024, 7, 16),
     "supplier_name": "구미석유", "item_description": "지게차 경유 외 1종",
     "supply_amount_krw": 2_089_000},
    # ─── 8월 ───
    {"source": "kepco", "year": 2024, "month": 8, "issue_date": date(2024, 8, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 4_340_000},
    {"source": "hometax", "year": 2024, "month": 8, "issue_date": date(2024, 8, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 320_000},
    {"source": "hometax", "year": 2024, "month": 8, "issue_date": date(2024, 8, 13),
     "supplier_name": "구미석유", "item_description": "지게차 경유",
     "supply_amount_krw": 1_980_000},
    # ─── 9월 ───
    {"source": "kepco", "year": 2024, "month": 9, "issue_date": date(2024, 9, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_870_000},
    {"source": "hometax", "year": 2024, "month": 9, "issue_date": date(2024, 9, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 410_000},
    {"source": "hometax", "year": 2024, "month": 9, "issue_date": date(2024, 9, 11),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_960_000},
    # ─── 10월 ───
    {"source": "kepco", "year": 2024, "month": 10, "issue_date": date(2024, 10, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_650_000},
    {"source": "hometax", "year": 2024, "month": 10, "issue_date": date(2024, 10, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 시작)",
     "supply_amount_krw": 720_000},
    {"source": "hometax", "year": 2024, "month": 10, "issue_date": date(2024, 10, 14),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_870_000},
    # ─── 11월 ───
    {"source": "kepco", "year": 2024, "month": 11, "issue_date": date(2024, 11, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_480_000},
    {"source": "hometax", "year": 2024, "month": 11, "issue_date": date(2024, 11, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (난방)",
     "supply_amount_krw": 1_050_000},
    {"source": "hometax", "year": 2024, "month": 11, "issue_date": date(2024, 11, 12),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_910_000},
    # ─── 12월 ───
    {"source": "kepco", "year": 2024, "month": 12, "issue_date": date(2024, 12, 24),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_290_000},
    {"source": "hometax", "year": 2024, "month": 12, "issue_date": date(2024, 12, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 난방)",
     "supply_amount_krw": 1_380_000},
    {"source": "hometax", "year": 2024, "month": 12, "issue_date": date(2024, 12, 11),
     "supplier_name": "구미석유", "item_description": "유류대금",
     "supply_amount_krw": 1_850_000},
]

DEMO_TRACE = [
    dict(step_type="계획", tool_name=None,
         message="2024년 12개월치 전표 분석 시작 → 결손 검사 먼저 수행"),
    dict(step_type="관찰", tool_name="마이데이터 수집기",
         message="전표 33건 수집 완료 (홈택스 22건, 한전 12건)"),
    dict(step_type="관찰", tool_name="결손 검사기",
         message="3~5월 도시가스 전표 0건 — 제조업 특성상 비정상 (동월 전기·경유는 정상 존재)"),
    dict(step_type="행동", tool_name="알림 생성기",
         message="사장님 알림 발송: '3~5월 가스 고지서 미연동 확인 필요'"),
    dict(step_type="행동", tool_name="계산 엔진",
         message="3~5월 도시가스 → 업종 평균값으로 임시 보정, 품질등급 하향(estimated) 표기"),
    dict(step_type="관찰", tool_name="이상치 검증기",
         message="7월 경유 사용량이 업종 중앙값의 3.2배 — 이상치 의심"),
    dict(step_type="행동", tool_name="LLM 분류기",
         message="7월 경유 전표 재파싱 → 품목명 '지게차 경유 외 1종' 확인"),
    dict(step_type="관찰", tool_name="LLM 분류기",
         message="'지게차 2대 증차' 맥락 → 일회성 설비 증가로 정상 판정, 주석 추가"),
    dict(step_type="계획", tool_name=None,
         message="PCAF 2등급까지 부족 데이터 1건(가스 3~5월 실측치) → 연동 요청 목록 생성"),
]


def seed(session: Session):
    if session.query(Company).filter_by(name="○○정밀").first():
        print("[SKIP] ○○정밀 목업 이미 존재")
        return

    company = Company(**DEMO_COMPANY)
    session.add(company)
    session.flush()

    for v in VOUCHERS:
        raw = {**v, "issue_date": v["issue_date"].isoformat()}
        session.add(Voucher(
            company_id=company.id,
            source=v["source"],
            year=v["year"],
            month=v["month"],
            issue_date=datetime(v["issue_date"].year, v["issue_date"].month,
                                v["issue_date"].day, tzinfo=timezone.utc),
            supplier_name=v["supplier_name"],
            item_description=v["item_description"],
            supply_amount_krw=v["supply_amount_krw"],
            raw_json=raw,
        ))

    session.flush()
    print(f"[OK] ○○정밀 전표 {len(VOUCHERS)}건 적재")

    session_id = str(uuid.uuid4())
    for t in DEMO_TRACE:
        session.add(TraceLog(
            company_id=company.id,
            session_id=session_id,
            step_type=t["step_type"],
            tool_name=t.get("tool_name"),
            message=t["message"],
        ))

    session.commit()
    print(f"[OK] 데모 트레이스 로그 {len(DEMO_TRACE)}건 적재 (session_id={session_id})")
    print(f"\n[완료] 데모 기업 ID: {company.id}")


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    with Session(engine) as session:
        seed(session)


if __name__ == "__main__":
    main()
