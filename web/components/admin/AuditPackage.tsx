"use client";

// 실API: GET /admin/audit-package?company_id=&year=&format=json|csv|pdf
//
// 기업·기간을 지정하면 trace_logs + classifications.evidence + 원본 전표를
// 시계열로 조회한다(v1 Tier 2, owner-admin-flow-spec.md §8). 신규 계산 로직 없음 —
// 기존 3개 테이블을 조인·정렬만 한다. CSV는 원자료 재검증용, PDF는 서술형 감사보고서
// (둘 다 재계산 없이 같은 원자료를 그대로 직렬화).

import { useState } from "react";
import { auditPackageCsvUrl, auditPackagePdfUrl } from "@/lib/admin-data";
import { apiGet } from "@/lib/api";
import type { Company } from "@/lib/admin-types";
import { CompanyCombobox } from "@/components/admin/CompanyCombobox";
import { CompanyTable } from "@/components/admin/CompanyTable";
import { YearDropdown } from "@/components/admin/YearDropdown";
import { splitEvidence } from "@/lib/evidence";

interface AuditEntry {
  entry_type: "voucher" | "trace";
  occurred_at: string | null;
  voucher_id?: number;
  month?: number;
  item_description?: string;
  supply_amount_krw?: number;
  scope?: number | null;
  fuel_type?: string | null;
  emission_co2e?: number | null;
  status?: string | null;
  evidence?: string | null;
  session_id?: string;
  step_type?: string;
  tool_name?: string | null;
  message?: string;
}

interface AuditPackageResponse {
  company_id: number;
  year: number;
  entry_count: number;
  entries: AuditEntry[];
}

function EntryRow({ entry }: { entry: AuditEntry }) {
  if (entry.entry_type === "trace") {
    return (
      <div className="border-b border-line px-5 py-3">
        <div className="mb-1 flex items-center gap-2">
          <span className="rounded border border-scope2/40 bg-scope2/15 px-1.5 py-0.5 text-[10px] font-medium text-ink">
            {entry.step_type}
          </span>
          <span className="text-xs text-faint">{entry.tool_name}</span>
        </div>
        <p className="text-xs text-ink">{entry.message}</p>
      </div>
    );
  }
  return (
    <div className="border-b border-line px-5 py-3">
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
          {entry.month}월 전표
        </span>
        {entry.status && (
          <span className="text-[10px] text-faint">{entry.status}</span>
        )}
      </div>
      <p className="text-xs text-ink">
        {entry.item_description} · {entry.supply_amount_krw?.toLocaleString("ko-KR")}원
        {entry.scope != null && ` · Scope${entry.scope}`}
        {entry.fuel_type && ` · ${entry.fuel_type}`}
      </p>
      <EvidenceBlock evidence={entry.evidence} />
    </div>
  );
}

/** 원본 AI 판단 근거와 담당자 조치를 구역을 나눠 보여준다 — 담당자 조치가 더
 * 눈에 띄도록 강조하고, 원본은 옆에 옅게 둔다(AuditLog.tsx와 동일한 시각 언어). */
function EvidenceBlock({ evidence }: { evidence: string | null | undefined }) {
  const { original, action } = splitEvidence(evidence);
  if (!original && !action) return null;

  return (
    <div className="mt-1.5 space-y-1">
      {original && (
        <div className="rounded border border-line bg-bg px-2 py-1.5">
          <span className="mr-1.5 text-[10px] font-semibold text-faint">AI 판단 근거</span>
          <span className="text-[11px] text-muted">{original}</span>
        </div>
      )}
      {action && (
        <div className="rounded border border-brand/30 bg-brand-soft px-2 py-1.5">
          <span className="mr-1.5 text-[10px] font-semibold text-brand-ink">담당자 조치</span>
          <span className="text-[11px] font-medium text-ink">{action}</span>
        </div>
      )}
    </div>
  );
}

export function AuditPackage({ companies }: { companies: Company[] }) {
  const [companyId, setCompanyId] = useState<number | "">("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [result, setResult] = useState<AuditPackageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (targetCompanyId: number | "" = companyId) => {
    if (targetCompanyId === "") return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiGet<AuditPackageResponse>(
        `/admin/audit-package?company_id=${targetCompanyId}&year=${year}`,
      );
      setResult(res);
    } catch (err) {
      console.error("감사 근거 패키지 조회 실패:", err);
      setError("조회에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const selectAndSearch = (id: number) => {
    setCompanyId(id);
    void search(id);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
      <div className="border-b border-line px-6 py-4">
        <h2 className="text-base font-semibold text-ink">감사 대응 근거 패키지</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {companyId !== "" && (
            <button
              type="button"
              onClick={() => {
                setCompanyId("");
                setResult(null);
              }}
              className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-muted transition-colors hover:text-ink"
            >
              ← 목록으로
            </button>
          )}
          <CompanyCombobox companies={companies} value={companyId} onChange={setCompanyId} />
          <YearDropdown value={year} onChange={setYear} />
          <button
            type="button"
            onClick={() => void search()}
            disabled={companyId === "" || busy}
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-ink disabled:opacity-50"
          >
            {busy ? "조회 중…" : "조회"}
          </button>
          {companyId !== "" && (
            <>
              <a
                href={auditPackageCsvUrl(companyId, year)}
                className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink"
              >
                CSV 내보내기
              </a>
              <a
                href={auditPackagePdfUrl(companyId, year)}
                className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink"
              >
                PDF 보고서
              </a>
            </>
          )}
        </div>
        {error && <p className="mt-2 text-[11px] text-hitl-ink">{error}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {companyId === "" ? (
          <div className="p-5">
            <CompanyTable companies={companies} onSelect={selectAndSearch} />
          </div>
        ) : result === null ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            {busy ? "조회 중…" : "조회 버튼을 눌러 근거를 불러오세요"}
          </div>
        ) : result.entry_count === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            해당 기간 근거 없음
          </div>
        ) : (
          result.entries.map((entry, i) => (
            <EntryRow key={`${entry.entry_type}-${i}`} entry={entry} />
          ))
        )}
      </div>
    </div>
  );
}
