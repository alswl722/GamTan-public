"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Check, FileText, Leaf } from "lucide-react";
import { getCarbonPointEligibility, type CarbonPointEligibility } from "@/lib/api";
import {
  CARBON_POINT_GAUGE_MAX_PCT,
  CARBON_POINT_THRESHOLD_PCT,
  KRW_PER_POINT,
  estimateRefund,
} from "@/lib/carbon-point";

/** 감축률 게이지 — 기준선(5%)을 눈금으로 찍어 "넘었는지"를 색이 아니라 위치로 보여준다.
 * 상한(10%)을 넘는 값은 막대가 꽉 찬 상태로 고정된다. */
function ReductionGauge({ pct }: { pct: number }) {
  const fillRatio = Math.min(1, pct / CARBON_POINT_GAUGE_MAX_PCT);
  const thresholdRatio = CARBON_POINT_THRESHOLD_PCT / CARBON_POINT_GAUGE_MAX_PCT;
  return (
    <div>
      <div className="relative h-[7px] w-full overflow-hidden rounded-full bg-line">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-ink to-lime"
          style={{ width: `${fillRatio * 100}%` }}
        />
        <span
          className="absolute top-0 h-full w-0.5 bg-white"
          style={{ left: `${thresholdRatio * 100}%` }}
        />
      </div>
      <div
        className="mt-1 -translate-x-1/2 text-[8px] font-semibold text-faint"
        style={{ marginLeft: `${thresholdRatio * 100}%` }}
      >
        기준 {CARBON_POINT_THRESHOLD_PCT}%
      </div>
    </div>
  );
}

/** 소상공인 탄소중립포인트 자격 안내 카드 — "맞춤 혜택" 페이지(/owner/benefits)의
 * 소상공인 전용 섹션. docs/small-business-green-supply-develop-plan.md §3.3 정본.
 *
 * RateProductCard·KTaxonomyCard·GovSupportCard와 같은 자기완결형 패턴을 따른다
 * ({ companyId }만 받고, 보여줄 게 없으면 스스로 숨는다). 2026-08-25에 fixture를 걷고
 * §9.1 API(GET /owner/{id}/carbon-point/eligibility)에 붙였다.
 *
 * 이름이 data-plan.md §10.1의 `GovSupportCard`가 아닌 이유: 그 이름은 이미 정부
 * 지원사업 매칭 카드가 점유하고 있다(web/components/GovSupportCard.tsx).
 *
 * 제조업 기업에는 카드 자체를 노출하지 않는다 — 산업용 전기를 쓰는 사업장은
 * 탄소중립포인트 에너지분야 신청 대상에서 원천 제외되기 때문(data-plan §6.2).
 * "미확인"도 노출하지 않는다(판별 실패 상태에서 자격을 말할 수 없다) — 그 경우의
 * 계약종별 재확인 안내는 페이지(§3.2)가 담당한다. */
export function CarbonPointCard({ companyId }: { companyId: number | null }) {
  const [eligibility, setEligibility] = useState<CarbonPointEligibility | null>(null);

  useEffect(() => {
    if (companyId === null) return;
    let cancelled = false;
    getCarbonPointEligibility(companyId)
      .then((res) => {
        if (!cancelled) setEligibility(res);
      })
      .catch((err) => console.error("탄소중립포인트 자격 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  if (companyId === null || eligibility === null) return null;
  if (eligibility.business_scale_hint !== "소상공인/상업시설") return null;

  const { reduction_rate_pct, eligible, missing_data } = eligibility;
  const refund = estimateRefund(reduction_rate_pct);

  return (
    <div className="mt-3 space-y-3">
      <div className="rounded-3xl bg-surface p-5 shadow-card">
        <div className="flex items-center gap-2.5">
          <span className="grid size-[42px] shrink-0 place-items-center rounded-full bg-brand">
            <Leaf size={20} strokeWidth={2.1} className="text-white" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-bold leading-snug text-ink">탄소중립포인트</div>
            <div className="text-[11px] text-muted">에너지 분야 · 한국환경공단</div>
          </div>
          <span
            className={`flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold ${
              eligible ? "bg-brand-soft text-brand-ink" : "bg-line text-muted"
            }`}
          >
            {eligible && <Check size={11} strokeWidth={3} />}
            {eligible ? "신청 대상" : "기준 미달"}
          </span>
        </div>

        {/* 감축률(왼쪽)과 그 결과인 환급액(오른쪽)을 같은 무게로 나란히 둔다 —
            "얼마나 줄였나"와 "그래서 얼마 받나"가 한 눈에 이어지도록. */}
        <div className="mt-4 rounded-2xl bg-bg px-4 py-3.5">
          <div className="flex items-start gap-3.5">
            <div className="min-w-0 flex-1">
              <div className="text-[11.5px] font-semibold text-muted">예상 감축률</div>
              {reduction_rate_pct === null ? (
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
                  아직 계산할 수 없어요.
                </p>
              ) : (
                <>
                  <div className="mt-1.5 flex items-baseline text-brand-ink">
                    <span className="text-[20px] font-extrabold leading-none">
                      {reduction_rate_pct}
                    </span>
                    <span className="text-[13px] font-bold">%</span>
                  </div>
                  <div className="mt-2.5">
                    <ReductionGauge pct={reduction_rate_pct} />
                  </div>
                </>
              )}
            </div>

            <div className="w-px self-stretch bg-line" />

            <div className="min-w-0 flex-1">
              <div className="text-[11.5px] font-semibold text-muted">예상 환급액</div>
              {refund === null ? (
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
                  기준 감축률을 넘으면 계산해 드려요.
                </p>
              ) : (
                <>
                  <div className="mt-1.5 text-[20px] font-extrabold leading-none text-brand-ink">
                    {refund.krw.toLocaleString()}원
                  </div>
                  <div className="mt-1 text-[9.5px] text-faint">
                    전기 {refund.points.toLocaleString()}P × {KRW_PER_POINT}원
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        {missing_data.length > 0 && (
          <div className="mt-4">
            <div className="text-[11.5px] font-semibold text-muted">아직 없는 자료</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {missing_data.map((item) => (
                <span
                  key={item}
                  className="flex items-center gap-1.5 rounded-full bg-bg px-3 py-1.5 text-[11.5px] font-semibold text-muted"
                >
                  <FileText size={13} className="shrink-0" />
                  {item}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* 신청서 초안은 자격을 충족했을 때만 열어준다(data-plan §6.2 — 판정이 통과한
            경우에만 신청 절차로 이어진다). 미달일 때는 왜 아직 안 되는지만 알려준다. */}
        {eligible ? (
          <Link
            href="/owner/carbon-point"
            className="btn-cta mt-4 flex w-full items-center justify-center gap-1.5 rounded-2xl bg-gradient-to-r from-brand-ink to-brand py-3.5 text-[14px] font-bold text-white"
          >
            신청서 초안 작성하러 가기
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        ) : (
          <p className="mt-4 text-[12px] leading-relaxed text-muted">
            예상 감축률이 {CARBON_POINT_THRESHOLD_PCT}%를 넘으면 신청서 초안을 만들어 드려요.
          </p>
        )}

        {/* 비보장 문구 — API에 플래그가 없으므로(§2.2) 컴포넌트에 정적으로 박아넣는다.
            GoalSheet.tsx의 "등급 상승·자격을 보장하지 않아요" 캡션과 같은 관행·스타일. */}
        <p className="mt-3 text-[11px] leading-relaxed text-faint">
          예상 감축률 기준이며, 실제 심사·지급은 한국환경공단이 진행합니다.
        </p>
      </div>
    </div>
  );
}
