"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch } from "@/lib/api";

/** HITL 검토 큐 — 저신뢰 분류 건을 담당자가 확인·확정(보조수단성 원칙).
 *  AI는 1차 스크리닝만, 최종 확정은 사람이 한다. */

type Item = {
  voucher_id: number;
  company_id: number;
  company_name: string;
  raw: string;
  scope: 1 | 2 | null;
  category: string | null;
  fuel: string | null;
  amount_krw: number | null;
  confidence: number;
  evidence: string | null;
  method: "rule" | "llm";
  month: number;
};

export function HitlQueue() {
  const [queue, setQueue] = useState<Item[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [rowError, setRowError] = useState<number | null>(null);

  function load() {
    setStatus("loading");
    apiGet<{ queue: Item[] }>("/admin/hitl")
      .then((r) => {
        setQueue(r.queue);
        setStatus("ready");
      })
      .catch((err) => {
        console.error("HITL 큐 조회 실패:", err);
        setStatus("error");
      });
  }

  useEffect(load, []);

  async function confirm(voucherId: number) {
    setConfirming(voucherId);
    setRowError(null);
    try {
      await apiPatch(`/admin/classifications/${voucherId}/confirm`);
      // 확정된 건은 큐에서 즉시 제거 (review_required → confirmed)
      setQueue((prev) => prev.filter((i) => i.voucher_id !== voucherId));
    } catch (err) {
      console.error("확정 실패:", err);
      setRowError(voucherId);
    } finally {
      setConfirming(null);
    }
  }

  return (
    <div className="rounded-2xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[16px] font-bold text-ink">HITL 검토 큐</h2>
          <p className="mt-0.5 text-[12.5px] text-muted">
            신뢰도가 낮아 사람 확인이 필요한 분류 건
          </p>
        </div>
        <span className="rounded-full bg-hitl/25 px-2.5 py-1 text-[11.5px] font-bold text-hitl-ink">
          {queue.length}건 대기
        </span>
      </div>

      {status === "loading" && (
        <div className="mt-5 grid h-24 place-items-center text-[13px] text-muted">
          검토 큐 조회 중…
        </div>
      )}

      {status === "error" && (
        <div className="mt-5">
          <div className="mb-3 rounded-xl bg-hitl/25 px-3 py-2 text-[12px] text-hitl-ink">
            검토 큐를 불러오지 못했습니다. 서버 연결을 확인해 주세요.
          </div>
          <button
            type="button"
            onClick={load}
            className="rounded-xl bg-brand px-4 py-2 text-[13px] font-bold text-white hover:bg-brand-ink"
          >
            다시 시도
          </button>
        </div>
      )}

      {status === "ready" && queue.length === 0 && (
        <div className="mt-5 grid h-24 place-items-center rounded-xl border border-dashed border-line bg-bg text-[13px] text-muted">
          검토 대기 건이 없습니다 — 모두 확정되었습니다
        </div>
      )}

      {status === "ready" && queue.length > 0 && (
        <div className="mt-4 space-y-2">
          {queue.map((i) => {
            const open = expanded === i.voucher_id;
            return (
              <div
                key={i.voucher_id}
                className="rounded-xl bg-bg ring-1 ring-hitl/30"
              >
                <div className="flex items-start justify-between gap-3 p-3.5">
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : i.voucher_id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono text-[13px] font-semibold text-ink">
                        “{i.raw}”
                      </span>
                      <span className="rounded-md border border-line px-1.5 py-0.5 text-[10.5px] text-muted">
                        {i.company_name} · {i.month}월
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                      <span className="rounded-md bg-hitl/20 px-1.5 py-0.5 font-semibold text-hitl-ink">
                        신뢰도 {i.confidence.toFixed(2)}
                      </span>
                      {i.fuel && (
                        <span className="rounded-md border border-line px-1.5 py-0.5 text-muted">
                          {i.fuel}
                        </span>
                      )}
                      <span className="tabular-nums text-faint">
                        {(i.amount_krw ?? 0).toLocaleString()}원
                      </span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => confirm(i.voucher_id)}
                    disabled={confirming === i.voucher_id}
                    className="shrink-0 rounded-lg bg-brand px-3.5 py-2 text-[12.5px] font-bold text-white transition-colors hover:bg-brand-ink disabled:opacity-60"
                  >
                    {confirming === i.voucher_id ? "확정 중…" : "확정"}
                  </button>
                </div>

                {rowError === i.voucher_id && (
                  <div className="border-t border-line px-3.5 py-2 text-[11.5px] text-hitl-ink">
                    확정에 실패했습니다. 다시 시도해 주세요.
                  </div>
                )}

                {open && (
                  <div className="step-enter border-t border-line px-3.5 py-2.5 text-[12px] leading-relaxed text-muted">
                    <span className="font-semibold text-ink">판단 근거</span> ·{" "}
                    {i.evidence ?? "근거 없음"}
                    <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[10px] text-faint">
                      {i.method === "rule" ? "룰 매칭" : "Gemini"}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-4 text-[11px] leading-relaxed text-faint">
        ⓘ 확정은 분류 값을 바꾸지 않고 ‘사람이 확인함’만 기록합니다 — 금융분야 AI
        가이드라인의 보조수단성 원칙(AI는 1차 스크리닝, 최종 판단은 사람).
      </p>
    </div>
  );
}
