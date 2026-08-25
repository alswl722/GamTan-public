/** 탄소중립포인트 화면이 공유하는 **제도 상수와 순수 계산**.
 *
 * 이 파일은 `web/lib/carbon-point-fixture.ts`의 후신이다. fixture는 2026-08-25에 실제
 * API(§9.1)로 교체되며 삭제됐지만, 그 안에 섞여 있던 제도 상수(임계값·포인트 단가·인센티브
 * 구간표)와 환급액 계산은 임시 대역이 아니라 계속 필요한 것들이라 여기로 옮겼다.
 * API 응답 타입과 fetch 함수는 `web/lib/api.ts`로 갔다.
 *
 * 여기 있는 것은 전부 결정론적이다 — 감축률에서 환급액을 얻는 계산은 구간표 조회일 뿐이라
 * 백엔드를 왕복할 이유가 없다. 대신 **감축률 자체는 절대 프론트에서 계산하지 않는다**
 * (CLAUDE.md 원칙1과 같은 결 — 사용량 집계·감축률은 백엔드 순수 함수의 몫이다).
 */

/** 탄소중립포인트 에너지분야 자격 임계값(data-plan §6.2).
 * 백엔드 `db/carbon_neutral_point.py::THRESHOLD_PCT`와 같은 값이어야 한다. */
export const CARBON_POINT_THRESHOLD_PCT = 5;

/** 게이지 눈금의 상한 — 감축률을 "기준(5%) 대비 어디까지 왔는지"로 보여주기 위한
 * 표시용 스케일이라 제도상 상한이 아니다(15% 이상은 한 구간으로 묶여 있다). */
export const CARBON_POINT_GAUGE_MAX_PCT = 10;

/** 「탄소중립포인트 제도 운영에 관한 규정」 별표2 — 에너지 분야 **상업(법인)** 기준
 * 전기 감축 인센티브. 소상공인은 개인이 아니라 이 표를 적용받는다(cpoint.or.kr). */
const ELECTRICITY_POINT_TIERS: readonly { minPct: number; points: number }[] = [
  { minPct: 15, points: 60_000 },
  { minPct: 10, points: 40_000 },
  { minPct: CARBON_POINT_THRESHOLD_PCT, points: 20_000 },
];

/** 포인트 단가 — **대구시 적용 단가 1.4원**(2025년 하반기에 1원에서 인상).
 * data-plan.md §15.1·develop-plan.md §2.6이 근거이며, 2026-08-22에 이 값으로 확정했다.
 *
 * 규정상 1포인트의 상한은 2원이지만 그건 지자체가 그 이하로 정하도록 한 **한도**일 뿐이고,
 * 우리 대상 지역(대구)의 실제 단가는 1.4원이다 — 상한을 그대로 쓰면 사장님에게 받을 금액을
 * 과대 안내하게 되므로(data-plan §3.3 과장 방지) 실제 단가를 쓴다.
 *
 * 화면 문구도 이 상수를 참조한다 — 숫자를 컴포넌트에 하드코딩하면 단가가 바뀔 때
 * 계산값과 라벨이 어긋난다(실제로 그렇게 어긋나 있던 것을 고친 것이다). */
export const KRW_PER_POINT = 1.4;

export interface CarbonPointRefundEstimate {
  points: number;
  /** 포인트 × 단가. 단가가 정수가 아니라 부동소수 잔재가 남을 수 있어 원 단위로 반올림한다. */
  krw: number;
}

/** 감축률 → 예상 환급액. 임계값 미만이거나 감축률을 계산하지 못했으면 null —
 * 0원으로 표시해 "받을 게 없다"와 "아직 모른다"를 뭉개지 않는다(CLAUDE.md 원칙7). */
export function estimateRefund(reductionRatePct: number | null): CarbonPointRefundEstimate | null {
  if (reductionRatePct === null) return null;
  const tier = ELECTRICITY_POINT_TIERS.find((t) => reductionRatePct >= t.minPct);
  if (!tier) return null;
  return { points: tier.points, krw: Math.round(tier.points * KRW_PER_POINT) };
}
