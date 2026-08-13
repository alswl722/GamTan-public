"use client";

import { useState } from "react";
import type { HitlItem, PortfolioResponse, TraceRunItem } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { AuditLog } from "@/components/admin/AuditLog";
import { AuditPackage } from "@/components/admin/AuditPackage";
import { CompanyDetail } from "@/components/admin/CompanyDetail";
import { DocumentAccessLog } from "@/components/admin/DocumentAccessLog";
import { HitlWorkspace } from "@/components/admin/HitlWorkspace";
import { TraceHistory } from "@/components/admin/TraceHistory";

const TABS = [
  { id: "hitl", label: "담당자 검토" },
  { id: "company", label: "기업" },
  { id: "trace", label: "실행 이력" },
  { id: "audit", label: "변경 이력" },
  { id: "audit-package", label: "감사 대응" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export interface DashboardShellProps {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
}

export function DashboardShell({ portfolio, hitlQueue, traceRuns }: DashboardShellProps) {
  const [activeTab, setActiveTab] = useState<TabId>("hitl");
  // AuditLog는 자체 서버사이드 페이지네이션으로 데이터를 관리해 부모가 직접 갱신할 수
  // 없다 — HITL 확정/반려 직후 최신 변경 이력을 보여주려면 key를 바꿔 리마운트한다.
  const [auditRefreshKey, setAuditRefreshKey] = useState(0);

  return (
    // 루트 레이아웃에 이미 h-16 헤더가 있으므로 그만큼 뺀 높이로 고정 — 페이지 스크롤 없음
    <div className="flex h-[calc(100vh-4rem)] flex-col overflow-hidden bg-bg">
      {/* 고정 헤더: 탭 바 */}
      <div className="flex-shrink-0 bg-surface">
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
            <HitlWorkspace
              initialQueue={hitlQueue}
              onChanged={() => setAuditRefreshKey((k) => k + 1)}
            />
          </div>
        )}

        {activeTab === "company" && (
          <CompanyDetail companies={portfolio.companies} traceRuns={traceRuns} />
        )}

        {activeTab === "trace" && (
          <div className="h-full p-4">
            <TraceHistory runs={traceRuns} />
          </div>
        )}

        {activeTab === "audit" && (
          <div className="grid h-full grid-cols-1 gap-5 overflow-hidden p-5 lg:grid-cols-2">
            <div className="min-h-0">
              <AuditLog key={auditRefreshKey} />
            </div>
            <div className="min-h-0">
              <DocumentAccessLog />
            </div>
          </div>
        )}

        {activeTab === "audit-package" && (
          <div className="h-full p-4">
            <AuditPackage companies={portfolio.companies} />
          </div>
        )}
      </div>
    </div>
  );
}
