/**
 * 관리자 대시보드 데이터 타입 — 백엔드 응답 형태와 1:1.
 * (id·month는 숫자, nullable 필드 명시 — v0 목업의 string 가정과 다름)
 */

/** 서버사이드 페이지네이션 메타 — review-log/documents/access-log 공통. */
export interface PageMeta {
  total: number;
  page: number;
  page_size: number;
}

export interface Company {
  company_id: number;
  company_name: string;
  industry_name: string | null;
  grade: number;
  measured: boolean;
  scope1: number;
  scope2: number;
  total: number;
  hitl_count: number;
}

export interface PortfolioResponse {
  company_count: number;
  scope1_total: number;
  scope2_total: number;
  total: number;
  grade_distribution: Record<string, number>;   // 도입 후(실측)
  before_distribution: Record<string, number>;   // 도입 전(전 기업 5등급)
  avg_grade: number | null;
  measured_coverage_pct: number;
  hitl_total: number;
  reviewed_today: number;
  companies: Company[];
}

/** 월(1~12) × 연료 대분류 존재 여부 매트릭스 + 결손 목록 — get_coverage() 응답. */
export interface CoverageInfo {
  matrix: Record<string, Record<string, number>>;
  gaps: { fuel: string; missing_months: number[] }[];
}

/** 기업 상세 탭 — GET /admin/companies/{id}/overview 응답. */
export interface CompanyOverview {
  company_id: number;
  company_name: string;
  industry_name: string | null;
  grade: number;
  measured: boolean;
  scope1: number;
  scope2: number;
  hitl_count: number;
  /** 확정은 했지만 아직 "전송" 전인 건수 — 0보다 크면 전송 버튼을 강조 표시. */
  pending_send_count: number;
  coverage: CoverageInfo;
  alerts: AlertItem[];
}

export interface HitlItem {
  voucher_id: number;
  company_id: number;
  company_name: string;
  raw: string;
  scope: 1 | 2 | null;
  category: string | null;
  fuel: string | null;
  amount_krw: number | null;
  confidence: number;
  evidence: string | null;
  /** 계산 엔진이 물량·배출량 산출에 실패해 사람검토로 넘긴 사유 — evidence(판단 근거)와 분리된 필드. */
  calc_failure_reason: string | null;
  method: "rule" | "llm";
  month: number;
  source_document_id: number | null;
  /** 기업이 직접 체크한 연료 목록(FUEL_OPTIONS 라벨) — null이면 아직 체크 전이라 필터링하지 않는다. */
  company_fuel_types: string[] | null;
  /** review_required(검토 대기) | confirmed(검토 완료, 전송 대기) — 확정해도 전송 전까진 큐에 남는다. */
  status: "review_required" | "confirmed";
  /** 이상치 되묻기(docs/tasks.md) — 사장님 확인 상태. disputed|unknown이면
   * 사장님이 명시적으로 "이상하다"고 답한 것이라 우선순위를 올려 표시한다. */
  anomaly_check_status: "pending" | "confirmed_normal" | "disputed" | "unknown" | null;
  anomaly_check_reason: string | null;
  anomaly_ratio: number | null;
}

/** 담당자 교정 입력 — 분류 필드만. */
export interface ClassificationEdit {
  scope?: number | null;
  category?: string | null;
  fuel_type?: string | null;
}

export interface TraceStep {
  id: number;
  step_type: "계획" | "관찰" | "행동";
  tool_name: string | null;
  message: string;
  detail_json?: unknown;
  created_at?: string | null;
}

export interface TraceRunItem {
  session_id: string;
  company_id: number;
  company_name: string;
  ran_at: string | null;
  step_count: number;
  status: "완료" | "실패";
  result_badges: string[];
}

/** 일괄 처리(bulk-confirm/bulk-reject) 건별 결과 — 부분 실패를 그대로 드러낸다. */
export interface BulkActionResult {
  voucher_id: number;
  ok: boolean;
  error?: string;
}

/** 담당자 조치 이력(감사 로그) 한 건 — Classification.evidence/reviewed_at 을 그대로 노출. */
export interface ReviewLogEntry {
  voucher_id: number;
  company_name: string;
  raw: string;
  month: number;
  status: "confirmed" | "rejected";
  evidence: string | null;
  reviewed_at: string | null;
}

// ── 목업 전용 (실 엔드포인트 없음 — 화면에 "예시" 표식) ──────────────────
export interface AlertItem {
  company_id: number;
  company_name: string;
  severity: "high" | "medium" | "low";
  type: "spike" | "drop" | "gap" | "anomaly" | "review";
  year?: number;
  month: number;
  fuel?: string;
  missing_months?: number[];
  review_reason?: "missing_activity_quantity";
  ratio?: number | null;
  anomaly_status?: "pending" | "confirmed_normal" | "disputed" | "unknown";
  message: string;
}

/** 원본문서 접근 감사 로그 한 건 — GET /admin/documents/access-log 응답 항목. */
export interface DocumentAccessLogEntry {
  log_id: number;
  source_document_id: number;
  company_name: string;
  document_type: string;
  original_filename: string | null;
  accessed_by: string;
  accessed_at: string | null;
}

/** 기후리스크 리포트 — GET /admin/climate-risk-report 응답. portfolio_summary()를
 * 재계산 없이 금감원 4단계(거버넌스/전략/리스크평가/공시) 틀로 재배열한 값. */
export interface ClimateRiskReport {
  institution_name: string;
  governance: { description: string };
  strategy: {
    company_count: number;
    before_grade: number;
    avg_grade: number | null;
  };
  risk_assessment: {
    grade_distribution: Record<string, number>;
    /** 도입 전 기준선 — 정의상 전 기업 5등급(매출·업종 통계 대입), Before/After 대조용. */
    before_distribution: Record<string, number>;
  };
  disclosure: {
    measured_coverage_pct: number;
    hitl_total: number;
    reviewed_today: number;
    /** PR #92로 실측 확정(기대_결과 50건 정답지 대조). DB 상태와 무관한
     * 고정값 — docs/v1-plan.md §5-1, db/verification_results.py. */
    classification_accuracy: {
      status: "measured";
      overall_pct: number;
      auto_confirmed_pct: number;
      hitl_recall_pct: number;
      sample_size: number;
      note: string;
    };
    /** 전제 데이터(공시 기업 리스트업) 미확보 — 항상 pending. */
    track_a_mape: { status: "pending"; note: string };
    /** 전제 데이터(실물 파일럿 기업) 미확보 — 항상 pending. */
    track_b_field_test: { status: "pending"; note: string };
  };
  financed_emissions_timeline: {
    /** 항상 true — 대출잔액(business_loan_exposures)이 은행 내부 여신
     * 시스템과 연동되기 전까지는 mock 값으로 계산한 예시일 뿐 실측이 아니다.
     * 산식(귀속계수×차주배출량) 자체는 실제 계산 결과다. */
    is_example: true;
    note: string;
    /** company_count: 그 연도에 실제로 계산된(재무정보+배출량+대출잔액이
     * 모두 있는) 기업 수 — 데이터가 없는 기업은 연도 배열 자체가 비거나
     * 이 값이 작게 나올 수 있다. */
    years: { year: number; financed_emission_tco2e: number; company_count: number }[];
  };
}
