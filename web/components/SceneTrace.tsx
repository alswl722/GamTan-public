"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, COMPANY_ID } from "@/lib/api";

/** 장면 ② — 에이전트 트레이스 뷰. /trace/latest 실데이터만 사용(목업 없음). */

type StepType = "계획" | "관찰" | "행동";

// 색이 아니라 아이콘 모양 + 텍스트 라벨로만 3가지 판단 타입을 구분한다.
const STEP_ICON: Record<StepType, string> = {
  계획: "◇",
  관찰: "◎",
  행동: "▶",
};

type Step = { type: StepType; tool?: string | null; message: string };

type TraceResponse = {
  session_id: string | null;
  steps: { step_type: StepType; tool_name: string | null; message: string }[];
};

function mapSteps(res: TraceResponse): Step[] {
  return res.steps.map((s) => ({
    type: s.step_type,
    tool: s.tool_name,
    message: s.message,
  }));
}

type Scenario = { name: string; label: string };

export type TraceRunState = {
  allSteps: Step[];
  finished: boolean;
};

/**
 * allSteps/finished를 상위(owner 페이지)에서 관리하도록 끌어올린다 — owner
 * 페이지는 스텝 전환 시 언마운트되지 않으므로, 뒤로 갔다가 다시 이 화면으로
 * 돌아와도 실행 결과가 유지된다(이 컴포넌트 자체는 스텝 전환마다 재마운트됨).
 */
export function SceneTrace({
  onNext,
  runState,
  onRunStateChange,
}: {
  onNext: () => void;
  runState: TraceRunState;
  onRunStateChange: (next: TraceRunState) => void;
}) {
  const { allSteps: committedSteps, finished } = runState;
  const [allSteps, setAllStepsLocal] = useState<Step[]>(committedSteps);
  const [visible, setVisible] = useState(finished ? committedSteps.length : 0);
  const [running, setRunning] = useState(false);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");

  function setAllSteps(updater: Step[] | ((prev: Step[]) => Step[])) {
    setAllStepsLocal((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      return next;
    });
  }

  // 페이지 진입 시엔 예전 실행 결과를 불러오지 않는다 — 실행 전엔 화면에
  // 아무 스텝도 없어야 한다. 시나리오 드롭다운만 채워둔다.
  useEffect(() => {
    let alive = true;
    apiGet<{ scenarios: Scenario[] }>(`/scenario`)
      .then((res) => {
        if (!alive || !res.scenarios?.length) return;
        setScenarios(res.scenarios);
        setSelected(res.scenarios[0].name);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // 선택 시나리오를 로드(전표 리셋) → 에이전트 실행 → 트레이스 재조회
  // 실행 중에는 /trace/latest를 짧게 폴링해 지금까지 쌓인 판단을 실시간으로 보여준다.
  // 폴링마다 목록을 통째로 교체하면 이미 노출된 스텝까지 처음부터 재생되므로,
  // "새로 늘어난 스텝만" 뒤에 이어붙인다(visible 애니메이션은 새 스텝에만 적용).
  async function runAgent() {
    setRunning(true);
    setAllSteps([]);
    setVisible(0);
    prevCountRef.current = 0;
    onRunStateChange({ allSteps: [], finished: false });

    const poll = setInterval(() => {
      apiGet<TraceResponse>(`/trace/latest?company_id=${COMPANY_ID}`)
        .then((res) => {
          const next = mapSteps(res);
          setAllSteps((prev) => (next.length > prev.length ? next : prev));
        })
        .catch(() => {});
    }, 1000);

    let finalSteps: Step[] = [];
    try {
      if (selected) await apiPost(`/scenario/${selected}/${COMPANY_ID}`);
      await apiPost(`/agent/run/${COMPANY_ID}`);
      const res = await apiGet<TraceResponse>(
        `/trace/latest?company_id=${COMPANY_ID}`,
      );
      if (res.steps?.length) {
        finalSteps = mapSteps(res);
        setAllSteps(finalSteps);
      }
    } catch {
      /* 서버 미기동 등 — 있는 만큼만 표시 */
    } finally {
      clearInterval(poll);
      setRunning(false);
      // 실행 결과를 상위(owner 페이지)로 커밋 — 스텝을 이동했다 돌아와도 유지된다.
      onRunStateChange({ allSteps: finalSteps, finished: true });
    }
  }

  // 판단 일지를 한 줄씩 순차 노출 — "AI가 지금 생각 중"인 연출.
  // allSteps가 늘어난 만큼(prevCount 이후)만 새로 애니메이션하고, 이미 보여준
  // 앞부분은 visible을 건드리지 않아 처음부터 다시 재생되지 않는다.
  const prevCountRef = useRef(finished ? committedSteps.length : 0);
  useEffect(() => {
    const from = prevCountRef.current;
    const added = allSteps.slice(from);
    prevCountRef.current = allSteps.length;

    const timers = added.map((_, i) =>
      setTimeout(
        () => setVisible((v) => Math.max(v, from + i + 1)),
        i === 0 ? 150 : 150 + i * 550,
      ),
    );
    return () => timers.forEach(clearTimeout);
  }, [allSteps]);

  const steps = allSteps.slice(0, visible);
  // "지금까지 받은 스텝을 다 보여줬다"와 "에이전트 실행 자체가 끝났다"는 다른 조건.
  // running이 true인 동안은 스텝이 더 늘어날 수 있으므로, 실행이 완전히
  // 끝나고(finished) 화면 애니메이션도 다 따라잡았을 때만 진짜 완료로 본다.
  const done = finished && !running && visible >= allSteps.length && allSteps.length > 0;

  const buttonLabel = done
    ? "판단 근거 확인하러 가기"
    : running
      ? allSteps.length > 0
        ? `판단 중… (${allSteps.length}단계)`
        : "판단 중…"
      : "에이전트 실행";

  function handleButtonClick() {
    if (done) {
      onNext();
    } else if (!running) {
      runAgent();
    }
  }

  return (
    <section>
      <h2 className="text-[17px] font-bold leading-snug text-ink">
        에이전트가 스스로 결손을 발견하고 있어요
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">
        모든 판단에는 근거가 남습니다.
      </p>

      {scenarios.length > 0 && (
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={running}
          className="mt-3 w-full rounded-lg bg-bg px-3 py-2 text-[12.5px] font-medium text-ink disabled:opacity-60"
        >
          {scenarios.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label}
            </option>
          ))}
        </select>
      )}

      {steps.length > 0 && (
        <ol className="mt-4 max-h-[340px] space-y-0 overflow-y-auto rounded-2xl bg-surface p-4">
          {steps.map((step, i) => {
            const icon = STEP_ICON[step.type] ?? STEP_ICON["관찰"];
            const last = i === allSteps.length - 1;
            return (
              <li
                key={i}
                className="step-enter relative flex gap-3 pb-3.5 last:pb-0"
              >
                {!last && (
                  <span className="absolute left-[9px] top-5 h-full w-px bg-line" />
                )}
                <span className="relative z-10 mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-bg text-[9.5px] text-muted">
                  {icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] font-bold text-ink">
                      {step.type}
                    </span>
                    {step.tool && (
                      <span className="rounded bg-bg px-1.5 py-0.5 text-[10px] text-muted">
                        {step.tool}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[12.5px] leading-snug text-ink">
                    {step.message}
                  </p>
                </div>
              </li>
            );
          })}
          {running && (
            <li className="flex items-center gap-2 pt-1 pl-7 text-[11.5px] text-faint">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-faint" />
              </span>
              판단 중…
            </li>
          )}
        </ol>
      )}

      <button
        type="button"
        onClick={handleButtonClick}
        disabled={running}
        className="mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white transition-colors hover:bg-brand-ink disabled:cursor-not-allowed disabled:opacity-60"
      >
        {buttonLabel}
      </button>

      {done && (
        <button
          type="button"
          onClick={runAgent}
          className="mt-3 w-full text-center text-[12px] text-faint underline underline-offset-2 transition-colors hover:text-muted"
        >
          에이전트 재실행
        </button>
      )}
    </section>
  );
}
