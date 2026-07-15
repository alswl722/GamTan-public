"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, COMPANY_ID } from "@/lib/api";

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
type ProgressResponse = { done: number; total: number; finished: boolean };

function ScopeTag({ scope }: { scope: 1 | 2 | null }) {
  if (scope === null) {
    return (
      <span className="rounded-md bg-hitl/25 px-2 py-0.5 text-[11.5px] font-bold text-hitl-ink">
        Scope 미정
      </span>
    );
  }
  const cls =
    scope === 1
      ? "text-ink bg-scope1/25"
      : "text-ink bg-scope2/25";
  return (
    <span className={`rounded-md px-2 py-0.5 text-[11.5px] font-bold ${cls}`}>
      Scope {scope}
    </span>
  );
}

function ClassifyProgressRing({ progress }: { progress: ProgressResponse | null }) {
  const pct =
    progress && progress.total > 0
      ? Math.round((progress.done / progress.total) * 100)
      : 0;
  const r = 40;
  const circumference = 2 * Math.PI * r;

  return (
    <div className="relative grid h-[104px] w-[104px] place-items-center">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke="var(--color-line)" strokeWidth="7" />
        <circle
          cx="48"
          cy="48"
          r={r}
          fill="none"
          stroke="var(--color-brand)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - pct / 100)}
          style={{ transition: "stroke-dashoffset 0.4s ease-out" }}
        />
      </svg>
      <span className="text-[20px] font-extrabold tabular-nums text-ink">{pct}%</span>
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const low = value < 0.7;
  return (
    <span className="ml-auto flex items-center gap-1.5">
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-line">
        <span
          className={`block h-full ${low ? "bg-hitl-ink" : "bg-brand"}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      <span className="tabular-nums text-[11.5px] font-semibold text-muted">
        {value.toFixed(2)}
      </span>
    </span>
  );
}

export function SceneClassify({ onNext }: { onNext: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);

  useEffect(() => {
    let alive = true;
    apiGet<ClassifyResponse>(`/classify/${COMPANY_ID}`)
      .then((res) => {
        if (!alive) return;
        if (res.results.length > 0) {
          // 이미 분류된 건이 있으면(재진입) 결과만 보여줌 — 재실행 없음
          setRows(res.results);
          setStatus("done");
        } else {
          // 처음 진입 시 — 버튼 없이 화면 진입과 동시에 바로 분류 시작
          runClassification();
        }
      })
      .catch(() => {
        // 서버 미기동 등 — 조회 자체가 실패해도 진입 시 바로 실행 시도
        runClassification();
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runClassification() {
    setStatus("loading");
    setError(null);
    setProgress(null);

    const poll = setInterval(() => {
      apiGet<ProgressResponse>(`/classify/progress/${COMPANY_ID}`)
        .then((p) => {
          if (p.total > 0) setProgress(p);
        })
        .catch(() => {});
    }, 800);

    try {
      const res = await apiPost<ClassifyResponse>(`/classify/${COMPANY_ID}`);
      setRows(res.results);
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "분류 실패");
      setStatus("error");
    } finally {
      clearInterval(poll);
      setProgress(null);
    }
  }

  const hitlCount = rows.filter((r) => r.hitl).length;

  return (
    <section>
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-bg px-2.5 py-1 text-[11px] font-bold text-muted">
          킬러씬 B
        </span>
        {status === "done" && (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            실제 분류 결과
          </span>
        )}
      </div>
      <h2 className="mt-3 text-[17px] font-bold leading-snug text-ink">
        비정형 전표를 AI가 읽고 분류했어요
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">
        신뢰도가 낮으면 스스로 사람에게 넘겨요. 카드를 눌러 근거를 확인하세요.
      </p>

      {rows.length === 0 && status === "loading" && (
        <div className="mt-6 flex flex-col items-center rounded-2xl bg-surface p-8 text-center">
          <ClassifyProgressRing progress={progress} />
          <p className="mt-4 text-[13px] font-semibold text-ink">
            {progress && progress.total > 0
              ? `전표 ${progress.done} / ${progress.total}건 분류 중…`
              : "분류 준비 중…"}
          </p>
          <p className="mt-1 text-[12px] text-faint">
            룰 매칭 → 애매한 건만 Gemini 병렬 호출 → 저신뢰 건은 HITL로 이관
          </p>
        </div>
      )}

      {rows.length === 0 && status === "error" && (
        <div className="mt-6 rounded-2xl border border-dashed border-line bg-surface p-8 text-center">
          <div className="mb-3 rounded-xl bg-hitl/25 px-3 py-2 text-[12px] text-hitl-ink">
            {error} · API 서버(8000)가 켜져 있는지 확인
          </div>
          <button
            type="button"
            onClick={runClassification}
            className="rounded-2xl bg-brand px-6 py-3.5 text-[14.5px] font-bold text-white transition-colors hover:bg-brand-ink"
          >
            다시 시도
          </button>
        </div>
      )}

      {rows.length > 0 && (
        <>
          {hitlCount > 0 && (
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-hitl/20 px-3.5 py-2.5 text-[12px] font-semibold text-hitl-ink">
              <span className="h-1.5 w-1.5 rounded-full bg-hitl-ink" />
              {hitlCount}건은 신뢰도가 낮아 사람 검토(HITL)로 넘겼어요
            </div>
          )}
          <div
            className={`max-h-[380px] space-y-2 overflow-y-auto ${hitlCount > 0 ? "mt-2.5" : "mt-4"}`}
          >
            {rows.map((r) => {
              const open = expanded === r.voucher_id;
              return (
                <div
                  key={r.voucher_id}
                  className={`rounded-xl bg-surface transition-shadow ${
                    r.hitl ? "ring-1 ring-hitl/40" : ""
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : r.voucher_id)}
                    className="flex w-full flex-col gap-1.5 p-3.5 text-left"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[13px] font-semibold text-ink">
                          “{r.raw}”
                        </span>
                        {r.hitl && (
                          <span className="rounded-md bg-hitl-ink px-1.5 py-0.5 text-[10px] font-bold text-white">
                            HITL
                          </span>
                        )}
                      </div>
                      <span className="text-[13px] font-semibold tabular-nums text-ink">
                        {(r.amount_krw ?? 0).toLocaleString()}원
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
                      <ScopeTag scope={r.scope} />
                      {r.category && (
                        <span className="rounded-md border border-line px-1.5 py-0.5 text-muted">
                          {r.category}
                        </span>
                      )}
                      {r.fuel && (
                        <span className="rounded-md border border-line px-1.5 py-0.5 text-muted">
                          {r.fuel}
                        </span>
                      )}
                      <ConfidenceBar value={r.confidence} />
                    </div>
                  </button>

                  {open && (
                    <div className="step-enter border-t border-line px-3.5 py-2.5 text-[12px] leading-relaxed text-muted">
                      <span className="font-semibold text-ink">판단 근거</span>{" "}
                      · {r.evidence ?? "근거 없음"}
                      <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[10px] text-faint">
                        {r.method === "rule" ? "룰 매칭" : "Gemini"}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <button
            type="button"
            onClick={onNext}
            className="mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white transition-colors hover:bg-brand-ink"
          >
            리포트 확인하러 가기
          </button>
        </>
      )}
    </section>
  );
}
