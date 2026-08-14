"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getRateCandidate, type RateCandidate, type RateCandidateResponse } from "@/lib/api";

/** 우대금리 안내 카드 — "금융 혜택" 페이지(/owner/benefits)의 한 섹션. 예전엔 메인
 * 화면(/owner)에 바로 떠 있었으나, K택소노미(설비금융) 카드와 성격이 같은 "금융
 * 혜택 안내"라 한 페이지로 묶었다(하단바 "혜택" 탭 추가, web/app/owner/page.tsx에서는
 * 제거).
 *
 * GET /owner/{id}/rate-candidate(db/rate_products.py::rate_product_status_for_company)가
 * Scope별로 status를 "eligible"(이미 상품 자격 충족)과 "upgrade_needed"(등급 개선
 * 필요)로 나눠 주므로, 두 카드 종류로 갈라 렌더링한다. 같은 상품이 Scope 1·2 양쪽에서
 * 매칭되면 카드 하나로 묶는다(같은 상품 안내가 두 번 뜨는 걸 막기 위함).
 *
 * 지어낸 금리가 아니라는 걸 보여주려고 상품마다 source_reference(실제 iM뱅크 상품
 * 공시 근거)를 노출한다 — URL이 포함돼 있으면 링크로, 아니면 텍스트로.
 *
 * 결손월 안내(missing_items)는 문서종류·월 단위로 구조화돼 있어 /owner/uploads의
 * 해당 칸으로 이동하는 딥링크를 건다 — "3~5월 도시가스 고지서를 올려주세요" 안내가
 * 텍스트로 끝나지 않고 실제 업로드 행동으로 이어지게. 결손월이 여러 달 이어질 때
 * 달마다 칩을 하나씩 만들면 너무 빽빽해져서(예: 9개월 결손 = 칩 9개), 연속 구간을
 * 하나로 묶어 칩 하나당 구간 하나로 보여준다 — 클릭하면 그 구간의 첫 달로 이동하고,
 * 나머지 달은 그리드에서 이어서 채우면 된다.
 *
 * 읽기 전용 안내 카드다 — 관리자측 승인요청 큐(ApprovalQueue.tsx, /admin/rate-requests)가
 * 이번 스코프에서 제외되며(팀원 커밋 0caca0e), 요청을 넣어도 은행 담당자가 확인할 UI가
 * 없어 "요청하기" 버튼은 만들지 않는다. */

/** source_reference는 "iM뱅크 ESG Grow-Up 특별대출 (https://...)"처럼 이름+URL이
 * 한 문장에 섞여 있다 — URL 부분만 잘라 링크로 만들고 나머지는 그대로 보여준다. */
function SourceReference({ text }: { text: string }) {
  const match = text.match(/https?:\/\/\S+/);
  if (!match) return <p className="mt-1.5 text-[11px] text-faint">{text}</p>;
  const url = match[0];
  const label = text.slice(0, match.index).trim();
  return (
    <p className="mt-1.5 text-[11px] text-faint">
      {label}{" "}
      <a href={url} target="_blank" rel="noreferrer" className="underline decoration-dotted">
        상품 안내 바로가기
      </a>
    </p>
  );
}

/** [4,5,6,9,11,12] → [{start:4,end:6},{start:9,end:9},{start:11,end:12}] — 이어지는
 * 달을 구간으로 묶는다(칩 개수를 줄이기 위함, months는 항상 오름차순으로 들어온다). */
function toMonthRanges(months: number[]): { start: number; end: number }[] {
  const ranges: { start: number; end: number }[] = [];
  for (const month of months) {
    const last = ranges[ranges.length - 1];
    if (last && month === last.end + 1) {
      last.end = month;
    } else {
      ranges.push({ start: month, end: month });
    }
  }
  return ranges;
}

function MissingItems({ items }: { items: RateCandidate["missing_items"] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {items.flatMap((item) =>
        toMonthRanges(item.months).map((range) => {
          const label =
            range.start === range.end
              ? `${item.fuel_label} ${range.start}월`
              : `${item.fuel_label} ${range.start}~${range.end}월(${range.end - range.start + 1}개월)`;
          return (
            <Link
              key={`${item.document_type}-${range.start}`}
              href={`/owner/uploads?type=${item.document_type}&month=${range.start}`}
              className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink transition-colors hover:bg-brand hover:text-white"
            >
              {label} 업로드하기
            </Link>
          );
        })
      )}
    </div>
  );
}

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
                <SourceReference text={p.source_reference} />
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
                <MissingItems items={c.missing_items} />
              </div>
            ))}
            {targetProducts.map((p) => (
              <div key={p.product_name} className="mt-3 rounded-2xl bg-bg p-3.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13.5px] font-bold text-ink">{p.product_name}</span>
                  <span className="shrink-0 text-[12.5px] font-bold text-brand-ink">
                    최대 {p.rate_discount_pct}%p 우대
                  </span>
                </div>
                <p className="mt-1 text-[11.5px] text-faint">{p.provider_name}</p>
                <SourceReference text={p.source_reference} />
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
