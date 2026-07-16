"use client";

import { useState } from "react";
import { SceneConsent } from "@/components/SceneConsent";
import { SceneTrace, type TraceRunState } from "@/components/SceneTrace";
import { SceneClassify } from "@/components/SceneClassify";
import { ScenePcaf } from "@/components/ScenePcaf";

const STEPS = [
  { key: "consent", label: "연동 동의" },
  { key: "trace", label: "결손 감지" },
  { key: "classify", label: "AI 분류" },
  { key: "pcaf", label: "리포트" },
] as const;

export default function OwnerPage() {
  const [active, setActive] = useState(0);
  // SceneTrace는 스텝 전환마다 언마운트되므로, 실행 결과는 여기(owner 페이지)
  // 레벨에 보관해 뒤로 갔다 돌아와도 유지되게 한다.
  const [traceRunState, setTraceRunState] = useState<TraceRunState>({
    allSteps: [],
    finished: false,
  });

  function goTo(i: number) {
    if (i < 0 || i >= STEPS.length) return;
    setActive(i);
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      {/* 진행 바 — mint→lime 단일 트랙 그라디언트를 진행률만큼만 노출 */}
      <div className="pt-7">
        <div className="relative h-1 overflow-hidden rounded-full bg-line">
          <div
            className="absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${(active / (STEPS.length - 1)) * 100}%`,
              minWidth: "6%",
              background:
                "linear-gradient(90deg, var(--color-brand), var(--color-lime))",
            }}
          />
        </div>
        <div className="mt-2 flex items-center justify-between">
          {STEPS.map((s, i) => (
            <span
              key={s.key}
              className={`text-[11.5px] font-semibold transition-colors ${
                i === active
                  ? "text-brand-ink"
                  : i < active
                    ? "text-muted"
                    : "text-faint"
              }`}
            >
              {s.label}
            </span>
          ))}
        </div>

        <div className="mt-6 flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold tracking-wide text-faint">
              STEP {active + 1} / {STEPS.length}
            </span>
            <h1 className="mt-1 text-[21px] font-extrabold tracking-tight text-ink">
              ○○정밀 탄소 측정 여정
            </h1>
          </div>
        </div>
      </div>

      <div className="step-enter mt-6 flex-1">
        {active === 0 && <SceneConsent onNext={() => goTo(1)} />}
        {active === 1 && (
          <SceneTrace
            onNext={() => goTo(2)}
            runState={traceRunState}
            onRunStateChange={setTraceRunState}
          />
        )}
        {active === 2 && <SceneClassify onNext={() => goTo(3)} />}
        {active === 3 && <ScenePcaf />}
      </div>

      <div className="mt-6 flex items-center justify-between">
        <button
          type="button"
          onClick={() => goTo(active - 1)}
          disabled={active === 0}
          className="rounded-full px-4 py-2.5 text-[13.5px] font-semibold text-muted transition-colors hover:text-ink disabled:pointer-events-none disabled:opacity-0"
        >
          ← 이전
        </button>
        {active < STEPS.length - 1 ? (
          <span className="text-[12.5px] text-faint">
            각 화면의 버튼을 눌러 진행하세요
          </span>
        ) : (
          <span className="text-[12.5px] font-semibold text-brand-ink">
            마지막 단계입니다
          </span>
        )}
      </div>
    </div>
  );
}
