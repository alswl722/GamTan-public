/** 온보딩 리워드 안내 배너 — 마이데이터 연동 완료 시점에만 노출
 * (docs/small-business-green-supply-develop-plan.md §3.1).
 *
 * 문구가 잠정 톤인 건 의도다. 온보딩 리워드(대구로페이 충전) 예산이 아직 확인되지
 * 않았고(data-plan.md §15.1 1순위), 확인 전에 "1만원 충전 예정"처럼 금액·시점을
 * 못박으면 지키지 못할 약속이 화면에 남는다(data-plan.md §3.3 안전한 표현 원칙).
 * 예산이 확정되면 아래 REWARD_BANNER_COPY 한 곳만 고친다 — 마크업은 안 건드린다.
 *
 * 링크가 아니라 안내라서 <div>다(누를 곳이 없다). 실제 송금도 아니다 — 백엔드도
 * trace_logs에 "[행동] 온보딩 리워드 지급 안내"를 남기는 것까지만 한다(§2.4).
 */

const REWARD_BANNER_COPY = {
  title: "온보딩 혜택 안내 (검토 중)",
  body: "마이데이터 연동을 마친 사장님께 드릴 혜택을 준비하고 있어요.",
} as const;

export function OnboardingRewardBanner() {
  return (
    <div className="mt-4 rounded-xl bg-brand-soft px-3.5 py-3">
      <div className="text-[12px] font-bold text-brand-ink">{REWARD_BANNER_COPY.title}</div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-brand-ink/80">
        {REWARD_BANNER_COPY.body}
      </p>
    </div>
  );
}
