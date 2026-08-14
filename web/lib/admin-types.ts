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
  method: "rule" | "llm";
  month: number;
  source_document_id: number | null;
  /** 기업이 직접 체크한 연료 목록(FUEL_OPTIONS 라벨) — null이면 아직 체크 전이라 필터링하지 않는다. */
  company_fuel_types: string[] | null;
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
