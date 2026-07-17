"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

/** 포트폴리오 금융배출량 집계 — 거래 기업 전체 Scope 1/2 + PCAF 등급 분포. */

type Company = {
  company_id: number;
  company_name: string;
  industry_name: string | null;
  grade: number;
  measured: boolean;
  scope1: number;
  scope2: number;
  total: number;
  hitl_count: number;
};

type Portfolio = {
  company_count: number;
  scope1_total: number;
  scope2_total: number;
  total: number;
  grade_distribution: Record<string, number>;
  hitl_total: number;
  companies: Company[];
};

function GradeChip({ grade }: { grade: number }) {
  // 2~3등급(실측 기반)은 브랜드, 5등급(추정)은 경고 톤으로 구분
  const good = grade <= 3;
  return (
    <span
      className={`rounded-md px-1.5 py-0.5 text-[11px] font-bold ${
        good ? "bg-brand-soft text-brand-ink" : "bg-hitl/25 text-hitl-ink"
      }`}
    >
      PCAF {grade}등급
    </span>
  );
}

export function PortfolioPanel() {
  const [data, setData] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    apiGet<Portfolio>("/admin/portfolio")
      .then(setData)
      .catch((err) => {
        console.error("포트폴리오 집계 조회 실패:", err);
        setError("집계 데이터를 불러오지 못했습니다. 서버 연결을 확인해 주세요.");
      });
  }

  useEffect(load, []);

  if (error) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-6">
        <div className="mb-3 rounded-xl bg-hitl/25 px-3 py-2 text-[12px] text-hitl-ink">
          {error}
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white hover:bg-brand-ink"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="grid h-40 place-items-center rounded-2xl border border-line bg-surface text-[13px] text-muted">
        집계 중…
      </div>
    );
  }

  const grades = [2, 3, 4, 5];

  return (
    <div className="rounded-2xl border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-bold text-ink">포트폴리오 금융배출량</h2>
          <p className="mt-0.5 text-[12.5px] text-muted">
            거래 기업 전체 Scope 1/2 합산 (전표 기반 실측 우선)
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-bg px-2.5 py-1 text-[11px] font-semibold text-muted">
          기업 {data.company_count}곳
        </span>
      </div>

      {/* 총 배출량 */}
      <div className="mt-5 grid grid-cols-3 gap-3">
        {[
          { l: "Scope 1 (직접)", v: data.scope1_total, c: "text-ink" },
          { l: "Scope 2 (간접)", v: data.scope2_total, c: "text-ink" },
          { l: "합계 tCO₂e", v: data.total, c: "text-brand-ink" },
        ].map((m) => (
          <div key={m.l} className="rounded-xl bg-bg p-3.5">
            <div className="text-[11px] font-semibold text-faint">{m.l}</div>
            <div className={`mt-1 text-[19px] font-extrabold tabular-nums ${m.c}`}>
              {m.v.toLocaleString(undefined, { maximumFractionDigits: 1 })}
            </div>
          </div>
        ))}
      </div>

      {/* PCAF 등급 분포 */}
      <div className="mt-5">
        <div className="mb-2 text-[12px] font-semibold text-muted">
          PCAF 데이터 품질 등급 분포
        </div>
        <div className="space-y-1.5">
          {grades.map((g) => {
            const n = data.grade_distribution[String(g)] ?? 0;
            const pct = data.company_count > 0 ? (n / data.company_count) * 100 : 0;
            return (
              <div key={g} className="flex items-center gap-2.5">
                <span className="w-14 shrink-0 text-[11.5px] font-semibold text-muted">
                  {g}등급
                </span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                  <span
                    className={`block h-full ${g <= 3 ? "bg-brand" : "bg-hitl-ink"}`}
                    style={{ width: `${Math.max(pct, n > 0 ? 6 : 0)}%` }}
                  />
                </span>
                <span className="w-8 shrink-0 text-right text-[11.5px] font-semibold tabular-nums text-ink">
                  {n}곳
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 기업별 내역 */}
      <div className="mt-5 space-y-2">
        {data.companies.map((c) => (
          <div
            key={c.company_id}
            className="flex items-center justify-between gap-3 rounded-xl bg-bg px-3.5 py-3"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-[13.5px] font-bold text-ink">
                  {c.company_name}
                </span>
                <GradeChip grade={c.grade} />
                {!c.measured && (
                  <span className="rounded-md border border-line px-1.5 py-0.5 text-[10px] text-faint">
                    기준선 추정
                  </span>
                )}
              </div>
              <div className="mt-0.5 truncate text-[11.5px] text-muted">
                {c.industry_name ?? "업종 미상"}
                {c.hitl_count > 0 && (
                  <span className="ml-1.5 text-hitl-ink">· 검토 {c.hitl_count}건</span>
                )}
              </div>
            </div>
            <span className="shrink-0 text-[14px] font-extrabold tabular-nums text-ink">
              {c.total.toLocaleString(undefined, { maximumFractionDigits: 1 })}
              <span className="ml-0.5 text-[11px] font-semibold text-faint">tCO₂e</span>
            </span>
          </div>
        ))}
      </div>

      {/* 정직 표기 — 없는 걸 있는 척 안 함 (실패 가시성과 같은 결) */}
      {data.company_count <= 1 && (
        <p className="mt-4 rounded-lg border border-dashed border-line bg-bg px-3 py-2 text-[11.5px] leading-relaxed text-faint">
          ⓘ v0.1 데모는 시연 기업 1곳 기준입니다. 동일 집계 로직이 결선에서 거래 기업
          포트폴리오 전체로 그대로 확장됩니다.
        </p>
      )}
    </div>
  );
}
