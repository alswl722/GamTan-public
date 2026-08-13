/**
 * 관리자 대시보드 데이터 접근 — 백엔드 실제 응답(apiGet/apiPatch)만 다룬다.
 */
import { apiGet, apiPatch, BASE_URL } from "@/lib/api";
import type {
  AlertItem,
  BulkActionResult,
  ClassificationEdit,
  DocumentAccessLogEntry,
  HitlItem,
  KTaxonomyLeadItem,
  PortfolioResponse,
  QualityIssueEntry,
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

/** K택소노미·설비투자 리드 목록 — 정렬은 데이터 완전성만(감축 실적 기반 금지, 원칙7). */
export function getKTaxonomyLeads(): Promise<KTaxonomyLeadItem[]> {
  return apiGet<{ leads: KTaxonomyLeadItem[] }>("/admin/k-taxonomy-leads").then((r) => r.leads);
}

/** 원본문서 접근 감사 로그 — 열람 이벤트 자체의 기록(review-log와 다른 축). */
export function getDocumentAccessLog(): Promise<DocumentAccessLogEntry[]> {
  return apiGet<{ entries: DocumentAccessLogEntry[] }>("/admin/documents/access-log").then(
    (r) => r.entries,
  );
}

/** 품질 이슈 로그(열람 전용) — 업로드 반려·실패 이력만 모은다(v1 Tier 2). */
export function getQualityIssues(): Promise<QualityIssueEntry[]> {
  return apiGet<{ issues: QualityIssueEntry[] }>("/admin/quality-issues").then((r) => r.issues);
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
