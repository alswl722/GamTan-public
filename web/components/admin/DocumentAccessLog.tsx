"use client";

// 실API: GET /admin/documents/access-log (page/page_size/company_name 서버사이드 페이지네이션)
//
// 기존 AuditLog(review-log)는 "분류를 확정/반려했다"는 조치 기록이지 "원본문서를
// 열어봤다"는 열람 기록이 아니다(v1 §6 2주차) — 별도 화면으로 분리한다.

import { getDocumentAccessLog } from "@/lib/admin-data";
import type { DocumentAccessLogEntry } from "@/lib/admin-types";
import { usePaginatedLog } from "@/lib/use-paginated-log";
import { DateText } from "@/lib/use-formatted-date";
import { PaginationBar } from "@/components/admin/PaginationBar";

const DOCUMENT_TYPE_LABEL: Record<string, string> = {
  tax_invoice: "세금계산서",
  electric_bill: "전기고지서",
  gas_bill: "도시가스고지서",
};

const PAGE_SIZE = 50;

/** companyName을 넘기면 검색창 없이 그 기업으로 고정 필터한다 — 기업 상세 탭이 사용. */
export function DocumentAccessLog({
  companyName: fixedCompanyName,
}: { companyName?: string } = {}) {
  const { data, loading, error, page, setPage, searchInput, setSearchInput, retry } =
    usePaginatedLog<{ entries: DocumentAccessLogEntry[] }>(
      getDocumentAccessLog,
      PAGE_SIZE,
      fixedCompanyName,
    );

  const entries = data?.entries ?? [];

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-ink">원본문서 접근 로그</h2>
          <p className="mt-0.5 text-xs text-faint">담당자가 원본 증빙을 열람한 이력 — 최근 순</p>
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
        ) : entries.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            열람 이력 없음
          </div>
        ) : (
          entries.map((entry) => (
            <div key={entry.log_id} className="border-b border-line px-5 py-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
                    {DOCUMENT_TYPE_LABEL[entry.document_type] ?? entry.document_type}
                  </span>
                  <span className="truncate text-sm font-semibold text-ink">
                    {entry.company_name}
                  </span>
                </div>
                <span className="flex-shrink-0 text-xs tabular-nums text-faint">
                  <DateText iso={entry.accessed_at} opts={{ dateStyle: "short", timeStyle: "short" }} />
                </span>
              </div>
              <p className="truncate text-xs text-faint">
                {entry.original_filename ?? `문서 #${entry.source_document_id}`} · 열람자{" "}
                {entry.accessed_by}
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
