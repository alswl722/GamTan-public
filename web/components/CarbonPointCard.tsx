"use client";

import { useState } from "react";
import {
  CARBON_POINT_THRESHOLD_PCT,
  FIXTURE_BADGE_LABEL,
  getDraftFixture,
  getEligibilityFixture,
  useCarbonPointScenario,
} from "@/lib/carbon-point-fixture";
import { CarbonPointDraftSheet } from "@/components/CarbonPointDraftSheet";

/** 소상공인 탄소중립포인트 자격 안내 카드 — "맞춤 혜택" 페이지(/owner/benefits)의
 * 소상공인 전용 섹션. docs/small-business-green-supply-develop-plan.md §3.3 정본.
 *
 * RateProductCard·KTaxonomyCard·GovSupportCard와 같은 자기완결형 패턴을 따른다
 * ({ companyId }만 받고, 보여줄 게 없으면 스스로 숨는다). 다만 데이터 출처는 아직
 * fetch가 아니라 fixture다(§3.0 — 백엔드 §9.1 API 미구현).
 *
 * 이름이 data-plan.md §10.1의 `GovSupportCard`가 아닌 이유: 그 이름은 이미 정부
 * 지원사업 매칭 카드가 점유하고 있다(web/components/GovSupportCard.tsx).
 *
 * 제조업 기업에는 카드 자체를 노출하지 않는다 — 산업용 전기를 쓰는 사업장은
 * 탄소중립포인트 에너지분야 신청 대상에서 원천 제외되기 때문(data-plan §6.2).
 * "미확인"도 노출하지 않는다(판별 실패 상태에서 자격을 말할 수 없다) — 그 경우의
 * 계약종별 재확인 안내는 페이지(§3.2)가 담당한다. */
export function CarbonPointCard({ companyId }: { companyId: number | null }) {
  const scenario = useCarbonPointScenario();
  const eligibility = getEligibilityFixture(scenario);
  const [draftOpen, setDraftOpen] = useState(false);

  if (companyId === null) return null;
  if (eligibility.business_scale_hint !== "소상공인/상업시설") return null;

  const { baseline_year, target_year, reduction_rate_pct, eligible, missing_data } = eligibility;

  return (
    <div className="mt-3 space-y-3">
      <div className="text-[13px] font-semibold text-ink">탄소중립포인트</div>

      <div className="rounded-3xl bg-surface p-4 shadow-card">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13px] font-semibold leading-snug text-ink">
              탄소중립포인트 (에너지)
            </div>
            <span className="mt-1.5 inline-block rounded-full bg-line px-2 py-0.5 text-[10.5px] font-semibold text-muted">
              한국환경공단
            </span>
          </div>
          <span
            className={`shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${
              eligible ? "bg-brand-soft text-brand-ink" : "bg-line text-muted"
            }`}
          >
            {eligible ? "신청 대상일 수 있어요" : "기준 미달"}
          </span>
        </div>

        {/* 감축률 — 예상치라는 걸 라벨에서부터 못박는다(§2.3 문구 통일) */}
        <div className="mt-3 rounded-2xl bg-bg px-3.5 py-3">
          <div className="text-[11.5px] font-semibold text-muted">
            {baseline_year}년 대비 {target_year}년 예상 감축률
          </div>
          {reduction_rate_pct === null ? (
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink">
              아직 예상 감축률을 계산할 수 없어요.
            </p>
          ) : (
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="text-[24px] font-extrabold leading-none text-ink">
                {reduction_rate_pct}
                <span className="text-[15px] font-bold">%</span>
              </span>
              <span className="text-[11.5px] text-faint">
                신청 기준 {CARBON_POINT_THRESHOLD_PCT}% 이상
              </span>
            </div>
          )}
        </div>

        {missing_data.length > 0 && (
          <div className="mt-2.5">
            <div className="text-[11.5px] font-semibold text-muted">아직 없는 자료</div>
            <ul className="mt-1 space-y-0.5">
              {missing_data.map((item) => (
                <li key={item} className="flex gap-1.5 text-[12px] leading-relaxed text-ink">
                  <span className="mt-[7px] size-1 shrink-0 rounded-full bg-faint" />
                  <span className="min-w-0">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 신청서 초안은 자격을 충족했을 때만 열어준다(data-plan §6.2 — 판정이 통과한
            경우에만 신청 절차로 이어진다). 미달일 때는 왜 아직 안 되는지만 알려준다. */}
        {eligible ? (
          <button
            type="button"
            onClick={() => setDraftOpen(true)}
            className="btn-cta mt-3 w-full rounded-2xl bg-brand py-3 text-[13.5px] font-extrabold text-white"
          >
            신청서 초안 보기
          </button>
        ) : (
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            예상 감축률이 {CARBON_POINT_THRESHOLD_PCT}%를 넘으면 신청서 초안을 만들어 드려요.
          </p>
        )}

        {/* 비보장 문구 — API에 플래그가 없으므로(§2.2) 컴포넌트에 정적으로 박아넣는다.
            GoalSheet.tsx의 "등급 상승·자격을 보장하지 않아요" 캡션과 같은 관행·스타일. */}
        <p className="mt-3 text-[11px] leading-relaxed text-faint">
          예상 감축률 기준이며, 실제 심사·지급은 한국환경공단이 진행합니다.
        </p>

        <div className="mt-2">
          <span className="inline-block rounded-full bg-line px-2 py-0.5 text-[10px] font-semibold text-faint">
            {FIXTURE_BADGE_LABEL}
          </span>
        </div>
      </div>

      {draftOpen && (
        <CarbonPointDraftSheet
          draft={getDraftFixture(scenario)}
          onClose={() => setDraftOpen(false)}
        />
      )}
    </div>
  );
}
