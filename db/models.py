from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, ForeignKey,
    SmallInteger, Text, Numeric, Index, UniqueConstraint
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
    emission_co2e = Column(Float)                     # tCO2e (결정론적 계산 결과)
    confidence = Column(Float)                        # 0.0 ~ 1.0
    evidence = Column(Text)                           # LLM 판단 근거
    method = Column(String(10))                       # rule | llm
    mixed_item = Column(Integer, default=0)           # 1 = "외 1종" 혼합 품목
    status = Column(String(20), default="auto")       # auto | review_required | confirmed
    classified_at = Column(DateTime(timezone=True), default=now)

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
