/**
 * 관리자 대시보드 데이터 접근 — 백엔드 실제 응답(apiGet/apiPatch)만 다룬다.
 */
import { apiGet, apiPatch } from "@/lib/api";
import type {
  AlertItem,
  ClassificationEdit,
  HitlItem,
  PortfolioResponse,
  RateCandidateItem,
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

export function getRateCandidates(): Promise<RateCandidateItem[]> {
  return apiGet<{ candidates: RateCandidateItem[] }>("/admin/rate-candidates").then(
    (r) => r.candidates,
  );
}
