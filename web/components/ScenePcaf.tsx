"use client";

import { useEffect, useState } from "react";
import { apiGet, COMPANY_ID } from "@/lib/api";
import { WireframeBadge } from "./WireframeBadge";

/** 장면 ④ — PCAF Before/After + 벤치마킹. /pcaf/{id} 실데이터 + 목업 폴백. */

// Tailwind 는 동적 조합 클래스(bg-pcaf-${n})를 못 잡으므로 완전한 문자열로 매핑.
const GRADE_BG: Record<number, string> = {
  1: "bg-pcaf-1",
  2: "bg-pcaf-2",
  3: "bg-pcaf-3",
  4: "bg-pcaf-4",
  5: "bg-pcaf-5",
};
const GRADE_BORDER: Record<number, string> = {
  1: "border-pcaf-1",
  2: "border-pcaf-2",
  3: "border-pcaf-3",
  4: "border-pcaf-4",
  5: "border-pcaf-5",
};
const GRADE_TEXT: Record<number, string> = {
  1: "text-pcaf-1",
  2: "text-pcaf-2",
  3: "text-pcaf-3",
  4: "text-pcaf-4",
  5: "text-pcaf-5",
};

function GradeBadge({ grade }: { grade: number }) {
  return (
    <span
      className={`grid h-11 w-11 place-items-center rounded-[10px] text-xl font-extrabold text-white ${GRADE_BG[grade]}`}
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
};
type PcafResponse = { before: Before; after: After | null; benchmark: Benchmark };

// 백엔드 미연결 시 폴백 (CLAUDE.md §8 기대효과 수치)
const MOCK: PcafResponse = {
  before: { grade: 5, scope1: 33.9, scope2: 18.1, emission_tco2e: 52.0 },
  after: {
    grade: 3,
    scope1: 22.1,
    scope2: 16.3,
    total: 38.4,
    measured_tco2e: 33.7,
    estimated_gap_tco2e: 4.7,
    hitl_count: 2,
    gap_months: [{ fuel: "가스", missing_months: [3, 4, 5] }],
  },
  benchmark: {
    industry_code: "C251",
    industry_name: "금속가공업",
    percentile_text: "동종 금속가공업 대비 상위 34%",
    hint: "가스 고지서 2장을 추가 연동하면 결손월 보정분이 실측으로 바뀌어 등급이 오릅니다.",
  },
};

const fmt = (n: number) => n.toFixed(1);

export function ScenePcaf() {
  const [data, setData] = useState<PcafResponse>(MOCK);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let alive = true;
    apiGet<PcafResponse>(`/pcaf/${COMPANY_ID}`)
      .then((res) => {
        if (!alive || !res?.before) return;
        setData(res);
        setLive(true);
      })
      .catch(() => {
        /* 폴백: 목업 유지 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const { before, after, benchmark } = data;

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">④ PCAF Before / After</h2>
        {live ? (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            실측 산정
          </span>
        ) : (
          <WireframeBadge />
        )}
      </div>
      <p className="mt-1 text-[13.5px] text-muted">
        기존 매출 추정({before.grade}등급 · 깜깜이)과 전표 기반 실측
        {after ? `(${after.grade}등급)` : ""}의 데이터 품질 비교입니다.
      </p>

      <div className="mt-[18px] grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-line p-[18px]">
          <div className="text-[11px] font-bold uppercase tracking-wide text-muted">
            Before · 기존 방식
          </div>
          <div className="mt-3 flex items-center gap-3">
            <GradeBadge grade={before.grade} />
            <div>
              <div className="text-[15px] font-bold">PCAF {before.grade}등급</div>
              <div className="text-[12.5px] text-muted">매출액 통계 대입 추정</div>
            </div>
          </div>
          <div className="mt-3.5 text-[13.5px] text-muted">
            추정 배출량{" "}
            <span className="font-bold text-ink tabular-nums">
              ~{fmt(before.emission_tco2e)} tCO₂e
            </span>{" "}
            · 오차 미인지
          </div>
        </div>

        {after ? (
          <div className={`rounded-lg border-2 p-[18px] ${GRADE_BORDER[after.grade]}`}>
            <div
              className={`text-[11px] font-bold uppercase tracking-wide ${GRADE_TEXT[after.grade]}`}
            >
              After · 본 엔진
            </div>
            <div className="mt-3 flex items-center gap-3">
              <GradeBadge grade={after.grade} />
              <div>
                <div className="text-[15px] font-bold">PCAF {after.grade}등급</div>
                <div className="text-[12.5px] text-muted">전표 기반 실측 산정</div>
              </div>
            </div>
            <div className="mt-3.5 text-[13.5px] text-muted">
              산정 배출량{" "}
              <span className="font-bold text-ink tabular-nums">
                {fmt(after.total)} tCO₂e
              </span>{" "}
              · Scope 1 {fmt(after.scope1)} · Scope 2 {fmt(after.scope2)}
              {after.hitl_count > 0 && (
                <span className="ml-1 text-scope1">· HITL {after.hitl_count}건</span>
              )}
            </div>
          </div>
        ) : (
          <div className="grid place-items-center rounded-lg border-2 border-dashed border-line p-[18px] text-center">
            <p className="text-[13.5px] text-muted">
              ③ AI 분류를 먼저 실행하면
              <br />
              전표 기반 실측 등급이 여기 표시됩니다.
            </p>
          </div>
        )}
      </div>

      <div className="mt-4 rounded-[10px] bg-brand-soft p-4 text-[13.5px]">
        <div className="font-bold text-brand-ink">동종 업종 벤치마킹</div>
        <p className="mt-1.5 text-[#2c4b45]">
          {benchmark.percentile_text ? (
            <>
              <span className="font-bold text-ink">{benchmark.percentile_text}</span>
              {benchmark.hint ? ` — ${benchmark.hint}` : ""}
            </>
          ) : (
            `${benchmark.industry_name ?? benchmark.industry_code} 벤치마킹은 분류 실행 후 산출됩니다.`
          )}
        </p>
      </div>
    </section>
  );
}
