"""테이블 생성 + 기초 마스터 데이터 적재 (배출계수, 환산단가, 업종분포)"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Base, EmissionFactor, UnitPrice, IndustryDistribution

load_dotenv()

# 이전에 만든 잉여 테이블 (확정 스키마 외)
LEGACY_TABLES = [
    "hitl_queue",
    "portfolio_summaries",
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
    print("[OK] 테이블 8개 생성 완료")


def migrate_columns(engine):
    """create_all은 신규 테이블만 만들고 기존 테이블 컬럼 추가는 반영하지 않는다.
    Alembic 없이 운영하는 소규모 스키마라 멱등 ALTER로 직접 보정."""
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE classifications ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ"
        ))
        conn.commit()
    print("[OK] 컬럼 마이그레이션 확인 완료 (classifications.reviewed_at)")


def seed_emission_factors(session: Session):
    """배출계수 — 회계 Excel 값을 항상 우선 반영 (기존 데이터 삭제 후 재적재).
    Excel 없거나 파싱 실패 시에만 하드코딩 폴백 (환경부 인벤토리 2023, source에 '하드코딩' 명시)."""
    try:
        from db.excel_loader import load_emission_factors
        rows = load_emission_factors()
        if rows:
            session.execute(delete(EmissionFactor))
            for r in rows:
                session.add(EmissionFactor(**r))
            session.commit()
            print(f"[OK] 배출계수 {len(rows)}건 적재 (Excel, 기존 데이터 교체)")
            return
    except (FileNotFoundError, LookupError) as e:
        print(f"[i] Excel 배출계수 미사용({e}) → 하드코딩 폴백")

    if session.query(EmissionFactor).count() > 0:
        print("[SKIP] 배출계수 이미 존재 (하드코딩 폴백은 교체하지 않음)")
        return

    factors = [
        # Scope 1 — 고정연소
        dict(fuel_type="도시가스(LNG)", scope=1, category="고정연소",
             factor_co2=2.1756, factor_ch4=0.00001, factor_n2o=0.00001,
             gwp_co2e=2.176, unit="m3",
             source="환경부 국가 온실가스 인벤토리 2023 (하드코딩 폴백)", valid_from=2020, valid_to=2025),
        dict(fuel_type="LPG", scope=1, category="고정연소",
             factor_co2=3.0120, factor_ch4=0.00006, factor_n2o=0.00006,
             gwp_co2e=3.014, unit="kg",
             source="환경부 국가 온실가스 인벤토리 2023 (하드코딩 폴백)", valid_from=2020, valid_to=2025),
        dict(fuel_type="경유(보일러)", scope=1, category="고정연소",
             factor_co2=2.6760, factor_ch4=0.00003, factor_n2o=0.00006,
             gwp_co2e=2.677, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023 (하드코딩 폴백)", valid_from=2020, valid_to=2025),
        # Scope 1 — 이동연소
        dict(fuel_type="경유", scope=1, category="이동연소",
             factor_co2=2.5820, factor_ch4=0.00011, factor_n2o=0.00028,
             gwp_co2e=2.591, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023 (하드코딩 폴백)", valid_from=2020, valid_to=2025),
        dict(fuel_type="휘발유", scope=1, category="이동연소",
             factor_co2=2.2030, factor_ch4=0.00025, factor_n2o=0.00022,
             gwp_co2e=2.211, unit="L",
             source="환경부 국가 온실가스 인벤토리 2023 (하드코딩 폴백)", valid_from=2020, valid_to=2025),
        # Scope 2 — 간접배출 (전기)
        dict(fuel_type="전기", scope=2, category="간접배출",
             factor_co2=0.4747, factor_ch4=0.0, factor_n2o=0.0,
             gwp_co2e=0.4747, unit="kWh",
             source="한국전력 전력배출계수 2023 (하드코딩 폴백)", valid_from=2023, valid_to=2023),
        dict(fuel_type="전기", scope=2, category="간접배출",
             factor_co2=0.4747, factor_ch4=0.0, factor_n2o=0.0,
             gwp_co2e=0.4747, unit="kWh",
             source="한국전력 전력배출계수 2024 (하드코딩 폴백)", valid_from=2024, valid_to=2024),
    ]
    for f in factors:
        session.add(EmissionFactor(**f))
    session.commit()
    print(f"[OK] 배출계수 {len(factors)}건 적재 (하드코딩 폴백)")


def seed_unit_prices(session: Session):
    """환산단가(월별) — 회계 Excel 값을 항상 우선 반영 (기존 데이터 삭제 후 재적재).
    `월별단가` 시트가 있으면 그대로, 없으면 `배출계수` 시트의 단일 단가를 12개월에
    동일 적용(source에 그 사실을 명시). Excel 자체가 없을 때만 하드코딩 폴백
    (source에 '하드코딩' 명시)."""
    try:
        from db.excel_loader import load_unit_prices
        rows = load_unit_prices()
        if rows:
            session.execute(delete(UnitPrice))
            for r in rows:
                session.add(UnitPrice(**r))
            session.commit()
            print(f"[OK] 월별 환산단가 {len(rows)}건 적재 (Excel, 기존 데이터 교체)")
            return
    except (FileNotFoundError, LookupError) as e:
        print(f"[i] Excel 단가 미사용({e}) → 하드코딩 폴백")

    if session.query(UnitPrice).count() > 0:
        print("[SKIP] 환산단가 이미 존재 (하드코딩 폴백은 교체하지 않음)")
        return

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
                      unit_price_krw=d, unit="L",   source="한국석유공사 오피넷 (하드코딩 폴백, 추정)"),
            UnitPrice(fuel_type="도시가스(LNG)", year=2024, month=m,
                      unit_price_krw=g, unit="m3",  source="한국가스공사 도매단가 (하드코딩 폴백, 추정)"),
            UnitPrice(fuel_type="전기",         year=2024, month=m,
                      unit_price_krw=e, unit="kWh", source="한전 산업용(을) 평균 (하드코딩 폴백, 추정)"),
        ]
    for row in rows:
        session.add(row)
    session.commit()
    print(f"[OK] 월별 환산단가 {len(rows)}건 적재 (하드코딩 폴백, 2024)")


def seed_industry_distributions(session: Session):
    """업종별 배출량 분포 — Excel 소스 없음, 전량 하드코딩·목업. 벤치마킹·이상치 검증용."""
    rows = [
        IndustryDistribution(
            industry_code="C251", industry_name="구조용 금속제품 제조", scope=1,
            emission_min_co2e=5.2, emission_median_co2e=18.7,
            emission_median_per_employee=1.56, emission_max_co2e=124.0,
            year=2023, source="환경정보공개시스템 (하드코딩·목업, Excel 소스 없음)"),
        IndustryDistribution(
            industry_code="C251", industry_name="구조용 금속제품 제조", scope=2,
            emission_min_co2e=8.1, emission_median_co2e=31.4,
            emission_median_per_employee=2.62, emission_max_co2e=198.0,
            year=2023, source="환경정보공개시스템 (하드코딩·목업, Excel 소스 없음)"),
        IndustryDistribution(
            industry_code="C259", industry_name="기타 금속가공제품 제조", scope=1,
            emission_min_co2e=3.8, emission_median_co2e=14.2,
            emission_median_per_employee=1.18, emission_max_co2e=89.0,
            year=2023, source="환경정보공개시스템 (하드코딩·목업, Excel 소스 없음)"),
        IndustryDistribution(
            industry_code="C259", industry_name="기타 금속가공제품 제조", scope=2,
            emission_min_co2e=6.5, emission_median_co2e=24.8,
            emission_median_per_employee=2.07, emission_max_co2e=156.0,
            year=2023, source="환경정보공개시스템 (하드코딩·목업, Excel 소스 없음)"),
    ]
    for row in rows:
        session.add(row)
    session.commit()
    print(f"[OK] 업종분포 {len(rows)}건 적재")


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    drop_legacy_tables(engine)
    create_tables(engine)
    migrate_columns(engine)

    with Session(engine) as session:
        # 배출계수·환산단가: Excel 값이 있으면 항상 최신 값으로 교체 (skip 없음)
        seed_emission_factors(session)
        seed_unit_prices(session)

        # 업종분포: Excel 소스 자체가 없는 순수 하드코딩 → 존재하면 그대로 유지
        if session.query(IndustryDistribution).count() == 0:
            seed_industry_distributions(session)
        else:
            print("[SKIP] 업종분포 이미 존재")

    print("\n[완료] DB 초기화 성공")


if __name__ == "__main__":
    main()
