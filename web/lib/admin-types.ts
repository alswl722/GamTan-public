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

/** 이상 신호 알림 — GET /admin/alerts 응답 항목. */
export interface AlertItem {
  company_id: number;
  company_name: string;
  severity: "high" | "medium" | "low";
  type: "spike" | "drop" | "gap";
  month: number;
  message: string;
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
