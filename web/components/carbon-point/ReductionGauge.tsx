import { CARBON_POINT_GAUGE_MAX_PCT, CARBON_POINT_THRESHOLD_PCT } from "@/lib/carbon-point";

/** 감축률 게이지 — 기준선(5%)을 눈금으로 찍어 "넘었는지"를 색이 아니라 위치로 보여준다.
 * 상한(10%)을 넘는 값은 막대가 꽉 찬 상태로 고정된다.
 *
 * CarbonPointCard(맞춤 혜택 카드)와 carbon-point 신청서 위저드 1단계가 함께 쓴다
 * (2026-08-25 — 위저드 1단계가 아이콘·색 배경 박스 대신 이 카드와 동일한 숫자 강조
 * 레이아웃을 재사용하도록 바뀌면서 분리됨). */
export function ReductionGauge({ pct }: { pct: number }) {
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
