"use client";

import { useState } from "react";
import type {
  AlertItem,
  DocumentAccessLogEntry,
  HitlItem,
  KTaxonomyLeadItem,
  PortfolioResponse,
  QualityIssueEntry,
  ReviewLogEntry,
  TraceRunItem,
} from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { AlertsPanel } from "@/components/admin/AlertsPanel";
import { AuditLog } from "@/components/admin/AuditLog";
import { AuditPackage } from "@/components/admin/AuditPackage";
import { DocumentAccessLog } from "@/components/admin/DocumentAccessLog";
import { GradeDonut } from "@/components/admin/GradeDonut";
import { HitlWorkspace } from "@/components/admin/HitlWorkspace";
import { KTaxonomyLeads } from "@/components/admin/KTaxonomyLeads";
import { QualityIssueLog } from "@/components/admin/QualityIssueLog";
import { TraceHistory } from "@/components/admin/TraceHistory";
import { VerificationBadge } from "@/components/admin/VerificationBadge";

const TABS = [
  { id: "hitl", label: "담당자 검토" },
  { id: "grades", label: "등급 분포" },
  { id: "risk", label: "여신 리스크" },
  { id: "k-taxonomy", label: "K택소노미 리드" },
  { id: "trace", label: "실행 이력" },
  { id: "audit", label: "변경 이력" },
  { id: "quality-issues", label: "품질 이슈" },
  { id: "audit-package", label: "감사 대응" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export interface DashboardShellProps {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
  reviewLog: ReviewLogEntry[];
  alerts: AlertItem[];
  documentAccessLog: DocumentAccessLogEntry[];
  qualityIssues: QualityIssueEntry[];
  kTaxonomyLeads: KTaxonomyLeadItem[];
  /** 담당자 검토 탭에서 확정/반려가 성공할 때마다 호출 — 변경 이력을 최신으로 다시 불러온다. */
  onReviewed?: () => void;
}

export function DashboardShell({
  portfolio,
  hitlQueue,
  traceRuns,
  reviewLog,
  alerts,
  documentAccessLog,
  qualityIssues,
  kTaxonomyLeads,
  onReviewed,
}: DashboardShellProps) {
  const [activeTab, setActiveTab] = useState<TabId>("hitl");

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
          <div className="h-full p-5">
            <AlertsPanel alerts={alerts} />
          </div>
        )}

        {activeTab === "k-taxonomy" && (
          <div className="h-full p-4">
            <KTaxonomyLeads leads={kTaxonomyLeads} />
          </div>
        )}

        {activeTab === "trace" && (
          <div className="h-full p-4">
            <TraceHistory runs={traceRuns} />
          </div>
        )}

        {activeTab === "audit" && (
          <div className="grid h-full grid-cols-1 gap-5 overflow-hidden p-5 lg:grid-cols-2">
            <div className="min-h-0">
              <AuditLog entries={reviewLog} />
            </div>
            <div className="min-h-0">
              <DocumentAccessLog entries={documentAccessLog} />
            </div>
          </div>
        )}

        {activeTab === "quality-issues" && (
          <div className="h-full p-4">
            <QualityIssueLog issues={qualityIssues} />
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
