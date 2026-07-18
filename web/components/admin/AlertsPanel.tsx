"use client";

// 목업: GET /admin/alerts (예시 — 결선 확장)

import type { AlertItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

const SEVERITY_MAP = {
  high: { label: "긴급", cls: "bg-red-50 text-red-600 border-red-200" },
  medium: { label: "주의", cls: "bg-amber-50 text-amber-600 border-amber-200" },
  low: { label: "정보", cls: "bg-slate-50 text-slate-500 border-slate-200" },
};

export function AlertsPanel({ alerts }: { alerts: AlertItem[] }) {
  return (
    <div className="flex h-full flex-col rounded-2xl border border-[#e8eaed] bg-white shadow-card">
      <div className="flex items-center justify-between border-b border-[#e8eaed] px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-[#222222]">이상 신호 알림</h2>
          <p className="mt-0.5 text-xs text-[#9ca3af]">여신 리스크 조기 경보</p>
        </div>
        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-600">
          예시 · 결선 확장
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-[#e8eaed] overflow-y-auto">
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
                <span className="text-xs font-semibold text-[#222222]">{a.company_name}</span>
                <span className="ml-1.5 text-xs leading-relaxed text-[#666666]">{a.message}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="border-t border-[#e8eaed] bg-amber-50/30 px-5 py-3">
        <p className="text-[11px] text-[#9ca3af]">
          예시 데이터입니다. 실제 엔드포인트{" "}
          <code className="rounded bg-slate-100 px-1 font-mono">GET /admin/alerts</code> 연결 후 반영됩니다.
        </p>
      </div>
    </div>
  );
}
