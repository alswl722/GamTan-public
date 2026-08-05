"use client";

/**
 * 관리자 대시보드 — 은행 ESG·여신 담당자 화면.
 * 실데이터: 포트폴리오 집계·담당자 검토 큐·실행 이력·이상 신호 알림 (백엔드 실제 응답).
 * 목업(예시): 우대금리·검증 오차율 (결선 확장 — 화면에 '예시' 표식).
 */
import { useCallback, useEffect, useState } from "react";
import { getAlerts, getHitl, getPortfolio, getTraceRuns } from "@/lib/admin-data";
import type { AlertItem, HitlItem, PortfolioResponse, TraceRunItem } from "@/lib/admin-types";
import { DashboardShell } from "@/components/admin/DashboardShell";

type Data = {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
  traceRuns: TraceRunItem[];
  alerts: AlertItem[];
};

export default function AdminPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    setData(null);
    Promise.all([getPortfolio(), getHitl(), getTraceRuns(), getAlerts()])
      .then(([portfolio, hitlQueue, traceRuns, alerts]) =>
        setData({ portfolio, hitlQueue, traceRuns, alerts }),
      )
      .catch((err) => {
        console.error("대시보드 데이터 조회 실패:", err);
        setError(true);
      });
  }, []);

  useEffect(load, [load]);

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
      alerts={data.alerts}
    />
  );
}
