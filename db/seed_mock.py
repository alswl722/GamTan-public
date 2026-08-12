"""목업 시나리오 데이터 — ○○정밀 (금속가공 2차 벤더, 직원 12명)
데모 시나리오: 2025년 12개월치 전표 (3~5월 가스 결손, 7월 경유 이상치)

트레이스는 심지 않는다 — 트레이스 뷰에는 실제 에이전트 실행 결과만 표시
(실패 가시성 원칙: 사전 녹화·연출 데이터 없음).
"""
import os
import sys
from datetime import datetime, timezone, date
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Company, FinancialInstitution, InstitutionBorrower, Voucher

load_dotenv()

# 0006 마이그레이션이 백필한 데모 금융기관과 같은 tenant — 신규 기업도 같은 기관 소속으로
# 붙여야 institution_borrower 조회(자료 업로드·마이데이터 연동)가 동작한다.
DEMO_TENANT_KEY = "demo-im-bank"
DEMO_INSTITUTION_NAME = "감탄 데모 금융기관"

# 회계 담당이 만든 결측 시나리오용 기업 6곳 (data/감탄_데이터준비_샘플.xlsx의 company_master
# 시트, data/마이데이터_연동자료_전체기업.csv, data/업로드서류/ 전부 이 6곳 기준).
# external_id는 그 CSV/PDF의 company_id 컬럼("C001"~"C006")과 그대로 맞춘다 — 마이데이터
# CSV를 읽을 때 이 값으로 다시 찾아간다(db/mydata_csv_source.py).
# industry_code는 벤치마킹 데이터(db/init_db.py::seed_industry_distributions)가 있는
# 기존 두 코드(C251/C259) 중 하나로 매핑 — 신규 코드를 쓰면 업종분포 비교가 빈 값이 된다.
EXTRA_COMPANIES = [
    dict(external_id="C001", name="구미정밀", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=18,
         revenue_krw=2_500_000_000, region="경북 구미"),
    dict(external_id="C002", name="대경부품", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=12,
         revenue_krw=1_800_000_000, region="경북 경산"),
    dict(external_id="C003", name="성서테크", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=25,
         revenue_krw=3_200_000_000, region="대구 달서"),
    dict(external_id="C004", name="칠곡소재", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=9,
         revenue_krw=950_000_000, region="경북 칠곡"),
    dict(external_id="C005", name="포항이엔지", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=15,
         revenue_krw=2_100_000_000, region="경북 포항"),
    dict(external_id="C006", name="대구정공", industry_code="C259",
         industry_name="기타 금속가공제품 제조", employee_count=11,
         revenue_krw=1_400_000_000, region="대구 북구"),
]


DEMO_COMPANY = dict(
    name="○○정밀",
    industry_code="C251",
    industry_name="구조용 금속제품 제조",
    employee_count=12,
    revenue_krw=2_400_000_000,  # 24억
    region="경북 구미시",
)

# 2025년 12개월치 전표 템플릿
# 3~5월 가스 전표 의도적 결손 (데모 킬러씬 A)
# 7월 경유 이상치: 지게차 2대 증차로 경유 사용량 급증
VOUCHERS = [
    # ─── 1월 ───
    {"source": "kepco", "year": 2025, "month": 1, "issue_date": date(2025, 1, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_420_000},
    {"source": "hometax", "year": 2025, "month": 1, "issue_date": date(2025, 1, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 난방)",
     "supply_amount_krw": 1_240_000},
    {"source": "hometax", "year": 2025, "month": 1, "issue_date": date(2025, 1, 18),
     "supplier_name": "구미석유", "item_description": "경유 외 1종",
     "supply_amount_krw": 654_000},
    # ─── 2월 ───
    {"source": "kepco", "year": 2025, "month": 2, "issue_date": date(2025, 2, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_180_000},
    {"source": "hometax", "year": 2025, "month": 2, "issue_date": date(2025, 2, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스 요금",
     "supply_amount_krw": 1_150_000},
    {"source": "hometax", "year": 2025, "month": 2, "issue_date": date(2025, 2, 15),
     "supplier_name": "구미석유", "item_description": "유류대금",
     "supply_amount_krw": 612_000},
    # ─── 3월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2025, "month": 3, "issue_date": date(2025, 3, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_560_000},
    # 도시가스 3월 전표 없음 (에이전트가 감지해야 함)
    {"source": "hometax", "year": 2025, "month": 3, "issue_date": date(2025, 3, 17),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 589_000},
    # ─── 4월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2025, "month": 4, "issue_date": date(2025, 4, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_210_000},
    # 도시가스 4월 전표 없음
    {"source": "hometax", "year": 2025, "month": 4, "issue_date": date(2025, 4, 16),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 601_000},
    # ─── 5월 — 가스 전표 결손! ───
    {"source": "kepco", "year": 2025, "month": 5, "issue_date": date(2025, 5, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_390_000},
    # 도시가스 5월 전표 없음
    {"source": "hometax", "year": 2025, "month": 5, "issue_date": date(2025, 5, 14),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 628_000},
    # ─── 6월 ───
    {"source": "kepco", "year": 2025, "month": 6, "issue_date": date(2025, 6, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_710_000},
    {"source": "hometax", "year": 2025, "month": 6, "issue_date": date(2025, 6, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 480_000},
    {"source": "hometax", "year": 2025, "month": 6, "issue_date": date(2025, 6, 12),
     "supplier_name": "구미석유", "item_description": "경유 외 1종",
     "supply_amount_krw": 643_000},
    # ─── 7월 — 경유 이상치! (지게차 2대 증차) ───
    {"source": "kepco", "year": 2025, "month": 7, "issue_date": date(2025, 7, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 4_120_000},
    {"source": "hometax", "year": 2025, "month": 7, "issue_date": date(2025, 7, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 390_000},
    # 경유 금액이 평월의 약 3.2배 — 지게차 증차로 정상
    {"source": "hometax", "year": 2025, "month": 7, "issue_date": date(2025, 7, 16),
     "supplier_name": "구미석유", "item_description": "지게차 경유 외 1종",
     "supply_amount_krw": 2_089_000},
    # ─── 8월 ───
    {"source": "kepco", "year": 2025, "month": 8, "issue_date": date(2025, 8, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 4_340_000},
    {"source": "hometax", "year": 2025, "month": 8, "issue_date": date(2025, 8, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 320_000},
    {"source": "hometax", "year": 2025, "month": 8, "issue_date": date(2025, 8, 13),
     "supplier_name": "구미석유", "item_description": "지게차 경유",
     "supply_amount_krw": 1_980_000},
    # ─── 9월 ───
    {"source": "kepco", "year": 2025, "month": 9, "issue_date": date(2025, 9, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_870_000},
    {"source": "hometax", "year": 2025, "month": 9, "issue_date": date(2025, 9, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스",
     "supply_amount_krw": 410_000},
    {"source": "hometax", "year": 2025, "month": 9, "issue_date": date(2025, 9, 11),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_960_000},
    # ─── 10월 ───
    {"source": "kepco", "year": 2025, "month": 10, "issue_date": date(2025, 10, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_650_000},
    {"source": "hometax", "year": 2025, "month": 10, "issue_date": date(2025, 10, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 시작)",
     "supply_amount_krw": 720_000},
    {"source": "hometax", "year": 2025, "month": 10, "issue_date": date(2025, 10, 14),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_870_000},
    # ─── 11월 ───
    {"source": "kepco", "year": 2025, "month": 11, "issue_date": date(2025, 11, 25),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_480_000},
    {"source": "hometax", "year": 2025, "month": 11, "issue_date": date(2025, 11, 20),
     "supplier_name": "대성에너지", "item_description": "도시가스 (난방)",
     "supply_amount_krw": 1_050_000},
    {"source": "hometax", "year": 2025, "month": 11, "issue_date": date(2025, 11, 12),
     "supplier_name": "구미석유", "item_description": "경유",
     "supply_amount_krw": 1_910_000},
    # ─── 12월 ───
    {"source": "kepco", "year": 2025, "month": 12, "issue_date": date(2025, 12, 24),
     "supplier_name": "한국전력공사", "item_description": "전기요금 (산업용 을)",
     "supply_amount_krw": 3_290_000},
    {"source": "hometax", "year": 2025, "month": 12, "issue_date": date(2025, 12, 19),
     "supplier_name": "대성에너지", "item_description": "도시가스 (동절기 난방)",
     "supply_amount_krw": 1_380_000},
    {"source": "hometax", "year": 2025, "month": 12, "issue_date": date(2025, 12, 11),
     "supplier_name": "구미석유", "item_description": "유류대금",
     "supply_amount_krw": 1_850_000},
]

# 실측 수량(고지서 사용량) 합성용 대표단가 — db/synth_generator.py 와 동일 기준.
# 전기·도시가스는 사용량이 있어야 계산 엔진이 실측 경로를 타고, 경유는 월별
# 단가(금액÷단가) 경로를 타게 남겨 두 계산 경로가 모두 시연에 등장한다.
_QTY_BY_FUEL = {"전기": (150, "kWh"), "도시가스": (800, "m3")}


def _quantity_fields(v: dict) -> dict:
    if v["source"] == "kepco":
        fuel = "전기"
    elif "가스" in v["item_description"]:
        fuel = "도시가스"
    else:
        return {}
    price, unit = _QTY_BY_FUEL[fuel]
    return {"quantity": round(v["supply_amount_krw"] / price), "quantity_unit": unit}


def seed(session: Session):
    if session.query(Company).filter_by(name="○○정밀").first():
        print("[SKIP] ○○정밀 목업 이미 존재")
        return

    company = Company(**DEMO_COMPANY)
    session.add(company)
    session.flush()

    for v in VOUCHERS:
        raw = {**v, "issue_date": v["issue_date"].isoformat(), **_quantity_fields(v)}
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

    session.commit()
    print(f"[OK] ○○정밀 전표 {len(VOUCHERS)}건 적재")
    print(f"\n[완료] 데모 기업 ID: {company.id}")


def seed_extra_companies(session: Session):
    """회사 선택 화면(웹)에 띄울 데모 기업 6곳 — 마이데이터·업로드 시나리오 전용.

    ○○정밀(전표·트레이스 킬러씬)은 건드리지 않는다 — 이 함수는 별도로 추가만 한다.
    각 기업을 institution_borrower 로도 즉시 백필한다(consent_status=active) — 0006이
    기존 기업에 한 것과 같은 가정: 데모라 동의는 이미 완료된 상태로 취급.
    """
    inst = session.query(FinancialInstitution).filter_by(tenant_key=DEMO_TENANT_KEY).first()
    if inst is None:
        inst = FinancialInstitution(
            name=DEMO_INSTITUTION_NAME, reporting_currency="KRW", tenant_key=DEMO_TENANT_KEY,
        )
        session.add(inst)
        session.flush()

    created = 0
    for c in EXTRA_COMPANIES:
        if session.query(Company).filter_by(name=c["name"]).first():
            continue
        company = Company(
            name=c["name"], industry_code=c["industry_code"], industry_name=c["industry_name"],
            employee_count=c["employee_count"], revenue_krw=c["revenue_krw"], region=c["region"],
        )
        session.add(company)
        session.flush()
        session.add(InstitutionBorrower(
            financial_institution_id=inst.id, company_id=company.id,
            external_customer_id=c["external_id"], consent_status="active",
        ))
        created += 1

    session.commit()
    if created:
        print(f"[OK] 데모 기업 {created}곳 추가 적재 (마이데이터·업로드 시나리오용)")
    else:
        print("[SKIP] 데모 기업 6곳 이미 존재")


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    with Session(engine) as session:
        seed(session)
        seed_extra_companies(session)


if __name__ == "__main__":
    main()
