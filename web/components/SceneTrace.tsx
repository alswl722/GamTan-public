"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, COMPANY_ID } from "@/lib/api";

/** 장면 ② — 에이전트 트레이스 뷰 (킬러씬 A). /trace/latest 실데이터 + 목업 폴백. */

type StepType = "계획" | "관찰" | "행동";

// 색이 아니라 아이콘 모양 + 텍스트 라벨로만 3가지 판단 타입을 구분한다.
const STEP_ICON: Record<StepType, string> = {
  계획: "◇",
  관찰: "◎",
  행동: "▶",
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

function mapSteps(res: TraceResponse): Step[] {
  return res.steps.map((s) => ({
    type: s.step_type,
    tool: s.tool_name,
    message: s.message,
  }));
}

type Scenario = { name: string; label: string };

export function SceneTrace({ onNext }: { onNext: () => void }) {
  const [allSteps, setAllSteps] = useState<Step[]>(MOCK_TRACE);
  const [live, setLive] = useState(false);
  const [visible, setVisible] = useState(0);
  const [running, setRunning] = useState(false);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    let alive = true;
    apiGet<TraceResponse>(`/trace/latest?company_id=${COMPANY_ID}`)
      .then((res) => {
        if (!alive || !res.steps?.length) return;
        setAllSteps(mapSteps(res));
        setLive(true);
      })
      .catch(() => {
        /* 폴백: 목업 유지 */
      });
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
  async function runAgent() {
    setRunning(true);
    setAllSteps([]);
    const poll = setInterval(() => {
      apiGet<TraceResponse>(`/trace/latest?company_id=${COMPANY_ID}`)
        .then((res) => {
          if (res.steps?.length) setAllSteps(mapSteps(res));
        })
        .catch(() => {});
    }, 1000);

    try {
      if (selected) await apiPost(`/scenario/${selected}/${COMPANY_ID}`);
      await apiPost(`/agent/run/${COMPANY_ID}`);
      const res = await apiGet<TraceResponse>(
        `/trace/latest?company_id=${COMPANY_ID}`,
      );
      if (res.steps?.length) {
        setAllSteps(mapSteps(res));
        setLive(true);
      }
    } catch {
      /* 서버 미기동 등 — 목업 유지 */
    } finally {
      clearInterval(poll);
      setRunning(false);
    }
  }

  // 판단 일지를 한 줄씩 순차 노출 — "AI가 지금 생각 중"인 연출
  useEffect(() => {
    setVisible(0);
    const timers = allSteps.map((_, i) =>
      setTimeout(() => setVisible((v) => Math.max(v, i + 1)), i === 0 ? 150 : 150 + i * 550),
    );
    return () => timers.forEach(clearTimeout);
  }, [allSteps]);

  const steps = allSteps.slice(0, visible);
  const done = visible >= allSteps.length;

  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-bg px-2.5 py-1 text-[11px] font-bold text-muted">
          킬러씬 A
        </span>
        {live && (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            실행 트레이스
          </span>
        )}
        {scenarios.length > 0 && (
          <div className="ml-auto flex items-center gap-1.5">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={running}
              className="rounded-lg bg-bg px-2 py-1.5 text-[11.5px] font-medium text-ink disabled:opacity-60"
            >
              {scenarios.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={runAgent}
              disabled={running}
              className="rounded-lg bg-brand px-3 py-1.5 text-[11.5px] font-bold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
            >
              {running
                ? allSteps.length > 0
                  ? `실행 중… (${allSteps.length}단계 진행)`
                  : "실행 중…"
                : "에이전트 실행"}
            </button>
          </div>
        )}
      </div>
      <h2 className="mt-3 text-[17px] font-bold leading-snug text-ink">
        에이전트가 스스로 결손을 발견하고 있어요
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">
        모든 판단에는 근거가 남습니다.
      </p>

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
        {!done && (
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

      <button
        type="button"
        onClick={onNext}
        disabled={!done}
        className="mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white transition-colors hover:bg-brand-ink disabled:cursor-not-allowed disabled:opacity-40"
      >
        {done ? "판단 근거 확인하러 가기" : "에이전트 판단 진행 중…"}
      </button>
    </section>
  );
}
