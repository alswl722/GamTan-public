"use client";

// 실API: GET /admin/companies/{id}/overview (등급·결손·HITL대기·최근알림)
//
// 기업 하나를 골라 "이 기업이 뭘 했고 뭐가 있고 없는지"를 한 화면에서 보는 탭.
// 항목 종류별로 흩어진 다른 탭(변경 이력·문서 열람·실행 이력)을 company_id
// 하나로 필터해 여기서 다시 모아 보여준다 — 각 데이터의 정본은 여전히 그
// 탭들이고, 여기서는 계산 로직을 새로 만들지 않는다.

import { useEffect, useState } from "react";
import { getCompanyOverview, sendClassificationsToOwner } from "@/lib/admin-data";
import type { Company, CompanyOverview, TraceRunItem } from "@/lib/admin-types";
import { gradeColor } from "@/lib/grade-colors";
import { AlertsPanel } from "@/components/admin/AlertsPanel";
import { AuditLog } from "@/components/admin/AuditLog";
import { CompanyCombobox } from "@/components/admin/CompanyCombobox";
import { CompanyTable } from "@/components/admin/CompanyTable";
import { DocumentAccessLog } from "@/components/admin/DocumentAccessLog";
import { TraceHistory } from "@/components/admin/TraceHistory";

function OverviewCard({
  overview,
  onSend,
  sending,
}: {
  overview: CompanyOverview;
  onSend: () => void;
  sending: boolean;
}) {
  const gapCount = overview.coverage.gaps.length;
  const pendingSend = overview.pending_send_count;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-5">
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
          {overview.scope1.toLocaleString()} /{" "}
          {overview.scope2.toLocaleString()} tCO2e
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
          {gapCount > 0 ? (
            <span className="text-hitl-ink">{gapCount}개 연료</span>
          ) : (
            "없음"
          )}
        </p>
      </div>
      <div
        className={
          pendingSend > 0
            ? "rounded-md border border-brand/40 bg-brand-soft p-4"
            : "rounded-md border border-line bg-surface p-4"
        }
      >
        <p className="text-[11px] text-faint">확정·전송 대기</p>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="text-sm font-semibold text-ink">
            {pendingSend > 0 ? `${pendingSend}건` : "없음"}
          </span>
          {pendingSend > 0 && (
            <button
              type="button"
              onClick={onSend}
              disabled={sending}
              className="rounded-md bg-brand px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-brand-ink disabled:opacity-50"
            >
              {sending ? "전송 중…" : "사장님께 전송"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function CoverageGaps({ overview }: { overview: CompanyOverview }) {
  const { gaps } = overview.coverage;
  return (
    <div className="rounded-md border border-line bg-surface p-4">
      <h3 className="text-xs font-semibold text-ink">
        데이터 결손 — 연료별 미연동 월
      </h3>
      {gaps.length === 0 ? (
        <p className="mt-2 text-xs text-faint">
          결손 없음 — 전 연료 12개월 데이터 확보
        </p>
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
  const [sending, setSending] = useState(false);

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

  async function handleSend() {
    if (companyId === "") return;
    setSending(true);
    try {
      await sendClassificationsToOwner(companyId);
      const fresh = await getCompanyOverview(companyId);
      setOverview(fresh);
    } catch (err) {
      console.error("전송 실패:", err);
      setError("전송에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSending(false);
    }
  }

  const companyTraceRuns =
    companyId === "" ? [] : traceRuns.filter((r) => r.company_id === companyId);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b border-line bg-surface px-6 py-4">
        <div className="flex items-center gap-2">
          {companyId !== "" && (
            <button
              type="button"
              onClick={() => setCompanyId("")}
              className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-muted transition-colors hover:text-ink"
            >
              ← 목록으로
            </button>
          )}
          <CompanyCombobox
            companies={companies}
            value={companyId}
            onChange={setCompanyId}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {companyId === "" ? (
          <CompanyTable companies={companies} onSelect={setCompanyId} />
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
            <OverviewCard overview={overview} onSend={handleSend} sending={sending} />

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
                <AuditLog companyId={overview.company_id} />
              </div>
              <div className="h-96">
                <DocumentAccessLog companyId={overview.company_id} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
