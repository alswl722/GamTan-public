"use client";

// 실API: GET /admin/companies/{id}/overview (등급·결손·HITL대기·최근알림)
//
// 기업 하나를 골라 "이 기업이 뭘 했고 뭐가 있고 없는지"를 한 화면에서 보는 탭.
// 항목 종류별로 흩어진 다른 탭(변경 이력·문서 열람·실행 이력)을 company_id
// 하나로 필터해 여기서 다시 모아 보여준다 — 각 데이터의 정본은 여전히 그
// 탭들이고, 여기서는 계산 로직을 새로 만들지 않는다.

import { useEffect, useState } from "react";
import { getCompanyOverview } from "@/lib/admin-data";
import type { Company, CompanyOverview, TraceRunItem } from "@/lib/admin-types";
import { gradeColor } from "@/lib/grade-colors";
import { AlertsPanel } from "@/components/admin/AlertsPanel";
import { AuditLog } from "@/components/admin/AuditLog";
import { DocumentAccessLog } from "@/components/admin/DocumentAccessLog";
import { TraceHistory } from "@/components/admin/TraceHistory";

function OverviewCard({ overview }: { overview: CompanyOverview }) {
  const gapCount = overview.coverage.gaps.length;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
      <div className="rounded-md border border-line bg-surface p-4">
        <p className="text-[11px] text-faint">PCAF 등급</p>
        <div className="mt-1.5 flex items-center gap-2">
          <span
            className="rounded-full px-2.5 py-1 text-[13px] font-bold text-white"
            style={{ backgroundColor: gradeColor(overview.grade) }}
          >
            {overview.grade}등급
          </span>
          {!overview.measured && (
            <span className="text-[10px] text-faint">매출 추정</span>
          )}
        </div>
      </div>
      <div className="rounded-md border border-line bg-surface p-4">
        <p className="text-[11px] text-faint">Scope1 / Scope2</p>
        <p className="mt-1.5 text-sm font-semibold text-ink">
          {overview.scope1.toLocaleString()} / {overview.scope2.toLocaleString()} tCO2e
        </p>
      </div>
      <div className="rounded-md border border-line bg-surface p-4">
        <p className="text-[11px] text-faint">검토 대기(HITL)</p>
        <p className="mt-1.5 text-sm font-semibold text-ink">
          {overview.hitl_count > 0 ? (
            <span className="text-hitl-ink">{overview.hitl_count}건</span>
          ) : (
            "없음"
          )}
        </p>
      </div>
      <div className="rounded-md border border-line bg-surface p-4">
        <p className="text-[11px] text-faint">데이터 결손</p>
        <p className="mt-1.5 text-sm font-semibold text-ink">
          {gapCount > 0 ? <span className="text-hitl-ink">{gapCount}개 연료</span> : "없음"}
        </p>
      </div>
    </div>
  );
}

function CoverageGaps({ overview }: { overview: CompanyOverview }) {
  const { gaps } = overview.coverage;
  return (
    <div className="rounded-md border border-line bg-surface p-4">
      <h3 className="text-xs font-semibold text-ink">데이터 결손 — 연료별 미연동 월</h3>
      {gaps.length === 0 ? (
        <p className="mt-2 text-xs text-faint">결손 없음 — 전 연료 12개월 데이터 확보</p>
      ) : (
        <div className="mt-2 space-y-1.5">
          {gaps.map((g) => (
            <div key={g.fuel} className="flex items-center gap-2 text-xs">
              <span className="rounded border border-line bg-bg px-1.5 py-0.5 font-medium text-muted">
                {g.fuel}
              </span>
              <span className="text-faint">
                {g.missing_months.map((m) => `${m}월`).join(", ")} 없음
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CompanyDetail({
  companies,
  traceRuns,
}: {
  companies: Company[];
  traceRuns: TraceRunItem[];
}) {
  const [companyId, setCompanyId] = useState<number | "">("");
  const [overview, setOverview] = useState<CompanyOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (companyId === "") {
      setOverview(null);
      return;
    }
    setLoading(true);
    setError(null);
    getCompanyOverview(companyId)
      .then(setOverview)
      .catch((err) => {
        console.error("기업 상세 조회 실패:", err);
        setError("조회에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      })
      .finally(() => setLoading(false));
  }, [companyId]);

  const selectedCompanyName =
    companyId === "" ? undefined : companies.find((c) => c.company_id === companyId)?.company_name;
  const companyTraceRuns =
    companyId === "" ? [] : traceRuns.filter((r) => r.company_id === companyId);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b border-line bg-surface px-6 py-4">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-ink">기업 상세</h2>
          <select
            value={companyId}
            onChange={(e) => setCompanyId(e.target.value ? Number(e.target.value) : "")}
            className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-muted focus:outline-none focus:ring-1 focus:ring-brand"
          >
            <option value="">기업 선택</option>
            {companies.map((c) => (
              <option key={c.company_id} value={c.company_id}>
                {c.company_name}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-1 text-xs text-faint">
          기업을 선택하면 등급·결손·검토 대기·알림·실행 이력·변경 이력을 한 화면에서 볼 수 있습니다
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {companyId === "" ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            기업을 선택하세요
          </div>
        ) : error ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-faint">
            <span className="text-hitl-ink">{error}</span>
          </div>
        ) : loading || !overview ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            불러오는 중…
          </div>
        ) : (
          <div className="space-y-5">
            <OverviewCard overview={overview} />

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              <CoverageGaps overview={overview} />
              <div className="h-64">
                <AlertsPanel alerts={overview.alerts} />
              </div>
            </div>

            <div className="h-96">
              <TraceHistory runs={companyTraceRuns} />
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              <div className="h-96">
                <AuditLog companyName={selectedCompanyName} />
              </div>
              <div className="h-96">
                <DocumentAccessLog companyName={selectedCompanyName} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
