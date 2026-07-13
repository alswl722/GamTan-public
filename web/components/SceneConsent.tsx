"use client";

import { useState } from "react";
import { apiPost, COMPANY_ID } from "@/lib/api";

/** 장면 ① — 마이데이터 연동 동의. 버튼 클릭 → Mock API 로 실제 전표 수집. */

type CollectResult = { source: string; count: number; vouchers: unknown[] };

export function SceneConsent() {
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );
  const [hometax, setHometax] = useState(0);
  const [kepco, setKepco] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const total = hometax + kepco;

  async function connect() {
    setStatus("loading");
    setError(null);
    try {
      const [ht, kp] = await Promise.all([
        apiPost<CollectResult>(`/mock/hometax/${COMPANY_ID}`),
        apiPost<CollectResult>(`/mock/kepco/${COMPANY_ID}`),
      ]);
      setHometax(ht.count);
      setKepco(kp.count);
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "수집 실패");
      setStatus("error");
    }
  }

  const pct = status === "done" ? 100 : status === "loading" ? 60 : 0;

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">① 마이데이터 연동 동의</h2>
        {status === "done" && (
          <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
            연동 완료
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        클릭 1회로 홈택스 세금계산서 · 한전 전기요금 고지서를 자동 수집합니다.
        입력 제로.
      </p>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <div className="rounded-lg border border-line bg-bg p-5">
          <div className="text-sm font-medium text-muted">
            ○○정밀 (구미 · 금속가공 · 12명)
          </div>
          <button
            type="button"
            onClick={connect}
            disabled={status === "loading"}
            className="mt-4 w-full rounded-lg bg-brand px-5 py-3 text-sm font-semibold text-white hover:bg-brand-ink disabled:opacity-60"
          >
            {status === "loading"
              ? "수집 중…"
              : status === "done"
                ? "다시 수집"
                : "마이데이터 연동에 동의하고 시작하기"}
          </button>
          <div className="mt-3 text-center text-[11px] text-muted">
            홈택스 · 한전과 동일 스키마의 Mock API (데모)
          </div>
          {error && (
            <div className="mt-3 rounded-md bg-hitl/10 p-2 text-center text-[11px] text-hitl">
              {error} · API 서버(8000)가 켜져 있는지 확인
            </div>
          )}
        </div>

        <div className="rounded-lg border border-line p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">전표 수집 진행</span>
            <span className="text-muted tabular-nums">
              {total} / {total || "—"}건
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-brand transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <ul className="mt-4 space-y-2 text-sm">
            <li className="flex items-center justify-between">
              <span className="text-muted">홈택스 세금계산서</span>
              <span className="font-medium text-scope1 tabular-nums">
                {hometax}건
              </span>
            </li>
            <li className="flex items-center justify-between">
              <span className="text-muted">한전 전기 고지서</span>
              <span className="font-medium text-scope2 tabular-nums">
                {kepco}건
              </span>
            </li>
          </ul>
          {status === "idle" && (
            <p className="mt-3 text-[11px] text-muted">
              왼쪽 버튼을 눌러 실제 수집을 시작하세요.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
