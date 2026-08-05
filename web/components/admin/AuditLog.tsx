"use client";

// 실API: GET /admin/review-log
// 별도 감사 테이블 없이 Classification.evidence 에 이미 누적된 담당자 조치 기록을 노출한다.

import { useMemo, useState } from "react";
import type { ReviewLogEntry } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";

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

export function AuditLog({ entries }: { entries: ReviewLogEntry[] }) {
  const [filterCompany, setFilterCompany] = useState("전체");
  const [filterStatus, setFilterStatus] = useState("전체");
  const [search, setSearch] = useState("");

  const companies = useMemo(
    () => ["전체", ...Array.from(new Set(entries.map((e) => e.company_name)))],
    [entries],
  );

  const filtered = useMemo(() => {
    let list = [...entries];
    if (filterCompany !== "전체") list = list.filter((e) => e.company_name === filterCompany);
    if (filterStatus !== "전체") list = list.filter((e) => e.status === filterStatus);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (e) => e.raw.toLowerCase().includes(q) || (e.evidence ?? "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [entries, filterCompany, filterStatus, search]);

  const selectCls =
    "rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-muted transition-colors focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div>
          <h2 className="text-base font-semibold text-ink">변경 이력</h2>
          <p className="mt-0.5 text-xs text-faint">
            담당자 확정·반려 조치 {entries.length}건 — 최근 조치순
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="전표·근거 검색"
            className="w-40 rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-ink placeholder:text-faint transition-colors focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <select className={selectCls} value={filterCompany} onChange={(e) => setFilterCompany(e.target.value)}>
            {companies.map((c) => (
              <option key={c} value={c}>
                {c === "전체" ? "기업 전체" : c}
              </option>
            ))}
          </select>
          <select className={selectCls} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="전체">상태 전체</option>
            <option value="confirmed">확정</option>
            <option value="rejected">반려</option>
          </select>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            조치 이력 없음
          </div>
        ) : (
          filtered.map((entry) => <LogRow key={entry.voucher_id} entry={entry} />)
        )}
      </div>
    </div>
  );
}
