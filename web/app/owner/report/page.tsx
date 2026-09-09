"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ScenePcaf } from "@/components/ScenePcaf";
import { getCompanyId, getOwnerProgress, type OwnerProgress } from "@/lib/api";

/** 하단바 "탄소 리포트" 탭 — 위저드(/owner/measure) 없이 해당 기업의 최신 PCAF
 * 리포트만 바로 보여준다. 측정을 아직 안 끝낸 기업은 리포트 대신 위저드로
 * 유도하는 안내를 보여준다(steps.report는 classify_done과 동일 조건,
 * api/queries.py::get_owner_progress). */
export default function OwnerReportPage() {
  const [progress, setProgress] = useState<OwnerProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    setProgress(null);
    getCompanyId()
      .then((cid) => getOwnerProgress(cid))
      .then(setProgress)
      .catch((err) => {
        console.error("진행 상태 조회 실패:", err);
        setError("진행 상태를 불러오지 못했습니다. 서버 연결 상태를 확인한 뒤 다시 시도해 주세요.");
      });
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-5 pb-16">
      <div className="pt-5">
        <Link
          href="/owner"
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-faint transition-colors hover:text-ink"
        >
          ← 홈으로
        </Link>
      </div>

      <h1 className="mt-4 text-[17px] font-bold leading-snug text-ink">탄소 리포트</h1>

      <div className="mt-3 flex-1">
        {error ? (
          <>
            <div className="rounded-xl bg-red-50 px-4 py-3 text-[12.5px] leading-relaxed text-red-600">
              {error}
            </div>
            <button
              type="button"
              onClick={load}
              className="btn-cta mt-4 w-full rounded-2xl bg-brand py-4 text-[15.5px] font-bold text-white"
            >
              다시 시도
            </button>
          </>
        ) : !progress ? (
          <p className="text-[13px] text-faint">불러오는 중…</p>
        ) : !progress.steps.report ? (
          <div className="rounded-2xl bg-surface p-5 text-center">
            <p className="text-[13.5px] font-semibold text-ink">
              아직 리포트가 생성되지 않았어요
            </p>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
              탄소 측정을 끝내면 이 자리에서 바로 리포트를 볼 수 있어요.
            </p>
            <Link
              href="/owner/measure"
              className="btn-cta mt-4 block w-full rounded-2xl bg-brand py-3.5 text-[14px] font-bold text-white"
            >
              탄소 측정하러 가기
            </Link>
          </div>
        ) : (
          <ScenePcaf showHeading={false} />
        )}
      </div>
    </div>
  );
}
