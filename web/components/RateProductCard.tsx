"use client";

import { useEffect, useState } from "react";
import { getRateCandidate, type RateCandidate, type RateCandidateResponse } from "@/lib/api";

/** 사장님 메인 화면(/owner)의 우대금리 카드 — 예전엔 리포트 화면(ScenePcaf.tsx)에
 * 붙어 있었으나, "탄소 측정하러 가기" 진입 전에도 바로 보이도록 메인으로 옮겼다.
 *
 * GET /owner/{id}/rate-candidate(db/rate_products.py::rate_product_status_for_company)가
 * Scope별로 status를 "eligible"(이미 상품 자격 충족)과 "upgrade_needed"(등급 개선
 * 필요)로 나눠 주므로, 두 카드 종류로 갈라 렌더링한다. 같은 상품이 Scope 1·2 양쪽에서
 * 매칭되면 카드 하나로 묶는다(같은 상품 안내가 두 번 뜨는 걸 막기 위함).
 *
 * 읽기 전용 안내 카드다 — 관리자측 승인요청 큐(ApprovalQueue.tsx, /admin/rate-requests)가
 * 이번 스코프에서 제외되며(팀원 커밋 0caca0e), 요청을 넣어도 은행 담당자가 확인할 UI가
 * 없어 "요청하기" 버튼은 만들지 않는다. */

const SCOPE_LABEL: Record<string, string> = { scope_1: "Scope 1", scope_2: "Scope 2" };

function ProductBadge({ name }: { name: string }) {
  return (
    <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-semibold text-brand-ink">
      {name}
    </span>
  );
}

function ScopeBadge({ label }: { label: string }) {
  return (
    <span className="rounded-full bg-line px-2 py-0.5 text-[10.5px] font-semibold text-muted">
      {label}
    </span>
  );
}

function groupByProductNames<T extends { scope_group: string }>(
  items: T[],
  productNamesOf: (item: T) => string[]
): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const key = productNamesOf(item).join(",");
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return groups;
}

export function RateProductCard({ companyId }: { companyId: number | null }) {
  const [data, setData] = useState<RateCandidateResponse | null>(null);

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    getRateCandidate(companyId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => console.error("우대금리 후보 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (companyId === null || !data || data.candidates.length === 0) return null;

  const eligible = data.candidates.filter((c) => c.status === "eligible");
  const upgradeNeeded = data.candidates.filter((c) => c.status === "upgrade_needed");

  const eligibleGroups = groupByProductNames(eligible, (c) => (c.products ?? []).map((p) => p.product_name));
  const upgradeGroups = groupByProductNames(upgradeNeeded, (c) =>
    (c.target_products ?? []).map((p) => p.product_name)
  );

  return (
    <div className="mt-4 flex flex-col gap-3">
      {[...eligibleGroups.values()].map((group) => {
        const products = group[0].products ?? [];
        const scopeLabels = group.map((c) => SCOPE_LABEL[c.scope_group]).join(" · ");
        return (
          <div key={scopeLabels} className="rounded-3xl bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-center gap-1.5">
              <div className="text-[13px] font-semibold text-ink">우대금리 대상 안내</div>
              <ScopeBadge label={`${scopeLabels} 조건 충족`} />
              {products.map((p) => (
                <ProductBadge key={p.product_name} name={p.product_name} />
              ))}
            </div>
            {products.map((p) => (
              <div key={p.product_name} className="mt-3 rounded-2xl bg-bg p-3.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13.5px] font-bold text-ink">{p.product_name}</span>
                  <span className="shrink-0 text-[12.5px] font-bold text-brand-ink">
                    최대 {p.rate_discount_pct}%p 우대
                  </span>
                </div>
                <p className="mt-1 text-[11.5px] text-faint">{p.provider_name}</p>
                <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
                  {p.eligibility_description}
                </p>
              </div>
            ))}
          </div>
        );
      })}

      {[...upgradeGroups.values()].map((group) => {
        const targetProducts = group[0].target_products ?? [];
        const scopeLabels = group.map((c) => SCOPE_LABEL[c.scope_group]).join(" · ");
        return (
          <div key={scopeLabels} className="rounded-3xl bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-center gap-1.5">
              <div className="text-[13px] font-semibold text-ink">우대금리 대상 안내</div>
              <ScopeBadge label={scopeLabels} />
              {targetProducts.map((p) => (
                <ProductBadge key={p.product_name} name={p.product_name} />
              ))}
            </div>
            {group.map((c) => (
              <div key={c.scope_group} className="mt-3">
                {group.length > 1 && (
                  <div className="text-[11.5px] font-semibold text-ink">{SCOPE_LABEL[c.scope_group]}</div>
                )}
                <div className="mt-1 flex items-center gap-1.5 text-[12.5px] text-muted">
                  <span className="rounded-full bg-line px-2 py-0.5 text-[11px] font-bold text-muted">
                    {c.current_grade}등급
                  </span>
                  <span className="text-faint">→</span>
                  <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-bold text-white">
                    {c.target_grade}등급
                  </span>
                </div>
                <p className="mt-1.5 whitespace-pre-line text-[12.5px] leading-relaxed text-muted">{c.missing}</p>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
