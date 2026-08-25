"use client";

import { Check } from "lucide-react";

export interface StepperStep {
  label: string;
  /** 현재 단계일 때만 펼쳐지는 본문. */
  content: React.ReactNode;
}

/** 탄소중립포인트 신청서 위저드의 세로 번호 스테퍼.
 *
 * 원형 번호 + 세로 연결선 + 현재 단계만 본문을 펼치는 아코디언 구조다. `/owner/measure`의
 * 가로 진행바를 쓰지 않은 이유: 저 위저드는 단계마다 화면 하나를 꽉 채우는 연출이고, 이쪽은
 * "지금 몇 단계인지"와 "앞으로 뭐가 남았는지"를 같이 보여주는 게 목적이다(신청 절차라
 * 전체 흐름이 먼저 보여야 사장님이 얼마나 걸릴지 가늠한다).
 *
 * 색은 brand 축만 쓴다 — 완료·현재·대기를 색 세 개로 나누면 화면의 유일한 강조축(민트)이
 * 흐려진다. 대기 단계는 채도를 빼는 게 아니라 line/faint 중립 토큰으로 떨어뜨린다.
 */
export function ApplicationStepper({
  steps,
  activeIndex,
  onStepClick,
}: {
  steps: StepperStep[];
  activeIndex: number;
  /** 이미 지난 단계로 되돌아가기. 앞선 단계는 누를 수 없다(넘어가려면 각 단계의 버튼을 쓴다). */
  onStepClick?: (index: number) => void;
}) {
  return (
    <ol className="mt-5">
      {steps.map((step, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        const last = i === steps.length - 1;
        const clickable = done && onStepClick !== undefined;

        return (
          <li key={step.label} className="relative flex gap-3">
            {/* 번호 열 — 연결선은 마지막 단계에서 끊는다. */}
            <div className="flex flex-col items-center">
              <span
                className={`grid size-[26px] shrink-0 place-items-center rounded-full text-[12px] font-bold transition-colors ${
                  done
                    ? "bg-brand-soft text-brand-ink"
                    : active
                      ? "bg-brand text-white"
                      : "bg-line text-faint"
                }`}
                aria-hidden
              >
                {done ? <Check size={14} strokeWidth={3} /> : i + 1}
              </span>
              {!last && (
                <span
                  className={`w-0.5 flex-1 ${done ? "bg-brand-soft" : "bg-line"}`}
                  aria-hidden
                />
              )}
            </div>

            <div className={`min-w-0 flex-1 ${last ? "pb-1" : "pb-6"}`}>
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onStepClick(i)}
                  className="pt-0.5 text-left text-[14.5px] font-bold text-muted transition-colors hover:text-ink"
                >
                  {step.label}
                </button>
              ) : (
                <div
                  className={`pt-0.5 text-[14.5px] font-bold ${
                    active ? "text-ink" : done ? "text-muted" : "text-faint"
                  }`}
                  // 현재 단계를 스크린리더가 먼저 읽도록 표시 — 시각적으로만 강조하면
                  // 어디까지 왔는지 알 수 없다.
                  aria-current={active ? "step" : undefined}
                >
                  {step.label}
                </div>
              )}

              {active && <div className="step-enter mt-3">{step.content}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
