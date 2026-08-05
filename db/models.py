from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, ForeignKey,
    SmallInteger, Text, Numeric, Index, UniqueConstraint, CheckConstraint,
    Boolean
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
    industry_code = Column(String(20), nullable=False)
    industry_name = Column(String(100))
    employee_count = Column(Integer)
    revenue_krw = Column(Numeric(20, 0))
    region = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=now)

    vouchers = relationship("Voucher", back_populates="company")
    trace_logs = relationship("TraceLog", back_populates="company")


class Voucher(Base):
    """전표 raw — 홈택스 세금계산서 + 한전 고지서"""
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    source = Column(String(20), nullable=False)       # hometax | kepco
    issue_date = Column(DateTime(timezone=True))
    year = Column(SmallInteger, nullable=False)
    month = Column(SmallInteger, nullable=False)
    supplier_name = Column(String(100))
    item_description = Column(Text)
    supply_amount_krw = Column(Numeric(15, 0))        # 공급가액 (부가세 제외)
    raw_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=now)

    company = relationship("Company", back_populates="vouchers")
    classification = relationship("Classification", back_populates="voucher", uselist=False)

    __table_args__ = (
        Index("ix_vouchers_company_year_month", "company_id", "year", "month"),
    )


class Classification(Base):
    """분류 결과 — LLM/룰 출력 + 상태 (자동확정/검토필요/확정)"""
    __tablename__ = "classifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=False, unique=True)
    scope = Column(SmallInteger)                      # 1 | 2 | 3
    category = Column(String(50))                     # 고정연소 | 이동연소 | 간접배출
    fuel_type = Column(String(50))
    amount_krw = Column(Numeric(15, 0))
    activity_amount = Column(Float)                   # 물량 (L, kWh, m³)
    activity_unit = Column(String(20))
    emission_co2e = Column(Float)                     # kgCO2e (결정론적 계산 결과, 표시 시 ÷1000)
    confidence = Column(Float)                        # 0.0 ~ 1.0
    evidence = Column(Text)                           # LLM 판단 근거
    method = Column(String(10))                       # rule | llm
    mixed_item = Column(Integer, default=0)           # 1 = "외 1종" 혼합 품목
    status = Column(String(20), default="auto")       # auto | review_required | confirmed
    classified_at = Column(DateTime(timezone=True), default=now)
    reviewed_at = Column(DateTime(timezone=True))      # 담당자 확정/반려 시각 (review_required 건만)

    voucher = relationship("Voucher", back_populates="classification")


class EmissionFactor(Base):
    """배출계수 — 환경부/환경공단 공개 계수, 회계 담당이 Table Editor로 직접 관리"""
    __tablename__ = "emission_factors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fuel_type = Column(String(50), nullable=False)
    scope = Column(SmallInteger, nullable=False)
    category = Column(String(50))
    factor_co2 = Column(Float, nullable=False)        # kg CO2/단위
    factor_ch4 = Column(Float, default=0.0)
    factor_n2o = Column(Float, default=0.0)
    gwp_co2e = Column(Float)                          # CO2e 환산 계수 합산
    unit = Column(String(20), nullable=False)
    source = Column(String(100))
    valid_from = Column(SmallInteger)
    valid_to = Column(SmallInteger)


class UnitPrice(Base):
    """환산단가 — 월별 필수 (유가 월 변동 반영), 금액 기준은 공급가액"""
    __tablename__ = "unit_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fuel_type = Column(String(50), nullable=False)
    year = Column(SmallInteger, nullable=False)
    month = Column(SmallInteger, nullable=False)
    unit_price_krw = Column(Numeric(10, 2), nullable=False)
    unit = Column(String(20), nullable=False)         # L | m3 | kWh
    source = Column(String(100))

    __table_args__ = (
        Index("ix_unit_prices_fuel_year_month", "fuel_type", "year", "month"),
    )


class TraceLog(Base):
    """에이전트 판단 일지 — 트레이스 뷰 타임라인 소스, 스키마 결선까지 불변"""
    __tablename__ = "trace_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    session_id = Column(String(36), nullable=False)
    step_type = Column(String(20), nullable=False)    # 계획 | 관찰 | 행동
    tool_name = Column(String(50))
    message = Column(Text, nullable=False)
    detail_json = Column(JSON)                        # tool input/output 원문
    created_at = Column(DateTime(timezone=True), default=now)

    company = relationship("Company", back_populates="trace_logs")

    __table_args__ = (
        Index("ix_trace_session", "session_id"),
    )


class LlmCache(Base):
    """LLM 캐시 — 전표 텍스트 해시 → LLM 응답 (비용·재현성 정식 기능)"""
    __tablename__ = "llm_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text_hash = Column(String(64), nullable=False, unique=True)  # SHA256
    item_description = Column(Text)                  # 원문 (디버깅용)
    llm_response = Column(JSON, nullable=False)      # Classification 스키마 그대로
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=now)
    last_used_at = Column(DateTime(timezone=True), default=now)


class IndustryDistribution(Base):
    """업종별 배출량 분포 — 환경정보공개시스템, 벤치마킹 + 이상치 검증용 (도구④)"""
    __tablename__ = "industry_distributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_code = Column(String(20), nullable=False)   # 예: C251
    industry_name = Column(String(100))
    scope = Column(SmallInteger, nullable=False)         # 1 | 2
    emission_min_co2e = Column(Float)                    # 최소
    emission_median_co2e = Column(Float)                 # 중앙값
    emission_median_per_employee = Column(Float)         # 인당 중앙값
    emission_max_co2e = Column(Float)                    # 최대
    revenue_basis_krw = Column(Numeric(20, 0))           # 정규화 기준 매출
    year = Column(SmallInteger, nullable=False)
    source = Column(String(100))

    __table_args__ = (
        Index("ix_industry_dist_code_year", "industry_code", "year"),
    )


class FinancialInstitution(Base):
    """금융기관 — v1 기관 데이터 격리의 루트 (docs/borrower-pcaf-data-plan.md §7.8)"""
    __tablename__ = "financial_institutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    reporting_currency = Column(String(3), nullable=False)   # ISO 4217, 예: KRW
    tenant_key = Column(String(50), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=now)


class InstitutionUser(Base):
    """금융기관 소속 사용자 — 역할 기반 권한의 기반 (§7.9)"""
    __tablename__ = "institution_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    user_id = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)   # admin | analyst | reviewer | approver | viewer
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'analyst', 'reviewer', 'approver', 'viewer')",
            name="ck_institution_users_role"
        ),
        Index("ix_institution_users_institution_user", "financial_institution_id", "user_id"),
    )


class InstitutionBorrower(Base):
    """금융기관-차주 관계 — 동의 범위 없이 기관 간 데이터를 공유하지 않는다 (§7.10)"""
    __tablename__ = "institution_borrowers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    external_customer_id = Column(String(100), nullable=False)
    consent_status = Column(String(20), nullable=False, default="pending")  # pending | active | revoked | expired
    consent_scope_json = Column(JSON)
    consent_started_at = Column(DateTime(timezone=True))
    consent_ended_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "consent_status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_institution_borrowers_consent_status"
        ),
        UniqueConstraint(
            "financial_institution_id", "external_customer_id",
            name="uq_institution_borrowers_institution_external_id"
        ),
    )


class Portfolio(Base):
    """기관별 기업대출 포트폴리오 — 산정 스냅숏의 상위 단위 (§7.11)"""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    name = Column(String(100), nullable=False)
    reporting_year = Column(SmallInteger, nullable=False)
    reporting_date = Column(DateTime(timezone=True))
    reporting_currency = Column(String(3), nullable=False)
    scope_mode = Column(String(30), nullable=False)   # supported_business_loans | full_institution
    total_relevant_outstanding = Column(Numeric(20, 0))
    reporting_date_events_json = Column(JSON)
    status = Column(String(20), nullable=False, default="draft")  # draft | calculated | reviewed | approved | superseded
    version = Column(Integer, nullable=False, default=1)
    supersedes_portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "scope_mode IN ('supported_business_loans', 'full_institution')",
            name="ck_portfolios_scope_mode"
        ),
        CheckConstraint(
            "status IN ('draft', 'calculated', 'reviewed', 'approved', 'superseded')",
            name="ck_portfolios_status"
        ),
        Index("ix_portfolios_institution_year", "financial_institution_id", "reporting_year"),
    )


