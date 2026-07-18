"use client";

import { useState } from "react";
import { MOCK_ALERTS, MOCK_RATE_CANDIDATES } from "@/lib/admin-data";
import type { HitlItem, PortfolioResponse, TraceRunItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { AlertsPanel } from "@/components/admin/AlertsPanel";
import { GradeDonut } from "@/components/admin/GradeDonut";
import { HitlWorkspace } from "@/components/admin/HitlWorkspace";
import { RateCandidates } from "@/components/admin/RateCandidates";
import { TraceHistory } from "@/components/admin/TraceHistory";
import { VerificationBadge } from "@/components/admin/VerificationBadge";

const TABS = [
  { id: "hitl", label: "담당자 검토" },
  { id: "grades", label: "등급 분포" },
  { id: "risk", label: "여신 리스크" },
  { id: "trace", label: "실행 이력" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export interface DashboardShellProps {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
}

/** 상단 KPI 스트립 — 한 줄, 헤더에 고정. */
function KpiStripCompact({ data }: { data: PortfolioResponse }) {
  const fmt = (n: number) => n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  const items = [
    { label: "Scope 1", value: fmt(data.scope1_total), unit: "tCO₂e" },
    { label: "Scope 2", value: fmt(data.scope2_total), unit: "tCO₂e" },
    { label: "합계", value: fmt(data.total), unit: "tCO₂e", accent: true },
    { label: "PCAF 가중평균 등급", value: data.avg_grade != null ? `${data.avg_grade}등급` : "—", unit: "" },
    { label: "실측 커버리지", value: `${data.measured_coverage_pct}%`, unit: "" },
    { label: "검토 대기", value: String(data.hitl_total), unit: "건", accent: true },
  ];

  return (
    <div className="-mx-1 flex flex-wrap items-center gap-y-2 divide-x divide-[#e8eaed]">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline gap-1.5 px-4 first:pl-0">
          <span className="whitespace-nowrap text-xs text-[#9ca3af]">{item.label}</span>
          <span
            className={cn(
              "text-sm font-bold tabular-nums",
              item.accent ? "text-[#00967f]" : "text-[#222222]",
            )}
          >
            {item.value}
          </span>
          {item.unit && <span className="text-[11px] text-[#9ca3af]">{item.unit}</span>}
        </div>
      ))}
    </div>
  );
}

export function DashboardShell({ portfolio, hitlQueue, traceRuns }: DashboardShellProps) {
  const [activeTab, setActiveTab] = useState<TabId>("hitl");

  return (
    // 루트 레이아웃에 이미 h-16 헤더가 있으므로 그만큼 뺀 높이로 고정 — 페이지 스크롤 없음
    <div className="flex h-[calc(100vh-4rem)] flex-col overflow-hidden bg-[#f7f8fa]">
      {/* 고정 헤더: KPI 스트립 + 탭 바 */}
      <div className="flex-shrink-0 bg-white">
        <div className="border-b border-[#e8eaed] px-6 py-3">
          <KpiStripCompact data={portfolio} />
        </div>
        <div className="flex h-11 items-end gap-1 border-b border-[#e8eaed] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "relative h-11 whitespace-nowrap px-5 text-sm font-medium transition-colors focus:outline-none",
                activeTab === tab.id ? "text-[#00967f]" : "text-[#666666] hover:text-[#222222]",
              )}
            >
              {tab.label}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full bg-[#00c7a9]" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 탭 본문 — 남은 높이를 채움 */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "hitl" && (
          <div className="h-full p-4">
            <HitlWorkspace initialQueue={hitlQueue} />
          </div>
        )}

        {activeTab === "grades" && (
          <div className="grid h-full grid-cols-1 items-stretch gap-5 overflow-y-auto p-5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <GradeDonut data={portfolio} />
            </div>
            <div className="lg:col-span-1">
              <VerificationBadge />
            </div>
          </div>
        )}

        {activeTab === "risk" && (
          <div className="grid h-full grid-cols-1 gap-5 overflow-hidden p-5 lg:grid-cols-2">
            <div className="min-h-0">
              <AlertsPanel alerts={MOCK_ALERTS} />
            </div>
            <div className="min-h-0">
              <RateCandidates candidates={MOCK_RATE_CANDIDATES} />
            </div>
          </div>
        )}

        {activeTab === "trace" && (
          <div className="h-full p-4">
            <TraceHistory runs={traceRuns} />
          </div>
        )}
      </div>
    </div>
  );
}
