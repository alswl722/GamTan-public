"use client";

// 실API: GET /admin/k-taxonomy-leads

import type { KTaxonomyLeadItem } from "@/lib/admin-types";

export function KTaxonomyLeads({ leads }: { leads: KTaxonomyLeadItem[] }) {
  return (
    <div className="flex h-full flex-col rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">K택소노미·설비투자 리드</h2>
          <p className="mt-0.5 text-xs text-faint">
            녹색여신·설비금융 안내 대상(여신 결정 아님, 데이터 완전성 순)
          </p>
        </div>
        <span className="rounded-full border border-line bg-bg px-2 py-1 text-[11px] font-semibold text-muted">
          {leads.length}건
        </span>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {leads.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center text-sm text-faint">
            K택소노미·설비투자 리드 없음
          </div>
        ) : (
          leads.map((lead, i) => (
            <div key={`${lead.company_id}-${i}`} className="px-5 py-3.5">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-ink">{lead.company_name}</span>
                <div className="flex flex-shrink-0 items-center gap-1.5">
                  <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-bold text-brand-ink">
                    {lead.finance_lead_type}
                  </span>
                  {lead.k_taxonomy_hitl_required && (
                    <span className="rounded-full bg-hitl/25 px-2 py-0.5 text-[11px] font-bold text-hitl-ink">
                      HITL 확인 필요
                    </span>
                  )}
                </div>
              </div>
              <p className="mb-1 text-xs leading-relaxed text-muted">
                <span className="font-medium text-ink">{lead.k_taxonomy_facility_type ?? "—"}</span>
                {lead.k_taxonomy_candidate_type && ` · ${lead.k_taxonomy_candidate_type}`}
              </p>
              <p className="text-xs text-faint">
                {lead.voucher_month}월 · &ldquo;{lead.item_description}&rdquo;
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
