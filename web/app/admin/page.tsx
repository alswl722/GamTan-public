"use client";

/**
 * 관리자 대시보드 — 은행 ESG·여신 담당자 화면.
 * 실데이터: 포트폴리오 집계·담당자 검토 큐 (백엔드 실제 응답).
 * 이상 신호 알림은 "기업" 탭(CompanyDetail)이 GET /admin/companies/{id}/overview로
 * 기업별 자체 조회한다 — 최초 로딩에는 포함하지 않는다.
 * 실행 이력·변경 이력·원본문서 접근 로그·품질 이슈 로그는 각자 서버사이드
 * 페이지네이션으로 자체 조회한다(DashboardShell 하위 컴포넌트) — 계속 쌓이는
 * 로그 테이블이라 최초 로딩에 전량을 포함하지 않는다.
 */
import { useCallback, useEffect, useState } from "react";
import { getHitl, getPortfolio } from "@/lib/admin-data";
import type { HitlItem, PortfolioResponse } from "@/lib/admin-types";
import { DashboardShell } from "@/components/admin/DashboardShell";

type Data = {
  portfolio: PortfolioResponse;
  hitlQueue: HitlItem[];
};

export default function AdminPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    setData(null);
    Promise.all([getPortfolio(), getHitl()])
      .then(([portfolio, hitlQueue]) => setData({ portfolio, hitlQueue }))
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
    <DashboardShell portfolio={data.portfolio} hitlQueue={data.hitlQueue} />
  );
}
