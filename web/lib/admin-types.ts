/**
 * 관리자 대시보드 데이터 타입 — 백엔드 응답 형태와 1:1.
 * (id·month는 숫자, nullable 필드 명시 — v0 목업의 string 가정과 다름)
 */

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
  method: "rule" | "llm";
  month: number;
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
  type: "spike" | "drop" | "gap";
  month: number;
  message: string;
}

/**
 * K택소노미·설비투자 리드 — GET /admin/k-taxonomy-leads 응답 항목. finance_lead_type이
 * 채워져도 여신 결정이 아니라 안내 대상일 뿐이다(CLAUDE.md §9).
 */
export interface KTaxonomyLeadItem {
  company_id: number;
  company_name: string;
  industry_name: string | null;
  finance_lead_type: string;
  k_taxonomy_candidate_type: string | null;
  k_taxonomy_facility_type: string | null;
  k_taxonomy_hitl_required: boolean;
  item_description: string;
  voucher_month: number;
  gap_count: number;
}

/** 등급 상승 역산 후보 — GET /admin/rate-candidates 응답 항목. */
export interface RateCandidateItem {
  company_id: number;
  company_name: string;
  current_grade: number;
  target_grade: number;
  missing: string;
  benefit: string;
}

/**
 * 승인요청 큐 항목 — GET /admin/rate-requests 응답. HITL 큐(분류 신뢰도, HitlItem)와는
 * 완전히 다른 데이터: 여기 status는 사장님 요청에 대한 은행 담당자의 승인/반려 상태이고,
 * 승인도 여신 결정이 아니라 "안내 대상 확인"일 뿐이다(disclaimer_text가 항상 동반).
 */
export interface RateApprovalRequestItem {
  id: number;
  company_id: number;
  company_name: string;
  request_type: "rate_upgrade" | "equipment_finance";
  current_grade: number | null;
  target_grade: number | null;
  missing_summary: string | null;
  disclaimer_text: string;
  status: "pending" | "approved" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string | null;
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

/**
 * 품질 이슈 로그 한 건 — GET /admin/quality-issues 응답 항목(열람 전용).
 * 업로드 반려·실패 이력만 모은다 — 성공한 업로드는 여기 안 남는다.
 */
export interface QualityIssueEntry {
  id: number;
  company_id: number;
  company_name: string;
  document_type: string | null;
  original_filename: string | null;
  failure_reason: "duplicate" | "missing_institution" | "excel_format" | "parse_error";
  failure_reason_label: string;
  detail: string;
  created_at: string | null;
}
