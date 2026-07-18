"use client";

// 목업: GET /admin/alerts (예시 — 결선 확장)

import type { AlertItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

const SEVERITY_MAP = {
  high: { label: "긴급", cls: "bg-hitl/20 text-hitl-ink border-hitl/40" },
  medium: { label: "주의", cls: "bg-bg text-muted border-line" },
  low: { label: "정보", cls: "bg-bg text-faint border-line" },
};

export function AlertsPanel({ alerts }: { alerts: AlertItem[] }) {
  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">이상 신호 알림</h2>
          <p className="mt-0.5 text-xs text-faint">여신 리스크 조기 경보</p>
        </div>
        <span className="rounded-full border border-line bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
          예시 · 결선 확장
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {alerts.map((a) => {
          const sev = SEVERITY_MAP[a.severity];
          return (
            <div key={a.id} className="flex items-start gap-3 px-5 py-3.5">
              <span
                className={cn(
                  "mt-0.5 flex-shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold",
                  sev.cls,
                )}
              >
                {sev.label}
              </span>
              <div className="min-w-0">
                <span className="text-xs font-semibold text-ink">{a.company_name}</span>
                <span className="ml-1.5 text-xs leading-relaxed text-muted">{a.message}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="border-t border-line bg-bg px-5 py-3">
        <p className="text-[11px] text-faint">
          예시 데이터입니다. 실제 엔드포인트{" "}
          <code className="rounded bg-line px-1 font-mono">GET /admin/alerts</code> 연결 후 반영됩니다.
        </p>
      </div>
    </div>
  );
}
