"use client";

/**
 * 관리자 대시보드 — 은행 ESG·여신 담당자 화면.
 * 실데이터: 포트폴리오 집계·담당자 검토 큐·실행 이력·이상 신호 알림·등급 상승 후보 (백엔드 실제 응답).
 * 목업(예시): 검증 오차율 (결선 확장 — 화면에 '예시' 표식).
 */
import { useCallback, useEffect, useState } from "react";
import {
  getAlerts,
  getHitl,
  getPortfolio,
  getRateCandidates,
  getReviewLog,
  getTraceRuns,
} from "@/lib/admin-data";
import type {
  AlertItem,
  HitlItem,
  PortfolioResponse,
  RateCandidateItem,
  ReviewLogEntry,
  TraceRunItem,
} from "@/lib/admin-types";
import { DashboardShell } from "@/components/admin/DashboardShell";

type Data = {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
  reviewLog: ReviewLogEntry[];
  alerts: AlertItem[];
  rateCandidates: RateCandidateItem[];
};

export default function AdminPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    setData(null);
    Promise.all([
      getPortfolio(),
      getHitl(),
      getTraceRuns(),
      getReviewLog(),
      getAlerts(),
      getRateCandidates(),
    ])
      .then(([portfolio, hitlQueue, traceRuns, reviewLog, alerts, rateCandidates]) =>
        setData({ portfolio, hitlQueue, traceRuns, reviewLog, alerts, rateCandidates }),
      )
      .catch((err) => {
        console.error("대시보드 데이터 조회 실패:", err);
        setError(true);
      });
  }, []);

  useEffect(load, [load]);

  /** 검토 조치 후 변경 이력만 조용히 다시 불러온다 — 전체 재로딩(깜빡임) 없이 최신 상태 유지. */
  const refreshReviewLog = useCallback(() => {
    getReviewLog()
      .then((reviewLog) => setData((prev) => (prev ? { ...prev, reviewLog } : prev)))
      .catch((err) => console.error("변경 이력 갱신 실패:", err));
  }, []);

  if (error) {
    return (
      <div className="mx-auto grid max-w-md flex-1 place-items-center px-5">
        <div className="text-center">
          <div className="mb-3 rounded-xl bg-hitl/20 px-4 py-3 text-sm text-hitl-ink">
            대시보드 데이터를 불러오지 못했습니다. 서버 연결을 확인해 주세요.
          </div>
          <button
            type="button"
            onClick={load}
            className="rounded-xl bg-brand px-5 py-2.5 text-sm font-bold text-white hover:bg-brand-ink"
          >
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="grid flex-1 place-items-center text-sm text-muted">대시보드 불러오는 중…</div>
    );
  }

  return (
    <DashboardShell
      portfolio={data.portfolio}
      hitlQueue={data.hitlQueue}
      traceRuns={data.traceRuns}
      reviewLog={data.reviewLog}
      alerts={data.alerts}
      rateCandidates={data.rateCandidates}
      onReviewed={refreshReviewLog}
    />
  );
}
