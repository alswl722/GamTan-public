"use client";

import Image from "next/image";
import { AlertCircle, Check, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AGENT_RUN_TIMEOUT_MS,
  apiGet,
  apiPost,
  getDocumentReviewStatus,
  getUploadJob,
  type DocumentReviewItem,
  type UploadJob,
} from "@/lib/api";

type FlowPhase = "agent" | "review" | "stamp";
type AgentStatus = "waiting_jobs" | "running" | "ready" | "error" | "all_failed";
type TraceStepType = "계획" | "관찰" | "행동";

type TraceStep = {
  id: number;
  step_type: TraceStepType;
  tool_name: string | null;
  message: string;
};

type TraceResponse = {
  session_id: string | null;
  steps: TraceStep[];
};

type AgentRunResponse = {
  session_id: string;
  mode: "llm" | "judge_failed";
  step_count: number;
};

export type UploadAgentFlowResult = {
  succeeded: UploadJob[];
  failed: UploadJob[];
  agentSucceeded: boolean;
};

const PHASES: { key: FlowPhase; label: string }[] = [
  { key: "agent", label: "AI Agent" },
  { key: "review", label: "담당자 검토" },
  { key: "stamp", label: "업로드 완료" },
];

const STEP_ICON: Record<TraceStepType, string> = {
  계획: "✦",
  관찰: "◎",
  행동: "→",
};

const DOC_LABEL: Record<string, string> = {
  tax_invoice: "세금계산서",
  electric_bill: "전기요금고지서",
  gas_bill: "도시가스고지서",
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function mergeReviewItems(statuses: PromiseSettledResult<Awaited<ReturnType<typeof getDocumentReviewStatus>>>[]) {
  const byVoucher = new Map<number, DocumentReviewItem>();
  for (const status of statuses) {
    if (status.status !== "fulfilled") continue;
    for (const item of status.value.items) byVoucher.set(item.voucher_id, item);
  }
  return [...byVoucher.values()].sort(
    (a, b) => a.year - b.year || a.month - b.month || a.voucher_id - b.voucher_id,
  );
}

export function UploadAgentFlowModal({
  companyId,
  jobIds,
  fileCount,
  acceptedCount,
  submissionErrors,
  onClose,
}: {
  companyId: number;
  jobIds: number[] | null;
  fileCount: number;
  acceptedCount: number;
  submissionErrors: string[];
  onClose: (result: UploadAgentFlowResult) => void;
}) {
  const isSubmitting = jobIds === null;
  const jobKey = jobIds?.join(",") ?? "";
  const stableJobIds = useMemo(
    () => jobKey.split(",").filter(Boolean).map(Number),
    [jobKey],
  );
  const [phase, setPhase] = useState<FlowPhase>("agent");
  const [status, setStatus] = useState<AgentStatus>("waiting_jobs");
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [succeeded, setSucceeded] = useState<UploadJob[]>([]);
  const [failed, setFailed] = useState<UploadJob[]>([]);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [reviewItems, setReviewItems] = useState<DocumentReviewItem[]>([]);
  const [reviewLoadFailed, setReviewLoadFailed] = useState(false);
  const [reviewReloading, setReviewReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentSucceeded, setAgentSucceeded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generationRef = useRef(0);
  const traceListRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    // 파일 선택 직후에는 아직 서버 job_id가 없다. 부모가 전송을 끝내 jobIds를
    // 채워줄 때까지 모달의 업로드 진행 화면만 유지하고 Agent 호출은 시작하지 않는다.
    if (isSubmitting) return;

    const generation = ++generationRef.current;
    let traceTimer: ReturnType<typeof setInterval> | null = null;
    const isCurrent = () => generationRef.current === generation;

    async function waitForJobs(): Promise<UploadJob[]> {
      for (let i = 0; i < 100; i += 1) {
        const current = await Promise.all(
          stableJobIds.map((jobId) => getUploadJob(companyId, jobId)),
        );
        if (!isCurrent()) return [];
        setJobs(current);
        if (current.every((job) => job.status !== "processing")) return current;
        await sleep(1500);
        if (!isCurrent()) return [];
      }
      throw new Error("업로드 자료를 읽는 데 시간이 오래 걸리고 있어요. 잠시 후 다시 확인해 주세요.");
    }

    function applyLiveTrace(response: TraceResponse, baselineSessionId: string | null, observed: { id: string | null }) {
      if (!isCurrent() || !response.session_id) return;
      if (observed.id === null && response.session_id === baselineSessionId) return;
      if (observed.id !== null && response.session_id !== observed.id) return;
      observed.id = response.session_id;
      setSteps(response.steps);
    }

    async function runFlow() {
      setPhase("agent");
      setStatus("waiting_jobs");
      setJobs([]);
      setSucceeded([]);
      setFailed([]);
      setSteps([]);
      setReviewItems([]);
      setReviewLoadFailed(false);
      setError(null);
      setAgentSucceeded(false);

      try {
        const terminalJobs = await waitForJobs();
        if (!isCurrent()) return;
        const successfulJobs = terminalJobs.filter((job) => job.status === "done");
        const failedJobs = terminalJobs.filter((job) => job.status === "failed");
        setSucceeded(successfulJobs);
        setFailed(failedJobs);

        if (successfulJobs.length === 0) {
          setStatus("all_failed");
          return;
        }

        const baseline = await apiGet<TraceResponse>(`/trace/latest?company_id=${companyId}`);
        if (!isCurrent()) return;
        const observedSession = { id: null as string | null };
        setStatus("running");
        traceTimer = setInterval(() => {
          apiGet<TraceResponse>(`/trace/latest?company_id=${companyId}`)
            .then((response) => applyLiveTrace(response, baseline.session_id, observedSession))
            .catch(() => {
              // 한 번의 trace 조회 실패는 다음 tick에서 복구한다. Agent POST가 최종 성패 정본이다.
            });
        }, 800);

        const run = await apiPost<AgentRunResponse>(
          `/agent/run/${companyId}`,
          undefined,
          AGENT_RUN_TIMEOUT_MS,
        );
        if (traceTimer) {
          clearInterval(traceTimer);
          traceTimer = null;
        }
        if (!isCurrent()) return;

        try {
          const finalTrace = await apiGet<TraceResponse>(`/trace/${run.session_id}`);
          if (isCurrent()) setSteps(finalTrace.steps);
        } catch {
          const latest = await apiGet<TraceResponse>(`/trace/latest?company_id=${companyId}`);
          if (isCurrent() && latest.session_id === run.session_id) setSteps(latest.steps);
        }

        const sourceDocumentIds = successfulJobs
          .map((job) => job.result_source_document_id)
          .filter((id): id is number => id !== null);
        const reviewStatuses = await Promise.allSettled(
          sourceDocumentIds.map((documentId) => getDocumentReviewStatus(companyId, documentId)),
        );
        if (!isCurrent()) return;
        setReviewItems(mergeReviewItems(reviewStatuses));
        setReviewLoadFailed(reviewStatuses.some((result) => result.status === "rejected"));
        setAgentSucceeded(true);
        setStatus("ready");
      } catch (caught) {
        if (!isCurrent()) return;
        console.error("추가 업로드 Agent 흐름 실패:", caught);
        const conflict = caught instanceof Error && caught.message.includes("409");
        setError(
          conflict
            ? "이미 다른 AI Agent가 실행 중이에요. 잠시 후 다시 확인해 주세요."
            : caught instanceof Error
              ? caught.message
              : "AI Agent 실행을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.",
        );
        setStatus("error");
      } finally {
        if (traceTimer) clearInterval(traceTimer);
      }
    }

    void runFlow();
    return () => {
      if (generationRef.current === generation) generationRef.current += 1;
      if (traceTimer) clearInterval(traceTimer);
    };
  }, [attempt, companyId, isSubmitting, stableJobIds]);

  // trace가 길어져 내부 스크롤이 생겨도 새 판단이 추가될 때마다 가장 최근 동작이
  // 보이게 한다. 모달은 시연 중 실시간 진행을 따라가는 화면이므로 사용자가 잠시
  // 위로 스크롤했더라도 다음 trace가 오면 최신 위치로 복귀한다.
  useEffect(() => {
    if (phase !== "agent" || steps.length === 0) return;
    const frame = requestAnimationFrame(() => {
      const list = traceListRef.current;
      if (!list) return;
      list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [phase, status, steps.length]);

  const currentPhaseIndex = PHASES.findIndex((item) => item.key === phase);
  const processingCount = jobs.filter((job) => job.status === "processing").length;
  const failedCount = failed.length + submissionErrors.length;
  const canClose =
    !isSubmitting && (phase === "stamp" || status === "error" || status === "all_failed");

  function close() {
    onClose({ succeeded, failed, agentSucceeded });
  }

  function retry() {
    setAttempt((value) => value + 1);
  }

  async function retryReviewStatuses() {
    const sourceDocumentIds = succeeded
      .map((job) => job.result_source_document_id)
      .filter((id): id is number => id !== null);
    const generation = generationRef.current;
    setReviewReloading(true);
    try {
      const reviewStatuses = await Promise.allSettled(
        sourceDocumentIds.map((documentId) => getDocumentReviewStatus(companyId, documentId)),
      );
      if (generationRef.current !== generation) return;
      setReviewItems(mergeReviewItems(reviewStatuses));
      setReviewLoadFailed(reviewStatuses.some((result) => result.status === "rejected"));
    } finally {
      if (generationRef.current === generation) setReviewReloading(false);
    }
  }

  const completedMessage =
    succeeded.length === 1 && succeeded[0].result_document_type
      ? `${DOC_LABEL[succeeded[0].result_document_type] ?? "업로드 자료"} ${succeeded[0].result_month ?? ""}월 자료를 등록했어요.`
      : `${succeeded.length}건의 자료를 등록했어요.`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-label="추가 업로드 AI Agent 처리"
    >
      <div className="relative flex max-h-full w-full max-w-lg flex-col overflow-hidden rounded-3xl bg-white shadow-xl">
        {canClose && (
          <button
            type="button"
            onClick={close}
            className="absolute right-4 top-4 z-10 text-faint transition-colors hover:text-ink"
            aria-label="닫기"
          >
            <X size={20} />
          </button>
        )}

        <div className="border-b border-line px-5 pb-4 pt-5">
          <div className="flex items-center gap-2 pr-8">
            {PHASES.map((item, index) => (
              <div key={item.key} className="flex min-w-0 flex-1 items-center gap-2">
                <span
                  className={`grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-bold ${
                    index <= currentPhaseIndex
                      ? "bg-brand text-white"
                      : "bg-line text-faint"
                  }`}
                >
                  {index < currentPhaseIndex ? <Check size={13} /> : index + 1}
                </span>
                <span
                  className={`truncate text-[10.5px] font-semibold ${
                    index <= currentPhaseIndex ? "text-brand-ink" : "text-faint"
                  }`}
                >
                  {item.key === "agent" && isSubmitting ? "자료 업로드" : item.label}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {phase === "agent" && (
            <div className="step-enter">
              <h2 className="text-[20px] font-extrabold leading-snug text-ink">
                {isSubmitting ? (
                  <>
                    자료를 안전하게
                    <br />
                    업로드하고 있어요
                  </>
                ) : (
                  <>
                    감탄 AI Agent가
                    <br />
                    새 자료를 확인하고 있어요
                  </>
                )}
              </h2>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                {isSubmitting
                  ? "파일 전송이 끝나면 문서 인식과 AI Agent 확인을 바로 이어갈게요."
                  : "자료 수집부터 분류와 계산까지, 지금 진행되는 판단을 실시간으로 보여드릴게요."}
              </p>

              {isSubmitting && (
                <div className="mt-5 rounded-2xl bg-bg p-5 text-center" aria-live="polite">
                  <span className="mx-auto flex w-fit gap-1.5">
                    <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.3s]" />
                    <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.15s]" />
                    <span className="dot-bounce size-2.5 rounded-full bg-brand" />
                  </span>
                  <p className="mt-3 text-[13px] font-semibold text-ink">자료 업로드 중…</p>
                  <p className="mt-1 text-[11.5px] text-faint">
                    {fileCount === 1
                      ? "파일을 서버로 안전하게 전송하고 있어요."
                      : `${acceptedCount}/${fileCount}건 접수 완료`}
                  </p>
                  {submissionErrors.length > 0 && (
                    <p className="mt-2 text-[11.5px] leading-relaxed text-red-600">
                      {submissionErrors.length}건은 접수하지 못했지만 나머지 파일은 계속 업로드하고 있어요.
                    </p>
                  )}
                </div>
              )}

              {!isSubmitting && status === "waiting_jobs" && (
                <div className="mt-5 rounded-2xl bg-bg p-5 text-center">
                  <span className="mx-auto flex w-fit gap-1.5">
                    <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.3s]" />
                    <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.15s]" />
                    <span className="dot-bounce size-2.5 rounded-full bg-brand" />
                  </span>
                  <p className="mt-3 text-[13px] font-semibold text-ink">업로드 자료를 읽는 중이에요</p>
                  <p className="mt-1 text-[11.5px] text-faint">
                    {jobs.length === 0
                      ? `${stableJobIds.length}건의 처리 상태를 확인하고 있어요.`
                      : `${jobs.length - processingCount}/${jobs.length}건 인식 완료`}
                  </p>
                </div>
              )}

              {(status === "running" || status === "ready") && (
                <div className="mt-5 rounded-2xl bg-bg p-4">
                  {steps.length === 0 ? (
                    <div className="py-5 text-center">
                      <span className="mx-auto flex w-fit gap-1.5">
                        <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.3s]" />
                        <span className="dot-bounce size-2.5 rounded-full bg-brand [animation-delay:-0.15s]" />
                        <span className="dot-bounce size-2.5 rounded-full bg-brand" />
                      </span>
                      <p className="mt-3 text-[12px] text-muted">Agent가 판단 계획을 세우고 있어요.</p>
                    </div>
                  ) : (
                    <ol
                      ref={traceListRef}
                      className="max-h-[310px] space-y-0 overflow-y-auto scroll-smooth"
                      aria-live="polite"
                    >
                      {steps.map((step, index) => (
                        <li key={step.id} className="step-enter relative flex gap-3 pb-3.5 last:pb-0">
                          {index < steps.length - 1 && (
                            <span className="absolute left-[9px] top-5 h-full w-px bg-line" />
                          )}
                          <span className="relative z-10 mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-full bg-white text-[9.5px] text-brand-ink">
                            {STEP_ICON[step.step_type]}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[11px] font-bold text-ink">{step.step_type}</span>
                              {step.tool_name && (
                                <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-muted">
                                  {step.tool_name}
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-[12.5px] leading-snug text-ink">{step.message}</p>
                          </div>
                        </li>
                      ))}
                      {status === "running" && (
                        <li className="flex items-center gap-2 pl-7 pt-2 text-[11.5px] text-faint">
                          <span className="flex gap-1">
                            <span className="dot-bounce size-2 rounded-full bg-brand [animation-delay:-0.3s]" />
                            <span className="dot-bounce size-2 rounded-full bg-brand [animation-delay:-0.15s]" />
                            <span className="dot-bounce size-2 rounded-full bg-brand" />
                          </span>
                          다음 판단을 이어가는 중…
                        </li>
                      )}
                    </ol>
                  )}
                </div>
              )}

              {failedCount > 0 && status === "ready" && (
                <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-[11.5px] leading-relaxed text-red-600">
                  {failedCount}건은 읽지 못했어요. 완료 후 실패한 파일을 다시 올려 주세요.
                </p>
              )}

              {status === "error" && (
                <div className="mt-5 rounded-2xl bg-red-50 p-4 text-red-600">
                  <div className="flex gap-2">
                    <AlertCircle size={17} className="mt-0.5 shrink-0" />
                    <p className="text-[12.5px] leading-relaxed">{error}</p>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button type="button" onClick={close} className="rounded-xl bg-white py-2.5 text-[12.5px] font-bold text-muted">
                      닫기
                    </button>
                    <button type="button" onClick={retry} className="rounded-xl bg-brand py-2.5 text-[12.5px] font-bold text-white">
                      다시 시도
                    </button>
                  </div>
                </div>
              )}

              {status === "all_failed" && (
                <div className="mt-5 rounded-2xl bg-red-50 p-4">
                  <div className="flex gap-2 text-red-600">
                    <AlertCircle size={17} className="mt-0.5 shrink-0" />
                    <div>
                      <p className="text-[12.5px] font-bold">업로드 자료를 등록하지 못했어요.</p>
                      {submissionErrors.map((message) => (
                        <p key={message} className="mt-1 text-[11.5px] leading-relaxed">
                          {message}
                        </p>
                      ))}
                      {failed.map((job) => (
                        <p key={job.job_id} className="mt-1 text-[11.5px] leading-relaxed">
                          {job.original_filename}: {job.error_message ?? "처리에 실패했어요."}
                        </p>
                      ))}
                    </div>
                  </div>
                  <button type="button" onClick={close} className="mt-3 w-full rounded-xl bg-white py-2.5 text-[12.5px] font-bold text-muted">
                    닫기
                  </button>
                </div>
              )}

              {status === "ready" && (
                <button
                  type="button"
                  onClick={() => setPhase("review")}
                  className="btn-cta mt-5 w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-bold text-white"
                >
                  다음
                </button>
              )}
            </div>
          )}

          {phase === "review" && (
            <div className="step-enter">
              <h2 className="text-[20px] font-extrabold leading-snug text-ink">
                추가 확인이 필요한 항목은
                <br />
                담당자가 검토할 예정이에요
              </h2>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                신뢰도가 낮거나 계산 근거가 부족한 항목만 안전하게 담당자 검토 목록으로 넘겼어요.
              </p>

              {reviewItems.length > 0 ? (
                <div className="mt-5 space-y-2.5">
                  {reviewItems.map((item) => (
                    <div key={item.voucher_id} className="rounded-2xl border border-hitl/40 bg-hitl/10 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-[13px] font-bold text-ink">{item.item_description}</p>
                          <p className="mt-1 text-[11.5px] text-muted">
                            {item.year}년 {item.month}월
                            {item.supplier_name ? ` · ${item.supplier_name}` : ""}
                          </p>
                        </div>
                        <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-[10.5px] font-bold text-hitl-ink">
                          {item.confidence === null
                            ? "추가 확인"
                            : `신뢰도 ${Math.round(item.confidence * 100)}%`}
                        </span>
                      </div>
                      <p className="mt-2 text-[11.5px] leading-relaxed text-hitl-ink">{item.reason_text}</p>
                    </div>
                  ))}
                </div>
              ) : !reviewLoadFailed ? (
                <div className="mt-5 rounded-2xl bg-brand-soft p-5 text-center">
                  <span className="mx-auto grid size-9 place-items-center rounded-full bg-white text-brand-ink">
                    <Check size={19} />
                  </span>
                  <p className="mt-3 text-[13px] font-bold text-brand-ink">담당자 검토가 필요한 항목이 없어요.</p>
                  <p className="mt-1 text-[11.5px] text-muted">AI가 새 자료를 안정적으로 분류했어요.</p>
                </div>
              ) : null}

              {reviewLoadFailed && (
                <div className="mt-3 rounded-xl bg-red-50 px-3 py-2.5 text-red-600">
                  <p className="text-[11.5px] leading-relaxed">
                    일부 검토 결과를 확인하지 못했어요. 담당자 검토 등록 상태는 그대로 유지돼요.
                  </p>
                  <button
                    type="button"
                    onClick={() => void retryReviewStatuses()}
                    disabled={reviewReloading}
                    className="mt-2 rounded-lg bg-white px-3 py-1.5 text-[11.5px] font-bold disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {reviewReloading ? "다시 확인하는 중…" : "검토 결과 다시 확인"}
                  </button>
                </div>
              )}

              <div className="mt-4 rounded-xl bg-bg px-3.5 py-3 text-[12px] leading-relaxed text-muted">
                검토가 끝난 항목은 담당자가 확인한 뒤 사장님 화면에 전달해 드려요.
              </div>
              <button
                type="button"
                onClick={() => setPhase("stamp")}
                className="btn-cta mt-5 w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-bold text-white"
              >
                다음
              </button>
            </div>
          )}

          {phase === "stamp" && (
            <div className="step-enter text-center">
              <h2 className="text-[23px] font-extrabold leading-snug text-ink">
                도장 꾹!
                <br />
                업로드가 완료됐어요!
              </h2>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">{completedMessage}</p>

              <div className="relative mx-auto mt-2 h-64 max-w-xs">
                <Image
                  src="/dandi_17.png"
                  alt=""
                  width={267}
                  height={267}
                  className="absolute bottom-0 left-1/2 h-56 w-auto -translate-x-1/2 object-contain"
                />
                <Image
                  src="/carbon_stamp.png"
                  alt="업로드 완료 도장"
                  width={112}
                  height={112}
                  className="stamp-enter absolute right-3 top-3 h-28 w-28 -rotate-6 object-contain drop-shadow-lg"
                  priority
                />
              </div>

              {failedCount > 0 && (
                <p className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-[11.5px] leading-relaxed text-red-600">
                  함께 선택한 파일 중 {failedCount}건은 등록하지 못했어요. 닫은 뒤 다시 올려 주세요.
                </p>
              )}
              <button
                type="button"
                onClick={close}
                className="btn-cta w-full rounded-2xl bg-brand py-3.5 text-[14.5px] font-bold text-white"
              >
                확인
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
