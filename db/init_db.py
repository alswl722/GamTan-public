"""테이블 생성 + 기초 마스터 데이터 적재 (배출계수, 환산단가)"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Base, EmissionFactor, UnitPrice

load_dotenv()

# 이전에 만든 잉여 테이블 (7개 확정 스키마 외)
LEGACY_TABLES = [
    "hitl_queue",
    "portfolio_summaries",
    "industry_distributions",
    "monthly_unit_prices",
    "classification_results",
]


def drop_legacy_tables(engine):
    with engine.connect() as conn:
        for table in LEGACY_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.commit()
    print("[OK] 레거시 테이블 정리 완료")


def create_tables(engine):
    Base.metadata.create_all(engine)
    print("[OK] 테이블 7개 생성 완료")


def seed_emission_factors(session: Session):
    """배출계수 — 환경부 국가 온실가스 인벤토리 2023년 기준"""
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


def seed_unit_prices(session: Session):
    """환산단가 — 2024년 월별 (경유/도시가스/전기), 공급가액 기준"""
    diesel_prices = [1720, 1690, 1680, 1700, 1710, 1740,
                     1760, 1750, 1730, 1720, 1700, 1690]
    lng_prices    = [820,  815,  800,  780,  760,  750,
                     745,  748,  755,  770,  790,  810]
    elec_prices   = [145,  145,  148,  150,  152,  155,
                     158,  158,  155,  152,  148,  146]

    rows = []
    for m, (d, g, e) in enumerate(zip(diesel_prices, lng_prices, elec_prices), start=1):
        rows += [
            UnitPrice(fuel_type="경유",        year=2024, month=m,
                      unit_price_krw=d, unit="L",   source="한국석유공사 오피넷 (추정)"),
            UnitPrice(fuel_type="도시가스(LNG)", year=2024, month=m,
                      unit_price_krw=g, unit="m3",  source="한국가스공사 도매단가 (추정)"),
            UnitPrice(fuel_type="전기",         year=2024, month=m,
                      unit_price_krw=e, unit="kWh", source="한전 산업용(을) 평균 (추정)"),
        ]
    for row in rows:
        session.add(row)
    session.commit()
    print(f"[OK] 월별 환산단가 {len(rows)}건 적재 (2024)")


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    drop_legacy_tables(engine)
    create_tables(engine)

    with Session(engine) as session:
        if session.query(EmissionFactor).count() == 0:
            seed_emission_factors(session)
        else:
            print("[SKIP] 배출계수 이미 존재")

        if session.query(UnitPrice).count() == 0:
            seed_unit_prices(session)
        else:
            print("[SKIP] 환산단가 이미 존재")

    print("\n[완료] DB 초기화 성공")


if __name__ == "__main__":
    main()
