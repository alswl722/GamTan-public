from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, JSON, ForeignKey,
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

    # v1 §3 원칙8 — 사장님이 2단계(연료 유형 체크)에서 고른 값. 체크 안 한 연료는
    # 결손 알림 대상에서 제외한다(예: 도시가스 미사용 기업에게 도시가스 결손 알림 금지).
    # {"diesel": bool, "gasoline": bool, "city_gas": bool, "lpg": "yes"|"no"|"unsure",
    #  "electricity": bool} — null이면 아직 미입력(필터 미적용, 기존 결손 감지 그대로 동작).
    fuel_types_json = Column(JSON)

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

    # v1: 어느 금융기관의 동의·수집 경로에서 생성된 전표인지 구분 (nullable — 0006에서 백필)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"))
    institution_borrower_id = Column(Integer, ForeignKey("institution_borrowers.id"))
    # 어느 업로드 원본 문서에서 만들어졌는지 (nullable — 0017에서 raw_json 텍스트값을
    # 백필. 마이데이터 mock 경로로 생긴 전표는 원본 문서가 없어 계속 null).
    source_document_id = Column(Integer, ForeignKey("source_documents.id"))

    company = relationship("Company", back_populates="vouchers")
    classification = relationship("Classification", back_populates="voucher", uselist=False)
    source_document = relationship("SourceDocument")

    __table_args__ = (
        Index("ix_vouchers_company_year_month", "company_id", "year", "month"),
        Index("ix_vouchers_source_document", "source_document_id"),
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
    evidence = Column(Text)                           # AI/룰의 순수 분류 판단 근거만 — 계산 실패
                                                        # 사유·담당자 조치는 섞지 않는다(원문과
                                                        # 조치를 구분해 보여주기 위한 필드 분리)
    calc_failure_reason = Column(Text)                # 결정론적 계산 엔진이 물량·배출량 산출에
                                                        # 실패해 사람검토로 넘긴 사유(db/calc_engine.py
                                                        # _review()/CalcDataGap). 계산 성공 시 null
    method = Column(String(10))                       # rule | llm
    mixed_item = Column(Integer, default=0)           # 1 = "외 1종" 혼합 품목
    status = Column(String(20), default="auto")       # auto | review_required | confirmed
    classified_at = Column(DateTime(timezone=True), default=now)
    reviewed_at = Column(DateTime(timezone=True))      # 담당자 확정/반려 시각 (review_required 건만)

    # 확정(저장)과 사장님 전송을 분리 — 담당자가 confirm/edit 해도 바로 사장님 화면에
    # 뜨지 않고, "이 기업 전송" 액션(POST /admin/companies/{id}/send-classifications)을
    # 눌러야 sent_to_owner_at 이 채워지며 그 순간부터 get_classifications()에 노출된다.
    # review_required 건은 애초에 이 필드와 무관(확정 전이라 전송 대상이 아님).
    sent_to_owner_at = Column(DateTime(timezone=True))

    # v1 §7.1 보완 — 기존 method(분류방법)와 분리해 활동자료 방법·증빙·계수버전까지 추적
    classification_method = Column(String(10))    # rule | llm | manual
    activity_data_method = Column(String(30))      # reported_quantity | invoice_quantity | spend_converted | economic_estimate | industry_estimate
    source_document_id = Column(Integer, ForeignKey("source_documents.id"))
    quantity_source = Column(String(20))            # document | calculated | manual
    factor_id = Column(Integer, ForeignKey("emission_factors.id"))
    factor_version = Column(String(20))
    data_period_start = Column(DateTime(timezone=True))
    data_period_end = Column(DateTime(timezone=True))
    calculation_warning = Column(JSON)

    # v1 2주차 — K택소노미·설비투자 리드(회계 data/*.xlsx의 k_taxonomy_mapping 시트,
    # db/k_taxonomy.py 참고). category='감축투자 후보'류 룰(R051~R058, R031, R032)이
    # 매칭됐을 때만 채워진다 — 배출량 계산과는 무관(원문: "배출량 계산 대상 아니나
    # 녹색여신 참고"). finance_lead_type이 채워져도 이건 "리드"일 뿐 여신 결정이
    # 아니다(CLAUDE.md §9) — 최종 승인은 기존 승인요청 큐(RateApprovalRequest)를 거친다.
    k_taxonomy_candidate_type = Column(String(50))   # 재생에너지 설비 | 에너지저장장치 | ...
    k_taxonomy_facility_type = Column(String(50))    # 태양광 설비 | ESS | 전동지게차 | ...
    finance_lead_type = Column(String(50))           # 녹색여신 후보 | 설비금융 후보 | ...
    k_taxonomy_hitl_required = Column(Boolean, default=False)

    # 이상치 되묻기(docs/tasks.md) — 에이전트가 코드로 판별한 이상치(평월 대비
    # N배 급증)를 사장님에게 "맞나요?" 확인받는다. 사장님은 숫자를 입력하지
    # 않는다 — LLM 산수 금지 원칙과 같은 결로, 사장님 입력도 계산 경로가 되면
    # 안 되기 때문에 예/아니오/모르겠어요 + 짧은 사유만 받는다. 1전표당 최신
    # 상태만 저장(이력 누적 아님). "네"는 참고정보로만 남지만, "아니요"·
    # "모르겠어요"는 담당자 우선순위 알림(HITL 큐 배지)으로 이어진다 —
    # api/routers/owner.py의 anomaly-check 엔드포인트가 이 필드를 채운다.
    anomaly_check_status = Column(String(20))  # pending | confirmed_normal | disputed | unknown
    anomaly_check_reason = Column(Text)        # 사장님이 남긴 짧은 사유(선택 입력)
    anomaly_ratio = Column(Float)              # 평월 대비 배수 — 트레이스 값을 영속화

    voucher = relationship("Voucher", back_populates="classification")

    __table_args__ = (
        CheckConstraint(
            "anomaly_check_status IS NULL OR anomaly_check_status IN "
            "('pending', 'confirmed_normal', 'disputed', 'unknown')",
            name="ck_classifications_anomaly_check_status"
        ),
        CheckConstraint(
            "classification_method IS NULL OR classification_method IN ('rule', 'llm', 'manual')",
            name="ck_classifications_classification_method"
        ),
        CheckConstraint(
            "activity_data_method IS NULL OR activity_data_method IN "
            "('reported_quantity', 'invoice_quantity', 'spend_converted', 'economic_estimate', 'industry_estimate')",
            name="ck_classifications_activity_data_method"
        ),
    )


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

    # 종사자 규모 밴드(예: "5인 ~ 9인") — NULL은 전체 규모 통합(밴드 무관 풀링,
    # 좁은 밴드 표본 부족 시 api/queries.py::get_distribution()의 폴백용).
    # 0022에서 추가 — scripts/fetch_industry_distributions.py 실데이터 도입과 함께.
    worker_band = Column(String(30))
    sample_size = Column(Integer)                        # 그 min/median/max 뒤 표본 사업장 수

    __table_args__ = (
        Index("ix_industry_dist_code_year", "industry_code", "year"),
        Index("ix_industry_dist_code_scope_year_band", "industry_code", "scope", "year", "worker_band"),
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


class OrganizationalBoundary(Base):
    """차주 배출량의 조직범위와 재무정보 연결범위를 비교하는 기준정보 (§7.3)"""
    __tablename__ = "organizational_boundaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    reporting_year = Column(SmallInteger, nullable=False)
    boundary_type = Column(String(30), nullable=False)   # operational_control | financial_control | equity_share
    consolidation_scope = Column(String(20), nullable=False)  # consolidated | separate
    included_entities_json = Column(JSON)
    excluded_entities_json = Column(JSON)
    description = Column(Text)
    approved_by = Column(String(100))
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "boundary_type IN ('operational_control', 'financial_control', 'equity_share')",
            name="ck_org_boundaries_boundary_type"
        ),
        CheckConstraint(
            "consolidation_scope IN ('consolidated', 'separate')",
            name="ck_org_boundaries_consolidation_scope"
        ),
        Index("ix_org_boundaries_company_year", "company_id", "reporting_year"),
    )


class SourceDocument(Base):
    """원본 증빙 문서 — 동일 문서 중복 적재 방지, 계산 결과 역추적용 (§7.2)"""
    __tablename__ = "source_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    document_type = Column(String(50), nullable=False)
    source_system = Column(String(50))
    document_date = Column(DateTime(timezone=True))
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    file_hash = Column(String(64))   # SHA256, 중복 적재 방지
    original_filename = Column(String(255))
    file_path = Column(String(500))  # data/uploads/ 하위 상대경로, nullable(구 레코드엔 없음)
    extracted_json = Column(JSON)
    verification_status = Column(String(20), default="unverified")
    # db/document_extraction.py 반환값을 그대로 영속화 — "text_layer" | "html_text" | "ocr".
    # OCR 경로일 때만 extraction_confidence가 채워진다(텍스트 레이어/HTML은 결정론적
    # 정규식 파싱이라 신뢰도 개념이 없음). 0021에서 추가, 그 이전 레코드는 둘 다 null.
    extraction_method = Column(String(20))
    extraction_confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), default=now)
    # "데이터 업로드" 그리드(문서종류 × 월)용 — OCR 업로드(row 1건)는 항상 채워짐.
    # 엑셀 대량 업로드처럼 한 문서가 여러 달에 걸치면 null로 남는다(0017 참고).
    year = Column(SmallInteger)
    month = Column(SmallInteger)

    __table_args__ = (
        Index("ix_source_documents_company", "company_id"),
        Index("ix_source_documents_file_hash", "file_hash"),
        Index("ix_source_documents_type_year_month", "company_id", "document_type", "year", "month"),
        # 코드 레벨 SELECT-then-INSERT 중복 체크만으로는 동시 업로드(더블클릭·재시도)
        # 레이스를 못 막는다 — DB 제약으로 최종 방어선을 둔다.
        UniqueConstraint("company_id", "file_hash", name="uq_source_documents_company_file_hash"),
    )


class SourceDocumentAccessLog(Base):
    """원본문서 열람 감사 로그 (v1 §6 2주차) — "누가 원본을 봤는가"의 기록.

    기존 review-log(Classification.evidence 누적)는 "분류를 확정/반려했다"는 조치
    기록이지 "문서를 열어봤다"는 열람 기록이 아니다 — 열람은 조치가 아니라 접근이라
    별도 로그가 필요하다(SourceDocument 자체엔 열람자·열람시각 컬럼이 없음).
    담당자 식별자는 아직 별도 인증 체계가 없어 문자열로만 받는다(institution_users
    테이블과의 FK 연결은 인증 붙을 때 확장).
    """
    __tablename__ = "source_document_access_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_document_id = Column(Integer, ForeignKey("source_documents.id"), nullable=False)
    accessed_by = Column(String(100), nullable=False)
    accessed_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ix_source_document_access_logs_document", "source_document_id"),
    )


class DocumentIngestionFailure(Base):
    """업로드 반려·실패 이력 (v1 Tier 2 "품질 이슈 로그", owner-admin-flow-spec.md §7).

    api/document_ingestion.py::ingest_uploaded_document()가 예외(DuplicateDocumentError,
    MissingInstitutionAttributionError, HometaxExcelFormatError, DocumentParseError)를
    던지면 그 순간 아무 것도 DB에 안 남고 HTTP 응답으로만 실패가 전달됐다 — 관리자가
    "왜, 얼마나 자주 업로드가 실패하는지" 추적할 방법이 없었다. 이 테이블은 그 실패
    자체를 기록한다(성공한 업로드는 SourceDocument로 이미 남으므로 여기 안 남는다).

    company_id는 nullable — MissingInstitutionAttributionError처럼 기관 귀속 판정 전
    단계에서 실패해도 기록은 남겨야 한다(company_id 자체는 항상 알 수 있어 실제로는
    항상 채워지지만, 미래의 실패 유형을 대비해 스키마를 강제하지 않는다).
    """
    __tablename__ = "document_ingestion_failures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    document_type = Column(String(50))
    original_filename = Column(String(255))
    failure_reason = Column(String(30), nullable=False)
    # duplicate | missing_institution | excel_format | parse_error
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "failure_reason IN ('duplicate', 'missing_institution', 'excel_format', 'parse_error')",
            name="ck_document_ingestion_failures_reason",
        ),
        Index("ix_document_ingestion_failures_company", "company_id"),
    )


class DocumentUploadJob(Base):
    """업로드 백그라운드 처리 잡 — 접수(파일 저장)와 실제 추출(OCR/LLM)을 분리한다.

    POST /owner/{id}/documents/upload는 이 레코드를 processing으로 만들고 즉시
    202로 응답한다(api/document_ingestion.py::create_upload_job). 실제 무거운 작업
    (api/document_ingestion.py::process_upload_job)은 FastAPI BackgroundTasks로
    돌며 이 레코드를 done/failed로 갱신한다 — 사장님이 업로드 페이지에 머물러
    있지 않아도 되게 하기 위함(v1 2주차, docs 미반영·채팅 계획 참고). 완료 시
    OwnerNotification(type=document_processed|document_failed)을 남겨 실패를
    조용히 흘려보내지 않는다(CLAUDE.md §6 실패 가시성 원칙).
    """
    __tablename__ = "document_upload_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=False)  # 같은 파일 재제출(더블클릭 등) 감지용
    file_path = Column(String(500), nullable=False)  # data/uploads/ 하위 상대경로 — 백그라운드에서 다시 읽음
    document_type_hint = Column(String(50))  # null이면 "그냥 업로드"(자동판별)
    mode = Column(String(10), nullable=False)  # ocr | excel
    status = Column(String(20), nullable=False, default="processing")
    result_source_document_id = Column(Integer, ForeignKey("source_documents.id"))
    result_document_type = Column(String(50))
    result_year = Column(SmallInteger)
    result_month = Column(SmallInteger)
    vouchers_created = Column(Integer)
    skipped_rows = Column(Integer)
    guidance_message = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)
    finished_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'done', 'failed')",
            name="ck_document_upload_jobs_status",
        ),
        Index("ix_document_upload_jobs_company_status", "company_id", "status"),
    )


class RateApprovalRequest(Base):
    """우대금리·설비금융 안내 승인요청 큐 (v1 §6 2주차).

    기존 GET /admin/rate-candidates(db/pcaf_quality.py::quality_rate_upgrade_candidates)는
    읽기 전용 "안내 후보" 목록일 뿐 사장님이 실제로 요청을 만드는 행위가 없었다. 이
    테이블은 그 요청 자체와 은행 담당자의 승인/반려를 저장한다.

    scope_group은 rate_upgrade 요청에서 어느 Scope(scope_1|scope_2)에 대한 등급 상승
    요청인지 저장한다 — 정식 엔진(db/pcaf_quality.py)은 Scope별로 독립 판정하므로 한
    기업이 동시에 두 Scope의 후보일 수 있다. equipment_finance 요청과 이 컬럼 추가 이전의
    과거 스냅샷은 null로 남는다.
    current_grade/target_grade는 요청 생성 시점 스냅샷 — 이후 재산정으로 등급이
    바뀌어도 요청 당시 근거가 그대로 남는다(감사 가능성).
    disclaimer_text는 승인/반려 응답에 항상 동반해야 하는 비보장 문구를 생성 시점에
    고정해 저장한다 — 문구 정책이 나중에 바뀌어도 과거 요청의 문구는 요청 당시 그대로
    보존된다.
    이 테이블의 승인은 여신 결정이 아니다(CLAUDE.md §9) — 은행 담당자가 "우대금리
    안내 대상으로 확인했다"는 수동 확인이며, 금리·여신 자동판정과는 무관하다.
    """
    __tablename__ = "rate_approval_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    request_type = Column(String(20), nullable=False, default="rate_upgrade")  # rate_upgrade | equipment_finance
    scope_group = Column(String(20))  # scope_1 | scope_2 | null(equipment_finance·과거 스냅샷)
    current_grade = Column(SmallInteger)
    target_grade = Column(SmallInteger)
    missing_summary = Column(Text)
    disclaimer_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending | approved | rejected
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime(timezone=True))
    review_note = Column(Text)
    # 어떤 상품(RateProduct.product_name)에 매칭돼 요청이 만들어졌는지 스냅샷 — FK가
    # 아니라 current_grade/target_grade와 같은 원칙(요청 시점 근거 보존, 상품 조건이
    # 나중에 바뀌어도 과거 요청은 그대로). "이미 대상"인 상태에서 만든 요청만 채워지고,
    # 등급 개선이 필요한 요청·equipment_finance는 null로 남는다.
    matched_product_name = Column(String(200))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "request_type IN ('rate_upgrade', 'equipment_finance')",
            name="ck_rate_approval_requests_request_type"
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_rate_approval_requests_status"
        ),
        Index("ix_rate_approval_requests_company", "company_id"),
        Index("ix_rate_approval_requests_status", "status"),
    )


class RateProduct(Base):
    """우대금리 참조 상품 목록 (PcafQualityRule과 동일 패턴 — 코드가 원 소스).

    db/init_db.py::seed_rate_products가 채운다. 임의로 지어낸 금리·조건이 아니라
    실제 은행 상품(첫 시드는 iM뱅크 "ESG Grow-Up 특별대출")의 공시된 우대금리 티어를
    참고한다 — 그중 감탄이 실제로 만드는 데이터(Scope 1·2 PCAF 데이터 품질등급)로
    증빙 가능한 티어만 시드한다(과잉주장 금지, CLAUDE.md 원칙10).

    min_data_quality_score: 이 점수 이하(=이 등급 이상 고품질)면 자격 충족 —
    PCAF 품질점수는 1(최고)~5(최저) 순서형이라 "작을수록 우수"다.
    rate_discount_pct: 우대금리 폭(%p). 실제 확정 금리가 아니라 상품 공시상 우대폭
    안내이며, 최종 적용 여부·수치는 은행 담당자 심사에 따른다(원칙10).
    requires_k_taxonomy_leads: True면 PCAF 등급만으로는 부족하고 db/k_taxonomy.py::
    k_taxonomy_leads_for_company()가 실제 K택소노미 설비 증거(전표)를 찾아야 자격
    충족으로 본다 — "K-택소노미 그린 SME 대출"처럼 원 상품 자체가 K택소노미 적합
    프로젝트 조건을 요구할 때만 True(2026-08-15, PCAF 등급만 보던 걸 실제 조건에
    맞게 분리). 기본 False는 ESG Grow-Up처럼 PCAF 등급만 보는 기존 상품과 동일.
    """
    __tablename__ = "rate_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(200), nullable=False)
    provider_name = Column(String(100), nullable=False)
    min_data_quality_score = Column(SmallInteger, nullable=False)
    rate_discount_pct = Column(Numeric(4, 2), nullable=False)
    eligibility_description = Column(Text, nullable=False)
    source_reference = Column(Text, nullable=False)
    disclaimer_note = Column(Text)
    requires_k_taxonomy_leads = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "min_data_quality_score BETWEEN 1 AND 5",
            name="ck_rate_products_min_data_quality_score"
        ),
    )


class CompanyGoal(Base):
    """사장님 목표 설정 — 5단계 위저드가 끝나면 홈 화면 박스가 목표 카드로 바뀔 때
    쓰는 스냅숏.

    goal_type 2종:
      - emission_reduction: 배출량 N% 감축. baseline/target_value는 tCO2e(Scope1+2 합산,
        null Scope는 제외 — 원칙7).
      - grade_upgrade: PCAF 데이터 품질 등급 상승. baseline/target_value는 등급(1~5,
        작을수록 우수). 내부적으로 우대금리 상품 매칭과 완전히 같은 엔진
        (db/pcaf_engine/rate_products.py::rate_product_status_for_scope)을 써서, 목표
        등급이 실제 상품 조건과 맞아떨어지면 target_product_name에 남는다 — 등급 상승과
        "혜택 조건 채우기"를 한 화면·한 흐름으로 다루기로 한 기획 결정(등급 탭과 혜택 탭을
        분리하지 않음).

    기업당 활성(status='active') 목표는 항상 최대 1개다 — 새 목표를 만들면 기존 활성
    목표는 덮어쓰지 않고 superseded로 전환한다(원칙8과 같은 결). 진행률·체크리스트는
    여기 저장하지 않고 조회할 때마다 다시 계산한다(quality-report·progress 엔드포인트와
    같은 이 프로젝트의 관례) — 이 테이블은 "무엇을 목표로 했는지"의 스냅숏만 갖는다.
    """
    __tablename__ = "company_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    goal_type = Column(String(30), nullable=False)  # emission_reduction | grade_upgrade
    scope_group = Column(String(10))  # grade_upgrade 필수(scope_1|scope_2), emission_reduction은 null(총량)
    baseline_reporting_year = Column(Integer, nullable=False)
    baseline_value = Column(Float, nullable=False)   # 감축: tCO2e 총량 / 등급: 시작 등급
    target_value = Column(Float, nullable=False)     # 감축: 목표 tCO2e / 등급: 목표 등급
    target_reduction_pct = Column(Float)              # emission_reduction 전용 — 사용자가 고른 원래 %
    target_product_name = Column(String(200))         # grade_upgrade 전용 — 매칭 상품명(없을 수 있음)
    status = Column(String(20), nullable=False, default="active")  # active|achieved|cancelled|superseded
    achieved_at = Column(DateTime(timezone=True))
    superseded_by_goal_id = Column(Integer, ForeignKey("company_goals.id"))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "goal_type IN ('emission_reduction', 'grade_upgrade')",
            name="ck_company_goals_goal_type",
        ),
        CheckConstraint(
            "status IN ('active', 'achieved', 'cancelled', 'superseded')",
            name="ck_company_goals_status",
        ),
        Index("ix_company_goals_company_status", "company_id", "status"),
    )


class PcafQualityRule(Base):
    """PCAF Business Loans and Unlisted Equity 데이터 품질표 (§7.7)

    PCAF Standard Part A Third Edition, Table 10.1-2(Annex, p.192)의 원문 옵션 체계를
    그대로 옮긴 것이다 — Option 1a/1b/2a/2b/3a/3b/3c 7종, Score 1(최고)~5(최저).
    원문은 Scope 1·2와 Scope 3에 별도 품질표를 두지 않고 이 옵션 체계를 공통 적용한다.
    유일한 예외는 Option 2a(에너지 소비량 기반)로, 원문 각주 208이 "The quality scoring
    for the Option 2a is only possible for/applicable to scope 1 and scope 2 emissions
    as scope 3 emissions cannot be estimated by this option"이라 명시해 Scope 3에는
    적용할 수 없다 — applies_to_scope3 플래그로 이 제약만 표현한다.
    분류 신뢰도(Classification.confidence)·HITL 상태와는 완전히 분리된 축이다(§6.1, §6.4).
    """
    __tablename__ = "pcaf_quality_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    standard_version = Column(String(50), nullable=False)   # "PCAF Part A Third Edition"
    asset_class = Column(String(50), nullable=False)         # business_loans_and_unlisted_equity
    option_code = Column(String(10), nullable=False, unique=True)   # 1a | 1b | 2a | 2b | 3a | 3b | 3c
    quality_score = Column(SmallInteger, nullable=False)   # PCAF Score 1(최고)~5(최저)
    # 원문 표의 "Emission factor > Emissions data" 열 — 무엇을 근거로 배출량을 산정하는지.
    activity_data_basis = Column(String(30), nullable=False)
    # verified_emissions | unverified_emissions | energy_consumption |
    # production | revenue | assets | asset_turnover_ratio
    applies_to_scope3 = Column(Boolean, nullable=False, default=True)   # Option 2a만 False
    description = Column(Text)
    source_reference = Column(Text, nullable=False)   # "PCAF Standard Part A, Table 10.1-2, Option 2b"
    valid_from = Column(SmallInteger)
    valid_to = Column(SmallInteger)

    __table_args__ = (
        CheckConstraint(
            "activity_data_basis IN ('verified_emissions', 'unverified_emissions', "
            "'energy_consumption', 'production', 'revenue', 'assets', 'asset_turnover_ratio')",
            name="ck_pcaf_quality_rules_activity_data_basis"
        ),
        CheckConstraint(
            "quality_score BETWEEN 1 AND 5",
            name="ck_pcaf_quality_rules_quality_score"
        ),
        Index("ix_pcaf_quality_rules_asset_class", "asset_class"),
    )


class BorrowerEmissionInventory(Base):
    """차주 연간 Scope별 배출량 인벤토리 (§7.4)

    emission_tco2e 는 nullable — Scope 3 미산정은 0이 아니라 null + scope3_status 로 저장한다
    (LLM 산수 금지·미산정을 0으로 처리하지 않는다는 정본 원칙, docs/borrower-pcaf-data-plan.md §7.4).
    """
    __tablename__ = "borrower_emission_inventories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    reporting_year = Column(SmallInteger, nullable=False)
    organizational_boundary_id = Column(Integer, ForeignKey("organizational_boundaries.id"), nullable=False)
    scope_group = Column(String(10), nullable=False)   # scope_1 | scope_2 | scope_3
    scope2_method = Column(String(20))                 # location_based | market_based | null
    scope3_status = Column(String(20))                 # reported | estimated | not_reported | not_calculated | not_applicable | null
    emission_tco2e = Column(Float, nullable=True)       # Scope 3 미산정 시 null (0 아님)
    calculation_method_summary = Column(Text)
    gwp_version = Column(String(20))
    verified = Column(Boolean, default=False)
    verification_level = Column(String(20))
    completeness_pct = Column(Float)
    candidate_quality_score = Column(SmallInteger)
    candidate_quality_rule_id = Column(Integer, ForeignKey("pcaf_quality_rules.id"))
    candidate_quality_basis_json = Column(JSON)
    limitations_json = Column(JSON)
    status = Column(String(20), nullable=False, default="draft")  # draft | calculated | reviewed | approved | superseded
    version = Column(Integer, nullable=False, default=1)
    supersedes_inventory_id = Column(Integer, ForeignKey("borrower_emission_inventories.id"))
    input_snapshot_hash = Column(String(64))
    approved_by = Column(String(100))
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "scope_group IN ('scope_1', 'scope_2', 'scope_3')",
            name="ck_inventories_scope_group"
        ),
        CheckConstraint(
            "scope2_method IS NULL OR scope2_method IN ('location_based', 'market_based')",
            name="ck_inventories_scope2_method"
        ),
        CheckConstraint(
            "scope3_status IS NULL OR scope3_status IN "
            "('reported', 'estimated', 'not_reported', 'not_calculated', 'not_applicable')",
            name="ck_inventories_scope3_status"
        ),
        CheckConstraint(
            "status IN ('draft', 'calculated', 'reviewed', 'approved', 'superseded')",
            name="ck_inventories_status"
        ),
        Index("ix_inventories_company_year_scope", "company_id", "reporting_year", "scope_group"),
    )


class InventoryGasEmission(Base):
    """인벤토리의 가스별 배출량 — 7대 온실가스, 미확인 가스는 0이 아니라 제외 사유를 남긴다 (§7.5)"""
    __tablename__ = "inventory_gas_emissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inventory_id = Column(Integer, ForeignKey("borrower_emission_inventories.id"), nullable=False)
    gas_type = Column(String(10), nullable=False)   # CO2 | CH4 | N2O | HFCs | PFCs | SF6 | NF3
    emission_mass = Column(Float)
    mass_unit = Column(String(20))
    gwp_value = Column(Float)
    gwp_version = Column(String(20))
    emission_co2e = Column(Float)
    included = Column(Boolean, default=True)
    exclusion_reason = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "gas_type IN ('CO2', 'CH4', 'N2O', 'HFCs', 'PFCs', 'SF6', 'NF3')",
            name="ck_gas_emissions_gas_type"
        ),
        Index("ix_gas_emissions_inventory", "inventory_id"),
    )


class BusinessLoanExposure(Base):
    """포트폴리오의 기업대출 익스포저 — 비상장 중소기업 일반 목적 기업대출만 지원 (§7.13)

    지원 조건: asset_class=business_loans_and_unlisted_equity, company_type=private_company,
    loan_purpose=general_corporate_purpose. 미충족 시 unsupported_methodology + exclusion_reason 기록.
    """
    __tablename__ = "business_loan_exposures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    external_exposure_id = Column(String(100), nullable=False)
    asset_class = Column(String(50), nullable=False)
    outstanding_amount = Column(Numeric(20, 0), nullable=False)
    currency = Column(String(3), nullable=False)
    reporting_date = Column(DateTime(timezone=True), nullable=False)
    loan_purpose = Column(String(50))
    company_type = Column(String(30))
    included = Column(Boolean, default=True)
    exclusion_reason = Column(Text)
    source_snapshot_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "external_exposure_id",
            name="uq_business_loan_exposures_portfolio_external_id"
        ),
        Index("ix_business_loan_exposures_company", "company_id"),
    )


class BorrowerFinancial(Base):
    """차주 재무정보 — PCAF 방법론상 total debt 는 총부채와 혼용하지 않는다 (§7.14)"""
    __tablename__ = "borrower_financials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    financial_institution_id = Column(Integer, ForeignKey("financial_institutions.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    financial_year = Column(SmallInteger, nullable=False)
    as_of_date = Column(DateTime(timezone=True), nullable=False)
    currency = Column(String(3), nullable=False)
    total_equity = Column(Numeric(20, 0))
    total_debt = Column(Numeric(20, 0))
    debt_definition = Column(Text)   # PCAF 방법론상 debt 정의와 재무제표 계정 출처 고정
    consolidation_scope = Column(String(20))
    included_entities_json = Column(JSON)
    source = Column(String(100))
    verified = Column(Boolean, default=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ix_borrower_financials_company_year", "company_id", "financial_year"),
        # version까지 포함 — 재산정 시 새 버전을 만드는 설계는 유지하되(§8.5 재산정 정책),
        # 동시 요청이 같은 (기업,연도,버전)에 중복 행을 만드는 레이스는 막는다.
        UniqueConstraint(
            "company_id", "financial_year", "version",
            name="uq_borrower_financials_company_year_version"
        ),
    )


class FxRate(Base):
    """환율 — 대출잔액·재무정보를 포트폴리오 보고통화로 변환, 결과 스냅숏에 기준일·출처 포함 (§7.15)"""
    __tablename__ = "fx_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    base_currency = Column(String(3), nullable=False)
    quote_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(20, 8), nullable=False)
    rate_date = Column(DateTime(timezone=True), nullable=False)
    rate_type = Column(String(20), nullable=False)   # closing | average | policy_defined
    source = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint(
            "rate_type IN ('closing', 'average', 'policy_defined')",
            name="ck_fx_rates_rate_type"
        ),
        Index("ix_fx_rates_pair_date", "base_currency", "quote_currency", "rate_date"),
    )


class OwnerNotification(Base):
    """사장님 화면 알림 — "확정 전송 → 사장님에게 알림" 축소판 (v1 Tier 2,
    docs/v1-plan.md §5 "PCAF 데이터 품질 실시간 지표화"의 착수분, docs/tasks.md 참고).

    별도 푸시 인프라 없이 DB 레코드 하나로 알림을 표현한다 — 사장님 화면이
    폴링(10~15초, SceneTrace.tsx와 동일 패턴)으로 조회한다. 담당자가
    POST /admin/companies/{id}/send-classifications 로 확정 건을 사장님 화면에
    전송할 때만 레코드가 생긴다(건수 0이면 생성 안 함).
    """
    __tablename__ = "owner_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    type = Column(String(30), nullable=False, default="classification_sent")
    message = Column(Text, nullable=False)
    payload = Column(JSON)  # {"sent_count": int} 등 — 표시 문구 재구성용 원자료
    created_at = Column(DateTime(timezone=True), default=now)
    read_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_owner_notifications_company_unread", "company_id", "read_at"),
    )


class GovSupportProgram(Base):
    """정부 지원사업 공고 — 기업마당(bizinfo) 등 외부 API에서 배치로 수집한 캐시.
    docs/gov-support-matching-plan.md 정본.

    기업별 매칭 결과는 저장하지 않고 매 조회 시 재계산한다(원칙8 대상 아님 —
    추천일 뿐 승인·확정 개념이 없음). embedding은 pgvector `Vector` 타입이 아니라
    JSON(float 리스트)이다 — 이 프로젝트 테스트가 SQLite로 도는데 Vector 타입은
    Postgres 전용이라 충돌해서, 공유 Postgres에 그대로 저장하되 코사인 유사도는
    db/gov_support/matching.py가 Python으로 계산한다(§5 정정, 2026-08-18).
    """
    __tablename__ = "gov_support_programs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(30), nullable=False, default="bizinfo")
    external_id = Column(String(50), nullable=False)  # API 원본 공고 ID (bizinfo pblancId)
    program_name = Column(String(200), nullable=False)
    category = Column(String(50))  # 분야명 (코드 아님 — "기술"·"경영" 등)
    agency_name = Column(String(100))  # 소관기관

    apply_start_date = Column(Date)  # 파싱 성공 시만 채움
    apply_end_date = Column(Date)  # 파싱 성공 시만 채움 — null은 "마감일 모름/상시"로 해석
    apply_period_raw = Column(String(100))  # 원문 그대로 — "모집 완료시"·"예산 소진시까지" 등

    # hashtags에서 뽑은 지역명 콤마 목록. null이거나 전국(다수 지역) 판정이면 지역
    # 제한 없음으로 취급 — 판정 로직은 db/gov_support/matching.py::is_region_eligible.
    region_tags = Column(String(200))

    detail_url = Column(String(500))
    raw_text = Column(Text)  # 임베딩 대상 원문(사업개요+지원대상, HTML 태그 제거)
    raw_text_hash = Column(String(64))  # sha256(raw_text) — 변경분만 재임베딩 판단
    embedding = Column(JSON)  # float 리스트(768차원) — pgvector Vector 타입 아님, 위 docstring 참고

    is_active = Column(Boolean, nullable=False, default=True)  # 최신 배치에서 안 보이면 false
    fetched_at = Column(DateTime(timezone=True))  # 마지막 성공 수집 시각
    updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_gov_support_source_external_id"),
        Index("ix_gov_support_active_apply_end", "is_active", "apply_end_date"),
    )
