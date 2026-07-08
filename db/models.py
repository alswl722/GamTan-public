from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, ForeignKey,
    SmallInteger, Text, Numeric, Index
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


def now():
    return datetime.now(timezone.utc)


class Company(Base):
    """기업"""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    industry_code = Column(String(20), nullable=False)   # 예: C251 (금속가공)
    industry_name = Column(String(100))
    employee_count = Column(Integer)
    revenue_krw = Column(Numeric(20, 0))
    region = Column(String(50))                          # 예: 경북 구미시
    created_at = Column(DateTime(timezone=True), default=now)

    vouchers = relationship("Voucher", back_populates="company")
    portfolio = relationship("PortfolioSummary", back_populates="company")
    trace_logs = relationship("TraceLog", back_populates="company")


class Voucher(Base):
    """전표 (raw) — 홈택스 세금계산서 + 한전 고지서"""
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    source = Column(String(20), nullable=False)          # 'hometax' | 'kepco'
    issue_date = Column(DateTime(timezone=True))
    year = Column(SmallInteger, nullable=False)
    month = Column(SmallInteger, nullable=False)
    supplier_name = Column(String(100))
    item_description = Column(Text)                      # 품목명 (경유 외 1종 등)
    supply_amount_krw = Column(Numeric(15, 0))           # 공급가액 (부가세 제외)
    raw_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=now)

    company = relationship("Company", back_populates="vouchers")
    classification = relationship("ClassificationResult", back_populates="voucher", uselist=False)
    hitl_item = relationship("HitlQueue", back_populates="voucher", uselist=False)

    __table_args__ = (
        Index("ix_vouchers_company_year_month", "company_id", "year", "month"),
    )


class ClassificationResult(Base):
    """분류 결과 — 도구2(룰) or 도구3(LLM) 출력 → 도구4(계산엔진) 결과"""
    __tablename__ = "classification_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=False, unique=True)
    scope = Column(SmallInteger)                         # 1 | 2 | 3
    category = Column(String(50))                        # 고정연소 | 이동연소 | 간접배출 등
    fuel_type = Column(String(50))                       # 경유 | 도시가스 | 전기 등
    amount_krw = Column(Numeric(15, 0))                  # 분류된 공급가액
    activity_amount = Column(Float)                      # 물량 (리터, kWh, m³ 등)
    activity_unit = Column(String(20))                   # L | kWh | MJ | m3
    emission_co2e = Column(Float)                        # tCO2e
    confidence = Column(Float)                           # 0.0 ~ 1.0
    evidence = Column(Text)                              # LLM 판단 근거
    method = Column(String(10))                          # 'rule' | 'llm'
    quality_flag = Column(String(20), default="normal")  # normal | estimated | hitl_required
    mixed_item = Column(Integer, default=0)              # 1 = "외 1종" 혼합 품목
    classified_at = Column(DateTime(timezone=True), default=now)

    voucher = relationship("Voucher", back_populates="classification")


class EmissionFactor(Base):
    """배출계수 — 환경부/환경공단 공개 계수"""
    __tablename__ = "emission_factors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fuel_type = Column(String(50), nullable=False)
    scope = Column(SmallInteger, nullable=False)
    category = Column(String(50))
    factor_co2 = Column(Float, nullable=False)           # kg CO2/단위
    factor_ch4 = Column(Float, default=0.0)
    factor_n2o = Column(Float, default=0.0)
    gwp_co2e = Column(Float)                             # CO2e 환산 계수 합산
    unit = Column(String(20), nullable=False)            # L | kWh | MJ | m3
    source = Column(String(100))                         # 환경부 국가 온실가스 인벤토리 등
    valid_from = Column(SmallInteger)                    # 연도
    valid_to = Column(SmallInteger)


class MonthlyUnitPrice(Base):
    """환산단가 (월별) — 경유·도시가스 등 유가 월 변동 반영"""
    __tablename__ = "monthly_unit_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fuel_type = Column(String(50), nullable=False)
    year = Column(SmallInteger, nullable=False)
    month = Column(SmallInteger, nullable=False)
    unit_price_krw = Column(Numeric(10, 2), nullable=False)  # 원/단위
    unit = Column(String(20), nullable=False)                 # L | m3 | kWh
    source = Column(String(100))

    __table_args__ = (
        Index("ix_unit_prices_fuel_year_month", "fuel_type", "year", "month"),
    )


class IndustryDistribution(Base):
    """업종별 배출량 분포 — 환경정보공개시스템, 벤치마킹 + 이상치 검증용"""
    __tablename__ = "industry_distributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_code = Column(String(20), nullable=False)
    industry_name = Column(String(100))
    scope = Column(SmallInteger, nullable=False)
    emission_min_co2e = Column(Float)                    # tCO2e/억원 (매출 정규화)
    emission_median_co2e = Column(Float)
    emission_median_per_employee = Column(Float)         # tCO2e/인
    emission_max_co2e = Column(Float)
    revenue_basis_krw = Column(Numeric(20, 0))           # 정규화 기준 매출액
    year = Column(SmallInteger, nullable=False)
    source = Column(String(100))

    __table_args__ = (
        Index("ix_industry_dist_code_year", "industry_code", "year"),
    )


class PortfolioSummary(Base):
    """포트폴리오 집계 — 기업별 연간 최종 배출량 + PCAF 등급"""
    __tablename__ = "portfolio_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    year = Column(SmallInteger, nullable=False)
    scope1_co2e = Column(Float, default=0.0)
    scope2_co2e = Column(Float, default=0.0)
    scope3_co2e = Column(Float, default=0.0)
    total_co2e = Column(Float)
    pcaf_grade = Column(SmallInteger)                    # 1~5 (본 엔진)
    pcaf_old_grade = Column(SmallInteger)                # 기존 방식 (매출 추정)
    pcaf_old_co2e = Column(Float)                        # 기존 방식 추정치
    quality_score = Column(Float)                        # 0.0~1.0
    benchmark_percentile = Column(Float)                 # 동종업종 상위 X%
    data_gap_months = Column(JSON)                       # 결손 월 목록 [3,4,5]
    calculated_at = Column(DateTime(timezone=True), default=now)

    company = relationship("Company", back_populates="portfolio")

    __table_args__ = (
        Index("ix_portfolio_company_year", "company_id", "year"),
    )


class TraceLog(Base):
    """에이전트 트레이스 로그 — 트레이스 뷰 타임라인 소스"""
    __tablename__ = "trace_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    session_id = Column(String(36), nullable=False)      # UUID per run
    step_type = Column(String(20), nullable=False)       # 계획 | 관찰 | 행동
    tool_name = Column(String(50))                       # 호출된 도구명
    message = Column(Text, nullable=False)               # 타임라인 표시 문구
    detail_json = Column(JSON)                           # tool input/output 원문
    created_at = Column(DateTime(timezone=True), default=now)

    company = relationship("Company", back_populates="trace_logs")

    __table_args__ = (
        Index("ix_trace_session", "session_id"),
    )


class HitlQueue(Base):
    """HITL 큐 — confidence 미달 건 검토 대기"""
    __tablename__ = "hitl_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=False, unique=True)
    classification_id = Column(Integer, ForeignKey("classification_results.id"))
    reason = Column(Text)                                # 큐 진입 사유
    status = Column(String(20), default="pending")       # pending | approved | rejected
    reviewer_note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)
    reviewed_at = Column(DateTime(timezone=True))

    voucher = relationship("Voucher", back_populates="hitl_item")
