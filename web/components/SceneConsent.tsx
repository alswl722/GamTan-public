"use client";

import { useState } from "react";
import { apiPost, getCompanyId } from "@/lib/api";

/** 장면 ① — 마이데이터 연동 동의. 버튼 클릭 → Mock API 로 실제 전표 수집. */

type CollectResult = { source: string; count: number; vouchers: unknown[] };
type Phase = "consent" | "collecting" | "done" | "error";
type SourceStatus = "waiting" | "loading" | "done";

const SOURCES = [
  { key: "hometax", badge: "홈", name: "홈택스 세금계산서" },
  { key: "kepco", badge: "한", name: "한국전력 고지서" },
] as const;

export function SceneConsent({ onNext }: { onNext: () => void }) {
  const [phase, setPhase] = useState<Phase>("consent");
  const [agreed, setAgreed] = useState(true);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [sourceStatus, setSourceStatus] = useState<
    Record<string, SourceStatus>
  >({ hometax: "waiting", kepco: "waiting" });
  const [error, setError] = useState<string | null>(null);

  const total = (counts.hometax ?? 0) + (counts.kepco ?? 0);
  const doneCount = Object.values(sourceStatus).filter((s) => s === "done")
    .length;
  const progressPct = Math.round((doneCount / SOURCES.length) * 100);

  async function connect() {
    setPhase("collecting");
    setError(null);
    setSourceStatus({ hometax: "waiting", kepco: "waiting" });
    try {
      const cid = await getCompanyId();
      setSourceStatus((s) => ({ ...s, hometax: "loading" }));
      const ht = await apiPost<CollectResult>(`/mock/hometax/${cid}`);
      setCounts((c) => ({ ...c, hometax: ht.count }));
      setSourceStatus((s) => ({ ...s, hometax: "done", kepco: "loading" }));

      const kp = await apiPost<CollectResult>(`/mock/kepco/${cid}`);
      setCounts((c) => ({ ...c, kepco: kp.count }));
      setSourceStatus((s) => ({ ...s, kepco: "done" }));

      setPhase("done");
    } catch (err) {
      console.error("마이데이터 수집 실패:", err);
      setError("데이터 수집에 실패했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
      setPhase("error");
    }
  }

  if (phase === "consent") {
    return (
      <section className="pt-4">
        <h2 className="text-[21px] font-bold leading-snug text-ink">
          전표만 연동하면
          <br />
          탄소 측정이 끝나요
        </h2>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">
          홈택스·한전 데이터를 감탄 AI가 대신 읽어
          <br />
          탄소 배출량을 자동으로 산정합니다.
        </p>

        <div className="mt-6 space-y-2.5">
          {SOURCES.map((s) => (
            <div
              key={s.key}
              className="flex items-center gap-3.5 rounded-2xl bg-surface p-4"
            >
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-[14px] font-bold text-brand-ink">
                {s.badge}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[14.5px] font-bold text-ink">
                  {s.name.split(" ")[0]}
                </div>
                <div className="text-[12.5px] text-muted">
                  {s.key === "hometax"
                    ? "세금계산서 12개월치 자동 수집"
                    : "전기요금 고지서 자동 수집"}
                </div>
              </div>
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand text-white">
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M3 8.5L6.2 11.5L13 4.5"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
            </div>
          ))}
        </div>

        <label className="mt-5 flex items-center gap-2.5 text-[13.5px] font-medium text-ink">
          <button
            type="button"
            role="checkbox"
            aria-checked={agreed}
            onClick={() => setAgreed((v) => !v)}
            className={`grid h-5 w-5 shrink-0 place-items-center rounded-md transition-colors ${
              agreed ? "bg-brand" : "bg-line"
            }`}
          >
            {agreed && (
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <path
                  d="M3 8.5L6.2 11.5L13 4.5"
                  stroke="white"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
          마이데이터 제공·활용에 동의합니다
        </label>

        <button
          type="button"
          onClick={connect}
          disabled={!agreed}
          className="btn-cta mt-4 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
        >
          동의하고 연동 시작
        </button>
        <p className="mt-3 text-center text-[11.5px] text-faint">
          클릭 1회로 홈택스·한전 수집이 시작됩니다
        </p>
      </section>
    );
  }

  return (
    <section className="pt-4">
      <div className="flex flex-col items-center text-center">
        <div className="relative grid h-40 w-40 place-items-center">
          <svg
            className="absolute inset-0 -rotate-90"
            viewBox="0 0 100 100"
          >
            <circle
              cx="50"
              cy="50"
              r="44"
              fill="none"
              stroke="var(--color-line)"
              strokeWidth="8"
            />
            <circle
              cx="50"
              cy="50"
              r="44"
              fill="none"
              stroke="var(--color-brand)"
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={2 * Math.PI * 44}
              strokeDashoffset={2 * Math.PI * 44 * (1 - progressPct / 100)}
              style={{ transition: "stroke-dashoffset 0.5s ease-out" }}
            />
          </svg>
          <span className="text-[32px] font-extrabold tabular-nums text-ink">
            {progressPct}%
          </span>
        </div>

        <h2 className="mt-5 text-[17px] font-bold text-ink">
          감탄이 전표를 읽고 있어요
        </h2>
        <p className="mt-1 text-[13px] text-muted">
          12개월치를 정리하는 중입니다
        </p>
      </div>

      <div className="mt-7 space-y-2">
        {SOURCES.map((s) => {
          const st = sourceStatus[s.key];
          return (
            <div
              key={s.key}
              className={`flex items-center gap-3.5 rounded-2xl bg-surface p-4 ${
                st === "loading" ? "ring-1 ring-brand/40" : ""
              }`}
            >
              {st === "done" ? (
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand text-white">
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M3 8.5L6.2 11.5L13 4.5"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
              ) : st === "loading" ? (
                <span className="h-6 w-6 shrink-0 animate-spin rounded-full border-2 border-line border-t-brand" />
              ) : (
                <span className="h-6 w-6 shrink-0 rounded-full border-2 border-line" />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-bold text-ink">{s.name}</div>
                <div className="text-[12px] text-muted">
                  {st === "done"
                    ? `${counts[s.key] ?? 0}건 수집 완료`
                    : st === "loading"
                      ? "수집 중…"
                      : "대기 중"}
                </div>
              </div>
              <span
                className={`text-[12.5px] font-bold ${
                  st === "done"
                    ? "text-brand-ink"
                    : st === "loading"
                      ? "text-ink"
                      : "text-faint"
                }`}
              >
                {st === "done" ? "완료" : st === "loading" ? "진행" : "대기"}
              </span>
            </div>
          );
        })}

        <div className="flex items-center gap-3.5 rounded-2xl bg-surface p-4 opacity-60">
          <span className="h-6 w-6 shrink-0 rounded-full border-2 border-line" />
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-bold text-ink">AI 분류</div>
            <div className="text-[12px] text-muted">수집 완료 후 시작</div>
          </div>
          <span className="text-[12.5px] font-bold text-faint">대기</span>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-hitl/25 px-3.5 py-2.5 text-[12.5px] text-hitl-ink">
          {error}
        </div>
      )}

      {phase === "done" ? (
        <button
          type="button"
          onClick={onNext}
          className="btn-cta mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
        >
          연동 완료 · 다음으로 ({total}건)
        </button>
      ) : phase === "error" ? (
        <button
          type="button"
          onClick={connect}
          className="btn-cta mt-6 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
        >
          다시 시도
        </button>
      ) : (
        <p className="mt-6 text-center text-[12.5px] text-faint">
          사장님은 기다리기만 하면 됩니다
        </p>
      )}
    </section>
  );
}
