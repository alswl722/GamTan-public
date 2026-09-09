"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getCompanyId,
  getOwnerBriefing,
  type BriefingFuelStat,
  type MonthlyBriefing,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// 월간 AI 브리핑 — Figma "⑧ 월간 AI 브리핑" 시안. 우디가 이번 달 결제·사용량을
// 편지 형식으로 전달한다. 문장(paragraphs)은 백엔드가 결정론적으로 조립해
// 내려준 것 — 프론트는 그대로 렌더만 한다(LLM 미사용).

function directionIcon(direction: BriefingFuelStat["direction"]): string {
  if (direction === "up") return "▲";
  if (direction === "down") return "▼";
  if (direction === "new") return "●";
  return "–";
}

function directionColor(direction: BriefingFuelStat["direction"]): string {
  if (direction === "up") return "text-hitl-ink";
  if (direction === "down") return "text-brand-ink";
  return "text-muted";
}

export default function MonthlyBriefingPage() {
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [cursor, setCursor] = useState<{ year: number; month: number } | null>(null);
  const [data, setData] = useState<MonthlyBriefing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCompanyId()
      .then((cid) => {
        setCompanyId(cid);
        const now = new Date();
        setCursor({ year: now.getFullYear(), month: now.getMonth() + 1 });
      })
      .catch((err) => {
        console.error("기업 정보 조회 실패:", err);
        setError("기업 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
  }, []);

  useEffect(() => {
    if (companyId === null || cursor === null) return;
    let cancelled = false;
    getOwnerBriefing(companyId, cursor.year, cursor.month)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("브리핑 조회 실패:", err);
        setError("브리핑을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, cursor]);

  // data가 지금 보려는 달(cursor)의 응답인지로 로딩 여부를 판단 — effect 안에서
  // setData(null)을 직접 호출하지 않는다(react-hooks/set-state-in-effect).
  const isLoadingCurrentMonth =
    cursor !== null && (!data || data.year !== cursor.year || data.month !== cursor.month);

  function shiftMonth(delta: number) {
    setCursor((prev) => {
      if (!prev) return prev;
      const d = new Date(prev.year, prev.month - 1 + delta, 1);
      return { year: d.getFullYear(), month: d.getMonth() + 1 };
    });
  }

  const now = new Date();
  const isCurrentMonth =
    cursor !== null && cursor.year === now.getFullYear() && cursor.month === now.getMonth() + 1;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      <div className="pt-5">
        <Link
          href="/owner/calendar"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-faint transition-colors hover:text-ink"
        >
          ← 탄소 캘린더로
        </Link>
      </div>

      <h1 className="mt-4 text-[17px] font-bold leading-snug text-ink">월간 AI 브리핑</h1>

      {error ? (
        <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
          {error}
        </div>
      ) : !cursor || isLoadingCurrentMonth || !data ? (
        <p className="mt-4 text-[13px] text-faint">불러오는 중…</p>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          <div>
            <p className="text-[12px] font-bold text-brand-ink">
              우디가 이번 달 소식을 전해드려요
            </p>
            <p className="text-[20px] font-extrabold text-ink">
              {cursor.year}년 {cursor.month}월 브리핑
            </p>
          </div>

          <div className="overflow-hidden rounded-3xl bg-surface shadow-card">
            <div className="flex items-start gap-2.5 px-5 pb-4 pt-5">
              <Image
                src="/woodi_letter_1.png"
                alt="우디"
                width={624}
                height={830}
                className="h-16 w-auto shrink-0 object-contain"
              />
              <div className="flex-1 rounded-2xl bg-brand-soft px-3.5 py-2.5">
                <p className="text-[13px] font-bold text-brand-ink">안녕하세요, 사장님!</p>
                <p className="text-[12px] text-brand-ink">
                  {cursor.month}월 한 달 동안의 이야기를 들려드릴게요 🍃
                </p>
              </div>
            </div>

            <div className="h-px bg-line" />

            <div className="flex flex-col gap-3.5 px-5 py-4">
              {data.paragraphs.map((p, i) => (
                <p key={i} className="text-[14px] leading-relaxed text-ink">
                  {p}
                </p>
              ))}

              {data.fuel_stats.length > 0 && (
                <div className="flex gap-2">
                  {data.fuel_stats.map((s) => (
                    <div key={s.fuel_type} className="flex-1 rounded-xl bg-bg px-3 py-2.5">
                      <span className="flex items-center gap-1">
                        <span className={cn("text-[10px] font-bold", directionColor(s.direction))}>
                          {directionIcon(s.direction)}
                        </span>
                        <span className="text-[10px] font-bold text-muted">{s.fuel_type}</span>
                      </span>
                      <p className="mt-0.5 text-[14px] font-bold text-ink">
                        {s.direction === "new" || s.delta_pct === null
                          ? `${s.this_month_co2e.toFixed(1)} tCO2e`
                          : `${s.delta_pct > 0 ? "+" : ""}${s.delta_pct.toFixed(0)}%`}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <Link
            href="/owner/report"
            className="btn-cta flex items-center justify-center rounded-2xl bg-brand py-3.5 text-[14px] font-bold text-white transition-transform"
          >
            이번 달 탄소 리포트 자세히 보기
          </Link>

          <div className="flex items-center justify-between px-1">
            <button
              type="button"
              onClick={() => shiftMonth(-1)}
              className="flex items-center gap-1 text-[12px] font-bold text-muted"
            >
              ‹ {cursor.month === 1 ? 12 : cursor.month - 1}월 브리핑
            </button>
            {isCurrentMonth ? (
              <span className="text-[11px] text-faint">최신 브리핑이에요</span>
            ) : (
              <button
                type="button"
                onClick={() => shiftMonth(1)}
                className="flex items-center gap-1 text-[12px] font-bold text-muted"
              >
                {cursor.month === 12 ? 1 : cursor.month + 1}월 브리핑 ›
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
