"use client";

// 실API: GET /admin/traces (page/page_size/company_id/from_time/to_time 서버사이드
// 페이지네이션) + GET /trace/{session_id} (드릴다운 스텝)

import { useEffect, useMemo, useState } from "react";
import { getTraceRuns, getTraceSteps } from "@/lib/admin-data";
import type { TraceRunItem, TraceStep } from "@/lib/admin-types";
import { usePaginatedLog } from "@/lib/use-paginated-log";
import { cn } from "@/lib/utils";
import { DateText } from "@/lib/use-formatted-date";
import { PaginationBar } from "@/components/admin/PaginationBar";

const STATUS_MAP: Record<string, string> = {
  완료: "bg-brand-soft text-brand-ink border-brand/30",
  실패: "bg-hitl/20 text-hitl-ink border-hitl/40",
};

const BADGE_MAP: Record<string, string> = {
  정상: "bg-brand-soft text-brand-ink",
  이상치: "bg-hitl/20 text-hitl-ink",
  "결손 발견": "bg-hitl/20 text-hitl-ink",
  "재검증 실패": "bg-hitl/20 text-hitl-ink",
};

// 색이 아니라 아이콘 모양 + 텍스트 라벨로만 구분 (owner 장면② 트레이스 뷰와 동일 원칙)
const STEP_ICON: Record<string, string> = { 계획: "◇", 관찰: "◎", 행동: "▶" };
const STEP_COLOR: Record<string, string> = {
  계획: "text-muted",
  관찰: "text-muted",
  행동: "text-muted",
};

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
      <div className="absolute bottom-2 left-3.5 top-2 w-px bg-line" />
      {steps.map((step) => {
        const detail = detailText(step.detail_json);
        return (
          <div key={step.id} className="relative flex gap-3 pb-4">
            <div
              className={cn(
                "absolute left-0 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-line bg-surface text-sm",
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
                  <span className="rounded border border-line bg-bg px-1.5 py-0.5 font-mono text-[10px] text-muted">
                    {step.tool_name}
                  </span>
                )}
                {step.created_at && (
                  <span className="ml-auto flex-shrink-0 text-[10px] text-faint">
                    <DateText iso={step.created_at} opts={{ hour: "2-digit", minute: "2-digit", second: "2-digit" }} />
                  </span>
                )}
              </div>
              <p className="text-xs leading-relaxed text-ink">{step.message}</p>
              {detail && (
                <pre className="mt-1.5 overflow-x-auto rounded-md border border-line bg-bg px-3 py-2 font-mono text-[10px] leading-relaxed text-faint">
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
        className="flex h-full w-full flex-col overflow-hidden bg-surface shadow-2xl sm:w-[40vw] sm:min-w-[420px]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-line px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-ink">
              트레이스 실행 이력 — {run.company_name}
            </h3>
            <p className="mt-0.5 text-xs text-faint">
              세션 <span className="font-mono">{run.session_id.slice(0, 8)}</span> ·{" "}
              <DateText
                iso={run.ran_at}
                opts={{ year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }}
              />
            </p>
          </div>
          <button
            onClick={onClose}
            className="mt-0.5 text-xl leading-none text-faint transition-colors hover:text-ink"
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
                  BADGE_MAP[b] ?? "bg-bg text-faint",
                )}
              >
                {b}
              </span>
            ))}
          </div>
          {error ? (
            <p className="text-sm text-hitl-ink">트레이스를 불러오지 못했습니다.</p>
          ) : steps === null ? (
            <p className="text-sm text-faint">불러오는 중…</p>
          ) : steps.length > 0 ? (
            <StepTimeline steps={steps} />
          ) : (
            <p className="text-sm text-faint">단계 데이터 없음</p>
          )}
        </div>

        <div className="border-t border-line bg-bg px-6 py-3">
          <p className="text-[11px] text-faint">감사(읽기 전용) — 확인 후 창을 닫으세요.</p>
        </div>
      </div>
    </div>
  );
}

type Preset = "전체" | "오늘" | "최근 7일" | "최근 30일" | "직접 설정";
const PRESETS: Preset[] = ["전체", "오늘", "최근 7일", "최근 30일", "직접 설정"];

function presetRange(preset: Preset): { from: string | undefined; to: string | undefined } {
  if (preset === "전체" || preset === "직접 설정") return { from: undefined, to: undefined };
  const now = new Date();
  const to = now.toISOString();
  const from = new Date(now);
  if (preset === "오늘") from.setHours(0, 0, 0, 0);
  if (preset === "최근 7일") from.setDate(from.getDate() - 7);
  if (preset === "최근 30일") from.setDate(from.getDate() - 30);
  return { from: from.toISOString(), to };
}

const PAGE_SIZE = 50;

/** companyId를 넘기면 기간 프리셋 없이 그 기업(정확일치)으로 고정 필터한다 —
 * 기업 상세 탭이 사용. trace_logs가 계속 쌓이는 로그 테이블이라 서버사이드
 * 페이지네이션으로 조회한다(review-log/access-log와 같은 패턴). */
export function TraceHistory({ companyId: fixedCompanyId }: { companyId?: number } = {}) {
  const [selected, setSelected] = useState<TraceRunItem | null>(null);
  const [preset, setPreset] = useState<Preset>("전체");
  // 프리셋이 아닌 "직접 설정"일 때만 쓰는 수동 기간 입력
  const [fromTime, setFromTime] = useState("");
  const [toTime, setToTime] = useState("");

  const dateRange = useMemo(() => {
    if (preset === "직접 설정") {
      return {
        fromTime: fromTime ? new Date(fromTime).toISOString() : undefined,
        toTime: toTime ? new Date(toTime).toISOString() : undefined,
      };
    }
    const { from, to } = presetRange(preset);
    return { fromTime: from, toTime: to };
  }, [preset, fromTime, toTime]);

  const { data, loading, error, page, setPage, retry } = usePaginatedLog<{ runs: TraceRunItem[] }>(
    getTraceRuns,
    PAGE_SIZE,
    fixedCompanyId,
    dateRange,
  );

  const runs = data?.runs ?? [];

  const inputCls =
    "rounded-md border border-line bg-surface px-2.5 py-1.5 text-xs text-muted transition-colors focus:outline-none focus:ring-1 focus:ring-brand";

  return (
    <>
      <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
          <h2 className="text-base font-semibold text-ink">트레이스 실행 이력</h2>
          <div className="flex flex-wrap items-center gap-2">
            {fixedCompanyId === undefined && (
              <div className="flex items-center gap-0.5 rounded-md border border-line bg-bg p-0.5">
                {PRESETS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPreset(p)}
                    className={cn(
                      "whitespace-nowrap rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                      preset === p ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink",
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
            {fixedCompanyId === undefined && preset === "직접 설정" && (
              <>
                <label className="flex items-center gap-1.5 text-xs text-faint">
                  시작
                  <input
                    type="datetime-local"
                    className={inputCls}
                    value={fromTime}
                    onChange={(e) => setFromTime(e.target.value)}
                  />
                </label>
                <label className="flex items-center gap-1.5 text-xs text-faint">
                  종료
                  <input
                    type="datetime-local"
                    className={inputCls}
                    value={toTime}
                    onChange={(e) => setToTime(e.target.value)}
                  />
                </label>
              </>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {error ? (
            <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-faint">
              <span className="text-hitl-ink">{error}</span>
              <button
                type="button"
                onClick={retry}
                className="rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink"
              >
                다시 시도
              </button>
            </div>
          ) : loading && !data ? (
            <div className="flex h-40 items-center justify-center text-sm text-faint">
              불러오는 중…
            </div>
          ) : runs.length === 0 ? (
            <div className="flex h-40 items-center justify-center text-sm text-faint">
              {preset === "전체" ? "실행 이력이 없습니다" : "선택한 기간에 실행 이력이 없습니다"}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-bg">
                  {["기업명", "실행 시각", "단계 수", "결과", "상태"].map((h) => (
                    <th
                      key={h}
                      className="whitespace-nowrap px-5 py-3 text-left text-xs font-semibold tracking-wide text-faint"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.map((run) => (
                  <tr
                    key={run.session_id}
                    onClick={() => setSelected(run)}
                    className="cursor-pointer transition-colors hover:bg-bg"
                  >
                    <td className="whitespace-nowrap px-5 py-3.5 font-medium text-ink">
                      {run.company_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-muted">
                      <DateText
                        iso={run.ran_at}
                        opts={{ month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }}
                      />
                    </td>
                    <td className="px-5 py-3.5 tabular-nums text-muted">{run.step_count}단계</td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-wrap gap-1">
                        {run.result_badges.map((b) => (
                          <span
                            key={b}
                            className={cn(
                              "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                              BADGE_MAP[b] ?? "bg-bg text-faint",
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
                          STATUS_MAP[run.status] ?? "bg-bg text-faint",
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

        {data && data.total > 0 && (
          <PaginationBar total={data.total} page={page} pageSize={PAGE_SIZE} onChange={setPage} />
        )}
      </div>

      {selected && <DrillDownModal run={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
