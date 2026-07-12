"use client";

import { useEffect, useState } from "react";
import { apiGet, COMPANY_ID } from "@/lib/api";
import { WireframeBadge } from "./WireframeBadge";

/** 장면 ② — 에이전트 트레이스 뷰 (킬러씬 A). /trace/latest 실데이터 + 목업 폴백. */

type StepType = "계획" | "관찰" | "행동";

const STEP_STYLE: Record<StepType, { dot: string; chip: string; icon: string }> =
  {
    계획: { dot: "bg-plan", chip: "bg-plan/10 text-plan", icon: "◇" },
    관찰: { dot: "bg-observe", chip: "bg-observe/10 text-observe", icon: "◎" },
    행동: { dot: "bg-act", chip: "bg-act/10 text-act", icon: "▶" },
  };

type Step = { type: StepType; tool?: string | null; message: string };

// 백엔드 미연결 시 폴백 (CLAUDE.md §3-4 결손 감지 시나리오)
const MOCK_TRACE: Step[] = [
  { type: "계획", message: "12개월 전표 분석 시작 → 결손 검사를 먼저 수행" },
  { type: "관찰", tool: "데이터 수집", message: "3~5월 도시가스 전표 0건 — 제조업 특성상 비정상" },
  { type: "행동", tool: "리포트·알림", message: "사장님 알림 발송 + 업종 평균 임시 보정 (품질등급 하향)" },
  { type: "관찰", tool: "업종 분포 조회", message: "7월 경유 사용량이 업종 중앙값의 3.2배 — 이상치 의심" },
  { type: "행동", tool: "전표 분류", message: '전표 재파싱 → "지게차 2대 증차" 확인 → 정상 판정, 주석 추가' },
  { type: "계획", message: "PCAF 2등급까지 부족 데이터 1건 → 요청 목록 생성" },
];

type TraceResponse = {
  session_id: string | null;
  steps: { step_type: StepType; tool_name: string | null; message: string }[];
};

export function SceneTrace() {
  const [steps, setSteps] = useState<Step[]>(MOCK_TRACE);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let alive = true;
    apiGet<TraceResponse>(`/trace/latest?company_id=${COMPANY_ID}`)
      .then((res) => {
        if (!alive || !res.steps?.length) return;
        setSteps(
          res.steps.map((s) => ({
            type: s.step_type,
            tool: s.tool_name,
            message: s.message,
          })),
        );
        setLive(true);
      })
      .catch(() => {
        /* 폴백: 목업 유지 */
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">
          ② 에이전트 트레이스 뷰
          <span className="ml-2 rounded bg-scope1/10 px-2 py-0.5 text-[11px] font-bold text-scope1">
            킬러씬 A
          </span>
        </h2>
        {live ? (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            실행 트레이스
          </span>
        ) : (
          <WireframeBadge />
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        에이전트가 스스로 결손을 발견하고 자기 답을 의심하는 판단 일지. 모든
        판단에 근거가 남습니다.
      </p>

      <ol className="mt-6 space-y-0">
        {steps.map((step, i) => {
          const s = STEP_STYLE[step.type] ?? STEP_STYLE["관찰"];
          const last = i === steps.length - 1;
          return (
            <li key={i} className="relative flex gap-4 pb-6">
              {!last && (
                <span className="absolute left-[11px] top-6 h-full w-px bg-line" />
              )}
              <span
                className={`relative z-10 mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] text-white ${s.dot}`}
              >
                {s.icon}
              </span>
              <div className="flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-semibold ${s.chip}`}
                  >
                    {step.type}
                  </span>
                  {step.tool && (
                    <span className="rounded border border-line px-2 py-0.5 text-[11px] text-muted">
                      {step.tool}
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-sm leading-relaxed">{step.message}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
