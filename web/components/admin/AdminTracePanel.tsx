"use client";

import { useEffect, useState } from "react";
import { apiGet, getCompanyId } from "@/lib/api";

/** 트레이스 뷰 패널 (읽기 전용) — 최근 에이전트 실행의 [계획]/[관찰]/[행동] 타임라인.
 *  실행 제어는 사장님 화면(장면②) 담당. 여기선 담당자가 감사 목적으로 열람만. */

type StepType = "계획" | "관찰" | "행동";

const STEP_ICON: Record<StepType, string> = { 계획: "◇", 관찰: "◎", 행동: "▶" };

type Step = {
  id: number;
  step_type: StepType;
  tool_name: string | null;
  message: string;
};

type TraceResponse = { session_id: string | null; steps: Step[] };

export function AdminTracePanel() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "error">(
    "loading",
  );

  function load() {
    setStatus("loading");
    getCompanyId()
      .then((cid) => apiGet<TraceResponse>(`/trace/latest?company_id=${cid}`))
      .then((res) => {
        setSteps(res.steps);
        setStatus(res.steps.length > 0 ? "ready" : "empty");
      })
      .catch((err) => {
        console.error("트레이스 조회 실패:", err);
        setStatus("error");
      });
  }

  useEffect(load, []);

  return (
    <div className="rounded-2xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[16px] font-bold text-ink">트레이스 뷰 패널</h2>
          <p className="mt-0.5 text-[12.5px] text-muted">
            최근 에이전트 실행 로그 (감사용 · 읽기 전용)
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-lg border border-line px-2.5 py-1.5 text-[12px] font-semibold text-muted transition-colors hover:text-ink"
        >
          새로고침
        </button>
      </div>

      {status === "loading" && (
        <div className="mt-5 grid h-24 place-items-center text-[13px] text-muted">
          트레이스 조회 중…
        </div>
      )}

      {status === "error" && (
        <div className="mt-5 rounded-xl bg-hitl/25 px-3 py-2 text-[12px] text-hitl-ink">
          트레이스를 불러오지 못했습니다. 서버 연결을 확인해 주세요.
        </div>
      )}

      {status === "empty" && (
        <div className="mt-5 grid h-24 place-items-center rounded-xl border border-dashed border-line bg-bg text-center text-[12.5px] text-muted">
          아직 실행된 에이전트 트레이스가 없습니다
          <br />
          <span className="text-faint">사장님 화면에서 에이전트를 실행하면 여기 표시됩니다</span>
        </div>
      )}

      {status === "ready" && (
        <ol className="mt-4 space-y-1.5">
          {steps.map((s) => {
            const icon = STEP_ICON[s.step_type] ?? STEP_ICON["관찰"];
            return (
              <li
                key={s.id}
                className="flex gap-3 rounded-xl bg-bg px-3.5 py-2.5"
              >
                <span className="mt-0.5 shrink-0 font-mono text-[13px] text-brand-ink">
                  {icon}
                </span>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-bold text-brand-ink">
                      [{s.step_type}]
                    </span>
                    {s.tool_name && (
                      <span className="rounded border border-line px-1.5 py-0.5 text-[10px] text-faint">
                        {s.tool_name}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink">
                    {s.message}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
