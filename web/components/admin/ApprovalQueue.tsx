"use client";

// 실API: GET /admin/rate-requests → requests
// 실API: PATCH /admin/rate-requests/{id}/approve | /{id}/reject
//
// HITL 큐(분류 신뢰도, HitlWorkspace.tsx)와는 완전히 다른 데이터·화면이다(v1 §6 2주차).
// 여기서 다루는 "승인"도 여신 결정이 아니라 사장님이 요청한 우대금리·설비금융 안내를
// 은행 담당자가 "안내 대상으로 확인했다"는 수동 확인일 뿐이다(CLAUDE.md §9).

import { useState } from "react";
import { approveRateRequest, rejectRateRequest } from "@/lib/admin-data";
import type { RateApprovalRequestItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";
import { gradeColor } from "@/lib/grade-colors";

const REQUEST_TYPE_LABEL: Record<RateApprovalRequestItem["request_type"], string> = {
  rate_upgrade: "우대금리",
  equipment_finance: "설비금융",
};

const STATUS_LABEL: Record<RateApprovalRequestItem["status"], { label: string; cls: string }> = {
  pending: { label: "대기", cls: "bg-hitl/20 text-hitl-ink border-hitl/40" },
  approved: { label: "승인", cls: "bg-brand-soft text-brand-ink border-brand/30" },
  rejected: { label: "반려", cls: "bg-bg text-muted border-line" },
};

function RequestCard({
  item,
  onDecided,
}: {
  item: RateApprovalRequestItem;
  onDecided: (id: number, next: RateApprovalRequestItem) => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = STATUS_LABEL[item.status];

  const decide = async (action: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      const reviewer = "은행 담당자"; // 별도 로그인 체계 도입 전 임시 식별자(TODO: 인증 연동 시 교체)
      const next =
        action === "approve"
          ? await approveRateRequest(item.id, reviewer, note || undefined)
          : await rejectRateRequest(item.id, reviewer, note || undefined);
      onDecided(item.id, next);
    } catch (err) {
      console.error("승인요청 처리 실패:", err);
      setError("처리에 실패했습니다. 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="px-5 py-3.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-ink">{item.company_name}</span>
          <span className="rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
            {REQUEST_TYPE_LABEL[item.request_type]}
          </span>
        </div>
        <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-bold", status.cls)}>
          {status.label}
        </span>
      </div>

      {item.current_grade != null && item.target_grade != null && (
        <div className="mb-1.5 flex items-center gap-1.5">
          {item.scope_group && (
            <span className="rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
              {item.scope_group === "scope_1" ? "Scope 1" : "Scope 2"}
            </span>
          )}
          <span
            className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
            style={{ backgroundColor: gradeColor(item.current_grade) }}
          >
            {item.current_grade}등급
          </span>
          <span className="text-xs text-faint">→</span>
          <span
            className="rounded-full px-2 py-0.5 text-[11px] font-bold text-white"
            style={{ backgroundColor: gradeColor(item.target_grade) }}
          >
            {item.target_grade}등급
          </span>
        </div>
      )}

      {item.missing_summary && (
        <p className="mb-1 text-xs leading-relaxed text-muted">
          <span className="font-medium text-ink">필요 데이터:</span> {item.missing_summary}
        </p>
      )}

      <p className="mb-2 text-[11px] leading-relaxed text-faint">{item.disclaimer_text}</p>

      {item.status === "pending" ? (
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="비고(선택)"
            className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <button
            type="button"
            disabled={busy}
            onClick={() => decide("approve")}
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-ink disabled:opacity-50"
          >
            승인
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide("reject")}
            className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink disabled:opacity-50"
          >
            반려
          </button>
        </div>
      ) : (
        <div className="text-[11px] text-faint">
          {item.reviewed_by} ·{" "}
          <DateText iso={item.reviewed_at} opts={{ dateStyle: "short", timeStyle: "short" }} />
          {item.review_note && <span className="ml-1">· {item.review_note}</span>}
        </div>
      )}

      {error && <p className="mt-1.5 text-[11px] text-hitl-ink">{error}</p>}
    </div>
  );
}

export function ApprovalQueue({ requests: initial }: { requests: RateApprovalRequestItem[] }) {
  const [requests, setRequests] = useState(initial);

  const handleDecided = (id: number, next: RateApprovalRequestItem) => {
    setRequests((prev) => prev.map((r) => (r.id === id ? next : r)));
  };

  const pendingCount = requests.filter((r) => r.status === "pending").length;

  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">승인요청 큐</h2>
          <p className="mt-0.5 text-xs text-faint">
            사장님이 요청한 우대금리·설비금융 안내 — 여신 결정 아님, 안내 대상 확인용
          </p>
        </div>
        <span className="rounded-full border border-line bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
          대기 {pendingCount}건
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {requests.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            승인요청 없음
          </div>
        ) : (
          requests.map((r) => <RequestCard key={r.id} item={r} onDecided={handleDecided} />)
        )}
      </div>
    </div>
  );
}
