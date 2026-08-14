"use client";

import { useEffect, useState } from "react";
import { getKTaxonomyLeads, type KTaxonomyLeadsResponse } from "@/lib/api";

/** 사장님 메인 화면(/owner)의 K택소노미(친환경 설비 투자) 안내 카드 — 예전엔 리포트
 * 화면(ScenePcaf.tsx)에 붙어 있었으나, 우대금리 카드(RateProductCard.tsx)와 같은 이유로
 * 메인으로 옮겼다.
 *
 * GET /owner/{id}/k-taxonomy-leads(db/k_taxonomy.py::k_taxonomy_leads_for_company)는
 * 룰 매칭 경로에서만 채워지는 필드라(LLM 분류 경로는 항상 비어 있음) 대다수 기업·기간은
 * 빈 배열이 정상이다 — 그럴 땐 카드 자체를 숨긴다.
 *
 * 읽기 전용 안내 카드다 — 관리자측 승인요청 큐(ApprovalQueue.tsx, /admin/rate-requests)가
 * 팀원 커밋 0caca0e로 이번 스코프에서 제외되며, 요청을 넣어도 은행 담당자가 확인할 UI가
 * 없어 "설비금융 안내 요청" 버튼은 만들지 않는다(RateProductCard.tsx와 동일 결정). */

export function KTaxonomyCard({ companyId }: { companyId: number | null }) {
  const [data, setData] = useState<KTaxonomyLeadsResponse | null>(null);

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    getKTaxonomyLeads(companyId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => console.error("K택소노미 리드 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (companyId === null || !data || data.leads.length === 0) return null;

  return (
    <div className="mt-3 space-y-3 rounded-3xl bg-surface p-5 shadow-card">
      <div>
        <div className="text-[13px] font-semibold text-ink">친환경 설비 투자 안내</div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-faint">
          전표에서 확인된 친환경·저탄소 설비예요.
        </p>
      </div>

      {data.leads.map((lead) => (
        <div key={lead.k_taxonomy_facility_type} className="rounded-xl bg-bg p-4">
          <div className="text-[12.5px] font-semibold text-ink">{lead.k_taxonomy_facility_type}</div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{lead.hint}</p>
        </div>
      ))}
    </div>
  );
}
