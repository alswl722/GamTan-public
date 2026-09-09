"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { getCarbonPointEligibility } from "@/lib/api";

/** 홈 화면 배너 — 소상공인 사업장이 탄소중립포인트 신청 대상일 때만 뜬다
 * (docs/small-business-green-supply-develop-plan.md §3.3). 누르면 "맞춤 혜택"
 * 페이지의 CarbonPointCard로 데려간다.
 *
 * 문구를 "신청 대상일 수 있어요"로 잡은 건 의도다 — 감축률은 감탄의 예상치이고 공식
 * 판정은 한국환경공단이 반기마다 따로 한다(data-plan §6.2). 홈 배너처럼 짧은 자리에도
 * 확정 표현을 쓰지 않는다(§3.3 안전한 표현 원칙).
 *
 * 2026-08-25에 fixture를 걷고 §9.1 API에 붙이면서 `companyId` prop이 생겼다 — 자격이
 * 기업별로 조회되기 때문이다. 부모(홈)의 `selectedId !== null` 게이트를 그대로 넘겨준다.
 * 조회 실패·미대상이면 아무것도 렌더하지 않는다(홈 배너라 에러를 띄울 자리가 아니다 —
 * 자격 판정은 홈의 주된 정보가 아니고, 실패는 혜택 페이지에서 드러난다). */
export default function CarbonPointNoticeBanner({ companyId }: { companyId: number | null }) {
  const [eligible, setEligible] = useState(false);

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    getCarbonPointEligibility(companyId)
      .then((res) => {
        if (!cancelled) {
          setEligible(res.business_scale_hint === "소상공인/상업시설" && res.eligible);
        }
      })
      .catch((err) => console.error("탄소중립포인트 자격 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (!eligible) return null;

  return (
    <Link
      href="/owner/benefits"
      className="mt-3 flex items-center gap-2 rounded-xl bg-brand-soft px-3.5 py-2.5 transition-opacity hover:opacity-90"
    >
      <span className="size-1.5 shrink-0 rounded-full bg-brand" />
      <span className="flex-1 text-[12px] font-bold text-brand-ink">
        탄소중립포인트 신청 대상일 수 있어요
      </span>
      <ChevronRight size={16} strokeWidth={2.6} className="shrink-0 text-brand-ink" />
    </Link>
  );
}
