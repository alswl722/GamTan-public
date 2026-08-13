/**
 * 관리자 대시보드 데이터 접근 — 백엔드 실제 응답(apiGet/apiPatch)만 다룬다.
 */
import { apiGet, apiPatch, BASE_URL } from "@/lib/api";
import type {
  BulkActionResult,
  ClassificationEdit,
  CompanyOverview,
  DocumentAccessLogEntry,
  HitlItem,
  PageMeta,
  PortfolioResponse,
  ReviewLogEntry,
  TraceRunItem,
  TraceStep,
} from "@/lib/admin-types";

/** 서버사이드 페이지네이션 요청 공통 파라미터 — review-log/access-log 공유. */
export interface PageParams {
  page?: number;
  pageSize?: number;
  companyName?: string;
}

function pageQuery({ page = 1, pageSize = 50, companyName }: PageParams): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (companyName?.trim()) params.set("company_name", companyName.trim());
  return params.toString();
}

// ── 실 API ──────────────────────────────────────────────────────────────
export function getPortfolio(): Promise<PortfolioResponse> {
  return apiGet<PortfolioResponse>("/admin/portfolio");
}

export function getHitl(): Promise<HitlItem[]> {
  return apiGet<{ queue: HitlItem[] }>("/admin/hitl").then((r) => r.queue);
}

/** 전표 원본 파일(PDF) URL — <iframe>/<a>가 직접 src·href로 거는 용도.
 * 열람 시점에 GET /admin/documents/{id}/file 쪽에서 접근 로그가 자동 기록된다. */
export function documentFileUrl(documentId: number, viewedBy: string): string {
  return `${BASE_URL}/admin/documents/${documentId}/file?viewed_by=${encodeURIComponent(viewedBy)}`;
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

export function getReviewLog(
  params: PageParams = {},
): Promise<{ entries: ReviewLogEntry[] } & PageMeta> {
  return apiGet(`/admin/review-log?${pageQuery(params)}`);
}

export function getTraceRuns(): Promise<TraceRunItem[]> {
  return apiGet<{ runs: TraceRunItem[] }>("/admin/traces").then((r) => r.runs);
}

/** 실행 이력 드릴다운 — 기존 /trace/{session_id} 재사용. */
export function getTraceSteps(sessionId: string): Promise<TraceStep[]> {
  return apiGet<{ steps: TraceStep[] }>(`/trace/${sessionId}`).then((r) => r.steps);
}

/** 기업 상세 탭 — 등급·결손·HITL대기·최근알림 요약. */
export function getCompanyOverview(companyId: number): Promise<CompanyOverview> {
  return apiGet(`/admin/companies/${companyId}/overview`);
}

/** 원본문서 접근 감사 로그 — 열람 이벤트 자체의 기록(review-log와 다른 축). */
export function getDocumentAccessLog(
  params: PageParams = {},
): Promise<{ entries: DocumentAccessLogEntry[] } & PageMeta> {
  return apiGet(`/admin/documents/access-log?${pageQuery(params)}`);
}

/** 감사 대응 근거 패키지 CSV 내보내기 URL — 다운로드 링크로 그대로 사용(fetch 불필요). */
export function auditPackageCsvUrl(companyId: number, year: number): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/admin/audit-package?company_id=${companyId}&year=${year}&format=csv`;
}

/** 감사 대응 근거 패키지 PDF(서술형 감사보고서) 내보내기 URL — 다운로드 링크로 그대로 사용. */
export function auditPackagePdfUrl(companyId: number, year: number): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/admin/audit-package?company_id=${companyId}&year=${year}&format=pdf`;
}
