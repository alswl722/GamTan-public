"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { getEligibilityFixture, useCarbonPointScenario } from "@/lib/carbon-point-fixture";

/** 홈 화면 배너 — 소상공인 사업장이 탄소중립포인트 신청 대상일 때만 뜬다
 * (docs/small-business-green-supply-develop-plan.md §3.3). 누르면 "맞춤 혜택"
 * 페이지의 CarbonPointCard로 데려간다.
 *
 * 문구를 "신청 대상일 수 있어요"로 잡은 건 의도다 — 감축률은 감탄의 예상치이고 공식
 * 판정은 한국환경공단이 반기마다 따로 한다(data-plan §6.2). 홈 배너처럼 짧은 자리에도
 * 확정 표현을 쓰지 않는다(§3.3 안전한 표현 원칙).
 *
 * OwnerNotificationBanner와 달리 companyId를 받지 않는다 — 지금은 fixture라 쓸 곳이
 * 없다. §9.1 API 연동 시 eligibility를 기업별로 조회하게 되면서 prop이 생긴다(그때
 * 부모의 `selectedId !== null` 게이트를 그대로 넘겨주면 된다). */
export default function CarbonPointNoticeBanner() {
  const scenario = useCarbonPointScenario();
  const { business_scale_hint, eligible } = getEligibilityFixture(scenario);

  if (business_scale_hint !== "소상공인/상업시설" || !eligible) return null;

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
