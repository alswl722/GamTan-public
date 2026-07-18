"use client";

// 실API: GET /admin/traces (실행 이력 목록) + GET /trace/{session_id} (드릴다운 스텝)

import { useEffect, useState } from "react";
import { getTraceSteps } from "@/lib/admin-data";
import type { TraceRunItem, TraceStep } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

const STATUS_MAP: Record<string, string> = {
  완료: "bg-[#e3faf5] text-[#00967f] border-[#00c7a9]/30",
  실패: "bg-red-50 text-red-600 border-red-200",
};

const BADGE_MAP: Record<string, string> = {
  정상: "bg-[#e3faf5] text-[#00967f]",
  이상치: "bg-amber-50 text-amber-600",
  "결손 발견": "bg-red-50 text-red-600",
  "재검증 실패": "bg-red-50 text-red-600",
};

const STEP_ICON: Record<string, string> = { 계획: "◇", 관찰: "◎", 행동: "▶" };
const STEP_COLOR: Record<string, string> = {
  계획: "text-[#9ca3af]",
  관찰: "text-[#53e1e5]",
  행동: "text-[#00c7a9]",
};

/** 날짜는 마운트 후에만 포맷 — SSR/hydration 불일치 회피. */
function useFormattedDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions) {
  const [formatted, setFormatted] = useState<string | null>(null);
  useEffect(() => {
    if (iso) setFormatted(new Date(iso).toLocaleString("ko-KR", opts));
  }, [iso]);
  return formatted;
}

function DateText({
  iso,
  opts,
}: {
  iso: string | null | undefined;
  opts: Intl.DateTimeFormatOptions;
}) {
  return <>{useFormattedDate(iso, opts) ?? "—"}</>;
}

function detailText(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  try {
    return JSON.stringify(detail);
  } catch {
    return null;
  }
}

function StepTimeline({ steps }: { steps: TraceStep[] }) {
  return (
    <div className="relative space-y-0 pl-8">
      <div className="absolute bottom-2 left-3.5 top-2 w-px bg-[#e8eaed]" />
      {steps.map((step) => {
        const detail = detailText(step.detail_json);
        return (
          <div key={step.id} className="relative flex gap-3 pb-4">
            <div
              className={cn(
                "absolute left-0 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-[#e8eaed] bg-white text-sm",
                STEP_COLOR[step.step_type],
              )}
            >
              {STEP_ICON[step.step_type]}
            </div>
            <div className="ml-9 min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <span className={cn("text-[11px] font-bold", STEP_COLOR[step.step_type])}>
                  {step.step_type}
                </span>
                {step.tool_name && (
                  <span className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                    {step.tool_name}
                  </span>
                )}
                {step.created_at && (
                  <span className="ml-auto flex-shrink-0 text-[10px] text-[#9ca3af]">
                    <DateText iso={step.created_at} opts={{ hour: "2-digit", minute: "2-digit", second: "2-digit" }} />
                  </span>
                )}
              </div>
              <p className="text-xs leading-relaxed text-[#222222]">{step.message}</p>
              {detail && (
                <pre className="mt-1.5 overflow-x-auto rounded-lg border border-[#e8eaed] bg-[#f7f8fa] px-3 py-2 font-mono text-[10px] leading-relaxed text-[#9ca3af]">
                  {detail}
                </pre>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DrillDownModal({ run, onClose }: { run: TraceRunItem; onClose: () => void }) {
  const [steps, setSteps] = useState<TraceStep[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getTraceSteps(run.session_id)
      .then((s) => alive && setSteps(s))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [run.session_id]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-end bg-black/20 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-xl flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-[#e8eaed] px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-[#222222]">
              트레이스 실행 이력 — {run.company_name}
            </h3>
            <p className="mt-0.5 text-xs text-[#9ca3af]">
              세션 <span className="font-mono">{run.session_id.slice(0, 8)}</span> ·{" "}
              <DateText
                iso={run.ran_at}
                opts={{ year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }}
              />
            </p>
          </div>
          <button
            onClick={onClose}
            className="mt-0.5 text-xl leading-none text-[#9ca3af] transition-colors hover:text-[#222222]"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-5 flex flex-wrap gap-2">
            {run.result_badges.map((b) => (
              <span
                key={b}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                  BADGE_MAP[b] ?? "bg-slate-50 text-slate-500",
                )}
              >
                {b}
              </span>
            ))}
          </div>
          {error ? (
            <p className="text-sm text-red-600">트레이스를 불러오지 못했습니다.</p>
          ) : steps === null ? (
            <p className="text-sm text-[#9ca3af]">불러오는 중…</p>
          ) : steps.length > 0 ? (
            <StepTimeline steps={steps} />
          ) : (
            <p className="text-sm text-[#9ca3af]">단계 데이터 없음</p>
          )}
        </div>

        <div className="border-t border-[#e8eaed] bg-[#f7f8fa] px-6 py-3">
          <p className="text-[11px] text-[#9ca3af]">감사(읽기 전용) — 확인 후 창을 닫으세요.</p>
        </div>
      </div>
    </div>
  );
}

export function TraceHistory({ runs }: { runs: TraceRunItem[] }) {
  const [selected, setSelected] = useState<TraceRunItem | null>(null);

  return (
    <>
      <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[#e8eaed] bg-white shadow-card">
        <div className="flex items-center justify-between border-b border-[#e8eaed] px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-[#222222]">트레이스 실행 이력</h2>
            <p className="mt-0.5 text-xs text-[#9ca3af]">에이전트 실행 기록 — 행 클릭 시 단계 드릴다운</p>
          </div>
          <span className="text-xs text-[#9ca3af]">총 {runs.length}건</span>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {runs.length === 0 ? (
            <div className="flex h-40 items-center justify-center text-sm text-[#9ca3af]">
              실행 이력이 없습니다
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#e8eaed] bg-[#f7f8fa]">
                  {["기업명", "실행 시각", "단계 수", "결과", "상태"].map((h) => (
                    <th
                      key={h}
                      className="whitespace-nowrap px-5 py-3 text-left text-xs font-semibold tracking-wide text-[#9ca3af]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e8eaed]">
                {runs.map((run) => (
                  <tr
                    key={run.session_id}
                    onClick={() => setSelected(run)}
                    className="cursor-pointer transition-colors hover:bg-[#f7f8fa]"
                  >
                    <td className="whitespace-nowrap px-5 py-3.5 font-medium text-[#222222]">
                      {run.company_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-[#666666]">
                      <DateText
                        iso={run.ran_at}
                        opts={{ month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }}
                      />
                    </td>
                    <td className="px-5 py-3.5 tabular-nums text-[#666666]">{run.step_count}단계</td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-wrap gap-1">
                        {run.result_badges.map((b) => (
                          <span
                            key={b}
                            className={cn(
                              "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                              BADGE_MAP[b] ?? "bg-slate-50 text-slate-500",
                            )}
                          >
                            {b}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                          STATUS_MAP[run.status] ?? "bg-slate-50 text-slate-500",
                        )}
                      >
                        {run.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {selected && <DrillDownModal run={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
