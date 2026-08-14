"use client";

import Image from "next/image";
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
 * 결손월 안내(missing_items)는 문서종류·월 단위로 구조화돼 있어 /owner/uploads의
 * 해당 칸으로 이동하는 딥링크를 건다 — "3~5월 도시가스 고지서를 올려주세요" 안내가
 * 텍스트로 끝나지 않고 실제 업로드 행동으로 이어지게. 결손월이 여러 달 이어질 때
 * 달마다 칩을 하나씩 만들면 너무 빽빽해져서(예: 9개월 결손 = 칩 9개), 연속 구간을
 * 하나로 묶어 칩 하나당 구간 하나로 보여준다 — 클릭하면 그 구간의 첫 달로 이동하고,
 * 나머지 달은 그리드에서 이어서 채우면 된다. missing 원문 문장은 화면에는 안 보여주고
 * (칩이 이미 같은 정보를 실행 가능하게 보여줘 중복) 이 칩의 접근성 라벨로만 쓴다.
 *
 * 컴포넌트 자체엔 "우대금리 대상 안내" 같은 섹션 타이틀·Scope/상품 배지 묶음을 두지
 * 않는다(2026-08-14 컴팩트화) — 그 라벨은 페이지(web/app/owner/benefits/page.tsx)가
 * 한 번만 보여주고, 카드는 상품명·우대율·상태만 한 겹으로 압축해서 보여준다.
 *
 * 읽기 전용 안내 카드다 — 관리자측 승인요청 큐(ApprovalQueue.tsx, /admin/rate-requests)가
 * 이번 스코프에서 제외되며(팀원 커밋 0caca0e), 요청을 넣어도 은행 담당자가 확인할 UI가
 * 없어 "요청하기" 버튼은 만들지 않는다. */

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
    <div className="space-y-1">
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
              className="block text-[12px] leading-relaxed text-brand-ink underline decoration-dotted underline-offset-2"
            >
              • {label} 업로드해주세요
            </Link>
          );
        })
      )}
    </div>
  );
}

/** "이상 신호 알림" 카드(ScenePcaf.tsx)와 같은 아바타+말풍선 패턴 — 캐릭터가 실제로
 * 안내해주는 느낌을 카드마다 반복해서 준다(2026-08-14, 사용자 요청으로 통일). */
function GuidanceBubble({ items }: { items: RateCandidate["missing_items"] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-2.5 flex items-start gap-2">
      <span className="relative h-7 w-7 shrink-0 overflow-hidden rounded-full bg-brand-soft">
        <Image src="/ddockdi_3.png" alt="" fill className="object-cover" />
      </span>
      <div className="relative min-w-0 flex-1 rounded-2xl rounded-tl-sm bg-bg px-3.5 py-2.5">
        <span className="absolute -left-1.5 top-3 h-3 w-3 rotate-45 rounded-sm bg-bg" />
        <MissingItems items={items} />
      </div>
    </div>
  );
}

const SCOPE_LABEL: Record<string, string> = { scope_1: "Scope 1", scope_2: "Scope 2" };

function ScopeBadge({ label }: { label: string }) {
  return (
    <span className="rounded-full bg-line px-2 py-0.5 text-[10.5px] font-semibold text-muted">
      {label}
    </span>
  );
}

function GradeBadge({ grade, target }: { grade: number; target?: boolean }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
        target ? "bg-brand text-white" : "bg-line text-muted"
      }`}
    >
      {grade}등급
    </span>
  );
}

/** 카드 우상단에 크게 박는 우대율 — "얼마 받는지"가 카드에서 가장 먼저 눈에 띄어야
 * 한다는 게 컴팩트 리디자인의 핵심 의도(2026-08-14). */
function DiscountHighlight({ pct, caption }: { pct: number; caption?: string }) {
  return (
    <div className="shrink-0 text-right">
      <div className="text-[19px] font-extrabold leading-none text-brand-ink">{pct}%p</div>
      {caption && <div className="mt-0.5 text-[10px] font-semibold text-faint">{caption}</div>}
    </div>
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
    <div className="mt-3 flex flex-col gap-2.5">
      {[...eligibleGroups.values()].flatMap((group) => {
        const products = group[0].products ?? [];
        const scopeLabels = group.map((c) => SCOPE_LABEL[c.scope_group]).join(" · ");
        return products.map((p) => (
          <div key={p.product_name} className="rounded-3xl bg-surface p-4 shadow-card">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <ScopeBadge label={`${scopeLabels} 충족`} />
                <div className="mt-1.5 text-[14.5px] font-bold leading-snug text-ink">
                  {p.product_name}
                </div>
              </div>
              <DiscountHighlight pct={p.rate_discount_pct} caption="우대" />
            </div>
            <p className="mt-2.5 text-[12px] leading-relaxed text-muted">{p.eligibility_description}</p>
          </div>
        ));
      })}

      {[...upgradeGroups.values()].map((group) => {
        const targetProducts = group[0].target_products ?? [];
        const scopeLabels = group.map((c) => SCOPE_LABEL[c.scope_group]).join(" · ");
        const headline = targetProducts[0];
        return (
          <div key={scopeLabels} className="rounded-3xl bg-surface p-4 shadow-card">
            {headline ? (
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[14.5px] font-bold leading-snug text-ink">
                    {headline.product_name}
                  </div>
                </div>
                <DiscountHighlight pct={headline.rate_discount_pct} />
              </div>
            ) : (
              <div className="text-[13px] font-semibold text-ink">등급 개선 안내</div>
            )}

            {group.map((c) => (
              <div key={c.scope_group} className="mt-2.5 flex flex-wrap items-center gap-1.5">
                <ScopeBadge label={SCOPE_LABEL[c.scope_group]} />
                <GradeBadge grade={c.current_grade!} />
                <span className="text-[11px] text-faint">→</span>
                <GradeBadge grade={c.target_grade!} target />
              </div>
            ))}
            <GuidanceBubble items={group.flatMap((c) => c.missing_items ?? [])} />
          </div>
        );
      })}
    </div>
  );
}
