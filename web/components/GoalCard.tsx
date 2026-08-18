"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import {
  getDocumentGrid,
  type CompanyGoal,
  type DocumentGridResponse,
  type MonthlyCoveragePoint,
  type RateMissingItem,
} from "@/lib/api";
import { MonthlyTrendChart } from "@/components/MonthlyTrendChart";

/** 홈 화면의 "탄소 측정하러 가기" 박스 자리 — 5단계 위저드가 끝나면(doneCount===5)
 * 이 박스가 대신 뜬다. 활성 목표가 없으면 설정 유도 프롬프트를, 있으면 큰 링 +
 * 월별 막대 차트로 구성된 진행 카드를 보여준다(걸음수 앱 레퍼런스 참고, 사용자
 * 요청 2026-08-18) — 다만 두 목표 타입의 "진행" 성격이 달라 링이 의미하는 값이
 * 다르다: 등급 목표는 completeness_pct(서류 채울 때마다 실제로 오름), 감축 목표는
 * "다음 측정 전엔 비교 대상 자체가 없다"는 원칙을 지키기 위해 measured=false일 땐
 * 링을 채우지 않고 목표 감축률만 숫자로 보여준다(가짜 진행률 금지). */

const SCOPE_LABEL: Record<string, string> = { scope_1: "Scope 1", scope_2: "Scope 2" };

const RING_SIZE = 104;
const RING_STROKE = 10;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
const RING_GRADIENT_ID = "goal-ring-gradient";

function GoalRing({ pct, bigText }: { pct: number; bigText: string }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const offset = RING_CIRCUMFERENCE * (1 - clamped / 100);
  return (
    <div className="relative shrink-0" style={{ width: RING_SIZE, height: RING_SIZE }}>
      <svg width={RING_SIZE} height={RING_SIZE} className="-rotate-90">
        <defs>
          <linearGradient id={RING_GRADIENT_ID} x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--color-brand)" />
            <stop offset="100%" stopColor="var(--color-lime)" />
          </linearGradient>
        </defs>
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RING_RADIUS}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth={RING_STROKE}
        />
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RING_RADIUS}
          fill="none"
          stroke={clamped > 0 ? `url(#${RING_GRADIENT_ID})` : "transparent"}
          strokeWidth={RING_STROKE}
          strokeLinecap="round"
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center px-2 text-center">
        <span className="text-[20px] font-extrabold leading-none text-ink">{bigText}</span>
      </div>
    </div>
  );
}

/** 직전달 번호(1~12) — 오늘이 1월이면 작년 12월이 직전달이지만, 이 카드는 항상 이번
 * 해 문서 그리드만 조회한다(연도 경계는 흔치 않은 엣지 케이스라 범위 밖으로 둠). */
function previousMonthNumber(): number {
  const thisMonth = new Date().getMonth() + 1;
  return thisMonth === 1 ? 12 : thisMonth - 1;
}

/** 데이터 업로드 탭(web/app/owner/uploads/page.tsx)의 도장칸과 같은 시각 언어 —
 * 채워지면 carbon_stamp.png, 비어있으면 점선 테두리 + 점. 여기선 "직전달"이라는
 * 한 칸만 문서종류별로 보여준다(그리드 전체가 아니라 최근 한 달 스냅숏). */
function StampCell({ label, filled }: { label: string; filled: boolean }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span
        className={`flex h-12 w-12 items-center justify-center rounded-full border-2 ${
          filled ? "border-brand bg-brand-soft" : "border-dashed border-line bg-bg"
        }`}
      >
        {filled ? (
          <Image
            src="/carbon_stamp.png"
            alt="업로드 완료 도장"
            width={56}
            height={56}
            className="h-11 w-11 -rotate-6 object-contain"
          />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-line" />
        )}
      </span>
      <span className={`text-[8px] font-semibold leading-none ${filled ? "text-ink" : "text-faint"}`}>
        {label}
      </span>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-faint">{label}</div>
      <div className="mt-0.5 text-[16.5px] font-extrabold text-ink">{value}</div>
    </div>
  );
}

/** 월별 막대 — 등급 목표의 monthly_coverage(채움/결손 이진값) 전용. 배출량 감축
 * 목표는 리포트와 동일한 MonthlyTrendChart(연료별 스택 막대+꺾은선)를 쓴다(사용자
 * 요청, 2026-08-18) — "채움 여부"만 있는 등급 목표는 배출량 성격이 아니라 이
 * 단순 막대를 그대로 유지한다. 값이 없는 달도 얇은 회색 막대로 남겨 x축이 끊기지
 * 않게 한다(레퍼런스의 "아직 안 온 시간대" 막대와 같은 결). */
function MonthlyBars({ items }: { items: { month: number; value: number; filled: boolean }[] }) {
  if (items.length === 0) return null;
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="mt-4 flex items-end gap-[3px]" style={{ height: 52 }}>
      {items.map((item) => {
        const heightPct = item.filled ? Math.max(14, (item.value / max) * 100) : 6;
        return (
          <div key={item.month} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
            <div
              className={`w-full rounded-full ${
                item.filled ? "bg-gradient-to-t from-brand to-lime" : "bg-line"
              }`}
              style={{ height: `${heightPct}%` }}
            />
            <span className="text-[8.5px] font-semibold text-faint">{item.month}</span>
          </div>
        );
      })}
    </div>
  );
}

function coverageBars(points: MonthlyCoveragePoint[] | undefined) {
  return (points ?? []).map((p) => ({ month: p.month, value: p.covered ? 1 : 0, filled: p.covered }));
}

/** [4,5,6,9] → [{start:4,end:6},{start:9,end:9}] — 칩 개수를 줄이기 위한 구간 묶기
 * (RateProductCard.tsx와 같은 목적, 이 프로젝트가 이미 쓰는 소규모 헬퍼 복제 관례). */
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

function GoalChecklist({ items }: { items: RateMissingItem[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5">
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
              className="flex items-center gap-1.5 text-[12px] text-brand-ink underline decoration-dotted underline-offset-2"
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-line" />
              {label} 업로드하기
            </Link>
          );
        })
      )}
    </div>
  );
}

function GoalProgressCard({
  goal,
  companyId,
  onEdit,
}: {
  goal: CompanyGoal;
  companyId: number;
  onEdit: () => void;
}) {
  const achieved = goal.status === "achieved";
  const scopeLabel = SCOPE_LABEL[goal.scope_group ?? ""] ?? "";
  const isEmission = goal.goal_type === "emission_reduction";

  // 감축 목표 카드에만 쓰는 "직전달 서류 도장칸" — 문서 그리드는 이 카드에서만 필요해
  // 등급 목표일 땐 조회하지 않는다.
  const [grid, setGrid] = useState<DocumentGridResponse | null>(null);
  useEffect(() => {
    if (!isEmission) return;
    let cancelled = false;
    getDocumentGrid(companyId)
      .then((r) => {
        if (!cancelled) setGrid(r);
      })
      .catch((err) => console.error("문서 업로드 현황 조회 실패:", err));
    return () => {
      cancelled = true;
    };
  }, [isEmission, companyId]);

  const prevMonth = previousMonthNumber();
  const taxInvoiceFilled =
    (grid?.document_types.find((r) => r.document_type === "tax_invoice")?.months[String(prevMonth)] ?? 0) > 0;
  const electricBillFilled =
    (grid?.document_types.find((r) => r.document_type === "electric_bill")?.months[String(prevMonth)] ?? 0) > 0;

  const ringPct = isEmission ? (goal.measured ? goal.progress_pct : 0) : goal.progress_pct;
  const ringBigText = isEmission
    ? goal.measured
      ? `${Math.round(goal.progress_pct)}%`
      : `${goal.target_reduction_pct}%`
    : `${Math.round(goal.progress_pct)}%`;
  const ringCaption = isEmission ? (goal.measured ? "감축 진행률" : "목표 감축률") : "데이터 완전성";

  // "최근"·"현재" 값은 다음 측정 전엔 목표 설정 시점 기준값이 곧 가장 최근에 확인된
  // 값이다(원칙7 — 없는 값을 지어내지 않고 마지막으로 확인된 값을 그대로 보여줌).
  const recentEmission = goal.measured && goal.current_value != null ? goal.current_value : goal.baseline_value;
  const currentGrade = goal.current_value ?? goal.baseline_value;

  return (
    <div className="mt-5 rounded-3xl bg-surface px-5 pb-4 pt-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="block text-[12px] font-bold text-brand-ink">
            {achieved ? "목표 달성" : "내 목표"}
          </span>
          <span className="mt-1 block text-[15.5px] font-extrabold leading-snug text-ink">
            {isEmission ? `배출량 ${goal.target_reduction_pct}% 감축하기` : `${scopeLabel} 등급 올리기`}
          </span>
        </div>
        <button
          type="button"
          onClick={onEdit}
          className="flex shrink-0 items-center gap-0.5 pt-0.5 text-[11.5px] font-semibold text-muted"
        >
          목표 변경
          <ChevronRight size={13} className="text-faint" />
        </button>
      </div>

      <div className="mt-4 flex items-start gap-4">
        <div className="flex flex-col items-center gap-1.5 pt-2.5">
          <span className="text-[11px] font-semibold text-faint">{ringCaption}</span>
          <GoalRing pct={ringPct} bigText={ringBigText} />
        </div>
        <div className="mt-2.5 w-px shrink-0 self-stretch bg-line" />
        <div className="flex flex-1 flex-col justify-center gap-3 pt-2.5">
          {isEmission ? (
            <>
              <StatRow label="최근 배출량" value={`${recentEmission}tCO2e`} />
              <StatRow label="목표 배출량" value={`${goal.target_value}tCO2e`} />
            </>
          ) : (
            <>
              <StatRow label="현재 등급" value={`${currentGrade}등급`} />
              <StatRow label="목표 등급" value={`${goal.target_value}등급`} />
            </>
          )}
        </div>

        {isEmission && (
          <>
            <div className="mt-2.5 w-px shrink-0 self-stretch bg-line" />
            <div className="flex shrink-0 flex-col items-center gap-1.5 self-stretch pt-2.5">
              <span className="text-[11px] font-semibold text-faint">저번달 서류</span>
              <div className="flex flex-1 items-center gap-2.5">
                <StampCell label="세금계산서" filled={taxInvoiceFilled} />
                <StampCell label="전기고지서" filled={electricBillFilled} />
              </div>
            </div>
          </>
        )}
      </div>

      {isEmission ? (
        goal.monthly_emission_detail && goal.monthly_emission_detail.length > 0 && (
          <MonthlyTrendChart monthly={goal.monthly_emission_detail} />
        )
      ) : (
        <MonthlyBars items={coverageBars(goal.monthly_coverage)} />
      )}

      {!isEmission && !achieved && <GoalChecklist items={goal.missing_items} />}

      {!isEmission && goal.target_product_name && (
        <p className="mt-3 text-[11px] leading-relaxed text-faint">
          목표를 채우면 {goal.target_product_name} 우대금리 안내 대상이 돼요.
        </p>
      )}

      {goal.disclaimer_text && (
        <p className="mt-2 text-[10.5px] leading-relaxed text-faint">{goal.disclaimer_text}</p>
      )}
    </div>
  );
}

function GoalSetupPrompt({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="btn-cta mt-5 flex w-full items-center justify-between gap-3 rounded-3xl bg-surface px-5 py-5 text-left shadow-card transition-transform"
    >
      <span>
        <span className="block text-[12px] font-bold text-brand-ink">목표 설정</span>
        <span className="mt-1 block text-[16px] font-extrabold leading-snug text-ink">
          비어있는 박스에
          <br />
          목표를 설정해보세요
        </span>
      </span>
      <ChevronRight size={18} className="shrink-0 text-faint" />
    </button>
  );
}

export function GoalBox({
  goal,
  companyId,
  onOpenSheet,
}: {
  goal: CompanyGoal | null;
  companyId: number;
  onOpenSheet: () => void;
}) {
  if (goal === null) return <GoalSetupPrompt onOpen={onOpenSheet} />;
  return <GoalProgressCard goal={goal} companyId={companyId} onEdit={onOpenSheet} />;
}
