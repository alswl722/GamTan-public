/**
 * 관리자 대시보드 데이터 접근 — 실 API는 기존 fetch 래퍼(apiGet/apiPatch) 위에,
 * 목업(우대금리)은 여기 상수로. 실데이터/목업 경계를 한곳에서 본다.
 *
 * 실API 연결: 포트폴리오·검토 큐·확정/수정/반려·실행 이력·이상 신호 알림 = 백엔드 실제 응답.
 * 목업(예시): 우대금리 후보 = 결선 확장 대상(GET /admin/rate-candidates 등 미구현).
 */
import { apiGet, apiPatch } from "@/lib/api";
import type {
  AlertItem,
  BulkActionResult,
  ClassificationEdit,
  HitlItem,
  PortfolioResponse,
  RateCandidateItem,
  ReviewLogEntry,
  TraceRunItem,
  TraceStep,
} from "@/lib/admin-types";

// ── 실 API ──────────────────────────────────────────────────────────────
export function getPortfolio(): Promise<PortfolioResponse> {
  return apiGet<PortfolioResponse>("/admin/portfolio");
}

export function getHitl(): Promise<HitlItem[]> {
  return apiGet<{ queue: HitlItem[] }>("/admin/hitl").then((r) => r.queue);
}

export function confirmVoucher(voucherId: number) {
  return apiPatch(`/admin/classifications/${voucherId}/confirm`);
}

export function editVoucher(voucherId: number, edits: ClassificationEdit) {
  return apiPatch(`/admin/classifications/${voucherId}`, edits);
}

export function rejectVoucher(voucherId: number) {
  return apiPatch(`/admin/classifications/${voucherId}/reject`);
}

/** 여러 건 일괄 확정 — 건별 성공/실패를 그대로 반환(부분 실패를 감추지 않는다). */
export function bulkConfirm(voucherIds: number[]): Promise<{ results: BulkActionResult[] }> {
  return apiPatch("/admin/classifications/bulk-confirm", { voucher_ids: voucherIds });
}

export function bulkReject(voucherIds: number[]): Promise<{ results: BulkActionResult[] }> {
  return apiPatch("/admin/classifications/bulk-reject", { voucher_ids: voucherIds });
}

export function getReviewLog(): Promise<ReviewLogEntry[]> {
  return apiGet<{ entries: ReviewLogEntry[] }>("/admin/review-log").then((r) => r.entries);
}

export function getTraceRuns(): Promise<TraceRunItem[]> {
  return apiGet<{ runs: TraceRunItem[] }>("/admin/traces").then((r) => r.runs);
}

/** 실행 이력 드릴다운 — 기존 /trace/{session_id} 재사용. */
export function getTraceSteps(sessionId: string): Promise<TraceStep[]> {
  return apiGet<{ steps: TraceStep[] }>(`/trace/${sessionId}`).then((r) => r.steps);
}

export function getAlerts(): Promise<AlertItem[]> {
  return apiGet<{ alerts: AlertItem[] }>("/admin/alerts").then((r) => r.alerts);
}

// ── 목업 (예시 · 결선 확장) ────────────────────────────────────────────
export const MOCK_RATE_CANDIDATES: RateCandidateItem[] = [
  { id: "r001", company_name: "동성금속㈜", current_grade: 5, target_grade: 3, missing: "전기요금 고지서 최근 6개월 + 경유 구매 전표", benefit: "대출금리 0.3%p 인하 (우대금리 적용)" },
  { id: "r002", company_name: "진흥산업개발", current_grade: 3, target_grade: 2, missing: "가스 고지서 2장 추가 연동 시 3등급 → 2등급", benefit: "우대금리 대상 + ESG 인증서 발급" },
  { id: "r003", company_name: "한빛화학공업", current_grade: 4, target_grade: 3, missing: "스팀 공급사 배출계수 확인서 제출", benefit: "여신 한도 5% 증액 검토 가능" },
  { id: "r004", company_name: "경남철강㈜", current_grade: 5, target_grade: 4, missing: "전기요금 KEPCO 연동 동의서 + 최근 3개월 전표", benefit: "금리 0.2%p 인하 가능" },
  { id: "r005", company_name: "동아플라스틱", current_grade: 4, target_grade: 3, missing: "작업차량 유류 대장 제출 (3개월)", benefit: "우대금리 검토 대상 진입" },
  { id: "r006", company_name: "광주자동차부품", current_grade: 5, target_grade: 3, missing: "전표 12개월 소급 연동 + 전기요금 연동", benefit: "금리 0.3%p 인하 + 녹색금융 인증 신청 가능" },
  { id: "r007", company_name: "대전반도체장비", current_grade: 3, target_grade: 2, missing: "클린룸 전용 계량기 데이터 3개월 + 냉매 사용 내역", benefit: "우대금리 + ESG 보고서 지원 서비스" },
];
