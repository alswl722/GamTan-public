"use client";

// 실API: GET /admin/quality-issues (page/page_size/company_name 서버사이드 페이지네이션)
//
// 업로드 반려·실패 이력만 모은 열람 전용 로그(v1 Tier 2, owner-admin-flow-spec.md §7).
// 성공한 업로드는 여기 안 남는다 — SourceDocument로 이미 기록되므로.

import { getQualityIssues } from "@/lib/admin-data";
import type { QualityIssueEntry } from "@/lib/admin-types";
import { usePaginatedLog } from "@/lib/use-paginated-log";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";
import { PaginationBar } from "@/components/admin/PaginationBar";

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

const PAGE_SIZE = 50;

/** companyName을 넘기면 검색창 없이 그 기업으로 고정 필터한다 — 기업 상세 탭이 사용. */
export function QualityIssueLog({ companyName: fixedCompanyName }: { companyName?: string } = {}) {
  const { data, loading, error, page, setPage, searchInput, setSearchInput, retry } =
    usePaginatedLog<{ issues: QualityIssueEntry[] }>(getQualityIssues, PAGE_SIZE, fixedCompanyName);

  const issues = data?.issues ?? [];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-ink">품질 이슈 로그</h2>
          <p className="mt-0.5 text-xs text-faint">업로드 반려·실패 이력 — 열람 전용, 최근 순</p>
        </div>
        {fixedCompanyName === undefined && (
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="기업명 검색"
            className="w-40 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink placeholder:text-faint transition-colors focus:outline-none focus:ring-1 focus:ring-brand"
          />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {error ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-faint">
            <span className="text-hitl-ink">{error}</span>
            <button
              type="button"
              onClick={retry}
              className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink"
            >
              다시 시도
            </button>
          </div>
        ) : loading && !data ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            불러오는 중…
          </div>
        ) : issues.length === 0 ? (
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

      {data && data.total > 0 && (
        <PaginationBar total={data.total} page={page} pageSize={PAGE_SIZE} onChange={setPage} />
      )}
    </div>
  );
}
