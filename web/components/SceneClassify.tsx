"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, getCompanyId } from "@/lib/api";
import { AnomalyCheckCard } from "@/components/AnomalyCheckCard";

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
};

/** results 는 담당자가 확정한 건만 담긴다 — 검토 대기(HITL) 건은 담당자 확정
 * 전까지 상세를 사장님에게 보여주지 않고 hitl_pending_count(건수)로만 안내한다. */
type ClassifyResponse = { results: Row[]; hitl_pending_count: number };
type ProgressResponse = { done: number; total: number; finished: boolean };

function ScopeTag({ scope }: { scope: 1 | 2 | null }) {
  if (scope === null) {
    return (
      <span className="rounded-md bg-hitl/25 px-2 py-0.5 text-[11.5px] font-bold text-hitl-ink">
        Scope 미정
      </span>
    );
  }
  const cls = scope === 1 ? "text-ink bg-scope1/25" : "text-ink bg-scope2/25";
  return (
    <span className={`rounded-md px-2 py-0.5 text-[11.5px] font-bold ${cls}`}>
      Scope {scope}
    </span>
  );
}

function ClassifyProgressRing({
  progress,
}: {
  progress: ProgressResponse | null;
}) {
  const pct =
    progress && progress.total > 0
      ? Math.round((progress.done / progress.total) * 100)
      : 0;
  const r = 40;
  const circumference = 2 * Math.PI * r;

  return (
    <div className="relative grid h-[104px] w-[104px] place-items-center">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 96 96">
        <circle
          cx="48"
          cy="48"
          r={r}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth="7"
        />
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
      <span className="text-[20px] font-extrabold tabular-nums text-ink">
        {pct}%
      </span>
    </div>
  );
}

function ClassificationCard({
  row,
  open,
  onToggle,
}: {
  row: Row;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-xl bg-surface shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-float">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-col gap-1.5 p-3.5 text-left"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[13px] font-semibold text-ink">
              {row.raw}
            </span>
          </div>
          <span className="text-[13px] font-semibold tabular-nums text-ink">
            {(row.amount_krw ?? 0).toLocaleString()}원
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
          <ScopeTag scope={row.scope} />
        </div>
      </button>

      {open && (
        <div className="step-enter border-t border-line px-3.5 py-2.5 text-[12px] leading-relaxed text-muted">
          <span className="font-semibold text-ink">판단 근거</span> ·{" "}
          {row.evidence ?? "근거 없음"}
          <span className="ml-2 rounded-md border border-line px-1.5 py-0.5 text-[10px] text-faint">
            {row.method === "rule" ? "룰 매칭" : "Gemini"}
          </span>
        </div>
      )}
    </div>
  );
}

export function SceneClassify({ onNext }: { onNext: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [hitlCount, setHitlCount] = useState(0);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [showAuto, setShowAuto] = useState(false);

  useEffect(() => {
    let alive = true;
    getCompanyId()
      .then((cid) => apiGet<ClassifyResponse>(`/classify/${cid}`))
      .then((res) => {
        if (!alive) return;
        // 확정 건 + 검토 대기 건수를 합쳐 "이미 분류가 실행된 적 있는지" 판단한다 —
        // 전량이 검토 대기라 results가 비어 있어도 재실행하면 안 된다.
        if (res.results.length > 0 || res.hitl_pending_count > 0) {
          setRows(res.results);
          setHitlCount(res.hitl_pending_count);
          setStatus("done");
        } else {
          // 처음 진입 시 — 버튼 없이 화면 진입과 동시에 바로 분류 시작
          runClassification();
        }
      })
      .catch((err) => {
        // StrictMode 이중 마운트에서 이중 실행되지 않도록 alive 확인 후 시도
        if (!alive) return;
        console.error("분류 결과 조회 실패:", err);
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

    let poll: ReturnType<typeof setInterval> | null = null;
    try {
      const cid = await getCompanyId();
      poll = setInterval(() => {
        apiGet<ProgressResponse>(`/classify/progress/${cid}`)
          .then((p) => {
            if (p.total > 0) setProgress(p);
          })
          .catch(() => {});
      }, 800);

      const res = await apiPost<ClassifyResponse>(`/classify/${cid}`);
      setRows(res.results);
      setHitlCount(res.hitl_pending_count);
      setStatus("done");
    } catch (err) {
      console.error("분류 실행 실패:", err);
      setError(
        "분류 실행에 실패했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.",
      );
      setStatus("error");
    } finally {
      if (poll) clearInterval(poll);
      setProgress(null);
    }
  }

  const autoRows = rows;

  return (
    <section>
      <h2 className="text-[17px] font-bold leading-snug text-ink">
        해당 항목들은
        <br />
        담당자가 검토할 예정이에요
      </h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">
        신뢰도가 낮은 항목들은 은행 담당자가 검토해요.
        <br />
        카드를 눌러 상세 내용을 확인할 수 있어요.
      </p>

      {rows.length === 0 && status === "loading" && (
        <div className="mt-6 flex flex-col items-center rounded-2xl bg-surface p-8 text-center">
          <ClassifyProgressRing progress={progress} />
          <p className="mt-4 flex items-center gap-2 text-[13px] font-semibold text-ink">
            {progress && progress.total > 0
              ? `전표 ${progress.done} / ${progress.total}건 분류 중…`
              : "분류 준비 중…"}
            <span className="flex gap-1">
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.3s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand [animation-delay:-0.15s]" />
              <span className="dot-bounce h-1.5 w-1.5 rounded-full bg-brand" />
            </span>
          </p>
          <p className="mt-1 text-[12px] text-faint">
            룰 매칭 → 애매한 건만 Gemini 병렬 호출 → 저신뢰 건은 은행 담당자에게
            전달
          </p>
        </div>
      )}

      {rows.length === 0 && status === "error" && (
        <div className="mt-6 rounded-2xl border border-dashed border-line bg-surface p-8 text-center">
          <div className="mb-3 rounded-xl bg-hitl/25 px-3 py-2 text-[12px] text-hitl-ink">
            {error}
          </div>
          <button
            type="button"
            onClick={runClassification}
            className="btn-cta rounded-2xl bg-brand px-6 py-3.5 text-[14.5px] font-bold text-white"
          >
            다시 시도
          </button>
        </div>
      )}

      {(rows.length > 0 || hitlCount > 0) && (
        <>
          {hitlCount > 0 && (
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-hitl/20 px-3.5 py-2.5 text-[12px] font-semibold text-hitl-ink">
              <span className="h-1.5 w-1.5 rounded-full bg-hitl-ink" />
              {hitlCount}건은 신뢰도가 낮아 은행 담당자가 검토 중이에요. 검토가
              끝나면 이 화면에 자동으로 반영돼요.
            </div>
          )}

          <AnomalyCheckCard />

          {autoRows.length > 0 && (
            <div className={hitlCount > 0 ? "mt-3" : "mt-4"}>
              <button
                type="button"
                onClick={() => setShowAuto((v) => !v)}
                className="flex w-full items-center justify-between rounded-2xl border border-line bg-surface px-4 py-4 text-[14.5px] font-bold text-ink shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-float"
              >
                <span className="flex items-center gap-2">
                  <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-soft text-[12px] font-extrabold text-brand-ink">
                    {autoRows.length}
                  </span>
                  확정 {autoRows.length}건 {showAuto ? "접기" : "보기"}
                </span>
                <span
                  className={`text-[14px] text-muted transition-transform duration-200 ${showAuto ? "rotate-180" : ""}`}
                >
                  ▾
                </span>
              </button>
              {showAuto && (
                <div className="step-enter mt-2 max-h-[380px] space-y-2 overflow-y-auto">
                  {autoRows.map((r) => (
                    <ClassificationCard
                      key={r.voucher_id}
                      row={r}
                      open={expanded === r.voucher_id}
                      onToggle={() =>
                        setExpanded(
                          expanded === r.voucher_id ? null : r.voucher_id,
                        )
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={onNext}
            className="btn-cta mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
          >
            리포트 확인하러 가기
          </button>
        </>
      )}
    </section>
  );
}
