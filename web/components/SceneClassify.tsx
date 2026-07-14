"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, COMPANY_ID } from "@/lib/api";
import { WireframeBadge } from "./WireframeBadge";

/** 장면 ③ — AI 분류 + 근거 (킬러씬 B). /classify/{id} 실데이터. */

type Row = {
  voucher_id: number;
  raw: string;
  scope: 1 | 2 | null;
  category: string | null;
  fuel: string | null;
  amount_krw: number | null;
  confidence: number;
  evidence: string | null;
  method: "rule" | "llm";
  hitl: boolean;
};

type ClassifyResponse = { results: Row[] };

function ScopeTag({ scope }: { scope: 1 | 2 | null }) {
  if (scope === null) {
    return (
      <span className="rounded bg-hitl/10 px-2 py-0.5 text-xs font-semibold text-hitl">
        Scope 미정
      </span>
    );
  }
  const cls = scope === 1 ? "text-scope1 bg-scope1/10" : "text-scope2 bg-scope2/10";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>
      Scope {scope}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const low = value < 0.7;
  return (
    <span className="ml-auto flex items-center gap-1.5">
      <span className="text-[11.5px] text-muted">신뢰도</span>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <span
          className={`block h-full ${low ? "bg-hitl" : "bg-ok"}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="tabular-nums text-[11.5px] font-medium">
        {value.toFixed(2)}
      </span>
    </span>
  );
}

export function SceneClassify() {
  const [rows, setRows] = useState<Row[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    apiGet<ClassifyResponse>(`/classify/${COMPANY_ID}`)
      .then((res) => {
        if (!alive) return;
        setRows(res.results);
        if (res.results.length > 0) setStatus("done");
      })
      .catch(() => {
        /* 서버 미기동 등 — 아래 "AI 분류 실행" 버튼으로 재시도 가능 */
      });
    return () => {
      alive = false;
    };
  }, []);

  async function runClassification() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiPost<ClassifyResponse>(`/classify/${COMPANY_ID}`);
      setRows(res.results);
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "분류 실패");
      setStatus("error");
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">
          ③ AI 분류 + 근거
          <span className="ml-2 rounded bg-scope2/10 px-2 py-0.5 text-[11px] font-bold text-scope2">
            킬러씬 B
          </span>
        </h2>
        {status === "done" ? (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            실제 분류 결과
          </span>
        ) : (
          <WireframeBadge />
        )}
      </div>
      <p className="mt-1 text-[13.5px] text-muted">
        비정형 전표를 Scope·연료로 분류하고 판단 근거를 남깁니다. 신뢰도가 낮으면
        스스로 사람 검토(HITL)로 넘깁니다.
      </p>

      {rows.length === 0 && (
        <div className="mt-[18px] rounded-lg border border-dashed border-line bg-bg p-6 text-center">
          <button
            type="button"
            onClick={runClassification}
            disabled={status === "loading"}
            className="rounded-lg bg-brand px-5 py-3 text-sm font-semibold text-white hover:bg-brand-ink disabled:opacity-60"
          >
            {status === "loading" ? "분류 중…" : "AI 분류 실행"}
          </button>
          <p className="mt-3 text-[11px] text-muted">
            룰 매칭 → 애매한 건만 Gemini 호출 → 저신뢰 건은 HITL로 이관
          </p>
          {error && (
            <div className="mt-3 rounded-md bg-hitl/10 p-2 text-[11px] text-hitl">
              {error} · API 서버(8000)가 켜져 있는지 확인
            </div>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <div className="mt-[18px] space-y-3">
          {rows.map((r) => (
            <div
              key={r.voucher_id}
              className={`rounded-lg border p-4 ${
                r.hitl ? "border-hitl/40 bg-hitl/5" : "border-line"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13.5px] font-semibold">
                    “{r.raw}”
                  </span>
                  {r.hitl && (
                    <span className="rounded bg-hitl px-2 py-0.5 text-[11px] font-bold text-white">
                      검토필요 · HITL
                    </span>
                  )}
                </div>
                <span className="text-[13.5px] tabular-nums text-muted">
                  {(r.amount_krw ?? 0).toLocaleString()}원
                </span>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]">
                <ScopeTag scope={r.scope} />
                {r.category && (
                  <span className="rounded border border-line px-2 py-0.5 text-muted">
                    {r.category}
                  </span>
                )}
                {r.fuel && (
                  <span className="rounded border border-line px-2 py-0.5 text-muted">
                    {r.fuel}
                  </span>
                )}
                <span className="rounded border border-line px-2 py-0.5 text-[11px] text-muted">
                  {r.method === "rule" ? "룰 매칭" : "Gemini"}
                </span>
                <ConfidenceBar value={r.confidence} />
              </div>

              <div className="mt-2.5 rounded-lg bg-bg px-2.5 py-2 text-[12.5px] text-muted">
                <span className="font-semibold text-ink">근거</span> ·{" "}
                {r.evidence ?? "근거 없음"}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
