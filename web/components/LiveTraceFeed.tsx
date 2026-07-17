"use client";

import { useEffect, useRef, useState } from "react";

/**
 * 랜딩 히어로의 시그니처 요소 — 가짜 데모 로그가 아니라 실제 오케스트레이터가
 * trace_logs에 쓰는 [계획]/[관찰]/[행동] 포맷과 ○○정밀 데모 시나리오를
 * 그대로 재생한다. 장면②(SceneTrace)를 미리 보여주는 셈.
 */

type StepType = "계획" | "관찰" | "행동";

const STEP_ICON: Record<StepType, string> = {
  계획: "◇",
  관찰: "◎",
  행동: "▶",
};

const STEP_DOT: Record<StepType, string> = {
  계획: "bg-faint",
  관찰: "bg-scope2",
  행동: "bg-brand",
};

type LogLine = { type: StepType; tool: string; message: string };

const SCRIPT: LogLine[] = [
  { type: "계획", tool: "", message: "12개월 전표 분석 시작 → 결손 검사를 먼저 수행" },
  { type: "관찰", tool: "마이데이터 수집기", message: "전표 33건 수집 완료 — 3~5월 도시가스 0건 확인" },
  { type: "행동", tool: "알림 생성기", message: "사장님 알림 발송 + 업종 평균으로 임시 보정" },
  { type: "행동", tool: "전표 분류기", message: "'지게차 경유 외 1종' → Scope 1·이동연소 (신뢰도 0.93)" },
  { type: "관찰", tool: "이상치 검증기", message: "7월 경유 사용량이 업종 중앙값의 3.2배 — 이상치 의심" },
  { type: "행동", tool: "전표 재파싱기", message: "'지게차 2대 증차' 확인 → 정상 판정" },
  { type: "행동", tool: "계산·PCAF 엔진", message: "매출추정 5등급 → 전표기반 2등급 산정 완료" },
];

const BASE_SECONDS = 9 * 3600 + 41 * 60; // 09:41:00 — 고정 합성 시각(하이드레이션 안전)

function fmtClock(stepIndex: number, cycle: number) {
  const total = BASE_SECONDS + cycle * 34 + stepIndex * 4;
  const h = Math.floor(total / 3600) % 24;
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

const TICK_MS = 2200;

export function LiveTraceFeed() {
  const [count, setCount] = useState(2);
  const [cycle, setCycle] = useState(0);
  const [paused, setPaused] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setCount(SCRIPT.length);
      return;
    }
    if (paused) return;
    const id = setInterval(() => {
      setCount((c) => {
        if (c >= SCRIPT.length) {
          setCycle((cy) => cy + 1);
          return 2;
        }
        return c + 1;
      });
    }, TICK_MS);
    return () => clearInterval(id);
  }, [paused]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [count]);

  const rows = SCRIPT.slice(0, count);

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className="w-full max-w-md overflow-hidden rounded-3xl border border-line bg-surface shadow-card"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
          </span>
          <span className="text-[11.5px] font-bold tracking-wide text-ink">
            실시간 판단 로그
          </span>
          <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-semibold text-brand-ink">
            ○○정밀
          </span>
        </div>
        <button
          type="button"
          onClick={() => {
            setCount(2);
            setCycle((c) => c + 1);
          }}
          aria-label="처음부터 다시 재생"
          className="rounded-full p-1.5 text-faint transition-colors hover:bg-bg hover:text-muted"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <path d="M3 4v5h5" />
          </svg>
        </button>
      </div>

      <ol
        ref={listRef}
        className="h-[300px] space-y-0 overflow-y-auto px-4 py-3.5"
      >
        {rows.map((row, i) => {
          const last = i === rows.length - 1;
          return (
            <li
              key={`${cycle}-${i}`}
              className="step-enter relative flex gap-3 pb-4 last:pb-0"
            >
              {!last && (
                <span className="absolute left-[7px] top-4 h-full w-px bg-line" />
              )}
              <span
                className={`relative z-10 mt-0.5 grid h-[15px] w-[15px] shrink-0 place-items-center rounded-full text-[8px] text-white ${STEP_DOT[row.type]}`}
              >
                {STEP_ICON[row.type]}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10.5px] font-bold text-ink">{row.type}</span>
                  {row.tool && (
                    <span className="rounded bg-bg px-1.5 py-0.5 font-mono text-[9.5px] text-muted">
                      {row.tool}
                    </span>
                  )}
                  <span className="ml-auto font-mono text-[10px] text-faint">
                    {fmtClock(i, cycle)}
                  </span>
                </div>
                <p className="mt-1 text-[12.5px] leading-snug text-ink">
                  {row.message}
                </p>
              </div>
            </li>
          );
        })}
        {count < SCRIPT.length && (
          <li className="flex items-center gap-2 pl-6 text-[11px] text-faint">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" />
            </span>
            판단 중…
          </li>
        )}
      </ol>
    </div>
  );
}
