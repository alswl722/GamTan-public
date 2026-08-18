"use client";

import type { MonthlyRow } from "@/lib/api";

/** 월별 배출 추이 — 연료별 스택 막대 + 부드러운 꺾은선 오버레이.
 *
 * 리포트(ScenePcaf.tsx)와 홈 화면 배출량 감축 목표 카드(GoalCard.tsx)가 완전히
 * 같은 컴포넌트를 쓴다(사용자 요청, 2026-08-18 — 두 화면의 시각 언어를 통일).
 * 데이터 재료도 같은 함수(db/pcaf_engine/pcaf.py::monthly_by_fuel)에서 나온다.
 */

// 연료 대분류(db/pcaf.py::_fuel_bucket과 동일 어휘) → 막대 색. scope1/scope2는
// 이미 "직접배출(연소)/간접배출(전기)" 의미로 쓰이는 색을 그대로 재사용하고,
// 경유/유류만 3번째 색(lime)을 새로 씀 — 하나의 색을 두 버킷이 나눠 쓰면
// 스택 막대에서 구분이 안 된다.
const FUEL_BAR_COLOR: Record<string, string> = {
  전기: "bg-scope2",
  가스: "bg-scope1",
  "경유/유류": "bg-lime",
  기타: "bg-faint",
};
const FUEL_ORDER = ["전기", "가스", "경유/유류", "기타"];
const CHART_HEIGHT_PX = 96;

// 점들을 부드러운 곡선으로 잇는 SVG path — Catmull-Rom 스플라인을 3차 베지어로
// 변환해서 그린다. 예전엔 "다음 점과의 중점까지만" 잇는 근사 기법(2차 베지어)을
// 썼는데, 이러면 한 달만 튀고 양옆이 0인 경우(실측 사례) 곡선 봉우리가 실제
// 막대 꼭대기까지 안 닿고 중간에서 눌려 보였다(2026-08-17, 막대 색이 꽉 차게
// 고쳐지면서 이 어긋남이 눈에 띄게 드러나 발견 — "선 그래프랑 다르잖아"). 이
// 방식은 모든 데이터 점을 정확히 지나가므로 막대 꼭대기와 곡선이 항상 일치한다.
function smoothLinePath(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0].x},${pts[0].y} L ${pts[0].x},${pts[0].y}`;
  if (pts.length === 2) return `M ${pts[0].x},${pts[0].y} L ${pts[1].x},${pts[1].y}`;

  const at = (i: number) => pts[Math.max(0, Math.min(pts.length - 1, i))];
  let d = `M ${pts[0].x},${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = at(i - 1);
    const p1 = at(i);
    const p2 = at(i + 1);
    const p3 = at(i + 2);
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = p1.y + (p2.y - p0.y) / 6;
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${cp1x},${cp1y} ${cp2x},${cp2y} ${p2.x},${p2.y}`;
  }
  return d;
}

export function MonthlyTrendChart({
  monthly,
  title = "월별 배출 추이",
}: {
  monthly: MonthlyRow[];
  title?: string;
}) {
  const maxTotal = Math.max(...monthly.map((m) => m.total_tco2e), 0.001);
  const fuelsPresent = new Set(monthly.flatMap((m) => Object.keys(m.by_fuel)));
  const fuels = FUEL_ORDER.filter((f) => fuelsPresent.has(f));

  // 막대 맨 위 중앙 좌표 — 꺾은선 오버레이용. x는 컨테이너 폭 대비 %(반응형 폭에
  // 맞춰 자동으로 따라감), y는 CHART_HEIGHT_PX 기준 고정 px(컨테이너 높이가
  // 고정값이라 DOM 측정 없이 계산 가능).
  const points = monthly.map((m, i) => {
    const barHeight = Math.max(2, Math.round((m.total_tco2e / maxTotal) * CHART_HEIGHT_PX));
    return { x: ((i + 0.5) / monthly.length) * 100, y: CHART_HEIGHT_PX - barHeight, barHeight };
  });

  const linePath = smoothLinePath(points);

  return (
    <div className="mt-3 rounded-2xl bg-surface p-5">
      <div className="text-[13px] font-semibold text-ink">{title}</div>

      <div
        className="relative mt-4 flex items-end justify-between gap-1"
        style={{ height: CHART_HEIGHT_PX }}
      >
        {monthly.map((m, i) => (
          <div key={m.month} className="flex flex-1 flex-col items-center justify-end">
            <div
              className="flex w-full flex-col-reverse overflow-hidden rounded-[3px] bg-line"
              style={{ height: points[i].barHeight }}
            >
              {fuels.map((f) => {
                const v = m.by_fuel[f] || 0;
                if (v <= 0 || m.total_tco2e <= 0) return null;
                // flex-grow(비율) 방식은 브라우저 devtools로 직접 재현 확인한 결과
                // grow 값이 1 미만인 소수(예: 0.41)일 때 "남는 공간을 전부 차지"가
                // 아니라 그 숫자를 컨테이너 대비 퍼센트처럼 그대로 써버리는 동작이
                // 나왔다(2026-08-17, 실측 — grow=1/100은 100% 채움, grow=0.41은
                // 정확히 41%만 채움. 형제 요소 없음도 콘솔로 확인해 다른 원인은
                // 배제됨). flex-grow 자체를 안 쓰고 이 연료가 그 달 총량에서 차지하는
                // 비율을 직접 계산해 height(%)로 넣는 방식으로 우회한다.
                const pct = (v / m.total_tco2e) * 100;
                return (
                  <div key={f} className={FUEL_BAR_COLOR[f]} style={{ height: `${pct}%` }} />
                );
              })}
            </div>
          </div>
        ))}

        {/* 꺾은선 오버레이 — 부드러운 곡선으로 막대 맨 위를 이어 총량 추이를
            한눈에 보여준다. */}
        <svg
          className="pointer-events-none absolute left-0 top-0 block"
          style={{ width: "100%", height: "100%" }}
          preserveAspectRatio="none"
          viewBox={`0 0 100 ${CHART_HEIGHT_PX}`}
        >
          <path
            d={linePath}
            fill="none"
            stroke="var(--color-brand)"
            strokeWidth={1.75}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div className="mt-1 flex justify-between text-[9px] text-faint">
        {monthly.map((m) => (
          <span key={m.month} className="flex-1 text-center">
            {m.month}
          </span>
        ))}
      </div>

      {fuels.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-3 text-[10.5px] text-muted">
          {fuels.map((f) => (
            <span key={f} className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${FUEL_BAR_COLOR[f]}`} /> {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
