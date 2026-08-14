"""테이블 생성 + 기초 마스터 데이터 적재 (배출계수, 환산단가, 업종분포)"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.models import Base, EmissionFactor, UnitPrice, IndustryDistribution, PcafQualityRule, RateProduct

load_dotenv()

# 이전에 만든 잉여 테이블 (확정 스키마 외)
# 주의: "portfolio_summaries"는 과거 잉여 테이블명이며, v1 신규 "portfolios"(정본 §7.11,
# alembic/versions/0002_*)와는 다른 테이블이다. 이 리스트에 "portfolios"를 추가하지 말 것.
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
    """DEPRECATED: v1부터 신규 컬럼 추가는 alembic/ (revision 0001~)으로 관리한다.
    이 함수는 Alembic 도입 이전(reviewed_at) 컬럼 유지 목적으로만 남기며, 새 ALTER 문을
    추가하지 않는다. 실서비스 배포는 `alembic upgrade head`를 사용한다."""
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


def seed_pcaf_quality_rules(session: Session):
    """PCAF Business Loans and Unlisted Equity 데이터 품질표 — PCAF Standard Part A
    Third Edition, Table 10.1-2(Annex, p.192) 원문을 옵션 단위 그대로 옮긴 것
    (하드코딩이 원 소스, Excel 아님). 원문은 Scope 1·2와 Scope 3에 별도 표를 두지
    않고 이 옵션 체계를 공통 적용하며, Option 2a만 각주 208에 의해 Scope 3에 적용
    불가하다("The quality scoring for the Option 2a is only possible for/applicable
    to scope 1 and scope 2 emissions as scope 3 emissions cannot be estimated by
    this option").

    이미 데이터가 있으면 건드리지 않는다(업종분포 시더와 동일 정책) — 회계가 원문과
    재대조해 valid_from/valid_to 등을 조정하면 그 값이 유지된다.
    """
    if session.query(PcafQualityRule).count() > 0:
        print("[SKIP] PCAF 품질규칙 이미 존재")
        return

    src = "PCAF Standard Part A, Third Edition (Dec 2025), Table 10.1-2, Option {opt}"
    rules = [
        dict(option_code="1a", quality_score=1, activity_data_basis="verified_emissions",
             description="검증된(verified) 배출량 — 차주가 GHG Protocol에 따라 보고하고 제3자 검증을 받은 배출량",
             applies_to_scope3=True, source_reference=src.format(opt="1a")),
        dict(option_code="1b", quality_score=2, activity_data_basis="unverified_emissions",
             description="미검증(unverified) 배출량 — 차주가 GHG Protocol에 따라 계산했으나 제3자 검증은 받지 않은 배출량",
             applies_to_scope3=True, source_reference=src.format(opt="1b")),
        dict(option_code="2a", quality_score=2, activity_data_basis="energy_consumption",
             description="1차 활동자료(에너지원별 에너지 소비량, 예: MWh 전력)에 해당 배출원 특정 배출계수를 적용한 계산값 — Scope 1·2만 적용 가능",
             applies_to_scope3=False, source_reference=src.format(opt="2a")),
        dict(option_code="2b", quality_score=3, activity_data_basis="production",
             description="1차 활동자료(생산량, 예: 톤당 쌀 생산량)에 해당 생산 특정 배출계수를 적용한 계산값",
             applies_to_scope3=True, source_reference=src.format(opt="2b")),
        dict(option_code="3a", quality_score=4, activity_data_basis="revenue",
             description="차주 매출액에 부문별 매출당 배출량(GHG emissions/Revenue) 계수를 적용한 추정값",
             applies_to_scope3=True, source_reference=src.format(opt="3a")),
        dict(option_code="3b", quality_score=5, activity_data_basis="assets",
             description="차주 자산에 부문별 자산당 배출량(GHG emissions/Assets) 계수를 적용한 추정값 (매출 미확보 시)",
             applies_to_scope3=True, source_reference=src.format(opt="3b")),
        dict(option_code="3c", quality_score=5, activity_data_basis="asset_turnover_ratio",
             description="부문별 자산회전율(asset turnover ratio)과 부문별 매출당 배출량 계수를 결합한 추정값",
             applies_to_scope3=True, source_reference=src.format(opt="3c")),
    ]
    for r in rules:
        session.add(PcafQualityRule(
            standard_version="PCAF Part A Third Edition",
            asset_class="business_loans_and_unlisted_equity",
            valid_from=2025,
            **r,
        ))
    session.commit()
    print(f"[OK] PCAF 품질규칙 {len(rules)}건 적재 (Table 10.1-2 원문)")


def seed_rate_products(session: Session):
    """우대금리 참조 상품 2건.

    ① "ESG Grow-Up 특별대출" — iM뱅크 실제 상품 공시 조건을 참고한다(iM뱅크 홈페이지,
    2026-08 확인). 대기업·중견·중소기업·개인사업자 대상, 중진공 ESG 심층진단
    "환경(E) 분야 단독 3등급 이상" 조건이 우대금리 0.30%p — 감탄이 실제로 만드는
    데이터(PCAF Scope 1·2 품질등급)로 증빙 가능한 티어만 시드한다. E·S·G 전분야
    3등급 이상(0.50%p) 티어는 감탄이 사회(S)·지배구조(G) 데이터를 만들지 않으므로
    시드하지 않는다(과잉주장 금지, CLAUDE.md 원칙10).

    ② "K-택소노미 그린 SME 대출" — iM뱅크가 2025.9 발행한 실제 한국형 녹색채권
    (1,100억원, K-택소노미 준거, 한국신용평가 External Review 완료)의 조달자금을
    중소기업 대출로 확장하는 트랜치 상품.

    PcafQualityRule과 동일한 count-guard 멱등 정책 — 이미 있으면 건드리지 않는다.
    """
    if session.query(RateProduct).count() > 0:
        print("[SKIP] 우대금리 상품 이미 존재")
        return

    session.add(RateProduct(
        product_name="ESG Grow-Up 특별대출",
        provider_name="iM뱅크",
        min_data_quality_score=2,
        rate_discount_pct=0.30,
        eligibility_description=(
            "PCAF 데이터 품질 2등급(에너지원별 소비량 실측 기반, Option 2a) 이상 — "
            "중소벤처기업진흥공단 ESG 심층진단 환경(E) 분야 단독 3등급 이상과 동일 "
            "수준의 우대금리 조건에 준함"
        ),
        source_reference=(
            "iM뱅크 ESG Grow-Up 특별대출 "
            "(https://www.imbank.co.kr/cms/fnm/loan/product/giup/01/sda_41211/1231351_2507.html)"
        ),
        disclaimer_note=(
            "실제 적용 여부·금리는 은행 담당자 심사에 따라 달라질 수 있습니다."
        ),
    ))
    session.add(RateProduct(
        product_name="K-택소노미 그린 SME 대출",
        provider_name="iM뱅크",
        min_data_quality_score=2,
        rate_discount_pct=0.40,
        eligibility_description=(
            "PCAF 데이터 품질 2등급(에너지원별 소비량 실측 기반, Option 2a) 이상 — "
            "K-택소노미 적합 프로젝트에 조달자금을 배정하는 iM뱅크 한국형 녹색채권 "
            "트랜치 기반 중소기업 대출"
        ),
        source_reference=(
            "iM뱅크 한국형 녹색채권(아이엠뱅크46-09이24A-26(녹), 2025.9 발행, 1,100억원, "
            "K-택소노미 준거, 한국신용평가 적합성 검토 완료) 조달자금 기반"
        ),
        disclaimer_note=(
            "실제 적용 여부·금리는 은행 담당자 심사에 따라 달라질 수 있습니다."
        ),
    ))
    session.commit()
    print("[OK] 우대금리 상품 2건 적재 (iM뱅크 ESG Grow-Up 특별대출 + K-택소노미 그린 SME 대출)")


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

        # PCAF 품질규칙: 회계 검수 전 초안 → 존재하면 그대로 유지(seed_pcaf_quality_rules 내부에서 skip 처리)
        seed_pcaf_quality_rules(session)

        # 우대금리 상품: 실제 iM뱅크 상품 참고 → 존재하면 그대로 유지(내부에서 skip 처리)
        seed_rate_products(session)

    print("\n[완료] DB 초기화 성공")


if __name__ == "__main__":
    main()
