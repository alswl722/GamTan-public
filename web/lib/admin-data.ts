/**
 * 관리자 대시보드 데이터 접근 — 백엔드 실제 응답(apiGet/apiPatch)만 다룬다.
 */
import { apiGet, apiPatch, apiPost, BASE_URL } from "@/lib/api";
import type {
  BulkActionResult,
  ClassificationEdit,
  ClimateRiskReport,
  CompanyOverview,
  DocumentAccessLogEntry,
  HitlItem,
  PageMeta,
  PortfolioResponse,
  ReviewLogEntry,
  TraceRunItem,
  TraceStep,
} from "@/lib/admin-types";

/** 서버사이드 페이지네이션 요청 공통 파라미터 — review-log/access-log 공유.
 * companyId(정확일치)와 companyName(부분일치 검색)은 동시에 넘기지 않는다 —
 * "기업" 탭은 companyId로 정확히 좁히고, "변경 이력" 탭 검색창은 companyName을 쓴다. */
export interface PageParams {
  page?: number;
  pageSize?: number;
  companyName?: string;
  companyId?: number;
}

function pageQuery({ page = 1, pageSize = 50, companyName, companyId }: PageParams): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (companyId != null) params.set("company_id", String(companyId));
  else if (companyName?.trim()) params.set("company_name", companyName.trim());
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

/** 확정(저장)된 건을 모아 사장님 화면에 한 번에 전송 — 확정 자체는 이 액션과 무관하게
 * 언제든 저장되지만, 이 버튼을 눌러야 그 시점까지 확정된 건이 사장님에게 보인다. */
export function sendClassificationsToOwner(
  companyId: number,
): Promise<{ company_id: number; sent_count: number; sent_at: string }> {
  return apiPost(`/admin/companies/${companyId}/send-classifications`);
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

/** 기후리스크 리포트 — portfolio_summary()를 금감원 4단계 구조로 재배열(재계산 없음). */
export function getClimateRiskReport(): Promise<ClimateRiskReport> {
  return apiGet("/admin/climate-risk-report");
}

/** 기후리스크 리포트 PDF 내보내기 URL — 다운로드 링크로 그대로 사용. */
export function climateRiskReportPdfUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/admin/climate-risk-report?format=pdf`;
}
