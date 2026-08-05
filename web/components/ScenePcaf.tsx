"use client";

import { useEffect, useState } from "react";
import { apiGet, getCompanyId } from "@/lib/api";
import type { AlertItem } from "@/lib/admin-types";

/** 장면 ④ — PCAF Before/After + 벤치마킹. /pcaf/{id} 실데이터만 사용.
 *  API 실패 시 목업으로 위장하지 않고 에러 배너 + 재시도를 표시한다(실패 가시성). */

// PCAF 등급을 사장님이 바로 이해할 수 있는 한 줄 설명으로 매핑 (1=가장 정확 → 5=가장 부정확)
const GRADE_DESC: Record<number, string> = {
  1: "실측 데이터 기반, 가장 정확해요",
  2: "실측 데이터 기반, 매우 정확해요",
  3: "전표 기반 실측, 상당히 정확해요",
  4: "일부 추정이 섞여 있어요",
  5: "매출액만으로 추정한 값이에요",
};

function GradeChip({
  grade,
  accent = false,
}: {
  grade: number;
  accent?: boolean;
}) {
  return (
    <span
      className={`grid h-5 w-5 shrink-0 place-items-center rounded-md text-[11px] font-extrabold ${
        accent ? "bg-brand text-white" : "bg-line text-muted"
      }`}
    >
      {grade}
    </span>
  );
}

type Before = {
  grade: number;
  scope1: number;
  scope2: number;
  emission_tco2e: number;
};
type After = {
  grade: number;
  scope1: number;
  scope2: number;
  total: number;
  measured_tco2e: number;
  estimated_gap_tco2e: number;
  hitl_count: number;
  gap_months: { fuel: string; missing_months: number[] }[];
};
type Benchmark = {
  industry_code: string;
  industry_name: string | null;
  percentile_text: string | null;
  hint: string | null;
  value: number | null;
  min: number | null;
  median: number | null;
  max: number | null;
  percentile_pct: number | null;
};
type PcafResponse = { before: Before; after: After | null; benchmark: Benchmark };

const fmt = (n: number) => n.toFixed(1);

function EmissionBar({
  label,
  grade,
  value,
  maxValue,
  accent,
  improvedBy,
}: {
  label: string;
  grade: number;
  value: number;
  maxValue: number;
  accent: boolean;
  improvedBy?: number;
}) {
  const pct = Math.max(4, Math.round((value / maxValue) * 100));
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="flex items-center gap-1.5 font-semibold text-muted">
          <GradeChip grade={grade} accent={accent} />
          {label}
          {improvedBy && improvedBy > 0 && (
            <span className="rounded-full bg-brand-soft px-1.5 py-0.5 text-[10.5px] font-bold text-brand-ink">
              {improvedBy}단계 개선
            </span>
          )}
        </span>
        <span className="font-bold tabular-nums text-ink">
          {fmt(value)} <span className="font-normal text-faint">tCO₂e</span>
        </span>
      </div>
      <div className="mt-1.5 h-3.5 overflow-hidden rounded-full bg-bg">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${
            accent ? "bg-brand" : "bg-faint"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function DistributionTrack({
  min,
  max,
  value,
}: {
  min: number;
  max: number;
  value: number;
}) {
  const span = Math.max(max - min, 0.001);
  // 배출량이 적을수록 "상위" → 트랙은 진한(상위) → 연한(하위) 순으로 좌에서 우로 흐름
  const valuePct = Math.min(100, Math.max(0, ((value - min) / span) * 100));

  // 마운트 시 0%에서 시작해 실제 위치로 스윽 슬라이드 — transition은 값이
  // "변할 때"만 트리거되므로, 첫 페인트는 0%로 그린 뒤 다음 프레임에 목표
  // 위치로 옮겨 애니메이션을 강제로 발생시킨다.
  const [animatedPct, setAnimatedPct] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimatedPct(valuePct));
    return () => cancelAnimationFrame(id);
  }, [valuePct]);

  return (
    <div className="mt-3">
      <div
        className="relative h-2 rounded-full"
        style={{
          background:
            "linear-gradient(90deg, var(--color-brand) 0%, var(--color-brand-soft) 100%)",
        }}
      >
        <div
          className="absolute -top-[7px] -translate-x-1/2 transition-[left] duration-700 ease-out"
          style={{ left: `${animatedPct}%` }}
        >
          <svg width="12" height="8" viewBox="0 0 12 8" fill="none">
            <path d="M6 8L0.5 0H11.5L6 8Z" fill="var(--color-ink)" />
          </svg>
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11px] font-semibold text-faint">
        <span>상위</span>
        <span>하위</span>
      </div>
    </div>
  );
}

export function ScenePcaf() {
  const [data, setData] = useState<PcafResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  async function load() {
    setError(null);
    try {
      const cid = await getCompanyId();
      const res = await apiGet<PcafResponse>(`/pcaf/${cid}`);
      setData(res);
      // 이상 신호는 은행 담당자와 동일한 판정 로직(GET /admin/alerts와 같은
      // db/alerts.py::detect_alerts)을 자기 기업분만 조회 — 은행이 먼저 알고
      // 사장은 모르는 구도를 만들지 않는다(CLAUDE.md §9).
      apiGet<{ alerts: AlertItem[] }>(`/owner/alerts/${cid}`)
        .then((r) => setAlerts(r.alerts))
        .catch((err) => console.error("이상 신호 조회 실패(부가 정보라 화면은 계속 진행):", err));
    } catch (err) {
      // 목업으로 위장하지 않는다 — 실패는 실패로 표시
      console.error("PCAF 조회 실패:", err);
      setData(null);
      setError("산정 결과를 불러오지 못했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (!data) {
    return (
      <section>
        <h2 className="text-[17px] font-bold leading-snug text-ink">
          측정 결과를 불러오는 중이에요
        </h2>
        {error ? (
          <>
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
              {error}
            </div>
            <button
              type="button"
              onClick={() => void load()}
              className="btn-cta mt-4 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
            >
              다시 시도
            </button>
          </>
        ) : (
          <p className="mt-1 flex items-center gap-2 text-[13px] leading-relaxed text-muted">
            잠시만 기다려 주세요…
            <span className="flex gap-1">
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.3s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.15s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand" />
            </span>
          </p>
        )}
      </section>
    );
  }

  const { before, after, benchmark } = data;
  const maxValue = Math.max(before.emission_tco2e, after?.total ?? 0) * 1.05 || 1;
  const gradeUp = after ? before.grade - after.grade : 0;
  const hasDistribution =
    benchmark.value !== null &&
    benchmark.min !== null &&
    benchmark.median !== null &&
    benchmark.max !== null;

  return (
    <section>
      <span className="inline-block rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
        실측 산정
      </span>
      <h2 className="mt-3 text-[17px] font-bold leading-snug text-ink">
        측정이 끝났어요
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">
        기존 매출 추정 대비 데이터 품질이 얼마나 좋아졌는지 보여드려요.
      </p>

      {/* 배출량 막대 비교 — 등급·개선폭·수치를 한 그래프 안에서 함께 전달 */}
      <div className="mt-5 space-y-3.5 rounded-2xl bg-surface p-5">
        <EmissionBar
          label="Before · 매출액 통계 추정"
          grade={before.grade}
          value={before.emission_tco2e}
          maxValue={maxValue}
          accent={false}
        />
        {after ? (
          <EmissionBar
            label="After · 전표 기반 실측"
            grade={after.grade}
            value={after.total}
            maxValue={maxValue}
            accent
            improvedBy={gradeUp}
          />
        ) : (
          <div className="rounded-xl border-2 border-dashed border-line p-4 text-center text-[12.5px] text-muted">
            ③ AI 분류를 먼저 실행하면 실측 배출량이 표시됩니다
          </div>
        )}
        <p className="text-[11.5px] text-faint">
          {GRADE_DESC[after ? after.grade : before.grade]}
        </p>
        {after && (
          <div className="flex items-center justify-between border-t border-line pt-3 text-[11.5px] text-muted">
            <span>
              Scope1 <span className="font-semibold text-ink">{fmt(after.scope1)}</span> · Scope2{" "}
              <span className="font-semibold text-ink">{fmt(after.scope2)}</span>
            </span>
            {after.hitl_count > 0 && (
              <span className="rounded-md bg-hitl/25 px-2 py-0.5 font-semibold text-hitl-ink">
                검토 예정 {after.hitl_count}건
              </span>
            )}
          </div>
        )}
      </div>

      <div className="mt-3 rounded-2xl bg-surface p-5">
        {hasDistribution ? (
          <>
            <p className="text-[12px] font-semibold text-muted">
              동종 {benchmark.industry_name ?? benchmark.industry_code} 대비
              배출량
            </p>
            <p className="mt-0.5 text-[16px] font-bold text-ink">
              상위 <span className="text-brand-ink">{benchmark.percentile_pct}%</span>
              입니다
            </p>
            <DistributionTrack
              min={benchmark.min!}
              max={benchmark.max!}
              value={benchmark.value!}
            />
            {benchmark.hint && (
              <p className="mt-3 text-[12.5px] leading-relaxed text-muted">
                {benchmark.hint}
              </p>
            )}
          </>
        ) : (
          <>
            <div className="text-[12px] font-semibold text-muted">
              동종 업종 벤치마킹 · {benchmark.industry_name ?? benchmark.industry_code}
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
              벤치마킹은 분류 실행 후 산출됩니다.
            </p>
          </>
        )}
      </div>

      {alerts.length > 0 && (
        <div className="mt-3 space-y-2 rounded-2xl bg-surface p-5">
          <div className="text-[13px] font-semibold text-ink">이상 신호 알림</div>
          <p className="text-[11.5px] leading-relaxed text-faint">
            은행 담당자에게도 같은 시점에 안내되는 신호예요. 여신 결정과는 무관하며,
            참고용 안내입니다.
          </p>
          {alerts.map((a) => (
            <div
              key={`${a.type}-${a.month}`}
              className="rounded-xl bg-bg px-3.5 py-2.5 text-[12.5px] leading-relaxed text-muted"
            >
              {a.message}
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 rounded-2xl bg-surface p-5 text-center">
        <div className="text-[13px] font-semibold text-ink">
          우대금리 대상 안내
        </div>
        <p className="mt-1 text-[12.5px] text-muted">
          PCAF {after ? after.grade : before.grade}등급 기준, 담당 은행원과의
          상담을 통해 우대금리 자격을 확인할 수 있어요.
        </p>
      </div>
    </section>
  );
}
