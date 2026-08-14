"use client";

// 실API: GET /admin/review-log (page/page_size/company_name|company_id 서버사이드 페이지네이션)
// 별도 감사 테이블 없이 Classification.evidence 에 이미 누적된 담당자 조치 기록을 노출한다.

import { useMemo, useState } from "react";
import { getReviewLog } from "@/lib/admin-data";
import type { ReviewLogEntry } from "@/lib/admin-types";
import { usePaginatedLog } from "@/lib/use-paginated-log";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";
import { PaginationBar } from "@/components/admin/PaginationBar";

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  confirmed: { label: "확정", cls: "bg-brand-soft text-brand-ink border-brand/30" },
  rejected: { label: "반려", cls: "bg-hitl/20 text-hitl-ink border-hitl/40" },
};

/** evidence 문자열의 마지막 " | " 뒤를 "이번 조치 내용"으로, 그 앞을 원본 판단 근거로 분리. */
function splitEvidence(evidence: string | null): { original: string | null; action: string | null } {
  if (!evidence) return { original: null, action: null };
  const idx = evidence.lastIndexOf(" | ");
  if (idx === -1) return { original: null, action: evidence };
  return { original: evidence.slice(0, idx), action: evidence.slice(idx + 3) };
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? { label: status, cls: "bg-bg text-muted border-line" };
  return (
    <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-bold", s.cls)}>{s.label}</span>
  );
}

function LogRow({ entry }: { entry: ReviewLogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const { original, action } = splitEvidence(entry.evidence);

  return (
    <div className="border-b border-line px-5 py-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <StatusBadge status={entry.status} />
          <span className="truncate text-sm font-semibold text-ink">{entry.company_name}</span>
          <span className="text-xs text-faint">·</span>
          <span className="truncate text-xs text-faint">{entry.raw}</span>
        </div>
        <span className="flex-shrink-0 text-xs tabular-nums text-faint">
          <DateText iso={entry.reviewed_at} opts={{ dateStyle: "short", timeStyle: "short" }} />
        </span>
      </div>

      {action && <p className="text-xs leading-relaxed text-ink">{action}</p>}

      {original && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[11px] font-medium text-faint underline decoration-dotted hover:text-muted"
        >
          {expanded ? "원본 판단 근거 접기" : "원본 판단 근거 보기"}
        </button>
      )}
      {expanded && original && (
        <p className="mt-1 rounded bg-bg px-2.5 py-2 text-[11px] leading-relaxed text-muted">{original}</p>
      )}
    </div>
  );
}

const PAGE_SIZE = 50;

/** companyId를 넘기면 검색창 없이 그 기업(정확일치)으로 고정 필터한다 — 기업 상세 탭이 사용. */
export function AuditLog({ companyId: fixedCompanyId }: { companyId?: number } = {}) {
  const { data, loading, error, page, setPage, searchInput, setSearchInput, retry } =
    usePaginatedLog<{ entries: ReviewLogEntry[] }>(getReviewLog, PAGE_SIZE, fixedCompanyId);
  // 상태(확정/반려) 필터는 서버 파라미터로 넘기지 않고 현재 페이지 안에서만 적용한다 —
  // 기업명 검색(서버사이드)과 달리 필터 결과가 페이지 경계를 넘나들 필요가 적은 보조 필터.
  const [filterStatus, setFilterStatus] = useState("전체");

  const entries = data?.entries ?? [];
  const filtered = useMemo(
    () => (filterStatus === "전체" ? entries : entries.filter((e) => e.status === filterStatus)),
    [entries, filterStatus],
  );

  const selectCls =
    "rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-muted transition-colors focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <h2 className="text-base font-semibold text-ink">변경 이력</h2>
        <div className="flex flex-wrap items-center gap-2">
          {fixedCompanyId === undefined && (
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="기업명 검색"
              className="w-40 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink placeholder:text-faint transition-colors focus:outline-none focus:ring-1 focus:ring-brand"
            />
          )}
          <select className={selectCls} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="전체">상태 전체</option>
            <option value="confirmed">확정</option>
            <option value="rejected">반려</option>
          </select>
        </div>
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
        ) : filtered.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            조치 이력 없음
          </div>
        ) : (
          filtered.map((entry) => <LogRow key={entry.voucher_id} entry={entry} />)
        )}
      </div>

      {data && data.total > 0 && (
        <PaginationBar total={data.total} page={page} pageSize={PAGE_SIZE} onChange={setPage} />
      )}
    </div>
  );
}
