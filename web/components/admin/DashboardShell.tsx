"use client";

import { useState } from "react";
import { MOCK_RATE_CANDIDATES } from "@/lib/admin-data";
import type {
  AlertItem,
  HitlItem,
  PortfolioResponse,
  ReviewLogEntry,
  TraceRunItem,
} from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { AlertsPanel } from "@/components/admin/AlertsPanel";
import { AuditLog } from "@/components/admin/AuditLog";
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
  { id: "audit", label: "변경 이력" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export interface DashboardShellProps {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
  reviewLog: ReviewLogEntry[];
  alerts: AlertItem[];
  /** 담당자 검토 탭에서 확정/반려가 성공할 때마다 호출 — 변경 이력을 최신으로 다시 불러온다. */
  onReviewed?: () => void;
}

/** 상단 KPI 스트립 — 한 줄, 헤더에 고정. */
function KpiStripCompact({ data, onReviewClick }: { data: PortfolioResponse; onReviewClick: () => void }) {
  const fmt = (n: number) => n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  const items = [
    { label: "Scope 1", value: fmt(data.scope1_total), unit: "tCO₂e" },
    { label: "Scope 2", value: fmt(data.scope2_total), unit: "tCO₂e" },
    { label: "합계", value: fmt(data.total), unit: "tCO₂e", accent: true },
    { label: "PCAF 가중평균 등급", value: data.avg_grade != null ? `${data.avg_grade}등급` : "—", unit: "" },
    { label: "실측 커버리지", value: `${data.measured_coverage_pct}%`, unit: "" },
  ];

  return (
    <div className="-mx-1 flex flex-wrap items-start gap-y-3 divide-x divide-line">
      {items.map((item) => (
        <div key={item.label} className="flex flex-col gap-0.5 px-4 first:pl-0">
          <span className="whitespace-nowrap text-xs text-faint">{item.label}</span>
          <span className="flex items-baseline gap-1">
            <span
              className={cn(
                "text-base font-bold leading-none tabular-nums",
                item.accent ? "text-brand-ink" : "text-ink",
              )}
            >
              {item.value}
            </span>
            {item.unit && <span className="text-xs text-faint">{item.unit}</span>}
          </span>
        </div>
      ))}

      <button type="button" onClick={onReviewClick} className="flex flex-col gap-0.5 px-4 text-left">
        <span className="whitespace-nowrap text-xs text-hitl-ink">검토 대기</span>
        <span className="flex items-baseline gap-1">
          <span className="text-base font-bold leading-none tabular-nums text-hitl-ink underline decoration-hitl-ink/40 underline-offset-4">
            {data.hitl_total}
          </span>
          <span className="text-xs text-faint">건</span>
        </span>
      </button>
    </div>
  );
}

export function DashboardShell({
  portfolio,
  hitlQueue,
  traceRuns,
  reviewLog,
  alerts,
  onReviewed,
}: DashboardShellProps) {
  const [activeTab, setActiveTab] = useState<TabId>("hitl");

  return (
    // 루트 레이아웃에 이미 h-16 헤더가 있으므로 그만큼 뺀 높이로 고정 — 페이지 스크롤 없음
    <div className="flex h-[calc(100vh-4rem)] flex-col overflow-hidden bg-bg">
      {/* 고정 헤더: KPI 스트립 + 탭 바 */}
      <div className="flex-shrink-0 bg-surface">
        <div className="border-b border-line px-6 py-3">
          <KpiStripCompact data={portfolio} onReviewClick={() => setActiveTab("hitl")} />
        </div>
        <div className="flex h-11 items-end gap-1 border-b border-line px-6">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "relative h-11 whitespace-nowrap px-5 text-sm font-medium transition-colors focus:outline-none",
                activeTab === tab.id ? "text-brand-ink" : "text-muted hover:text-ink",
              )}
            >
              {tab.label}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full bg-brand" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 탭 본문 — 남은 높이를 채움 */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "hitl" && (
          <div className="h-full p-4">
            <HitlWorkspace initialQueue={hitlQueue} onChanged={onReviewed} />
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
              <AlertsPanel alerts={alerts} />
            </div>
            <div className="min-h-0">
              <RateCandidates candidates={rateCandidates} />
            </div>
          </div>
        )}

        {activeTab === "trace" && (
          <div className="h-full p-4">
            <TraceHistory runs={traceRuns} />
          </div>
        )}

        {activeTab === "audit" && (
          <div className="h-full p-4">
            <AuditLog entries={reviewLog} />
          </div>
        )}
      </div>
    </div>
  );
}
