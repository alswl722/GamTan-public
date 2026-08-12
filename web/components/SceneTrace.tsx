"use client";

import { useEffect, useRef, useState } from "react";
import { AGENT_RUN_TIMEOUT_MS, apiGet, apiPost, getCompanyId } from "@/lib/api";

/** 장면 ② — 에이전트 트레이스 뷰. /trace/latest 실데이터만 사용(목업 없음). */

type StepType = "계획" | "관찰" | "행동";

// 색이 아니라 아이콘 모양 + 텍스트 라벨로만 3가지 판단 타입을 구분한다.
const STEP_ICON: Record<StepType, string> = {
  계획: "◇",
  관찰: "◎",
  행동: "▶",
};

type Step = { id: number; type: StepType; tool?: string | null; message: string };

type TraceResponse = {
  session_id: string | null;
  steps: { id: number; step_type: StepType; tool_name: string | null; message: string }[];
};

function mapSteps(res: TraceResponse): Step[] {
  return res.steps.map((s) => ({
    id: s.id,
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
  const [error, setError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");

  // 최신 스텝 목록을 ref로도 유지 — 실행 실패 시 폴링으로 모인 만큼을 커밋할 때 사용.
  const stepsRef = useRef<Step[]>(committedSteps);
  function setAllSteps(updater: Step[] | ((prev: Step[]) => Step[])) {
    setAllStepsLocal((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      stepsRef.current = next;
      return next;
    });
  }

  // 폴링 인터벌은 ref로 들고 언마운트 시 반드시 정리한다.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<string | null>(null);
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

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
      .catch((err) => {
        if (alive) console.error("시나리오 목록 조회 실패:", err);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 선택 시나리오를 로드(전표·트레이스 리셋)한 **다음에야** 폴링을 시작한다 —
  // 리셋 전에 폴링하면 이전 실행의 트레이스가 새 실행 화면에 섞인다.
  // 폴링마다 목록을 통째로 교체하면 이미 노출된 스텝까지 처음부터 재생되므로,
  // 같은 세션이면 "새로 늘어난 스텝만" 이어붙이고, 세션이 바뀌면 교체한다.
  async function runAgent() {
    setRunning(true);
    setError(null);
    setAllSteps([]);
    setVisible(0);
    prevCountRef.current = 0;
    sessionRef.current = null;
    onRunStateChange({ allSteps: [], finished: false });

    let succeeded = false;
    try {
      const cid = await getCompanyId();
      if (selected) await apiPost(`/scenario/${selected}/${cid}`);

      pollRef.current = setInterval(() => {
        apiGet<TraceResponse>(`/trace/latest?company_id=${cid}`)
          .then((res) => {
            const next = mapSteps(res);
            if (res.session_id !== sessionRef.current) {
              // 새 실행 세션 감지 — 길이 비교 없이 통째로 교체 + 애니메이션 리셋
              sessionRef.current = res.session_id;
              prevCountRef.current = 0;
              setVisible(0);
              setAllSteps(next);
            } else {
              setAllSteps((prev) => (next.length > prev.length ? next : prev));
            }
          })
          .catch(() => {}); // 폴링 1회 실패는 다음 틱이 재시도 — 최종 성패는 아래서 판정
      }, 1000);

      await apiPost(`/agent/run/${cid}`, undefined, AGENT_RUN_TIMEOUT_MS);
      const res = await apiGet<TraceResponse>(`/trace/latest?company_id=${cid}`);
      if (res.steps.length > 0) {
        // 빈 응답(동시 리셋 등)으로 폴링 누적분을 덮지 않는다
        sessionRef.current = res.session_id;
        setAllSteps(mapSteps(res));
      }
      succeeded = true;
    } catch (err) {
      // 실패를 무음으로 삼키지 않는다 — 배너 표시 + 버튼은 재시도로 남는다
      console.error("에이전트 실행 실패:", err);
      const conflict = err instanceof Error && err.message.includes("409");
      setError(
        conflict
          ? "이미 실행 중입니다 — 진행 중인 실행이 끝난 뒤 다시 시도해 주세요."
          : "에이전트 실행에 실패했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.",
      );
    } finally {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setRunning(false);
      // 폴링으로 모인 만큼은 보존해 커밋 — 빈 배열로 덮지 않는다.
      // finished는 성공 시에만 true — 실패 시 버튼이 '실행(재시도)'으로 남는다.
      onRunStateChange({ allSteps: stepsRef.current, finished: succeeded });
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
  // 데이터 완료(dataReady)와 "리빌 애니메이션이 다 따라잡았다"는 별개다.
  // 버튼의 다음 단계 진행 여부는 데이터 완료에만 걸어야 한다 — 애니메이션이
  // 폴링 속도를 못 따라가 몇 초 지연되는 동안 "에이전트 실행"으로 되돌아가
  // 재실행을 유발하던 버그가 있었다. 화면 재생(visible)은 순수 연출로만 쓴다.
  const dataReady = finished && !running && allSteps.length > 0;

  const buttonLabel = dataReady
    ? "판단 근거 확인하러 가기"
    : running
      ? allSteps.length > 0
        ? `판단 중… (${allSteps.length}단계)`
        : "판단 중…"
      : "에이전트 실행";

  function handleButtonClick() {
    if (dataReady) {
      onNext();
    } else if (!running) {
      runAgent();
    }
  }

  return (
    <section>
      <h2 className="text-[17px] font-bold leading-snug text-ink">
        감탄 AI 에이전트가
        <br />
        데이터를 확인 중이에요
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
                key={step.id}
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
                <span className="dot-bounce h-2 w-2 rounded-full bg-brand [animation-delay:-0.3s]" />
                <span className="dot-bounce h-2 w-2 rounded-full bg-brand [animation-delay:-0.15s]" />
                <span className="dot-bounce h-2 w-2 rounded-full bg-brand" />
              </span>
              판단 중…
            </li>
          )}
        </ol>
      )}

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={handleButtonClick}
        disabled={running}
        className="btn-cta mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
      >
        {buttonLabel}
      </button>

      {dataReady && (
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
