"use client";

// 실API: GET /admin/portfolio → companies (같은 응답 안의 기업별 내역)

import type { Company } from "@/lib/admin-types";
import { GRADE_LABELS, gradeColor } from "@/lib/grade-colors";

export function CompanyGradeList({ companies }: { companies: Company[] }) {
  const sorted = [...companies].sort((a, b) => a.grade - b.grade);

  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">기업별 데이터 등급</h2>
          <p className="mt-0.5 text-xs text-faint">
            거래 기업 각각의 PCAF 등급 · 실측 여부 · 검토 대기 건수
          </p>
        </div>
        <span className="rounded-full border border-line bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
          {companies.length}개사
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {sorted.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            거래 기업 없음
          </div>
        ) : (
          sorted.map((c) => (
            <div
              key={c.company_id}
              className="flex items-center justify-between gap-3 px-5 py-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-semibold text-ink">
                    {c.company_name}
                  </span>
                  {c.industry_name && (
                    <span className="flex-shrink-0 rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] font-medium text-muted">
                      {c.industry_name}
                    </span>
                  )}
                  {!c.measured && (
                    <span className="flex-shrink-0 rounded border border-hitl/40 bg-hitl/20 px-1.5 py-0.5 text-[10px] font-medium text-hitl-ink">
                      추정치
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-faint">
                  Scope1 {c.scope1.toLocaleString()} · Scope2 {c.scope2.toLocaleString()}{" "}
                  tCO2e
                  {c.hitl_count > 0 && (
                    <span className="ml-1.5 text-hitl-ink">
                      · 검토 대기 {c.hitl_count}건
                    </span>
                  )}
                </p>
              </div>
              <span
                className="flex-shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold text-white"
                style={{ backgroundColor: gradeColor(c.grade) }}
              >
                {GRADE_LABELS[String(c.grade)] ?? `${c.grade}등급`}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
