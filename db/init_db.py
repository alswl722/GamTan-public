"""테이블 생성 + 기초 마스터 데이터 적재 (배출계수, 환산단가, 업종분포)"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Base, EmissionFactor, MonthlyUnitPrice, IndustryDistribution

load_dotenv()


def create_tables(engine):
    Base.metadata.create_all(engine)
    print("[OK] 테이블 생성 완료")


def seed_emission_factors(session: Session):
    """배출계수 — 환경부 국가 온실가스 인벤토리 2023년 기준 (주요 연료만)"""
    factors = [
        # Scope 1 — 고정연소
        dict(fuel_type="도시가스(LNG)", scope=1, category="고정연소",
             factor_co2=2.1756, factor_ch4=0.00001, factor_n2o=0.00001,
             gwp_co2e=2.176, unit="m3",
             source="환경부 국가 온실가스 인벤토리 2023", valid_from=2020, valid_to=2025),
        dict(fuel_type="LPG", scope=1, category="고정연소",
             factor_co2=3.0120, factor_ch4=0.00006, factor_n2o=0.00006,
             gwp_co2e=3.014, unit="kg",
             source="환경부 국가 온실가스 인벤토리 2023", valid_from=2020, valid_to=2025),
        dict(fuel_type="경유(보일러)", scope=1, category="고정연소",
             factor_co2=2.6760, factor_ch4=0.00003, factor_n2o=0.00006,
             gwp_co2e=2.677, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023", valid_from=2020, valid_to=2025),
        # Scope 1 — 이동연소
        dict(fuel_type="경유", scope=1, category="이동연소",
             factor_co2=2.5820, factor_ch4=0.00011, factor_n2o=0.00028,
             gwp_co2e=2.591, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023", valid_from=2020, valid_to=2025),
        dict(fuel_type="휘발유", scope=1, category="이동연소",
             factor_co2=2.2030, factor_ch4=0.00025, factor_n2o=0.00022,
             gwp_co2e=2.211, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023", valid_from=2020, valid_to=2025),
        # Scope 2 — 간접배출 (전기)
        dict(fuel_type="전기", scope=2, category="간접배출",
             factor_co2=0.4747, factor_ch4=0.0, factor_n2o=0.0,
             gwp_co2e=0.4747, unit="kWh",
             source="한국전력 전력배출계수 2023", valid_from=2023, valid_to=2023),
        dict(fuel_type="전기", scope=2, category="간접배출",
             factor_co2=0.4747, factor_ch4=0.0, factor_n2o=0.0,
             gwp_co2e=0.4747, unit="kWh",
             source="한국전력 전력배출계수 2024", valid_from=2024, valid_to=2024),
    ]
    for f in factors:
        session.add(EmissionFactor(**f))
    session.commit()
    print(f"[OK] 배출계수 {len(factors)}건 적재")


def seed_monthly_unit_prices(session: Session):
    """환산단가 — 경유/도시가스 월별 단가 (2024년 목업, 실제 교체 필요)
    단위: 경유=원/L, 도시가스=원/m3, 전기=원/kWh
    """
    # 2024년 월별 경유 소비자가격 (한국석유공사 오피넷 기준 추정치)
    diesel_prices = [
        1720, 1690, 1680, 1700, 1710, 1740,
        1760, 1750, 1730, 1720, 1700, 1690
    ]
    # 2024년 월별 도시가스 도매단가 (가스공사 기준 추정치, 원/m3)
    lng_prices = [
        820, 815, 800, 780, 760, 750,
        745, 748, 755, 770, 790, 810
    ]
    # 한전 산업용 전기 (을) 평균 단가 추정 (원/kWh)
    elec_prices = [
        145, 145, 148, 150, 152, 155,
        158, 158, 155, 152, 148, 146
    ]

    rows = []
    for m, (d, g, e) in enumerate(zip(diesel_prices, lng_prices, elec_prices), start=1):
        rows.append(MonthlyUnitPrice(
            fuel_type="경유", year=2024, month=m,
            unit_price_krw=d, unit="L", source="한국석유공사 오피넷 (추정)"))
        rows.append(MonthlyUnitPrice(
            fuel_type="도시가스(LNG)", year=2024, month=m,
            unit_price_krw=g, unit="m3", source="한국가스공사 도매단가 (추정)"))
        rows.append(MonthlyUnitPrice(
            fuel_type="전기", year=2024, month=m,
            unit_price_krw=e, unit="kWh", source="한전 산업용(을) 평균 (추정)"))

    for row in rows:
        session.add(row)
    session.commit()
    print(f"[OK] 월별 환산단가 {len(rows)}건 적재 (2024)")


def seed_industry_distributions(session: Session):
    """업종별 배출량 분포 — 환경정보공개시스템 기반 (금속가공 중심, 목업)"""
    rows = [
        # Scope 1 — 금속가공 (C251, 구조용 금속제품)
        IndustryDistribution(
            industry_code="C251", industry_name="구조용 금속제품 제조",
            scope=1,
            emission_min_co2e=5.2, emission_median_co2e=18.7,
            emission_median_per_employee=1.56,
            emission_max_co2e=124.0,
            year=2023, source="환경정보공개시스템 (목업)"),
        # Scope 2 — 금속가공
        IndustryDistribution(
            industry_code="C251", industry_name="구조용 금속제품 제조",
            scope=2,
            emission_min_co2e=8.1, emission_median_co2e=31.4,
            emission_median_per_employee=2.62,
            emission_max_co2e=198.0,
            year=2023, source="환경정보공개시스템 (목업)"),
        # Scope 1 — 일반 금속가공 (C259)
        IndustryDistribution(
            industry_code="C259", industry_name="기타 금속가공제품 제조",
            scope=1,
            emission_min_co2e=3.8, emission_median_co2e=14.2,
            emission_median_per_employee=1.18,
            emission_max_co2e=89.0,
            year=2023, source="환경정보공개시스템 (목업)"),
        IndustryDistribution(
            industry_code="C259", industry_name="기타 금속가공제품 제조",
            scope=2,
            emission_min_co2e=6.5, emission_median_co2e=24.8,
            emission_median_per_employee=2.07,
            emission_max_co2e=156.0,
            year=2023, source="환경정보공개시스템 (목업)"),
    ]
    for row in rows:
        session.add(row)
    session.commit()
    print(f"[OK] 업종분포 {len(rows)}건 적재")


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    create_tables(engine)

    with Session(engine) as session:
        # 이미 데이터가 있으면 스킵
        if session.query(EmissionFactor).count() == 0:
            seed_emission_factors(session)
        else:
            print("[SKIP] 배출계수 이미 존재")

        if session.query(MonthlyUnitPrice).count() == 0:
            seed_monthly_unit_prices(session)
        else:
            print("[SKIP] 환산단가 이미 존재")

        if session.query(IndustryDistribution).count() == 0:
            seed_industry_distributions(session)
        else:
            print("[SKIP] 업종분포 이미 존재")

    print("\n[완료] DB 초기화 성공")


if __name__ == "__main__":
    main()
