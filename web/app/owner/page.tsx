"use client";

import { useState } from "react";
import { SceneConsent } from "@/components/SceneConsent";
import { SceneUpload, type FuelTypesState } from "@/components/SceneUpload";
import { SceneTrace, type TraceRunState } from "@/components/SceneTrace";
import { SceneClassify } from "@/components/SceneClassify";
import { ScenePcaf } from "@/components/ScenePcaf";

// 스텝별 제목은 각 Scene 컴포넌트 자체의 h2가 담당한다(예: SceneConsent의
// "먼저 기업 정보부터 확인할게요") — 진행 바 라벨과 내용이 겹치는 페이지 레벨
// h1은 중복이라 없앤다.
// 연료 체크 + 자료 업로드는 한 화면(SceneUpload)으로 합쳤다 — 스텝 하나로 줄어듦.
const STEPS = [
  { key: "consent", label: "연동 동의" },
  { key: "upload", label: "연료·자료" },
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
  // fuelState도 traceRunState와 같은 이유로 부모 레벨에 보관 —
  // 뒤로 갔다 SceneUpload로 돌아와도 연료 선택이 유지되게(Scene은 스텝 전환마다 언마운트됨).
  const [fuelState, setFuelState] = useState<FuelTypesState | undefined>(undefined);

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
      </div>

      <div className="step-enter mt-6 flex-1">
        {active === 0 && <SceneConsent onNext={() => goTo(1)} />}
        {active === 1 && (
          <SceneUpload
            initialFuel={fuelState}
            onFuelChange={setFuelState}
            onNext={() => goTo(2)}
          />
        )}
        {active === 2 && (
          <SceneTrace
            onNext={() => goTo(3)}
            runState={traceRunState}
            onRunStateChange={setTraceRunState}
          />
        )}
        {active === 3 && <SceneClassify onNext={() => goTo(4)} />}
        {active === 4 && <ScenePcaf />}
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
