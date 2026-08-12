"use client";

// 실API: GET /admin/quality-issues
//
// 업로드 반려·실패 이력만 모은 열람 전용 로그(v1 Tier 2, owner-admin-flow-spec.md §7).
// 성공한 업로드는 여기 안 남는다 — SourceDocument로 이미 기록되므로.

import type { QualityIssueEntry } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";

const DOCUMENT_TYPE_LABEL: Record<string, string> = {
  tax_invoice: "세금계산서",
  electric_bill: "전기고지서",
  gas_bill: "도시가스고지서",
};

const FAILURE_REASON_CLS: Record<QualityIssueEntry["failure_reason"], string> = {
  duplicate: "bg-bg text-muted border-line",
  missing_institution: "bg-hitl/20 text-hitl-ink border-hitl/40",
  excel_format: "bg-hitl/20 text-hitl-ink border-hitl/40",
  parse_error: "bg-hitl/20 text-hitl-ink border-hitl/40",
};

export function QualityIssueLog({ issues }: { issues: QualityIssueEntry[] }) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="border-b border-line px-6 py-4">
        <h2 className="text-base font-semibold text-ink">품질 이슈 로그</h2>
        <p className="mt-0.5 text-xs text-faint">
          업로드 반려·실패 이력 {issues.length}건 — 열람 전용, 최근 순
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {issues.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            반려·실패 이력 없음
          </div>
        ) : (
          issues.map((issue) => (
            <div key={issue.id} className="border-b border-line px-5 py-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-[10px] font-bold",
                      FAILURE_REASON_CLS[issue.failure_reason],
                    )}
                  >
                    {issue.failure_reason_label}
                  </span>
                  <span className="truncate text-sm font-semibold text-ink">
                    {issue.company_name}
                  </span>
                  {issue.document_type && (
                    <span className="rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
                      {DOCUMENT_TYPE_LABEL[issue.document_type] ?? issue.document_type}
                    </span>
                  )}
                </div>
                <span className="flex-shrink-0 text-xs tabular-nums text-faint">
                  <DateText iso={issue.created_at} opts={{ dateStyle: "short", timeStyle: "short" }} />
                </span>
              </div>
              <p className="truncate text-xs text-faint">
                {issue.original_filename ?? "파일명 없음"} · {issue.detail}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
